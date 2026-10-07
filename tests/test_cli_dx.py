"""
Comprehensive Unit Tests for Extended CLI Suite (CI/CD AST Safety Linter & Schema Exporters).
=============================================================================================
Tests all CLI subcommands, flags, exit codes, output formatting (JSON and terminal text),
file I/O, error paths, and sync/async connector drivers.
"""

from __future__ import annotations

import json
from typing import Any

from query_builder.cli import main
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.registry import ConnectorRegistry
from query_builder.models import ColumnMeta, SchemaSnapshot, TableMeta

# ============================================================================
# 1. Validate Subcommand Tests
# ============================================================================


def test_cli_validate_raw_sql_safe(capsys):
    ret = main(["validate", "SELECT * FROM users"])
    assert ret == 0
    captured = capsys.readouterr()
    assert (
        "[PASS] AST validation succeeded. Safe read-only SELECT query." in captured.out
    )


def test_cli_validate_raw_sql_mutation(capsys):
    ret = main(["validate", "DELETE FROM users"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] AST validation failed:" in captured.out
    assert "Statement type: DELETE" in captured.out
    assert "Injection risk: CRITICAL" in captured.out
    assert "Violations:" in captured.out


def test_cli_validate_json_mode(capsys):
    ret = main(["validate", "--json", "SELECT * FROM users"])
    assert ret == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["valid"] is True
    assert res["injection_risk"] == "NONE"


def test_cli_validate_sql_file(capsys, tmp_path):
    sql_file = tmp_path / "query.sql"
    sql_file.write_text("SELECT id, name FROM users WHERE active = true;")

    ret = main(["validate", str(sql_file)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "[PASS]" in captured.out


def test_cli_validate_spec_file(capsys, tmp_path):
    # Declarative query spec JSON
    spec = {"table": "users", "columns": ["users.id", "users.email"]}
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    ret = main(["validate", str(spec_file)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "[PASS]" in captured.out

    # Raw SQL wrapped in JSON
    sql_json_file = tmp_path / "sql_spec.json"
    sql_json_file.write_text(json.dumps({"sql": "SELECT 1;"}))
    ret_sql = main(["validate", str(sql_json_file)])
    assert ret_sql == 0


def test_cli_validate_inline_json_spec(capsys):
    # Inline declarative spec
    ret = main(["validate", '{"table": "users", "columns": ["users.id"]}'])
    assert ret == 0
    captured = capsys.readouterr()
    assert "[PASS]" in captured.out

    # Inline JSON with "sql" key
    ret2 = main(["validate", '{"sql": "SELECT 42;"}'])
    assert ret2 == 0


def test_cli_validate_invalid_spec(capsys, tmp_path):
    bad_spec_file = tmp_path / "bad.json"
    bad_spec_file.write_text('{"table": "users", "joins": [{"invalid": true}]}')

    # In text mode
    ret = main(["validate", str(bad_spec_file)])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Validation error:" in captured.err

    # In JSON mode
    ret_json = main(["validate", "--json", str(bad_spec_file)])
    assert ret_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["valid"] is False
    assert payload["injection_risk"] == "CRITICAL"


def test_cli_validate_nonexistent_file(capsys):
    # In text mode
    ret = main(["validate", "nonexistent_query_file.sql"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Target file not found" in captured.err

    # In JSON mode
    ret_json = main(["validate", "--json", "nonexistent_spec.json"])
    assert ret_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["valid"] is False
    assert any("Target file not found" in v for v in payload["violations"])


def test_cli_validate_empty_target(capsys):
    ret = main(["validate", ""])
    assert ret == 1
    captured = capsys.readouterr()
    assert "No query target provided" in captured.err

    ret_json = main(["validate", "--json", ""])
    assert ret_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["valid"] is False


def test_cli_validate_allowed_schemas(capsys):
    # Allowed schema
    ret1 = main(
        [
            "validate",
            "--allowed-schemas",
            "public,analytics",
            "SELECT * FROM public.users",
        ]
    )
    assert ret1 == 0

    # Disallowed schema
    ret2 = main(
        [
            "validate",
            "--allowed-schemas",
            "analytics",
            "SELECT * FROM pg_catalog.pg_tables",
        ]
    )
    assert ret2 == 1


def test_cli_validate_restricted_tables(capsys):
    ret = main(
        [
            "validate",
            "--restricted-tables",
            "custom_secrets,audit_logs",
            "SELECT * FROM custom_secrets",
        ]
    )
    assert ret == 1


def test_cli_validate_disallow_cte(capsys):
    cte_query = "WITH cte AS (SELECT 1 AS x) SELECT x FROM cte"

    # With CTE allowed by default
    ret_ok = main(["validate", cte_query])
    assert ret_ok == 0

    # With CTE disallowed
    ret_disallow = main(["validate", "--disallow-cte", cte_query])
    assert ret_disallow == 1


def test_cli_validate_fail_on_risk_levels(capsys):
    # Safe query with CRITICAL threshold passes
    ret_safe = main(["validate", "--fail-on-risk", "CRITICAL", "SELECT 1"])
    assert ret_safe == 0

    # Malformed SQL with critical injection risk
    multi_stmt = "SELECT 1; DROP TABLE users;"

    ret_crit = main(["validate", "--fail-on-risk", "CRITICAL", multi_stmt])
    assert ret_crit == 1

    ret_high = main(["validate", "--fail-on-risk", "HIGH", multi_stmt])
    assert ret_high == 1


# ============================================================================
# 2. Compile Subcommand Tests
# ============================================================================


def test_cli_compile_output_file_and_text(capsys, tmp_path):
    spec = {"table": "orders", "columns": ["orders.id", "orders.total"]}
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    out_file = tmp_path / "out.sql"

    ret = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--dialect",
            "postgres",
            "--output",
            str(out_file),
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert "--- Main SQL ---" in captured.out
    assert out_file.exists()
    assert 'FROM "orders"' in out_file.read_text()


def test_cli_compile_json_mode(capsys, tmp_path):
    spec = {"table": "items", "columns": ["items.id"]}
    spec_file = tmp_path / "items_spec.json"
    spec_file.write_text(json.dumps(spec))
    out_json = tmp_path / "compiled.json"

    ret = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--json",
            "--output",
            str(out_json),
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "main_sql" in payload
    assert "params" in payload
    assert "count_sql" in payload
    assert payload["dialect"] == "postgres"
    assert out_json.exists()

    # Without --output
    ret2 = main(["compile", "--spec", str(spec_file), "--json"])
    assert ret2 == 0


def test_cli_compile_dialect_selection(capsys, tmp_path):
    spec = {"table": "users", "columns": ["users.name"]}
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    ret = main(["compile", "--spec", str(spec_file), "--dialect", "sqlite"])
    assert ret == 0
    captured = capsys.readouterr()
    assert 'FROM "users" "t1"' in captured.out


def test_cli_compile_error_handling(capsys, tmp_path):
    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{invalid json")

    # Text mode error
    ret = main(["compile", "--spec", str(broken_file)])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Compilation error:" in captured.err

    # JSON mode error
    ret_json = main(["compile", "--spec", str(broken_file), "--json"])
    assert ret_json == 1
    captured_json = capsys.readouterr()
    res = json.loads(captured_json.out)
    assert res["success"] is False


# ============================================================================
# 3. Test-Connection Subcommand Tests
# ============================================================================


def test_cli_test_connection_sqlite_sync(capsys):
    ret = main(["test-connection", "--connector", "sqlite"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "[OK] Connection to 'sqlite' successful" in captured.out


def test_cli_test_connection_json_mode(capsys):
    ret = main(["test-connection", "--connector", "sqlite", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "healthy"
    assert "latency_ms" in payload


def test_cli_test_connection_config_file_and_string(capsys, tmp_path):
    # Inline JSON config
    ret1 = main(
        [
            "test-connection",
            "--connector",
            "sqlite",
            "--config",
            '{"database": ":memory:"}',
        ]
    )
    assert ret1 == 0

    # Config file
    cfg_file = tmp_path / "db_config.json"
    cfg_file.write_text(json.dumps({"database": ":memory:"}))
    ret2 = main(["test-connection", "--connector", "sqlite", "--config", str(cfg_file)])
    assert ret2 == 0


def test_cli_test_connection_unknown_connector(capsys):
    ret = main(["test-connection", "--connector", "nonexistent_db"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "[ERROR] Connection to 'nonexistent_db' failed:" in captured.out

    ret_json = main(["test-connection", "--connector", "nonexistent_db", "--json"])
    assert ret_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["success"] is False
    assert payload["status"] == "unhealthy"


def test_cli_test_connection_async_connector(capsys):
    class MockAsyncConnector(AsyncBaseConnector):
        dialect_name = "async_mock"

        async def connect(self) -> Any:
            return None

        async def close(self) -> None:
            pass

        async def execute(self, spec, middleware=None):
            return {}

        async def test_connection(self):
            return {
                "success": True,
                "status": "healthy",
                "dialect": "async_mock",
                "latency_ms": 1.23,
            }

    ConnectorRegistry.register("mock_async_test", MockAsyncConnector)
    try:
        ret = main(["test-connection", "--connector", "mock_async_test"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "[OK] Connection to 'mock_async_test' successful" in captured.out
    finally:
        ConnectorRegistry.unregister("mock_async_test")


def test_cli_test_connection_unhealthy_status(capsys):
    class UnhealthyConnector(BaseConnector):
        def connect(self):
            return None

        def test_connection(self):
            return {"status": "unhealthy", "error": "Database is unreachable"}

    ConnectorRegistry.register("mock_unhealthy", UnhealthyConnector)
    try:
        ret = main(["test-connection", "--connector", "mock_unhealthy"])
        assert ret == 1
        captured = capsys.readouterr()
        assert (
            "[ERROR] Connection to 'mock_unhealthy' failed: Database is unreachable"
            in captured.out
        )
    finally:
        ConnectorRegistry.unregister("mock_unhealthy")


# ============================================================================
# 4. Introspect Subcommand Tests
# ============================================================================


def test_cli_introspect_sqlite(capsys, tmp_path):
    import sqlite3

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT, price REAL);"
    )
    conn.close()

    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            json.dumps({"database": str(db_path)}),
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert "[OK] Introspected 1 tables" in captured.out
    assert "products" in captured.out


def test_cli_introspect_json_mode(capsys, tmp_path):
    import sqlite3

    db_path = tmp_path / "test_json.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE customers (id INT, name TEXT);")
    conn.close()

    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            json.dumps({"database": str(db_path)}),
            "--json",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "tables" in payload
    assert "customers" in payload["tables"]


def test_cli_introspect_output_file(capsys, tmp_path):
    import sqlite3

    db_path = tmp_path / "test_out.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE sales (id INT, amount REAL);")
    conn.close()

    schema_out = tmp_path / "snapshot.json"
    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--config",
            json.dumps({"database": str(db_path)}),
            "--output",
            str(schema_out),
        ]
    )
    assert ret == 0
    assert schema_out.exists()
    data = json.loads(schema_out.read_text())
    assert "sales" in data["tables"]


def test_cli_introspect_filter_sensitive_flag(capsys):
    ret = main(
        [
            "introspect",
            "--connector",
            "sqlite",
            "--no-filter-sensitive",
            "--json",
        ]
    )
    assert ret == 0


def test_cli_introspect_async_connector(capsys):
    class MockAsyncIntrospectConnector(AsyncBaseConnector):
        dialect_name = "async_intro"

        async def connect(self) -> Any:
            return None

        async def close(self) -> None:
            pass

        async def execute(self, spec, middleware=None):
            return {}

        async def introspect_schema(self, filter_sensitive=True):
            return SchemaSnapshot(
                tables={
                    "metrics": TableMeta(
                        name="metrics",
                        columns=[ColumnMeta(name="id", data_type="int")],
                    )
                }
            )

    ConnectorRegistry.register("mock_async_intro", MockAsyncIntrospectConnector)
    try:
        ret = main(["introspect", "--connector", "mock_async_intro"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "[OK] Introspected 1 tables" in captured.out
    finally:
        ConnectorRegistry.unregister("mock_async_intro")


def test_cli_introspect_error(capsys):
    # In text mode
    ret = main(["introspect", "--connector", "unknown_connector_xyz"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Introspection error:" in captured.err

    # In JSON mode
    ret_json = main(["introspect", "--connector", "unknown_connector_xyz", "--json"])
    assert ret_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["success"] is False


# ============================================================================
# 5. Export-Schema Subcommand Tests
# ============================================================================


def test_cli_export_schema_prisma(capsys, tmp_path):
    schema = {
        "tables": {
            "users": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "name", "data_type": "text"},
                ]
            }
        }
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "prisma",
            "--dialect",
            "postgresql",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert 'provider = "postgresql"' in captured.out
    assert "model Users {" in captured.out


def test_cli_export_schema_drizzle(capsys, tmp_path):
    schema = {
        "tables": {
            "posts": {
                "columns": [
                    {"name": "id", "data_type": "serial", "is_primary": True},
                    {"name": "title", "data_type": "text"},
                ]
            }
        }
    }
    schema_file = tmp_path / "posts.json"
    schema_file.write_text(json.dumps(schema))

    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "drizzle",
            "--dialect",
            "postgres",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert 'from "drizzle-orm/pg-core";' in captured.out
    assert 'export const posts = pgTable("posts"' in captured.out


def test_cli_export_schema_sqlalchemy(capsys, tmp_path):
    schema = {
        "tables": {
            "articles": {
                "columns": [
                    {"name": "id", "data_type": "int", "is_primary": True},
                    {"name": "headline", "data_type": "varchar"},
                ]
            }
        }
    }
    schema_file = tmp_path / "articles.json"
    schema_file.write_text(json.dumps(schema))

    ret = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "sqlalchemy",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert "Base = declarative_base()" in captured.out
    assert "class Articles(Base):" in captured.out


def test_cli_export_schema_output_file_and_inline_json(capsys, tmp_path):
    inline_schema = (
        '{"tables": {"users": {"columns": [{"name": "id", "is_primary": true}]}}}'
    )
    out_file = tmp_path / "models.py"

    ret = main(
        [
            "export-schema",
            "--schema",
            inline_schema,
            "--format",
            "sqlalchemy",
            "--output",
            str(out_file),
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert "[OK] Exported sqlalchemy schema to" in captured.out
    assert out_file.exists()
    assert "class Users(Base):" in out_file.read_text()


def test_cli_export_schema_json_mode(capsys, tmp_path):
    inline_schema = (
        '{"tables": {"orders": {"columns": [{"name": "id", "is_primary": true}]}}}'
    )

    ret = main(
        [
            "export-schema",
            "--schema",
            inline_schema,
            "--format",
            "prisma",
            "--json",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is True
    assert payload["format"] == "prisma"
    assert "model Orders {" in payload["content"]


def test_cli_export_schema_errors(capsys, tmp_path):
    schema_file = tmp_path / "valid.json"
    schema_file.write_text('{"tables": {}}')

    # Unsupported format (in text mode) returns 1
    ret_bad_fmt = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "unknown_format",
        ]
    )
    assert ret_bad_fmt == 1
    captured_fmt = capsys.readouterr()
    assert "Unknown format" in captured_fmt.err

    # Unsupported format in json mode
    ret_bad_fmt_json = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "unknown_format",
            "--json",
        ]
    )
    assert ret_bad_fmt_json == 1
    payload_bad_fmt = json.loads(capsys.readouterr().out)
    assert payload_bad_fmt["success"] is False

    # Unsupported dialect causes converter error (exit 1)
    ret_bad_dialect = main(
        [
            "export-schema",
            "--schema",
            str(schema_file),
            "--format",
            "prisma",
            "--dialect",
            "unsupported_db",
        ]
    )
    assert ret_bad_dialect == 1
    captured_dialect = capsys.readouterr()
    assert "Export error:" in captured_dialect.err

    # Nonexistent schema file
    ret_missing = main(
        [
            "export-schema",
            "--schema",
            "nonexistent_schema_xyz.json",
            "--format",
            "prisma",
        ]
    )
    assert ret_missing == 1
    captured = capsys.readouterr()
    assert "Export error:" in captured.err

    # Nonexistent schema file with --json
    ret_missing_json = main(
        [
            "export-schema",
            "--schema",
            "nonexistent_schema_xyz.json",
            "--format",
            "prisma",
            "--json",
        ]
    )
    assert ret_missing_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["success"] is False


# ============================================================================
# 6. Backward Compatibility Subcommand Tests (join-path & serve)
# ============================================================================


def test_cli_join_path_json_and_compat(capsys, tmp_path):
    schema = {
        "tables": {
            "a": {"columns": [{"name": "id"}]},
            "b": {"columns": [{"name": "id"}, {"name": "a_id"}]},
        },
        "foreign_keys": [
            {
                "table": "b",
                "column": "a_id",
                "foreign_table": "a",
                "foreign_column": "id",
            }
        ],
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    ret = main(
        [
            "join-path",
            "--active",
            "a",
            "--target",
            "b",
            "--schema",
            str(schema_file),
            "--json",
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert len(res) == 1
    assert res[0]["table"] == "b"

    # join-path without --schema
    ret_no_schema = main(["join-path", "--active", "a", "--target", "b"])
    assert ret_no_schema == 0


def test_cli_join_path_error(capsys):
    ret = main(
        ["join-path", "--active", "a", "--target", "b", "--schema", "nonexistent.json"]
    )
    assert ret == 1
    captured = capsys.readouterr()
    assert "Join path error:" in captured.err

    ret_json = main(
        [
            "join-path",
            "--active",
            "a",
            "--target",
            "b",
            "--schema",
            "nonexistent.json",
            "--json",
        ]
    )
    assert ret_json == 1
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert "error" in payload


def test_cli_introspect_empty_and_custom_connector(capsys, tmp_path):
    # Empty in-memory sqlite has 0 tables in text mode
    ret_empty = main(
        ["introspect", "--connector", "sqlite", "--config", '{"database": ":memory:"}']
    )
    assert ret_empty == 0
    captured_empty = capsys.readouterr()
    assert "[OK] Introspected 0 tables" in captured_empty.out

    # Config from file in introspect
    cfg_file = tmp_path / "sqlite_file_cfg.json"
    cfg_file.write_text(json.dumps({"database": ":memory:"}))
    ret_cfg_file = main(
        ["introspect", "--connector", "sqlite", "--config", str(cfg_file)]
    )
    assert ret_cfg_file == 0

    # Connector returning non-dict, non-dataclass snapshot (e.g. None)
    class MockNoneConnector(BaseConnector):
        def connect(self):
            return None

        def introspect_schema(self, filter_sensitive=True):
            return None

    ConnectorRegistry.register("mock_none_intro", MockNoneConnector)
    try:
        ret_none = main(["introspect", "--connector", "mock_none_intro"])
        assert ret_none == 0
    finally:
        ConnectorRegistry.unregister("mock_none_intro")


def test_cli_main_module_execution(monkeypatch):
    import runpy

    import pytest

    monkeypatch.setattr("sys.argv", ["query-builder", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("query_builder/cli.py", run_name="__main__")
    assert exc.value.code == 0


# ============================================================================
# 8. Init and Doctor Subcommand Tests
# ============================================================================


def test_cli_init_fullstack(tmp_path, capsys):
    target = tmp_path / "starter_app"
    ret = main(["init", str(target), "--template", "fullstack", "--dialect", "sqlite"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "[OK] Scaffolded Query-Builder 'fullstack' starter project" in captured.out
    assert (target / "schema.json").exists()
    assert (target / "spec.json").exists()
    assert (target / "main.py").exists()
    assert (target / "README.md").exists()
    main_text = (target / "main.py").read_text()
    assert "create_query_builder_router" in main_text


def test_cli_init_minimal_json(tmp_path, capsys):
    target = tmp_path / "minimal_app"
    ret = main(["init", str(target), "--template", "minimal", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["success"] is True
    assert payload["template"] == "minimal"
    assert "schema.json" in payload["created_files"]
    assert (target / "main.py").exists()
    main_text = (target / "main.py").read_text()
    assert "QueryCompiler" in main_text


def test_cli_init_existing_without_and_with_force(tmp_path, capsys):
    target = tmp_path / "overwrite_app"
    main(["init", str(target), "--json"])
    capsys.readouterr()  # Flush initial output

    # Run again without --force -> files skipped
    ret_skip = main(["init", str(target), "--json"])
    assert ret_skip == 0
    payload_skip = json.loads(capsys.readouterr().out)
    assert len(payload_skip["skipped_files"]) == 4
    assert len(payload_skip["created_files"]) == 0

    # Run with --force -> files overwritten
    ret_force = main(["init", str(target), "--force", "--json"])
    assert ret_force == 0
    payload_force = json.loads(capsys.readouterr().out)
    assert len(payload_force["created_files"]) == 4


def test_cli_doctor_text_output(capsys):
    ret = main(["doctor"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Query-Builder Doctor Diagnostics" in captured.out
    assert "[OK] Python:" in captured.out
    assert "[OK] Query-Builder:" in captured.out
    assert "sqlite (in-memory):" in captured.out
    assert "[PASS] All core Query-Builder diagnostic checks passed!" in captured.out


def test_cli_doctor_json_output(capsys):
    ret = main(["doctor", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "healthy"
    assert "environment" in payload
    assert "drivers" in payload
    assert "registered_connectors" in payload
    assert "connectivity" in payload
    assert payload["drivers"]["sqlite3"]["available"] is True


def test_cli_doctor_with_connector(capsys):
    ret = main(["doctor", "--connector", "sqlite", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "healthy"
    assert "sqlite" in payload["connectivity"]


def test_cli_doctor_with_failing_connector(capsys):
    ret = main(["doctor", "--connector", "nonexistent_driver_xyz"])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Doctor error:" in captured.err or "failed" in captured.out


def test_cli_join_path_with_inline_schema(capsys):
    inline_schema = json.dumps(
        {
            "tables": {
                "users": {"columns": [{"name": "id"}]},
                "orders": {"columns": [{"name": "id"}, {"name": "user_id"}]},
            },
            "foreign_keys": [
                {
                    "table": "orders",
                    "column": "user_id",
                    "foreign_table": "users",
                    "foreign_column": "id",
                }
            ],
        }
    )
    ret = main(
        [
            "join-path",
            "--active",
            "users",
            "--target",
            "orders",
            "--schema",
            inline_schema,
        ]
    )
    assert ret == 0
    captured = capsys.readouterr()
    path = json.loads(captured.out)
    assert len(path) == 1
    assert path[0]["table"] == "orders"


def test_cli_init_with_dialects(tmp_path, capsys):
    # 1. Postgres dialect in fullstack
    pg_target = tmp_path / "pg_app"
    ret_pg = main(["init", str(pg_target), "--dialect", "postgres", "--json"])
    assert ret_pg == 0
    pg_main = (pg_target / "main.py").read_text()
    assert "ConnectorRegistry" in pg_main
    assert 'get("postgres"' in pg_main

    # 2. DuckDB dialect in fullstack
    duck_target = tmp_path / "duck_app"
    ret_duck = main(["init", str(duck_target), "--dialect", "duckdb", "--json"])
    assert ret_duck == 0
    duck_main = (duck_target / "main.py").read_text()
    assert 'get("duckdb"' in duck_main

    # 3. Minimal template with postgres dialect
    min_target = tmp_path / "min_pg_app"
    ret_min = main(
        [
            "init",
            str(min_target),
            "--template",
            "minimal",
            "--dialect",
            "postgres",
            "--json",
        ]
    )
    assert ret_min == 0
    min_main = (min_target / "main.py").read_text()
    assert 'dialect="postgres"' in min_main
