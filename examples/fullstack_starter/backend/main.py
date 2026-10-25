"""
FastAPI Backend Server for Query-Builder Studio & Multi-Database Hub.
=====================================================================
Provides turnkey REST endpoints for multi-database schema introspection, query
compilation, AST safety validation, read-only query execution, and tabular export
across PostgreSQL, MySQL, DuckDB, and SQLite databases.
"""

from __future__ import annotations

import base64
import contextlib
import contextvars
import csv
import decimal
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Ensure parent directory is importable
starter_root = Path(__file__).resolve().parent.parent
if str(starter_root) not in sys.path:
    sys.path.insert(0, str(starter_root))

from database import (
    DEFAULT_DB_PATH,
    SCHEMA_DDL,
    SEED_DATA_SQL,
    get_starter_schema_snapshot,
    init_database,
    snapshot_to_dict,
)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from query_builder import (
    DuckDBConnector,
    MySQLConnector,
    PostgresConnector,
    SQLiteConnector,
    configure_query_builder,
    create_query_builder_router,
    get_query_builder_config,
    list_dialects,
    register_filter_operator,
    reset_query_builder_config,
    reset_security_config,
)
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.postgres import _pg_read_only

db_path = DEFAULT_DB_PATH

# Context variable tracking which database ID is active for the current HTTP request
_active_db_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "active_db_id", default=None
)

# Per-database schema introspection cache: db_id -> (monotonic_timestamp, schema_dict)
_SCHEMA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SCHEMA_CACHE_TTL_SEC = 300.0


def _sanitize_cell_value(val: Any) -> Any:
    """Ensures binary blobs and Decimals serialize cleanly to JSON."""
    if isinstance(val, (bytes, bytearray, memoryview)):
        raw = bytes(val)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            preview = raw[:16].hex()
            suffix = "..." if len(raw) > 16 else ""
            return f"<binary {len(raw)} bytes: 0x{preview}{suffix}>"
    if isinstance(val, decimal.Decimal):
        return float(val)
    return val


def _sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitizes a list of row dicts for safe JSON serialization."""
    for row in rows:
        if isinstance(row, dict):
            for k, v in row.items():
                if isinstance(v, (bytes, bytearray, memoryview, decimal.Decimal)):
                    row[k] = _sanitize_cell_value(v)
    return rows


def infer_missing_foreign_keys(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Enriches an introspected schema snapshot with inferred foreign keys and categories.

    Many SQLite and legacy applications omit explicit FOREIGN KEY constraints in DDL
    while following strict naming conventions (`<table_singular>_id` or `<TableSingular>Id`).
    """
    tables = snapshot.get("tables", {})
    if not isinstance(tables, dict) or not tables:
        return snapshot

    valid_tables = set(tables.keys())

    # Filter out any FKs pointing to sensitive tables that were removed during normalization
    existing_fks: list[dict[str, Any]] = [
        fk
        for fk in snapshot.get("foreign_keys", [])
        if fk.get("table") in valid_tables and fk.get("foreign_table") in valid_tables
    ]
    existing_rels: list[dict[str, Any]] = [
        rel
        for rel in snapshot.get("relationships", [])
        if rel.get("source_table") in valid_tables
        and rel.get("target_table") in valid_tables
    ]

    seen_fk_pairs: set[tuple[str, str]] = {
        (str(fk.get("table", "")), str(fk.get("column", ""))) for fk in existing_fks
    }

    # Build lookup from singular/plural table stems -> (actual_table_name, pk_col)
    stem_to_target: dict[str, tuple[str, str]] = {}
    for tname, tmeta in tables.items():
        cols = tmeta.get("columns", []) if isinstance(tmeta, dict) else []
        pk_col: str | None = None
        for c in cols:
            if isinstance(c, dict) and c.get("is_primary"):
                pk_col = str(c.get("name", ""))
                break
        if not pk_col:
            for c in cols:
                cname = str(c.get("name", "")) if isinstance(c, dict) else ""
                if cname.lower() == "id":
                    pk_col = cname
                    break
        if not pk_col:
            continue

        low = tname.lower()
        candidates = {low}
        if low.startswith("api_"):
            candidates.add(low[4:])
        for base in list(candidates):
            if base.endswith("ies") and len(base) > 3:
                candidates.add(base[:-3] + "y")
            if base.endswith("es") and len(base) > 2:
                candidates.add(base[:-2])
            if base.endswith("s") and len(base) > 1:
                candidates.add(base[:-1])

        for cand in candidates:
            stem_to_target.setdefault(cand, (tname, pk_col))

    for tname, tmeta in tables.items():
        cols = tmeta.get("columns", []) if isinstance(tmeta, dict) else []
        for c in cols:
            if not isinstance(c, dict) or c.get("is_primary"):
                continue
            cname = str(c.get("name", ""))
            if not cname or (tname, cname) in seen_fk_pairs:
                continue

            target: tuple[str, str] | None = None
            if cname.lower().endswith("_id") and len(cname) > 3:
                stem = cname[:-3].lower()
                target = stem_to_target.get(stem)
            elif cname.endswith("Id") and len(cname) > 2:
                raw_stem = cname[:-2]
                snake_stem = re.sub(r"(?<!^)(?=[A-Z])", "_", raw_stem).lower()
                target = stem_to_target.get(snake_stem) or stem_to_target.get(
                    raw_stem.lower()
                )

            if target and target[0] != tname:
                target_tbl, target_col = target
                seen_fk_pairs.add((tname, cname))
                existing_fks.append(
                    {
                        "table": tname,
                        "column": cname,
                        "foreign_table": target_tbl,
                        "foreign_column": target_col,
                    }
                )
                existing_rels.append(
                    {
                        "source_table": tname,
                        "source_column": cname,
                        "target_table": target_tbl,
                        "target_column": target_col,
                    }
                )

    snapshot["foreign_keys"] = existing_fks
    snapshot["relationships"] = existing_rels

    # Populate helpful table categories if none exist and there are >= 6 tables
    if not snapshot.get("categories") and len(tables) >= 6:
        categories: dict[str, list[str]] = {}
        for tname in sorted(tables.keys()):
            if "_" in tname:
                prefix = tname.split("_", 1)[0].capitalize()
            else:
                prefix = "Core"
            categories.setdefault(prefix, []).append(tname)
        snapshot["categories"] = categories

    return snapshot


@dataclass
class DatabaseEntry:
    """Metadata and connection parameters for a registered database."""

    id: str
    name: str
    group: str
    dialect: str
    description: str
    icon: str
    default_table: str
    sqlite_path: Path | None = None
    pg_config: dict[str, Any] | None = None
    mysql_config: dict[str, Any] | None = None
    duckdb_path: str | None = None
    schema_name: str = "public"
    is_starter: bool = False
    is_custom: bool = False


# Dynamic registry of custom user-connected databases added via the UI
_CUSTOM_DATABASES: dict[str, DatabaseEntry] = {}
_UPLOAD_DIR = Path(os.environ.get("QB_UPLOAD_DIR", "/tmp/qb_uploads"))
_CUSTOM_DB_REGISTRY_FILE = _UPLOAD_DIR / "custom_databases.json"


def _save_custom_databases() -> None:
    """Persists custom database entries to disk so connections survive server restarts."""
    with contextlib.suppress(OSError):
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        payload = []
        for entry in _CUSTOM_DATABASES.values():
            payload.append(
                {
                    "id": entry.id,
                    "name": entry.name,
                    "group": entry.group,
                    "dialect": entry.dialect,
                    "description": entry.description,
                    "icon": entry.icon,
                    "default_table": entry.default_table,
                    "sqlite_path": (
                        str(entry.sqlite_path)
                        if entry.sqlite_path is not None
                        else None
                    ),
                    "pg_config": entry.pg_config,
                    "mysql_config": entry.mysql_config,
                    "duckdb_path": entry.duckdb_path,
                    "schema_name": entry.schema_name,
                    "is_starter": entry.is_starter,
                    "is_custom": True,
                }
            )
        _CUSTOM_DB_REGISTRY_FILE.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


def _load_custom_databases() -> None:
    """Loads persisted custom database entries from disk if _CUSTOM_DATABASES is empty."""
    if _CUSTOM_DATABASES or not _CUSTOM_DB_REGISTRY_FILE.is_file():
        return
    with contextlib.suppress(Exception):
        raw = json.loads(_CUSTOM_DB_REGISTRY_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return
        builtin_ids = get_builtin_database_ids()
        for item in raw:
            if not isinstance(item, dict):
                continue
            db_id = str(item.get("id") or "").strip()
            if not db_id or db_id in builtin_ids:
                continue
            sqlite_raw = item.get("sqlite_path")
            _CUSTOM_DATABASES[db_id] = DatabaseEntry(
                id=db_id,
                name=str(item.get("name") or db_id),
                group=str(item.get("group") or "🔌 Custom Connections"),
                dialect=str(item.get("dialect") or "sqlite"),
                description=str(item.get("description") or ""),
                icon=str(item.get("icon") or "🔌"),
                default_table=str(item.get("default_table") or ""),
                sqlite_path=Path(sqlite_raw) if sqlite_raw else None,
                pg_config=item.get("pg_config")
                if isinstance(item.get("pg_config"), dict)
                else None,
                mysql_config=item.get("mysql_config")
                if isinstance(item.get("mysql_config"), dict)
                else None,
                duckdb_path=str(item.get("duckdb_path"))
                if item.get("duckdb_path")
                else None,
                schema_name=str(item.get("schema_name") or "public"),
                is_starter=bool(item.get("is_starter", False)),
                is_custom=True,
            )


def clear_custom_databases() -> None:
    """Clears all dynamically connected custom databases (used in test teardown)."""
    _load_custom_databases()
    for db_id, entry in list(_CUSTOM_DATABASES.items()):
        _SCHEMA_CACHE.pop(db_id, None)
        if (
            entry.sqlite_path
            and entry.sqlite_path.parent == _UPLOAD_DIR
            and entry.sqlite_path.is_file()
        ):
            with contextlib.suppress(OSError):
                entry.sqlite_path.unlink()
    _CUSTOM_DATABASES.clear()
    _SCHEMA_CACHE.pop("federated_hub", None)
    with contextlib.suppress(OSError):
        if _CUSTOM_DB_REGISTRY_FILE.is_file():
            _CUSTOM_DB_REGISTRY_FILE.unlink()


def get_builtin_database_ids() -> set[str]:
    """Returns the set of built-in starter database IDs."""
    return {
        "starter_demo",
        "federated_hub",
    }


def get_database_registry() -> dict[str, DatabaseEntry]:
    """Builds the registry of all built-in and user-connected databases."""
    entries = [
        DatabaseEntry(
            id="starter_demo",
            name="Starter Demo (E-Commerce SQLite)",
            group="SQLite — Demo",
            dialect="sqlite",
            description="Built-in E-Commerce sample dataset (categories, products, users, orders, order_items).",
            icon="🛒",
            default_table="products",
            sqlite_path=db_path,
            is_starter=True,
        ),
        DatabaseEntry(
            id="federated_hub",
            name="Federated Cross-Database Hub (Join Across All DBs)",
            group="🌐 Cross-Database Federation",
            dialect="sqlite",
            description="Unified federated query engine: join tables across all connected PostgreSQL, MySQL, DuckDB, and SQLite databases in a single query.",
            icon="🌐",
            default_table="starter_demo__products",
        ),
    ]
    _load_custom_databases()
    registry = {e.id: e for e in entries}
    registry.update(_CUSTOM_DATABASES)
    return registry


def _register_custom_operators() -> None:
    """Registers starter custom SQL filter operators on the backend compiler."""
    register_filter_operator(
        "TAX_EXEMPT",
        lambda col_ref, val, dialect: f"{col_ref} IS NOT NULL AND {col_ref} = 0",
    )


_register_custom_operators()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI starter backend.
    Configures Query-Builder with development profile and initializes database
    during application runtime, cleaning up global state on shutdown.
    """
    configure_query_builder(
        profile="development",
        default_dialect="sqlite",
        default_limit=50,
    )
    _register_custom_operators()
    with contextlib.closing(init_database(db_path)):
        pass
    try:
        yield
    finally:
        reset_query_builder_config()
        reset_security_config()


# Create FastAPI app
app = FastAPI(
    title="Query-Builder Fullstack Starter API",
    description="Interactive backend demonstrating Query-Builder schema introspection, compilation, and execution across connected databases.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def database_context_middleware(request: Request, call_next: Any) -> Any:
    """Extracts the requested database ID from query params, headers, or JSON body."""
    db_id = (
        request.query_params.get("db") or request.headers.get("x-qb-database") or None
    )
    if not db_id and request.method in ("POST", "PUT", "PATCH"):
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            with contextlib.suppress(Exception):
                body_bytes = await request.body()
                if body_bytes:
                    parsed = json.loads(body_bytes)
                    if isinstance(parsed, dict) and isinstance(parsed.get("db"), str):
                        db_id = parsed["db"]

    if not db_id:
        db_id = os.environ.get("QB_DEFAULT_DB", "starter_demo")

    if request.query_params.get("refresh", "").lower() in ("true", "1", "yes"):
        _SCHEMA_CACHE.pop(db_id, None)

    token = _active_db_id.set(db_id)
    try:
        return await call_next(request)
    finally:
        _active_db_id.reset(token)


class StarterSQLiteConnector(SQLiteConnector):
    """SQLiteConnector enriched with starter schema metadata (enums, comments, categories)."""

    def introspect_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            live_schema = super().introspect_schema(*args, **kwargs)
            rich_snapshot = snapshot_to_dict(get_starter_schema_snapshot())
            rich_tables = rich_snapshot.get("tables", {})
            live_tables = live_schema.get("tables", {})

            for table_name, live_table in live_tables.items():
                rich_table = rich_tables.get(table_name)
                if not rich_table or not isinstance(live_table, dict):
                    continue
                rich_comment = (
                    rich_table.get("comment")
                    if isinstance(rich_table, dict)
                    else getattr(rich_table, "comment", None)
                )
                if rich_comment and not live_table.get("comment"):
                    live_table["comment"] = rich_comment

                rich_enums = (
                    rich_table.get("enums")
                    if isinstance(rich_table, dict)
                    else getattr(rich_table, "enums", None)
                )
                if rich_enums and not live_table.get("enums"):
                    live_table["enums"] = dict(rich_enums)

                raw_rich_cols = (
                    rich_table.get("columns", [])
                    if isinstance(rich_table, dict)
                    else getattr(rich_table, "columns", [])
                )
                rich_cols: dict[str, Any] = {}
                for rc in raw_rich_cols:
                    rc_name = (
                        rc.get("name")
                        if isinstance(rc, dict)
                        else getattr(rc, "name", None)
                    )
                    if rc_name:
                        rich_cols[rc_name] = rc

                for col in live_table.get("columns", []):
                    if not isinstance(col, dict):
                        continue
                    rc = rich_cols.get(col.get("name", ""))
                    if not rc:
                        continue
                    col_enums = (
                        rc.get("enums")
                        if isinstance(rc, dict)
                        else getattr(rc, "enums", None)
                    )
                    if col_enums and not col.get("enums"):
                        col["enums"] = list(col_enums)

            if rich_snapshot.get("categories") and not live_schema.get("categories"):
                live_schema["categories"] = rich_snapshot["categories"]

            return live_schema
        finally:
            self.close()

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        try:
            cols, rows, latency = super().execute_raw(sql, params)
            return cols, _sanitize_rows(rows), latency
        finally:
            self.close()

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            res = super().execute(*args, **kwargs)
            if isinstance(res, dict) and isinstance(res.get("rows"), list):
                res["rows"] = _sanitize_rows(res["rows"])
            return res
        finally:
            self.close()


class ManagedSQLiteConnector(SQLiteConnector):
    """Read-only SQLite connector with FK inference, caching, and binary sanitization."""

    def __init__(self, db_id: str, database: str, **kwargs: Any) -> None:
        super().__init__(database=database, **kwargs)
        self.db_id = db_id

    def _read_only_uri_applicable(self, kwargs: dict[str, Any]) -> bool:
        db = str(self.database)
        return bool(
            not kwargs.get("uri")
            and db not in ("", ":memory:")
            and not db.startswith("file:")
            and os.path.isfile(db)
        )

    def connect(self) -> Any:
        was_connected = self._connection is not None
        conn = super().connect()
        if not was_connected:
            if str(self.database) == ":memory:":
                with contextlib.suppress(Exception):
                    conn.executescript(SCHEMA_DDL)
                    conn.executescript(SEED_DATA_SQL)
                    conn.commit()
            with contextlib.suppress(Exception):
                self.apply_read_only(conn)
        return conn

    def introspect_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        cached = _SCHEMA_CACHE.get(self.db_id)
        if cached and (time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL_SEC:
            return dict(cached[1])
        try:
            raw_schema = super().introspect_schema(*args, **kwargs)
            enriched = infer_missing_foreign_keys(raw_schema)
            _SCHEMA_CACHE[self.db_id] = (time.monotonic(), enriched)
            return dict(enriched)
        finally:
            self.close()

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        try:
            cols, rows, latency = super().execute_raw(sql, params)
            return cols, _sanitize_rows(rows), latency
        finally:
            self.close()

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            res = super().execute(*args, **kwargs)
            if isinstance(res, dict) and isinstance(res.get("rows"), list):
                res["rows"] = _sanitize_rows(res["rows"])
            return res
        finally:
            self.close()


class ManagedPostgresConnector(PostgresConnector):
    """Read-only PostgreSQL connector with FK inference, caching, and binary sanitization."""

    def __init__(self, db_id: str, schema_name: str = "public", **config: Any) -> None:
        super().__init__(schema_name=schema_name, **config)
        self.db_id = db_id

    def connect(self) -> Any:
        try:
            conn = super().connect()
        except Exception:
            host = str(self.config.get("host", "")).lower()
            port = int(self.config.get("port", 5432))
            fallback_host = os.environ.get("QB_PG_DOCKER_HOST")
            fallback_port = int(os.environ.get("QB_PG_DOCKER_PORT", str(port)))
            if (
                host not in ("localhost", "127.0.0.1", "::1")
                or not fallback_host
                or fallback_host == host
            ):
                raise
            self.config["host"] = fallback_host
            self.config["port"] = fallback_port
            self.config.pop("hostaddr", None)
            conn = super().connect()
        with contextlib.suppress(Exception):
            _pg_read_only(conn)
        return conn

    def introspect_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        cached = _SCHEMA_CACHE.get(self.db_id)
        if cached and (time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL_SEC:
            return dict(cached[1])
        try:
            raw_schema = super().introspect_schema(*args, **kwargs)
            enriched = infer_missing_foreign_keys(raw_schema)
            _SCHEMA_CACHE[self.db_id] = (time.monotonic(), enriched)
            return dict(enriched)
        finally:
            self.close()

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        try:
            cols, rows, latency = super().execute_raw(sql, params)
            return cols, _sanitize_rows(rows), latency
        finally:
            self.close()

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            res = super().execute(*args, **kwargs)
            if isinstance(res, dict) and isinstance(res.get("rows"), list):
                res["rows"] = _sanitize_rows(res["rows"])
            return res
        finally:
            self.close()


class ManagedMySQLConnector(MySQLConnector):
    """Read-only MySQL/MariaDB connector with FK inference, caching, and binary sanitization."""

    def __init__(self, db_id: str, database: str = "mysql", **config: Any) -> None:
        super().__init__(database=database, **config)
        self.db_id = db_id

    def introspect_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        cached = _SCHEMA_CACHE.get(self.db_id)
        if cached and (time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL_SEC:
            return dict(cached[1])
        try:
            raw_schema = super().introspect_schema(*args, **kwargs)
            enriched = infer_missing_foreign_keys(raw_schema)
            _SCHEMA_CACHE[self.db_id] = (time.monotonic(), enriched)
            return dict(enriched)
        finally:
            self.close()

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        try:
            cols, rows, latency = super().execute_raw(sql, params)
            return cols, _sanitize_rows(rows), latency
        finally:
            self.close()

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            res = super().execute(*args, **kwargs)
            if isinstance(res, dict) and isinstance(res.get("rows"), list):
                res["rows"] = _sanitize_rows(res["rows"])
            return res
        finally:
            self.close()


_DUCKDB_MEMORY_SEED_SQL = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    description VARCHAR,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name VARCHAR NOT NULL,
    price DOUBLE NOT NULL,
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    status VARCHAR NOT NULL,
    description VARCHAR
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email VARCHAR NOT NULL,
    full_name VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    last_login VARCHAR
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status VARCHAR NOT NULL,
    total_amount DOUBLE NOT NULL,
    shipping_address VARCHAR,
    created_at VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price DOUBLE NOT NULL,
    discount DOUBLE DEFAULT 0.0
);
"""


class ManagedDuckDBConnector(DuckDBConnector):
    """Read-only DuckDB connector with FK inference, caching, and binary sanitization."""

    def __init__(self, db_id: str, database: str = ":memory:", **config: Any) -> None:
        super().__init__(database=database, **config)
        self.db_id = db_id

    def connect(self) -> Any:
        was_connected = self._connection is not None
        conn = super().connect()
        if not was_connected and str(self.database) == ":memory:":
            with contextlib.suppress(Exception):
                conn.execute(_DUCKDB_MEMORY_SEED_SQL)
                conn.execute(SEED_DATA_SQL)
        return conn

    def introspect_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        cached = _SCHEMA_CACHE.get(self.db_id)
        if cached and (time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL_SEC:
            return dict(cached[1])
        try:
            raw_schema = super().introspect_schema(*args, **kwargs)
            enriched = infer_missing_foreign_keys(raw_schema)
            _SCHEMA_CACHE[self.db_id] = (time.monotonic(), enriched)
            return dict(enriched)
        finally:
            self.close()

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        try:
            cols, rows, latency = super().execute_raw(sql, params)
            return cols, _sanitize_rows(rows), latency
        finally:
            self.close()

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            res = super().execute(*args, **kwargs)
            if isinstance(res, dict) and isinstance(res.get("rows"), list):
                res["rows"] = _sanitize_rows(res["rows"])
            return res
        finally:
            self.close()


def _coerce_sqlite_param(val: Any) -> Any:
    """Coerces PostgreSQL-specific Python types (JSONB dicts/lists, UUID, Decimal, datetime) for SQLite."""
    if val is None or isinstance(val, (int, float, str, bytes)):
        return val
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, (bytes, bytearray, memoryview)):
        return bytes(val)
    if isinstance(val, (dict, list, tuple)):
        return json.dumps(val, default=str)
    return str(val)


class _FederatedCursorProxy:
    """DB-API cursor proxy that lazily attaches SQLite DBs and materializes PostgreSQL tables on demand."""

    def __init__(self, conn: Any, real_cursor: Any) -> None:
        self._conn = conn
        self._cur = real_cursor
        self._loaded_tables: set[str] = set()
        self._attached_dbs: set[str] = set()

    def _rewrite_dot_syntax(self, sql: str, registry: dict[str, DatabaseEntry]) -> str:
        """Allows raw SQL queries to reference `<db_id>.<table_name>` in addition to `<db_id>__<table_name>`."""
        db_ids = [k for k in registry if k != "federated_hub"]
        if not db_ids:
            return sql
        pattern = re.compile(
            r'(?:"('
            + "|".join(re.escape(d) for d in db_ids)
            + r')"\s*\.\s*"([A-Za-z0-9_]+)")'
            r"|(?:(?<!\w)("
            + "|".join(re.escape(d) for d in db_ids)
            + r")\.([A-Za-z0-9_]+)\b)"
        )

        def _repl(m: re.Match[str]) -> str:
            db_id = m.group(1) or m.group(3)
            tbl = m.group(2) or m.group(4)
            return f'"{db_id}__{tbl}"'

        return pattern.sub(_repl, sql)

    def _materialize_referenced_tables(self, sql: str) -> str:
        registry = get_database_registry()
        rewritten_sql = self._rewrite_dot_syntax(sql, registry)

        matches = re.findall(r"\b([a-z0-9_]+)__([A-Za-z0-9_]+)\b", rewritten_sql)
        for db_id, tbl_name in matches:
            fed_name = f"{db_id}__{tbl_name}"
            if (
                fed_name in self._loaded_tables
                or db_id not in registry
                or db_id == "federated_hub"
            ):
                continue

            entry = registry[db_id]
            safe_fed = fed_name.replace('"', '""')
            safe_tbl = tbl_name.replace('"', '""')

            # Fast zero-copy path for SQLite databases via ATTACH DATABASE + TEMP VIEW
            if (
                entry.dialect == "sqlite"
                and entry.sqlite_path is not None
                and str(entry.sqlite_path) != ":memory:"
                and len(self._attached_dbs) < 8
            ):
                alias = f"att_{db_id}"
                if db_id not in self._attached_dbs:
                    uri_base = entry.sqlite_path.resolve().as_uri() + "?mode=ro"
                    try:
                        self._conn.execute(
                            f"ATTACH DATABASE '{uri_base}' AS \"{alias}\""
                        )
                        self._conn.execute(
                            f'SELECT 1 FROM "{alias}".sqlite_master LIMIT 1'
                        ).fetchall()
                    except Exception:
                        with contextlib.suppress(Exception):
                            self._conn.execute(f'DETACH DATABASE "{alias}"')
                        self._conn.execute(
                            f"ATTACH DATABASE '{uri_base}&immutable=1' AS \"{alias}\""
                        )
                    self._attached_dbs.add(db_id)

                self._conn.execute(
                    f'CREATE TEMP VIEW IF NOT EXISTS "{safe_fed}" AS SELECT * FROM "{alias}"."{safe_tbl}"'
                )
                self._loaded_tables.add(fed_name)
                continue

            # Materialization path for PostgreSQL tables (or overflow SQLite DBs)
            src_conn = get_connector_for_db(db_id)
            try:
                cols, rows, _ = src_conn.execute_raw(
                    f'SELECT * FROM "{safe_tbl}" LIMIT 25000'
                )
                if not cols:
                    schema = src_conn.introspect_schema()
                    tmeta = schema.get("tables", {}).get(tbl_name, {})
                    cols = [c["name"] for c in tmeta.get("columns", [])]
                if not cols:
                    continue

                col_defs = ", ".join(
                    f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cols
                )
                self._conn.execute(
                    f'CREATE TEMP TABLE IF NOT EXISTS "{safe_fed}" ({col_defs})'
                )
                if rows:
                    placeholders = ", ".join("?" for _ in cols)
                    tuples = [
                        tuple(_coerce_sqlite_param(r.get(c)) for c in cols)
                        for r in rows
                    ]
                    self._conn.executemany(
                        f'INSERT INTO "{safe_fed}" VALUES ({placeholders})',
                        tuples,
                    )
                self._loaded_tables.add(fed_name)
            finally:
                src_conn.close()

        return rewritten_sql

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        rewritten = self._materialize_referenced_tables(sql)
        return self._cur.execute(rewritten, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cur, name)


class FederatedCrossDatabaseConnector(SQLiteConnector):
    """Federated cross-database connector joining tables across all registered databases."""

    def __init__(self) -> None:
        super().__init__(database=":memory:")

    @contextlib.contextmanager
    def get_cursor(self):
        conn = self.connect()
        real_cur = conn.cursor()
        try:
            yield _FederatedCursorProxy(conn, real_cur)
        finally:
            with contextlib.suppress(Exception):
                real_cur.close()

    def introspect_schema(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        cached = _SCHEMA_CACHE.get("federated_hub")
        if cached and (time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL_SEC:
            return dict(cached[1])

        registry = get_database_registry()
        tables: dict[str, dict[str, Any]] = {}
        foreign_keys: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        categories: dict[str, list[str]] = {}

        for db_id, entry in registry.items():
            if db_id == "federated_hub":
                continue
            with contextlib.suppress(Exception):
                conn = get_connector_for_db(db_id)
                try:
                    sub_schema = conn.introspect_schema()
                finally:
                    conn.close()
                cat_label = f"{entry.icon} {db_id}"
                for tname, tmeta in sub_schema.get("tables", {}).items():
                    fed_tname = f"{db_id}__{tname}"
                    tcopy = dict(tmeta)
                    tcopy["name"] = fed_tname
                    orig_comment = tcopy.get("comment") or ""
                    tcopy["comment"] = f"[{entry.name}] {orig_comment}".strip()
                    tables[fed_tname] = tcopy
                    categories.setdefault(cat_label, []).append(fed_tname)

                for fk in sub_schema.get("foreign_keys", []):
                    src_t = f"{db_id}__{fk['table']}"
                    dst_t = f"{db_id}__{fk['foreign_table']}"
                    if src_t in tables and dst_t in tables:
                        foreign_keys.append(
                            {
                                "table": src_t,
                                "column": fk["column"],
                                "foreign_table": dst_t,
                                "foreign_column": fk["foreign_column"],
                            }
                        )
                        relationships.append(
                            {
                                "source_table": src_t,
                                "source_column": fk["column"],
                                "target_table": dst_t,
                                "target_column": fk["foreign_column"],
                            }
                        )

        # Dynamically infer cross-database foreign keys across distinct connected databases
        stem_targets: dict[str, list[tuple[str, str, str]]] = {}
        for fed_tname, tmeta in tables.items():
            if "__" not in fed_tname:
                continue
            t_db, raw_t = fed_tname.split("__", 1)
            cols = tmeta.get("columns", []) if isinstance(tmeta, dict) else []
            pk_col = next(
                (
                    str(c.get("name"))
                    for c in cols
                    if isinstance(c, dict) and c.get("is_primary")
                ),
                None,
            ) or next(
                (
                    str(c.get("name"))
                    for c in cols
                    if isinstance(c, dict) and str(c.get("name", "")).lower() == "id"
                ),
                None,
            )
            if not pk_col:
                continue
            low = raw_t.lower()
            stems = {low}
            if low.endswith("ies") and len(low) > 3:
                stems.add(low[:-3] + "y")
            if low.endswith("es") and len(low) > 2:
                stems.add(low[:-2])
            if low.endswith("s") and len(low) > 1:
                stems.add(low[:-1])
            for st in stems:
                stem_targets.setdefault(st, []).append((t_db, fed_tname, pk_col))

        seen_cross_fks = {
            (fk["table"], fk["column"], fk["foreign_table"]) for fk in foreign_keys
        }
        for src_fed, tmeta in tables.items():
            if "__" not in src_fed:
                continue
            src_db, _ = src_fed.split("__", 1)
            cols = tmeta.get("columns", []) if isinstance(tmeta, dict) else []
            for c in cols:
                if not isinstance(c, dict) or c.get("is_primary"):
                    continue
                cname = str(c.get("name", ""))
                if not cname.lower().endswith("_id") or len(cname) <= 3:
                    continue
                stem = cname[:-3].lower()
                for dst_db, dst_fed, dst_pk in stem_targets.get(stem, []):
                    if (
                        dst_db != src_db
                        and (src_fed, cname, dst_fed) not in seen_cross_fks
                    ):
                        seen_cross_fks.add((src_fed, cname, dst_fed))
                        foreign_keys.append(
                            {
                                "table": src_fed,
                                "column": cname,
                                "foreign_table": dst_fed,
                                "foreign_column": dst_pk,
                            }
                        )
                        relationships.append(
                            {
                                "source_table": src_fed,
                                "source_column": cname,
                                "target_table": dst_fed,
                                "target_column": dst_pk,
                            }
                        )

        result = {
            "tables": tables,
            "foreign_keys": foreign_keys,
            "relationships": relationships,
            "categories": categories,
        }
        _SCHEMA_CACHE["federated_hub"] = (time.monotonic(), result)
        return dict(result)

    def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        try:
            cols, rows, latency = super().execute_raw(sql, params)
            return cols, _sanitize_rows(rows), latency
        finally:
            self.close()

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            res = super().execute(*args, **kwargs)
            if isinstance(res, dict) and isinstance(res.get("rows"), list):
                res["rows"] = _sanitize_rows(res["rows"])
            return res
        finally:
            self.close()


def _instantiate_connector_for_entry(entry: DatabaseEntry) -> BaseConnector:
    """Instantiates the appropriate connector for a DatabaseEntry."""
    if entry.id == "federated_hub":
        return FederatedCrossDatabaseConnector()

    if entry.is_starter:
        return StarterSQLiteConnector(database=str(db_path))

    if entry.dialect == "postgres" and entry.pg_config is not None:
        return ManagedPostgresConnector(
            db_id=entry.id,
            schema_name=entry.schema_name,
            **entry.pg_config,
        )

    if entry.dialect == "mysql" and entry.mysql_config is not None:
        mysql_kwargs = dict(entry.mysql_config)
        dbname = str(mysql_kwargs.pop("database", entry.schema_name or "mysql"))
        return ManagedMySQLConnector(
            db_id=entry.id,
            database=dbname,
            **mysql_kwargs,
        )

    if entry.dialect == "duckdb":
        return ManagedDuckDBConnector(
            db_id=entry.id,
            database=str(entry.duckdb_path or ":memory:"),
        )

    sqlite_file = entry.sqlite_path or db_path
    return ManagedSQLiteConnector(
        db_id=entry.id,
        database=str(sqlite_file),
    )


def get_connector_for_db(db_id: str | None = None) -> BaseConnector:
    """Instantiates a request-scoped connector for the specified database ID."""
    _register_custom_operators()
    registry = get_database_registry()
    resolved_id = (
        db_id or _active_db_id.get() or os.environ.get("QB_DEFAULT_DB", "starter_demo")
    )
    entry = registry.get(resolved_id)
    if entry is None:
        entry = registry["starter_demo"]
    return _instantiate_connector_for_entry(entry)


def connector() -> BaseConnector:
    """Factory invoked per-request by create_query_builder_router."""
    return get_connector_for_db(_active_db_id.get())


class DatabaseConnectionPayload(BaseModel):
    """Request payload for testing or registering a database connection from the UI."""

    id: str | None = Field(default=None, description="Optional custom database ID")
    name: str = Field(
        default="Custom Database", description="Human-readable connection name"
    )
    dialect: str = Field(
        default="sqlite",
        description="Database dialect: postgres, mysql, sqlite, duckdb",
    )
    connection_uri: str | None = Field(
        default=None,
        description="Optional connection URI (postgresql://, mysql://, sqlite:///)",
    )
    host: str | None = Field(default=None, description="Database server hostname or IP")
    port: int | None = Field(default=None, description="Database server port")
    database: str | None = Field(default=None, description="Database name or file path")
    user: str | None = Field(default=None, description="Database username")
    password: str | None = Field(default=None, description="Database password")
    schema_name: str | None = Field(
        default="public", description="Target database schema"
    )
    sslmode: str | None = Field(default=None, description="Optional SSL mode")
    file_path: str | None = Field(
        default=None, description="File path for SQLite or DuckDB"
    )

    model_config = ConfigDict(extra="allow")


class DatabaseUploadPayload(BaseModel):
    """Request payload for uploading a SQLite, CSV, or JSON file to create a connected database."""

    name: str | None = Field(
        default=None, description="Display name for the uploaded database"
    )
    filename: str = Field(description="Original filename (.sqlite, .db, .csv, .json)")
    content_base64: str = Field(description="Base64-encoded file bytes")

    model_config = ConfigDict(extra="allow")


def _resolve_local_db_path(raw_target: str, label: str = "SQLite database") -> Path:
    """Resolves a local SQLite or DuckDB path, handling 3-slash URIs, query params, and Windows/UNC paths."""
    cleaned = raw_target.split("?", 1)[0].strip()
    normalized = (
        cleaned.lstrip("/")
        if re.match(r"^/+([A-Za-z]:[\\/]|\\\\)", cleaned)
        else cleaned
    )
    candidate = Path(normalized).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    if not candidate.is_absolute() and not re.match(
        r"^([A-Za-z]:[\\/]|\\\\|//)", normalized
    ):
        rel_starter = starter_root / candidate
        if rel_starter.is_file():
            return rel_starter.resolve()
        abs_root = Path("/") / candidate
        if abs_root.is_file():
            return abs_root.resolve()

    raise HTTPException(
        status_code=400,
        detail=f"{label} file not found: '{raw_target}'",
    )


def _parse_backend_connection_uri(raw_uri: str) -> dict[str, Any]:
    """Parses a connection URI string into normalized dialect and connection fields."""
    trimmed = raw_uri.strip()
    lower = trimmed.lower()
    if lower.startswith("sqlite:///") or lower.startswith("sqlite://"):
        path_part = re.sub(r"^sqlite:///?", "", trimmed, flags=re.IGNORECASE)
        path_part = path_part.split("?", 1)[0].strip()
        if re.match(r"^/+([A-Za-z]:[\\/]|\\\\)", path_part):
            path_part = path_part.lstrip("/")
        elif not re.match(r"^([A-Za-z]:[\\/]|\\\\|//)", path_part):
            if trimmed.lower().startswith("sqlite:////") and not path_part.startswith(
                "/"
            ):
                path_part = "/" + path_part
            elif (
                trimmed.lower().startswith("sqlite:///")
                and path_part
                and path_part != ":memory:"
                and not path_part.startswith("/")
                and (Path("/") / path_part).exists()
            ):
                path_part = "/" + path_part
        return {
            "dialect": "sqlite",
            "file_path": path_part or ":memory:",
            "database": path_part or ":memory:",
        }
    if lower.startswith("duckdb:///") or lower.startswith("duckdb://"):
        path_part = re.sub(r"^duckdb:///?", "", trimmed, flags=re.IGNORECASE)
        path_part = path_part.split("?", 1)[0].strip()
        if re.match(r"^/+([A-Za-z]:[\\/]|\\\\)", path_part):
            path_part = path_part.lstrip("/")
        elif not re.match(r"^([A-Za-z]:[\\/]|\\\\|//)", path_part):
            if trimmed.lower().startswith("duckdb:////") and not path_part.startswith(
                "/"
            ):
                path_part = "/" + path_part
            elif (
                trimmed.lower().startswith("duckdb:///")
                and path_part
                and path_part != ":memory:"
                and not path_part.startswith("/")
                and (Path("/") / path_part).exists()
            ):
                path_part = "/" + path_part
        return {
            "dialect": "duckdb",
            "file_path": path_part or ":memory:",
            "database": path_part or ":memory:",
        }

    dialect = "postgres"
    normalized = trimmed
    if re.match(r"^postgres(ql)?(\+\w+)?://", trimmed, flags=re.IGNORECASE):
        dialect = "postgres"
        normalized = re.sub(
            r"^postgres(ql)?(\+\w+)?://", "http://", trimmed, flags=re.IGNORECASE
        )
    elif re.match(r"^(mysql|mariadb)(\+\w+)?://", trimmed, flags=re.IGNORECASE):
        dialect = "mysql"
        normalized = re.sub(
            r"^(mysql|mariadb)(\+\w+)?://", "http://", trimmed, flags=re.IGNORECASE
        )
    else:
        raise ValueError(
            "Unsupported connection URI scheme. Supported schemes: postgresql://, mysql://, sqlite:///, duckdb:///"
        )

    parsed = urllib.parse.urlsplit(normalized)
    qs = urllib.parse.parse_qs(parsed.query)
    dbname = urllib.parse.unquote(parsed.path.lstrip("/"))
    schema_name = (
        (qs.get("schema") or qs.get("currentSchema") or ["public"])[0]
        if dialect == "postgres"
        else dbname
    )
    sslmode = (qs.get("sslmode") or [None])[0]
    default_port = 5432 if dialect == "postgres" else 3306
    return {
        "dialect": dialect,
        "host": parsed.hostname or "localhost",
        "port": parsed.port or default_port,
        "database": dbname,
        "user": urllib.parse.unquote(parsed.username) if parsed.username else None,
        "password": urllib.parse.unquote(parsed.password) if parsed.password else None,
        "schema_name": schema_name,
        "sslmode": sslmode,
    }


def _slugify_db_id(raw_name: str, existing_ids: set[str]) -> str:
    """Generates a safe, collision-free database identifier."""
    slug = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_") or "database"
    if not slug.startswith("custom_"):
        slug = f"custom_{slug}"
    candidate = slug
    counter = 2
    while candidate in existing_ids or candidate in get_builtin_database_ids():
        candidate = f"{slug}_{counter}"
        counter += 1
    return candidate


def _build_entry_from_payload(
    payload: DatabaseConnectionPayload,
    assign_id: bool = False,
) -> DatabaseEntry:
    """Constructs a DatabaseEntry from a DatabaseConnectionPayload."""
    _load_custom_databases()
    fields: dict[str, Any] = {
        "dialect": (payload.dialect or "sqlite").lower().strip(),
        "host": payload.host,
        "port": payload.port,
        "database": payload.database,
        "user": payload.user,
        "password": payload.password,
        "schema_name": payload.schema_name or "public",
        "sslmode": payload.sslmode,
        "file_path": payload.file_path,
    }
    if payload.connection_uri and payload.connection_uri.strip():
        uri_fields = _parse_backend_connection_uri(payload.connection_uri)
        for k, v in uri_fields.items():
            if v is not None:
                fields[k] = v

    dialect = str(fields["dialect"]).lower()
    if dialect in ("postgresql", "pg"):
        dialect = "postgres"
    elif dialect in ("mariadb",):
        dialect = "mysql"

    existing_ids = set(_CUSTOM_DATABASES.keys())
    if assign_id:
        normalized_req_id = (
            re.sub(r"[^a-z0-9_]", "_", payload.id.strip().lower()).strip("_")
            if payload.id and payload.id.strip()
            else ""
        )
        if (
            normalized_req_id
            and normalized_req_id not in get_builtin_database_ids()
            and normalized_req_id not in existing_ids
        ):
            db_id = normalized_req_id
        else:
            db_id = _slugify_db_id(
                payload.name or fields.get("database") or dialect, existing_ids
            )
    else:
        db_id = f"_test_{int(time.monotonic() * 1000)}"

    display_name = (payload.name or "").strip() or str(
        fields.get("database") or fields.get("file_path") or "Custom Database"
    )

    if dialect == "sqlite":
        raw_target = str(
            fields.get("file_path") or fields.get("database") or ""
        ).strip()
        if not raw_target:
            raise HTTPException(
                status_code=400, detail="SQLite file_path or database path is required."
            )
        if raw_target != ":memory:":
            sqlite_path: Path | None = _resolve_local_db_path(
                raw_target, "SQLite database"
            )
        else:
            sqlite_path = Path(":memory:")
        return DatabaseEntry(
            id=db_id,
            name=display_name,
            group="🔌 Custom Connections",
            dialect="sqlite",
            description=f"Custom SQLite database ({raw_target})",
            icon="🔌",
            default_table="",
            sqlite_path=sqlite_path,
            schema_name="main",
            is_custom=True,
        )

    if dialect == "duckdb":
        raw_target = str(
            fields.get("file_path") or fields.get("database") or ":memory:"
        ).strip()
        if raw_target != ":memory:":
            resolved_duck = _resolve_local_db_path(raw_target, "DuckDB")
            raw_target = str(resolved_duck)
        return DatabaseEntry(
            id=db_id,
            name=display_name,
            group="🔌 Custom Connections",
            dialect="duckdb",
            description=f"Custom DuckDB database ({raw_target})",
            icon="🦆",
            default_table="",
            duckdb_path=raw_target,
            schema_name="main",
            is_custom=True,
        )

    if dialect == "postgres":
        host = str(fields.get("host") or "127.0.0.1").strip()
        port = int(fields.get("port") or 5432)
        dbname = str(fields.get("database") or "").strip()
        if not dbname:
            raise HTTPException(
                status_code=400, detail="PostgreSQL database name is required."
            )
        user = str(fields.get("user") or "postgres").strip()
        password = str(fields.get("password") or "")
        schema_name = str(fields.get("schema_name") or "public").strip() or "public"

        pg_config: dict[str, Any] = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "connect_timeout": 5,
        }
        if schema_name and schema_name != "public":
            pg_config["options"] = f"-c search_path={schema_name},public"
        if fields.get("sslmode"):
            pg_config["sslmode"] = str(fields["sslmode"])

        return DatabaseEntry(
            id=db_id,
            name=display_name,
            group="🔌 Custom Connections",
            dialect="postgres",
            description=f"PostgreSQL — {host}:{port}/{dbname} ({schema_name})",
            icon="🐘",
            default_table="",
            pg_config=pg_config,
            schema_name=schema_name,
            is_custom=True,
        )

    if dialect == "mysql":
        host = str(fields.get("host") or "127.0.0.1").strip()
        port = int(fields.get("port") or 3306)
        dbname = str(fields.get("database") or "").strip()
        if not dbname:
            raise HTTPException(
                status_code=400, detail="MySQL database name is required."
            )
        user = str(fields.get("user") or "root").strip()
        password = str(fields.get("password") or "")
        mysql_config: dict[str, Any] = {
            "host": host,
            "port": port,
            "database": dbname,
            "user": user,
            "password": password,
            "connect_timeout": 5,
        }
        return DatabaseEntry(
            id=db_id,
            name=display_name,
            group="🔌 Custom Connections",
            dialect="mysql",
            description=f"MySQL — {host}:{port}/{dbname}",
            icon="🐬",
            default_table="",
            mysql_config=mysql_config,
            schema_name=dbname,
            is_custom=True,
        )

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported dialect '{dialect}'. Supported dialects: postgres, mysql, sqlite, duckdb.",
    )


def _serialize_database_entry(entry: DatabaseEntry) -> dict[str, Any]:
    """Serializes a DatabaseEntry for API responses without exposing credentials."""
    available = True
    if (
        entry.dialect == "sqlite"
        and entry.sqlite_path is not None
        and not entry.is_starter
        and str(entry.sqlite_path) != ":memory:"
    ):
        available = entry.sqlite_path.is_file()
    elif (
        entry.dialect == "duckdb"
        and entry.duckdb_path
        and str(entry.duckdb_path) != ":memory:"
    ):
        available = Path(entry.duckdb_path).is_file()
    elif (
        entry.dialect == "postgres"
        and entry.pg_config is not None
        and not entry.is_custom
    ):
        available = bool(entry.pg_config.get("password"))

    cached = _SCHEMA_CACHE.get(entry.id)
    table_count: int | None = None
    fk_count: int | None = None
    if cached:
        table_count = len(cached[1].get("tables", {}))
        fk_count = len(cached[1].get("foreign_keys", []))

    return {
        "id": entry.id,
        "name": entry.name,
        "group": entry.group,
        "dialect": entry.dialect,
        "schema_name": entry.schema_name,
        "description": entry.description,
        "icon": entry.icon,
        "default_table": entry.default_table,
        "available": available,
        "is_custom": entry.is_custom,
        "table_count": table_count,
        "foreign_key_count": fk_count,
    }


@app.get("/api/databases", tags=["Database Hub"])
def list_databases(refresh: bool = Query(default=False)) -> dict[str, Any]:
    """Returns all registered built-in and custom databases with live status and metadata."""
    if refresh:
        _SCHEMA_CACHE.clear()

    registry = get_database_registry()
    default_db = os.environ.get("QB_DEFAULT_DB", "starter_demo")
    if default_db not in registry:
        default_db = "starter_demo"

    databases_list = [_serialize_database_entry(entry) for entry in registry.values()]

    return {
        "default_database": default_db,
        "count": len(databases_list),
        "databases": databases_list,
    }


_SYSTEM_TABLE_RE = re.compile(
    r"^(auth_|axes_|django_|account_|socialaccount_|token_blacklist_|authtoken_|celery_|sqlite_|pg_|information_schema)",
    re.IGNORECASE,
)


def _rank_non_system_tables(tables: list[str]) -> list[str]:
    """Places core application tables ahead of framework/system plumbing tables."""
    core = [t for t in tables if not _SYSTEM_TABLE_RE.match(t)]
    sys_tables = [t for t in tables if _SYSTEM_TABLE_RE.match(t)]
    return core + sys_tables


@app.post("/api/databases/test", tags=["Database Hub"])
def test_database_connection(payload: DatabaseConnectionPayload) -> dict[str, Any]:
    """Tests a candidate database connection and previews its schema without saving it."""
    try:
        entry = _build_entry_from_payload(payload, assign_id=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    t0 = time.perf_counter()
    conn = _instantiate_connector_for_entry(entry)
    try:
        info = conn.test_connection()
        schema = conn.introspect_schema()
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        tables = _rank_non_system_tables(list((schema.get("tables") or {}).keys()))
        fks = schema.get("foreign_keys") or []
        return {
            "ok": True,
            "status": info.get("status", "connected"),
            "dialect": entry.dialect,
            "latency_ms": latency_ms,
            "engine_version": info.get("engine_version"),
            "table_count": len(tables),
            "foreign_key_count": len(fks),
            "sample_tables": tables[:12],
            "default_table": tables[0] if tables else "",
            "message": f"Connected! Found {len(tables)} tables and {len(fks)} relationships ({latency_ms} ms)",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Connection failed: {exc}",
        ) from exc
    finally:
        _SCHEMA_CACHE.pop(entry.id, None)
        with contextlib.suppress(Exception):
            conn.close()


@app.post("/api/databases/connect", tags=["Database Hub"])
@app.post("/api/databases", tags=["Database Hub"])
def connect_new_database(payload: DatabaseConnectionPayload) -> dict[str, Any]:
    """Tests, introspects, and registers a new database connection so it can be queried in the UI."""
    try:
        entry = _build_entry_from_payload(payload, assign_id=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = _instantiate_connector_for_entry(entry)
    try:
        schema = conn.introspect_schema()
        tables = _rank_non_system_tables(list((schema.get("tables") or {}).keys()))
        entry.default_table = tables[0] if tables else ""
        _CUSTOM_DATABASES[entry.id] = entry
        _save_custom_databases()
        _SCHEMA_CACHE[entry.id] = (time.monotonic(), schema)
        _SCHEMA_CACHE.pop("federated_hub", None)
        return {
            "ok": True,
            "database": _serialize_database_entry(entry),
            "schema": schema,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _SCHEMA_CACHE.pop(entry.id, None)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect to database: {exc}",
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            conn.close()


_SQLITE_INT64_MIN = -(1 << 63)
_SQLITE_INT64_MAX = (1 << 63) - 1


def _infer_sqlite_col_type(values: list[Any]) -> str:
    """Infers INTEGER, REAL, or TEXT column affinity across all non-empty values."""
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_empty:
        return "TEXT"
    all_int = True
    all_float = True
    for val in non_empty:
        if isinstance(val, (dict, list, tuple, bool)):
            return "TEXT"
        s = str(val).strip()
        if all_int:
            try:
                parsed_int = int(s)
                if not (_SQLITE_INT64_MIN <= parsed_int <= _SQLITE_INT64_MAX):
                    all_int = False
                    all_float = False
            except ValueError:
                all_int = False
        if all_float:
            try:
                parsed_float = float(s)
                if not (-float("inf") < parsed_float < float("inf")):
                    all_float = False
            except ValueError:
                all_float = False
        if not all_int and not all_float:
            return "TEXT"
    if all_int:
        return "INTEGER"
    if all_float:
        return "REAL"
    return "TEXT"


def _coerce_uploaded_cell(val: Any, col_type: str) -> Any:
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val) if col_type == "INTEGER" else str(val).lower()
    s = str(val).strip()
    if s == "":
        return None
    if col_type == "INTEGER":
        with contextlib.suppress(ValueError):
            parsed_int = int(s)
            if _SQLITE_INT64_MIN <= parsed_int <= _SQLITE_INT64_MAX:
                return parsed_int
            return s
    elif col_type == "REAL":
        with contextlib.suppress(ValueError):
            parsed_float = float(s)
            if -float("inf") < parsed_float < float("inf"):
                return parsed_float
            return s
    if isinstance(val, int) and not (_SQLITE_INT64_MIN <= val <= _SQLITE_INT64_MAX):
        return str(val)
    return val if isinstance(val, (int, float, str)) else json.dumps(val, default=str)


def _write_dict_rows_to_sqlite_table(
    sconn: sqlite3.Connection,
    table_name: str,
    rows_list: list[dict[str, Any]],
) -> None:
    """Creates a SQLite table from a list of row dicts with automatic type and primary key inference."""
    raw_keys: list[str] = []
    seen_raw_keys: set[str] = set()
    for obj in rows_list:
        if isinstance(obj, dict):
            for k in obj:
                if k not in seen_raw_keys:
                    seen_raw_keys.add(k)
                    raw_keys.append(k)
    if not raw_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Table '{table_name}' contains no column keys.",
        )

    headers: list[str] = []
    seen_cols: set[str] = set()
    for idx, k in enumerate(raw_keys):
        clean_h = (
            re.sub(r"[^A-Za-z0-9_]", "_", str(k).strip()).strip("_") or f"col_{idx + 1}"
        )
        if clean_h[0].isdigit():
            clean_h = f"c_{clean_h}"
        base_h = clean_h
        c_idx = 2
        while clean_h.lower() in seen_cols:
            clean_h = f"{base_h}_{c_idx}"
            c_idx += 1
        seen_cols.add(clean_h.lower())
        headers.append(clean_h)

    col_types = [
        _infer_sqlite_col_type(
            [row.get(k) for row in rows_list if isinstance(row, dict)]
        )
        for k in raw_keys
    ]
    col_defs_list: list[str] = []
    for i, (h, t) in enumerate(zip(headers, col_types, strict=False)):
        if h.lower() == "id" and t == "INTEGER":
            raw_vals = [
                _coerce_uploaded_cell(row.get(raw_keys[i]), t)
                for row in rows_list
                if isinstance(row, dict)
            ]
            if (
                raw_vals
                and all(
                    isinstance(v, int) and not isinstance(v, bool) for v in raw_vals
                )
                and len(set(raw_vals)) == len(raw_vals)
            ):
                col_defs_list.append(f'"{h}" INTEGER PRIMARY KEY')
                continue
        col_defs_list.append(f'"{h}" {t}')

    col_defs = ", ".join(col_defs_list)
    sconn.execute(f'CREATE TABLE "{table_name}" ({col_defs});')
    placeholders = ", ".join("?" for _ in headers)
    coerced_rows = [
        tuple(
            _coerce_uploaded_cell(row.get(raw_keys[i]), col_types[i])
            for i in range(len(raw_keys))
        )
        for row in rows_list
        if isinstance(row, dict)
    ]
    sconn.executemany(
        f'INSERT INTO "{table_name}" VALUES ({placeholders});',
        coerced_rows,
    )


_SQL_LITERAL_OR_COMMENT_RE = re.compile(
    r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|/\*[\s\S]*?\*/|--[^\r\n]*"
)
_SAFE_DUMP_PRAGMAS = {
    "foreign_keys",
    "defer_foreign_keys",
    "encoding",
    "case_sensitive_like",
    "ignore_check_constraints",
    "legacy_alter_table",
}


def _sqlite_dump_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    _dbname: str | None,
    _source: str | None,
) -> int:
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        if (arg1 or "").lower() in _SAFE_DUMP_PRAGMAS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _normalize_ddl_segment(segment: str) -> str:
    chunk = re.sub(
        r"\b(?:BIG|SMALL)?SERIAL\s+PRIMARY\s+KEY\b",
        "INTEGER PRIMARY KEY",
        segment,
        flags=re.IGNORECASE,
    )
    chunk = re.sub(
        r"\bINT(?:EGER)?\s+(?:NOT\s+NULL\s+)?AUTO_INCREMENT\s+PRIMARY\s+KEY\b",
        "INTEGER PRIMARY KEY",
        chunk,
        flags=re.IGNORECASE,
    )
    chunk = re.sub(
        r"\bINT(?:EGER)?\s+PRIMARY\s+KEY\s+AUTO_INCREMENT\b",
        "INTEGER PRIMARY KEY",
        chunk,
        flags=re.IGNORECASE,
    )
    chunk = re.sub(r"\bAUTO_INCREMENT\b", "", chunk, flags=re.IGNORECASE)
    chunk = re.sub(
        r"\)\s*ENGINE\s*=\s*[A-Za-z0-9_]+[^;]*;",
        ");",
        chunk,
        flags=re.IGNORECASE,
    )
    return chunk


def _prepare_sql_dump_for_sqlite(sql_script: str) -> str:
    """Validates a .sql dump outside of comments/literals and normalizes common PG/MySQL DDL for SQLite."""
    code_only = _SQL_LITERAL_OR_COMMENT_RE.sub(" ", sql_script)
    if re.search(r"\b(ATTACH|DETACH|LOAD_EXTENSION)\b", code_only, re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="SQL script contains restricted statements (ATTACH, DETACH, PRAGMA, or LOAD_EXTENSION).",
        )
    for m in re.finditer(r"\bPRAGMA\s+([A-Za-z0-9_.]+)", code_only, re.IGNORECASE):
        if m.group(1).lower() not in _SAFE_DUMP_PRAGMAS:
            raise HTTPException(
                status_code=400,
                detail="SQL script contains restricted statements (ATTACH, DETACH, PRAGMA, or LOAD_EXTENSION).",
            )

    parts: list[str] = []
    last_end = 0
    for match in _SQL_LITERAL_OR_COMMENT_RE.finditer(sql_script):
        parts.append(_normalize_ddl_segment(sql_script[last_end : match.start()]))
        parts.append(match.group(0))
        last_end = match.end()
    parts.append(_normalize_ddl_segment(sql_script[last_end:]))
    normalized = "".join(parts)
    normalized = re.sub(
        r"(?m)^\s*(?:SET\s+(?:SESSION\s+|GLOBAL\s+|LOCAL\s+|NAMES\s+|CHARACTER\s+SET\s+|statement_timeout|lock_timeout|idle_in_transaction_session_timeout|client_encoding|standard_conforming_strings|check_function_bodies|xmloption|client_min_messages|row_security|default_tablespace|default_table_access_method|FOREIGN_KEY_CHECKS|SQL_MODE|TIME_ZONE|UNIQUE_CHECKS|AUTOCOMMIT)[^;\r\n]*|LOCK\s+TABLES\s+[^;\r\n]+|UNLOCK\s+TABLES)\s*;\s*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


@app.post("/api/databases/upload", tags=["Database Hub"])
def upload_database_file(payload: DatabaseUploadPayload) -> dict[str, Any]:
    """Uploads a .sqlite/.db/.sql file or converts a .csv/.tsv/.json/.jsonl file into a connected SQLite database."""
    _load_custom_databases()
    filename = (payload.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    try:
        raw_bytes = base64.b64decode(payload.content_base64, validate=False)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid base64 file content: {exc}"
        ) from exc

    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw_bytes) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=400, detail="Uploaded file exceeds 50 MB limit."
        )

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem
    ext = Path(filename).suffix.lower()
    display_name = (
        (payload.name or "").strip()
        or stem.replace("_", " ").replace("-", " ").title()
        or filename
    )
    db_id = _slugify_db_id(display_name, set(_CUSTOM_DATABASES.keys()))
    target_sqlite_path = _UPLOAD_DIR / f"{db_id}.sqlite"

    safe_table_name = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_") or "uploaded_data"
    if safe_table_name[0].isdigit():
        safe_table_name = f"t_{safe_table_name}"

    if ext in (".sqlite", ".sqlite3", ".db") or raw_bytes.startswith(
        b"SQLite format 3\x00"
    ):
        if not raw_bytes.startswith(b"SQLite format 3\x00"):
            raise HTTPException(
                status_code=400,
                detail=f"File '{filename}' does not have a valid SQLite 3 header.",
            )
        target_sqlite_path.write_bytes(raw_bytes)
    elif ext in (".csv", ".tsv"):
        delimiter = "\t" if ext == ".tsv" else ","
        label = "TSV" if ext == ".tsv" else "CSV"
        try:
            text_content = raw_bytes.decode("utf-8-sig")
            reader = [
                row
                for row in csv.reader(io.StringIO(text_content), delimiter=delimiter)
                if any(cell.strip() for cell in row)
            ]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to parse {label} file: {exc}"
            ) from exc
        if not reader or not reader[0]:
            raise HTTPException(
                status_code=400, detail=f"{label} file contains no rows."
            )
        raw_headers = reader[0]
        data_rows = reader[1:]
        headers: list[str] = []
        seen_cols: set[str] = set()
        for idx, h in enumerate(raw_headers):
            clean_h = (
                re.sub(r"[^A-Za-z0-9_]", "_", h.strip()).strip("_") or f"col_{idx + 1}"
            )
            if clean_h[0].isdigit():
                clean_h = f"c_{clean_h}"
            base_h = clean_h
            c_idx = 2
            while clean_h.lower() in seen_cols:
                clean_h = f"{base_h}_{c_idx}"
                c_idx += 1
            seen_cols.add(clean_h.lower())
            headers.append(clean_h)

        col_types = [
            _infer_sqlite_col_type([r[i] if i < len(r) else None for r in data_rows])
            for i in range(len(headers))
        ]
        col_defs_list = []
        for i, (h, t) in enumerate(zip(headers, col_types, strict=False)):
            if h.lower() == "id" and t == "INTEGER" and data_rows:
                raw_vals = [
                    _coerce_uploaded_cell(row[i] if i < len(row) else None, t)
                    for row in data_rows
                ]
                if all(
                    isinstance(v, int) and not isinstance(v, bool) for v in raw_vals
                ) and len(set(raw_vals)) == len(raw_vals):
                    col_defs_list.append(f'"{h}" INTEGER PRIMARY KEY')
                    continue
            col_defs_list.append(f'"{h}" {t}')

        if target_sqlite_path.exists():
            target_sqlite_path.unlink()
        try:
            with contextlib.closing(sqlite3.connect(str(target_sqlite_path))) as sconn:
                col_defs = ", ".join(col_defs_list)
                sconn.execute(f'CREATE TABLE "{safe_table_name}" ({col_defs});')
                if data_rows:
                    placeholders = ", ".join("?" for _ in headers)
                    coerced_rows = [
                        tuple(
                            _coerce_uploaded_cell(
                                row[i] if i < len(row) else None, col_types[i]
                            )
                            for i in range(len(headers))
                        )
                        for row in data_rows
                    ]
                    sconn.executemany(
                        f'INSERT INTO "{safe_table_name}" VALUES ({placeholders});',
                        coerced_rows,
                    )
                sconn.commit()
        except Exception:
            if target_sqlite_path.exists():
                target_sqlite_path.unlink()
            raise
    elif ext in (".jsonl", ".ndjson"):
        try:
            lines = [
                ln.strip()
                for ln in raw_bytes.decode("utf-8-sig").splitlines()
                if ln.strip()
            ]
            parsed_rows = [json.loads(ln) for ln in lines]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to parse JSONL file: {exc}"
            ) from exc
        if not parsed_rows or not isinstance(parsed_rows[0], dict):
            raise HTTPException(
                status_code=400,
                detail="JSONL file must contain at least one JSON object line.",
            )
        if target_sqlite_path.exists():
            target_sqlite_path.unlink()
        try:
            with contextlib.closing(sqlite3.connect(str(target_sqlite_path))) as sconn:
                _write_dict_rows_to_sqlite_table(sconn, safe_table_name, parsed_rows)
                sconn.commit()
        except Exception:
            if target_sqlite_path.exists():
                target_sqlite_path.unlink()
            raise
    elif ext == ".json":
        try:
            parsed_json = json.loads(raw_bytes.decode("utf-8-sig"))
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to parse JSON file: {exc}"
            ) from exc

        multi_tables: dict[str, list[dict[str, Any]]] = {}
        if isinstance(parsed_json, dict):
            table_candidates = [
                (k, v)
                for k, v in parsed_json.items()
                if isinstance(v, list) and v and isinstance(v[0], dict)
            ]
            # Treat as single-table wrapper ({ "rows": [...], "total": 10 }) only when
            # there is a single list-of-dicts entry under a standard wrapper key.
            if len(table_candidates) == 1 and table_candidates[0][0] in (
                "rows",
                "data",
                "items",
                "records",
            ):
                parsed_json = table_candidates[0][1]
            else:
                seen_tables_lower: set[str] = set()
                for k, v in table_candidates:
                    tbl = (
                        re.sub(r"[^A-Za-z0-9_]", "_", str(k).strip()).strip("_")
                        or "table"
                    )
                    if tbl[0].isdigit():
                        tbl = f"t_{tbl}"
                    base_tbl = tbl
                    t_idx = 2
                    while tbl.lower() in seen_tables_lower:
                        tbl = f"{base_tbl}_{t_idx}"
                        t_idx += 1
                    seen_tables_lower.add(tbl.lower())
                    multi_tables[tbl] = v

        if multi_tables:
            if target_sqlite_path.exists():
                target_sqlite_path.unlink()
            try:
                with contextlib.closing(
                    sqlite3.connect(str(target_sqlite_path))
                ) as sconn:
                    for tbl_name, rows_list in multi_tables.items():
                        _write_dict_rows_to_sqlite_table(sconn, tbl_name, rows_list)
                    sconn.commit()
            except Exception:
                if target_sqlite_path.exists():
                    target_sqlite_path.unlink()
                raise
            safe_table_name = next(iter(multi_tables.keys()))
        else:
            if (
                not isinstance(parsed_json, list)
                or not parsed_json
                or not isinstance(parsed_json[0], dict)
            ):
                raise HTTPException(
                    status_code=400,
                    detail="JSON file must contain a non-empty array of row objects or a dictionary of table arrays.",
                )
            if target_sqlite_path.exists():
                target_sqlite_path.unlink()
            try:
                with contextlib.closing(
                    sqlite3.connect(str(target_sqlite_path))
                ) as sconn:
                    _write_dict_rows_to_sqlite_table(
                        sconn, safe_table_name, parsed_json
                    )
                    sconn.commit()
            except Exception:
                if target_sqlite_path.exists():
                    target_sqlite_path.unlink()
                raise
    elif ext == ".sql":
        try:
            sql_script = raw_bytes.decode("utf-8-sig")
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to decode SQL file: {exc}"
            ) from exc
        prepared_sql = _prepare_sql_dump_for_sqlite(sql_script)
        if target_sqlite_path.exists():
            target_sqlite_path.unlink()
        try:
            with contextlib.closing(sqlite3.connect(str(target_sqlite_path))) as sconn:
                sconn.set_authorizer(_sqlite_dump_authorizer)
                try:
                    sconn.executescript(prepared_sql)
                finally:
                    sconn.set_authorizer(None)
                created_tables = _rank_non_system_tables(
                    [
                        r[0]
                        for r in sconn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        ).fetchall()
                    ]
                )
                sconn.commit()
        except Exception as exc:
            if target_sqlite_path.exists():
                target_sqlite_path.unlink()
            err_msg = str(exc)
            if "not authorized" in err_msg.lower():
                raise HTTPException(
                    status_code=400,
                    detail="SQL script contains restricted statements (ATTACH, DETACH, PRAGMA, or LOAD_EXTENSION).",
                ) from exc
            raise HTTPException(
                status_code=400, detail=f"Failed to execute SQL script: {exc}"
            ) from exc
        if not created_tables:
            if target_sqlite_path.exists():
                target_sqlite_path.unlink()
            raise HTTPException(
                status_code=400,
                detail="SQL script did not create any tables.",
            )
        safe_table_name = created_tables[0]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Supported formats: .sqlite, .db, .sqlite3, .sql, .csv, .tsv, .json, .jsonl, .ndjson",
        )

    entry = DatabaseEntry(
        id=db_id,
        name=display_name,
        group="🔌 Custom Connections",
        dialect="sqlite",
        description=f"Uploaded file ({filename})",
        icon="📁",
        default_table=safe_table_name,
        sqlite_path=target_sqlite_path,
        schema_name="main",
        is_custom=True,
    )
    conn = _instantiate_connector_for_entry(entry)
    try:
        schema = conn.introspect_schema()
        tables = _rank_non_system_tables(list((schema.get("tables") or {}).keys()))
        entry.default_table = tables[0] if tables else safe_table_name
        _CUSTOM_DATABASES[entry.id] = entry
        _save_custom_databases()
        _SCHEMA_CACHE[entry.id] = (time.monotonic(), schema)
        _SCHEMA_CACHE.pop("federated_hub", None)
        return {
            "ok": True,
            "database": _serialize_database_entry(entry),
            "schema": schema,
        }
    finally:
        with contextlib.suppress(Exception):
            conn.close()


@app.delete("/api/databases/{db_id}", tags=["Database Hub"])
def disconnect_database(db_id: str) -> dict[str, Any]:
    """Removes a custom user-connected database from the registry."""
    _load_custom_databases()
    if db_id in get_builtin_database_ids():
        raise HTTPException(
            status_code=400,
            detail=f"Built-in database '{db_id}' cannot be removed.",
        )
    entry = _CUSTOM_DATABASES.pop(db_id, None)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"Custom database '{db_id}' not found."
        )

    _save_custom_databases()
    _SCHEMA_CACHE.pop(db_id, None)
    _SCHEMA_CACHE.pop("federated_hub", None)

    if (
        entry.sqlite_path
        and entry.sqlite_path.parent == _UPLOAD_DIR
        and entry.sqlite_path.is_file()
    ):
        with contextlib.suppress(OSError):
            entry.sqlite_path.unlink()

    return {"ok": True, "deleted_id": db_id}


@app.post("/api/databases/{db_id}/refresh", tags=["Database Hub"])
def refresh_database_schema(db_id: str) -> dict[str, Any]:
    """Clears the cached schema for a specific database and re-introspects it."""
    registry = get_database_registry()
    if db_id not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown database '{db_id}'")
    _SCHEMA_CACHE.pop(db_id, None)
    conn = get_connector_for_db(db_id)
    try:
        schema = conn.introspect_schema()
        return {
            "id": db_id,
            "table_count": len(schema.get("tables", {})),
            "foreign_key_count": len(schema.get("foreign_keys", [])),
            "schema": schema,
        }
    finally:
        conn.close()


@app.get("/api/columns/distinct", tags=["Database Hub"])
def get_distinct_column_values(
    db: str = Query(default="starter_demo"),
    table: str = Query(...),
    column: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Returns up to `limit` distinct non-null values for a specific table and column."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table) or not re.match(
        r"^[A-Za-z_][A-Za-z0-9_]*$", column
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid table or column identifier.",
        )
    registry = get_database_registry()
    if db not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown database '{db}'")
    conn = get_connector_for_db(db)
    try:
        res = conn.execute(
            {
                "table": table,
                "columns": [column],
                "distinct": True,
                "filters": [{"column": column, "operator": "IS NOT NULL"}],
                "limit": limit,
            }
        )
        rows = res.get("rows", []) if isinstance(res, dict) else []
        values: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                val = row.get(column)
                if val is None and row:
                    val = next(iter(row.values()))
                if val is not None:
                    s = str(val).strip()
                    if s and s not in values:
                        values.append(s)
        return {
            "db": db,
            "table": table,
            "column": column,
            "values": values,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch distinct values: {exc}",
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            conn.close()


# Turnkey Query-Builder APIRouter mounted at /api
from query_builder.nlq.service import NlqService


def _resolve_gemini_api_key() -> str | None:
    """Resolves GEMINI_API_KEY or GOOGLE_API_KEY from environment variables."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


class _DynamicNlqService(NlqService):
    """NlqService that automatically uses Gemini with the configured API key when available."""

    def __init__(self) -> None:
        super().__init__(
            default_provider="gemini" if _resolve_gemini_api_key() else "mock"
        )

    @property  # type: ignore[override]
    def default_provider(self) -> str:
        return "gemini" if _resolve_gemini_api_key() else "mock"

    @default_provider.setter
    def default_provider(self, value: str) -> None:
        self._default_provider = value

    def translate(self, request: Any) -> Any:
        key = _resolve_gemini_api_key()
        if isinstance(request, dict) and key and not request.get("api_key"):
            req_copy = dict(request)
            req_copy["api_key"] = key
            if not req_copy.get("provider"):
                req_copy["provider"] = "gemini"
            return super().translate(req_copy)
        return super().translate(request)

    def explain(
        self,
        query: Any,
        dialect: str = "postgres",
        provider: str = "mock",
        api_key: str | None = None,
        model: str | None = None,
        **options: Any,
    ) -> Any:
        key = api_key or _resolve_gemini_api_key()
        eff_provider = provider if provider != "mock" or not key else "gemini"
        return super().explain(
            query,
            dialect=dialect,
            provider=eff_provider,
            api_key=key,
            model=model,
            **options,
        )

    def list_available_providers(self) -> list[dict[str, Any]]:
        providers = super().list_available_providers()
        if _resolve_gemini_api_key():
            for p in providers:
                if p.get("name") == "gemini":
                    p["configured"] = True
        return providers


nlq_service = _DynamicNlqService()

router = create_query_builder_router(
    connector=connector,
    prefix="/api",
    nlq_service=nlq_service,
)
app.include_router(router)


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Returns server health status, available dialects, and active security profile."""
    config = get_query_builder_config()
    registry = get_database_registry()
    gemini_ready = bool(_resolve_gemini_api_key())
    return {
        "status": "healthy",
        "service": "query-builder-fullstack-starter",
        "dialects": list_dialects(),
        "security_profile": "development",
        "read_only_enforced": config.security.execution.enforce_read_only_session,
        "database": str(db_path),
        "registered_databases": len(registry),
        "gemini_configured": gemini_ready,
        "nlq_default_provider": "gemini" if gemini_ready else "mock",
    }


# Serve compiled React SPA from ../frontend/dist when built
frontend_dist = starter_root / "frontend" / "dist"
if frontend_dist.is_dir():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend_assets",
        )

    @app.get("/", include_in_schema=False)
    async def serve_spa_index() -> FileResponse:
        return FileResponse(str(frontend_dist / "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port, reload=True)
