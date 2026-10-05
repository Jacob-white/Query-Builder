"""
Domain Exception Hierarchy for Query-Builder.
=============================================
Provides a structured domain exception hierarchy for compilation, validation,
dialect formatting, and security policy enforcement.
"""

from __future__ import annotations


class QueryBuilderError(Exception):
    """Base exception for all Query-Builder domain errors."""


class CompilationError(QueryBuilderError):
    """Raised when query specification is invalid or violates compilation rules."""


class ValidationError(CompilationError):
    """Raised when query specification schema, type, or parameter validation fails."""


class SecurityError(CompilationError):
    """Raised when a query violates security policies, AST safety, or access rules."""


class DialectError(QueryBuilderError):
    """Raised when identifier, alias, or dialect formatting encounters an invalid pattern."""


__all__ = [
    "CompilationError",
    "DialectError",
    "QueryBuilderError",
    "SecurityError",
    "ValidationError",
]
