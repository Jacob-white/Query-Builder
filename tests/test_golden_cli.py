"""Golden tests pinning the observable behaviour (stdout, stderr, exit code and
written files) of every ``query-builder`` CLI subcommand.

They guard behaviour-preserving refactors of ``query_builder.cli.main``.
Regenerate deliberately (never to make a refactor pass) with::

    QB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden_cli.py
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from query_builder.cli import main

GOLDEN = Path(__file__).parent / "golden" / "cli_golden.json"

SCHEMA = {
    "tables": {
        "users": {
            "name": "users",
            "comment": "People",
            "has_user_id": True,
            "columns": [
                {"name": "id", "data_type": "integer", "is_primary": True},
                {"name": "email", "data_type": "text", "is_nullable": False},
                {"name": "password", "data_type": "text"},
            ],
        },
        "orders": {
            "name": "orders",
            "columns": [
                {"name": "id", "data_type": "integer", "is_primary": True},
                {"name": "user_id", "data_type": "integer"},
                {"name": "total", "data_type": "decimal"},
            ],
        },
        "items": {
            "name": "items",
            "columns": [
                {"name": "id", "data_type": "integer", "is_primary": True},
                {"name": "order_id", "data_type": "integer"},
            ],
        },
    },
    "foreign_keys": [
        {
            "table": "orders",
            "column": "user_id",
            "foreign_table": "users",
            "foreign_column": "id",
        },
        {
            "table": "items",
            "column": "order_id",
            "foreign_table": "orders",
            "foreign_column": "id",
        },
    ],
    "relationships": [
        {
            "source_table": "orders",
            "source_column": "user_id",
            "target_table": "users",
            "target_column": "id",
        },
        {
            "source_table": "items",
            "source_column": "order_id",
            "target_table": "orders",
            "target_column": "id",
        },
    ],
}
SPEC = {
    "table": "orders",
    "columns": ["orders.id", "users.email"],
    "joins": [{"table": "users"}],
    "filters": [{"column": "total", "op": "gt", "value": 5}],
    "limit": 5,
}
VSPEC = {"table": "users", "columns": ["id"], "vector_search": {"vector": [1, 2]}}

Argv = Callable[[Path], list[str]]
CASES: dict[str, Argv] = {}


def _p(tmp: Path, name: str) -> str:
    return str(tmp / name)


def case(name: str) -> Callable[[Argv], Argv]:
    def deco(fn: Argv) -> Argv:
        CASES[name] = fn
        return fn

    return deco


def simple(name: str, *argv: str) -> None:
    CASES[name] = lambda tmp: list(argv)


def _prepare(tmp: Path) -> None:
    (tmp / "spec.json").write_text(json.dumps(SPEC))
    (tmp / "schema.json").write_text(json.dumps(SCHEMA))
    (tmp / "vspec.json").write_text(json.dumps(VSPEC))
    (tmp / "bad.json").write_text("{not json")
    (tmp / "q.sql").write_text("SELECT id FROM users;")
    (tmp / "evil.sql").write_text("DROP TABLE users;")
    (tmp / "sqlspec.json").write_text(json.dumps({"sql": "SELECT 1"}))
    (tmp / "conn.json").write_text(json.dumps({"database": str(tmp / "app.db")}))
    db = sqlite3.connect(tmp / "app.db")
    db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    db.execute("CREATE TABLE pets (id INTEGER PRIMARY KEY, owner INTEGER)")
    db.commit()
    db.close()


# ----------------------------------------------------------------- compile
@case("compile_file")
def _(t: Path) -> list[str]:
    return ["compile", "--spec", _p(t, "spec.json"), "--schema", _p(t, "schema.json")]


@case("compile_json")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        _p(t, "spec.json"),
        "--schema",
        _p(t, "schema.json"),
        "--json",
        "-d",
        "mysql",
    ]


@case("compile_mssql")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        _p(t, "spec.json"),
        "--schema",
        _p(t, "schema.json"),
        "-d",
        "mssql",
    ]


@case("compile_inline")
def _(t: Path) -> list[str]:
    return ["compile", "--spec", json.dumps({"table": "users", "limit": 2})]


@case("compile_user_tenant")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "--spec",
        json.dumps({"table": "users", "columns": ["id"]}),
        "--user-id",
        "9",
        "--tenant-id",
        "4",
        "--schema",
        _p(t, "schema.json"),
    ]


@case("compile_tenant_error")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "--spec",
        json.dumps({"table": "items", "columns": ["id"]}),
        "--tenant-id",
        "4",
        "--schema",
        _p(t, "schema.json"),
    ]


@case("compile_output_text")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        _p(t, "spec.json"),
        "--schema",
        _p(t, "schema.json"),
        "-o",
        _p(t, "out.sql"),
    ]


@case("compile_output_json")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        _p(t, "spec.json"),
        "--schema",
        _p(t, "schema.json"),
        "--json",
        "-o",
        _p(t, "out.json"),
    ]


@case("compile_vector_csv")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        _p(t, "vspec.json"),
        "--vector",
        "0.1, 0.2,0.3",
        "--top-k",
        "4",
    ]


@case("compile_vector_json_list")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        json.dumps({"table": "users", "columns": ["id"]}),
        "--vector",
        "[1,2]",
        "--json",
    ]


@case("compile_topk_only")
def _(t: Path) -> list[str]:
    return ["compile", "-s", _p(t, "vspec.json"), "--top-k", "3"]


@case("compile_topk_no_vs")
def _(t: Path) -> list[str]:
    return ["compile", "-s", json.dumps({"table": "users"}), "--top-k", "3"]


@case("compile_missing_spec_file")
def _(t: Path) -> list[str]:
    return ["compile", "-s", _p(t, "nope.json")]


@case("compile_missing_spec_file_json")
def _(t: Path) -> list[str]:
    return ["compile", "-s", _p(t, "nope.json"), "--json"]


@case("compile_bad_json_file")
def _(t: Path) -> list[str]:
    return ["compile", "-s", _p(t, "bad.json")]


@case("compile_bad_inline_json")
def _(t: Path) -> list[str]:
    return ["compile", "-s", "{oops", "--json"]


@case("compile_compilation_error")
def _(t: Path) -> list[str]:
    return [
        "compile",
        "-s",
        json.dumps({"table": "ghost"}),
        "--schema",
        _p(t, "schema.json"),
    ]


@case("compile_schema_missing")
def _(t: Path) -> list[str]:
    return ["compile", "-s", _p(t, "spec.json"), "--schema", _p(t, "nope.json")]


# ---------------------------------------------------------------- validate
simple("validate_ok", "validate", "SELECT id FROM users")
simple("validate_ok_json", "validate", "--json", "SELECT id FROM users")
simple("validate_delete", "validate", "DELETE FROM users")
simple("validate_delete_json", "validate", "--json", "DELETE FROM users")
simple("validate_empty", "validate", "")
simple("validate_empty_json", "validate", "--json", "")
simple(
    "validate_union_injection", "validate", "SELECT 1 UNION SELECT password FROM users"
)
simple(
    "validate_fail_high",
    "validate",
    "--fail-on-risk",
    "high",
    "SELECT 1 UNION SELECT password FROM users",
)
simple(
    "validate_fail_critical",
    "validate",
    "--fail-on-risk",
    "CRITICAL",
    "DROP TABLE users",
)
simple(
    "validate_fail_critical_pass", "validate", "--fail-on-risk", "CRITICAL", "SELECT 1"
)
simple("validate_cte", "validate", "WITH a AS (SELECT 1) SELECT * FROM a")
simple(
    "validate_no_cte",
    "validate",
    "--disallow-cte",
    "WITH a AS (SELECT 1) SELECT * FROM a",
)
simple(
    "validate_schemas_allowed",
    "validate",
    "--allowed-schemas",
    "public, prod",
    "SELECT * FROM public.users",
)
simple(
    "validate_schemas_denied",
    "validate",
    "--allowed-schemas",
    "public",
    "SELECT * FROM secret.users",
)
simple(
    "validate_restricted",
    "validate",
    "--restricted-tables",
    "users, Payroll",
    "SELECT * FROM users",
)
simple(
    "validate_restricted_json",
    "validate",
    "--json",
    "--restricted-tables",
    "users",
    "SELECT * FROM users",
)
simple("validate_missing_sql_file", "validate", "nope.sql")
simple("validate_missing_json_file_json", "validate", "--json", "nope.json")
simple(
    "validate_inline_spec",
    "validate",
    json.dumps({"table": "users", "columns": ["id"]}),
)
simple("validate_inline_sql_key", "validate", json.dumps({"sql": "SELECT 1"}))
simple("validate_inline_bad_json", "validate", "{oops")
simple("validate_inline_bad_json_json", "validate", "--json", "{oops")
simple("validate_inline_bad_spec", "validate", json.dumps({"table": "a b"}))


@case("validate_sql_file")
def _(t: Path) -> list[str]:
    return ["validate", _p(t, "q.sql")]


@case("validate_evil_sql_file")
def _(t: Path) -> list[str]:
    return ["validate", _p(t, "evil.sql")]


@case("validate_json_spec_file")
def _(t: Path) -> list[str]:
    return ["validate", _p(t, "vspec.json")]


@case("validate_json_sql_file")
def _(t: Path) -> list[str]:
    return ["validate", _p(t, "sqlspec.json")]


@case("validate_json_bad_file")
def _(t: Path) -> list[str]:
    return ["validate", _p(t, "bad.json")]


@case("validate_json_bad_file_json")
def _(t: Path) -> list[str]:
    return ["validate", "--json", _p(t, "bad.json")]


# ---------------------------------------------------------- test-connection
@case("test_sqlite_ok")
def _(t: Path) -> list[str]:
    return [
        "test-connection",
        "-c",
        "sqlite",
        "--config",
        json.dumps({"database": ":memory:"}),
    ]


@case("test_alias_json")
def _(t: Path) -> list[str]:
    return ["test", "--connector", "sqlite", "--config", _p(t, "conn.json"), "--json"]


@case("test_unknown_connector")
def _(t: Path) -> list[str]:
    return ["test", "-c", "nonesuch"]


@case("test_unknown_connector_json")
def _(t: Path) -> list[str]:
    return ["test", "-c", "nonesuch", "--json"]


@case("test_bad_config")
def _(t: Path) -> list[str]:
    return ["test", "-c", "sqlite", "--config", "{oops"]


# -------------------------------------------------------------- introspect
@case("introspect_text")
def _(t: Path) -> list[str]:
    return ["introspect", "-c", "sqlite", "--config", _p(t, "conn.json")]


@case("introspect_json_output")
def _(t: Path) -> list[str]:
    return [
        "introspect",
        "-c",
        "sqlite",
        "--config",
        _p(t, "conn.json"),
        "--json",
        "-o",
        _p(t, "snap.json"),
    ]


@case("introspect_no_filter")
def _(t: Path) -> list[str]:
    return [
        "introspect",
        "-c",
        "sqlite",
        "--config",
        json.dumps({"database": str(t / "app.db")}),
        "--no-filter-sensitive",
    ]


@case("introspect_error")
def _(t: Path) -> list[str]:
    return ["introspect", "-c", "nonesuch"]


@case("introspect_error_json")
def _(t: Path) -> list[str]:
    return ["introspect", "-c", "nonesuch", "--json"]


# ------------------------------------------------------------------ export
@case("export_prisma")
def _(t: Path) -> list[str]:
    return ["export-schema", "-s", _p(t, "schema.json"), "-f", "prisma"]


@case("export_prisma_mysql_json")
def _(t: Path) -> list[str]:
    return [
        "export",
        "-s",
        _p(t, "schema.json"),
        "-f",
        "PRISMA",
        "-d",
        "mysql",
        "--json",
    ]


@case("export_drizzle")
def _(t: Path) -> list[str]:
    return ["export", "-s", json.dumps(SCHEMA), "-f", "drizzle", "-d", "sqlite"]


@case("export_sqlalchemy_output")
def _(t: Path) -> list[str]:
    return [
        "export",
        "-s",
        _p(t, "schema.json"),
        "-f",
        "sqlalchemy",
        "-o",
        _p(t, "models.py"),
    ]


@case("export_sqlalchemy_json")
def _(t: Path) -> list[str]:
    return ["export", "-s", _p(t, "schema.json"), "-f", "sqlalchemy", "--json"]


@case("export_unknown_format")
def _(t: Path) -> list[str]:
    return ["export", "-s", _p(t, "schema.json"), "-f", "cobol"]


@case("export_unknown_format_json")
def _(t: Path) -> list[str]:
    return ["export", "-s", _p(t, "schema.json"), "-f", "cobol", "--json"]


@case("export_missing_schema")
def _(t: Path) -> list[str]:
    return ["export", "-s", _p(t, "nope.json"), "-f", "prisma"]


# -------------------------------------------------------------------- join
@case("join_ok")
def _(t: Path) -> list[str]:
    return ["join-path", "-a", "items", "-t", "users", "--schema", _p(t, "schema.json")]


@case("join_inline_schema")
def _(t: Path) -> list[str]:
    return [
        "join",
        "--active",
        "orders, items",
        "--target",
        "users",
        "--schema",
        json.dumps(SCHEMA),
    ]


@case("join_no_schema")
def _(t: Path) -> list[str]:
    return ["join", "-a", "orders", "-t", "users"]


@case("join_no_path")
def _(t: Path) -> list[str]:
    return ["join", "-a", "orders", "-t", "ghost", "--schema", _p(t, "schema.json")]


@case("join_no_path_json")
def _(t: Path) -> list[str]:
    return [
        "join",
        "-a",
        "orders",
        "-t",
        "ghost",
        "--schema",
        _p(t, "schema.json"),
        "--json",
    ]


@case("join_bad_schema")
def _(t: Path) -> list[str]:
    return ["join", "-a", "orders", "-t", "users", "--schema", _p(t, "nope.json")]


# ------------------------------------------------------------------ schema
@case("schema_overview")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json")]


@case("schema_overview_json")
def _(t: Path) -> list[str]:
    return ["schema", "-s", json.dumps(SCHEMA), "--json"]


@case("schema_no_filter")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "--no-filter-sensitive"]


@case("schema_tree")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "--tree"]


@case("schema_table")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "-t", "Orders"]


@case("schema_table_users")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "-t", "users"]


@case("schema_table_incoming")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "-t", "orders"]


@case("schema_table_json")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "-t", "users", "--json"]


@case("schema_table_missing")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "-t", "ghost"]


@case("schema_table_missing_json")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "schema.json"), "-t", "ghost", "--json"]


@case("schema_bad_file")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "nope.json")]


@case("schema_bad_file_json")
def _(t: Path) -> list[str]:
    return ["schema", "-s", _p(t, "nope.json"), "--json"]


# -------------------------------------------------------------------- init
@case("init_default")
def _(t: Path) -> list[str]:
    return ["init", _p(t, "proj_default")]


@case("init_json")
def _(t: Path) -> list[str]:
    return ["init", _p(t, "proj_json"), "--json", "-d", "postgres"]


@case("init_fastapi_duckdb")
def _(t: Path) -> list[str]:
    return ["init", _p(t, "proj_duck"), "-t", "fastapi", "-d", "duckdb"]


@case("init_fullstack_mysql")
def _(t: Path) -> list[str]:
    return ["init", _p(t, "proj_mysql"), "-d", "mysql"]


@case("init_postgresql")
def _(t: Path) -> list[str]:
    return ["init", _p(t, "proj_pg"), "-d", "postgresql", "-t", "fastapi"]


@case("init_minimal")
def _(t: Path) -> list[str]:
    return [
        "init",
        _p(t, "proj_min"),
        "--template",
        "minimal",
        "--dialect",
        "snowflake",
    ]


@case("init_skip_existing")
def _(t: Path) -> list[str]:
    (t / "proj_skip").mkdir()
    (t / "proj_skip" / "spec.json").write_text("KEEP")
    return ["init", _p(t, "proj_skip")]


@case("init_skip_existing_json")
def _(t: Path) -> list[str]:
    (t / "proj_skipj").mkdir()
    (t / "proj_skipj" / "README.md").write_text("KEEP")
    return ["init", _p(t, "proj_skipj"), "--json"]


@case("init_force")
def _(t: Path) -> list[str]:
    (t / "proj_force").mkdir()
    (t / "proj_force" / "spec.json").write_text("OLD")
    return ["init", _p(t, "proj_force"), "--force"]


@case("init_error")
def _(t: Path) -> list[str]:
    (t / "afile").write_text("x")
    return ["init", str(t / "afile" / "sub")]


@case("init_error_json")
def _(t: Path) -> list[str]:
    (t / "afile").write_text("x")
    return ["init", str(t / "afile" / "sub"), "--json"]


# ------------------------------------------------------------------ doctor
@case("doctor_json")
def _(t: Path) -> list[str]:
    return ["doctor", "--json"]


@case("doctor_text")
def _(t: Path) -> list[str]:
    return ["doctor"]


@case("doctor_connector")
def _(t: Path) -> list[str]:
    return ["doctor", "-c", "sqlite", "--config", _p(t, "conn.json"), "--json"]


@case("doctor_bad_connector")
def _(t: Path) -> list[str]:
    return ["doctor", "-c", "nonesuch"]


@case("doctor_bad_connector_json")
def _(t: Path) -> list[str]:
    return ["doctor", "-c", "nonesuch", "--json"]


# --------------------------------------------------------- verify-connectors
simple("verify_table", "verify-connectors")
simple("verify_json", "verify-connectors", "--json")


# ------------------------------------------------------------- normalisation
_LATENCY = re.compile(r"(latency(?:_ms)?\"?[:=]? ?\"?)[0-9.]+")


_OS_ERROR = re.compile(r"\[(?:WinError|Errno) \d+\] [^:']+:")
_ENGINE_VERSION = re.compile(r'("engine_version": ")[0-9][0-9.]*')
_AVAILABLE = re.compile(r"Available connectors: \[[^\]]*\]")


def _norm(text: str, tmp: Path) -> str:
    # the registry content depends on which connectors other tests registered
    text = _AVAILABLE.sub("Available connectors: [<names>]", text)
    for width in (4, 2, 1):
        text = text.replace(str(tmp).replace("\\", "\\" * width), "<TMP>")
    text = text.replace("\\\\", "/").replace("\\", "/")
    text = text.replace("<TMP>//", "<TMP>/")  # a tmp dir may or may not end in a slash
    # OS-specific wording of the same failure ([Errno 20] vs [WinError 3]) and the SQLite
    # library version differ between the platforms the suite runs on
    text = _OS_ERROR.sub("<OSERROR>:", text)
    text = _ENGINE_VERSION.sub(r"\1<VER>", text)
    return _LATENCY.sub(r"\1<N>", text)


def _stable_doctor(out: str, rc_name: str) -> str:
    """Doctor / verify output embeds host and registry specifics; keep the stable shape."""
    if rc_name in ("doctor_json", "doctor_connector", "doctor_bad_connector_json"):
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return out
        return json.dumps(
            {
                k: (
                    sorted(v)
                    if isinstance(v, dict)
                    else ("<list>" if isinstance(v, list) else v)
                )
                for k, v in data.items()
                if k not in ("status",)
            },
            sort_keys=True,
        )
    if rc_name == "doctor_text":
        return "\n".join(
            line
            for line in out.splitlines()
            if line.startswith(
                ("Query-Builder Doctor", "====", "Database", "Registered")
            )
        )
    if rc_name == "verify_json":
        return json.dumps(sorted(json.loads(out)))
    if rc_name == "verify_table":
        return out.splitlines()[0].split()[0]  # first header column
    return out


INPUT_FILES = {
    "spec.json",
    "schema.json",
    "vspec.json",
    "bad.json",
    "q.sql",
    "evil.sql",
    "sqlspec.json",
    "conn.json",
    "app.db",
}


def _run(name: str, tmp: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    _prepare(tmp)
    argv = CASES[name](tmp)
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        try:
            rc: Any = main(argv)
        except SystemExit as exc:
            rc = f"SystemExit({exc.code})"
    finally:
        os.chdir(cwd)
    cap = capsys.readouterr()
    rec: dict[str, Any] = {
        "rc": rc,
        "out": _norm(_stable_doctor(cap.out, name), tmp),
        "err": _norm(cap.err, tmp),
    }
    written: dict[str, str] = {}
    for sub in sorted(tmp.rglob("*")):
        if not sub.is_file():
            continue
        if sub.parent == tmp and sub.name in INPUT_FILES:
            continue
        written[sub.relative_to(tmp).as_posix()] = _norm(
            sub.read_text(encoding="utf-8"), tmp
        )
    rec["files"] = written
    return rec


def _load() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(CASES))
def test_cli_matches_golden(
    name: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rec = _run(name, tmp_path, capsys)
    if os.environ.get("QB_UPDATE_GOLDEN") == "1":
        data = _load() if GOLDEN.exists() else {}
        data[name] = rec
        GOLDEN.write_text(
            json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    assert rec == _load()[name]


def test_golden_has_no_orphans() -> None:
    assert sorted(_load()) == sorted(CASES)


def test_golden_exit_codes_are_diverse() -> None:
    codes = {rec["rc"] for rec in _load().values()}
    assert {0, 1} <= codes


# ------------------------------------------------------------ mcp and serve
def test_mcp_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeServer:
        def run_stdio(self) -> None:
            calls.append("run")

    mod = types.ModuleType("query_builder.mcp_server")
    mod.McpServer = FakeServer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "query_builder.mcp_server", mod)
    assert main(["mcp"]) == 0
    assert calls == ["run"]


@pytest.mark.parametrize("interrupt", [False, True])
def test_serve_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interrupt: bool,
) -> None:
    events: list[Any] = []

    class FakeHttp:
        server_address = ("127.0.0.1", 4321)

        def serve_forever(self) -> None:
            events.append("serve")
            if interrupt:
                raise KeyboardInterrupt

        def server_close(self) -> None:
            events.append("close")

    import query_builder.config as config_mod
    import query_builder.server as server_mod

    def fake_create(host: str, port: int) -> FakeHttp:
        events.append(("create", host, port))
        return FakeHttp()

    monkeypatch.setattr(server_mod, "create_server", fake_create)
    monkeypatch.setattr(
        config_mod, "configure_query_builder", lambda **kw: events.append(("cfg", kw))
    )
    rc = main(["serve", "--host", "0.0.0.0", "-p", "9", "--profile", "strict"])
    out = capsys.readouterr().out
    assert rc == 0
    assert events[0] == ("cfg", {"profile": "strict"})
    assert events[1] == ("create", "0.0.0.0", 9)
    assert "listening on http://0.0.0.0:4321 (Docs: http://0.0.0.0:4321/docs)" in out
    assert ("close" in events) is interrupt
    assert ("Shutting down server" in out) is interrupt


def test_serve_defaults_without_profile(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import query_builder.config as config_mod
    import query_builder.server as server_mod

    seen: list[Any] = []

    class FakeHttp:
        server_address = ("127.0.0.1", 8000)

        def serve_forever(self) -> None:
            return None

    monkeypatch.setattr(
        server_mod,
        "create_server",
        lambda host, port: seen.append((host, port)) or FakeHttp(),
    )
    monkeypatch.setattr(
        config_mod, "configure_query_builder", lambda **kw: seen.append("cfg")
    )
    assert main(["serve"]) == 0
    assert seen == [("127.0.0.1", 8000)]
    assert "http://127.0.0.1:8000" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv", [[], ["--version"], ["bogus"], ["compile"], ["init", "-t", "x"]]
)
def test_argparse_exits(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code in (0, 2)
    cap = capsys.readouterr()
    assert (cap.out + cap.err).strip()
    if argv == ["--version"]:
        assert cap.out.startswith("query-builder ")
        assert exc.value.code == 0
    else:
        assert exc.value.code == 2
