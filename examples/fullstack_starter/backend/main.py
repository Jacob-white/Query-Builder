"""
FastAPI Backend Server for Fullstack Starter.
=============================================
Provides REST endpoints for database schema introspection, query compilation,
AST safety validation, and query execution against SQLite using Query-Builder.
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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from query_builder import (
    CompilationError,
    QueryCompiler,
    QueryExecutionError,
    SecurityError,
    SQLiteConnector,
    ValidationError,
    configure_query_builder,
    get_query_builder_config,
    list_dialects,
    reset_query_builder_config,
    reset_security_config,
    validate_sql_ast,
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


class CompileRequest(BaseModel):
    spec: dict[str, Any] = Field(
        ..., description="Declarative JSON query specification"
    )
    dialect: str = Field(default="sqlite", description="Target SQL dialect name")


class ExecuteRequest(BaseModel):
    spec: dict[str, Any] | None = Field(
        default=None, description="Declarative JSON query specification"
    )
    sql: str | None = Field(default=None, description="Optional raw SQL query string")
    params: list[Any] | None = Field(
        default=None, description="Optional positional bind parameters"
    )


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


@app.get("/api/schema")
def get_schema() -> dict[str, Any]:
    """Returns the complete relational schema snapshot for visual query building."""
    snapshot = get_starter_schema_snapshot()
    return snapshot_to_dict(snapshot)


@app.post("/api/compile")
def compile_query(request: CompileRequest) -> dict[str, Any]:
    """Compiles a declarative JSON query specification into parameterized SQL."""
    snapshot = get_starter_schema_snapshot()
    try:
        compiler = QueryCompiler(
            spec=request.spec,
            schema=snapshot,
            dialect=request.dialect,
        )
        main_sql, params, count_sql, count_params = compiler.compile()
        return {
            "sql": main_sql,
            "params": params,
            "count_sql": count_sql,
            "count_params": count_params,
        }
    except (CompilationError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Internal compilation error: {exc}"
        ) from exc


@app.post("/api/execute")
def execute_query(request: ExecuteRequest) -> dict[str, Any]:
    """
    Executes a query specification or raw SQL query with AST safety verification
    against the SQLite database.
    """
    # 1. If raw SQL is passed, enforce AST read-only validation
    if request.sql:
        ast_result = validate_sql_ast(request.sql)
        if not ast_result.get("valid") or not ast_result.get("is_read_only"):
            errors = ast_result.get("errors", ["Query failed AST safety validation."])
            raise HTTPException(
                status_code=403,
                detail=f"Security violation: {'; '.join(errors)}",
            )

    # 2. Execute via SQLiteConnector
    snapshot = get_starter_schema_snapshot()
    connector = SQLiteConnector(database=str(db_path))

    try:
        result = connector.execute(
            spec=request.spec,
            sql=request.sql,
            params=request.params,
            schema=snapshot,
        )
        return {
            "columns": result.get("columns", []),
            "rows": result.get("rows", []),
            "count": result.get("count", 0),
            "latency_ms": result.get("latency_ms", 0.0),
            "dialect": result.get("dialect", "sqlite"),
            "limit": result.get("limit"),
            "offset": result.get("offset"),
        }
    except SecurityError as exc:
        raise HTTPException(
            status_code=403, detail=f"Security violation: {exc}"
        ) from exc
    except (CompilationError, ValidationError, QueryExecutionError) as exc:
        raise HTTPException(status_code=400, detail=f"Execution error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Internal execution error: {exc}"
        ) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
