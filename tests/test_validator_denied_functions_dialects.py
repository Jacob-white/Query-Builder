"""Functions that read files, reach other systems, or change state from inside a SELECT.

Found by probing the validator with dialect-specific queries: each query below was accepted
before the deny list was extended. Every attack has a benign control (a column, alias or table
that merely shares the name) so the list is not satisfied by rejecting everything.
"""

from __future__ import annotations

import pytest

from query_builder.ast_validator import validate_sql_ast

ATTACKS = [
    # DuckDB
    ("duckdb", "SELECT * FROM glob('/*')"),
    ("duckdb", "SELECT getenv('AWS_SECRET_ACCESS_KEY')"),
    ("duckdb", "SELECT * FROM duckdb_secrets()"),
    ("duckdb", "SELECT which_secret('s3://b/x', 's3')"),
    ("duckdb", "SELECT * FROM sqlite_scan('/data/x.db', 't')"),
    ("duckdb", "SELECT * FROM postgres_scan('host=db', 'public', 't')"),
    ("duckdb", "SELECT * FROM mysql_scan('host=db', 'd', 't')"),
    ("duckdb", "SELECT * FROM iceberg_scan('/warehouse/t')"),
    ("duckdb", "SELECT * FROM delta_scan('/lake/t')"),
    ("duckdb", "SELECT * FROM st_read('/data/x.shp')"),
    ("duckdb", "SELECT * FROM read_xlsx('/data/x.xlsx')"),
    # ClickHouse table functions
    ("clickhouse", "SELECT * FROM mongodb('h:27017', 'd', 'c', 'u', 'p', 'a Int32')"),
    ("clickhouse", "SELECT * FROM redis('h:6379', 'k', 'k String')"),
    ("clickhouse", "SELECT * FROM azureBlobStorage('c', 'k', 'b', 'f')"),
    ("clickhouse", "SELECT * FROM gcs('http://storage/x')"),
    ("clickhouse", "SELECT * FROM deltaLake('http://x/t')"),
    ("clickhouse", "SELECT * FROM iceberg('http://x/t')"),
    ("clickhouse", "SELECT * FROM hudi('http://x/t')"),
    ("clickhouse", "SELECT * FROM sqlite('/data/x.db', 't')"),
    ("clickhouse", "SELECT * FROM urlCluster('c', 'http://x', 'CSV', 'a Int32')"),
    ("clickhouse", "SELECT * FROM fileCluster('c', '/x', 'CSV', 'a Int32')"),
    ("clickhouse", "SELECT * FROM clusterAllReplicas('c', 'd', 't')"),
    # BigQuery / SQL Server
    ("bigquery", "SELECT * FROM EXTERNAL_QUERY('conn', 'SELECT 1')"),
    ("tsql", "SELECT * FROM fn_xe_file_target_read_file('x', 'y', NULL, NULL)"),
    ("tsql", "SELECT * FROM fn_get_audit_file('x', NULL, NULL)"),
    # State changes and locks reachable from a SELECT
    ("postgres", "SELECT nextval('orders_id_seq')"),
    ("postgres", "SELECT setval('orders_id_seq', 1)"),
    ("postgres", "SELECT pg_notify('chan', 'payload')"),
    ("postgres", "SELECT pg_advisory_lock(1)"),
    ("postgres", "SELECT pg_advisory_xact_lock(1)"),
    ("postgres", "SELECT pg_logical_emit_message(true, 'a', 'b')"),
    ("postgres", "SELECT pg_backup_start('x')"),
    ("postgres", "SELECT pg_switch_wal()"),
    ("mysql", "SELECT GET_LOCK('a', 10)"),
    ("mysql", "SELECT RELEASE_LOCK('a')"),
]

# Same names used as plain identifiers, and ordinary scalar calls.
BENIGN = [
    ("duckdb", "SELECT redis, gcs, getenv FROM t"),
    ("duckdb", "SELECT a FROM t WHERE name GLOB 'x*'"),
    ("clickhouse", "SELECT redis, sqlite FROM t"),
    ("postgres", "SELECT a FROM t ORDER BY a"),
    ("postgres", "SELECT current_setting('server_version')"),
    ("postgres", "SELECT * FROM t AS gcs"),
    ("mysql", "SELECT lock_name FROM locks"),
    ("tsql", "SELECT * FROM t WHERE c = 'fn_get_audit_file'"),
]


@pytest.mark.parametrize(("dialect", "sql"), ATTACKS)
def test_dangerous_function_is_rejected(dialect, sql):
    result = validate_sql_ast(sql, dialect=dialect)
    assert not result["valid"], sql
    assert any("Function" in v for v in result["violations"]), result["violations"]


@pytest.mark.parametrize(("dialect", "sql"), ATTACKS)
def test_dangerous_function_is_rejected_without_a_dialect(dialect, sql):
    # No dialect hint (the common case for callers that do not know the engine).
    assert not validate_sql_ast(sql)["valid"], sql


@pytest.mark.parametrize(("dialect", "sql"), BENIGN)
def test_control_same_names_as_identifiers_stay_valid(dialect, sql):
    result = validate_sql_ast(sql, dialect=dialect)
    assert result["valid"], (sql, result["violations"])


def test_qualified_call_is_rejected():
    assert not validate_sql_ast("SELECT main.getenv('HOME')", dialect="duckdb")["valid"]
    assert not validate_sql_ast("SELECT pg_catalog.nextval('s')", dialect="postgres")[
        "valid"
    ]
