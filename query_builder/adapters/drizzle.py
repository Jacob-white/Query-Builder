"""
Drizzle ORM Adapter for Query Builder.
======================================
Parses Drizzle TypeScript schema definitions (.ts files or code strings)
into Query-Builder TableSchema models.
"""

from __future__ import annotations

import re
from typing import Any

from query_builder.adapters.utils import normalize_type_name, read_source
from query_builder.models import ColumnSchema, ForeignKey, SchemaDict, TableSchema

DRIZZLE_TYPE_MAP: dict[str, str] = {
    "serial": "integer",
    "bigserial": "bigint",
    "smallserial": "integer",
    "int": "integer",
    "integer": "integer",
    "smallint": "integer",
    "bigint": "bigint",
    "tinyint": "integer",
    "mediumint": "integer",
    "text": "text",
    "varchar": "text",
    "char": "text",
    "boolean": "boolean",
    "bool": "boolean",
    "timestamp": "timestamp",
    "date": "date",
    "datetime": "timestamp",
    "time": "time",
    "float": "float",
    "double": "float",
    "real": "float",
    "doubleprecision": "float",
    "decimal": "decimal",
    "numeric": "decimal",
    "json": "json",
    "jsonb": "json",
    "uuid": "uuid",
    "bytes": "bytes",
    "blob": "bytes",
}


def from_drizzle(source: str | dict[str, Any]) -> SchemaDict:
    """
    Parses Drizzle ORM TypeScript schema code or file into Query-Builder TableSchema models.

    Args:
        source: Drizzle TypeScript schema file path, source string, or structured table definitions.

    Returns:
        SchemaDict mapping table names to TableSchema instances.
    """
    if isinstance(source, dict):
        # Structured dictionary format
        tables = SchemaDict()
        for tbl_name, tbl_data in source.items():
            if isinstance(tbl_data, TableSchema):
                tables[tbl_name] = tbl_data
            elif isinstance(tbl_data, dict):
                cols = []
                for c in tbl_data.get("columns", []):
                    if isinstance(c, ColumnSchema):
                        cols.append(c)
                    elif isinstance(c, dict):
                        cols.append(ColumnSchema(**c))
                tables[tbl_name] = TableSchema(
                    name=tbl_name,
                    columns=cols,
                    primary_keys=tbl_data.get("primary_keys", []),
                    comment=tbl_data.get("comment"),
                )
        return tables

    code = read_source(source)

    # 1. Parse Enums:
    # export const roleEnum = pgEnum('role', ['admin', 'customer', 'guest']);
    # or mysqlEnum('role', ['admin', 'customer'])
    enums: dict[str, list[str]] = {}
    enum_pattern = re.compile(
        r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:pgEnum|mysqlEnum|sqliteEnum)\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*\[([^\]]+)\]",
        re.MULTILINE,
    )
    for var_name, enum_db_name, raw_vals in enum_pattern.findall(code):
        vals = [
            v.strip().strip("'\"`")
            for v in raw_vals.split(",")
            if v.strip().strip("'\"`")
        ]
        enums[var_name] = vals
        enums[enum_db_name] = vals

    # 2. Map variable names to table names:
    # export const users = pgTable('users', ...);
    table_var_to_name: dict[str, str] = {}
    var_table_pattern = re.compile(
        r"(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*(?:pgTable|mysqlTable|sqliteTable)\(\s*['\"`]([^'\"`]+)['\"`]"
    )
    for var_name, tbl_name in var_table_pattern.findall(code):
        table_var_to_name[var_name] = tbl_name

    tables = SchemaDict()

    # 3. Find table definitions:
    # (pgTable|mysqlTable|sqliteTable)('name', { columns }, (table) => ({ extra }))
    table_header_regex = re.compile(
        r"(?:(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*)?(?:pgTable|mysqlTable|sqliteTable)\s*\(\s*['\"`]([^'\"`]+)['\"`]"
    )

    for header_match in table_header_regex.finditer(code):
        var_name = header_match.group(1) or ""
        table_name = header_match.group(2)
        call_start_idx = code.find("(", header_match.start())
        if call_start_idx == -1:  # pragma: no cover
            continue

        # Balance parentheses to find full call
        depth = 0
        in_quote = None
        call_end_idx = -1
        i = call_start_idx
        while i < len(code):
            ch = code[i]
            if in_quote:
                if ch == in_quote and code[i - 1] != "\\":
                    in_quote = None
            elif ch in ("'", '"', "`"):
                in_quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    call_end_idx = i
                    break
            i += 1

        if call_end_idx == -1:
            continue

        args_content = code[call_start_idx + 1 : call_end_idx]
        args = []
        arg_depth = 0
        arg_quote = None
        curr_arg = []
        for ch in args_content:
            if arg_quote:
                if ch == arg_quote and curr_arg and curr_arg[-1] != "\\":
                    arg_quote = None
                curr_arg.append(ch)
            elif ch in ("'", '"', "`"):
                arg_quote = ch
                curr_arg.append(ch)
            elif ch in ("(", "{", "["):
                arg_depth += 1
                curr_arg.append(ch)
            elif ch in (")", "}", "]"):
                arg_depth -= 1
                curr_arg.append(ch)
            elif ch == "," and arg_depth == 0:
                args.append("".join(curr_arg).strip())
                curr_arg = []
            else:
                curr_arg.append(ch)
        if curr_arg:
            args.append("".join(curr_arg).strip())

        raw_col_arg = args[1] if len(args) > 1 else ""
        columns_block = re.sub(r"^\s*\{|\}\s*$", "", raw_col_arg)
        extra_block = args[2] if len(args) > 2 else ""

        # Map variable to table if available
        if var_name:
            table_var_to_name[var_name] = table_name

        columns: list[ColumnSchema] = []
        foreign_keys: list[ForeignKey] = []
        primary_keys: list[str] = []
        col_prop_to_name: dict[str, str] = {}

        # Parse column definitions inside columns_block
        # e.g.: id: serial('id').primaryKey(),
        # userId: integer('user_id').references(() => users.id).notNull(),
        col_lines = []
        # Split by comma or newline while respecting parentheses
        current = []
        paren_depth = 0
        for char in columns_block:
            if char in "({[":
                paren_depth += 1
            elif char in ")}]":
                paren_depth -= 1
            if (char == "," or char == "\n") and paren_depth == 0:
                chunk = "".join(current).strip()
                if chunk:
                    col_lines.append(chunk)
                current = []
            else:
                current.append(char)
        if current:
            chunk = "".join(current).strip()
            if chunk:
                col_lines.append(chunk)

        for raw_col in col_lines:
            col_def = raw_col.split("//")[0].strip()
            if not col_def or ":" not in col_def:
                continue

            prop_name, expr = col_def.split(":", 1)
            prop_name = prop_name.strip()
            expr = expr.strip()

            # Extract column type call: e.g. serial('id'), integer('user_id'), text('bio')
            col_call_m = re.search(r"(\w+)\s*\(\s*(?:['\"`]([^'\"`]*)['\"`])?", expr)
            if not col_call_m:
                continue

            raw_type = col_call_m.group(1)
            sql_col_name = col_call_m.group(2) or prop_name
            col_prop_to_name[prop_name] = sql_col_name

            # Determine primary key
            is_pk = ".primaryKey(" in expr or raw_type.lower() == "serial"
            if is_pk and sql_col_name not in primary_keys:
                primary_keys.append(sql_col_name)

            # Determine nullability
            # In Drizzle, .notNull() makes it non-nullable; serial is also non-nullable
            is_not_null = ".notNull(" in expr or is_pk
            is_nullable = not is_not_null

            # Determine default
            default_val: Any = None
            if ".defaultNow(" in expr:
                default_val = "now()"
            else:
                def_m = re.search(r"\.default\(([^)]+)\)", expr)
                if def_m:
                    raw_def = def_m.group(1).strip()
                    if (raw_def.startswith('"') and raw_def.endswith('"')) or (
                        raw_def.startswith("'") and raw_def.endswith("'")
                    ):
                        default_val = raw_def[1:-1]
                    elif raw_def.lower() in ("true", "false"):
                        default_val = raw_def.lower() == "true"
                    elif raw_def.isdigit():
                        default_val = int(raw_def)
                    else:
                        try:
                            default_val = float(raw_def)
                        except ValueError:
                            default_val = raw_def

            # Check enum
            col_enums: list[str] | None = None
            if raw_type in enums:
                data_type = "string"
                col_enums = enums[raw_type]
            else:
                data_type = DRIZZLE_TYPE_MAP.get(
                    raw_type.lower(), normalize_type_name(raw_type)
                )

            # Check references: .references(() => targetTable.col)
            fk: ForeignKey | None = None
            ref_m = re.search(r"\.references\(\s*\(\)\s*=>\s*(\w+)\.(\w+)", expr)
            if ref_m:
                tgt_var = ref_m.group(1)
                tgt_col_prop = ref_m.group(2)
                tgt_table = table_var_to_name.get(tgt_var, tgt_var)
                fk = ForeignKey(
                    table=table_name,
                    column=sql_col_name,
                    foreign_table=tgt_table,
                    foreign_column=tgt_col_prop,
                )
                foreign_keys.append(fk)

            columns.append(
                ColumnSchema(
                    name=sql_col_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    is_primary=is_pk,
                    default=default_val,
                    enums=col_enums,
                    foreign_key=fk,
                )
            )

        # Check composite primary key in extra_block:
        # pk: primaryKey({ columns: [table.orderId, table.productId] })
        # or primaryKey(table.orderId, table.productId)
        if extra_block and "primaryKey(" in extra_block:
            raw_cols = ""
            col_list_m = re.search(r"columns\s*:\s*\[([^\]]+)\]", extra_block)
            if col_list_m:
                raw_cols = col_list_m.group(1)
            else:
                pk_pos_m = re.search(r"primaryKey\(([^)]+)\)", extra_block)
                if pk_pos_m:
                    raw_cols = pk_pos_m.group(1)
            if raw_cols:
                extra_pks = []
                for c in raw_cols.split(","):
                    c_clean = re.sub(r"[^a-zA-Z0-9_.]", "", c).split(".")[-1].strip()
                    sql_name = col_prop_to_name.get(c_clean, c_clean)
                    if sql_name and sql_name not in extra_pks:
                        extra_pks.append(sql_name)
                if extra_pks:
                    primary_keys = extra_pks
                    for col in columns:
                        if col.name in primary_keys:
                            col.is_primary = True

        table_enums: dict[str, list[str]] = {}
        for c in columns:
            if c.enums:
                table_enums[c.name] = c.enums

        tables[table_name] = TableSchema(
            name=table_name,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            enums=table_enums,
        )

    # Post-process foreign keys to fix any foreign_column property-to-sql mappings
    for tbl in tables.values():
        for fk in tbl.foreign_keys:
            if fk.foreign_table in tables:
                tgt_tbl = tables[fk.foreign_table]
                # If foreign_column matches a column property but not actual column name
                matched = any(c.name == fk.foreign_column for c in tgt_tbl.columns)
                if not matched:
                    for c in tgt_tbl.columns:
                        if c.name.lower() == fk.foreign_column.lower():
                            fk.foreign_column = c.name
                            break

    return tables
