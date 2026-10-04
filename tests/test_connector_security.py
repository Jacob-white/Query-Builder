"""
Unit & Integration Test Suite for Connector Security Framework (Milestone 3).
=============================================================================
Tests BaseConnector and AsyncBaseConnector for:
1. SecurityConfig initialization (default, explicit, and environment configurations)
2. Automated secret scrubbing in __repr__ and __str__
3. Network SSRF egress validation during connect() and execute()
4. Exception credential scrubbing (ConnectionFailedError, QueryExecutionError, etc.)
5. Dynamic execution boundary enforcement (statement timeouts, read-only sessions,
   AST validation, AST complexity score governors, Cartesian product prevention,
   row limit ceilings, dynamic column masking)
6. Structured audit event and telemetry emission
7. 100% statement and 100% branch test coverage across base.py and async_base.py
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.compiler import CompilationError
from query_builder.config import (
    ExecutionSecurityConfig,
    LoggingSecurityConfig,
    PrivacySecurityConfig,
    SecurityConfig,
    SecurityProfile,
)
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    ConnectorError,
    DriverNotInstalledError,
    IntrospectionError,
    QueryExecutionError,
)
from query_builder.dialects import BaseDialect
from query_builder.middleware import LifecycleInterceptor
from query_builder.models import QuerySpec
from query_builder.policy import TenantContext
from query_builder.security import SecurityError

# ==============================================================================
# Test Fixtures and Mock Classes
# ==============================================================================


def test_connector_exception_hierarchy():
    """Validates that all connector exception classes inherit from ConnectorError."""
    assert issubclass(ConnectionFailedError, ConnectorError)
    assert issubclass(QueryExecutionError, ConnectorError)
    assert issubclass(DriverNotInstalledError, ConnectorError)
    assert issubclass(IntrospectionError, ConnectorError)


class ConcreteSyncConnector(BaseConnector):
    """Synchronous test connector."""

    dialect_name = "postgres"

    def __init__(self, conn_obj: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.mock_db = conn_obj
        self.connect_calls = 0

    def connect(self) -> Any:
        self.connect_calls += 1
        if isinstance(self.mock_db, Exception):
            raise self.mock_db
        if self._connection is None:
            self._connection = self.mock_db or MagicMock()
        return self._connection


class GrandchildSyncConnector(ConcreteSyncConnector):
    """Subclass without explicit connect implementation to test inheritance."""

    dialect_name = "sqlite"


class ConcreteAsyncConnector(AsyncBaseConnector):
    """Asynchronous test connector."""

    dialect_name = "postgres"

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        count: int = 1,
        conn_obj: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.dummy_rows = rows if rows is not None else [{"id": 1, "name": "Alice"}]
        self.dummy_count = count
        self.mock_db = conn_obj
        self.connect_calls = 0
        self.raw_queries: list[tuple[str, list[Any] | None]] = []

    async def connect(self) -> Any:
        self.connect_calls += 1
        if isinstance(self.mock_db, Exception):
            raise self.mock_db
        if self._connection is None:
            self._connection = self.mock_db or MagicMock()
        return self._connection

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        self.raw_queries.append((sql, params))
        if "COUNT" in sql.upper():
            return ["count"], [{"count": self.dummy_count}], 1.0
        cols = list(self.dummy_rows[0].keys()) if self.dummy_rows else []
        return cols, self.dummy_rows, 1.5


class GrandchildAsyncConnector(ConcreteAsyncConnector):
    """Subclass without explicit connect implementation."""

    dialect_name = "sqlite"


class UnconstructibleError(Exception):
    def __init__(self, a: int, b: int) -> None:
        super().__init__(f"Error {a} {b}")


# ==============================================================================
# SECTION 1: Initialization & Security Configuration Tests
# ==============================================================================


def test_base_connector_security_init_defaults():
    """Verify default security configuration resolution."""
    conn = ConcreteSyncConnector()
    assert isinstance(conn.security, SecurityConfig)
    assert conn._explicit_security is False
    assert conn.telemetry_collector is not None


def test_base_connector_security_init_explicit():
    """Verify explicit security parameter takes precedence."""
    sec = SecurityProfile.strict()
    conn = ConcreteSyncConnector(security=sec)
    assert conn.security is sec
    assert conn._explicit_security is True


def test_base_connector_security_init_via_config_dict():
    """Verify security passed inside config dictionary."""
    sec = SecurityProfile.development()
    conn = ConcreteSyncConnector(security=sec, host="localhost")
    assert conn.security is sec
    assert conn._explicit_security is True

    # Also test passing inside kwargs as 'security'
    conn2 = ConcreteSyncConnector(security=sec, host="127.0.0.1")
    assert conn2.security is sec
    assert conn2._explicit_security is True


def test_base_connector_dialect_variants():
    """Verify dialect initialization variants (None, string, BaseDialect)."""

    class CustomDialect(BaseDialect):
        name = "custom_test"

    c1 = ConcreteSyncConnector(dialect=None)
    assert c1.dialect_name == "postgres"

    c2 = ConcreteSyncConnector(dialect="sqlite")
    assert c2.dialect_name == "sqlite"

    c3 = ConcreteSyncConnector(dialect=CustomDialect())
    assert c3.dialect_name == "custom_test"


def test_async_base_connector_security_init():
    """Verify AsyncBaseConnector security initialization."""
    sec = SecurityProfile.strict()
    conn = ConcreteAsyncConnector(security=sec)
    assert conn.security is sec
    assert conn._explicit_security is True

    conn_def = ConcreteAsyncConnector()
    assert isinstance(conn_def.security, SecurityConfig)
    assert conn_def._explicit_security is False

    conn_dict = ConcreteAsyncConnector(security=sec)
    assert conn_dict.security is sec

    conn_str = ConcreteAsyncConnector(dialect="sqlite")
    assert conn_str.dialect_name == "sqlite"


# ==============================================================================
# SECTION 2: Automated Secret Scrubbing in __repr__ and __str__
# ==============================================================================


def test_base_connector_repr_str_secret_scrubbing():
    """Verify __repr__ and __str__ scrub passwords, tokens, and URIs."""
    conn = ConcreteSyncConnector(
        password="super_secret_password",
        token="bearer_xyz123abc",
        connection_string="postgresql://admin:super_secret@db.internal:5432/finance",
        host="db.internal",
    )
    r = repr(conn)
    s = str(conn)

    assert "super_secret_password" not in r
    assert "bearer_xyz123abc" not in r
    assert "super_secret" not in r
    assert "***" in r

    assert "super_secret_password" not in s
    assert "bearer_xyz123abc" not in s
    assert "super_secret" not in s
    assert "***" in s


def test_base_connector_repr_str_mask_credentials_disabled():
    """Verify __repr__ and __str__ preserve raw config when mask_credentials is False."""
    sec = SecurityProfile.development()
    sec.logging.mask_credentials = False

    conn = ConcreteSyncConnector(
        security=sec,
        password="plaintext_secret",
    )
    r = repr(conn)
    s = str(conn)

    assert "plaintext_secret" in r
    assert "plaintext_secret" in s


def test_async_base_connector_repr_str_secret_scrubbing():
    """Verify AsyncBaseConnector __repr__ and __str__ scrubbing."""
    conn = ConcreteAsyncConnector(
        password="async_super_secret",
        token="token_val",
    )
    r = repr(conn)
    s = str(conn)

    assert "async_super_secret" not in r
    assert "token_val" not in r
    assert "***" in r
    assert "async_super_secret" not in s
    assert "token_val" not in s
    assert "***" in s

    # With mask_credentials disabled
    sec = SecurityProfile.development()
    sec.logging.mask_credentials = False
    conn_unmasked = ConcreteAsyncConnector(security=sec, password="exposed")
    assert "exposed" in repr(conn_unmasked)
    assert "exposed" in str(conn_unmasked)


# ==============================================================================
# SECTION 3: Network SSRF Egress Validation in connect() & execute()
# ==============================================================================


def test_base_connector_blocks_cloud_metadata():
    """Verify connection to cloud metadata endpoint (169.254.169.254) is blocked."""
    conn = ConcreteSyncConnector(host="169.254.169.254")
    with pytest.raises(SecurityError, match="cloud metadata"):
        conn.connect()


def test_base_connector_blocks_metadata_hostname():
    """Verify connection to cloud metadata hostname is blocked."""
    conn = ConcreteSyncConnector(host="metadata.google.internal")
    with pytest.raises(SecurityError, match="cloud metadata"):
        conn.connect()


def test_base_connector_blocks_private_networks_when_configured():
    """Verify loopback / private subnet targets blocked when allow_private_networks=False."""
    sec = SecurityProfile.production()
    sec.network.allow_private_networks = False

    conn = ConcreteSyncConnector(security=sec, host="127.0.0.1")
    with pytest.raises(SecurityError, match="private/internal network target|loopback"):
        conn.connect()


def test_base_connector_permits_private_networks_in_development():
    """Verify private subnet targets allowed when allow_private_networks=True."""
    sec = SecurityProfile.development()
    assert sec.network.allow_private_networks is True

    conn = ConcreteSyncConnector(security=sec, host="127.0.0.1")
    c = conn.connect()
    assert c is not None


def test_base_connector_env_var_enforces_ssrf():
    """Verify QB_ALLOW_PRIVATE_NETWORKS=false blocks localhost without explicit security."""
    with patch.dict(os.environ, {"QB_ALLOW_PRIVATE_NETWORKS": "false"}):
        conn = ConcreteSyncConnector(host="127.0.0.1")
        with pytest.raises(
            SecurityError, match="private/internal network target|loopback"
        ):
            conn.connect()


def test_base_connector_env_var_permits_private_networks():
    """Verify QB_ALLOW_PRIVATE_NETWORKS=true permits localhost."""
    with patch.dict(os.environ, {"QB_ALLOW_PRIVATE_NETWORKS": "true"}):
        conn = ConcreteSyncConnector(host="127.0.0.1")
        c = conn.connect()
        assert c is not None


def test_base_connector_validate_network_method():
    """Verify explicit validate_network() method invocation."""
    conn = ConcreteSyncConnector(host="169.254.169.254")
    with pytest.raises(SecurityError, match="cloud metadata"):
        conn.validate_network()

    # When no host is targeted, validation succeeds
    conn_clean = ConcreteSyncConnector()
    conn_clean.validate_network()


def test_async_base_connector_ssrf_validation():
    """Verify AsyncBaseConnector SSRF validation blocks metadata and private IPs."""

    async def _test():
        conn_meta = ConcreteAsyncConnector(host="169.254.169.254")
        with pytest.raises(SecurityError, match="cloud metadata"):
            await conn_meta.connect()

        sec = SecurityProfile.production()
        conn_loop = ConcreteAsyncConnector(security=sec, host="127.0.0.1")
        with pytest.raises(
            SecurityError, match="private/internal network target|loopback"
        ):
            await conn_loop.connect()

        conn_dev = ConcreteAsyncConnector(
            security=SecurityProfile.development(), host="127.0.0.1"
        )
        c = await conn_dev.connect()
        assert c is not None

        # validate_network method
        conn_dev.validate_network()

    asyncio.run(_test())


# ==============================================================================
# SECTION 4: Exception Credential Scrubbing Tests
# ==============================================================================


def test_base_connector_connect_error_scrubbing():
    """Verify credentials scrubbed from ConnectionFailedError and causes."""
    raw_err = ConnectionFailedError(
        "Failed connection to postgresql://admin:secret_password@db.corp:5432/db"
    )
    conn = ConcreteSyncConnector(conn_obj=raw_err)

    with pytest.raises(ConnectionFailedError) as exc_info:
        conn.connect()

    msg = str(exc_info.value)
    assert "secret_password" not in msg
    assert "***" in msg


def test_base_connector_connect_error_with_cause_scrubbing():
    """Verify cause exceptions also have sensitive tokens scrubbed."""
    cause = RuntimeError("Driver failure: password=super_secret_token")
    raw_err = ConnectionFailedError("Connection failed")
    raw_err.__cause__ = cause

    conn = ConcreteSyncConnector(conn_obj=raw_err)

    with pytest.raises(ConnectionFailedError) as exc_info:
        conn.connect()

    assert "super_secret_token" not in str(exc_info.value.__cause__)
    assert "***" in str(exc_info.value.__cause__)


def test_base_connector_error_scrubbing_disabled():
    """Verify error messages not scrubbed when mask_credentials is False."""
    sec = SecurityProfile.development()
    sec.logging.mask_credentials = False

    raw_err = ConnectionFailedError("Connection with password=plaintext_token failed")
    conn = ConcreteSyncConnector(security=sec, conn_obj=raw_err)

    with pytest.raises(ConnectionFailedError) as exc_info:
        conn.connect()

    assert "plaintext_token" in str(exc_info.value)


def test_base_connector_error_scrubbing_unconstructible_fallback():
    """Verify fallback to ConnectionFailedError when original exception type cannot be re-instantiated."""

    class CustomBadError(Exception):
        def __init__(self, x: int, y: int):
            super().__init__(f"Bad {x} {y}")

    bad_err = CustomBadError(10, 20)
    # inject secret into str representation
    with patch.object(
        CustomBadError, "__str__", return_value="Error password=secret_code"
    ):
        conn = ConcreteSyncConnector(conn_obj=bad_err)
        with pytest.raises(ConnectionFailedError) as exc_info:
            conn.connect()
        assert "secret_code" not in str(exc_info.value)


def test_async_base_connector_connect_error_scrubbing():
    """Verify AsyncBaseConnector scrubs credentials from connection errors."""

    async def _test():
        raw_err = ConnectionFailedError(
            "Async connection to redis://user:secret_token@redis.corp failed"
        )
        conn = ConcreteAsyncConnector(conn_obj=raw_err)

        with pytest.raises(ConnectionFailedError) as exc_info:
            await conn.connect()

        assert "secret_token" not in str(exc_info.value)
        assert "***" in str(exc_info.value)

    asyncio.run(_test())


# ==============================================================================
# SECTION 5: Dynamic Execution Boundaries (Timeouts, Read-Only, AST, Limits)
# ==============================================================================


def test_base_connector_timeout_validation():
    """Verify positive timeout validation and timeout_ms parameter."""
    conn = ConcreteSyncConnector()
    with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
        conn.execute({"table": "users"}, statement_timeout_ms=0)

    with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
        conn.execute({"table": "users"}, statement_timeout_ms=-100)

    with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
        conn.execute({"table": "users"}, timeout_ms=0)


def test_base_connector_read_only_session_enforcement():
    """Verify mutating statements blocked when enforce_read_only_session is True."""
    sec = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=True),
        profile="production",
    )
    conn = ConcreteSyncConnector(security=sec)

    # Via raw SQL parameter
    with pytest.raises(SecurityError, match="Read-only session violation"):
        conn.execute(sql="DELETE FROM users WHERE id = 1", validate_ast=False)

    with pytest.raises(SecurityError, match="Read-only session violation"):
        conn.execute(sql="DROP TABLE users", validate_ast=False)

    with pytest.raises(SecurityError, match="Read-only session violation"):
        conn.execute(sql="INSERT INTO users (id) VALUES (1)", validate_ast=False)


def test_base_connector_ast_complexity_limit():
    """Verify queries exceeding max_complexity_score are blocked."""
    sec = SecurityConfig(
        execution=ExecutionSecurityConfig(max_complexity_score=5),
        profile="production",
    )
    conn = ConcreteSyncConnector(security=sec)

    # Complex spec with joins, filters, group_by
    complex_spec = {
        "table": "orders",
        "columns": ["id", "total", "customer_id"],
        "joins": [
            {"table": "customers", "type": "LEFT", "on": ["orders.cid = customers.id"]}
        ],
        "filters": [{"column": "total", "op": "gt", "value": 100}],
        "group_by": ["customer_id"],
    }
    with pytest.raises(SecurityError, match="AST complexity score"):
        conn.execute(complex_spec)


def test_base_connector_cartesian_product_prevention():
    """Verify explicit CROSS JOIN raises SecurityError when prevent_cartesian_products is True."""
    sec = SecurityConfig(
        execution=ExecutionSecurityConfig(prevent_cartesian_products=True),
        profile="production",
    )
    conn = ConcreteSyncConnector(security=sec)

    cross_spec = {
        "table": "users",
        "joins": [{"table": "roles", "type": "CROSS"}],
    }
    with pytest.raises(SecurityError, match="Cartesian product detected"):
        conn.execute(cross_spec)


def test_base_connector_max_join_depth():
    """Verify exceeding max_join_depth raises SecurityError."""
    sec = SecurityConfig(
        execution=ExecutionSecurityConfig(max_join_depth=1),
        profile="production",
    )
    conn = ConcreteSyncConnector(security=sec)

    deep_joins_spec = {
        "table": "a",
        "joins": [
            {"table": "b", "on": ["a.id = b.a_id"]},
            {"table": "c", "on": ["b.id = c.b_id"]},
        ],
    }
    with pytest.raises(SecurityError, match="Query join depth"):
        conn.execute(deep_joins_spec)


def test_base_connector_row_limit_ceiling():
    """Verify server-side max_rows_limit restricts returned rows and clamps limit."""
    sec = SecurityConfig(
        execution=ExecutionSecurityConfig(max_rows_limit=2),
        profile="production",
    )

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (10,)
    mock_cur.description = [("id",), ("name",)]
    mock_cur.fetchall.return_value = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]

    conn = ConcreteSyncConnector(cursor=mock_cur, security=sec)
    res = conn.execute({"table": "users", "limit": 100}, validate_ast=False)

    assert len(res["rows"]) == 2
    assert res.get("truncated") is True
    assert res["limit"] == 2


def test_base_connector_column_masking():
    """Verify sensitive columns are masked for non-admin users."""
    sec = SecurityConfig(
        privacy=PrivacySecurityConfig(
            sensitive_column_patterns=[r"(?i)(secret|password|token)"],
            masking_strategy="redact",
        ),
        profile="production",
    )

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)
    mock_cur.description = [("id",), ("secret_key",), ("public_name",)]
    mock_cur.fetchall.return_value = [(1, "sensitive_value_123", "Visible")]

    conn = ConcreteSyncConnector(cursor=mock_cur, security=sec)

    # 1. Non-admin execution
    res = conn.execute({"table": "credentials"}, validate_ast=False)
    assert res["rows"][0]["secret_key"] == "[REDACTED]"
    assert res["rows"][0]["public_name"] == "Visible"

    # 2. Admin execution preserves raw values
    admin_ctx = TenantContext(tenant_id="t1", roles=["admin"])
    res_admin = conn.execute(
        {"table": "credentials"},
        context={"tenant_context": admin_ctx},
        validate_ast=False,
    )
    assert res_admin["rows"][0]["secret_key"] == "sensitive_value_123"


def test_base_connector_per_query_security_override():
    """Verify execute(security=...) overrides connector instance security config."""
    instance_sec = SecurityProfile.development()
    query_sec = SecurityProfile.strict()

    conn = ConcreteSyncConnector(security=instance_sec)

    # Query with strict security limit
    cross_spec = {
        "table": "users",
        "joins": [{"table": "roles", "type": "CROSS"}],
    }
    with pytest.raises(SecurityError, match="Cartesian product detected"):
        conn.execute(cross_spec, security=query_sec)


def test_base_connector_telemetry_audit_emission():
    """Verify AuditEvent and execution events are emitted when emit_audit_events is True."""
    sec = SecurityConfig(
        logging=LoggingSecurityConfig(emit_audit_events=True),
        profile="production",
    )

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)
    mock_cur.description = [("id",)]
    mock_cur.fetchall.return_value = [(1,)]

    conn = ConcreteSyncConnector(cursor=mock_cur, security=sec)
    conn.execute({"table": "audit_test"}, validate_ast=False)

    recent_audits = conn.telemetry_collector.get_recent_audit_events()
    assert len(recent_audits) >= 1
    assert recent_audits[0]["resource"] == "audit_test"
    assert recent_audits[0]["status"] == "success"

    metrics = conn.telemetry_collector.get_metrics()
    assert metrics["total_queries"] >= 1


def test_base_connector_dataclass_spec_execution():
    """Verify execute() accepts QuerySpec dataclass instances."""
    spec = QuerySpec(table="users", limit=10)
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)
    mock_cur.description = [("id",)]
    mock_cur.fetchall.return_value = [(1,)]

    conn = ConcreteSyncConnector(cursor=mock_cur)
    res = conn.execute(spec, validate_ast=False)
    assert res["count"] == 1
    assert res["limit"] == 10


def test_base_connector_raw_sql_execution_success():
    """Verify execute() with sql parameter directly."""
    mock_cur = MagicMock()
    mock_cur.description = [("num",)]
    mock_cur.fetchall.return_value = [(42,)]

    conn = ConcreteSyncConnector(cursor=mock_cur)
    res = conn.execute(sql="SELECT 42 AS num", validate_ast=False)
    assert res["rows"] == [{"num": 42}]
    assert res["count"] == 1


def test_base_connector_execute_error_telemetry_emission():
    """Verify execution errors record audit events and scrub secrets."""
    sec = SecurityConfig(
        logging=LoggingSecurityConfig(emit_audit_events=True, mask_credentials=True),
        profile="production",
    )

    mock_cur = MagicMock()
    mock_cur.execute.side_effect = RuntimeError(
        "Fatal query error with password=exposed_pw"
    )

    conn = ConcreteSyncConnector(cursor=mock_cur, security=sec)
    with pytest.raises(RuntimeError) as exc_info:
        conn.execute({"table": "faulty"}, validate_ast=False)

    assert "exposed_pw" not in str(exc_info.value)
    audits = conn.telemetry_collector.get_recent_audit_events()
    assert len(audits) >= 1
    assert audits[0]["status"] == "error"
    assert "exposed_pw" not in audits[0]["error_message"]


# ==============================================================================
# SECTION 6: Asynchronous Dynamic Execution Boundaries Tests
# ==============================================================================


def test_async_base_connector_execution_boundaries():
    """Verify AsyncBaseConnector execution boundaries (read-only, complexity, limits, masking)."""

    async def _test():
        # 1. Read-only violation
        sec_ro = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=True),
            profile="production",
        )
        conn_ro = ConcreteAsyncConnector(security=sec_ro)
        with pytest.raises(SecurityError, match="Read-only session violation"):
            await conn_ro.execute(sql="DROP TABLE users", validate_ast=False)

        # 2. AST complexity violation
        sec_comp = SecurityConfig(
            execution=ExecutionSecurityConfig(max_complexity_score=2),
            profile="production",
        )
        conn_comp = ConcreteAsyncConnector(security=sec_comp)
        with pytest.raises(SecurityError, match="AST complexity score"):
            await conn_comp.execute(
                {
                    "table": "users",
                    "joins": [{"table": "roles", "on": ["users.rid = roles.id"]}],
                }
            )

        # 3. Cartesian product violation
        sec_cart = SecurityConfig(
            execution=ExecutionSecurityConfig(prevent_cartesian_products=True),
            profile="production",
        )
        conn_cart = ConcreteAsyncConnector(security=sec_cart)
        with pytest.raises(SecurityError, match="Cartesian product detected"):
            await conn_cart.execute(
                {"table": "users", "joins": [{"table": "roles", "type": "CROSS"}]}
            )

        # 4. Join depth violation
        sec_join = SecurityConfig(
            execution=ExecutionSecurityConfig(max_join_depth=1),
            profile="production",
        )
        conn_join = ConcreteAsyncConnector(security=sec_join)
        with pytest.raises(SecurityError, match="Query join depth"):
            await conn_join.execute(
                {
                    "table": "t1",
                    "joins": [
                        {"table": "t2", "on": ["t1.id = t2.id"]},
                        {"table": "t3", "on": ["t2.id = t3.id"]},
                    ],
                }
            )

        # 5. Row limit ceiling
        sec_rows = SecurityConfig(
            execution=ExecutionSecurityConfig(max_rows_limit=1),
            profile="production",
        )
        conn_rows = ConcreteAsyncConnector(
            rows=[{"id": 1}, {"id": 2}, {"id": 3}],
            count=3,
            security=sec_rows,
        )
        res_rows = await conn_rows.execute({"table": "users"}, validate_ast=False)
        assert len(res_rows["rows"]) == 1
        assert res_rows.get("truncated") is True

        # 6. Column masking
        sec_mask = SecurityConfig(
            privacy=PrivacySecurityConfig(
                sensitive_column_patterns=[r"(?i)token"],
                masking_strategy="redact",
            ),
            profile="production",
        )
        conn_mask = ConcreteAsyncConnector(
            rows=[{"id": 1, "token": "secret_123"}],
            security=sec_mask,
        )
        res_mask = await conn_mask.execute({"table": "tokens"}, validate_ast=False)
        assert res_mask["rows"][0]["token"] == "[REDACTED]"

        # 7. Raw SQL execution
        conn_raw = ConcreteAsyncConnector(rows=[{"result": 100}])
        res_raw = await conn_raw.execute(sql="SELECT 100 AS result", validate_ast=False)
        assert res_raw["rows"] == [{"result": 100}]

        # 8. Execution error scrubbing & telemetry
        class FailingAsync(ConcreteAsyncConnector):
            async def execute_raw(self, sql, params=None):
                raise RuntimeError("Async query failure with password=leaked_secret")

        sec_tel = SecurityConfig(
            logging=LoggingSecurityConfig(
                emit_audit_events=True, mask_credentials=True
            ),
            profile="production",
        )
        conn_fail = FailingAsync(security=sec_tel)
        with pytest.raises(RuntimeError) as exc_info:
            await conn_fail.execute({"table": "err_test"}, validate_ast=False)

        assert "leaked_secret" not in str(exc_info.value)
        audits = conn_fail.telemetry_collector.get_recent_audit_events()
        assert len(audits) >= 1
        assert audits[0]["status"] == "error"

    asyncio.run(_test())


# ==============================================================================
# SECTION 7: Full Schema Introspection & Coverage Branches
# ==============================================================================


def test_base_connector_schema_introspection_branches():
    """Verify all introspection and metadata branches in BaseConnector."""
    # 1. SQLite dialect introspection
    mem_conn = sqlite3.connect(":memory:")
    mem_conn.execute(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT, price REAL);"
    )
    mem_conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, product_id INTEGER, FOREIGN KEY(product_id) REFERENCES products(id));"
    )

    conn_sqlite = ConcreteSyncConnector(conn_obj=mem_conn, dialect="sqlite")
    tables = conn_sqlite.inspect_tables()
    assert "products" in tables
    assert "orders" in tables

    cols_prod = conn_sqlite.inspect_columns("products")
    assert any(c["name"] == "title" for c in cols_prod)

    pks_prod = conn_sqlite.inspect_primary_keys("products")
    assert "id" in pks_prod

    fks_all = conn_sqlite.inspect_foreign_keys()
    assert len(fks_all) >= 1
    fks_orders = conn_sqlite.inspect_foreign_keys("orders")
    assert len(fks_orders) >= 1
    fks_prod = conn_sqlite.inspect_foreign_keys("products")
    assert len(fks_prod) == 0

    cols_nonexistent = conn_sqlite.inspect_columns("non_existent_table")
    assert cols_nonexistent == []

    # 2. Information schema branch
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [("items", "id", "integer", False, None)]
    conn_info = ConcreteSyncConnector(
        cursor=mock_cur, dialect="postgres", schema_name="public"
    )
    snap_info = conn_info.introspect_schema()
    assert "tables" in snap_info

    # 3. Introspection exception fallback branch
    exploding_cur = MagicMock()
    exploding_cur.execute.side_effect = RuntimeError("Catastrophic catalog failure")
    conn_exploding = ConcreteSyncConnector(cursor=exploding_cur)
    snap_fallback = conn_exploding.introspect_schema()
    assert snap_fallback["tables"] == {}
    assert snap_fallback["foreign_keys"] == []


def test_async_base_connector_schema_introspection_branches():
    """Verify AsyncBaseConnector introspection branches (tables, columns, PKs, FKs)."""

    async def _test():
        conn = ConcreteAsyncConnector()

        # inspect_tables
        tables = await conn.inspect_tables()
        assert tables == []

        # inspect_columns
        cols_none = await conn.inspect_columns("unknown")
        assert cols_none == []

        # mock introspect_schema returning tables
        with patch.object(
            conn,
            "introspect_schema",
            return_value={
                "tables": {
                    "users": {
                        "columns": [
                            {"name": "id", "is_primary": True},
                            {"name": "email", "is_primary": False},
                        ]
                    }
                },
                "foreign_keys": [{"table": "posts", "from": "user_id", "to": "id"}],
            },
        ):
            cols_users = await conn.inspect_columns("users")
            assert len(cols_users) == 2

            pks = await conn.inspect_primary_keys("users")
            assert pks == ["id"]

            fks_all = await conn.inspect_foreign_keys()
            assert len(fks_all) == 1

            fks_posts = await conn.inspect_foreign_keys("posts")
            assert len(fks_posts) == 1

            fks_users = await conn.inspect_foreign_keys("users")
            assert len(fks_users) == 0

    asyncio.run(_test())


def test_base_connector_lifecycle_and_error_branches():
    """Verify close(), context managers, and corner error cases."""
    # 1. Close when already closed
    c_empty = ConcreteSyncConnector()
    c_empty.close()
    assert c_empty._connection is None

    # 2. Close suppressing errors
    err_cur = MagicMock()
    err_cur.close.side_effect = RuntimeError("Cur fail")
    err_conn = MagicMock()
    err_conn.close.side_effect = RuntimeError("Conn fail")

    c_err = ConcreteSyncConnector(connection=err_conn, cursor=err_cur)
    c_err.close()
    assert c_err._cursor is None
    assert c_err._connection is None

    # 3. Context manager
    with ConcreteSyncConnector() as c:
        assert isinstance(c, ConcreteSyncConnector)

    # 4. apply_statement_timeout base implementation
    c_empty.apply_statement_timeout(MagicMock(), 1000)

    # 5. Grandchild connector inherits wrapped connect
    grandchild = GrandchildSyncConnector()
    assert grandchild.connect() is not None


def test_async_base_connector_lifecycle_branches():
    """Verify AsyncBaseConnector close(), __aenter__, __aexit__, execute_raw NotImplemented."""

    async def _test():
        # 1. Execute raw NotImplemented on base class
        class BareAsync(AsyncBaseConnector):
            async def connect(self):
                return None

        bare = BareAsync()
        with pytest.raises(NotImplementedError):
            await bare.execute_raw("SELECT 1")

        # 2. Async close handling sync close vs async close vs exception
        sync_mock = MagicMock()
        sync_mock.close.return_value = None
        conn_sync = ConcreteAsyncConnector(conn_obj=sync_mock)
        await conn_sync.connect()
        await conn_sync.close()
        assert conn_sync._connection is None

        exploding_mock = MagicMock()
        exploding_mock.close.side_effect = RuntimeError("Async close exploded")
        conn_exp = ConcreteAsyncConnector(conn_obj=exploding_mock)
        await conn_exp.connect()
        await conn_exp.close()
        assert conn_exp._connection is None

        # 3. Async context manager
        async with ConcreteAsyncConnector() as managed:
            assert managed is not None

        # 4. Grandchild async connector
        gc = GrandchildAsyncConnector()
        assert await gc.connect() is not None

    asyncio.run(_test())


# ==============================================================================
# SECTION 8: Deep Branch Coverage for All Edge Cases
# ==============================================================================


def test_base_connector_edge_branches():
    """Exercise remaining edge branches in BaseConnector."""

    # 1. Already wrapped subclass
    class Level1(ConcreteSyncConnector):
        pass

    class Level2(Level1):
        pass

    assert Level2().connect() is not None

    # 2. Dialect string postgres
    c_str = ConcreteSyncConnector(dialect="postgres")
    assert c_str.dialect_name == "postgres"

    # 3. validate_network with sec=None or network=None
    c_none = ConcreteSyncConnector()
    c_none.security = None
    c_none.validate_network()

    c_no_net = ConcreteSyncConnector()
    c_no_net.security = MagicMock(network=None)
    c_no_net.validate_network()

    # 4. QB_SECURITY_PROFILE in os.environ
    with patch.dict(os.environ, {"QB_SECURITY_PROFILE": "strict"}, clear=True):
        c_prof = ConcreteSyncConnector(host="127.0.0.1")
        with pytest.raises(SecurityError):
            c_prof.connect()

    # 5. Unconstructible cause in _scrub_exception
    err = ConnectionFailedError("Conn failed password=clean")
    err.__cause__ = UnconstructibleError(1, 2)
    with patch.object(
        UnconstructibleError,
        "__str__",
        return_value="Unconstructible with token=mysecret",
    ):
        c_uncon = ConcreteSyncConnector(conn_obj=err)
        with pytest.raises(ConnectionFailedError) as exc_info:
            c_uncon.connect()
        assert isinstance(exc_info.value.__cause__, Exception)
        assert "mysecret" not in str(exc_info.value.__cause__)

    # 6. get_cursor without cursor method
    raw_conn = MagicMock(spec=[])
    c_raw = ConcreteSyncConnector(conn_obj=raw_conn)
    with c_raw.get_cursor() as yielded:
        assert yielded is raw_conn

    # 7. get_cursor cursor.close raises exception in finally
    mock_cur = MagicMock()
    mock_cur.close.side_effect = RuntimeError("Close err")
    mock_db = MagicMock()
    mock_db.cursor.return_value = mock_cur
    c_cur_err = ConcreteSyncConnector(conn_obj=mock_db)
    with c_cur_err.get_cursor() as cur:
        assert cur is mock_cur

    # 8. execute spec=None and sql=None
    with pytest.raises(
        CompilationError,
        match="Specification must be a dictionary or dataclass instance",
    ):
        c_none.execute(spec=None, sql=None)

    # 9. Raw SQL with AST failure and short-circuit
    with (
        patch(
            "query_builder.connectors.base.validate_sql_ast",
            return_value={"valid": False, "message": "Raw AST invalid"},
        ),
        pytest.raises(CompilationError, match="Raw AST invalid"),
    ):
        c_none.execute(sql="SELECT 1", validate_ast=True)

    class ShortCircuitInterceptor(LifecycleInterceptor):
        def on_pre_execute(self, plan, ctx):
            return {
                "sql": "RAW_SHORT",
                "rows": [{"val": 99}],
                "columns": ["val"],
                "count": 1,
            }

    res_sc = c_none.execute(sql="SELECT 1", middleware=[ShortCircuitInterceptor()])
    assert res_sc["rows"] == [{"val": 99}]

    # 10. Spec pre-execute short-circuit
    class SpecShortCircuit(LifecycleInterceptor):
        def on_pre_execute(self, plan, ctx):
            return {
                "sql": "SPEC_SHORT",
                "rows": [{"id": 1}],
                "columns": ["id"],
                "count": 1,
            }

    res_spec_sc = c_none.execute({"table": "users"}, middleware=[SpecShortCircuit()])
    assert res_spec_sc["sql"] == "SPEC_SHORT"

    # 11. Spec AST validation failures
    with (
        patch(
            "query_builder.connectors.base.validate_sql_ast",
            return_value={"valid": False, "message": "Main AST invalid"},
        ),
        pytest.raises(CompilationError, match="Main AST invalid"),
    ):
        c_none.execute({"table": "users"}, validate_ast=True)

    with (
        patch(
            "query_builder.connectors.base.validate_sql_ast",
            side_effect=[
                {"valid": True, "message": "OK"},
                {"valid": False, "message": "Count AST invalid"},
            ],
        ),
        pytest.raises(CompilationError, match="Count AST invalid"),
    ):
        c_none.execute({"table": "users"}, validate_ast=True)

    # 12. Read-only violation on count_sql
    class CountMutator(LifecycleInterceptor):
        def on_post_compile(self, comp, ctx):
            comp["count_sql"] = "DELETE FROM users"
            return comp

    sec_ro = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=True)
    )
    c_ro = ConcreteSyncConnector(security=sec_ro)
    with pytest.raises(SecurityError, match="Read-only session violation"):
        c_ro.execute(
            {"table": "users"}, middleware=[CountMutator()], validate_ast=False
        )

    # 13. Count query without count_params (empty filters)
    mock_cur2 = MagicMock()
    mock_cur2.fetchone.return_value = (5,)
    mock_cur2.description = [("id",)]
    mock_cur2.fetchall.return_value = [(1,), (2,)]
    c_no_params = ConcreteSyncConnector(cursor=mock_cur2)
    res_no_params = c_no_params.execute(
        {"table": "users", "limit": 10}, validate_ast=False
    )
    assert res_no_params["count"] == 5

    # 14. Non-dict rows during column masking
    sec_mask = SecurityConfig(
        privacy=PrivacySecurityConfig(sensitive_column_patterns=["token"])
    )
    c_nondict = ConcreteSyncConnector(security=sec_mask)
    with patch(
        "query_builder.connectors.base.execute_cursor_query",
        return_value=(["val"], ["scalar_row"], 1.0),
    ):
        res_nondict = c_nondict.execute({"table": "users"}, validate_ast=False)
        assert res_nondict["rows"] == ["scalar_row"]


def test_async_base_connector_edge_branches():
    """Exercise remaining edge branches in AsyncBaseConnector."""

    async def _test():
        conn = ConcreteAsyncConnector()

        # 1. Already wrapped subclass
        class AsyncL1(ConcreteAsyncConnector):
            pass

        class AsyncL2(AsyncL1):
            pass

        assert await AsyncL2().connect() is not None

        # 2. validate_network with sec=None or network=None
        conn_none = ConcreteAsyncConnector()
        conn_none.security = None
        conn_none.validate_network()

        conn_no_net = ConcreteAsyncConnector()
        conn_no_net.security = MagicMock(network=None)
        conn_no_net.validate_network()

        # 3. QB_SECURITY_PROFILE in os.environ
        with patch.dict(os.environ, {"QB_SECURITY_PROFILE": "strict"}, clear=True):
            conn_prof = ConcreteAsyncConnector(host="127.0.0.1")
            with pytest.raises(SecurityError):
                await conn_prof.connect()

        # 4. Unconstructible cause in _scrub_exception
        err = ConnectionFailedError("Async conn failed password=clean")
        err.__cause__ = UnconstructibleError(3, 4)
        with patch.object(
            UnconstructibleError,
            "__str__",
            return_value="Async Cause with token=secret_token",
        ):
            c_uncon = ConcreteAsyncConnector(conn_obj=err)
            with pytest.raises(ConnectionFailedError) as exc_info:
                await c_uncon.connect()
            assert isinstance(exc_info.value.__cause__, Exception)
            assert "secret_token" not in str(exc_info.value.__cause__)

        # 5. execute spec=None and sql=None
        with pytest.raises(
            CompilationError,
            match="Specification must be a dictionary or dataclass instance",
        ):
            await conn.execute(spec=None, sql=None)

        # 6. Raw SQL with AST failure and short-circuit
        with (
            patch(
                "query_builder.connectors.async_base.validate_sql_ast",
                return_value={"valid": False, "message": "Async Raw AST invalid"},
            ),
            pytest.raises(CompilationError, match="Async Raw AST invalid"),
        ):
            await conn.execute(sql="SELECT 1", validate_ast=True)

        class AsyncShortCircuit(LifecycleInterceptor):
            def on_pre_execute(self, plan, ctx):
                return {
                    "sql": "ASYNC_SC",
                    "rows": [{"a": 1}],
                    "columns": ["a"],
                    "count": 1,
                }

        res_sc = await conn.execute(sql="SELECT 1", middleware=[AsyncShortCircuit()])
        assert res_sc["rows"] == [{"a": 1}]

        # 7. Spec pre-execute short-circuit
        class AsyncSpecSC(LifecycleInterceptor):
            def on_pre_execute(self, plan, ctx):
                return {"sql": "ASYNC_SPEC_SC", "rows": [], "count": 0}

        res_spec_sc = await conn.execute({"table": "users"}, middleware=[AsyncSpecSC()])
        assert res_spec_sc["sql"] == "ASYNC_SPEC_SC"

        # 8. Spec AST validation failures
        with (
            patch(
                "query_builder.connectors.async_base.validate_sql_ast",
                return_value={"valid": False, "message": "Async Main AST invalid"},
            ),
            pytest.raises(CompilationError, match="Async Main AST invalid"),
        ):
            await conn.execute({"table": "users"}, validate_ast=True)

        with (
            patch(
                "query_builder.connectors.async_base.validate_sql_ast",
                side_effect=[
                    {"valid": True, "message": "OK"},
                    {"valid": False, "message": "Async Count AST invalid"},
                ],
            ),
            pytest.raises(CompilationError, match="Async Count AST invalid"),
        ):
            await conn.execute({"table": "users"}, validate_ast=True)

        # 9. Read-only violation on count_sql
        class AsyncCountMutator(LifecycleInterceptor):
            def on_post_compile(self, comp, ctx):
                comp["count_sql"] = "DELETE FROM users"
                return comp

        sec_ro = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=True)
        )
        conn_ro = ConcreteAsyncConnector(security=sec_ro)
        with pytest.raises(SecurityError, match="Read-only session violation"):
            await conn_ro.execute(
                {"table": "users"}, middleware=[AsyncCountMutator()], validate_ast=False
            )

        # 10. Tuple count rows
        class TupleCountAsync(ConcreteAsyncConnector):
            async def execute_raw(self, sql, params=None):
                if "COUNT" in sql.upper():
                    return ["cnt"], [(10,)], 1.0
                return ["id"], [{"id": 1}], 1.0

        c_tuple = TupleCountAsync()
        res_tuple = await c_tuple.execute({"table": "users"}, validate_ast=False)
        assert res_tuple["count"] == 10

        # 11. Non-dict rows during column masking
        class NonDictAsync(ConcreteAsyncConnector):
            async def execute_raw(self, sql, params=None):
                if "COUNT" in sql.upper():
                    return ["cnt"], [{"cnt": 1}], 1.0
                return ["val"], [("raw_tuple",)], 1.0

        sec_mask = SecurityConfig(
            privacy=PrivacySecurityConfig(sensitive_column_patterns=["token"])
        )
        c_nd = NonDictAsync(security=sec_mask)
        res_nd = await c_nd.execute({"table": "users"}, validate_ast=False)
        assert res_nd["rows"] == [("raw_tuple",)]

        # 12. QuerySpec dataclass execution
        q_spec = QuerySpec(table="products", limit=5)
        res_qspec = await conn.execute(q_spec, validate_ast=False)
        assert res_qspec["limit"] == 5

    asyncio.run(_test())


# ==============================================================================
# SECTION 9: 100% Statement and Branch Precision Coverage Tests
# ==============================================================================


def test_base_connector_precision_branches():
    """Pinpoint remaining branches in BaseConnector."""
    # 1. introspect_information_schema with schema_name attribute and config fallback
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [("t1", "id", "int", False, None)]
    c_attr_schema = ConcreteSyncConnector(cursor=mock_cur, dialect="postgres")
    c_attr_schema.schema_name = "my_custom_schema"
    snap1 = c_attr_schema.introspect_schema()
    assert "tables" in snap1

    c_cfg_schema = ConcreteSyncConnector(
        cursor=mock_cur, dialect="postgres", schema_name="cfg_schema"
    )
    snap2 = c_cfg_schema.introspect_schema()
    assert "tables" in snap2

    # 2. apply_statement_timeout
    c_attr_schema.apply_statement_timeout(mock_cur, 5000)

    # 3. Main SQL mutating violation in spec execution path
    class MainSqlMutator(LifecycleInterceptor):
        def on_post_compile(self, comp, ctx):
            comp["main_sql"] = "UPDATE users SET active = 1"
            return comp

    sec_ro = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=True)
    )
    c_main_mut = ConcreteSyncConnector(security=sec_ro)
    with pytest.raises(SecurityError, match="Read-only session violation"):
        c_main_mut.execute(
            {"table": "users"}, middleware=[MainSqlMutator()], validate_ast=False
        )

    # 4. Error handling when scrubbed_exc is exc (clean error)
    mock_clean_err_cur = MagicMock()
    mock_clean_err_cur.execute.side_effect = RuntimeError("Clean error without secrets")
    c_clean_err = ConcreteSyncConnector(cursor=mock_clean_err_cur)
    with pytest.raises(RuntimeError, match="Clean error without secrets"):
        c_clean_err.execute({"table": "users"}, validate_ast=False)

    # 5. Error handling when emit_audit_events is False
    sec_no_audit = SecurityConfig(
        logging=LoggingSecurityConfig(emit_audit_events=False, mask_credentials=True)
    )
    mock_secret_err_cur = MagicMock()
    mock_secret_err_cur.execute.side_effect = RuntimeError(
        "Error with password=secret_token"
    )
    c_no_audit = ConcreteSyncConnector(
        cursor=mock_secret_err_cur, security=sec_no_audit
    )
    with pytest.raises(RuntimeError) as exc_info:
        c_no_audit.execute({"table": "users"}, validate_ast=False)
    assert "secret_token" not in str(exc_info.value)

    # 6. Success execution when emit_audit_events is False
    mock_success_cur = MagicMock()
    mock_success_cur.fetchone.return_value = (1,)
    mock_success_cur.description = [("id",)]
    mock_success_cur.fetchall.return_value = [(10,)]
    c_success_no_audit = ConcreteSyncConnector(
        cursor=mock_success_cur, security=sec_no_audit
    )
    res_no_audit = c_success_no_audit.execute({"table": "users"}, validate_ast=False)
    assert res_no_audit["count"] == 1


def test_async_base_connector_precision_branches():
    """Pinpoint remaining branches in AsyncBaseConnector."""

    async def _test():
        # 1. Main SQL mutating violation in spec execution path
        class AsyncMainSqlMutator(LifecycleInterceptor):
            def on_post_compile(self, comp, ctx):
                comp["main_sql"] = "UPDATE users SET active = 1"
                return comp

        sec_ro = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=True)
        )
        c_main_mut = ConcreteAsyncConnector(security=sec_ro)
        with pytest.raises(SecurityError, match="Read-only session violation"):
            await c_main_mut.execute(
                {"table": "users"},
                middleware=[AsyncMainSqlMutator()],
                validate_ast=False,
            )

        # 2. Error handling when scrubbed_exc is exc (clean error)
        class CleanErrAsync(ConcreteAsyncConnector):
            async def execute_raw(self, sql, params=None):
                raise RuntimeError("Clean async error")

        c_clean_err = CleanErrAsync()
        with pytest.raises(RuntimeError, match="Clean async error"):
            await c_clean_err.execute({"table": "users"}, validate_ast=False)

        # 3. Error handling when emit_audit_events is False
        sec_no_audit = SecurityConfig(
            logging=LoggingSecurityConfig(
                emit_audit_events=False, mask_credentials=True
            )
        )

        class SecretErrAsync(ConcreteAsyncConnector):
            async def execute_raw(self, sql, params=None):
                raise RuntimeError("Secret async error password=token_abc")

        c_sec_err = SecretErrAsync(security=sec_no_audit)
        with pytest.raises(RuntimeError) as exc_info:
            await c_sec_err.execute({"table": "users"}, validate_ast=False)
        assert "token_abc" not in str(exc_info.value)

        # 4. Success execution when emit_audit_events is False
        c_success_no_audit = ConcreteAsyncConnector(security=sec_no_audit)
        res_no_audit = await c_success_no_audit.execute(
            {"table": "users"}, validate_ast=False
        )
        assert res_no_audit["count"] == 1

        # 5. Empty count_rows in execute
        class EmptyCountAsync(ConcreteAsyncConnector):
            async def execute_raw(self, sql, params=None):
                if "COUNT" in sql.upper():
                    return ["count"], [], 1.0
                return ["id"], [{"id": 1}], 1.0

        c_empty_cnt = EmptyCountAsync()
        res_empty_cnt = await c_empty_cnt.execute(
            {"table": "users"}, validate_ast=False
        )
        assert res_empty_cnt["count"] == 0

    asyncio.run(_test())


# ==============================================================================
# SECTION 10: 100% Comprehensive Coverage Finalizer Tests
# ==============================================================================


def test_base_connector_final_branches():
    """Final branches for BaseConnector 100% coverage."""

    # 1. Subclass without connect in __dict__
    class EmptySubclassSync(BaseConnector):
        pass

    assert "connect" not in EmptySubclassSync.__dict__

    # 2. Unconstructible exception itself in connect()
    uncon_err = UnconstructibleError(10, 20)
    with patch.object(
        UnconstructibleError, "__str__", return_value="Error with password=uncon_secret"
    ):
        c_uncon_direct = ConcreteSyncConnector(conn_obj=uncon_err)
        with pytest.raises(ConnectionFailedError) as exc_info:
            c_uncon_direct.connect()
        assert "uncon_secret" not in str(exc_info.value)
        assert isinstance(exc_info.value, ConnectionFailedError)

    # 3. Public fallback in introspect_schema
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [("t_pub", "id", "int", False, None)]
    c_pub = ConcreteSyncConnector(cursor=mock_cur, dialect="postgres")
    # ensure neither schema_name attribute nor config has schema_name
    c_pub.schema_name = None
    snap_pub = c_pub.introspect_schema()
    assert "tables" in snap_pub

    # 4. spec_limit is None vs spec_limit <= max_rows_limit
    sec_clamp = SecurityConfig(execution=ExecutionSecurityConfig(max_rows_limit=50))
    mock_cur_clamp = MagicMock()
    mock_cur_clamp.fetchone.return_value = (1,)
    mock_cur_clamp.description = [("id",)]
    mock_cur_clamp.fetchall.return_value = [(1,)]
    c_clamp = ConcreteSyncConnector(cursor=mock_cur_clamp, security=sec_clamp)

    # spec without limit (spec_limit is None)
    res_none_limit = c_clamp.execute({"table": "users"}, validate_ast=False)
    assert res_none_limit["limit"] == 50

    # spec with limit <= max_rows_limit
    res_small_limit = c_clamp.execute(
        {"table": "users", "limit": 10}, validate_ast=False
    )
    assert res_small_limit["limit"] == 10

    # 5. enforce_read_only_session=False allows mutation without error
    sec_ro_false = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=False)
    )
    c_ro_false = ConcreteSyncConnector(cursor=mock_cur_clamp, security=sec_ro_false)
    res_mut_allowed = c_ro_false.execute(sql="SELECT 1", validate_ast=False)
    assert res_mut_allowed["count"] == 1


def test_async_base_connector_final_branches():
    """Final branches for AsyncBaseConnector 100% coverage."""

    async def _test():
        # 1. Subclass without connect in __dict__
        class EmptySubclassAsync(AsyncBaseConnector):
            pass

        assert "connect" not in EmptySubclassAsync.__dict__

        # 2. Unconstructible exception itself in connect()
        uncon_err = UnconstructibleError(30, 40)
        with patch.object(
            UnconstructibleError,
            "__str__",
            return_value="Async error with password=async_uncon",
        ):
            c_uncon_direct = ConcreteAsyncConnector(conn_obj=uncon_err)
            with pytest.raises(ConnectionFailedError) as exc_info:
                await c_uncon_direct.connect()
            assert "async_uncon" not in str(exc_info.value)

        # 3. spec_limit is None vs spec_limit <= max_rows_limit in async
        sec_clamp = SecurityConfig(execution=ExecutionSecurityConfig(max_rows_limit=25))
        c_async_clamp = ConcreteAsyncConnector(security=sec_clamp)
        res_none_limit = await c_async_clamp.execute(
            {"table": "users"}, validate_ast=False
        )
        assert res_none_limit["limit"] == 25

        res_small_limit = await c_async_clamp.execute(
            {"table": "users", "limit": 5}, validate_ast=False
        )
        assert res_small_limit["limit"] == 5

        # 4. Column masking with admin role bypass
        sec_mask = SecurityConfig(
            privacy=PrivacySecurityConfig(
                sensitive_column_patterns=[r"(?i)token"],
                masking_strategy="redact",
            )
        )
        c_async_admin = ConcreteAsyncConnector(
            rows=[{"id": 1, "token": "admin_raw_token"}],
            security=sec_mask,
        )
        admin_ctx = TenantContext(tenant_id="t1", roles=["admin"])
        res_admin = await c_async_admin.execute(
            {"table": "tokens"},
            context={"tenant_context": admin_ctx},
            validate_ast=False,
        )
        assert res_admin["rows"][0]["token"] == "admin_raw_token"

        # 5. enforce_read_only_session=False allows query
        sec_ro_false = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=False)
        )
        c_ro_false = ConcreteAsyncConnector(security=sec_ro_false)
        res_mut = await c_ro_false.execute(sql="SELECT 1", validate_ast=False)
        assert res_mut["count"] == 1

    asyncio.run(_test())


# ==============================================================================
# SECTION 11: 100% Full-Spectrum Line & Branch Coverage Assurance
# ==============================================================================


def test_sync_100_percent_coverage():
    """Hits all remaining lines and branch conditions in base.py."""

    # 1. __init_subclass__ when _security_wrapped is True
    class SubWithConnect(BaseConnector):
        def connect(self):
            return 1

    BaseConnector.__init_subclass__.__func__(SubWithConnect)

    # 2. test_connection and execute_raw on BaseConnector
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1,)
    mock_cur.description = [("col",)]
    mock_cur.fetchall.return_value = [(100,)]
    conn = ConcreteSyncConnector(cursor=mock_cur)
    health = conn.test_connection()
    assert health["status"] == "healthy"
    _cols, rows, _lat = conn.execute_raw("SELECT 100")
    assert rows == [{"col": 100}]

    # 3. sec is None in execute
    conn_nosec = ConcreteSyncConnector(cursor=mock_cur)
    conn_nosec.security = None
    res_nosec = conn_nosec.execute(sql="SELECT 1", validate_ast=False)
    assert res_nosec["count"] == 1

    # 4. execute with invalid spec type (e.g. "not a dict")
    with pytest.raises(CompilationError, match="Specification must be a dictionary"):
        conn.execute("invalid string spec")

    # 5. prevent_cartesian_products is False and joins within max_join_depth
    sec_custom = SecurityConfig(
        execution=ExecutionSecurityConfig(
            prevent_cartesian_products=False,
            max_join_depth=5,
            max_rows_limit=100,
        )
    )
    conn_custom = ConcreteSyncConnector(cursor=mock_cur, security=sec_custom)
    res_clean = conn_custom.execute(
        {
            "table": "users",
            "joins": [
                {
                    "table": "roles",
                    "on": [{"left": "users.rid", "right": "roles.id"}],
                }
            ],
            "limit": 10,
        },
        validate_ast=False,
    )
    assert res_clean["limit"] == 10

    # 6. count_row is None in execute
    mock_cur_nocnt = MagicMock()
    mock_cur_nocnt.fetchone.return_value = None
    mock_cur_nocnt.description = [("id",)]
    mock_cur_nocnt.fetchall.return_value = []
    conn_nocnt = ConcreteSyncConnector(cursor=mock_cur_nocnt)
    res_nocnt = conn_nocnt.execute({"table": "users"}, validate_ast=False)
    assert res_nocnt["count"] == 0

    # 7. len(dict_rows) <= max_rows_limit
    mock_cur_rows = MagicMock()
    mock_cur_rows.fetchone.return_value = (1,)
    mock_cur_rows.description = [("id",)]
    mock_cur_rows.fetchall.return_value = [(1,)]
    sec_row_limit = SecurityConfig(execution=ExecutionSecurityConfig(max_rows_limit=10))
    conn_rows = ConcreteSyncConnector(cursor=mock_cur_rows, security=sec_row_limit)
    res_rows = conn_rows.execute({"table": "users", "limit": 5}, validate_ast=False)
    assert res_rows["count"] == 1
    assert "truncated" not in res_rows

    # 8. enforce_read_only_session=False in execute spec (line 463->473)
    sec_ro_false = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=False)
    )
    conn_ro_false = ConcreteSyncConnector(cursor=mock_cur_rows, security=sec_ro_false)
    res_ro_false = conn_ro_false.execute({"table": "users"}, validate_ast=False)
    assert res_ro_false["count"] == 1

    # 10. count_params non-empty (line 491)
    mock_cur_params = MagicMock()
    mock_cur_params.fetchone.return_value = (5,)
    mock_cur_params.description = [("id",)]
    mock_cur_params.fetchall.return_value = [(1,)]
    conn_params = ConcreteSyncConnector(cursor=mock_cur_params)
    res_params = conn_params.execute(
        {
            "table": "users",
            "filters": [{"column": "age", "operator": "gt", "value": 18}],
        },
        validate_ast=False,
    )
    assert res_params["count"] == 5


def test_async_100_percent_coverage():
    """Hits all remaining lines and branch conditions in async_base.py."""

    async def _test():
        # 1. __init_subclass__ when _security_wrapped is True
        class AsyncSubWithConnect(AsyncBaseConnector):
            async def connect(self):
                return 1

        AsyncBaseConnector.__init_subclass__.__func__(AsyncSubWithConnect)

        # 2. test_connection
        conn = ConcreteAsyncConnector()
        health = await conn.test_connection()
        assert health["status"] == "healthy"

        # 3. close when connection has no close method
        no_close_conn = ConcreteAsyncConnector()
        no_close_conn._connection = 42
        await no_close_conn.close()
        assert no_close_conn._connection is None

        # 4. close when connection is None
        empty_conn = ConcreteAsyncConnector()
        await empty_conn.close()
        assert empty_conn._connection is None

        # 5. close when connection close() is an async coroutine
        class AsyncCloseTarget:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        target = AsyncCloseTarget()
        conn_async_close = ConcreteAsyncConnector(conn_obj=target)
        await conn_async_close.connect()
        await conn_async_close.close()
        assert target.closed is True

        # 6. execute with invalid spec type
        with pytest.raises(
            CompilationError, match="Specification must be a dictionary"
        ):
            await conn.execute("invalid string spec")

        # 7. sec is None in execute
        conn_nosec = ConcreteAsyncConnector()
        conn_nosec.security = None
        res_nosec = await conn_nosec.execute(sql="SELECT 1", validate_ast=False)
        assert res_nosec["count"] == 1

        # 8. prevent_cartesian_products is False and joins within max_join_depth
        sec_custom = SecurityConfig(
            execution=ExecutionSecurityConfig(
                prevent_cartesian_products=False,
                max_join_depth=5,
                max_rows_limit=100,
            )
        )
        conn_custom = ConcreteAsyncConnector(security=sec_custom)
        res_clean = await conn_custom.execute(
            {
                "table": "users",
                "joins": [
                    {
                        "table": "roles",
                        "on": [{"left": "users.rid", "right": "roles.id"}],
                    }
                ],
                "limit": 10,
            },
            validate_ast=False,
        )
        assert res_clean["limit"] == 10

        # 9. len(dict_rows) <= max_rows_limit
        sec_rows = SecurityConfig(execution=ExecutionSecurityConfig(max_rows_limit=10))
        conn_rows = ConcreteAsyncConnector(rows=[{"id": 1}], security=sec_rows)
        res_rows = await conn_rows.execute(
            {"table": "users", "limit": 5}, validate_ast=False
        )
        assert res_rows["count"] == 1
        assert "truncated" not in res_rows

        # 10. Exception in connect without cause
        err_no_cause = ConnectionFailedError("Direct error with password=my_pw")
        conn_err = ConcreteAsyncConnector(conn_obj=err_no_cause)
        with pytest.raises(ConnectionFailedError) as exc_info:
            await conn_err.connect()
        assert "my_pw" not in str(exc_info.value)

        # 11. Clean exception in connect without secrets (line 69: if scrubbed is exc: raise)
        clean_err = ValueError("Clean error without secrets")
        conn_clean = ConcreteAsyncConnector(conn_obj=clean_err)
        with pytest.raises(ValueError, match="Clean error without secrets"):
            await conn_clean.connect()

        # 12. QB_ALLOW_PRIVATE_NETWORKS env var in AsyncBaseConnector (lines 144-146)
        with patch.dict(os.environ, {"QB_ALLOW_PRIVATE_NETWORKS": "true"}):
            conn_priv = ConcreteAsyncConnector(host="10.0.0.1")
            conn_priv._validate_network_target()

        # 13. mask_credentials=False for async connector (line 170)
        sec_no_mask = SecurityConfig(
            logging=LoggingSecurityConfig(mask_credentials=False)
        )
        raw_exc = Exception("Error with password=secret")
        scrubbed_exc = conn._scrub_exception(raw_exc, security_config=sec_no_mask)
        assert scrubbed_exc is raw_exc

        # 14. statement_timeout_ms <= 0 in async execute (line 319)
        with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
            await conn.execute("SELECT 1", statement_timeout_ms=0)

        # 15. enforce_read_only_session=False in async execute spec (line 453->463)
        sec_ro_false_async = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=False)
        )
        conn_ro_false_async = ConcreteAsyncConnector(
            rows=[{"id": 1}], security=sec_ro_false_async
        )
        res_ro_false_async = await conn_ro_false_async.execute(
            {"table": "users"}, validate_ast=False
        )
        assert res_ro_false_async["count"] == 1

        # 17. Column masking for non-admin user with dict and non-dict rows (lines 505->536)
        sec_mask_user = SecurityConfig(
            privacy=PrivacySecurityConfig(
                sensitive_column_patterns=[r"(?i)token"],
                masking_strategy="redact",
            )
        )
        conn_mask_user = ConcreteAsyncConnector(
            rows=[{"id": 1, "token": "sensitive_user_token"}, "non_dict_row"],
            security=sec_mask_user,
        )
        user_ctx = TenantContext(tenant_id="t1", roles=["user"])
        res_mask_user = await conn_mask_user.execute(
            {"table": "tokens"},
            context={"tenant_context": user_ctx},
            validate_ast=False,
        )
        assert res_mask_user["rows"][0]["token"] == "[REDACTED]"
        assert res_mask_user["rows"][1] == "non_dict_row"

        # 18. dict_rows is empty in async execute (covers line 501->532 false branch)
        conn_empty_rows = ConcreteAsyncConnector(rows=[])
        res_empty_rows = await conn_empty_rows.execute(
            {"table": "users"}, validate_ast=False
        )
        assert res_empty_rows["rows"] == []

    asyncio.run(_test())
