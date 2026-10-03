"""
Pluggable SQL Dialects for Query Builder Engine.
================================================
Provides quote escaping, parameter placeholder handling, and dialect-specific
SQL syntax generation for PostgreSQL, Snowflake, Microsoft SQL Server, SQLite, and MySQL.
"""

import re

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")


class DialectError(Exception):
    """Raised when identifier or alias formatting encounters an invalid pattern."""


class BaseDialect:
    """Base SQL dialect adhering to ANSI-SQL standards with parameter binding."""

    name: str = "base"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        """Quotes a schema, table, or column identifier."""
        if not IDENTIFIER_REGEX.match(ident):
            raise DialectError(f"Invalid identifier name: '{ident}'")
        parts = ident.split(".")
        return ".".join(f'"{part}"' for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        """Quotes an output projection alias safely."""
        cleaned = alias_name.replace('"', '""')
        return f'"{cleaned}"'

    def format_ilike(self, col_ref: str) -> str:
        """Formats a case-insensitive string matching expression."""
        return f"{col_ref} ILIKE {self.placeholder}"

    def format_like(self, col_ref: str) -> str:
        """Formats a case-sensitive string matching expression."""
        return f"{col_ref} LIKE {self.placeholder}"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        """Formats LIMIT and OFFSET clause with bind parameters."""
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]


class PostgresDialect(BaseDialect):
    """PostgreSQL dialect."""

    name: str = "postgres"


class SnowflakeDialect(BaseDialect):
    """Snowflake dialect."""

    name: str = "snowflake"


class MSSQLDialect(BaseDialect):
    """Microsoft SQL Server dialect using square bracket quoting and FETCH FIRST pagination."""

    name: str = "mssql"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        if not IDENTIFIER_REGEX.match(ident):
            raise DialectError(f"Invalid identifier name: '{ident}'")
        parts = ident.split(".")
        return ".".join(f"[{part}]" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        cleaned = alias_name.replace("]", "]]")
        return f"[{cleaned}]"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )


class SQLiteDialect(BaseDialect):
    """SQLite dialect using double-quote escaping and question mark placeholders."""

    name: str = "sqlite"
    placeholder: str = "?"

    def format_ilike(self, col_ref: str) -> str:
        # SQLite LIKE is case-insensitive by default for ASCII
        return f"{col_ref} LIKE {self.placeholder}"


class MySQLDialect(BaseDialect):
    """MySQL dialect using backtick quoting."""

    name: str = "mysql"
    placeholder: str = "%s"

    def quote_identifier(self, ident: str) -> str:
        if not IDENTIFIER_REGEX.match(ident):
            raise DialectError(f"Invalid identifier name: '{ident}'")
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"

    def format_ilike(self, col_ref: str) -> str:
        return f"LOWER({col_ref}) LIKE LOWER({self.placeholder})"


DIALECTS: dict[str, BaseDialect] = {
    "postgres": PostgresDialect(),
    "postgresql": PostgresDialect(),
    "snowflake": SnowflakeDialect(),
    "mssql": MSSQLDialect(),
    "sqlserver": MSSQLDialect(),
    "sqlite": SQLiteDialect(),
    "mysql": MySQLDialect(),
}


def get_dialect(name: str = "postgres") -> BaseDialect:
    """Returns the dialect instance for the specified name (defaults to postgres)."""
    return DIALECTS.get(name.lower(), DIALECTS["postgres"])


def quote_identifier(ident: str, dialect_name: str = "postgres") -> str:
    """Convenience helper to quote an identifier with the named dialect."""
    return get_dialect(dialect_name).quote_identifier(ident)


def quote_alias(alias_name: str, dialect_name: str = "postgres") -> str:
    """Convenience helper to quote an alias with the named dialect."""
    return get_dialect(dialect_name).quote_alias(alias_name)
