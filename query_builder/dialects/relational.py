"""Relational / OLTP SQL engines and their wire-compatible forks."""

from __future__ import annotations

from typing import Any

from query_builder.dialects.base import (
    BaseDialect,
    _validate_alias,
    _validate_identifier,
)


class PostgresDialect(BaseDialect):
    """PostgreSQL dialect."""

    name: str = "postgres"
    supports_materialized_cte: bool = True
    supports_window_groups_frame: bool = True
    like_escape_char = "\\"  # PostgreSQL's default LIKE escape

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats pgvector distance operator expression."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"({col_ref} <-> {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"({col_ref} <#> {self.placeholder})"
        return f"({col_ref} <=> {self.placeholder})"

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats PostgreSQL ts_rank_cd full text search ranking score."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        coalesced = " || ' ' || ".join(
            [f"COALESCE({col}::text, '')" for col in col_refs]
        )
        return f"ts_rank_cd(to_tsvector('english', {coalesced}), plainto_tsquery('english', {ph}))"


class SnowflakeDialect(BaseDialect):
    """Snowflake dialect."""

    name: str = "snowflake"
    # '\\' is itself an escape character inside Snowflake string literals, so use a plain
    # character as the LIKE escape and declare it.
    like_escape_char = "!"
    like_escape_clause = True

    def format_vector_distance(self, col_ref: str, metric: str = "cosine") -> str:
        """Formats Snowflake vector similarity expression."""
        m = metric.lower()
        if m in ("euclidean", "l2"):
            return f"VECTOR_L2_DISTANCE({col_ref}, {self.placeholder})"
        elif m in ("dot_product", "inner_product"):
            return f"VECTOR_INNER_PRODUCT({col_ref}, {self.placeholder})"
        return f"VECTOR_COSINE_SIMILARITY({col_ref}, {self.placeholder})"

    def format_text_search(
        self, col_refs: list[str], placeholder: str | None = None
    ) -> str:
        """Formats Snowflake keyword search score expression."""
        ph = placeholder or self.placeholder
        if not col_refs:
            return "1.0"
        cases = [
            f"(CASE WHEN CONTAINS(LOWER({col}), LOWER({ph})) THEN 1.0 ELSE 0.0 END)"
            for col in col_refs
        ]
        return f"({' + '.join(cases)})"


class MSSQLDialect(BaseDialect):
    """Microsoft SQL Server dialect using square bracket quoting and FETCH FIRST pagination."""

    name: str = "mssql"
    placeholder: str = "%s"
    requires_order_by_for_pagination: bool = True
    # AVG over an integer column does integer division in T-SQL (AVG(1,2) = 1).
    avg_template = "AVG(CAST({} AS FLOAT))"
    like_escape_char = "\\"
    like_escape_clause = True
    like_special_chars = "%_["
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"[{part}]" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("]", "]]")
        return f"[{cleaned}]"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )


class SQLiteDialect(BaseDialect):
    """SQLite dialect using double-quote escaping and question mark placeholders."""

    name: str = "sqlite"
    placeholder: str = "?"
    supports_materialized_cte: bool = True
    supports_window_groups_frame: bool = False
    like_escape_char = "\\"
    like_escape_clause = True
    ilike_template: str = "{col} LIKE {ph}"

    def inspect_tables_query(self, schema_name: str = "main") -> tuple[str, list[Any]]:
        return (
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;",
            [],
        )

    def inspect_columns_query(
        self, schema_name: str = "main", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        tbl = table_name or "sqlite_master"
        return f'PRAGMA table_info("{tbl}");', []

    def inspect_primary_keys_query(
        self, schema_name: str = "main", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        tbl = table_name or "sqlite_master"
        return f'PRAGMA table_info("{tbl}");', []

    def inspect_foreign_keys_query(
        self, schema_name: str = "main", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        tbl = table_name or "sqlite_master"
        return f'PRAGMA foreign_key_list("{tbl}");', []


class MySQLDialect(BaseDialect):
    """MySQL dialect using backtick quoting."""

    name: str = "mysql"
    placeholder: str = "%s"
    like_escape_char = "\\"  # MySQL's default LIKE escape
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"


class DuckDBDialect(BaseDialect):
    """DuckDB dialect supporting native ILIKE and question mark placeholders."""

    name: str = "duckdb"
    placeholder: str = "?"
    supports_materialized_cte: bool = True
    supports_window_groups_frame: bool = True
    like_escape_char = "\\"
    like_escape_clause = True


class OracleDialect(BaseDialect):
    """Oracle SQL dialect using standard ANSI double-quote escaping and OFFSET-FETCH pagination."""

    name: str = "oracle"
    placeholder: str = "%s"  # OracleConnector rewrites to :1, :2, ... for the driver
    subquery_alias_keyword = ""  # ORA-03048: no AS before a derived-table alias
    like_escape_char = "\\"
    like_escape_clause = True
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(
        self, schema_name: str = "SYSTEM"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM all_tables WHERE owner = {self.placeholder} ORDER BY table_name;",
            [schema_name.upper()],
        )


class RedshiftDialect(BaseDialect):
    """Amazon Redshift dialect."""

    name: str = "redshift"
    placeholder: str = "%s"


class TimescaleDialect(PostgresDialect):
    """TimescaleDB time-series dialect extending PostgreSQL."""

    name: str = "timescaledb"


class CockroachDialect(PostgresDialect):
    """CockroachDB distributed SQL dialect extending PostgreSQL."""

    name: str = "cockroachdb"


class SpannerDialect(BaseDialect):
    """Google Cloud Spanner SQL dialect using backtick quoting."""

    name: str = "spanner"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"`{part}`" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("`", "``")
        return f"`{cleaned}`"


class TiDBDialect(MySQLDialect):
    """TiDB distributed HTAP database dialect."""

    name: str = "tidb"


class SingleStoreDialect(MySQLDialect):
    """SingleStore / MemSQL distributed SQL dialect."""

    name: str = "singlestore"


class TeradataDialect(BaseDialect):
    """Teradata enterprise analytical data warehouse dialect."""

    name: str = "teradata"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )


class D1Dialect(SQLiteDialect):
    """Cloudflare D1 serverless edge SQL database dialect."""

    name: str = "d1"


class NeonDialect(PostgresDialect):
    """Neon serverless PostgreSQL dialect."""

    name: str = "neon"


class SupabaseDialect(PostgresDialect):
    """Supabase managed PostgreSQL dialect."""

    name: str = "supabase"


class MaterializeDialect(PostgresDialect):
    """Materialize streaming SQL database engine dialect."""

    name: str = "materialize"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # Materialize rejects a bound OFFSET ("OFFSET must be an integer constant"):
        # inline the int-coerced values.
        return f"LIMIT {int(limit)} OFFSET {int(offset)}", []


class RisingWaveDialect(PostgresDialect):
    """RisingWave distributed streaming SQL database dialect."""

    name: str = "risingwave"


class CrateDBDialect(BaseDialect):
    """CrateDB distributed SQL database dialect."""

    name: str = "cratedb"
    placeholder: str = (
        "?"  # the `crate` client binds qmark parameters; `%s` is a parse error
    )

    def inspect_tables_query(self, schema_name: str = "doc") -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} ORDER BY table_name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "doc", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name, table_name],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name],
        )


class AlloyDBDialect(PostgresDialect):
    """Google Cloud AlloyDB for PostgreSQL dialect."""

    name: str = "alloydb"


class VerticaDialect(BaseDialect):
    """Vertica columnar analytical data warehouse dialect."""

    name: str = "vertica"
    placeholder: str = "%s"


class SAPHANADialect(BaseDialect):
    """SAP HANA in-memory database dialect."""

    name: str = "saphana"
    placeholder: str = "%s"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def inspect_tables_query(
        self, schema_name: str = "SYSTEM"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABLE_NAME FROM SYS.TABLES WHERE SCHEMA_NAME = {self.placeholder} ORDER BY TABLE_NAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "SYSTEM", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME = {self.placeholder} AND TABLE_NAME = {self.placeholder} ORDER BY POSITION;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME = {self.placeholder} ORDER BY TABLE_NAME, POSITION;",
            [schema_name.upper()],
        )


class OceanBaseDialect(MySQLDialect):
    """OceanBase distributed SQL database dialect."""

    name: str = "oceanbase"


class ExasolDialect(BaseDialect):
    """Exasol high-performance in-memory MP-relational analytics dialect."""

    name: str = "exasol"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def inspect_tables_query(
        self, schema_name: str = "PUBLIC"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABLE_NAME FROM EXA_ALL_TABLES WHERE TABLE_SCHEMA = {self.placeholder} ORDER BY TABLE_NAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE, COLUMN_IS_NULLABLE FROM EXA_ALL_COLUMNS WHERE COLUMN_SCHEMA = {self.placeholder} AND COLUMN_TABLE = {self.placeholder} ORDER BY COLUMN_ORDINAL_POSITION;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE, COLUMN_IS_NULLABLE FROM EXA_ALL_COLUMNS WHERE COLUMN_SCHEMA = {self.placeholder} ORDER BY COLUMN_ORDINAL_POSITION;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT CONSTRAINT_TABLE, COLUMN_NAME FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TABLE = {self.placeholder} AND CONSTRAINT_TYPE = 'PRIMARY KEY';",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT CONSTRAINT_TABLE, COLUMN_NAME FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TYPE = 'PRIMARY KEY';",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT CONSTRAINT_TABLE AS src_table, COLUMN_NAME AS src_column, REFERENCED_TABLE AS tgt_table, REFERENCED_COLUMN AS tgt_column FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TABLE = {self.placeholder} AND CONSTRAINT_TYPE = 'FOREIGN KEY';",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT CONSTRAINT_TABLE AS src_table, COLUMN_NAME AS src_column, REFERENCED_TABLE AS tgt_table, REFERENCED_COLUMN AS tgt_column FROM EXA_ALL_CONSTRAINT_COLUMNS WHERE CONSTRAINT_SCHEMA = {self.placeholder} AND CONSTRAINT_TYPE = 'FOREIGN KEY';",
            [schema_name.upper()],
        )


class DB2Dialect(BaseDialect):
    """IBM DB2 enterprise relational database dialect."""

    name: str = "db2"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(
        self, schema_name: str = "SYSCAT"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT TABNAME FROM SYSCAT.TABLES WHERE TABSCHEMA = {self.placeholder} AND TYPE = 'T' ORDER BY TABNAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "SYSCAT", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABNAME, COLNAME, TYPENAME, NULLS FROM SYSCAT.COLUMNS WHERE TABSCHEMA = {self.placeholder} AND TABNAME = {self.placeholder} ORDER BY COLNO;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABNAME, COLNAME, TYPENAME, NULLS FROM SYSCAT.COLUMNS WHERE TABSCHEMA = {self.placeholder} ORDER BY TABNAME, COLNO;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "SYSCAT", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABNAME, COLNAME FROM SYSCAT.KEYCOLUSE WHERE TABSCHEMA = {self.placeholder} AND TABNAME = {self.placeholder} ORDER BY COLSEQ;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABNAME, COLNAME FROM SYSCAT.KEYCOLUSE WHERE TABSCHEMA = {self.placeholder} ORDER BY COLSEQ;",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "SYSCAT", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TABNAME AS src_table, FK_COLNAMES AS src_column, REFTABNAME AS tgt_table, PK_COLNAMES AS tgt_column FROM SYSCAT.REFERENCES WHERE TABSCHEMA = {self.placeholder} AND TABNAME = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT TABNAME AS src_table, FK_COLNAMES AS src_column, REFTABNAME AS tgt_table, PK_COLNAMES AS tgt_column FROM SYSCAT.REFERENCES WHERE TABSCHEMA = {self.placeholder};",
            [schema_name.upper()],
        )


class YugabyteDBDialect(PostgresDialect):
    """YugabyteDB distributed cloud-native HTAP database dialect."""

    name: str = "yugabyte"


class FirebirdDialect(BaseDialect):
    """Firebird relational database dialect using double-quote escaping and ROWS pagination."""

    name: str = "firebird"
    placeholder: str = "?"

    like_escape_char = "\\"
    like_escape_clause = True
    # AVG over an INTEGER column is integer division in Firebird
    avg_template = "AVG(CAST({} AS DOUBLE PRECISION))"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        # SQL:2008 OFFSET/FETCH (Firebird 3.0+): standard, so the structural validator can
        # parse it (the legacy ``ROWS m TO n`` form is not parseable and was rejected).
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(
        self, schema_name: str = "public"
    ) -> tuple[str, list[Any]]:
        return (
            "SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL ORDER BY RDB$RELATION_NAME;",
            [],
        )

    def inspect_columns_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME), TRIM(f.RDB$FIELD_TYPE), rf.RDB$NULL_FLAG FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME WHERE rf.RDB$SYSTEM_FLAG = 0 AND rf.RDB$RELATION_NAME = {self.placeholder} ORDER BY rf.RDB$FIELD_POSITION;",
                [table_name.upper()],
            )
        return (
            "SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME), TRIM(f.RDB$FIELD_TYPE), rf.RDB$NULL_FLAG FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME WHERE rf.RDB$SYSTEM_FLAG = 0 ORDER BY rf.RDB$RELATION_NAME, rf.RDB$FIELD_POSITION;",
            [],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(iseg.RDB$FIELD_NAME) FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' AND rc.RDB$RELATION_NAME = {self.placeholder} ORDER BY iseg.RDB$FIELD_POSITION;",
                [table_name.upper()],
            )
        return (
            "SELECT TRIM(rc.RDB$RELATION_NAME), TRIM(iseg.RDB$FIELD_NAME) FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY' ORDER BY rc.RDB$RELATION_NAME, iseg.RDB$FIELD_POSITION;",
            [],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "public", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT TRIM(rc.RDB$RELATION_NAME) AS src_table, TRIM(iseg.RDB$FIELD_NAME) AS src_column, TRIM(ref_rc.RDB$RELATION_NAME) AS tgt_table, TRIM(ref_iseg.RDB$FIELD_NAME) AS tgt_column FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$REF_CONSTRAINTS refc ON rc.RDB$CONSTRAINT_NAME = refc.RDB$CONSTRAINT_NAME JOIN RDB$RELATION_CONSTRAINTS ref_rc ON refc.RDB$CONST_NAME_UQ = ref_rc.RDB$CONSTRAINT_NAME JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME JOIN RDB$INDEX_SEGMENTS ref_iseg ON ref_rc.RDB$INDEX_NAME = ref_iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY' AND rc.RDB$RELATION_NAME = {self.placeholder};",
                [table_name.upper()],
            )
        return (
            "SELECT TRIM(rc.RDB$RELATION_NAME) AS src_table, TRIM(iseg.RDB$FIELD_NAME) AS src_column, TRIM(ref_rc.RDB$RELATION_NAME) AS tgt_table, TRIM(ref_iseg.RDB$FIELD_NAME) AS tgt_column FROM RDB$RELATION_CONSTRAINTS rc JOIN RDB$REF_CONSTRAINTS refc ON rc.RDB$CONSTRAINT_NAME = refc.RDB$CONSTRAINT_NAME JOIN RDB$RELATION_CONSTRAINTS ref_rc ON refc.RDB$CONST_NAME_UQ = ref_rc.RDB$CONSTRAINT_NAME JOIN RDB$INDEX_SEGMENTS iseg ON rc.RDB$INDEX_NAME = iseg.RDB$INDEX_NAME JOIN RDB$INDEX_SEGMENTS ref_iseg ON ref_rc.RDB$INDEX_NAME = ref_iseg.RDB$INDEX_NAME WHERE rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY';",
            [],
        )


class MonetDBDialect(BaseDialect):
    """MonetDB columnar analytical database dialect using double-quote escaping and LIMIT/OFFSET."""

    name: str = "monetdb"
    placeholder: str = "%s"  # pymonetdb paramstyle is pyformat
    # MonetDB rejects a backslash ESCAPE; "!" works
    like_escape_char = "!"
    like_escape_clause = True

    def inspect_tables_query(self, schema_name: str = "sys") -> tuple[str, list[Any]]:
        return (
            f"SELECT t.name FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.id WHERE s.name = {self.placeholder} AND t.system = FALSE ORDER BY t.name;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "sys", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f'SELECT t.name, c.name, c.type, c."null" FROM sys.columns c JOIN sys.tables t ON c.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE s.name = {self.placeholder} AND t.name = {self.placeholder} ORDER BY c.number;',
                [schema_name, table_name],
            )
        return (
            f'SELECT t.name, c.name, c.type, c."null" FROM sys.columns c JOIN sys.tables t ON c.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE s.name = {self.placeholder} AND t.system = FALSE ORDER BY t.name, c.number;',
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "sys", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.name, kc.name FROM sys.keys k JOIN sys.objects kc ON k.id = kc.id JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE k.type = 0 AND s.name = {self.placeholder} AND t.name = {self.placeholder} ORDER BY kc.nr;",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.name, kc.name FROM sys.keys k JOIN sys.objects kc ON k.id = kc.id JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id WHERE k.type = 0 AND s.name = {self.placeholder} ORDER BY t.name, kc.nr;",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "sys", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.name AS src_table, kc.name AS src_column, rt.name AS tgt_table, rkc.name AS tgt_column FROM sys.keys k JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id JOIN sys.objects kc ON k.id = kc.id JOIN sys.keys rk ON k.rkey = rk.id JOIN sys.tables rt ON rk.table_id = rt.id JOIN sys.objects rkc ON rk.id = rkc.id AND kc.nr = rkc.nr WHERE k.type = 2 AND s.name = {self.placeholder} AND t.name = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.name AS src_table, kc.name AS src_column, rt.name AS tgt_table, rkc.name AS tgt_column FROM sys.keys k JOIN sys.tables t ON k.table_id = t.id JOIN sys.schemas s ON t.schema_id = s.id JOIN sys.objects kc ON k.id = kc.id JOIN sys.keys rk ON k.rkey = rk.id JOIN sys.tables rt ON rk.table_id = rt.id JOIN sys.objects rkc ON rk.id = rkc.id AND kc.nr = rkc.nr WHERE k.type = 2 AND s.name = {self.placeholder};",
            [schema_name],
        )


class H2Dialect(BaseDialect):
    """H2 embedded and in-memory Java database dialect using double-quote escaping and LIMIT/OFFSET."""

    name: str = "h2"
    placeholder: str = "?"
    like_escape_char = "\\"  # H2's default LIKE escape
    like_escape_clause = True

    def inspect_tables_query(
        self, schema_name: str = "PUBLIC"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = {self.placeholder} AND table_type = 'BASE TABLE' ORDER BY table_name;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} AND table_name = {self.placeholder} ORDER BY ordinal_position;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = {self.placeholder} ORDER BY table_name, ordinal_position;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT kcu.table_name, kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "PUBLIC", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder} AND tc.table_name = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT kcu.table_name AS src_table, kcu.column_name AS src_column, ccu.table_name AS tgt_table, ccu.column_name AS tgt_column FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = {self.placeholder};",
            [schema_name.upper()],
        )


class DerbyDialect(BaseDialect):
    """Apache Derby relational database dialect using double-quote escaping and OFFSET/FETCH pagination."""

    name: str = "derby"
    placeholder: str = "?"
    like_escape_char = "\\"  # Derby has no default LIKE escape: declare it
    like_escape_clause = True
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(self, schema_name: str = "APP") -> tuple[str, list[Any]]:
        return (
            f"SELECT t.TABLENAME FROM SYS.SYSTABLES t JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE s.SCHEMANAME = {self.placeholder} AND t.TABLETYPE = 'T' ORDER BY t.TABLENAME;",
            [schema_name.upper()],
        )

    def inspect_columns_query(
        self, schema_name: str = "APP", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.TABLENAME, c.COLUMNNAME, c.COLUMNDATATYPE, c.AUTOINCREMENTVALUE FROM SYS.SYSCOLUMNS c JOIN SYS.SYSTABLES t ON c.REFERENCEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE s.SCHEMANAME = {self.placeholder} AND t.TABLENAME = {self.placeholder} ORDER BY c.COLUMNNUMBER;",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT t.TABLENAME, c.COLUMNNAME, c.COLUMNDATATYPE, c.AUTOINCREMENTVALUE FROM SYS.SYSCOLUMNS c JOIN SYS.SYSTABLES t ON c.REFERENCEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE s.SCHEMANAME = {self.placeholder} ORDER BY t.TABLENAME, c.COLUMNNUMBER;",
            [schema_name.upper()],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "APP", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.TABLENAME, c.CONSTRAINTNAME FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE c.TYPE = 'P' AND s.SCHEMANAME = {self.placeholder} AND t.TABLENAME = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT t.TABLENAME, c.CONSTRAINTNAME FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID WHERE c.TYPE = 'P' AND s.SCHEMANAME = {self.placeholder};",
            [schema_name.upper()],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "APP", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.TABLENAME AS src_table, c.CONSTRAINTNAME AS src_column, rt.TABLENAME AS tgt_table, rc.CONSTRAINTNAME AS tgt_column FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID JOIN SYS.SYSKEYS k ON c.CONSTRAINTID = k.CONSTRAINTID JOIN SYS.SYSCONSTRAINTS rc ON k.CONGLOMERATEID = rc.CONSTRAINTID JOIN SYS.SYSTABLES rt ON rc.TABLEID = rt.TABLEID WHERE c.TYPE = 'F' AND s.SCHEMANAME = {self.placeholder} AND t.TABLENAME = {self.placeholder};",
                [schema_name.upper(), table_name.upper()],
            )
        return (
            f"SELECT t.TABLENAME AS src_table, c.CONSTRAINTNAME AS src_column, rt.TABLENAME AS tgt_table, rc.CONSTRAINTNAME AS tgt_column FROM SYS.SYSCONSTRAINTS c JOIN SYS.SYSTABLES t ON c.TABLEID = t.TABLEID JOIN SYS.SYSSCHEMAS s ON t.SCHEMAID = s.SCHEMAID JOIN SYS.SYSKEYS k ON c.CONSTRAINTID = k.CONSTRAINTID JOIN SYS.SYSCONSTRAINTS rc ON k.CONGLOMERATEID = rc.CONSTRAINTID JOIN SYS.SYSTABLES rt ON rc.TABLEID = rt.TABLEID WHERE c.TYPE = 'F' AND s.SCHEMANAME = {self.placeholder};",
            [schema_name.upper()],
        )


class SybaseDialect(BaseDialect):
    """Sybase / SAP ASE database dialect using square bracket quoting and T-SQL pagination."""

    name: str = "sybase"
    placeholder: str = "?"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def quote_identifier(self, ident: str) -> str:
        _validate_identifier(ident)
        parts = ident.split(".")
        return ".".join(f"[{part}]" for part in parts)

    def quote_alias(self, alias_name: str) -> str:
        _validate_alias(alias_name)
        cleaned = alias_name.replace("]", "]]")
        return f"[{cleaned}]"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return (
            f"OFFSET {self.placeholder} ROWS FETCH NEXT {self.placeholder} ROWS ONLY",
            [offset, limit],
        )

    def inspect_tables_query(self, schema_name: str = "dbo") -> tuple[str, list[Any]]:
        return (
            "SELECT name FROM sysobjects WHERE type = 'U' ORDER BY name;",
            [],
        )

    def inspect_columns_query(
        self, schema_name: str = "dbo", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT o.name, c.name, t.name, c.status FROM syscolumns c JOIN sysobjects o ON c.id = o.id JOIN systypes t ON c.usertype = t.usertype WHERE o.type = 'U' AND o.name = {self.placeholder} ORDER BY c.colid;",
                [table_name],
            )
        return (
            "SELECT o.name, c.name, t.name, c.status FROM syscolumns c JOIN sysobjects o ON c.id = o.id JOIN systypes t ON c.usertype = t.usertype WHERE o.type = 'U' ORDER BY o.name, c.colid;",
            [],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "dbo", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT o.name, c.name FROM sysconstraints con JOIN sysobjects o ON con.tableid = o.id JOIN syscolumns c ON con.tableid = c.id WHERE con.status = 1 AND o.type = 'U' AND o.name = {self.placeholder};",
                [table_name],
            )
        return (
            "SELECT o.name, c.name FROM sysconstraints con JOIN sysobjects o ON con.tableid = o.id JOIN syscolumns c ON con.tableid = c.id WHERE con.status = 1 AND o.type = 'U';",
            [],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "dbo", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT so.name AS src_table, sc.name AS src_column, ro.name AS tgt_table, rc.name AS tgt_column FROM sysreferences r JOIN sysobjects so ON r.tableid = so.id JOIN sysobjects ro ON r.reftabid = ro.id JOIN syscolumns sc ON r.tableid = sc.id JOIN syscolumns rc ON r.reftabid = rc.id WHERE so.name = {self.placeholder};",
                [table_name],
            )
        return (
            "SELECT so.name AS src_table, sc.name AS src_column, ro.name AS tgt_table, rc.name AS tgt_column FROM sysreferences r JOIN sysobjects so ON r.tableid = so.id JOIN sysobjects ro ON r.reftabid = ro.id JOIN syscolumns sc ON r.tableid = sc.id JOIN syscolumns rc ON r.reftabid = rc.id;",
            [],
        )


class InformixDialect(BaseDialect):
    """IBM Informix Dynamic Server dialect using double-quote escaping and SKIP/FIRST pagination."""

    name: str = "informix"
    placeholder: str = "%s"
    pagination_placement: str = "prefix"
    ilike_template: str = "LOWER({col}) LIKE LOWER({ph})"

    def format_limit_offset(self, limit: int, offset: int) -> tuple[str, list[int]]:
        return f"SKIP {self.placeholder} FIRST {self.placeholder}", [offset, limit]

    def inspect_tables_query(
        self, schema_name: str = "informix"
    ) -> tuple[str, list[Any]]:
        return (
            f"SELECT tabname FROM systables WHERE tabtype = 'T' AND owner = {self.placeholder} ORDER BY tabname;",
            [schema_name],
        )

    def inspect_columns_query(
        self, schema_name: str = "informix", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.tabname, c.colname, c.coltype, c.collength FROM syscolumns c JOIN systables t ON c.tabid = t.tabid WHERE t.tabtype = 'T' AND t.owner = {self.placeholder} AND t.tabname = {self.placeholder} ORDER BY c.colno;",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.tabname, c.colname, c.coltype, c.collength FROM syscolumns c JOIN systables t ON c.tabid = t.tabid WHERE t.tabtype = 'T' AND t.owner = {self.placeholder} ORDER BY t.tabname, c.colno;",
            [schema_name],
        )

    def inspect_primary_keys_query(
        self, schema_name: str = "informix", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.tabname, c.constrname FROM sysconstraints c JOIN systables t ON c.tabid = t.tabid WHERE c.constrtype = 'P' AND t.owner = {self.placeholder} AND t.tabname = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.tabname, c.constrname FROM sysconstraints c JOIN systables t ON c.tabid = t.tabid WHERE c.constrtype = 'P' AND t.owner = {self.placeholder};",
            [schema_name],
        )

    def inspect_foreign_keys_query(
        self, schema_name: str = "informix", table_name: str | None = None
    ) -> tuple[str, list[Any]]:
        if table_name:
            return (
                f"SELECT t.tabname AS src_table, c.constrname AS src_column, pt.tabname AS tgt_table, pc.constrname AS tgt_column FROM sysreferences r JOIN sysconstraints c ON r.constrid = c.constrid JOIN systables t ON c.tabid = t.tabid JOIN sysconstraints pc ON r.primaryid = pc.constrid JOIN systables pt ON pc.tabid = pt.tabid WHERE t.owner = {self.placeholder} AND t.tabname = {self.placeholder};",
                [schema_name, table_name],
            )
        return (
            f"SELECT t.tabname AS src_table, c.constrname AS src_column, pt.tabname AS tgt_table, pc.constrname AS tgt_column FROM sysreferences r JOIN sysconstraints c ON r.constrid = c.constrid JOIN systables t ON c.tabid = t.tabid JOIN sysconstraints pc ON r.primaryid = pc.constrid JOIN systables pt ON pc.tabid = pt.tabid WHERE t.owner = {self.placeholder};",
            [schema_name],
        )
