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
    init_database,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from query_builder import (
    SQLiteConnector,
    configure_query_builder,
    create_query_builder_router,
    get_query_builder_config,
    list_dialects,
    reset_query_builder_config,
    reset_security_config,
)

db_path = DEFAULT_DB_PATH


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

# Turnkey Query-Builder APIRouter mounted at /api
connector = SQLiteConnector(database=str(db_path))
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
