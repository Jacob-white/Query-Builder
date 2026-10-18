"""
FastAPI Backend Server for Fullstack Starter.
=============================================
Provides turnkey REST endpoints for database schema introspection, query compilation,
AST safety validation, query execution, and tabular export using Query-Builder.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from query_builder import (
    SQLiteConnector,
    configure_query_builder,
    create_query_builder_router,
    get_query_builder_config,
    list_dialects,
    register_filter_operator,
    reset_query_builder_config,
    reset_security_config,
)

db_path = DEFAULT_DB_PATH


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
    description="Interactive backend demonstrating Query-Builder schema introspection, compilation, and execution.",
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


# A factory gives every request its own SQLite connection. A single shared connection is
# bound to the thread that created it and is not safe to share across concurrent requests.
def connector() -> SQLiteConnector:
    _register_custom_operators()
    return StarterSQLiteConnector(database=str(db_path))


# Turnkey Query-Builder APIRouter mounted at /api
router = create_query_builder_router(
    connector=connector,
    prefix="/api",
)
app.include_router(router)


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Returns server health status, available dialects, and active security profile."""
    config = get_query_builder_config()
    return {
        "status": "healthy",
        "service": "query-builder-fullstack-starter",
        "dialects": list_dialects(),
        "security_profile": "development",
        "read_only_enforced": config.security.execution.enforce_read_only_session,
        "database": str(db_path),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
