"""
Command-Line Interface for Query Builder Engine.
================================================
Provides CLI utilities for compiling declarative specs to SQL,
validating raw SQL strings, and testing join graph pathfinding.
"""

from __future__ import annotations

import argparse
import json
import sys

from query_builder import __version__
from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.join_solver import find_join_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="query-builder",
        description="Universal SQL Query Builder, Declarative Compiler, and AST Safety Validator.",
    )
    parser.add_argument(
        "--version", action="version", version=f"query-builder {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Compile subcommand
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

    # Validate subcommand
    validate_p = subparsers.add_parser(
        "validate", help="Validate a SQL query string against AST safety rules."
    )
    validate_p.add_argument("sql", help="SQL query string to validate.")

    # Join path subcommand
    join_p = subparsers.add_parser(
        "join-path", help="Find the shortest join path between tables."
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

    args = parser.parse_args(argv)

    if args.command == "compile":
        try:
            if args.spec.startswith("{"):
                spec_data = json.loads(args.spec)
            else:
                with open(args.spec, "r", encoding="utf-8") as f:
                    spec_data = json.load(f)

            schema_data = None
            if args.schema:
                with open(args.schema, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)

            compiler = QueryCompiler(
                spec_data, schema=schema_data, dialect=args.dialect
            )
            main_sql, params, count_sql, _count_params = compiler.compile()

            print("--- Main SQL ---")
            print(main_sql)
            print("\n--- Bind Parameters ---")
            print(params)
            print("\n--- Count Subquery ---")
            print(count_sql)
            return 0
        except (CompilationError, json.JSONDecodeError, OSError) as e:
            sys.stderr.write(f"Compilation error: {e}\n")
            return 1

    elif args.command == "validate":
        res = validate_sql_ast(args.sql)
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 1

    else:
        active = [t.strip() for t in args.active.split(",") if t.strip()]
        schema_data = None
        if args.schema:
            with open(args.schema, "r", encoding="utf-8") as f:
                schema_data = json.load(f)

        path = find_join_path(active, args.target, schema_data)
        print(json.dumps(path, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())
