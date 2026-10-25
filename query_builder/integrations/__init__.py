"""
Turnkey Web Framework & ORM Integrations for Query-Builder.
===========================================================
Exports integration helpers for:
- FastAPI   : `create_query_builder_router`
- Django    : `create_django_urls`, `create_drf_views`, `create_ninja_router`
- Flask     : `create_flask_blueprint`
- Litestar  : `create_litestar_router`
- SQLAlchemy: `SQLAlchemyIntegration`, `create_sqlalchemy_integration`, `compile_to_sqlalchemy`
"""

from __future__ import annotations

from query_builder.integrations.django import (
    create_django_urls,
    create_drf_views,
    create_ninja_router,
)
from query_builder.integrations.fastapi import (
    CompileRequest,
    ExecuteRequest,
    ExportRequest,
    ValidateRequest,
    create_query_builder_router,
)
from query_builder.integrations.flask import create_flask_blueprint
from query_builder.integrations.litestar import create_litestar_router
from query_builder.integrations.sqlalchemy import (
    SQLAlchemyIntegration,
    compile_to_sqlalchemy,
    create_sqlalchemy_integration,
)

__all__ = [
    "CompileRequest",
    "ExecuteRequest",
    "ExportRequest",
    "SQLAlchemyIntegration",
    "ValidateRequest",
    "compile_to_sqlalchemy",
    "create_django_urls",
    "create_drf_views",
    "create_flask_blueprint",
    "create_litestar_router",
    "create_ninja_router",
    "create_query_builder_router",
    "create_sqlalchemy_integration",
]
