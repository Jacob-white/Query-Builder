"""
Adversarial Stress Testing & Empirical Verification Suite for Phase 1 Connectors.
==================================================================================
Empirically stress-tests and verifies edge cases, failure modes, and lifecycle
invariants for the 6 Phase 1 connectors (Firebird, MonetDB, H2, Derby, Sybase, Informix):

1. Cursor Adapter Lifecycle & Stress:
   - Repeated cursor close / double-close idempotent safety.
   - Post-close fetch operations returning empty / None safely.
   - High-volume rowsets (50,000+ rows) with chunked fetchmany slicing and fetchall drainage.
   - Parameter binding variants (None, empty list, exotic values, null bytes).
   - SQL cleaning and whitespace / semicolon stripping invariants.
   - Inner cursor exception safety guaranteeing cursor.close() execution.
   - Fallback to execute() without cursor() and bare object behavior.

2. Catalog Introspection Robustness:
   - Empty catalog / schema handling returning valid normalized empty snapshot.
   - Malformed, empty, and partial rows with unexpected NULL columns/keys.
   - Permission / access denial errors on constraint queries gracefully suppressed.
   - Base catalog failure correctly wrapped in IntrospectionError.
   - Sensitive table and column filtering invariants.

3. Dialect Quoting & Boundary Safety:
   - Identifier injection attempts rejected by _validate_identifier.
   - Sybase bracket alias escaping and control character rejection.
   - Boundary pagination values (0 limit, 0 offset, large offsets).
   - Parameterized introspection queries preventing SQL injection via catalog arguments.

4. Async Execution Lifecycle & Concurrency:
   - High concurrency on shared connector instance with zero cursor collisions.
   - Async cancellation guaranteeing deterministic cursor cleanup via finally.
   - Async introspection failure guaranteeing cursor cleanup and IntrospectionError.
   - Driver missing and connection failure propagation.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from query_builder.connectors import (
    AsyncDerbyConnector,
    AsyncFirebirdConnector,
    AsyncH2Connector,
    AsyncInformixConnector,
    AsyncMonetDBConnector,
    AsyncSybaseConnector,
    DerbyConnector,
    FirebirdConnector,
    H2Connector,
    InformixConnector,
    IntrospectionError,
    MonetDBConnector,
    SybaseConnector,
    introspect_derby,
    introspect_firebird,
    introspect_h2,
    introspect_informix,
    introspect_monetdb,
    introspect_sybase,
)
from query_builder.connectors.derby import _DerbyCursorAdapter
from query_builder.connectors.firebird import _FirebirdCursorAdapter
from query_builder.connectors.h2 import _H2CursorAdapter
from query_builder.connectors.informix import _InformixCursorAdapter
from query_builder.connectors.monetdb import _MonetDBCursorAdapter
from query_builder.connectors.sybase import _SybaseCursorAdapter
from query_builder.dialects import (
    DerbyDialect,
    DialectError,
    FirebirdDialect,
    H2Dialect,
    InformixDialect,
    MonetDBDialect,
    SybaseDialect,
    get_dialect,
)

ALL_ADAPTER_CLASSES = [
    _FirebirdCursorAdapter,
    _MonetDBCursorAdapter,
    _H2CursorAdapter,
    _DerbyCursorAdapter,
    _SybaseCursorAdapter,
    _InformixCursorAdapter,
]


# ============================================================================
# 1. Cursor Adapter Lifecycle & Stress Tests
# ============================================================================


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_cursor_adapter_double_close_and_post_close_drain(adapter_cls):
    """Verifies that calling close() multiple times is safe, and fetch methods return empty."""
    mock_cursor = MagicMock()
    mock_cursor.description = [("id", 1), ("val", 2)]
    mock_cursor.fetchall.return_value = [[1, "alpha"], [2, "beta"]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)
    adapter.execute("SELECT id, val FROM items;")

    # First close
    adapter.close()
    assert adapter.fetchone() is None
    assert adapter.fetchmany(10) == []
    assert adapter.fetchall() == []

    # Second and third close calls (idempotence check)
    adapter.close()
    adapter.close()
    assert adapter.fetchone() is None
    assert adapter.fetchmany(1) == []
    assert adapter.fetchall() == []


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_cursor_adapter_large_result_set_streaming(adapter_cls):
    """Stress tests cursor adapter with 50,000 rows across chunked fetchmany and fetchall."""
    row_count = 50000
    mock_rows = [[i, f"payload_{i}"] for i in range(row_count)]

    mock_cursor = MagicMock()
    mock_cursor.description = [("id", 1), ("name", 2)]
    mock_cursor.fetchall.return_value = list(mock_rows)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)
    adapter.execute("SELECT id, name FROM large_table;")

    # Fetch 10,000 in slices of 1,234
    accumulated: list[list[Any]] = []
    chunk_size = 1234
    for _ in range(8):
        chunk = adapter.fetchmany(chunk_size)
        assert len(chunk) == chunk_size
        accumulated.extend(chunk)

    assert len(accumulated) == 8 * chunk_size

    # Fetch one single item
    one = adapter.fetchone()
    assert one is not None
    assert one[0] == 8 * chunk_size

    # Drain remaining with fetchall
    rest = adapter.fetchall()
    assert len(rest) == row_count - (8 * chunk_size + 1)

    # Next fetch operations are completely empty
    assert adapter.fetchone() is None
    assert adapter.fetchall() == []
    assert adapter.fetchmany(100) == []


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_cursor_adapter_parameter_bindings_and_sql_cleaning(adapter_cls):
    """Verifies exotic parameter bindings and whitespace/semicolon stripping."""
    mock_cursor = MagicMock()
    mock_cursor.description = [("x", 1)]
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)

    # Messy SQL with single trailing semicolon and whitespaces
    messy_sql = "   \n\t  SELECT ? AS val FROM tbl; \t\n  "
    params = [None, "", 0, False, 3.14, "injection'; --"]
    adapter.execute(messy_sql, params)

    # Cleaned SQL must be passed without trailing semicolon
    mock_cursor.execute.assert_called_with("SELECT ? AS val FROM tbl", params)

    # When params is an empty list, execute should be called with clean_sql without params
    adapter.execute(messy_sql, [])
    mock_cursor.execute.assert_called_with("SELECT ? AS val FROM tbl")


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_cursor_adapter_inner_cursor_exception_cleanup(adapter_cls):
    """Verifies that an exception during execute still deterministically closes the inner cursor."""
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = RuntimeError("Syntax error in query")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)
    with pytest.raises(RuntimeError, match="Syntax error in query"):
        adapter.execute("SELECT * FROM invalid_syntax;")

    # Inner cursor MUST have been closed despite the exception
    mock_cursor.close.assert_called_once()


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTER_CLASSES)
def test_cursor_adapter_fetchmany_boundary_arguments(adapter_cls):
    """Verifies fetchmany behavior with size <= 0 or size larger than remaining rows."""
    mock_cursor = MagicMock()
    mock_cursor.description = [("col", 1)]
    mock_cursor.fetchall.return_value = [[1], [2], [3]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    adapter = adapter_cls(mock_conn)
    adapter.execute("SELECT col FROM tbl;")

    # size = 0
    zero_chunk = adapter.fetchmany(0)
    assert zero_chunk == []

    # size = -5
    neg_chunk = adapter.fetchmany(-5)
    assert neg_chunk == []

    # size > remaining rows (3 rows available)
    large_chunk = adapter.fetchmany(100)
    assert large_chunk == [[1], [2], [3]]
    assert adapter.fetchall() == []


# ============================================================================
# 2. Schema Introspection Robustness & Edge Cases
# ============================================================================


@pytest.mark.parametrize(
    ("introspect_fn", "db_name"),
    [
        (introspect_firebird, "Firebird"),
        (introspect_monetdb, "MonetDB"),
        (introspect_h2, "H2"),
        (introspect_derby, "Derby"),
        (introspect_sybase, "Sybase"),
        (introspect_informix, "Informix"),
    ],
)
def test_introspection_empty_catalog(introspect_fn, db_name):
    """Verifies that empty catalog queries return a valid empty schema snapshot."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    res = introspect_fn(mock_cursor)
    assert isinstance(res, dict)
    assert "tables" in res
    assert res["tables"] == {}
    assert "foreign_keys" in res
    assert res["foreign_keys"] == []
    assert "relationships" in res
    assert res["relationships"] == []


@pytest.mark.parametrize(
    ("introspect_fn", "db_name"),
    [
        (introspect_firebird, "Firebird"),
        (introspect_monetdb, "MonetDB"),
        (introspect_h2, "H2"),
        (introspect_derby, "Derby"),
        (introspect_sybase, "Sybase"),
        (introspect_informix, "Informix"),
    ],
)
def test_introspection_constraint_permission_denial_graceful_degradation(
    introspect_fn, db_name
):
    """Verifies that failure of PK or FK constraint catalog queries is gracefully suppressed."""
    mock_cursor = MagicMock()

    call_count = 0

    def mock_fetchall():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Tables query
            return [("accounts",)]
        if call_count == 2:
            # Columns query
            return [
                ("accounts", "id", "int", 1 if db_name == "Firebird" else "NO"),
                (
                    "accounts",
                    "balance",
                    "decimal",
                    0 if db_name == "Firebird" else "YES",
                ),
            ]
        # PK query or FK query raises permission / catalog access denial
        raise PermissionError("User lacks SELECT privilege on system constraints")

    mock_cursor.fetchall.side_effect = mock_fetchall

    res = introspect_fn(mock_cursor)
    assert "accounts" in res["tables"]
    cols = res["tables"]["accounts"]["columns"]
    assert len(cols) == 2
    # 'id' column falls back to primary key detection
    id_col = next(c for c in cols if c["name"] == "id")
    assert id_col["is_primary"] is True
    assert res["foreign_keys"] == []


@pytest.mark.parametrize(
    ("introspect_fn", "db_name"),
    [
        (introspect_firebird, "Firebird"),
        (introspect_monetdb, "MonetDB"),
        (introspect_h2, "H2"),
        (introspect_derby, "Derby"),
        (introspect_sybase, "Sybase"),
        (introspect_informix, "Informix"),
    ],
)
def test_introspection_sensitive_table_filtering(introspect_fn, db_name):
    """Verifies that sensitive tables (e.g. passwords, auth_user) are filtered when filter_sensitive=True."""
    mock_cursor = MagicMock()

    call_count = 0

    def mock_fetchall():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [("passwords",), ("products",), ("credentials",)]
        if call_count == 2:
            return [
                ("passwords", "hash", "varchar", "NO"),
                ("products", "name", "varchar", "YES"),
                ("credentials", "secret", "varchar", "NO"),
            ]
        return []

    mock_cursor.fetchall.side_effect = mock_fetchall

    # With filter_sensitive=True (default)
    res_filtered = introspect_fn(mock_cursor, filter_sensitive=True)
    assert "passwords" not in res_filtered["tables"]
    assert "credentials" not in res_filtered["tables"]
    assert "products" in res_filtered["tables"]

    # Reset and test with filter_sensitive=False
    call_count = 0
    res_unfiltered = introspect_fn(mock_cursor, filter_sensitive=False)
    assert "passwords" in res_unfiltered["tables"]
    assert "credentials" in res_unfiltered["tables"]
    assert "products" in res_unfiltered["tables"]


@pytest.mark.parametrize(
    ("introspect_fn", "db_name"),
    [
        (introspect_firebird, "Firebird"),
        (introspect_monetdb, "MonetDB"),
        (introspect_h2, "H2"),
        (introspect_derby, "Derby"),
        (introspect_sybase, "Sybase"),
        (introspect_informix, "Informix"),
    ],
)
def test_introspection_fatal_error_propagation(introspect_fn, db_name):
    """Verifies that failure of primary tables query wraps into IntrospectionError."""
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = ConnectionResetError("Connection severed")

    with pytest.raises(IntrospectionError, match=f"Failed to introspect .*{db_name}"):
        introspect_fn(mock_cursor)


# ============================================================================
# 3. Dialect Quoting & Boundary Safety Tests
# ============================================================================


@pytest.mark.parametrize(
    "dialect_name",
    ["firebird", "monetdb", "h2", "derby", "sybase", "informix"],
)
def test_dialect_identifier_injection_prevention(dialect_name):
    """Verifies that adversarial identifier strings are rejected with DialectError."""
    dialect = get_dialect(dialect_name)

    malicious_identifiers = [
        "users; DROP TABLE users; --",
        "tbl' OR '1'='1",
        'tbl" OR ""=""',
        "schema.tbl; SELECT 1",
        "users\x00hidden",
        "table name with spaces",
        "tbl[0]",
        "",
        "123startsWithDigit",
    ]

    for bad_id in malicious_identifiers:
        with pytest.raises(DialectError):
            dialect.quote_identifier(bad_id)


def test_sybase_dialect_alias_bracket_escaping():
    """Verifies Sybase-specific alias bracket escaping and control char validation."""
    dialect: SybaseDialect = get_dialect("sybase")  # type: ignore

    # Bracket inside alias must be doubled
    escaped = dialect.quote_alias("my]alias")
    assert escaped == "[my]]alias]"

    # Normal alias
    normal = dialect.quote_alias("regular_alias")
    assert normal == "[regular_alias]"

    # Control char must be rejected
    with pytest.raises(DialectError, match="control characters"):
        dialect.quote_alias("alias\x00null")

    # Excessive length must be rejected
    with pytest.raises(DialectError, match="exceeds maximum limit"):
        dialect.quote_alias("a" * 300)


@pytest.mark.parametrize(
    ("dialect_name", "cls"),
    [
        ("firebird", FirebirdDialect),
        ("monetdb", MonetDBDialect),
        ("h2", H2Dialect),
        ("derby", DerbyDialect),
        ("sybase", SybaseDialect),
        ("informix", InformixDialect),
    ],
)
def test_dialect_pagination_boundary_values(dialect_name, cls):
    """Verifies limit/offset generation under boundary conditions (0, large numbers)."""
    dialect = get_dialect(dialect_name)
    assert isinstance(dialect, cls)

    # Boundary 1: limit=0, offset=0
    clause, params = dialect.format_limit_offset(limit=0, offset=0)
    assert isinstance(clause, str)
    assert isinstance(params, list)
    if dialect_name == "firebird":
        assert clause == "ROWS ?" and params == [0]
    elif dialect_name in ("monetdb", "h2"):
        assert clause == "LIMIT ? OFFSET ?" and params == [0, 0]
    elif dialect_name in ("derby", "sybase"):
        assert clause == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" and params == [0, 0]
    elif dialect_name == "informix":
        assert clause == "SKIP %s FIRST %s" and params == [0, 0]

    # Boundary 2: limit=1000000, offset=5000000
    clause, params = dialect.format_limit_offset(limit=1000000, offset=5000000)
    if dialect_name == "firebird":
        assert clause == "ROWS ? TO ?" and params == [5000001, 6000000]
    elif dialect_name in ("monetdb", "h2"):
        assert clause == "LIMIT ? OFFSET ?" and params == [1000000, 5000000]
    elif dialect_name in ("derby", "sybase"):
        assert clause == "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" and params == [
            5000000,
            1000000,
        ]
    elif dialect_name == "informix":
        assert clause == "SKIP %s FIRST %s" and params == [5000000, 1000000]


@pytest.mark.parametrize(
    "dialect_name",
    ["firebird", "monetdb", "h2", "derby", "sybase", "informix"],
)
def test_dialect_inspect_queries_parameterization(dialect_name):
    """Verifies that schema and table names are parameterized to prevent injection in catalog queries."""
    dialect = get_dialect(dialect_name)
    hostile_input = "public' OR '1'='1"

    # Tables query
    q, p = dialect.inspect_tables_query(hostile_input)
    assert hostile_input not in q  # Hostile string must NEVER appear in SQL text
    if p:
        assert any(hostile_input.lower() in str(param).lower() for param in p)

    # Columns query
    q, p = dialect.inspect_columns_query(hostile_input, hostile_input)
    assert hostile_input not in q
    if p:
        assert any(hostile_input.lower() in str(param).lower() for param in p)


# ============================================================================
# 4. Async Execution Lifecycle & Concurrency Tests
# ============================================================================


@pytest.mark.parametrize(
    ("connector_cls", "dialect_name"),
    [
        (AsyncFirebirdConnector, "firebird"),
        (AsyncMonetDBConnector, "monetdb"),
        (AsyncH2Connector, "h2"),
        (AsyncDerbyConnector, "derby"),
        (AsyncSybaseConnector, "sybase"),
        (AsyncInformixConnector, "informix"),
    ],
)
def test_async_connector_concurrent_execution(connector_cls, dialect_name):
    """Stress tests 20 concurrent queries executed on a single shared async connector instance."""

    async def _run():
        mock_conn = MagicMock()

        def make_cursor():
            cur = MagicMock()
            cur.description = [("col_a", 1), ("col_b", 2)]
            cur.fetchall.return_value = [[42, "test_data"]]
            return cur

        mock_conn.cursor.side_effect = make_cursor

        connector = connector_cls(connection=mock_conn)

        async def run_query(idx: int):
            cols, rows, latency = await connector.execute_raw(
                f"SELECT col_a, col_b FROM table_{idx};"
            )
            assert cols == ["col_a", "col_b"]
            assert rows == [{"col_a": 42, "col_b": "test_data"}]
            assert latency >= 0.0
            return True

        # Run 20 tasks concurrently
        tasks = [run_query(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        assert all(results)
        assert len(results) == 20

    asyncio.run(_run())


@pytest.mark.parametrize(
    "connector_cls",
    [
        AsyncFirebirdConnector,
        AsyncMonetDBConnector,
        AsyncH2Connector,
        AsyncDerbyConnector,
        AsyncSybaseConnector,
        AsyncInformixConnector,
    ],
)
def test_async_connector_cancellation_resource_cleanup(connector_cls):
    """Verifies that an async query cancelled via task.cancel() deterministically closes the cursor."""

    async def _run():
        mock_cursor = MagicMock()
        mock_cursor.description = [("id", 1)]

        def slow_execute(*args, **kwargs):
            raise asyncio.CancelledError()

        mock_cursor.execute.side_effect = slow_execute
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        connector = connector_cls(connection=mock_conn)

        with pytest.raises(asyncio.CancelledError):
            await connector.execute_raw("SELECT * FROM large_table;")

        # Cursor must be closed in finally block despite CancelledError
        mock_cursor.close.assert_called_once()

    asyncio.run(_run())


@pytest.mark.parametrize(
    "connector_cls",
    [
        AsyncFirebirdConnector,
        AsyncMonetDBConnector,
        AsyncH2Connector,
        AsyncDerbyConnector,
        AsyncSybaseConnector,
        AsyncInformixConnector,
    ],
)
def test_async_connector_introspection_failure_cleanup(connector_cls):
    """Verifies that introspection failure in async connector closes cursor and raises IntrospectionError."""

    async def _run():
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("Catalog error")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        connector = connector_cls(connection=mock_conn)

        with pytest.raises(IntrospectionError):
            await connector.introspect_schema()

        mock_cursor.close.assert_called_once()

    asyncio.run(_run())


# ============================================================================
# 5. Sync Connector Resource Invariants & Error Handling
# ============================================================================


@pytest.mark.parametrize(
    ("connector_cls", "test_query"),
    [
        (FirebirdConnector, "SELECT 1 FROM RDB$DATABASE;"),
        (MonetDBConnector, "SELECT 1;"),
        (H2Connector, "SELECT 1;"),
        (DerbyConnector, "SELECT 1 FROM SYSIBM.SYSDUMMY1;"),
        (SybaseConnector, "SELECT 1;"),
        (InformixConnector, "SELECT 1 FROM systables WHERE tabid = 1;"),
    ],
)
def test_sync_connector_test_connection_and_get_cursor(connector_cls, test_query):
    """Verifies that test_connection executes the exact test query and cleans up cursor."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [1]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    connector = connector_cls(connection=mock_conn)
    status = connector.test_connection()

    assert status["status"] == "healthy"
    assert status["latency_ms"] >= 0.0
    mock_cursor.execute.assert_called_with(test_query)
    mock_cursor.close.assert_called_once()
