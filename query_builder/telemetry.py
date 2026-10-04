"""
Query Execution & Security Audit Telemetry Engine.
==================================================
Fingerprints queries via SHA-256 hashing, collects runtime metrics in a
thread-safe ring buffer, computes real-time latency percentiles (p50/p95/p99),
records security audit events, and redacts sensitive parameters/credentials.
"""

from __future__ import annotations

import collections
import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from query_builder.security import scrub_secrets


def hash_query(sql: str) -> str:
    """Normalizes query whitespace and returns a 16-character SHA-256 fingerprint."""
    if not sql or not isinstance(sql, str):
        return ""
    normalized = re.sub(r"\s+", " ", sql.strip())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExecutionEvent:
    """Represents a recorded query execution event."""

    query_hash: str
    sql: str
    tenant_id: str | None
    user_id: str | None
    dialect: str
    latency_ms: float
    row_count: int
    status: str  # "success" | "error"
    timestamp: float
    error_message: str | None = None
    parameters: list[Any] | dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Converts execution event to serializable dictionary."""
        data: dict[str, Any] = {
            "query_hash": self.query_hash,
            "sql": self.sql,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "dialect": self.dialect,
            "latency_ms": self.latency_ms,
            "row_count": self.row_count,
            "status": self.status,
            "timestamp": self.timestamp,
            "error_message": self.error_message,
        }
        if self.parameters is not None:
            data["parameters"] = self.parameters
        return data


@dataclass
class AuditEvent:
    """Represents a security audit event."""

    event_type: str  # "query_execution", "security_violation", "access_denied", "policy_enforcement"
    action: str  # "compile", "execute", "mask", "validate"
    resource: str  # table, column, or target
    status: str  # "success", "denied", "error"
    timestamp: float
    tenant_id: str | None = None
    user_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Converts audit event to serializable dictionary."""
        return {
            "event_type": self.event_type,
            "action": self.action,
            "resource": self.resource,
            "status": self.status,
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "details": self.details,
            "error_message": self.error_message,
        }


class TelemetryCollector:
    """Thread-safe ring-buffer execution metrics and security audit event collector."""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._events: collections.deque[ExecutionEvent] = collections.deque(
            maxlen=max_size
        )
        self._audit_events: collections.deque[AuditEvent] = collections.deque(
            maxlen=max_size
        )
        self._lock = threading.Lock()
        self._total_queries = 0
        self._success_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._active_tenants: set[str] = set()

    def record_execution(
        self,
        sql: str,
        latency_ms: float,
        row_count: int = 0,
        status: str = "success",
        dialect: str = "postgres",
        tenant_id: str | None = None,
        user_id: str | None = None,
        error_message: str | None = None,
        parameters: list[Any] | dict[str, Any] | None = None,
        redact_parameters: bool = False,
    ) -> ExecutionEvent:
        """Records a query execution event into the ring buffer, scrubbing credentials and redacting parameters if requested."""
        q_hash = hash_query(sql)

        # Sanitize error message
        clean_error = scrub_secrets(error_message) if error_message else None

        # Sanitize or redact parameters
        sanitized_params: list[Any] | dict[str, Any] | None = None
        if parameters is not None:
            if redact_parameters:
                if isinstance(parameters, dict):
                    sanitized_params = {k: "[REDACTED]" for k in parameters}
                elif isinstance(parameters, (list, tuple)):
                    sanitized_params = ["[REDACTED]" for _ in parameters]
                else:
                    sanitized_params = "[REDACTED]"
            else:
                sanitized_params = scrub_secrets(parameters)

        event = ExecutionEvent(
            query_hash=q_hash,
            sql=sql,
            tenant_id=tenant_id,
            user_id=user_id,
            dialect=dialect,
            latency_ms=round(float(latency_ms), 2),
            row_count=row_count,
            status=status,
            timestamp=time.time(),
            error_message=clean_error,
            parameters=sanitized_params,
        )

        with self._lock:
            self._events.append(event)
            self._total_queries += 1
            if status == "success":
                self._success_count += 1
                self._total_latency_ms += float(latency_ms)
            else:
                self._error_count += 1
            if tenant_id:
                self._active_tenants.add(tenant_id)

        return event

    def record_audit_event(
        self,
        event_type: str,
        action: str,
        resource: str,
        status: str = "success",
        tenant_id: str | None = None,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> AuditEvent:
        """Records a security audit event into the audit ring buffer."""
        clean_error = scrub_secrets(error_message) if error_message else None
        clean_details = scrub_secrets(details) if details is not None else {}

        event = AuditEvent(
            event_type=event_type,
            action=action,
            resource=resource,
            status=status,
            timestamp=time.time(),
            tenant_id=tenant_id,
            user_id=user_id,
            details=clean_details,
            error_message=clean_error,
        )

        with self._lock:
            self._audit_events.append(event)

        return event

    def get_metrics(self) -> dict[str, Any]:
        """Calculates and returns execution metrics including latency percentiles."""
        with self._lock:
            success_latencies = [
                e.latency_ms for e in self._events if e.status == "success"
            ]
            total = self._total_queries
            success = self._success_count
            error = self._error_count
            active_tenants = len(self._active_tenants)

        if not success_latencies:
            avg_latency = 0.0
            p50 = 0.0
            p95 = 0.0
            p99 = 0.0
        else:
            sorted_lats = sorted(success_latencies)
            n = len(sorted_lats)
            avg_latency = round(sum(sorted_lats) / n, 2)
            p50 = sorted_lats[round(0.50 * (n - 1))]
            p95 = sorted_lats[round(0.95 * (n - 1))]
            p99 = sorted_lats[round(0.99 * (n - 1))]

        error_rate = round(error / total, 4) if total > 0 else 0.0

        return {
            "total_queries": total,
            "success_count": success,
            "error_count": error,
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "active_tenants_count": active_tenants,
        }

    def get_recent_events(
        self, limit: int = 50, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Returns recent execution events, optionally filtered by tenant."""
        with self._lock:
            filtered = [
                e for e in self._events if tenant_id is None or e.tenant_id == tenant_id
            ]
            recent = list(reversed(filtered[-limit:]))
            return [e.to_dict() for e in recent]

    def get_recent_audit_events(
        self, limit: int = 50, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Returns recent audit events, optionally filtered by tenant."""
        with self._lock:
            filtered = [
                e
                for e in self._audit_events
                if tenant_id is None or e.tenant_id == tenant_id
            ]
            recent = list(reversed(filtered[-limit:]))
            return [e.to_dict() for e in recent]

    def clear(self) -> None:
        """Resets all telemetry counters and clears event and audit buffers."""
        with self._lock:
            self._events.clear()
            self._audit_events.clear()
            self._total_queries = 0
            self._success_count = 0
            self._error_count = 0
            self._total_latency_ms = 0.0
            self._active_tenants.clear()
