"""
Prisma Schema Adapter for Query Builder.
========================================
Parses Prisma schema definitions (.prisma files or strings) and Prisma DMMF
(Data Model Meta Format) dictionaries into Query-Builder TableSchema models.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from typing import Any

from query_builder.adapters.utils import normalize_type_name, read_source
from query_builder.models import ColumnSchema, ForeignKey, SchemaDict, TableSchema

PRISMA_TYPE_MAP: dict[str, str] = {
    "int": "integer",
    "bigint": "bigint",
    "float": "float",
    "decimal": "decimal",
    "string": "text",
    "boolean": "boolean",
    "datetime": "timestamp",
    "json": "json",
    "bytes": "bytes",
}


def _parse_prisma_dmmF(dmmf: dict[str, Any]) -> SchemaDict:
    """Parses a Prisma DMMF structure into a SchemaDict."""
    datamodel = dmmf.get("datamodel", dmmf)
    raw_enums = datamodel.get("enums", [])
    raw_models = datamodel.get("models", [])

    enums: dict[str, list[str]] = {}
    for enum_def in raw_enums:
        name = enum_def.get("name", "")
        values: list[str] = []
        for val in enum_def.get("values", []):
            if isinstance(val, dict):
                values.append(val.get("name", ""))
            else:
                values.append(str(val))
        if name:
            enums[name] = values

    # Map model name to actual DB table name
    model_to_table: dict[str, str] = {}
    for model in raw_models:
        model_name = model.get("name", "")
        table_name = model.get("dbName") or model_name
        model_to_table[model_name] = table_name

    tables = SchemaDict()

    for model in raw_models:
        model_name = model.get("name", "")
        table_name = model.get("dbName") or model_name

        columns: list[ColumnSchema] = []
        foreign_keys: list[ForeignKey] = []
        primary_keys: list[str] = []

        # Model-level primary key
        pk_info = model.get("primaryKey")
        if pk_info and isinstance(pk_info, dict) and "fields" in pk_info:
            primary_keys.extend(pk_info["fields"])

        fields = model.get("fields", [])
        relation_map: dict[str, tuple[str, str]] = {}

        # First pass: collect relations
        for f in fields:
            kind = f.get("kind", "")
            if kind == "object":
                rel_from = f.get("relationFromFields") or []
                rel_to = f.get("relationToFields") or []
                target_model = f.get("type", "")
                target_table = model_to_table.get(target_model, target_model)
                if rel_from and rel_to:
                    relation_map[rel_from[0]] = (target_table, rel_to[0])

        # Second pass: construct columns
        for f in fields:
            kind = f.get("kind", "")
            if kind == "object":
                continue  # Virtual relation field

            col_name = f.get("dbName") or f.get("name", "")
            raw_type = f.get("type", "String")
            is_nullable = not f.get("isRequired", True)
            is_primary = bool(f.get("isId", False))
            if is_primary and col_name not in primary_keys:
                primary_keys.append(col_name)

            default_val = f.get("default")
            if isinstance(default_val, dict) and "name" in default_val:
                default_val = f"{default_val['name']}()"

            col_enums: list[str] | None = None
            if kind == "enum" or raw_type in enums:
                data_type = "string"
                col_enums = enums.get(raw_type)
            else:
                data_type = PRISMA_TYPE_MAP.get(
                    raw_type.lower(), normalize_type_name(raw_type)
                )

            fk: ForeignKey | None = None
            orig_name = f.get("name", "")
            if orig_name in relation_map:
                tgt_table, tgt_col = relation_map[orig_name]
                fk = ForeignKey(
                    table=table_name,
                    column=col_name,
                    foreign_table=tgt_table,
                    foreign_column=tgt_col,
                )
                foreign_keys.append(fk)

            columns.append(
                ColumnSchema(
                    name=col_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    is_primary=is_primary,
                    default=default_val,
                    comment=f.get("documentation"),
                    enums=col_enums,
                    foreign_key=fk,
                )
            )

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
            comment=model.get("documentation"),
        )

    return tables


_ENUM_HEADER_RE = re.compile(r"enum\s+(\w+)\s*\{")
_MODEL_HEADER_RE = re.compile(r"model\s+(\w+)\s*\{")


def _find_blocks(text: str, header_re: re.Pattern[str]) -> list[tuple[str, str]]:
    r"""Returns ``(name, body)`` for each ``<keyword> name { body }`` block, linearly.

    Equivalent to ``re.findall(r"enum\s+(\w+)\s*\{([^}]*)\}", text)`` and to the former
    ``model`` pattern ``model\s+(\w+)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}``: the greedy
    ``[^}]*`` always reaches the first ``}`` where the final ``\}`` matches at once, so
    the nested-group part of the model pattern never participated in a successful match
    and only caused catastrophic backtracking when no ``}`` followed (``"model a {" * n``
    took minutes).  Once one header has no closing brace no later one has either, so the
    scan stops instead of rescanning to the end of the text from every header.
    """
    blocks: list[tuple[str, str]] = []
    pos = 0
    while True:
        header = header_re.search(text, pos)
        if header is None:
            return blocks
        close = text.find("}", header.end())
        if close < 0:
            return blocks
        blocks.append((header.group(1), text[header.end() : close]))
        pos = close + 1


_RELATION_START_RE = re.compile(r"@relation\(")
_FIELDS_RE = re.compile(r"fields\s*:\s*\[")
_REFERENCES_RE = re.compile(r"references\s*:\s*\[")


def _match_relation(line: str) -> tuple[str, str] | None:
    r"""Returns ``(fields, references)`` of the first ``@relation(...)`` on ``line``.

    Linear-time equivalent of ``re.search`` with::

        @relation\([^)]*fields\s*:\s*\[([^\]]+)\][^)]*references\s*:\s*\[([^\]]+)\][^)]*\)

    whose three ``[^)]*`` gaps and two ``[^\]]+`` groups backtrack cubically.  A
    ``[`` opens each list, which ends at the first ``]`` (non-empty), and the ``(``
    gaps cannot cross a ``)``.  The regex prefers the last ``fields`` and then the last
    ``references`` that lead to a match, and the leftmost ``@relation(`` that matches
    wins.  A start that fails makes every start before the same ``)`` fail, so each
    ``)``-delimited region is examined once.
    """
    close_parens = [i for i, ch in enumerate(line) if ch == ")"]
    if not close_parens:
        return None
    close_brackets = [i for i, ch in enumerate(line) if ch == "]"]
    length = len(line)

    def first_after(positions: list[int], index: int) -> int:
        at = bisect_left(positions, index)
        return positions[at] if at < len(positions) else -1

    def list_end(bracket: int) -> int:
        """End of the list opened at ``bracket`` (-1 when empty / unterminated)."""
        end = first_after(close_brackets, bracket + 1)
        return end if end > bracket + 1 else -1

    fields = [(m.start(), m.end() - 1) for m in _FIELDS_RE.finditer(line)]
    field_starts = [start for start, _ in fields]
    field_brackets = [bracket for _, bracket in fields]
    references = [(m.start(), m.end() - 1) for m in _REFERENCES_RE.finditer(line)]
    ref_starts = [start for start, _ in references]
    ref_brackets = [bracket for _, bracket in references]
    # A references list is usable when it is closed and a ")" follows it.
    last_paren = close_parens[-1]
    ref_ends = [list_end(bracket) for _, bracket in references]
    usable = [end != -1 and end < last_paren for end in ref_ends]
    previous_usable: list[int] = []
    latest = -1
    for index, ok in enumerate(usable):
        latest = index if ok else latest
        previous_usable.append(latest)

    scanned_until = -1
    for start in _RELATION_START_RE.finditer(line):
        position = start.end()
        if position < scanned_until:
            continue  # same ")"-delimited region as a start that already failed
        region_end = first_after(close_parens, position)
        region_end = length if region_end == -1 else region_end
        scanned_until = region_end
        low = bisect_left(field_starts, position)
        high = bisect_left(field_brackets, region_end)
        for index in range(high - 1, low - 1, -1):
            bracket = fields[index][1]
            fields_end = list_end(bracket)
            if fields_end == -1:
                continue
            gap_end = first_after(close_parens, fields_end + 1)
            gap_end = length if gap_end == -1 else gap_end
            first_ref = bisect_left(ref_starts, fields_end + 1)
            last_ref = bisect_left(ref_brackets, gap_end) - 1
            if last_ref < first_ref:
                continue
            chosen = previous_usable[last_ref]
            if chosen >= first_ref:
                ref_bracket = references[chosen][1]
                return (
                    line[bracket + 1 : fields_end],
                    line[ref_bracket + 1 : ref_ends[chosen]],
                )
    return None


_ID_LIST_RE = re.compile(r"@@id\(\s*\[([^\]]+)\]\s*\)")
_CLOSE_PAREN_RE = re.compile(r"\s*\)")


def _through_last_list_close(text: str) -> str:
    r"""``text`` cut after the last ``]`` (and an immediately following ``\s*)``).

    ``@@id\(\s*\[([^\]]+)\]\s*\)`` can only match up to there, and searching the
    cut text is equivalent while guaranteeing every ``[^\]]+`` scan ends at a ``]``
    (repeated ``@@id([`` starts without any ``]`` were otherwise quadratic).
    """
    cut = text.rfind("]") + 1
    if not cut:
        return ""
    closing = _CLOSE_PAREN_RE.match(text, cut)
    return text[: closing.end() if closing else cut]


def from_prisma(source: str | dict[str, Any]) -> SchemaDict:
    """
    Parses a Prisma schema definition string, file path, or DMMF dictionary
    into Query-Builder TableSchema models.

    Args:
        source: Prisma schema file path, schema DSL string, or pre-parsed DMMF dictionary.

    Returns:
        SchemaDict mapping table names to TableSchema instances.
    """
    if isinstance(source, dict):
        return _parse_prisma_dmmF(source)

    text = read_source(source)

    # 1. Parse Enums: enum <Name> { ... }
    enums: dict[str, list[str]] = {}
    enum_blocks = _find_blocks(text, _ENUM_HEADER_RE)
    for enum_name, enum_body in enum_blocks:
        values = []
        for raw_line in enum_body.strip().splitlines():
            clean_line = raw_line.split("//")[0].strip()
            if clean_line:
                values.append(clean_line)
        enums[enum_name] = values

    # 2. Extract model name to @@map name
    model_blocks = _find_blocks(text, _MODEL_HEADER_RE)
    model_to_table: dict[str, str] = {}
    for model_name, model_body in model_blocks:
        map_match = re.search(r'@@map\(\s*["\']([^"\']+)["\']\s*\)', model_body)
        model_to_table[model_name] = map_match.group(1) if map_match else model_name

    tables = SchemaDict()

    for model_name, model_body in model_blocks:
        map_match = re.search(r'@@map\(\s*["\']([^"\']+)["\']\s*\)', model_body)
        table_name = map_match.group(1) if map_match else model_name

        # Check composite primary keys: @@id([field1, field2])
        composite_pk: list[str] = []
        pk_match = _ID_LIST_RE.search(_through_last_list_close(model_body))
        if pk_match:
            composite_pk = [
                f.strip() for f in pk_match.group(1).split(",") if f.strip()
            ]

        # Scan relation directives
        # e.g.: user User @relation(fields: [userId], references: [id])
        relation_map: dict[str, tuple[str, str]] = {}

        for line in model_body.splitlines():
            clean_line = line.split("//")[0].strip()
            if not clean_line or clean_line.startswith("@@"):
                continue
            rel_m = _match_relation(clean_line)
            if rel_m:
                parts = clean_line.split()
                if len(parts) >= 2:
                    rel_type = parts[1].replace("?", "").replace("[]", "")
                    target_table = model_to_table.get(rel_type, rel_type)
                    from_fields = [f.strip() for f in rel_m[0].split(",") if f.strip()]
                    to_fields = [f.strip() for f in rel_m[1].split(",") if f.strip()]
                    if from_fields and to_fields:
                        relation_map[from_fields[0]] = (target_table, to_fields[0])

        columns: list[ColumnSchema] = []
        foreign_keys: list[ForeignKey] = []
        primary_keys: list[str] = list(composite_pk)

        for line in model_body.splitlines():
            comment: str | None = None
            if "///" in line:
                comment = line.split("///", 1)[1].strip()
            clean_line = line.split("//")[0].strip()
            if not clean_line or clean_line.startswith("@@"):
                continue

            parts = clean_line.split()
            if len(parts) < 2:
                continue

            field_name = parts[0]
            raw_field_type = parts[1]

            # If field_type is a relation model or list of relation models, skip if not column
            base_type = raw_field_type.rstrip("?").rstrip("[]")
            if base_type in model_to_table:
                # Virtual relation field
                continue

            # Check nullability
            is_nullable = raw_field_type.endswith("?")

            # Column mapping via @map("...")
            col_map_m = re.search(r'@map\(\s*["\']([^"\']+)["\']\s*\)', clean_line)
            col_name = col_map_m.group(1) if col_map_m else field_name

            # Primary key via @id
            is_primary = "@id" in clean_line or field_name in composite_pk
            if is_primary and col_name not in primary_keys:
                primary_keys.append(col_name)

            # Default value via @default(...)
            default_val: Any = None
            def_idx = clean_line.find("@default(")
            if def_idx != -1:
                start = def_idx + len("@default(")
                depth = 1
                end = start
                while end < len(clean_line) and depth > 0:
                    if clean_line[end] == "(":
                        depth += 1
                    elif clean_line[end] == ")":
                        depth -= 1
                    end += 1
                if depth == 0:
                    raw_def = clean_line[start : end - 1].strip()
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
            if base_type in enums:
                data_type = "string"
                col_enums = enums[base_type]
            else:
                data_type = PRISMA_TYPE_MAP.get(
                    base_type.lower(), normalize_type_name(base_type)
                )

            # Check foreign key
            fk: ForeignKey | None = None
            if field_name in relation_map or col_name in relation_map:
                tgt_tbl, tgt_col = relation_map.get(
                    field_name, relation_map.get(col_name)
                )  # type: ignore[arg-type]
                fk = ForeignKey(
                    table=table_name,
                    column=col_name,
                    foreign_table=tgt_tbl,
                    foreign_column=tgt_col,
                )
                foreign_keys.append(fk)

            columns.append(
                ColumnSchema(
                    name=col_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    is_primary=is_primary,
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

        tables[table_name] = TableSchema(
            name=table_name,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            enums=table_enums,
        )

    return tables
