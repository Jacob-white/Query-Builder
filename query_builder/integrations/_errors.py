"""Shared error-message policy for the HTTP integrations (FastAPI, Django).

Library errors (compilation, validation, security, disabled features, export) carry messages
written for API clients, so they are returned as-is. Any other exception is unexpected: its
text may expose driver, file-system or infrastructure details, so clients get only the fixed
prefix while the full error is logged server-side.
"""

from __future__ import annotations

import logging

from query_builder.capabilities import DisabledFeatureError
from query_builder.exceptions import QueryBuilderError
from query_builder.export import ExportError

logger = logging.getLogger("query_builder.integrations")

CLIENT_SAFE_ERRORS: tuple[type[BaseException], ...] = (
    QueryBuilderError,
    DisabledFeatureError,
    ExportError,
)


def public_error(prefix: str, exc: BaseException) -> str:
    """Returns the message a client may see for ``exc``, logging unexpected errors."""
    if isinstance(exc, CLIENT_SAFE_ERRORS):
        return f"{prefix}: {exc}"
    logger.error("%s (unexpected %s)", prefix, type(exc).__name__, exc_info=exc)
    return prefix
