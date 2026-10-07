"""
Turnkey Web Framework Integrations for Query-Builder.
=====================================================
Exports integration helpers for:
- FastAPI: `create_query_builder_router`
- Django : `create_django_urls`, `create_drf_views`, `create_ninja_router`
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

__all__ = [
    "CompileRequest",
    "ExecuteRequest",
    "ExportRequest",
    "ValidateRequest",
    "create_django_urls",
    "create_drf_views",
    "create_ninja_router",
    "create_query_builder_router",
]
