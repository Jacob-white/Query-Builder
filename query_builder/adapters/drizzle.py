"""
Drizzle ORM Adapter for Query Builder.
======================================
Parses Drizzle TypeScript schema definitions (.ts files or code strings)
into Query-Builder TableSchema models.
"""

from __future__ import annotations

import re
from heapq import heappop, heappush
from typing import Any, NamedTuple

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


# ``(?<!\w)`` limits the unanchored search to word starts: a match from the middle of a
# word implies the same match from its first character (which the leftmost-match rule
# prefers), but trying every position of a long identifier was quadratic.
_COLUMN_CALL_RE = re.compile(r"(?<!\w)(\w+)\s*\(\s*(?:['\"`]([^'\"`]*)['\"`])?")


_ENUM_DECL_RE = re.compile(
    r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:pgEnum|mysqlEnum|sqliteEnum)\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*\[([^\]]+)\]",
    re.MULTILINE,
)
# These searches only see text cut after the last closing character (``_through_last``).
_DEFAULT_CALL_RE = re.compile(r"\.default\(([^)]+)\)")
_COLUMNS_LIST_RE = re.compile(r"columns\s*:\s*\[([^\]]+)\]")
_PRIMARY_KEY_CALL_RE = re.compile(r"primaryKey\(([^)]+)\)")
_TABLE_KEYWORD = r"(?:pgTable|mysqlTable|sqliteTable)"
_QUOTED_NAME = r"['\"`]([^'\"`]+)['\"`]"
# ``= pgTable('name'`` (strict: no space before the parenthesis) as used for the
# variable -> table name map, and the looser form used for table headers.
_ASSIGNED_STRICT_RE = re.compile(r"=\s*" + _TABLE_KEYWORD + r"\(\s*" + _QUOTED_NAME)
_ASSIGNED_LOOSE_RE = re.compile(r"=\s*" + _TABLE_KEYWORD + r"\s*\(\s*" + _QUOTED_NAME)
_BARE_TABLE_RE = re.compile(_TABLE_KEYWORD + r"\s*\(\s*" + _QUOTED_NAME)
# ``const name`` + optional ``: annotation`` that ends exactly at the end position
# passed to ``match`` (the ``=`` sign).
_CONST_HEAD_RE = re.compile(r"const\s+(\w+)\s*(?::\s*[^=]+)?\Z")


def _through_last(text: str, char: str) -> str:
    """``text`` up to and including its last ``char`` (empty when there is none).

    Patterns of the form ``literal([^X]+)X`` can only match up to the last ``X``, and
    searching the truncated text is equivalent.  It guarantees that every scan of
    ``[^X]+`` ends at an ``X``; without a following ``X`` each repeated ``literal(``
    start rescanned the rest of the text (quadratic).
    """
    return text[: text.rfind(char) + 1]


def _assignment_head(code: str, eq: int, low: int) -> tuple[int, str] | None:
    r"""Leftmost ``[export ]const name[: type]`` ending exactly at the ``=`` at ``eq``.

    Returns ``(start, name)`` for the leftmost start ``>= low``; the annotation cannot
    contain ``=`` so only the text after the previous ``=`` can hold the head.  This
    replaces the regex ``(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=`` whose
    ``[^=]+`` rescans to the next ``=`` from every ``const x:`` start (quadratic).
    """
    previous = code.rfind("=", low, eq)
    if previous != -1:
        low = previous + 1
    position = code.find("const", low, eq)
    while position != -1:
        match = _CONST_HEAD_RE.match(code, position, eq)
        if match:
            start = position
            before = position
            while before > low and code[before - 1].isspace():
                before -= 1
            if before < position and before - 6 >= low:
                if code.startswith("export", before - 6, before):
                    start = before - 6
            return start, match.group(1)
        position = code.find("const", position + 1, eq)
    return None


class _TableHeader(NamedTuple):
    start: int
    variable: str | None
    table: str


def _find_assigned_tables(code: str) -> list[tuple[str, str]]:
    r"""Linear equivalent of ``findall`` for ``[export ]const v[: T] = pgTable('t'``."""
    headers: list[tuple[str, str]] = []
    last_end = 0
    position = 0
    while True:
        tail = _ASSIGNED_STRICT_RE.search(code, position)
        if tail is None:
            return headers
        head = _assignment_head(code, tail.start(), last_end)
        if head is None:
            position = tail.start() + 1
            continue
        headers.append((head[1], tail.group(1)))
        last_end = position = tail.end()


def _find_table_headers(code: str) -> list[_TableHeader]:
    r"""Linear equivalent of ``finditer`` for the table header pattern.

    ``(?:[export ]const v[: T]=\s*)?(?:pgTable|...)\s*\(\s*'name'`` -- the assignment
    prefix is optional, so every table keyword yields one header.  Matches are found
    in order of their start: a ``const v: T`` head whose annotation spans earlier table
    keywords (the annotation may hold anything but ``=``) starts before them and wins.
    """
    headers: list[_TableHeader] = []
    last_end = 0
    heads: dict[int, tuple[int, str] | None] = {}

    def head_at(eq: int) -> tuple[int, str] | None:
        if eq not in heads:
            heads[eq] = _assignment_head(code, eq, last_end)
        return heads[eq]

    while True:
        bare = _BARE_TABLE_RE.search(code, last_end)
        if bare is None:
            return headers
        keyword = bare.start()
        spanning = None
        eq = code.find("=", keyword)
        if eq != -1:
            tail = _ASSIGNED_LOOSE_RE.match(code, eq)
            head = head_at(eq) if tail else None
            if tail and head and head[0] < keyword:
                spanning = (head, tail)
        if spanning is not None:
            (start, variable), tail = spanning
            headers.append(_TableHeader(start, variable, tail.group(1)))
            last_end = tail.end()
            heads.clear()
            continue
        before = keyword
        while before > last_end and code[before - 1].isspace():
            before -= 1
        head = (
            head_at(before - 1)
            if before > last_end and code[before - 1] == "="
            else None
        )
        if head is None:
            headers.append(_TableHeader(keyword, None, bare.group(1)))
        else:
            headers.append(_TableHeader(head[0], head[1], bare.group(1)))
        last_end = bare.end()
        heads.clear()


class _OpenScans:
    """Open parenthesis scans that currently share one quote state.

    Depths are stored relative to ``offset`` in a min-heap, so a ``(`` / ``)`` applies
    to every scan in the group at once and finished scans pop off the front.
    """

    __slots__ = ("heap", "offset")

    def __init__(self) -> None:
        self.heap: list[tuple[int, int]] = []
        self.offset = 0

    def absorb(self, other: _OpenScans) -> _OpenScans:
        """Merges two groups, moving the smaller heap into the larger one."""
        big, small = (
            (self, other) if len(self.heap) >= len(other.heap) else (other, self)
        )
        for stored, start in small.heap:
            heappush(big.heap, (stored + small.offset - big.offset, start))
        return big


def _balanced_call_ends(code: str, starts: list[int]) -> dict[int, int]:
    r"""Index of the ``)`` closing the call whose ``(`` is at each start (-1: unclosed).

    Equivalent to scanning forward from every start with a depth counter and a quote
    state (a quote closes only on the same character not preceded by a backslash).  The
    quote state evolves independently of the depth, so all scans that are in the same
    quote state can share one pass: a single left-to-right sweep keeps at most four
    groups (no quote, ``'``, ``"``, `````) of open scans in depth-ordered heaps, instead
    of rescanning to the end of the file for every start.
    """
    ends: dict[int, int] = {}
    pending = sorted(set(starts))
    if not pending:
        return ends
    quotes = ("'", '"', "`")
    groups = {
        None: _OpenScans(),
        "'": _OpenScans(),
        '"': _OpenScans(),
        "`": _OpenScans(),
    }
    active = 0
    next_start = 0
    index = pending[0]
    length = len(code)
    while index < length:
        if next_start < len(pending) and pending[next_start] == index:
            fresh = groups[None]
            heappush(fresh.heap, (-fresh.offset, index))
            active += 1
            next_start += 1
        elif not active:
            if next_start >= len(pending):
                break
            index = pending[next_start]
            continue
        char = code[index]
        if char in quotes:
            outside = groups[None]
            inside = groups[char]
            if code[index - 1] == "\\":
                groups[None], groups[char] = _OpenScans(), outside.absorb(inside)
            else:
                groups[None], groups[char] = inside, outside
        elif char == "(":
            groups[None].offset += 1
        elif char == ")":
            group = groups[None]
            group.offset -= 1
            while group.heap and group.heap[0][0] + group.offset == 0:
                ends[heappop(group.heap)[1]] = index
                active -= 1
        index += 1
    for start in pending:
        ends.setdefault(start, -1)
    return ends


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
    # (the pattern ends with "]", so nothing after the last "]" can take part)
    for var_name, enum_db_name, raw_vals in _ENUM_DECL_RE.findall(
        _through_last(code, "]")
    ):
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
    for variable, table in _find_assigned_tables(code):
        table_var_to_name[variable] = table

    tables = SchemaDict()

    # 3. Find table definitions:
    # (pgTable|mysqlTable|sqliteTable)('name', { columns }, (table) => ({ extra }))
    headers = _find_table_headers(code)
    call_starts = [code.find("(", h.start) for h in headers]
    call_ends = _balanced_call_ends(code, [c for c in call_starts if c != -1])

    # A header inside the argument list of a call that was already parsed is not a new
    # table: skipping it keeps the whole pass linear (every argument list is parsed once).
    consumed_end = 0
    for header_match, call_start_idx in zip(headers, call_starts, strict=True):
        if header_match.start < consumed_end:
            continue
        var_name = header_match.variable or ""
        table_name = header_match.table
        if call_start_idx == -1:  # pragma: no cover
            continue

        # Balanced parentheses of the full call (computed for all headers in one pass)
        call_end_idx = call_ends[call_start_idx]

        if call_end_idx == -1:
            continue
        consumed_end = call_end_idx + 1

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
            col_call_m = _COLUMN_CALL_RE.search(expr)
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
                def_m = _DEFAULT_CALL_RE.search(_through_last(expr, ")"))
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
            col_list_m = _COLUMNS_LIST_RE.search(_through_last(extra_block, "]"))
            if col_list_m:
                raw_cols = col_list_m.group(1)
            else:
                pk_pos_m = _PRIMARY_KEY_CALL_RE.search(_through_last(extra_block, ")"))
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
