"""
FastAPI Backend Server for Query-Builder Studio & Home Server Multi-Database Hub.
=================================================================================
Provides turnkey REST endpoints for multi-database schema introspection, query
compilation, AST safety validation, read-only query execution, and tabular export
across all PostgreSQL and SQLite databases on the home server.
"""

from __future__ import annotations

import contextlib
import contextvars
import decimal
import json
import os
import re
import sys
import time
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
    get_starter_schema_snapshot,
    init_database,
    snapshot_to_dict,
)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from query_builder import (
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


def _load_dotenv_file(filepath: Path) -> dict[str, str]:
    """Parses a simple KEY=VALUE .env file without external dependencies."""
    values: dict[str, str] = {}
    if not filepath.is_file():
        return values
    try:
        for raw_line in filepath.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            values[key] = val
    except OSError:
        pass
    return values


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

    Many SQLite applications (Plex, Sonarr, Radarr, Prowlarr, Nginx Proxy Manager)
    omit explicit FOREIGN KEY constraints in DDL while following strict naming
    conventions (`<table_singular>_id` or `<TableSingular>Id`).
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
        if not pk_col and tname == "firm_master":
            pk_col = "crd_number"
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
            if (
                cname == "crd_number"
                and tname != "firm_master"
                and "firm_master" in tables
            ):
                target = ("firm_master", "crd_number")
            elif cname.lower().endswith("_id") and len(cname) > 3:
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
    schema_name: str = "public"
    is_starter: bool = False


def get_database_registry() -> dict[str, DatabaseEntry]:
    """Builds the registry of all 17 databases available on the home server."""
    myserver_root = Path(os.environ.get("MYSERVER_ROOT", "/home/jwhite/myserver"))
    firm_root = Path(
        os.environ.get("FIRM_PLATFORM_ROOT", "/home/jwhite/Firm_Association_Platform")
    )

    myserver_env = _load_dotenv_file(myserver_root / ".env")
    firm_env = _load_dotenv_file(firm_root / ".env")

    hh_host = os.environ.get("HH_PG_HOST", "127.0.0.1")
    hh_port = int(os.environ.get("HH_PG_PORT", "5432"))
    hh_user = os.environ.get(
        "HH_PG_USER", myserver_env.get("POSTGRES_USER", "caretaker")
    )
    hh_password = os.environ.get(
        "HH_PG_PASSWORD", myserver_env.get("POSTGRES_PASSWORD", "")
    )
    hh_dbname = os.environ.get(
        "HH_PG_DB", myserver_env.get("POSTGRES_DB", "caretaker_db")
    )

    fn_host = os.environ.get("FN_PG_HOST", "127.0.0.1")
    fn_port = int(os.environ.get("FN_PG_PORT", "5434"))
    fn_user = os.environ.get("FN_PG_USER", firm_env.get("POSTGRES_USER", "daas_user"))
    fn_password = os.environ.get(
        "FN_PG_PASSWORD",
        myserver_env.get("FN_POSTGRES_PASSWORD", firm_env.get("POSTGRES_PASSWORD", "")),
    )
    fn_dbname = os.environ.get(
        "FN_PG_DB", firm_env.get("POSTGRES_DB", "firm_association")
    )

    plex_db_dir = (
        myserver_root
        / "plex_config/Library/Application Support/Plex Media Server/Plug-in Support/Databases"
    )

    entries = [
        DatabaseEntry(
            id="federated_hub",
            name="Federated Cross-Database Hub (Join Across All DBs)",
            group="🌐 Cross-Database Federation",
            dialect="sqlite",
            description="Unified federated query engine: join tables across PostgreSQL (HobbyHabbit, Firm Network, Synfinii) and SQLite (Plex, Sonarr, Radarr, Jellyseerr, Prowlarr, NPM) in a single query.",
            icon="🌐",
            default_table="jellyseerr__media",
        ),
        DatabaseEntry(
            id="hobbyhabbit",
            name="HobbyHabbit Production (caretaker_db)",
            group="PostgreSQL 18 — Applications",
            dialect="postgres",
            description="Core HobbyHabbit social platform: hobbies, shires, posts, comments, quests, milestones, and user activity.",
            icon="🏰",
            default_table="hobbies",
            schema_name="public",
            pg_config={
                "host": hh_host,
                "port": hh_port,
                "dbname": hh_dbname,
                "user": hh_user,
                "password": hh_password,
                "connect_timeout": 5,
            },
        ),
        DatabaseEntry(
            id="firm_production",
            name="Firm Network — Production Schema",
            group="PostgreSQL 18 — Firm Network",
            dialect="postgres",
            description="Institutional wealth management intelligence: 131 tables covering RIAs, broker-dealers, AUM, custodians, SMAs, and M&A.",
            icon="🏛️",
            default_table="firm_master",
            schema_name="production",
            pg_config={
                "host": fn_host,
                "port": fn_port,
                "dbname": fn_dbname,
                "user": fn_user,
                "password": fn_password,
                "options": "-c search_path=production,public",
                "connect_timeout": 5,
            },
        ),
        DatabaseEntry(
            id="firm_staging",
            name="Firm Network — Staging Schema",
            group="PostgreSQL 18 — Firm Network",
            dialect="postgres",
            description="SEC Form ADV, 13F, Form 5500 & data pipeline staging tables (41 tables).",
            icon="📥",
            default_table="sec_raw_firms",
            schema_name="staging",
            pg_config={
                "host": fn_host,
                "port": fn_port,
                "dbname": fn_dbname,
                "user": fn_user,
                "password": fn_password,
                "options": "-c search_path=staging,public",
                "connect_timeout": 5,
            },
        ),
        DatabaseEntry(
            id="firm_history",
            name="Firm Network — History Schema",
            group="PostgreSQL 18 — Firm Network",
            dialect="postgres",
            description="Historical time-series snapshots of advisory teams, contacts, funds, and pipeline runs (~968k rows).",
            icon="📈",
            default_table="advisory_team_history",
            schema_name="history",
            pg_config={
                "host": fn_host,
                "port": fn_port,
                "dbname": fn_dbname,
                "user": fn_user,
                "password": fn_password,
                "options": "-c search_path=history,public",
                "connect_timeout": 5,
            },
        ),
        DatabaseEntry(
            id="firm_public",
            name="Firm Network — Airflow & App Schema",
            group="PostgreSQL 18 — Firm Network",
            dialect="postgres",
            description="Airflow DAG runs, task instances, pipeline schedules, and Django application tables.",
            icon="⚙️",
            default_table="dag",
            schema_name="public",
            pg_config={
                "host": fn_host,
                "port": fn_port,
                "dbname": fn_dbname,
                "user": fn_user,
                "password": fn_password,
                "options": "-c search_path=public",
                "connect_timeout": 5,
            },
        ),
        DatabaseEntry(
            id="synfinii_lab",
            name="Synfinii Lab (Distribution Sales)",
            group="PostgreSQL 18 — Applications",
            dialect="postgres",
            description="Financial product distribution sales analytics across regions and channels.",
            icon="💹",
            default_table="distribution_sales",
            schema_name="public",
            pg_config={
                "host": hh_host,
                "port": hh_port,
                "dbname": "synfinii_lab",
                "user": hh_user,
                "password": hh_password,
                "connect_timeout": 5,
            },
        ),
        DatabaseEntry(
            id="plex_library",
            name="Plex Media Server — Library DB",
            group="SQLite — Media Stack",
            dialect="sqlite",
            description="Complete Plex catalog: metadata_items, media_items, media_parts, library_sections, playbacks, and accounts.",
            icon="🎬",
            default_table="metadata_items",
            sqlite_path=plex_db_dir / "com.plexapp.plugins.library.db",
        ),
        DatabaseEntry(
            id="sonarr",
            name="Sonarr — TV Series & Episodes DB",
            group="SQLite — Media Stack",
            dialect="sqlite",
            description="TV series library, episodes, episode files, quality profiles, indexers, and download history.",
            icon="📺",
            default_table="Series",
            sqlite_path=myserver_root / "sonarr_config/sonarr.db",
        ),
        DatabaseEntry(
            id="radarr",
            name="Radarr — Movies Collection DB",
            group="SQLite — Media Stack",
            dialect="sqlite",
            description="Movie collection, metadata, movie files, quality profiles, custom formats, and download history.",
            icon="🍿",
            default_table="Movies",
            sqlite_path=myserver_root / "radarr_config/radarr.db",
        ),
        DatabaseEntry(
            id="prowlarr",
            name="Prowlarr — Indexer Manager DB",
            group="SQLite — Media Stack",
            dialect="sqlite",
            description="Configured torrent/usenet indexers, indexer status, synced applications, and search history.",
            icon="🔍",
            default_table="Indexers",
            sqlite_path=myserver_root / "prowlarr_config/prowlarr.db",
        ),
        DatabaseEntry(
            id="jellyseerr",
            name="Jellyseerr — Media Requests DB",
            group="SQLite — Media Stack",
            dialect="sqlite",
            description="Media requests, users, issues, seasons, and notification settings.",
            icon="🎟️",
            default_table="media",
            sqlite_path=myserver_root / "jellyseerr_config/db/db.sqlite3",
        ),
        DatabaseEntry(
            id="npm",
            name="Nginx Proxy Manager — Proxy DB",
            group="SQLite — Infrastructure",
            dialect="sqlite",
            description="Reverse proxy hosts, Let's Encrypt SSL certificates, access lists, redirection hosts, and audit logs.",
            icon="🌐",
            default_table="proxy_host",
            sqlite_path=myserver_root / "npm_data/database.sqlite",
        ),
        DatabaseEntry(
            id="plex_blobs",
            name="Plex Media Server — Blobs DB",
            group="SQLite — Media Stack",
            dialect="sqlite",
            description="Plex binary artwork, thumbnails, and compressed media blob metadata.",
            icon="🖼️",
            default_table="blobs",
            sqlite_path=plex_db_dir / "com.plexapp.plugins.library.blobs.db",
        ),
        DatabaseEntry(
            id="sonarr_logs",
            name="Sonarr — Event Logs DB",
            group="SQLite — Infrastructure",
            dialect="sqlite",
            description="Sonarr application event and diagnostic logs.",
            icon="📋",
            default_table="Logs",
            sqlite_path=myserver_root / "sonarr_config/logs.db",
        ),
        DatabaseEntry(
            id="radarr_logs",
            name="Radarr — Event Logs DB",
            group="SQLite — Infrastructure",
            dialect="sqlite",
            description="Radarr application event and diagnostic logs.",
            icon="📋",
            default_table="Logs",
            sqlite_path=myserver_root / "radarr_config/logs.db",
        ),
        DatabaseEntry(
            id="prowlarr_logs",
            name="Prowlarr — Event Logs DB",
            group="SQLite — Infrastructure",
            dialect="sqlite",
            description="Prowlarr application event and diagnostic logs.",
            icon="📋",
            default_table="Logs",
            sqlite_path=myserver_root / "prowlarr_config/logs.db",
        ),
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
    ]
    return {e.id: e for e in entries}


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
    init_database(db_path)
    try:
        yield
    finally:
        reset_query_builder_config()
        reset_security_config()


# Create FastAPI app
app = FastAPI(
    title="Query-Builder Fullstack Starter API",
    description="Interactive backend demonstrating Query-Builder schema introspection, compilation, and execution across all home server databases.",
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


class HomeServerSQLiteConnector(SQLiteConnector):
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
        conn = super().connect()
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


class HomeServerPostgresConnector(PostgresConnector):
    """Read-only PostgreSQL connector with FK inference, caching, and binary sanitization."""

    def __init__(self, db_id: str, schema_name: str = "public", **config: Any) -> None:
        super().__init__(schema_name=schema_name, **config)
        self.db_id = db_id

    def connect(self) -> Any:
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
    """Federated cross-database connector joining tables across all 17 PostgreSQL and SQLite databases."""

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
                sub_schema = conn.introspect_schema()
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

        # Curated cross-database foreign key relationships for automatic multi-DB join path solving
        cross_db_links = [
            ("jellyseerr__media", "tmdbId", "radarr__MovieMetadata", "TmdbId"),
            ("jellyseerr__media", "imdbId", "radarr__MovieMetadata", "ImdbId"),
            ("jellyseerr__media", "tvdbId", "sonarr__Series", "TvdbId"),
            ("jellyseerr__media", "imdbId", "sonarr__Series", "ImdbId"),
            ("radarr__MovieMetadata", "Title", "plex_library__metadata_items", "title"),
            ("sonarr__Series", "Title", "plex_library__metadata_items", "title"),
            (
                "firm_staging__sec_raw_firms",
                "raw_crd_number",
                "firm_production__firm_master",
                "crd_number",
            ),
            (
                "firm_staging__firm_master_history",
                "firm_master_id",
                "firm_production__firm_master",
                "firm_master_id",
            ),
            (
                "firm_history__advisory_team_history",
                "firm_id",
                "firm_production__firm_master",
                "firm_master_id",
            ),
        ]
        for src_t, src_c, dst_t, dst_c in cross_db_links:
            if src_t in tables and dst_t in tables:
                foreign_keys.append(
                    {
                        "table": src_t,
                        "column": src_c,
                        "foreign_table": dst_t,
                        "foreign_column": dst_c,
                    }
                )
                relationships.append(
                    {
                        "source_table": src_t,
                        "source_column": src_c,
                        "target_table": dst_t,
                        "target_column": dst_c,
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

    if entry.id == "federated_hub":
        return FederatedCrossDatabaseConnector()

    if entry.is_starter:
        return StarterSQLiteConnector(database=str(db_path))

    if entry.dialect == "postgres" and entry.pg_config is not None:
        return HomeServerPostgresConnector(
            db_id=entry.id,
            schema_name=entry.schema_name,
            **entry.pg_config,
        )

    sqlite_file = entry.sqlite_path or db_path
    return HomeServerSQLiteConnector(
        db_id=entry.id,
        database=str(sqlite_file),
    )


def connector() -> BaseConnector:
    """Factory invoked per-request by create_query_builder_router."""
    return get_connector_for_db(_active_db_id.get())


@app.get("/api/databases", tags=["Database Hub"])
def list_databases(refresh: bool = Query(default=False)) -> dict[str, Any]:
    """Returns all registered home server databases with live status and metadata."""
    if refresh:
        _SCHEMA_CACHE.clear()

    registry = get_database_registry()
    default_db = os.environ.get("QB_DEFAULT_DB", "hobbyhabbit")
    if default_db not in registry:
        default_db = "starter_demo"

    databases_list: list[dict[str, Any]] = []
    for db_id, entry in registry.items():
        available = True
        if (
            entry.dialect == "sqlite"
            and entry.sqlite_path is not None
            and not entry.is_starter
        ):
            available = entry.sqlite_path.is_file()
        elif entry.dialect == "postgres" and entry.pg_config is not None:
            available = bool(entry.pg_config.get("password"))

        cached = _SCHEMA_CACHE.get(db_id)
        table_count: int | None = None
        fk_count: int | None = None
        if cached:
            table_count = len(cached[1].get("tables", {}))
            fk_count = len(cached[1].get("foreign_keys", []))

        databases_list.append(
            {
                "id": entry.id,
                "name": entry.name,
                "group": entry.group,
                "dialect": entry.dialect,
                "schema_name": entry.schema_name,
                "description": entry.description,
                "icon": entry.icon,
                "default_table": entry.default_table,
                "available": available,
                "table_count": table_count,
                "foreign_key_count": fk_count,
            }
        )

    return {
        "default_database": default_db,
        "count": len(databases_list),
        "databases": databases_list,
    }


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


# Turnkey Query-Builder APIRouter mounted at /api
from query_builder.nlq.service import NlqService

_myserver_dotenv = _load_dotenv_file(
    Path(os.environ.get("MYSERVER_ROOT", "/home/jwhite/myserver")) / ".env"
)


def _resolve_gemini_api_key() -> str | None:
    """Resolves GEMINI_API_KEY from environment or myserver .env without mutating global os.environ."""
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or _myserver_dotenv.get("GEMINI_API_KEY")
        or _myserver_dotenv.get("GOOGLE_API_KEY")
    )


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
