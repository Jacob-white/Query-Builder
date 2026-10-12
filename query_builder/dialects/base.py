"""Dialect base class, identifier/alias validation and shared constants."""

from __future__ import annotations

import re
from typing import Any

from query_builder.exceptions import DialectError

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
MAX_IDENTIFIER_LENGTH = 128
MAX_ALIAS_LENGTH = 256


def _validate_identifier(ident: str) -> None:
    if not isinstance(ident, str) or not IDENTIFIER_REGEX.match(ident):
        raise DialectError(f"Invalid identifier name: '{ident}'")
    parts = ident.split(".")
    if any(len(part) > MAX_IDENTIFIER_LENGTH for part in parts):
        raise DialectError(
            f"Identifier part exceeds maximum allowed length ({MAX_IDENTIFIER_LENGTH}): '{ident}'"
        )


def _validate_alias(alias_name: str) -> None:
    if not isinstance(alias_name, str):
        raise DialectError(f"Alias must be a string, got {type(alias_name).__name__}")
    if len(alias_name) > MAX_ALIAS_LENGTH:
        raise DialectError(
            f"Alias length ({len(alias_name)}) exceeds maximum limit of {MAX_ALIAS_LENGTH} characters."
        )
    if "\x00" in alias_name or any(
        ord(c) < 32 and c not in ("\t", "\n", "\r") for c in alias_name
    ):
        raise DialectError(
            f"Alias contains forbidden control characters: '{alias_name}'"
        )


class BaseDialect:
    """Base SQL dialect adhering to ANSI-SQL standards with parameter binding."""

    name: str = "base"
    placeholder: str = "%s"
    pagination_placement: str = "suffix"
    requires_order_by_for_pagination: bool = False
    supports_cte: bool = True
    supports_recursive_cte: bool = True
    supports_materialized_cte: bool = False
    supports_window_functions: bool = True
    supports_window_groups_frame: bool = False
    #: True when ``SELECT DISTINCT`` rejects an ORDER BY expression that is not textually a
    #: select-list item (RisingWave): the compiler then orders by the select alias instead
    distinct_order_by_alias: bool = False
    #: True when an aggregate window with ``PARTITION BY`` and no ORDER BY / frame silently
    #: drops the rows whose partition key is NULL (RisingWave): the compiler then adds an
    #: equivalent ``ORDER BY <partition key> ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED
    #: FOLLOWING``, which the engine evaluates correctly
    window_partition_null_rows_dropped: bool = False
    #: False when the engine cannot resolve ``alias.column`` references or ``FROM t alias``
    #: (MongoDB via pymongosql, which silently returns no rows): the compiler then emits bare
    #: column names and an un-aliased FROM, and refuses joins, which need aliases
    supports_table_aliases: bool = True
    #: True when a dotted column name is ONE column, not ``table.column`` (Bigtable's
    #: ``family.qualifier``): the compiler then keeps the whole name as the column
    dotted_column_names: bool = False
    # LIKE wildcard handling for the contains/starts_with/ends_with operators.
    # ``None`` (default): the bound value is passed through unchanged, so a user
    # value containing ``%`` or ``_`` acts as a wildcard. Dialects verified live
    # set the escape character (and whether it must be declared with ESCAPE).
    avg_template: str = "AVG({})"
    count_distinct_template: str = "COUNT(DISTINCT {})"
    #: keyword between a derived table's ")" and its alias; Oracle rejects ``AS`` there
    subquery_alias_keyword: str = "AS "
    neq_operator: str = "!="  # Drill rejects "!=" ("Bang equal is not allowed")
    like_escape_char: str | None = None
    like_escape_clause: bool = False
    like_special_chars: str = "%_"
    #: case-insensitive match template; ``{col}`` is the column reference and
    #: ``{ph}`` the bind placeholder (see ``format_ilike``)
    ilike_template: str = "{col} ILIKE {ph}"
    #: True for engines that number positional bind parameters of the main query BEFORE those
    #: inside a ``WITH`` clause (CrateDB), so the compiler appends the CTE params instead
    cte_params_after_main: bool = False
    #: False for engines with no primary/foreign key catalog: the key
    #: introspection queries then return ``("", [])``
    introspects_keys: bool = True

    def escape_like(self, value: Any) -> str:
        """Escape LIKE wildcards in a literal substring (no-op if unsupported)."""
        text = str(value)
        esc = self.like_escape_char
        if not esc:
            return text
        for ch in (esc, *self.like_special_chars):
            text = text.replace(ch, esc + ch)
        return text

    def substring_param(self, mode: str, value: Any) -> str:
        """Bound value for contains ("contains") / starts_with ("starts") / ends_with ("ends")."""
        escaped = self.escape_like(value)
        if mode == "contains":
            return f"%{escaped}%"
        return f"{escaped}%" if mode == "starts" else f"%{escaped}"

    def format_substring_match(self, col_ref: str) -> str:
        """Case-insensitive LIKE used by contains/starts_with/ends_with."""
        expr = self.format_ilike(col_ref)
        if self.like_escape_clause and self.like_escape_char:
            expr = f"{expr} ESCAPE '{self.like_escape_char}'"
        return expr

    def format_cte_materialized(self, materialized: bool | None) -> str:
        """Returns MATERIALIZED or NOT MATERIALIZED hint if supported, else empty string."""
        if materialized is None or not getattr(
            self, "supports_materialized_cte", False
        ):
            return ""
        return "MATERIALIZED " if materialized else "NOT MATERIALIZED "

    def quote_identifier(self, ident: str) -> str:
        """Quotes a schema, table, or column identifier."""
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f'"{part}"' for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        """Quotes an output projection alias safely."""
        _validate_alias(alias_name)
        cleaned = alias_name.replace('"', '""')
        return f'"{cleaned}"'

    def format_ilike(self, col_ref: str) -> str:
        """Formats a case-insensitive string matching expression."""
        return self.ilike_template.format(col=col_ref, ph=self.placeholder)

    def format_like(self, col_ref: str) -> str:
        """Formats a case-sensitive string matching expression."""
        return f"{col_ref} LIKE {self.placeholder}"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        """Formats LIMIT and OFFSET clause with bind parameters."""
        return f"LIMIT {self.placeholder} OFFSET {self.placeholder}", [limit, offset]

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats vector distance calculation expression for a column reference and placeholder."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"L2_DISTANCE({col_ref}, {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"INNER_PRODUCT({col_ref}, {self.placeholder})"
        return f"COSINE_DISTANCE({col_ref}, {self.placeholder})"

    def format_vector_param(self, vector: list[float]) -> Any:
        """Formats a vector list for driver query parameter binding."""
        return str(vector)

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats a basic text matching score expression."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        cases = [
            f"(CASE WHEN {col} LIKE {ph} THEN 1.0 ELSE 0.0 END)" for col in col_refs
        ]
        return f"({' + '.join(cases)})"

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect tables for this dialect."""
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} AND table_type = 'BASE TABLE' ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect columns for this dialect."""
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect primary keys for this dialect."""
        if not self.introspects_keys:
            return "", []
        if table_name:
            return (
                f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Returns the SQL query and parameters to introspect foreign keys for this dialect."""
        if not self.introspects_keys:
            return "", []
        if table_name:
            return (
                f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints AS tc JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name],
        )

    def inspect_tables(self, schema_name: str = "public") -> tuple[str, list[Any]]:
        """Convenience alias for inspect_tables_query."""
        return self.inspect_tables_query(schema_name)

    def inspect_columns(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Convenience alias for inspect_columns_query."""
        return self.inspect_columns_query(schema_name, table_name)

    def inspect_primary_keys(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Convenience alias for inspect_primary_keys_query."""
        return self.inspect_primary_keys_query(schema_name, table_name)

    def inspect_foreign_keys(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        """Convenience alias for inspect_foreign_keys_query."""
        return self.inspect_foreign_keys_query(schema_name, table_name)
