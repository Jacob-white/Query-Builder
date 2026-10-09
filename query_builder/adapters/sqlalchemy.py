"""
SQLAlchemy Adapter for Query Builder.
=====================================
Dual-mode adapter supporting live SQLAlchemy MetaData / Model reflection
and zero-dependency AST parsing of Python model source code.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from query_builder.adapters.utils import normalize_type_name, read_source
from query_builder.models import ColumnSchema, ForeignKey, SchemaDict, TableSchema

SQLALCHEMY_TYPE_MAP: dict[str, str] = {
    "integer": "integer",
    "int": "integer",
    "smallinteger": "integer",
    "biginteger": "bigint",
    "string": "text",
    "text": "text",
    "unicode": "text",
    "unicodetext": "text",
    "varchar": "text",
    "char": "text",
    "boolean": "boolean",
    "datetime": "timestamp",
    "date": "date",
    "time": "time",
    "timestamp": "timestamp",
    "float": "float",
    "numeric": "decimal",
    "decimal": "decimal",
    "json": "json",
    "uuid": "uuid",
    "largebinary": "bytes",
    "binary": "bytes",
}


def _reflect_live_sqlalchemy(target: Any) -> SchemaDict | None:
    """Reflects live SQLAlchemy MetaData, Table, or Model objects."""
    # Check if target is or contains Table objects
    tables = SchemaDict()
    live_tables: list[Any] = []

    if hasattr(target, "tables") and isinstance(target.tables, dict):
        # MetaData instance
        live_tables.extend(target.tables.values())
    elif hasattr(target, "__tablename__") and hasattr(target, "__table__"):
        # Single declarative model
        live_tables.append(target.__table__)
    elif hasattr(target, "columns") and hasattr(target, "name"):
        # Single Table instance
        live_tables.append(target)
    elif isinstance(target, (list, tuple)):
        for item in target:
            if hasattr(item, "__table__"):
                live_tables.append(item.__table__)
            elif hasattr(item, "columns") and hasattr(item, "name"):
                live_tables.append(item)
    elif isinstance(target, dict):
        # Might be dict of models or tables
        for val in target.values():
            if hasattr(val, "__table__"):
                live_tables.append(val.__table__)
            elif hasattr(val, "columns") and hasattr(val, "name"):
                live_tables.append(val)

    if not live_tables:
        return None

    for tbl in live_tables:
        tbl_name = getattr(tbl, "name", str(tbl))
        schema_name = getattr(tbl, "schema", None) or "public"

        columns: list[ColumnSchema] = []
        foreign_keys: list[ForeignKey] = []
        primary_keys: list[str] = []

        for col in tbl.columns:
            col_name = col.name
            is_pk = bool(col.primary_key)
            if is_pk:
                primary_keys.append(col_name)

            is_nullable = bool(col.nullable)
            raw_type = type(col.type).__name__.lower()
            data_type = SQLALCHEMY_TYPE_MAP.get(raw_type, normalize_type_name(raw_type))

            col_enums: list[str] | None = None
            if hasattr(col.type, "enums") and col.type.enums:
                col_enums = list(col.type.enums)
                data_type = "string"

            # Check default
            default_val: Any = None
            if col.default is not None:
                default_val = getattr(col.default, "arg", str(col.default))

            fk: ForeignKey | None = None
            if col.foreign_keys:
                live_fk = next(iter(col.foreign_keys))
                target_col = live_fk.column.name
                target_tbl = live_fk.column.table.name
                fk = ForeignKey(
                    table=tbl_name,
                    column=col_name,
                    foreign_table=target_tbl,
                    foreign_column=target_col,
                )
                foreign_keys.append(fk)

            columns.append(
                ColumnSchema(
                    name=col_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    is_primary=is_pk,
                    default=default_val,
                    comment=getattr(col, "comment", None),
                    enums=col_enums,
                    foreign_key=fk,
                )
            )

        table_enums: dict[str, list[str]] = {}
        for c in columns:
            if c.enums:
                table_enums[c.name] = c.enums

        tables[tbl_name] = TableSchema(
            name=tbl_name,
            schema=schema_name,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            enums=table_enums,
            comment=getattr(tbl, "comment", None),
        )

    return tables


def _parse_ast_sqlalchemy(code: str) -> SchemaDict:
    """Parses Python source code with AST to extract SQLAlchemy models."""
    parsed = ast.parse(code)
    tables = SchemaDict()

    for node in ast.walk(parsed):
        if not isinstance(node, ast.ClassDef):
            continue

        tablename: str | None = None
        columns: list[ColumnSchema] = []
        foreign_keys: list[ForeignKey] = []
        primary_keys: list[str] = []
        composite_pks: list[str] = []

        # Find __tablename__ and constraints
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        if isinstance(item.value, ast.Constant) and isinstance(
                            item.value.value, str
                        ):
                            tablename = item.value.value
                    elif isinstance(target, ast.Name) and target.id == "__table_args__":
                        # Inspect for PrimaryKeyConstraint('a', 'b')
                        for subnode in ast.walk(item.value):
                            if (
                                isinstance(subnode, ast.Call)
                                and getattr(subnode.func, "id", "")
                                == "PrimaryKeyConstraint"
                            ):
                                for arg in subnode.args:
                                    if isinstance(arg, ast.Constant) and isinstance(
                                        arg.value, str
                                    ):
                                        composite_pks.append(arg.value)

        if not tablename:
            # Fallback to snake_cased class name
            s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", node.name)
            tablename = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

        # Parse column assignments:
        # col = Column(...)
        # col: Mapped[...] = mapped_column(...)
        for item in node.body:
            col_target_name: str | None = None
            call_node: ast.Call | None = None
            ann_type_name: str | None = None

            if (
                isinstance(item, ast.Assign)
                and item.targets
                and isinstance(item.targets[0], ast.Name)
            ):
                col_target_name = item.targets[0].id
                if isinstance(item.value, ast.Call):
                    call_node = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                col_target_name = item.target.id
                if isinstance(item.value, ast.Call):
                    call_node = item.value
                # Extract type annotation e.g. Mapped[int], Mapped[str]
                if isinstance(item.annotation, ast.Subscript):
                    slice_node = item.annotation.slice
                    if isinstance(slice_node, ast.Name):
                        ann_type_name = slice_node.id

            if not col_target_name or not call_node:
                continue

            func_name = getattr(call_node.func, "id", "")
            if func_name not in ("Column", "mapped_column"):
                continue

            # Determine column name: check if first arg is string literal
            sql_col_name = col_target_name
            type_call: ast.AST | None = None
            fk_call: ast.Call | None = None

            args = list(call_node.args)
            if (
                args
                and isinstance(args[0], ast.Constant)
                and isinstance(args[0].value, str)
            ):
                sql_col_name = args[0].value
                args = args[1:]

            # Process args for Type or ForeignKey
            for arg in args:
                if isinstance(arg, ast.Call):
                    fn = getattr(arg.func, "id", "")
                    if fn == "ForeignKey":
                        fk_call = arg
                    else:
                        type_call = arg
                elif isinstance(arg, ast.Name):
                    if arg.id == "ForeignKey":
                        pass
                    else:
                        type_call = arg

            # Process keywords
            is_pk = False
            is_nullable: bool | None = None
            default_val: Any = None
            comment: str | None = None

            for kw in call_node.keywords:
                if kw.arg == "primary_key":
                    if isinstance(kw.value, ast.Constant):
                        is_pk = bool(kw.value.value)
                elif kw.arg == "nullable":
                    if isinstance(kw.value, ast.Constant):
                        is_nullable = bool(kw.value.value)
                elif kw.arg == "default":
                    if isinstance(kw.value, ast.Constant):
                        default_val = kw.value.value
                    elif isinstance(kw.value, ast.Name):
                        default_val = kw.value.id
                elif kw.arg == "comment":
                    if isinstance(kw.value, ast.Constant):
                        comment = str(kw.value.value)
                elif kw.arg == "type_":
                    type_call = kw.value

            if sql_col_name in composite_pks or col_target_name in composite_pks:
                is_pk = True

            if is_pk:
                primary_keys.append(sql_col_name)
                if is_nullable is None:
                    is_nullable = False
            elif is_nullable is None:
                is_nullable = True

            # Determine type & enums
            data_type = "text"
            col_enums: list[str] | None = None

            if type_call is not None:
                type_name = ""
                if isinstance(type_call, ast.Call):
                    type_name = getattr(type_call.func, "id", "").lower()
                    if type_name == "enum":
                        # Check enum string arguments e.g. Enum('admin', 'customer', name='role_enum')
                        enum_vals = [
                            a.value
                            for a in type_call.args
                            if isinstance(a, ast.Constant) and isinstance(a.value, str)
                        ]
                        if enum_vals:
                            col_enums = enum_vals
                            data_type = "string"
                elif isinstance(type_call, ast.Name):
                    type_name = type_call.id.lower()

                if not col_enums and type_name:
                    data_type = SQLALCHEMY_TYPE_MAP.get(
                        type_name, normalize_type_name(type_name)
                    )
            elif ann_type_name:
                type_lower = ann_type_name.lower()
                if type_lower in ("int", "integer"):
                    data_type = "integer"
                elif type_lower in ("str", "string", "text"):
                    data_type = "text"
                elif type_lower in ("bool", "boolean"):
                    data_type = "boolean"
                elif type_lower in ("float", "decimal"):
                    data_type = "float"
                else:
                    data_type = normalize_type_name(type_lower)

            # Check ForeignKey
            fk: ForeignKey | None = None
            if fk_call and fk_call.args:
                fk_target_arg = fk_call.args[0]
                if isinstance(fk_target_arg, ast.Constant) and isinstance(
                    fk_target_arg.value, str
                ):
                    fk_ref = fk_target_arg.value
                    if "." in fk_ref:
                        ref_tbl, ref_col = fk_ref.split(".", 1)
                        fk = ForeignKey(
                            table=tablename,
                            column=sql_col_name,
                            foreign_table=ref_tbl,
                            foreign_column=ref_col,
                        )
                        foreign_keys.append(fk)

            columns.append(
                ColumnSchema(
                    name=sql_col_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    is_primary=is_pk,
                    default=default_val,
                    comment=comment,
                    enums=col_enums,
                    foreign_key=fk,
                )
            )

        table_enums: dict[str, list[str]] = {}
        for c in columns:
            if c.enums:
                table_enums[c.name] = c.enums

        tables[tablename] = TableSchema(
            name=tablename,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            enums=table_enums,
        )

    return tables


def from_sqlalchemy(source: Any) -> SchemaDict:
    """
    Parses SQLAlchemy metadata, declarative models, or Python model code into TableSchema models.

    Args:
        source: SQLAlchemy MetaData instance, Model class, list of Models,
                or Python model file path/source code string.

    Returns:
        SchemaDict mapping table names to TableSchema instances.
    """
    # 1. Attempt live reflection first if source is not a plain string
    if not isinstance(source, (str, bytes)):
        live_result = _reflect_live_sqlalchemy(source)
        if live_result is not None:
            return live_result

    # 2. Treat as code string or file path
    code = read_source(source)
    return _parse_ast_sqlalchemy(code)
