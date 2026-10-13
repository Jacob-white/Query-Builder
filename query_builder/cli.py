"""
Command-Line Interface for Query Builder Engine.
================================================
Provides developer CLI utilities for compiling declarative specs to SQL,
validating raw SQL and query specs against AST safety rules, inspecting connectors,
testing database connectivity, and exporting schemas to Prisma, Drizzle, and SQLAlchemy.

Layout: ``_add_<name>_parser`` functions declare each subcommand's arguments,
``_cmd_<name>`` functions implement them, and ``_COMMAND_HANDLERS`` maps every
command name (and alias) to its handler; ``main`` only parses and dispatches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from query_builder import __version__
from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.join_solver import find_join_path


def _run_coroutine_safely(coro: Any) -> Any:
    """Executes a coroutine safely whether or not an event loop is already running."""
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _wants_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


def _load_json_arg(value: str) -> Any:
    """Parse ``value`` as inline JSON when it starts with ``{``, else read it as a file."""
    if value.startswith("{"):
        return json.loads(value)
    with open(value, encoding="utf-8") as f:
        return json.load(f)


def _load_connector_config(raw: str | None) -> dict[str, Any]:
    """Connection config from a JSON file path or an inline JSON string."""
    if not raw:
        return {}
    if os.path.isfile(raw):
        with open(raw, encoding="utf-8") as f:
            loaded: dict[str, Any] = json.load(f)
        return loaded
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def _verify_connectors(args: argparse.Namespace) -> int:
    """`verify-connectors`: print the evidence-based status table; --live runs the suite."""
    from query_builder.connectors import status

    report = status.build_report()
    if args.json and not args.live:
        print(json.dumps(report, indent=2))
        return 0
    if not args.live:
        print(status.render_table(report))
        return 0
    try:
        code, live_report = status.run_live_suite(
            args.engine or None, strict=args.strict
        )
    except RuntimeError as exc:
        sys.stderr.write(f"verify-connectors: {exc}\n")
        return 2
    if args.json:
        print(json.dumps(live_report, indent=2))
    else:
        print(status.render_live_summary(live_report))
    return status.live_exit_code(code, live_report)


# ---------------------------------------------------------------------------
# Argument parsers (one per subcommand)
# ---------------------------------------------------------------------------
Subparsers = Any  # argparse's _SubParsersAction is private


def _add_compile_parser(subparsers: Subparsers) -> None:
    compile_p = subparsers.add_parser(
        "compile", help="Compile a JSON query spec into parameterized SQL."
    )
    compile_p.add_argument(
        "--spec",
        "-s",
        required=True,
        help="Path to JSON query specification file or JSON string.",
    )
    compile_p.add_argument(
        "--schema", help="Optional path to JSON schema snapshot file."
    )
    compile_p.add_argument(
        "--dialect",
        "-d",
        default="postgres",
        help="SQL dialect (postgres, snowflake, mssql, sqlite, mysql).",
    )
    compile_p.add_argument(
        "--user-id",
        help="Optional user ID for ownership isolation.",
    )
    compile_p.add_argument(
        "--tenant-id",
        help="Optional tenant ID for multi-tenant isolation.",
    )
    compile_p.add_argument(
        "--output",
        "-o",
        help="Optional output file to write compiled SQL or JSON payload.",
    )
    compile_p.add_argument(
        "--json",
        action="store_true",
        help="Output compiled SQL and parameters as structured JSON.",
    )
    compile_p.add_argument(
        "--vector",
        help="Optional comma-separated or JSON array query vector embedding to inject.",
    )
    compile_p.add_argument(
        "--top-k",
        type=int,
        help="Optional top_k nearest neighbors limit for vector search.",
    )


def _add_validate_parser(subparsers: Subparsers) -> None:
    validate_p = subparsers.add_parser(
        "validate",
        help="Validate a SQL query string or query spec against AST safety rules.",
    )
    validate_p.add_argument(
        "target", help="Raw SQL query string, .sql file, or .json query spec file."
    )
    validate_p.add_argument(
        "--allowed-schemas",
        help="Comma-separated list of authorized database schemas.",
    )
    validate_p.add_argument(
        "--restricted-tables",
        help="Comma-separated list of restricted table names.",
    )
    validate_p.add_argument(
        "--disallow-cte",
        action="store_true",
        help="Disallow Common Table Expressions (WITH queries).",
    )
    validate_p.add_argument(
        "--fail-on-risk",
        choices=["HIGH", "CRITICAL", "high", "critical"],
        help="Exit non-zero if injection risk meets or exceeds threshold (HIGH or CRITICAL).",
    )
    validate_p.add_argument(
        "--json",
        action="store_true",
        help="Output AST validation result as structured JSON.",
    )


def _add_test_connection_parser(subparsers: Subparsers) -> None:
    test_p = subparsers.add_parser(
        "test-connection",
        aliases=["test"],
        help="Test database reachability and latency.",
    )
    test_p.add_argument(
        "--connector",
        "-c",
        required=True,
        help="Registered connector identifier (e.g. sqlite, duckdb, postgres).",
    )
    test_p.add_argument(
        "--config", help="Connection configuration JSON string or file path."
    )
    test_p.add_argument(
        "--json",
        action="store_true",
        help="Output connection test status as structured JSON.",
    )


def _add_introspect_parser(subparsers: Subparsers) -> None:
    introspect_p = subparsers.add_parser(
        "introspect", help="Reverse-engineer database schema metadata."
    )
    introspect_p.add_argument(
        "--connector",
        "-c",
        required=True,
        help="Registered connector identifier.",
    )
    introspect_p.add_argument(
        "--config", help="Connection configuration JSON string or file path."
    )
    introspect_p.add_argument(
        "--output",
        "-o",
        help="Optional output file path to write schema snapshot JSON.",
    )
    introspect_p.add_argument(
        "--filter-sensitive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Filter sensitive system and auth tables (default: enabled).",
    )
    introspect_p.add_argument(
        "--json",
        action="store_true",
        help="Output schema snapshot as structured JSON to stdout.",
    )


def _add_export_parser(subparsers: Subparsers) -> None:
    export_p = subparsers.add_parser(
        "export-schema",
        aliases=["export"],
        help="Convert schema snapshot into ORM schema definitions.",
    )
    export_p.add_argument(
        "--schema",
        "-s",
        required=True,
        help="Path to schema snapshot JSON file or JSON string.",
    )
    export_p.add_argument(
        "--format",
        "-f",
        required=True,
        help="Target ORM schema format (prisma, drizzle, sqlalchemy).",
    )
    export_p.add_argument(
        "--dialect",
        "-d",
        help="Database dialect/provider (e.g. postgres, sqlite, mysql).",
    )
    export_p.add_argument(
        "--output",
        "-o",
        help="Optional output file path to write generated code.",
    )
    export_p.add_argument(
        "--json",
        action="store_true",
        help="Output export payload as structured JSON.",
    )


def _add_join_path_parser(subparsers: Subparsers) -> None:
    join_p = subparsers.add_parser(
        "join-path",
        aliases=["join"],
        help="Find the shortest join path between tables.",
    )
    join_p.add_argument(
        "--active",
        "-a",
        required=True,
        help="Comma-separated list of active table names.",
    )
    join_p.add_argument(
        "--target", "-t", required=True, help="Target table name to join."
    )
    join_p.add_argument("--schema", help="Optional path to JSON schema snapshot file.")
    join_p.add_argument(
        "--json",
        action="store_true",
        help="Output join path as structured JSON.",
    )


def _add_serve_parser(subparsers: Subparsers) -> None:
    serve_p = subparsers.add_parser(
        "serve", help="Start the Query-Builder HTTP API microservice."
    )
    serve_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind HTTP server (default: 127.0.0.1).",
    )
    serve_p.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000).",
    )
    serve_p.add_argument(
        "--profile",
        choices=["development", "production", "strict"],
        default=None,
        help="Active security profile preset (development, production, strict).",
    )
    serve_p.add_argument(
        "--secure",
        action="store_true",
        help=(
            "Secure mode: the server, not the client, chooses tenant, policy and connection "
            "(see docs/SECURE_DEPLOYMENT.md). Implies --profile production unless one is given."
        ),
    )
    serve_p.add_argument(
        "--tenant-header",
        default="X-Tenant-ID",
        help=(
            "Secure mode: header that carries the tenant id. ONLY safe behind a reverse proxy that "
            "authenticates the caller and sets/overwrites it (default: X-Tenant-ID)."
        ),
    )
    serve_p.add_argument(
        "--connections",
        metavar="FILE",
        help=(
            "Secure mode: JSON file {id: {connector, config, dialect?}} of the connections to "
            "register at start-up. Clients cannot create connections in secure mode."
        ),
    )
    serve_p.add_argument(
        "--default-connection",
        default="default",
        help="Secure mode: connection id used for every request (default: 'default').",
    )
    serve_p.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help="Secure mode: browser origin allowed to call the server (repeatable). Default: none.",
    )
    serve_p.add_argument(
        "--no-security-notice",
        action="store_true",
        help="Do not print the start-up security notice.",
    )


def _add_schema_parser(subparsers: Subparsers) -> None:
    schema_p = subparsers.add_parser(
        "schema",
        help="Explore and inspect database schema structure, relationships, and stats.",
    )
    schema_p.add_argument(
        "--schema",
        "-s",
        required=True,
        help="Path to JSON schema snapshot file or JSON string.",
    )
    schema_p.add_argument(
        "--table",
        "-t",
        help="Optional specific table name to inspect in detail.",
    )
    schema_p.add_argument(
        "--tree",
        action="store_true",
        help="Render ASCII hierarchy tree of tables, columns, and foreign keys.",
    )
    schema_p.add_argument(
        "--filter-sensitive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Filter sensitive system and auth tables (default: enabled).",
    )
    schema_p.add_argument(
        "--json",
        action="store_true",
        help="Output schema exploration metrics as structured JSON.",
    )


def _add_mcp_parser(subparsers: Subparsers) -> None:
    mcp_p = subparsers.add_parser(
        "mcp",
        help="Run the Query-Builder Model Context Protocol (MCP) server over standard I/O.",
    )
    mcp_p.add_argument(
        "--profile",
        choices=["development", "production", "strict"],
        default=None,
        help="Active security profile preset (development, production, strict).",
    )
    mcp_p.add_argument(
        "--no-security-notice",
        action="store_true",
        help="Do not print the start-up security notice (to stderr).",
    )


def _add_init_parser(subparsers: Subparsers) -> None:
    init_p = subparsers.add_parser(
        "init",
        help="Scaffold a turnkey Query-Builder starter project.",
    )
    init_p.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Target directory to scaffold starter setup into (default: current directory).",
    )
    init_p.add_argument(
        "--template",
        "-t",
        choices=["fullstack", "fastapi", "minimal"],
        default="fullstack",
        help="Starter template variant (fullstack, fastapi, minimal). Default: fullstack.",
    )
    init_p.add_argument(
        "--dialect",
        "-d",
        default="sqlite",
        help="Target SQL dialect for starter setup (default: sqlite).",
    )
    init_p.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing files in target directory.",
    )
    init_p.add_argument(
        "--json",
        action="store_true",
        help="Output scaffolding result as structured JSON.",
    )


def _add_doctor_parser(subparsers: Subparsers) -> None:
    doctor_p = subparsers.add_parser(
        "doctor",
        help="Check environment health, database connectivity, and driver availability.",
    )
    doctor_p.add_argument(
        "--connector",
        "-c",
        help="Optional database connector to test (e.g. sqlite, postgres, duckdb).",
    )
    doctor_p.add_argument(
        "--config",
        help="Optional connection configuration JSON string or file path.",
    )
    doctor_p.add_argument(
        "--json",
        action="store_true",
        help="Output diagnostics as structured JSON.",
    )


def _add_verify_connectors_parser(subparsers: Subparsers) -> None:
    verify_p = subparsers.add_parser(
        "verify-connectors",
        help="Show how each connector is verified (certified/verified/experimental); "
        "--live runs the live conformance suite against real engines.",
    )
    verify_p.add_argument(
        "--live",
        action="store_true",
        help="Run tests/integration (needs a source checkout and the compose "
        "services from docs/TESTING_LIVE.md); exits non-zero on failures.",
    )
    verify_p.add_argument(
        "--engine",
        "-e",
        action="append",
        metavar="NAME",
        help="With --live: only this engine (repeatable), e.g. -e postgres -e mysql.",
    )
    verify_p.add_argument(
        "--strict",
        action="store_true",
        help="With --live: an unreachable selected engine is a failure, not a skip.",
    )
    verify_p.add_argument(
        "--json", action="store_true", help="Output the report as JSON."
    )


_PARSER_BUILDERS: tuple[Callable[[Subparsers], None], ...] = (
    _add_compile_parser,
    _add_validate_parser,
    _add_test_connection_parser,
    _add_introspect_parser,
    _add_export_parser,
    _add_join_path_parser,
    _add_serve_parser,
    _add_schema_parser,
    _add_mcp_parser,
    _add_init_parser,
    _add_doctor_parser,
    _add_verify_connectors_parser,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="query-builder",
        description="Universal SQL Query Builder, Declarative Compiler, AST Safety Validator & Schema Exporter.",
    )
    parser.add_argument(
        "--version", action="version", version=f"query-builder {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for add_parser in _PARSER_BUILDERS:
        add_parser(subparsers)
    return parser


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------
def _inject_vector(args: argparse.Namespace, spec_data: dict[str, Any]) -> None:
    """Apply ``--vector`` / ``--top-k`` overrides onto the spec's vector_search."""
    if getattr(args, "vector", None):
        raw_v = args.vector.strip()
        if raw_v.startswith("["):
            v_list = json.loads(raw_v)
        else:
            v_list = [float(x.strip()) for x in raw_v.split(",") if x.strip()]
        vs_dict = dict(spec_data.get("vector_search") or {})
        vs_dict["vector"] = v_list
        if getattr(args, "top_k", None):
            vs_dict["top_k"] = args.top_k
        spec_data["vector_search"] = vs_dict
    elif getattr(args, "top_k", None) and "vector_search" in spec_data:
        vs_dict = dict(spec_data["vector_search"])
        vs_dict["top_k"] = args.top_k
        spec_data["vector_search"] = vs_dict


def _cmd_compile(args: argparse.Namespace) -> int:
    try:
        spec_data = _load_json_arg(args.spec)

        schema_data = None
        if args.schema:
            with open(args.schema, encoding="utf-8") as f:
                schema_data = json.load(f)

        _inject_vector(args, spec_data)

        compiler = QueryCompiler(
            spec_data,
            schema=schema_data,
            dialect=args.dialect,
            user_id=getattr(args, "user_id", None),
            force_user_filter=bool(getattr(args, "user_id", None)),
            tenant_id=getattr(args, "tenant_id", None),
        )
        main_sql, params, count_sql, count_params = compiler.compile()

        if _wants_json(args):
            payload = {
                "main_sql": main_sql,
                "params": params,
                "count_sql": count_sql,
                "count_params": count_params,
                "dialect": args.dialect,
            }
            out_str = json.dumps(payload, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(out_str)
            print(out_str)
        else:
            out_text = (
                f"--- Main SQL ---\n{main_sql}\n\n"
                f"--- Bind Parameters ---\n{params}\n\n"
                f"--- Count Subquery ---\n{count_sql}"
            )
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(main_sql)
            print(out_text)
        return 0
    except (CompilationError, json.JSONDecodeError, OSError) as e:
        if _wants_json(args):
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Compilation error: {e}\n")
        return 1


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
def _validate_failure(
    args: argparse.Namespace, message: str, risk: str, stderr_text: str | None = None
) -> int:
    """Report a pre-validation failure (JSON verdict or stderr line) and return 1."""
    if _wants_json(args):
        print(
            json.dumps(
                {"valid": False, "violations": [message], "injection_risk": risk},
                indent=2,
            )
        )
    else:
        sys.stderr.write(
            stderr_text if stderr_text is not None else f"Validation error: {message}\n"
        )
    return 1


def _sql_from_spec(spec_data: Any) -> str:
    """The SQL to validate for a loaded JSON target: its ``sql`` or the compiled spec."""
    if isinstance(spec_data, dict) and "sql" in spec_data and "table" not in spec_data:
        raw_sql: str = spec_data["sql"]
        return raw_sql
    compiler = QueryCompiler(spec_data)
    raw_sql, _, _, _ = compiler.compile()
    return raw_sql


def _load_validation_target(target: str) -> str:
    if os.path.isfile(target):
        if target.endswith(".json"):
            with open(target, encoding="utf-8") as f:
                return _sql_from_spec(json.load(f))
        with open(target, encoding="utf-8") as f:
            return f.read()
    if target.startswith("{"):
        return _sql_from_spec(json.loads(target))
    return target


def _print_validation_text(
    res: dict[str, Any],
    args: argparse.Namespace,
    is_valid: bool,
    risk: str,
    risk_failed: bool,
) -> None:
    if is_valid:
        print("[PASS] AST validation succeeded. Safe read-only SELECT query.")
        return
    print("[FAIL] AST validation failed:")
    print(f"  Statement type: {res.get('statement_type', 'UNKNOWN')}")
    print(f"  Injection risk: {res.get('injection_risk', 'UNKNOWN')}")
    violations = list(res.get("violations", []))
    if risk_failed:
        violations.append(
            f"Risk level {risk} meets or exceeds threshold {args.fail_on_risk}"
        )
    print("  Violations:")
    for v in violations:
        print(f"    - {v}")


def _cmd_validate(args: argparse.Namespace) -> int:
    target = getattr(args, "target", None) or getattr(args, "sql", None)
    if not target:
        return _validate_failure(
            args,
            "No query provided.",
            "NONE",
            stderr_text="Validation error: No query target provided.\n",
        )

    # Check for nonexistent file if target looks like a path
    if target.endswith((".json", ".sql")) and not os.path.exists(target):
        return _validate_failure(args, f"Target file not found: {target}", "CRITICAL")

    allowed_schemas = None
    if args.allowed_schemas:
        allowed_schemas = [
            s.strip() for s in args.allowed_schemas.split(",") if s.strip()
        ] + [s.strip().upper() for s in args.allowed_schemas.split(",") if s.strip()]

    restricted_tables = None
    if args.restricted_tables:
        raw_t = [t.strip() for t in args.restricted_tables.split(",") if t.strip()]
        restricted_tables = set(raw_t) | {t.upper() for t in raw_t}

    allow_cte = not args.disallow_cte

    try:
        raw_sql = _load_validation_target(target)
    except Exception as exc:  # noqa: BLE001
        return _validate_failure(
            args,
            f"Failed to load or compile target: {exc}",
            "CRITICAL",
            stderr_text=f"Validation error: {exc}\n",
        )

    res = validate_sql_ast(
        raw_sql,
        allowed_schemas=allowed_schemas,
        restricted_tables=restricted_tables,
        allow_cte=allow_cte,
    )

    risk = res.get("injection_risk", "NONE").upper()
    risk_failed = False
    if args.fail_on_risk:
        thresh = args.fail_on_risk.upper()
        if (thresh == "HIGH" and risk in ("HIGH", "CRITICAL")) or (
            thresh == "CRITICAL" and risk == "CRITICAL"
        ):
            risk_failed = True

    is_valid = bool(res.get("valid", False)) and not risk_failed

    if _wants_json(args):
        print(json.dumps(res, indent=2))
    else:
        _print_validation_text(res, args, is_valid, risk, risk_failed)

    return 0 if is_valid else 1


# ---------------------------------------------------------------------------
# test-connection / introspect
# ---------------------------------------------------------------------------
def _call_connector(connector: Any, method: str, *call_args: Any, **kwargs: Any) -> Any:
    """Invoke a sync or async connector method uniformly."""
    from query_builder.connectors import AsyncBaseConnector

    result = getattr(connector, method)(*call_args, **kwargs)
    if isinstance(connector, AsyncBaseConnector):
        return _run_coroutine_safely(result)
    return result


def _connection_ok(result: dict[str, Any]) -> bool:
    return result.get("status") == "healthy" or result.get("success") is True


def _cmd_test_connection(args: argparse.Namespace) -> int:
    try:
        config = _load_connector_config(args.config)

        from query_builder.connectors import ConnectorRegistry

        connector = ConnectorRegistry.get(args.connector, **config)
        result = _call_connector(connector, "test_connection")
        is_ok = _connection_ok(result)

        if _wants_json(args):
            print(json.dumps(result, indent=2))
        elif is_ok:
            latency = result.get("latency_ms", "N/A")
            dialect = result.get("dialect", args.connector)
            print(
                f"[OK] Connection to '{args.connector}' successful (dialect: {dialect}, latency: {latency}ms)"
            )
        else:
            err = result.get("error", "Health check failed")
            print(f"[ERROR] Connection to '{args.connector}' failed: {err}")
        return 0 if is_ok else 1

    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(
                json.dumps(
                    {"success": False, "status": "unhealthy", "error": str(e)},
                    indent=2,
                )
            )
        else:
            print(f"[ERROR] Connection to '{args.connector}' failed: {e}")
        return 1


def _cmd_introspect(args: argparse.Namespace) -> int:
    try:
        config = _load_connector_config(args.config)

        from query_builder.connectors import ConnectorRegistry

        connector = ConnectorRegistry.get(args.connector, **config)

        filter_sensitive = bool(getattr(args, "filter_sensitive", True))
        snapshot = _call_connector(
            connector, "introspect_schema", filter_sensitive=filter_sensitive
        )

        if is_dataclass(snapshot):
            snap_dict = asdict(snapshot)  # type: ignore[arg-type]
        elif isinstance(snapshot, dict):
            snap_dict = snapshot
        else:
            snap_dict = {"tables": {}}

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(snap_dict, f, indent=2)

        if _wants_json(args):
            print(json.dumps(snap_dict, indent=2))
        else:
            tables = snap_dict.get("tables", {})
            table_count = len(tables)
            col_count = sum(
                len(t.get("columns", []))
                for t in (tables.values() if isinstance(tables, dict) else [])
            )
            print(
                f"[OK] Introspected {table_count} tables ({col_count} columns) from '{args.connector}'."
            )
            if table_count > 0:
                sorted_tables = sorted(tables.keys())
                print(f"  Tables: {', '.join(sorted_tables)}")
        return 0

    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Introspection error: {e}\n")
        return 1


# ---------------------------------------------------------------------------
# export-schema / join-path
# ---------------------------------------------------------------------------
def _cmd_export_schema(args: argparse.Namespace) -> int:
    try:
        schema_data = _load_json_arg(args.schema)

        fmt = args.format.lower().strip()
        dialect = args.dialect

        from query_builder.schema_converters import (
            to_drizzle_schema,
            to_prisma_schema,
            to_sqlalchemy_models,
        )

        if fmt == "prisma":
            provider = dialect or "postgresql"
            content = to_prisma_schema(schema_data, provider=provider)
            used_dialect = provider
        elif fmt == "drizzle":
            d_dialect = dialect or "postgres"
            content = to_drizzle_schema(schema_data, dialect=d_dialect)
            used_dialect = d_dialect
        elif fmt == "sqlalchemy":
            content = to_sqlalchemy_models(schema_data)
            used_dialect = dialect or "sqlalchemy"
        else:
            raise ValueError(
                f"Unknown format '{fmt}'. Choose from: prisma, drizzle, sqlalchemy"
            )

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(content)

        if _wants_json(args):
            print(
                json.dumps(
                    {
                        "success": True,
                        "format": fmt,
                        "dialect": used_dialect,
                        "content": content,
                    },
                    indent=2,
                )
            )
        elif args.output:
            print(f"[OK] Exported {fmt} schema to {args.output}")
        else:
            print(content)
        return 0

    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Export error: {e}\n")
        return 1


def _cmd_join_path(args: argparse.Namespace) -> int:
    try:
        active = [t.strip() for t in args.active.split(",") if t.strip()]
        schema_data = _load_json_arg(args.schema) if args.schema else None

        path = find_join_path(active, args.target, schema_data)
        print(json.dumps(path, indent=2))
        return 0
    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Join path error: {e}\n")
        return 1


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def _print_table_detail(tbl_info: dict[str, Any]) -> None:
    user_tag = " [user-isolated]" if tbl_info.get("has_user_id") else ""
    print(f"Table: {tbl_info['name']}{user_tag}")
    if tbl_info.get("comment"):
        print(f"Comment: {tbl_info['comment']}")
    print(f"Columns ({tbl_info['column_count']}):")
    for c in tbl_info.get("columns", []):
        pk = " [PK]" if c.get("is_primary") else ""
        null_str = "NULL" if c.get("is_nullable", True) else "NOT NULL"
        print(f"  • {c['name']} ({c.get('data_type', 'text')}, {null_str}){pk}")
    if tbl_info.get("outgoing_fks"):
        print("Outgoing Foreign Keys:")
        for fk in tbl_info["outgoing_fks"]:
            print(f"  ➔ {fk['column']} -> {fk['foreign_table']}.{fk['foreign_column']}")
    if tbl_info.get("incoming_fks"):
        print("Incoming References:")
        for fk in tbl_info["incoming_fks"]:
            print(f"  ⬅ {fk['table']}.{fk['column']} -> {fk['foreign_column']}")


def _print_schema_overview(exploration: dict[str, Any]) -> None:
    print(
        f"Schema Overview: {exploration['table_count']} tables, "
        f"{exploration['column_count']} columns, "
        f"{exploration['foreign_key_count']} foreign keys"
    )
    if exploration.get("hubs"):
        print(f"  Hub Tables: {', '.join(exploration['hubs'])}")
    if exploration.get("user_isolated_count"):
        print(f"  User-Isolated Tables: {exploration['user_isolated_count']}")
    sorted_tables = sorted(exploration["tables"].keys())
    print(f"  Tables: {', '.join(sorted_tables)}")


def _cmd_schema(args: argparse.Namespace) -> int:
    try:
        schema_data = _load_json_arg(args.schema)

        from query_builder.schema import explore_schema, format_schema_tree

        filter_sensitive = bool(getattr(args, "filter_sensitive", True))

        if getattr(args, "tree", False):
            print(format_schema_tree(schema_data, filter_sensitive=filter_sensitive))
            return 0

        exploration = explore_schema(schema_data, filter_sensitive=filter_sensitive)

        if getattr(args, "table", None):
            target_table = args.table.lower().strip()
            tbl_info = exploration["tables"].get(target_table)
            if not tbl_info:
                msg = f"Table '{args.table}' not found in schema snapshot."
                if _wants_json(args):
                    print(json.dumps({"success": False, "error": msg}, indent=2))
                else:
                    sys.stderr.write(f"Schema Explorer error: {msg}\n")
                return 1

            if _wants_json(args):
                print(json.dumps(tbl_info, indent=2))
            else:
                _print_table_detail(tbl_info)
            return 0

        if _wants_json(args):
            print(json.dumps(exploration, indent=2))
        else:
            _print_schema_overview(exploration)
        return 0

    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Schema Explorer error: {e}\n")
        return 1


# ---------------------------------------------------------------------------
# mcp / serve
# ---------------------------------------------------------------------------
def _print_notice(lines: list[str]) -> None:
    for line in lines:
        sys.stderr.write(line + "\n")
    sys.stderr.flush()


def _cmd_mcp(args: argparse.Namespace) -> int:
    from query_builder.mcp_server import McpServer
    from query_builder.server_security import insecure_mode_notice

    if getattr(args, "profile", None):
        from query_builder.config import configure_query_builder

        configure_query_builder(profile=args.profile)
    if not getattr(args, "no_security_notice", False):
        _print_notice(insecure_mode_notice("mcp"))

    server = McpServer()
    server.run_stdio()
    return 0


def _secure_server_options(args: argparse.Namespace) -> dict[str, Any]:
    """``create_server`` keyword arguments for ``serve --secure`` (registers the connections)."""
    import json

    from query_builder.pool import get_connection_pool_manager
    from query_builder.server import register_connection
    from query_builder.server_security import ServerSecurity, header_tenant_resolver

    manager = get_connection_pool_manager()
    if args.connections:
        with open(args.connections, encoding="utf-8") as fh:
            declared = json.load(fh)
        if not isinstance(declared, dict):
            raise ValueError(
                "--connections must be a JSON object {id: {connector, config}}"
            )
        for connection_id, spec in declared.items():
            register_connection(
                manager,
                str(connection_id),
                str(spec["connector"]),
                dict(spec.get("config", {})),
                dialect=spec.get("dialect"),
            )
    return {
        "connection_pool_manager": manager,
        "security": ServerSecurity(
            tenant_resolver=header_tenant_resolver(args.tenant_header),
            default_connection_id=args.default_connection,
            cors_origins=tuple(args.allow_origin),
        ),
    }


def _cmd_serve(args: argparse.Namespace) -> int:
    import os

    from query_builder.config import configure_query_builder
    from query_builder.server import create_server
    from query_builder.server_security import insecure_mode_notice

    profile = getattr(args, "profile", None)
    secure = bool(getattr(args, "secure", False))
    if secure and not profile and "QB_SECURITY_PROFILE" not in os.environ:
        profile = (
            "production"  # secure mode must not run with the permissive default policy
        )
    if profile:
        configure_query_builder(profile=profile)

    if secure:
        server = create_server(
            host=args.host, port=args.port, **_secure_server_options(args)
        )
    else:
        server = create_server(host=args.host, port=args.port)
    if not getattr(args, "no_security_notice", False):
        _print_notice(insecure_mode_notice("serve", secure=secure))
    actual_port = server.server_address[1]
    sys.stdout.write(
        f"Query Builder server listening on http://{args.host}:{actual_port} (Docs: http://{args.host}:{actual_port}/docs)\n"
    )
    if secure:
        sys.stdout.write(
            f"Secure mode: tenant from header {args.tenant_header!r}, connection {args.default_connection!r}\n"
        )
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stdout.write("\nShutting down server...\n")
        server.server_close()
    return 0


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------
def _init_column(
    name: str, data_type: str, *, primary: bool = False, nullable: bool = False
) -> dict[str, Any]:
    return {
        "name": name,
        "data_type": data_type,
        "is_primary": primary,
        "is_nullable": nullable,
    }


def _init_schema_content() -> dict[str, Any]:
    return {
        "tables": {
            "users": {
                "name": "users",
                "columns": [
                    _init_column("id", "integer", primary=True),
                    _init_column("email", "text"),
                    _init_column("full_name", "text", nullable=True),
                    _init_column("created_at", "timestamp"),
                ],
            },
            "orders": {
                "name": "orders",
                "columns": [
                    _init_column("id", "integer", primary=True),
                    _init_column("user_id", "integer"),
                    _init_column("total_amount", "decimal"),
                    _init_column("status", "text"),
                ],
            },
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ],
        "relationships": [
            {
                "source_table": "orders",
                "source_column": "user_id",
                "target_table": "users",
                "target_column": "id",
            }
        ],
    }


def _init_spec_content() -> dict[str, Any]:
    return {
        "table": "orders",
        "columns": ["orders.id", "orders.total_amount", "users.email"],
        "joins": [
            {
                "table": "users",
                "type": "INNER JOIN",
                "on": [{"left": "orders.user_id", "right": "users.id"}],
            }
        ],
        "filters": [{"column": "orders.status", "op": "eq", "value": "COMPLETED"}],
        "limit": 25,
    }


_INIT_IMPORT = (
    "from query_builder import ConnectorRegistry, create_query_builder_router"
)
_INIT_SQLITE_SEED = (
    "# Auto-seed starter tables on launch if using SQLite\n"
    "import sqlite3\n"
    '_conn = sqlite3.connect("starter.db")\n'
    '_conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, full_name TEXT, created_at TEXT NOT NULL);")\n'
    '_conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), total_amount REAL NOT NULL, status TEXT NOT NULL);")\n'
    'if _conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0] == 0:\n'
    "    _conn.execute(\"INSERT INTO users (id, email, full_name, created_at) VALUES (1, 'alice@example.com', 'Alice Smith', '2026-01-01');\")\n"
    "    _conn.execute(\"INSERT INTO orders (id, user_id, total_amount, status) VALUES (1, 1, 99.50, 'COMPLETED');\")\n"
    "    _conn.commit()\n"
    "_conn.close()\n\n"
)

# dialect -> (import line, connector setup line, seed snippet) for the API starters
_INIT_CONNECTOR_SNIPPETS: dict[str, tuple[str, str, str]] = {
    "postgres": (
        _INIT_IMPORT,
        'connector = ConnectorRegistry.get("postgres", database="starter", user="postgres", host="localhost")',
        "",
    ),
    "duckdb": (
        _INIT_IMPORT,
        'connector = ConnectorRegistry.get("duckdb", database="starter.duckdb")',
        "",
    ),
    "mysql": (
        _INIT_IMPORT,
        'connector = ConnectorRegistry.get("mysql", database="starter", user="root", host="localhost")',
        "",
    ),
}
_INIT_CONNECTOR_SNIPPETS["postgresql"] = _INIT_CONNECTOR_SNIPPETS["postgres"]
_INIT_SQLITE_SNIPPET = (
    "from query_builder import SQLiteConnector, create_query_builder_router",
    'connector = SQLiteConnector(database="starter.db")',
    _INIT_SQLITE_SEED,
)


def _init_main_py(template: str, dialect: str) -> str:
    if template in ("fullstack", "fastapi"):
        conn_import, conn_setup, seed_snippet = _INIT_CONNECTOR_SNIPPETS.get(
            dialect, _INIT_SQLITE_SNIPPET
        )
        return (
            '"""\n'
            "Query-Builder Starter Backend API.\n"
            '"""\n\n'
            "from fastapi import FastAPI\n"
            f"{conn_import}\n\n"
            'app = FastAPI(title="Query-Builder Starter API")\n\n'
            f"{seed_snippet}"
            f"{conn_setup}\n"
            'router = create_query_builder_router(connector=connector, prefix="/api")\n'
            "app.include_router(router)\n\n"
            '@app.get("/health")\n'
            "def health():\n"
            '    return {"status": "healthy"}\n\n'
            'if __name__ == "__main__":\n'
            "    import uvicorn\n"
            '    uvicorn.run(app, host="127.0.0.1", port=8000)\n'
        )
    return (  # minimal
        '"""\n'
        "Query-Builder Minimal Starter.\n"
        '"""\n\n'
        "import json\n"
        "from query_builder import QueryCompiler, validate_sql_ast\n\n"
        'with open("spec.json", "r") as f:\n'
        "    spec = json.load(f)\n"
        'with open("schema.json", "r") as f:\n'
        "    schema = json.load(f)\n\n"
        f'compiler = QueryCompiler(spec, schema=schema, dialect="{dialect}")\n'
        "sql, params, count_sql, count_params = compiler.compile()\n\n"
        'print("Compiled SQL:\\n", sql)\n'
        'print("Params:", params)\n'
        'print("AST Validation:", validate_sql_ast(sql))\n'
    )


def _init_readme(template: str, dialect: str) -> str:
    return (
        f"# Query-Builder Starter ({template.capitalize()})\n\n"
        f"Scaffolded with default dialect: `{dialect}`.\n\n"
        "## Quickstart Commands\n\n"
        "- **Validate Environment & Drivers:**\n"
        "  ```bash\n"
        "  query-builder doctor\n"
        "  ```\n"
        "- **Compile QuerySpec to SQL:**\n"
        "  ```bash\n"
        f"  query-builder compile --spec spec.json --schema schema.json --dialect {dialect}\n"
        "  ```\n"
        "- **Validate SQL AST Safety:**\n"
        "  ```bash\n"
        '  query-builder validate "SELECT * FROM users;"\n'
        "  ```\n"
        "- **Start API Server:**\n"
        "  ```bash\n"
        "  python main.py\n"
        "  ```\n"
    )


def _cmd_init(args: argparse.Namespace) -> int:
    try:
        target_dir = os.path.abspath(args.directory)
        os.makedirs(target_dir, exist_ok=True)

        template = getattr(args, "template", "fullstack")
        dialect = getattr(args, "dialect", "sqlite")
        force = getattr(args, "force", False)

        files_to_create = {
            "schema.json": json.dumps(_init_schema_content(), indent=2),
            "spec.json": json.dumps(_init_spec_content(), indent=2),
            "main.py": _init_main_py(template, dialect),
            "README.md": _init_readme(template, dialect),
        }

        created_files: list[str] = []
        skipped_files: list[str] = []

        for filename, content in files_to_create.items():
            file_path = os.path.join(target_dir, filename)
            if os.path.exists(file_path) and not force:
                skipped_files.append(filename)
                continue
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            created_files.append(filename)

        if _wants_json(args):
            print(
                json.dumps(
                    {
                        "success": True,
                        "directory": target_dir,
                        "template": template,
                        "dialect": dialect,
                        "created_files": created_files,
                        "skipped_files": skipped_files,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[OK] Scaffolded Query-Builder '{template}' starter project in: {target_dir}"
            )
            for cf in created_files:
                print(f"  + Created {cf}")
            for sf in skipped_files:
                print(f"  - Skipped {sf} (already exists, use --force to overwrite)")
            print("\nNext steps:")
            print(f"  cd {args.directory}")
            print("  query-builder doctor")
            print("  query-builder compile --spec spec.json")
        return 0
    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(json.dumps({"success": False, "error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Scaffolding error: {e}\n")
        return 1


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------
# (display name, import name, description, optional)
_DOCTOR_DRIVERS: tuple[tuple[str, str, str, bool], ...] = (
    ("sqlite3", "sqlite3", "SQLite standard library driver", False),
    ("sqlparse", "sqlparse", "SQL AST parsing and security validator engine", False),
    ("duckdb", "duckdb", "DuckDB analytical engine", True),
    ("psycopg", "psycopg", "PostgreSQL modern binary driver (psycopg 3)", True),
    ("psycopg2", "psycopg2", "PostgreSQL legacy driver (psycopg2)", True),
    ("asyncpg", "asyncpg", "Async PostgreSQL driver", True),
    ("mysql.connector", "mysql.connector", "Official MySQL driver", True),
    ("pymysql", "pymysql", "Pure-Python MySQL driver", True),
    ("pymssql", "pymssql", "Microsoft SQL Server driver", True),
    ("pyodbc", "pyodbc", "ODBC universal driver", True),
    ("snowflake.connector", "snowflake.connector", "Snowflake connector", True),
    ("pyarrow", "pyarrow", "Apache Arrow / Parquet columnar engine", True),
    ("fastapi", "fastapi", "FastAPI HTTP API framework", True),
    ("pydantic", "pydantic", "Pydantic data validation", True),
    ("sqlalchemy", "sqlalchemy", "SQLAlchemy ORM & schema introspection", True),
)


def _doctor_driver_status() -> dict[str, dict[str, Any]]:
    import importlib

    drivers_status: dict[str, dict[str, Any]] = {}
    for name, mod_name, desc, optional in _DOCTOR_DRIVERS:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "__version__"):
                ver = mod.__version__
            elif hasattr(mod, "sqlite_version"):
                ver = mod.sqlite_version
            else:
                ver = "available"
            drivers_status[name] = {
                "available": True,
                "version": str(ver),
                "description": desc,
                "optional": optional,
            }
        except ImportError:
            drivers_status[name] = {
                "available": False,
                "version": None,
                "description": desc,
                "optional": optional,
            }
    return drivers_status


def _doctor_connectivity(args: argparse.Namespace, registry: Any) -> dict[str, Any]:
    target_connector = getattr(args, "connector", None)
    conn_config = _load_connector_config(getattr(args, "config", None))

    connectivity_status: dict[str, Any] = {}
    if target_connector:
        conn = registry.get(target_connector, **conn_config)
        connectivity_status[target_connector] = _call_connector(conn, "test_connection")
    else:
        conn = registry.get("sqlite", database=":memory:")
        connectivity_status["sqlite (in-memory)"] = conn.test_connection()
    return connectivity_status


def _print_doctor_report(
    py_ver: str,
    py_supported: bool,
    os_info: str,
    drivers_status: dict[str, dict[str, Any]],
    registered_connectors: list[str],
    connectivity_status: dict[str, Any],
    overall_healthy: bool,
) -> None:
    print("Query-Builder Doctor Diagnostics")
    print("=================================")
    py_tag = "[OK]" if py_supported else "[ERROR]"
    print(f"{py_tag} Python: {py_ver} on {os_info}")
    print(f"[OK] Query-Builder: v{__version__}")

    print("\nDatabase Drivers & Dependencies:")
    for name, d_info in drivers_status.items():
        if d_info["available"]:
            print(f"  • {name}: Installed (v{d_info['version']})")
        else:
            opt_tag = "(optional)" if d_info["optional"] else "(required)"
            print(f"  • {name}: Not installed {opt_tag}")

    print("\nRegistered Connectors:")
    print(f"  {', '.join(registered_connectors)}")

    print("\nDatabase Connectivity:")
    for c_name, res in connectivity_status.items():
        c_tag = "[OK]" if _connection_ok(res) else "[ERROR]"
        lat = res.get("latency_ms", "N/A")
        print(f"  {c_tag} {c_name}: {res.get('status', 'unknown')} (latency: {lat}ms)")

    if overall_healthy:
        print("\n[PASS] All core Query-Builder diagnostic checks passed!")
    else:
        print("\n[FAIL] Some diagnostic checks failed or warnings were reported.")


def _cmd_doctor(args: argparse.Namespace) -> int:
    try:
        import platform

        # 1. Environment checks
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        py_supported = sys.version_info >= (3, 11)
        os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"

        env_checks = {
            "python_version": py_ver,
            "python_supported": py_supported,
            "platform": os_info,
            "query_builder_version": __version__,
        }

        # 2. Driver availability, 3. connector registry, 4. connectivity
        drivers_status = _doctor_driver_status()

        from query_builder.connectors.registry import ConnectorRegistry

        registered_connectors = ConnectorRegistry.list_available()
        connectivity_status = _doctor_connectivity(args, ConnectorRegistry)

        conn_healthy = all(_connection_ok(r) for r in connectivity_status.values())
        required_drivers_ok = all(
            d["available"] for d in drivers_status.values() if not d["optional"]
        )
        overall_healthy = py_supported and conn_healthy and required_drivers_ok

        if _wants_json(args):
            payload = {
                "status": "healthy" if overall_healthy else "degraded",
                "environment": env_checks,
                "drivers": drivers_status,
                "registered_connectors": registered_connectors,
                "connectivity": connectivity_status,
            }
            print(json.dumps(payload, indent=2))
        else:
            _print_doctor_report(
                py_ver,
                py_supported,
                os_info,
                drivers_status,
                registered_connectors,
                connectivity_status,
                overall_healthy,
            )

        return 0 if overall_healthy else 1
    except Exception as e:  # noqa: BLE001
        if _wants_json(args):
            print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        else:
            sys.stderr.write(f"Doctor error: {e}\n")
        return 1


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
_COMMAND_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "compile": _cmd_compile,
    "validate": _cmd_validate,
    "test-connection": _cmd_test_connection,
    "test": _cmd_test_connection,
    "introspect": _cmd_introspect,
    "export-schema": _cmd_export_schema,
    "export": _cmd_export_schema,
    "join-path": _cmd_join_path,
    "join": _cmd_join_path,
    "schema": _cmd_schema,
    "mcp": _cmd_mcp,
    "init": _cmd_init,
    "doctor": _cmd_doctor,
    "verify-connectors": _verify_connectors,
    "serve": _cmd_serve,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _COMMAND_HANDLERS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
