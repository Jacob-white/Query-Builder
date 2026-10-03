"""
Query Execution Telemetry Engine.
=================================
Fingerprints queries via SHA-256 hashing, collects runtime metrics in a
thread-safe ring buffer, and computes real-time latency percentiles (p50/p95/p99).
"""

from __future__ import annotations

import collections
import hashlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any


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

    def to_dict(self) -> dict[str, Any]:
        """Converts execution event to serializable dictionary."""
        return {
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


class TelemetryCollector:
    """Thread-safe ring-buffer execution metrics collector."""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._events: collections.deque[ExecutionEvent] = collections.deque(
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
    ) -> ExecutionEvent:
        """Records a query execution event into the ring buffer."""
        q_hash = hash_query(sql)
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
            error_message=error_message,
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

    def clear(self) -> None:
        """Resets all telemetry counters and clears event buffer."""
        with self._lock:
            self._events.clear()
            self._total_queries = 0
            self._success_count = 0
            self._error_count = 0
            self._total_latency_ms = 0.0
            self._active_tenants.clear()
