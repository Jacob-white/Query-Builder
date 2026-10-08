"""
Command-Line Interface for Query Builder Engine.
================================================
Provides developer CLI utilities for compiling declarative specs to SQL,
validating raw SQL and query specs against AST safety rules, inspecting connectors,
testing database connectivity, and exporting schemas to Prisma, Drizzle, and SQLAlchemy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="query-builder",
        description="Universal SQL Query Builder, Declarative Compiler, AST Safety Validator & Schema Exporter.",
    )
    parser.add_argument(
        "--version", action="version", version=f"query-builder {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Compile subcommand
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

    # 2. Validate subcommand
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

    # 3. Test-connection subcommand
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

    # 4. Introspect subcommand
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

    # 5. Export-schema subcommand
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

    # 6. Join path subcommand
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

    # 7. Serve subcommand
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

    # 8. Schema subcommand
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

    subparsers.add_parser(
        "mcp",
        help="Run the Query-Builder Model Context Protocol (MCP) server over standard I/O.",
    )

    # 10. Init subcommand
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

    # 11. Doctor subcommand
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

    args = parser.parse_args(argv)

    if args.command == "compile":
        try:
            if args.spec.startswith("{"):
                spec_data = json.loads(args.spec)
            else:
                with open(args.spec, encoding="utf-8") as f:
                    spec_data = json.load(f)

            schema_data = None
            if args.schema:
                with open(args.schema, encoding="utf-8") as f:
                    schema_data = json.load(f)

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

            compiler = QueryCompiler(
                spec_data,
                schema=schema_data,
                dialect=args.dialect,
                user_id=getattr(args, "user_id", None),
                force_user_filter=bool(getattr(args, "user_id", None)),
                tenant_id=getattr(args, "tenant_id", None),
            )
            main_sql, params, count_sql, count_params = compiler.compile()

            if getattr(args, "json", False):
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
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Compilation error: {e}\n")
            return 1

    elif args.command == "validate":
        target = getattr(args, "target", None) or getattr(args, "sql", None)
        if not target:
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "violations": ["No query provided."],
                            "injection_risk": "NONE",
                        },
                        indent=2,
                    )
                )
            else:
                sys.stderr.write("Validation error: No query target provided.\n")
            return 1

        # Check for nonexistent file if target looks like a path
        if target.endswith((".json", ".sql")) and not os.path.exists(target):
            err_msg = f"Target file not found: {target}"
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "violations": [err_msg],
                            "injection_risk": "CRITICAL",
                        },
                        indent=2,
                    )
                )
            else:
                sys.stderr.write(f"Validation error: {err_msg}\n")
            return 1

        allowed_schemas = None
        if args.allowed_schemas:
            allowed_schemas = [
                s.strip() for s in args.allowed_schemas.split(",") if s.strip()
            ] + [
                s.strip().upper() for s in args.allowed_schemas.split(",") if s.strip()
            ]

        restricted_tables = None
        if args.restricted_tables:
            raw_t = [t.strip() for t in args.restricted_tables.split(",") if t.strip()]
            restricted_tables = set(raw_t) | {t.upper() for t in raw_t}

        allow_cte = not args.disallow_cte

        try:
            if os.path.isfile(target):
                if target.endswith(".json"):
                    with open(target, encoding="utf-8") as f:
                        spec_data = json.load(f)
                    if (
                        isinstance(spec_data, dict)
                        and "sql" in spec_data
                        and "table" not in spec_data
                    ):
                        raw_sql = spec_data["sql"]
                    else:
                        compiler = QueryCompiler(spec_data)
                        raw_sql, _, _, _ = compiler.compile()
                else:
                    with open(target, encoding="utf-8") as f:
                        raw_sql = f.read()
            elif target.startswith("{"):
                spec_data = json.loads(target)
                if (
                    isinstance(spec_data, dict)
                    and "sql" in spec_data
                    and "table" not in spec_data
                ):
                    raw_sql = spec_data["sql"]
                else:
                    compiler = QueryCompiler(spec_data)
                    raw_sql, _, _, _ = compiler.compile()
            else:
                raw_sql = target
        except Exception as exc:  # noqa: BLE001
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "valid": False,
                            "violations": [f"Failed to load or compile target: {exc}"],
                            "injection_risk": "CRITICAL",
                        },
                        indent=2,
                    )
                )
            else:
                sys.stderr.write(f"Validation error: {exc}\n")
            return 1

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

        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            if is_valid:
                print("[PASS] AST validation succeeded. Safe read-only SELECT query.")
            else:
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

        return 0 if is_valid else 1

    elif args.command in ("test-connection", "test"):
        try:
            config: dict[str, Any] = {}
            if args.config:
                if os.path.isfile(args.config):
                    with open(args.config, encoding="utf-8") as f:
                        config = json.load(f)
                else:
                    config = json.loads(args.config)

            from query_builder.connectors import AsyncBaseConnector, ConnectorRegistry

            connector = ConnectorRegistry.get(args.connector, **config)

            if isinstance(connector, AsyncBaseConnector):
                result = _run_coroutine_safely(connector.test_connection())
            else:
                result = connector.test_connection()

            is_ok = result.get("status") == "healthy" or result.get("success") is True

            if getattr(args, "json", False):
                print(json.dumps(result, indent=2))
            else:
                if is_ok:
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
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"success": False, "status": "unhealthy", "error": str(e)},
                        indent=2,
                    )
                )
            else:
                print(f"[ERROR] Connection to '{args.connector}' failed: {e}")
            return 1

    elif args.command == "introspect":
        try:
            config = {}
            if args.config:
                if os.path.isfile(args.config):
                    with open(args.config, encoding="utf-8") as f:
                        config = json.load(f)
                else:
                    config = json.loads(args.config)

            from query_builder.connectors import AsyncBaseConnector, ConnectorRegistry

            connector = ConnectorRegistry.get(args.connector, **config)

            filter_sensitive = bool(getattr(args, "filter_sensitive", True))

            if isinstance(connector, AsyncBaseConnector):
                snapshot = _run_coroutine_safely(
                    connector.introspect_schema(filter_sensitive=filter_sensitive)
                )
            else:
                snapshot = connector.introspect_schema(
                    filter_sensitive=filter_sensitive
                )

            if is_dataclass(snapshot):
                snap_dict = asdict(snapshot)
            elif isinstance(snapshot, dict):
                snap_dict = snapshot
            else:
                snap_dict = {"tables": {}}

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(snap_dict, f, indent=2)

            if getattr(args, "json", False):
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
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Introspection error: {e}\n")
            return 1

    elif args.command in ("export-schema", "export"):
        try:
            if args.schema.startswith("{"):
                schema_data = json.loads(args.schema)
            else:
                with open(args.schema, encoding="utf-8") as f:
                    schema_data = json.load(f)

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

            if getattr(args, "json", False):
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
            else:
                if args.output:
                    print(f"[OK] Exported {fmt} schema to {args.output}")
                else:
                    print(content)
            return 0

        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Export error: {e}\n")
            return 1

    elif args.command in ("join-path", "join"):
        try:
            active = [t.strip() for t in args.active.split(",") if t.strip()]
            schema_data = None
            if args.schema:
                if args.schema.startswith("{"):
                    schema_data = json.loads(args.schema)
                else:
                    with open(args.schema, encoding="utf-8") as f:
                        schema_data = json.load(f)

            path = find_join_path(active, args.target, schema_data)
            print(json.dumps(path, indent=2))
            return 0
        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Join path error: {e}\n")
            return 1

    elif args.command == "schema":
        try:
            if args.schema.startswith("{"):
                schema_data = json.loads(args.schema)
            else:
                with open(args.schema, encoding="utf-8") as f:
                    schema_data = json.load(f)

            from query_builder.schema import explore_schema, format_schema_tree

            filter_sensitive = bool(getattr(args, "filter_sensitive", True))

            if getattr(args, "tree", False):
                tree_str = format_schema_tree(
                    schema_data, filter_sensitive=filter_sensitive
                )
                print(tree_str)
                return 0

            exploration = explore_schema(schema_data, filter_sensitive=filter_sensitive)

            if getattr(args, "table", None):
                target_table = args.table.lower().strip()
                tbl_info = exploration["tables"].get(target_table)
                if not tbl_info:
                    msg = f"Table '{args.table}' not found in schema snapshot."
                    if getattr(args, "json", False):
                        print(json.dumps({"success": False, "error": msg}, indent=2))
                    else:
                        sys.stderr.write(f"Schema Explorer error: {msg}\n")
                    return 1

                if getattr(args, "json", False):
                    print(json.dumps(tbl_info, indent=2))
                else:
                    user_tag = " [user-isolated]" if tbl_info.get("has_user_id") else ""
                    print(f"Table: {tbl_info['name']}{user_tag}")
                    if tbl_info.get("comment"):
                        print(f"Comment: {tbl_info['comment']}")
                    print(f"Columns ({tbl_info['column_count']}):")
                    for c in tbl_info.get("columns", []):
                        pk = " [PK]" if c.get("is_primary") else ""
                        null_str = "NULL" if c.get("is_nullable", True) else "NOT NULL"
                        print(
                            f"  • {c['name']} ({c.get('data_type', 'text')}, {null_str}){pk}"
                        )
                    if tbl_info.get("outgoing_fks"):
                        print("Outgoing Foreign Keys:")
                        for fk in tbl_info["outgoing_fks"]:
                            print(
                                f"  ➔ {fk['column']} -> {fk['foreign_table']}.{fk['foreign_column']}"
                            )
                    if tbl_info.get("incoming_fks"):
                        print("Incoming References:")
                        for fk in tbl_info["incoming_fks"]:
                            print(
                                f"  ⬅ {fk['table']}.{fk['column']} -> {fk['foreign_column']}"
                            )
                return 0

            if getattr(args, "json", False):
                print(json.dumps(exploration, indent=2))
            else:
                print(
                    f"Schema Overview: {exploration['table_count']} tables, "
                    f"{exploration['column_count']} columns, "
                    f"{exploration['foreign_key_count']} foreign keys"
                )
                if exploration.get("hubs"):
                    print(f"  Hub Tables: {', '.join(exploration['hubs'])}")
                if exploration.get("user_isolated_count"):
                    print(
                        f"  User-Isolated Tables: {exploration['user_isolated_count']}"
                    )
                sorted_tables = sorted(exploration["tables"].keys())
                print(f"  Tables: {', '.join(sorted_tables)}")
            return 0

        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Schema Explorer error: {e}\n")
            return 1

    elif args.command == "mcp":
        from query_builder.mcp_server import McpServer

        server = McpServer()
        server.run_stdio()
        return 0

    elif args.command == "init":
        try:
            target_dir = os.path.abspath(args.directory)
            os.makedirs(target_dir, exist_ok=True)

            template = getattr(args, "template", "fullstack")
            dialect = getattr(args, "dialect", "sqlite")
            force = getattr(args, "force", False)

            # 1. schema.json
            schema_content = {
                "tables": {
                    "users": {
                        "name": "users",
                        "columns": [
                            {
                                "name": "id",
                                "data_type": "integer",
                                "is_primary": True,
                                "is_nullable": False,
                            },
                            {
                                "name": "email",
                                "data_type": "text",
                                "is_primary": False,
                                "is_nullable": False,
                            },
                            {
                                "name": "full_name",
                                "data_type": "text",
                                "is_primary": False,
                                "is_nullable": True,
                            },
                            {
                                "name": "created_at",
                                "data_type": "timestamp",
                                "is_primary": False,
                                "is_nullable": False,
                            },
                        ],
                    },
                    "orders": {
                        "name": "orders",
                        "columns": [
                            {
                                "name": "id",
                                "data_type": "integer",
                                "is_primary": True,
                                "is_nullable": False,
                            },
                            {
                                "name": "user_id",
                                "data_type": "integer",
                                "is_primary": False,
                                "is_nullable": False,
                            },
                            {
                                "name": "total_amount",
                                "data_type": "decimal",
                                "is_primary": False,
                                "is_nullable": False,
                            },
                            {
                                "name": "status",
                                "data_type": "text",
                                "is_primary": False,
                                "is_nullable": False,
                            },
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

            # 2. spec.json
            spec_content = {
                "table": "orders",
                "columns": ["orders.id", "orders.total_amount", "users.email"],
                "joins": [
                    {
                        "table": "users",
                        "type": "INNER JOIN",
                        "on": [{"left": "orders.user_id", "right": "users.id"}],
                    }
                ],
                "filters": [
                    {"column": "orders.status", "op": "eq", "value": "COMPLETED"}
                ],
                "limit": 25,
            }

            # 3. main.py
            if template in ("fullstack", "fastapi"):
                if dialect in ("postgres", "postgresql"):
                    conn_import = "from query_builder import ConnectorRegistry, create_query_builder_router"
                    conn_setup = 'connector = ConnectorRegistry.get("postgres", database="starter", user="postgres", host="localhost")'
                    seed_snippet = ""
                elif dialect == "duckdb":
                    conn_import = "from query_builder import ConnectorRegistry, create_query_builder_router"
                    conn_setup = 'connector = ConnectorRegistry.get("duckdb", database="starter.duckdb")'
                    seed_snippet = ""
                elif dialect == "mysql":
                    conn_import = "from query_builder import ConnectorRegistry, create_query_builder_router"
                    conn_setup = 'connector = ConnectorRegistry.get("mysql", database="starter", user="root", host="localhost")'
                    seed_snippet = ""
                else:
                    conn_import = "from query_builder import SQLiteConnector, create_query_builder_router"
                    conn_setup = 'connector = SQLiteConnector(database="starter.db")'
                    seed_snippet = (
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

                main_py_content = (
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
            else:  # minimal
                main_py_content = (
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

            # 4. README.md
            readme_content = (
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

            files_to_create = {
                "schema.json": json.dumps(schema_content, indent=2),
                "spec.json": json.dumps(spec_content, indent=2),
                "main.py": main_py_content,
                "README.md": readme_content,
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

            if getattr(args, "json", False):
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
                    print(
                        f"  - Skipped {sf} (already exists, use --force to overwrite)"
                    )
                print("\nNext steps:")
                print(f"  cd {args.directory}")
                print("  query-builder doctor")
                print("  query-builder compile --spec spec.json")
            return 0
        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Scaffolding error: {e}\n")
            return 1

    elif args.command == "doctor":
        try:
            import importlib
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

            # 2. Driver availability checks
            driver_candidates = [
                ("sqlite3", "sqlite3", "SQLite standard library driver", False),
                (
                    "sqlparse",
                    "sqlparse",
                    "SQL AST parsing and security validator engine",
                    False,
                ),
                ("duckdb", "duckdb", "DuckDB analytical engine", True),
                (
                    "psycopg",
                    "psycopg",
                    "PostgreSQL modern binary driver (psycopg 3)",
                    True,
                ),
                ("psycopg2", "psycopg2", "PostgreSQL legacy driver (psycopg2)", True),
                ("asyncpg", "asyncpg", "Async PostgreSQL driver", True),
                ("mysql.connector", "mysql.connector", "Official MySQL driver", True),
                ("pymysql", "pymysql", "Pure-Python MySQL driver", True),
                ("pymssql", "pymssql", "Microsoft SQL Server driver", True),
                ("pyodbc", "pyodbc", "ODBC universal driver", True),
                (
                    "snowflake.connector",
                    "snowflake.connector",
                    "Snowflake connector",
                    True,
                ),
                ("pyarrow", "pyarrow", "Apache Arrow / Parquet columnar engine", True),
                ("fastapi", "fastapi", "FastAPI HTTP API framework", True),
                ("pydantic", "pydantic", "Pydantic data validation", True),
                (
                    "sqlalchemy",
                    "sqlalchemy",
                    "SQLAlchemy ORM & schema introspection",
                    True,
                ),
            ]

            drivers_status = {}
            for name, mod_name, desc, optional in driver_candidates:
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

            # 3. Connector registry
            from query_builder.connectors.registry import ConnectorRegistry

            registered_connectors = ConnectorRegistry.list_available()

            # 4. Connectivity check
            target_connector = getattr(args, "connector", None)
            conn_config = {}
            if getattr(args, "config", None):
                if os.path.isfile(args.config):
                    with open(args.config, encoding="utf-8") as f:
                        conn_config = json.load(f)
                else:
                    conn_config = json.loads(args.config)

            connectivity_status = {}
            if target_connector:
                from query_builder.connectors import AsyncBaseConnector

                conn = ConnectorRegistry.get(target_connector, **conn_config)
                if isinstance(conn, AsyncBaseConnector):
                    test_res = _run_coroutine_safely(conn.test_connection())
                else:
                    test_res = conn.test_connection()
                connectivity_status[target_connector] = test_res
            else:
                conn = ConnectorRegistry.get("sqlite", database=":memory:")
                test_res = conn.test_connection()
                connectivity_status["sqlite (in-memory)"] = test_res

            conn_healthy = all(
                r.get("status") == "healthy" or r.get("success") is True
                for r in connectivity_status.values()
            )
            required_drivers_ok = all(
                d["available"] for d in drivers_status.values() if not d["optional"]
            )
            overall_healthy = py_supported and conn_healthy and required_drivers_ok

            if getattr(args, "json", False):
                payload = {
                    "status": "healthy" if overall_healthy else "degraded",
                    "environment": env_checks,
                    "drivers": drivers_status,
                    "registered_connectors": registered_connectors,
                    "connectivity": connectivity_status,
                }
                print(json.dumps(payload, indent=2))
            else:
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
                    c_ok = res.get("status") == "healthy" or res.get("success") is True
                    c_tag = "[OK]" if c_ok else "[ERROR]"
                    lat = res.get("latency_ms", "N/A")
                    print(
                        f"  {c_tag} {c_name}: {res.get('status', 'unknown')} (latency: {lat}ms)"
                    )

                if overall_healthy:
                    print("\n[PASS] All core Query-Builder diagnostic checks passed!")
                else:
                    print(
                        "\n[FAIL] Some diagnostic checks failed or warnings were reported."
                    )

            return 0 if overall_healthy else 1
        except Exception as e:  # noqa: BLE001
            if getattr(args, "json", False):
                print(json.dumps({"status": "error", "error": str(e)}, indent=2))
            else:
                sys.stderr.write(f"Doctor error: {e}\n")
            return 1

    else:
        from query_builder.config import configure_query_builder
        from query_builder.server import create_server

        if getattr(args, "profile", None):
            configure_query_builder(profile=args.profile)

        server = create_server(host=args.host, port=args.port)
        actual_port = server.server_address[1]
        sys.stdout.write(
            f"Query Builder server listening on http://{args.host}:{actual_port} (Docs: http://{args.host}:{actual_port}/docs)\n"
        )
        sys.stdout.flush()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            sys.stdout.write("\nShutting down server...\n")
            server.server_close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
