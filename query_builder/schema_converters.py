"""
Schema Exporters and Model Converters for Query Builder Engine.
================================================================
Transforms Query-Builder SchemaSnapshot metadata and schema dictionaries
into production-ready definitions for:
- Prisma Schema (.prisma)
- Drizzle ORM TypeScript definitions (.ts)
- SQLAlchemy Declarative Base Python models (.py)
"""

from __future__ import annotations

import re
from typing import Any

from query_builder.models import (
    ColumnMeta,
    ColumnSchema,
    ForeignKey,
    ForeignKeyMeta,
    SchemaSnapshot,
    TableMeta,
    TableSchema,
)

SUPPORTED_PRISMA_PROVIDERS: set[str] = {
    "postgresql",
    "mysql",
    "sqlite",
    "sqlserver",
    "cockroachdb",
    "mongodb",
}

PRISMA_PROVIDER_ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "mssql": "sqlserver",
}

SUPPORTED_DRIZZLE_DIALECTS: set[str] = {
    "postgres",
    "mysql",
    "sqlite",
}

DRIZZLE_DIALECT_ALIASES: dict[str, str] = {
    "postgresql": "postgres",
}


def _to_pascal_case(name: str) -> str:
    """Converts snake_case, kebab-case, or spaced strings to PascalCase."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", name).strip()
    if not cleaned:
        return "Model"
    words = cleaned.split()
    result = "".join(w.capitalize() for w in words)
    if result and result[0].isdigit():
        result = f"Model{result}"
    return result


def _to_camel_case(name: str) -> str:
    """Converts snake_case, kebab-case, or spaced strings to camelCase."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", name).strip()
    if not cleaned:
        return "field"
    words = cleaned.split()
    first = words[0].lower()
    rest = "".join(w.capitalize() for w in words[1:])
    result = f"{first}{rest}"
    if result and result[0].isdigit():
        result = f"col{result}"
    return result


def _to_snake_case(name: str) -> str:
    """Converts identifier to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    s3 = re.sub(r"[^a-zA-Z0-9]+", "_", s2).lower().strip("_")
    if not s3:
        return "col"
    if s3[0].isdigit():
        s3 = f"col_{s3}"
    return s3


def _extract_snapshot(
    snapshot: SchemaSnapshot | dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """
    Normalizes a SchemaSnapshot or raw dictionary into a structured tables dict
    and deduplicated foreign keys list.
    """
    if isinstance(snapshot, SchemaSnapshot):
        raw_tables = snapshot.tables
        raw_fks = snapshot.foreign_keys
        raw_rels = snapshot.relationships
    elif isinstance(snapshot, TableSchema):
        raw_tables = {snapshot.name: snapshot}
        raw_fks = list(snapshot.foreign_keys)
        raw_rels = []
    elif isinstance(snapshot, dict):
        if "tables" in snapshot:
            raw_tables = snapshot.get("tables", {})
            raw_fks = list(snapshot.get("foreign_keys") or [])
            raw_rels = list(snapshot.get("relationships") or [])
        else:
            raw_tables = snapshot
            raw_fks = []
            raw_rels = []
    else:
        raise TypeError(
            f"Expected SchemaSnapshot or dict, got {type(snapshot).__name__}"
        )

    tables: dict[str, dict[str, Any]] = {}
    if isinstance(raw_tables, dict):
        for tbl_name, tbl_info in raw_tables.items():
            if isinstance(tbl_info, (TableMeta, TableSchema)):
                t_name = tbl_info.name
                t_comment = tbl_info.comment
                cols_source = tbl_info.columns
                if isinstance(tbl_info, TableSchema) and tbl_info.foreign_keys:
                    for fk in tbl_info.foreign_keys:
                        raw_fks.append(fk)
            elif isinstance(tbl_info, dict):
                t_name = tbl_info.get("name", tbl_name)
                t_comment = tbl_info.get("comment")
                cols_source = tbl_info.get("columns", [])
            else:
                t_name = tbl_name
                t_comment = None
                cols_source = []

            cols: list[dict[str, Any]] = []
            for col in cols_source:
                if isinstance(col, (ColumnMeta, ColumnSchema)):
                    cols.append(
                        {
                            "name": col.name,
                            "data_type": col.data_type,
                            "is_nullable": col.is_nullable,
                            "is_primary": col.is_primary,
                            "comment": col.comment,
                        }
                    )
                elif isinstance(col, dict):
                    cols.append(
                        {
                            "name": col.get("name", ""),
                            "data_type": col.get("data_type", "text"),
                            "is_nullable": bool(col.get("is_nullable", True)),
                            "is_primary": bool(col.get("is_primary", False)),
                            "comment": col.get("comment"),
                        }
                    )
                elif isinstance(col, str):
                    cols.append(
                        {
                            "name": col,
                            "data_type": "text",
                            "is_nullable": True,
                            "is_primary": col == "id",
                            "comment": None,
                        }
                    )

            tables[t_name] = {
                "name": t_name,
                "columns": cols,
                "comment": t_comment,
            }

    seen_fks: set[tuple[str, str, str, str]] = set()
    foreign_keys: list[dict[str, str]] = []

    for fk in raw_fks or []:
        if isinstance(fk, (ForeignKeyMeta, ForeignKey)):
            entry = (fk.table, fk.column, fk.foreign_table, fk.foreign_column)
        elif isinstance(fk, dict):
            entry = (
                fk.get("table", ""),
                fk.get("column", ""),
                fk.get("foreign_table", ""),
                fk.get("foreign_column", ""),
            )
        else:
            continue
        if all(entry) and entry not in seen_fks:
            seen_fks.add(entry)
            foreign_keys.append(
                {
                    "table": entry[0],
                    "column": entry[1],
                    "foreign_table": entry[2],
                    "foreign_column": entry[3],
                }
            )

    for rel in raw_rels or []:
        if isinstance(rel, dict):
            src_tbl = rel.get("source_table", "")
            src_col = rel.get("source_column", "")
            tgt_tbl = rel.get("target_table", "")
            tgt_col = rel.get("target_column", "")
            entry = (src_tbl, src_col, tgt_tbl, tgt_col)
            if all(entry) and entry not in seen_fks:
                seen_fks.add(entry)
                foreign_keys.append(
                    {
                        "table": entry[0],
                        "column": entry[1],
                        "foreign_table": entry[2],
                        "foreign_column": entry[3],
                    }
                )

    return tables, foreign_keys


def to_prisma_schema(
    snapshot: SchemaSnapshot | dict[str, Any],
    provider: str = "postgresql",
) -> str:
    """
    Converts a SchemaSnapshot or dictionary to a Prisma schema (.prisma).

    Generates:
    - datasource db block with configured provider and url = env("DATABASE_URL")
    - generator client block
    - Typed model declarations with @id, @default(autoincrement()), nullability (?)
    - Bidirectional @relation directives with matching back-relations
    - Field-level @map and model-level @@map attributes
    """
    clean_provider = provider.lower().strip()
    clean_provider = PRISMA_PROVIDER_ALIASES.get(clean_provider, clean_provider)
    if clean_provider not in SUPPORTED_PRISMA_PROVIDERS:
        supported = sorted(SUPPORTED_PRISMA_PROVIDERS)
        raise ValueError(
            f"Unsupported Prisma provider '{provider}'. Supported: {supported}"
        )

    tables, foreign_keys = _extract_snapshot(snapshot)

    header = (
        "datasource db {\n"
        f'  provider = "{clean_provider}"\n'
        '  url      = env("DATABASE_URL")\n'
        "}\n\n"
        "generator client {\n"
        '  provider = "prisma-client-js"\n'
        "}"
    )

    if not tables:
        return header

    # Index foreign keys
    # outgoing: table -> list of fks
    # incoming: foreign_table -> list of fks
    outgoing_fks: dict[str, list[dict[str, str]]] = {t: [] for t in tables}
    incoming_fks: dict[str, list[dict[str, str]]] = {t: [] for t in tables}
    rel_counts: dict[tuple[str, str], int] = {}

    for fk in foreign_keys:
        src = fk["table"]
        tgt = fk["foreign_table"]
        if src in tables and tgt in tables:
            outgoing_fks[src].append(fk)
            incoming_fks[tgt].append(fk)
            pair = (src, tgt)
            rel_counts[pair] = rel_counts.get(pair, 0) + 1

    model_blocks: list[str] = []

    for table_name, table_info in tables.items():
        model_name = _to_pascal_case(table_name)
        columns = table_info["columns"]
        lines: list[str] = []

        # 1. Scalar column definitions
        for col in columns:
            c_name = col["name"]
            c_type = col.get("data_type", "text").lower()
            is_pk = col.get("is_primary", False)
            is_nullable = col.get("is_nullable", True)

            field_name = _to_camel_case(c_name)

            # Map SQL type to Prisma type
            if any(t in c_type for t in ("bigint", "bigserial")):
                prisma_type = "BigInt"
            elif any(t in c_type for t in ("int", "serial", "smallint", "tinyint")):
                prisma_type = "Int"
            elif any(t in c_type for t in ("bool", "boolean")):
                prisma_type = "Boolean"
            elif any(t in c_type for t in ("float", "double", "real")):
                prisma_type = "Float"
            elif any(t in c_type for t in ("decimal", "numeric", "money")):
                prisma_type = "Decimal"
            elif any(t in c_type for t in ("datetime", "timestamp", "date", "time")):
                prisma_type = "DateTime"
            elif any(t in c_type for t in ("json", "jsonb")):
                prisma_type = "Json"
            elif any(t in c_type for t in ("bytea", "blob", "binary", "varbinary")):
                prisma_type = "Bytes"
            else:
                prisma_type = "String"

            # Directives
            directives: list[str] = []
            if is_pk:
                directives.append("@id")
                if prisma_type == "Int":
                    directives.append("@default(autoincrement())")
                type_suffix = ""
            else:
                type_suffix = "?" if is_nullable else ""

            if field_name != c_name:
                directives.append(f'@map("{c_name}")')

            directive_str = f" {' '.join(directives)}" if directives else ""
            lines.append(f"  {field_name} {prisma_type}{type_suffix}{directive_str}")

        # 2. Outgoing relation fields
        for fk in outgoing_fks.get(table_name, []):
            src_col = fk["column"]
            tgt_tbl = fk["foreign_table"]
            tgt_col = fk["foreign_column"]
            target_model = _to_pascal_case(tgt_tbl)
            src_field = _to_camel_case(src_col)
            tgt_field = _to_camel_case(tgt_col)

            # Determine relation field name
            if src_col.lower().endswith("_id"):
                base_rel = _to_camel_case(src_col[:-3])
            elif src_col.lower().endswith("id") and len(src_col) > 2:
                base_rel = _to_camel_case(src_col[:-2])
            else:
                base_rel = _to_camel_case(tgt_tbl)

            # If clashes with existing scalar field name, disambiguate
            rel_field_name = base_rel
            if rel_field_name in {_to_camel_case(c["name"]) for c in columns}:
                rel_field_name = f"{base_rel}Rel"

            # Nullability matches foreign key column
            col_meta = next((c for c in columns if c["name"] == src_col), None)
            rel_nullable = (
                bool(col_meta.get("is_nullable", True))
                if col_meta and not col_meta.get("is_primary", False)
                else False
            )
            rel_suffix = "?" if rel_nullable else ""

            pair = (table_name, tgt_tbl)
            is_multi = rel_counts.get(pair, 0) > 1
            rel_name_tag = f'"{target_model}_{src_field}", ' if is_multi else ""

            lines.append(
                f"  {rel_field_name} {target_model}{rel_suffix} "
                f"@relation({rel_name_tag}fields: [{src_field}], references: [{tgt_field}])"
            )

        # 3. Incoming back-relations
        for fk in incoming_fks.get(table_name, []):
            src_tbl = fk["table"]
            src_col = fk["column"]
            source_model = _to_pascal_case(src_tbl)
            src_field = _to_camel_case(src_col)

            pair = (src_tbl, table_name)
            is_multi = rel_counts.get(pair, 0) > 1

            if is_multi:
                back_field = _to_camel_case(f"{src_tbl}_by_{src_col}")
                rel_tag = f' @relation("{model_name}_{src_field}")'
            else:
                base_back = _to_camel_case(src_tbl)
                back_field = (
                    f"{base_back}s"
                    if not base_back.endswith("s")
                    else f"{base_back}List"
                )
                rel_tag = ""

            # Check collision with existing fields
            existing = {l.strip().split()[0] for l in lines}
            if back_field in existing:
                back_field = f"{back_field}Rel"

            lines.append(f"  {back_field} {source_model}[]{rel_tag}")

        # 4. Table mapping
        if model_name != table_name:
            if lines:
                lines.append("")
            lines.append(f'  @@map("{table_name}")')

        body = "\n".join(lines)
        if body:
            model_blocks.append(f"model {model_name} {{\n{body}\n}}")
        else:
            model_blocks.append(f"model {model_name} {{\n}}")

    models_content = "\n\n".join(model_blocks)
    return f"{header}\n\n{models_content}"


def to_drizzle_schema(
    snapshot: SchemaSnapshot | dict[str, Any],
    dialect: str = "postgres",
) -> str:
    """
    Converts a SchemaSnapshot or dictionary to Drizzle ORM TypeScript definitions.

    Generates:
    - Dialect-specific core imports (drizzle-orm/pg-core, mysql-core, sqlite-core)
    - Typed table declarations (pgTable, mysqlTable, sqliteTable)
    - Column creators, serial/autoincrement primary keys
    - Foreign key constraints via .references(() => targetTable.col)
    - .notNull() chained modifiers
    """
    clean_dialect = dialect.lower().strip()
    clean_dialect = DRIZZLE_DIALECT_ALIASES.get(clean_dialect, clean_dialect)
    if clean_dialect not in SUPPORTED_DRIZZLE_DIALECTS:
        raise ValueError(
            f"Unsupported Drizzle dialect '{dialect}'. Supported: ('postgres', 'mysql', 'sqlite')"
        )

    tables, foreign_keys = _extract_snapshot(snapshot)

    # Core imports per dialect
    if clean_dialect == "postgres":
        import_stmt = (
            "import { bigint, boolean, doublePrecision, integer, jsonb, numeric, "
            'pgTable, serial, text, timestamp, varchar } from "drizzle-orm/pg-core";'
        )
        table_creator = "pgTable"
    elif clean_dialect == "mysql":
        import_stmt = (
            "import { bigint, boolean, decimal, double, int, json, "
            'mysqlTable, serial, text, timestamp, varchar } from "drizzle-orm/mysql-core";'
        )
        table_creator = "mysqlTable"
    else:  # sqlite
        import_stmt = 'import { blob, integer, real, sqliteTable, text } from "drizzle-orm/sqlite-core";'
        table_creator = "sqliteTable"

    if not tables:
        return import_stmt

    # Build FK index: (table, col) -> (foreign_table, foreign_column)
    fk_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    for fk in foreign_keys:
        fk_lookup[(fk["table"], fk["column"])] = (
            fk["foreign_table"],
            fk["foreign_column"],
        )

    table_blocks: list[str] = []

    for table_name, table_info in tables.items():
        table_var = _to_camel_case(table_name)
        columns = table_info["columns"]

        col_lines: list[str] = []
        for col in columns:
            c_name = col["name"]
            c_type = col.get("data_type", "text").lower()
            is_pk = col.get("is_primary", False)
            is_nullable = col.get("is_nullable", True)
            col_var = _to_camel_case(c_name)

            is_int = any(t in c_type for t in ("int", "serial", "smallint", "tinyint"))
            is_bigint = any(t in c_type for t in ("bigint", "bigserial"))

            # Column definition per dialect
            if clean_dialect == "postgres":
                if is_pk and is_int:
                    expr = f'serial("{c_name}").primaryKey()'
                elif is_pk:
                    expr = f'text("{c_name}").primaryKey()'
                elif is_bigint:
                    expr = f'bigint("{c_name}", {{ mode: "number" }})'
                elif is_int:
                    expr = f'integer("{c_name}")'
                elif any(t in c_type for t in ("bool", "boolean")):
                    expr = f'boolean("{c_name}")'
                elif any(t in c_type for t in ("float", "double", "real")):
                    expr = f'doublePrecision("{c_name}")'
                elif any(t in c_type for t in ("decimal", "numeric", "money")):
                    expr = f'numeric("{c_name}")'
                elif any(
                    t in c_type for t in ("datetime", "timestamp", "date", "time")
                ):
                    expr = f'timestamp("{c_name}")'
                elif any(t in c_type for t in ("json", "jsonb")):
                    expr = f'jsonb("{c_name}")'
                elif "varchar" in c_type:
                    expr = f'varchar("{c_name}", {{ length: 255 }})'
                else:
                    expr = f'text("{c_name}")'

            elif clean_dialect == "mysql":
                if is_pk and is_int:
                    expr = f'serial("{c_name}").primaryKey()'
                elif is_pk:
                    expr = f'varchar("{c_name}", {{ length: 255 }}).primaryKey()'
                elif is_bigint:
                    expr = f'bigint("{c_name}", {{ mode: "number" }})'
                elif is_int:
                    expr = f'int("{c_name}")'
                elif any(t in c_type for t in ("bool", "boolean")):
                    expr = f'boolean("{c_name}")'
                elif any(t in c_type for t in ("float", "double", "real")):
                    expr = f'double("{c_name}")'
                elif any(t in c_type for t in ("decimal", "numeric", "money")):
                    expr = f'decimal("{c_name}", {{ precision: 10, scale: 2 }})'
                elif any(
                    t in c_type for t in ("datetime", "timestamp", "date", "time")
                ):
                    expr = f'timestamp("{c_name}")'
                elif any(t in c_type for t in ("json", "jsonb")):
                    expr = f'json("{c_name}")'
                else:
                    expr = f'varchar("{c_name}", {{ length: 255 }})'

            else:  # sqlite
                if is_pk and is_int:
                    expr = f'integer("{c_name}").primaryKey({{ autoIncrement: true }})'
                elif is_pk:
                    expr = f'text("{c_name}").primaryKey()'
                elif is_int or is_bigint:
                    expr = f'integer("{c_name}")'
                elif any(t in c_type for t in ("bool", "boolean")):
                    expr = f'integer("{c_name}", {{ mode: "boolean" }})'
                elif any(
                    t in c_type
                    for t in ("float", "double", "real", "decimal", "numeric")
                ):
                    expr = f'real("{c_name}")'
                elif any(t in c_type for t in ("blob", "bytea", "binary")):
                    expr = f'blob("{c_name}")'
                else:
                    expr = f'text("{c_name}")'

            # Foreign key chaining
            fk_key = (table_name, c_name)
            if fk_key in fk_lookup:
                tgt_tbl, tgt_col = fk_lookup[fk_key]
                tgt_tbl_var = _to_camel_case(tgt_tbl)
                tgt_col_var = _to_camel_case(tgt_col)
                expr += f".references(() => {tgt_tbl_var}.{tgt_col_var})"

            # Not-null chaining
            if not is_nullable and not is_pk:
                expr += ".notNull()"

            col_lines.append(f"  {col_var}: {expr},")

        body = "\n".join(col_lines)
        if body:
            table_blocks.append(
                f'export const {table_var} = {table_creator}("{table_name}", {{\n{body}\n}});'
            )
        else:
            table_blocks.append(
                f'export const {table_var} = {table_creator}("{table_name}", {{}});\n'
            )

    tables_content = "\n\n".join(table_blocks)
    return f"{import_stmt}\n\n{tables_content}"


def to_sqlalchemy_models(
    snapshot: SchemaSnapshot | dict[str, Any],
) -> str:
    """
    Converts a SchemaSnapshot or dictionary to SQLAlchemy Declarative Base models (.py).

    Generates:
    - Base = declarative_base() definition
    - Model classes inheriting from Base with __tablename__
    - Column declarations with standard SQLAlchemy types
    - ForeignKey constraints and relationship() definitions
    """
    tables, foreign_keys = _extract_snapshot(snapshot)

    header = (
        "from __future__ import annotations\n\n"
        "from sqlalchemy import (\n"
        "    Boolean,\n"
        "    Column,\n"
        "    DateTime,\n"
        "    Float,\n"
        "    ForeignKey,\n"
        "    Integer,\n"
        "    Numeric,\n"
        "    String,\n"
        "    Text,\n"
        ")\n"
        "from sqlalchemy.orm import declarative_base, relationship\n\n"
        "Base = declarative_base()"
    )

    if not tables:
        return header

    # Build FK index: table -> list of fks
    fks_by_table: dict[str, list[dict[str, str]]] = {t: [] for t in tables}
    for fk in foreign_keys:
        if fk["table"] in tables:
            fks_by_table[fk["table"]].append(fk)

    model_blocks: list[str] = []

    for table_name, table_info in tables.items():
        model_name = _to_pascal_case(table_name)
        columns = table_info["columns"]
        table_comment = table_info.get("comment")

        docstring = (
            table_comment
            if table_comment
            else f"Declarative model for table '{table_name}'."
        )

        lines: list[str] = [
            f"class {model_name}(Base):",
            f'    """{docstring}"""',
            f'    __tablename__ = "{table_name}"',
        ]

        if not columns:
            lines.append("    pass")
            model_blocks.append("\n".join(lines))
            continue

        # Map FK columns for this table
        fk_map = {fk["column"]: fk for fk in fks_by_table.get(table_name, [])}

        col_var_names: set[str] = set()

        for col in columns:
            c_name = col["name"]
            c_type = col.get("data_type", "text").lower()
            is_pk = col.get("is_primary", False)
            is_nullable = col.get("is_nullable", True)

            col_var = _to_snake_case(c_name)
            col_var_names.add(col_var)

            # Map to SQLAlchemy type
            if any(
                t in c_type
                for t in ("bigint", "bigserial", "int", "serial", "smallint", "tinyint")
            ):
                sa_type = "Integer"
            elif any(t in c_type for t in ("bool", "boolean")):
                sa_type = "Boolean"
            elif any(t in c_type for t in ("float", "double", "real")):
                sa_type = "Float"
            elif any(t in c_type for t in ("decimal", "numeric", "money")):
                sa_type = "Numeric"
            elif any(t in c_type for t in ("datetime", "timestamp", "date", "time")):
                sa_type = "DateTime"
            elif any(t in c_type for t in ("text", "clob", "json", "jsonb")):
                sa_type = "Text"
            else:
                sa_type = "String"

            # Check for FK
            if c_name in fk_map:
                fk = fk_map[c_name]
                fk_clause = (
                    f'ForeignKey("{fk["foreign_table"]}.{fk["foreign_column"]}"), '
                )
            else:
                fk_clause = ""

            lines.append(
                f"    {col_var} = Column({sa_type}, {fk_clause}primary_key={is_pk}, nullable={is_nullable})"
            )

        # Generate relationships for outgoing FKs
        for fk in fks_by_table.get(table_name, []):
            src_col = fk["column"]
            tgt_tbl = fk["foreign_table"]
            src_var = _to_snake_case(src_col)
            target_model = _to_pascal_case(tgt_tbl)

            if src_var.endswith("_id"):
                rel_name = src_var[:-3]
            elif src_var.endswith("id") and len(src_var) > 2:
                rel_name = src_var[:-2]
            else:
                rel_name = _to_snake_case(tgt_tbl)

            if rel_name in col_var_names:
                rel_name = f"{rel_name}_rel"

            lines.append(
                f'    {rel_name} = relationship("{target_model}", foreign_keys=[{src_var}])'
            )

        model_blocks.append("\n".join(lines))

    models_content = "\n\n\n".join(model_blocks)
    return f"{header}\n\n\n{models_content}"
