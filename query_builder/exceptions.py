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


class SpecColumnError(ValidationError):
    """Raised by ``check_columns`` when a spec names a column that does not exist in a table of the query.

    ``column`` is the reference as written, ``table`` the table it was read against, ``suggestions`` the likeliest real
    columns (best first) and ``available`` every column that table has. The message carries all of that, so it can be
    shown to a person or sent back to a model as it is.
    """

    def __init__(
        self,
        message: str,
        *,
        column: str = "",
        table: str = "",
        suggestions: list[str] | None = None,
        available: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.column = column
        self.table = table
        self.suggestions = list(suggestions or [])
        self.available = list(available or [])


class SecurityError(CompilationError):
    """Raised when a query violates security policies, AST safety, or access rules."""


class DialectError(QueryBuilderError):
    """Raised when identifier, alias, or dialect formatting encounters an invalid pattern."""


__all__ = [
    "CompilationError",
    "DialectError",
    "QueryBuilderError",
    "SecurityError",
    "SpecColumnError",
    "ValidationError",
]
