"""
SQL to QuerySpec Parser Module for Query Builder.
=================================================
Provides bidirectional parsing from raw SQL strings back into QuerySpec
and dict representations, supporting CTEs, window functions, temporal time grains,
semantic filtered aggregates, joins, complex WHERE conditions, order by, and pagination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from query_builder._regex_utils import (
    strip_block_comments,
    strip_trailing_semicolons,
)
from query_builder.models import (
    CteSpec,
    FilterSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
    WindowFunctionSpec,
)

ALLOWED_OPERATORS = [
    "IS NOT NULL",
    "IS NULL",
    "NOT IN",
    "IN",
    "BETWEEN",
    "ILIKE",
    "LIKE",
    "STARTS_WITH",
    "ENDS_WITH",
    "CONTAINS",
    ">=",
    "<=",
    "!=",
    "<>",
    "=",
    ">",
    "<",
]

AGGREGATE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


def clean_identifier(ident: str) -> str:
    """Strips quotes, backticks, or brackets from an identifier, supporting dotted parts."""
    if not ident:
        return ""
    clean = ident.strip()

    if "." in clean:
        parts = clean.split(".")
        return ".".join(clean_identifier(p) for p in parts)

    while (
        clean and clean[0] in ('"', "'", "`", "[") and clean[-1] in ('"', "'", "`", "]")
    ):
        clean = clean[1:-1].strip()

    return clean


# ---------------------------------------------------------------------------------
# Linear-time SELECT-item matchers.
#
# The original single-regex forms put ``\s*`` next to a lazy ``.*?`` / ``[^)]+`` that
# could also match whitespace, which backtracks polynomially (cubic) on inputs such as
# ``"0 AS(" + " " * n``.  The patterns below capture the text between the parentheses
# without surrounding ``\s*``; the helpers reproduce the old capture-group values.
# ---------------------------------------------------------------------------------

_ALIAS_TAIL = r"(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$"

_SELECT_WORD_RE = re.compile(r"SELECT\b", re.IGNORECASE)

# ``\s*([\s\S]*)\s*`` around the CTE body is redundant: the caller strips the body.
_CTE_DEF_RE = re.compile(
    r"^([a-zA-Z0-9_\"`\[\]]+)(?:\s*\(([^\)]+)\))?\s+AS\s*"
    r"(?:(MATERIALIZED|NOT\s+MATERIALIZED)\s*)?\(([\s\S]*)\)$",
    re.IGNORECASE,
)

_DATE_TRUNC_RE = re.compile(
    r"^DATE_TRUNC\s*\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*,([^\)]+)\)" + _ALIAS_TAIL,
    re.IGNORECASE,
)
_DATETRUNC_RE = re.compile(
    r"^DATETRUNC\s*\(\s*([a-zA-Z0-9_]+)\s*,([^\)]+)\)" + _ALIAS_TAIL,
    re.IGNORECASE,
)
_AGG_RE = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\s*\(([^\)]+)\)" + _ALIAS_TAIL,
    re.IGNORECASE,
)
_FILTER_AGG_RE = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\s*\(([^\)]+)\)\s+FILTER\s*\(\s*WHERE([^\)]+)\)"
    + _ALIAS_TAIL,
    re.IGNORECASE,
)
_AGG_ARG_RE = re.compile(r"\s*(?:DISTINCT\s+)?([^)]+)", re.IGNORECASE)


def _arg_after_comma(raw: str) -> str:
    """Value of the old ``,\\s*([^\\)]+)`` group: ``raw`` minus leading whitespace.

    When ``raw`` is whitespace only the old regex backtracked ``\\s*`` by one character
    so the group was the final whitespace character.
    """
    return raw.lstrip() or raw[-1:]


def _agg_argument(raw: str) -> str:
    """Value of the old ``\\(\\s*(?:DISTINCT\\s+)?([^\\)]+)\\s*\\)`` group.

    ``raw`` is everything between the parentheses; the group keeps any trailing
    whitespace (the caller strips it).  ``_AGG_ARG_RE`` runs on text without ``)`` so it
    cannot backtrack beyond a single whitespace run.
    """
    match = _AGG_ARG_RE.match(raw)
    return match.group(1) if match else raw  # pragma: no cover


def _valid_filter_condition(raw: str) -> bool:
    """Old ``WHERE\\s+([^\\)]+)``: needs a whitespace char and a non-empty condition."""
    return len(raw) >= 2 and raw[0].isspace()


@dataclass
class _WindowMatch:
    func: str
    args: str
    over: str
    alias: str | None


_WINDOW_HEAD_RE = re.compile(r"([a-zA-Z0-9_]+)\s*\(")
_WINDOW_OVER_RE = re.compile(r"\)\s+OVER\s*\(", re.IGNORECASE)
_WINDOW_TAIL_RE = re.compile(r"\)" + _ALIAS_TAIL, re.IGNORECASE)


def _match_window_expr(expr: str) -> _WindowMatch | None:
    """Matches ``FUNC(args) OVER (body) [[AS] alias]``.

    Equivalent to the former ``^FUNC\\s*\\(\\s*(.*?)\\s*\\)\\s+OVER\\s*\\(\\s*(.*?)\\s*\\)``
    (+ alias tail, ``DOTALL``) regex, whose two lazy groups next to ``\\s*`` were cubic.
    The first ``) OVER (`` is always the lazy choice for the arguments, and the first
    ``)`` after it with a valid tail is the lazy choice for the body.  The returned
    ``args`` / ``over`` keep the surrounding whitespace; callers strip them.
    """
    head = _WINDOW_HEAD_RE.match(expr)
    if head is None:
        return None
    over = _WINDOW_OVER_RE.search(expr, head.end())
    if over is None:
        return None
    body_start = over.end()
    close = body_start - 1
    while True:
        close = expr.find(")", close + 1)
        if close < 0:
            return None
        tail = _WINDOW_TAIL_RE.match(expr, close)
        if tail is not None:
            return _WindowMatch(
                head.group(1),
                expr[head.end() : over.start()],
                expr[body_start:close],
                tail.group(1),
            )


_PARTITION_BY_RE = re.compile(r"\bPARTITION\s+BY\s+", re.IGNORECASE)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\s+", re.IGNORECASE)
_PARTITION_TERMINATOR_RE = re.compile(
    r"\bORDER\s+BY\b|\bROWS\b|\bRANGE\b", re.IGNORECASE
)
_ORDER_TERMINATOR_RE = re.compile(r"\bROWS\b|\bRANGE\b", re.IGNORECASE)


def _clause_body(
    text: str, start_re: re.Pattern[str], terminator_re: re.Pattern[str]
) -> str | None:
    """Body of the first ``start_re`` clause in ``text`` (up to a terminator or ``)``).

    Equivalent to ``re.search(start + r"([^)]*?)(?=" + terminators + r"|$)", text, I)``
    group 1 but linear: a clause start that fails (a ``)`` comes before any terminator
    or the end) makes every start before that ``)`` fail too, so the search resumes
    after it instead of re-scanning.
    """
    length = len(text)
    pos = 0
    while True:
        start = start_re.search(text, pos)
        if start is None:
            return None
        close = text.find(")", start.end())
        limit = length if close < 0 else close
        term = terminator_re.search(text, start.end(), limit)
        if term is not None:
            return text[start.end() : term.start()]
        if close < 0:
            # ``$`` also matches just before a final newline.
            end = length - 1 if text.endswith("\n") else length
            return text[start.end() : max(end, start.end())]
        pos = close + 1


def parse_literal_value(val_str: str) -> Any:
    """Parses raw literal string or number into typed Python value."""
    trimmed = val_str.strip()
    if (trimmed.startswith("'") and trimmed.endswith("'")) or (
        trimmed.startswith('"') and trimmed.endswith('"')
    ):
        return trimmed[1:-1].replace("''", "'")
    if trimmed.lower() == "true":
        return True
    if trimmed.lower() == "false":
        return False
    if re.match(r"^-?\d+$", trimmed):
        return int(trimmed)
    if re.match(r"^-?\d+\.\d+$", trimmed):
        return float(trimmed)
    return trimmed


@dataclass
class ClauseToken:
    keyword: str
    index: int
    length: int


def find_top_level_clauses(sql: str) -> list[ClauseToken]:
    """Finds top-level clause keywords outside of string literals and parentheses."""
    tokens: list[ClauseToken] = []
    upper = sql.upper()
    in_string = False
    string_char = ""
    paren_depth = 0
    sql_len = len(sql)

    keywords = [
        "SELECT",
        "FROM",
        "LEFT JOIN",
        "INNER JOIN",
        "RIGHT JOIN",
        "FULL JOIN",
        "CROSS JOIN",
        "JOIN",
        "WHERE",
        "GROUP BY",
        "ORDER BY",
        "LIMIT",
        "OFFSET",
    ]

    i = 0
    while i < sql_len:
        char = sql[i]

        if in_string:
            if char == string_char:
                if i + 1 < sql_len and sql[i + 1] == string_char:
                    i += 1
                else:
                    in_string = False
            i += 1
            continue

        if char in ("'", '"', "`"):
            in_string = True
            string_char = char
            i += 1
            continue

        if char == "(":
            paren_depth += 1
            i += 1
            continue
        if char == ")":
            if paren_depth > 0:
                paren_depth -= 1
            i += 1
            continue

        if paren_depth == 0:
            matched = False
            for kw in keywords:
                if upper.startswith(kw, i):
                    prev_char = sql[i - 1] if i > 0 else " "
                    next_char = sql[i + len(kw)] if i + len(kw) < sql_len else " "
                    if re.match(r"[\s(),]", prev_char) and re.match(
                        r"[\s(),]", next_char
                    ):
                        tokens.append(ClauseToken(keyword=kw, index=i, length=len(kw)))
                        i += len(kw)
                        matched = True
                        break
            if matched:
                continue

        i += 1

    return tokens


def split_top_level(text: str, delimiter_regex: str) -> list[dict[str, str]]:
    """Splits a clause by delimiter outside parentheses and quotes."""
    parts: list[dict[str, str]] = []
    in_string = False
    string_char = ""
    paren_depth = 0
    last_index = 0
    # Patterns are matched in place (``pattern.match(text, i)``), which is already
    # anchored at ``i``; slicing ``text[i:]`` for every position was quadratic.
    pattern = re.compile(delimiter_regex.removeprefix("^"), re.IGNORECASE)
    text_len = len(text)

    i = 0
    while i < text_len:
        char = text[i]

        if in_string:
            if char == string_char:
                if i + 1 < text_len and text[i + 1] == string_char:
                    i += 1
                else:
                    in_string = False
            i += 1
            continue

        if char in ("'", '"', "`"):
            in_string = True
            string_char = char
            i += 1
            continue

        if char == "(":
            paren_depth += 1
            i += 1
            continue
        if char == ")":
            if paren_depth > 0:
                paren_depth -= 1
            i += 1
            continue

        if paren_depth == 0:
            match = pattern.match(text, i)
            if match:
                parts.append(
                    {
                        "value": text[last_index:i].strip(),
                        "delimiter": match.group(0).strip(),
                    }
                )
                i = match.end()
                last_index = i
                continue

        i += 1

    if last_index < text_len:
        val = text[last_index:].strip()
        if val:
            parts.append({"value": val, "delimiter": ""})

    return [p for p in parts if p["value"]]


def split_where_conditions(text: str) -> list[dict[str, str]]:
    """Splits WHERE conditions by top-level AND/OR outside parens and BETWEEN expressions."""
    parts: list[dict[str, str]] = []
    in_string = False
    string_char = ""
    paren_depth = 0
    last_index = 0
    in_between = False
    text_len = len(text)

    i = 0
    while i < text_len:
        char = text[i]

        if in_string:
            if char == string_char:
                if i + 1 < text_len and text[i + 1] == string_char:
                    i += 1
                else:
                    in_string = False
            i += 1
            continue

        if char in ("'", '"', "`"):
            in_string = True
            string_char = char
            i += 1
            continue

        if char == "(":
            paren_depth += 1
            i += 1
            continue
        if char == ")":
            if paren_depth > 0:
                paren_depth -= 1
            i += 1
            continue

        if paren_depth == 0:
            # (``\b`` is implied at the start of the former ``text[i:]`` slice.)
            if not in_between and _BETWEEN_RE.match(text, i):
                in_between = True
                i += 7
                continue

            # A delimiter can only start at the beginning of a whitespace run: a match
            # attempted mid-run would re-scan the rest of the run (quadratic) and, if it
            # succeeded, the attempt at the run start would already have consumed it.
            if i > 0 and char.isspace() and text[i - 1].isspace():
                i += 1
                continue
            match = _AND_OR_RE.match(text, i)
            if match:
                delim = match.group(1).upper()
                if in_between and delim == "AND":
                    in_between = False
                    i = match.end()
                    continue

                parts.append(
                    {
                        "value": text[last_index:i].strip(),
                        "delimiter": delim,
                    }
                )
                i = match.end()
                last_index = i
                in_between = False
                continue

        i += 1

    if last_index < text_len:
        val = text[last_index:].strip()
        parts.append({"value": val, "delimiter": ""})

    return [p for p in parts if p["value"]]


def _operator_matchers() -> list[tuple[str, bool, re.Pattern[str]]]:
    matchers: list[tuple[str, bool, re.Pattern[str]]] = []
    for op in ALLOWED_OPERATORS:
        is_symbol = bool(re.match(r"^[><=!]+$", op))
        if is_symbol:
            pattern = re.compile(r"\s*(" + re.escape(op) + r")(?![><=])")
        else:
            escaped_op = re.sub(r"\s+", r"\\s+", op)
            pattern = re.compile(r"\s+(" + escaped_op + r")(\s+|$)", re.IGNORECASE)
        matchers.append((op, is_symbol, pattern))
    return matchers


_OPERATOR_MATCHERS = _operator_matchers()
_BETWEEN_RE = re.compile(r"BETWEEN\s+", re.IGNORECASE)
_AND_OR_RE = re.compile(r"\s+(AND|OR)\s+", re.IGNORECASE)


def find_top_level_operator(cond_str: str) -> tuple[str, int, int] | None:
    """Finds top-level operator in a WHERE condition chunk, respecting parentheses and strings."""
    if re.match(r"^\s*(NOT\s+)?EXISTS\s*\(", cond_str, re.IGNORECASE):
        return None

    in_string = False
    string_char = ""
    paren_depth = 0
    cond_len = len(cond_str)

    i = 0
    while i < cond_len:
        char = cond_str[i]

        if in_string:
            if char == string_char:
                if i + 1 < cond_len and cond_str[i + 1] == string_char:
                    i += 1
                else:
                    in_string = False
            i += 1
            continue

        if char in ("'", '"', "`"):
            in_string = True
            string_char = char
            i += 1
            continue

        if char == "(":
            paren_depth += 1
            i += 1
            continue
        if char == ")":
            if paren_depth > 0:
                paren_depth -= 1
            i += 1
            continue

        if paren_depth == 0:
            # Every operator pattern starts with optional/required whitespace and reports
            # the same operator index from any position inside a whitespace run, so only
            # the run start needs to be tried (mid-run attempts are quadratic).
            if i > 0 and char.isspace() and cond_str[i - 1].isspace():
                i += 1
                continue
            for op, is_symbol, op_pattern in _OPERATOR_MATCHERS:
                matched = False
                match_len = 0
                match_offset = 0

                match = op_pattern.match(cond_str, i)
                if match:
                    if is_symbol:
                        match_offset = match.group(0).index(op)
                        match_len = len(op)
                    else:
                        match_offset = match.start(1) - i
                        match_len = len(match.group(1))
                    matched = True

                if matched:
                    actual_index = i + match_offset
                    left_part = cond_str[:actual_index].strip()
                    if left_part:
                        normalized_op = "!=" if op == "<>" else op
                        return (normalized_op, actual_index, match_len)

        i += 1

    return None


def parse_sql_to_spec(sql: str, dialect: str = "postgres") -> QuerySpec | None:
    """Parses raw SQL query string into a structured QuerySpec dataclass instance."""
    if not sql or not isinstance(sql, str):
        return None

    # Strip SQL comments
    clean_sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    clean_sql = strip_block_comments(clean_sql).strip()

    # Strip trailing semicolons
    clean_sql = strip_trailing_semicolons(clean_sql).strip()
    if not clean_sql:
        return None

    # Must begin with SELECT or WITH
    if not re.match(r"^(SELECT|WITH)\b", clean_sql, re.IGNORECASE):
        return None

    # Reject non-SELECT or destructive statements
    disallow_pattern = re.compile(
        r"\b(UNION|INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|DROP\s+|ALTER\s+|TRUNCATE\s+)\b",
        re.IGNORECASE,
    )
    if disallow_pattern.search(clean_sql):
        return None

    ctes: list[CteSpec] = []
    if re.match(r"^WITH\b", clean_sql, re.IGNORECASE):
        is_recursive = bool(re.match(r"^WITH\s+RECURSIVE\b", clean_sql, re.IGNORECASE))
        with_prefix_match = re.match(
            r"^WITH(?:\s+RECURSIVE)?\s+", clean_sql, re.IGNORECASE
        )
        idx = with_prefix_match.end() if with_prefix_match else 4

        paren_depth = 0
        in_string = False
        string_char = ""
        main_select_index = -1
        c_len = len(clean_sql)

        i = idx
        while i < c_len:
            ch = clean_sql[i]
            if in_string:
                if ch == string_char:
                    if i + 1 < c_len and clean_sql[i + 1] == string_char:
                        i += 2
                        continue
                    in_string = False
                i += 1
                continue
            if ch in ("'", '"', "`"):
                in_string = True
                string_char = ch
                i += 1
                continue
            if ch == "(":
                paren_depth += 1
                i += 1
                continue
            if ch == ")":
                if paren_depth > 0:
                    paren_depth -= 1
                i += 1
                continue
            if paren_depth == 0:
                if _SELECT_WORD_RE.match(clean_sql, i):
                    main_select_index = i
                    break
            i += 1

        if main_select_index != -1:
            with_part = clean_sql[idx:main_select_index].strip()
            clean_sql = clean_sql[main_select_index:].strip()

            raw_cte_defs = split_top_level(with_part, r"^,")
            for def_item in raw_cte_defs:
                text = def_item["value"].strip()
                as_match = _CTE_DEF_RE.match(text)
                if as_match:
                    name = clean_identifier(as_match.group(1))
                    cols = (
                        [
                            clean_identifier(c.strip())
                            for c in as_match.group(2).split(",")
                        ]
                        if as_match.group(2)
                        else []
                    )
                    materialized = (
                        not bool(re.search(r"NOT", as_match.group(3), re.IGNORECASE))
                        if as_match.group(3)
                        else None
                    )
                    query_sql = as_match.group(4).strip()
                    # Recursively parse the inner query if possible, or create minimal wrapper
                    sub_spec = parse_sql_to_spec(query_sql, dialect=dialect)
                    inner_query: Any = (
                        sub_spec if sub_spec is not None else QuerySpec(table=name)
                    )
                    ctes.append(
                        CteSpec(
                            name=name,
                            recursive=is_recursive,
                            columns=cols,
                            materialized=materialized,
                            query=inner_query,
                        )
                    )
                else:
                    first_token = (
                        clean_identifier(text.split()[0]) if text.split() else "cte"
                    )
                    ctes.append(
                        CteSpec(
                            name=first_token,
                            recursive=is_recursive,
                            columns=[],
                            query=QuerySpec(table=first_token),
                        )
                    )
        else:
            return None

    tokens = find_top_level_clauses(clean_sql)
    if not tokens:
        return None

    clause_map: dict[str, str] = {}
    join_clauses: list[dict[str, str]] = []

    for idx, curr in enumerate(tokens):
        next_tok = tokens[idx + 1] if idx + 1 < len(tokens) else None
        start = curr.index + curr.length
        end = next_tok.index if next_tok else len(clean_sql)
        content = clean_sql[start:end].strip()

        if curr.keyword.endswith("JOIN"):
            j_type = "LEFT JOIN" if curr.keyword == "JOIN" else curr.keyword
            join_clauses.append({"type": j_type, "content": content})
        else:
            clause_map[curr.keyword] = content

    # 1. Primary Table (FROM)
    from_content = clause_map.get("FROM")
    if not from_content:
        return None

    from_tokens = from_content.split()
    primary_table = clean_identifier(from_tokens[0])
    if not primary_table:
        return None

    # 2. Projections & DISTINCT (SELECT)
    select_content = clause_map.get("SELECT", "")
    is_distinct = False
    if re.match(r"^DISTINCT\s+", select_content, re.IGNORECASE):
        is_distinct = True
        select_content = re.sub(
            r"^DISTINCT\s+", "", select_content, flags=re.IGNORECASE
        ).strip()

    columns: list[str | dict[str, Any]] = []
    window_functions: list[WindowFunctionSpec] = []

    if not select_content or select_content == "*":
        columns.append("*")
    else:
        raw_items = split_top_level(select_content, r"^,")
        for item in raw_items:
            col_expr = item["value"].strip()

            # Window Function: FUNC(...) OVER (...) [AS alias]
            win_match = _match_window_expr(col_expr)
            if win_match:
                func_name = win_match.func.upper()
                args_str = win_match.args.strip()
                args = (
                    [clean_identifier(a.strip()) for a in args_str.split(",")]
                    if args_str
                    else []
                )
                over_body = win_match.over.strip()
                alias = (
                    clean_identifier(win_match.alias)
                    if win_match.alias
                    else f"{func_name.lower()}_over"
                )

                partition_by: list[str] = []
                p_match = _clause_body(
                    over_body, _PARTITION_BY_RE, _PARTITION_TERMINATOR_RE
                )
                if p_match is not None:
                    partition_by = [
                        clean_identifier(c.strip())
                        for c in p_match.split(",")
                        if c.strip()
                    ]

                order_by_specs: list[OrderBySpec] = []
                o_match = _clause_body(over_body, _ORDER_BY_RE, _ORDER_TERMINATOR_RE)
                if o_match is not None:
                    order_chunks = split_top_level(o_match.strip(), r"^,")
                    for oc in order_chunks:
                        parts = oc["value"].strip().split()
                        col_s = clean_identifier(parts[0])
                        direction = (
                            parts[1].lower()
                            if len(parts) > 1 and parts[1].upper() == "DESC"
                            else "asc"
                        )
                        order_by_specs.append(
                            OrderBySpec(column=col_s, direction=direction)
                        )

                window_functions.append(
                    WindowFunctionSpec(
                        function=func_name,
                        arguments=args,
                        partition_by=partition_by,
                        order_by=order_by_specs,
                        alias=alias,
                    )
                )
                columns.append({"column": alias, "alias": alias})
                continue

            # DATE_TRUNC('month', created_at) [AS alias]
            date_trunc_match = _DATE_TRUNC_RE.match(col_expr)
            if date_trunc_match:
                grain = date_trunc_match.group(1).lower()
                inner_col = clean_identifier(
                    _arg_after_comma(date_trunc_match.group(2))
                )
                alias = (
                    clean_identifier(date_trunc_match.group(3))
                    if date_trunc_match.group(3)
                    else f"{inner_col}_{grain}"
                )
                columns.append(
                    {"column": inner_col, "time_grain": grain, "alias": alias}
                )
                continue

            # DATETRUNC(day, last_login) [AS alias]
            datetrunc_mssql_match = _DATETRUNC_RE.match(col_expr)
            if datetrunc_mssql_match:
                grain = datetrunc_mssql_match.group(1).lower()
                inner_col = clean_identifier(
                    _arg_after_comma(datetrunc_mssql_match.group(2))
                )
                alias = (
                    clean_identifier(datetrunc_mssql_match.group(3))
                    if datetrunc_mssql_match.group(3)
                    else f"{inner_col}_{grain}"
                )
                columns.append(
                    {"column": inner_col, "time_grain": grain, "alias": alias}
                )
                continue

            # Aggregate with FILTER: SUM(orders.amount) FILTER (WHERE orders.status = 'complete') [AS alias]
            filter_agg_match = _FILTER_AGG_RE.match(col_expr)
            if filter_agg_match and not _valid_filter_condition(
                filter_agg_match.group(3)
            ):
                filter_agg_match = None
            if filter_agg_match:
                agg_name = filter_agg_match.group(1).upper()
                inner_col = clean_identifier(_agg_argument(filter_agg_match.group(2)))
                alias = (
                    clean_identifier(filter_agg_match.group(4))
                    if filter_agg_match.group(4)
                    else f"{agg_name.lower()}_{inner_col}"
                )
                columns.append(
                    {
                        "column": inner_col,
                        "agg": agg_name,
                        "metric": alias,
                        "alias": alias,
                    }
                )
                continue

            # Standard aggregate: COUNT(id) AS cnt or COUNT(DISTINCT id)
            agg_match = _AGG_RE.match(col_expr)
            if agg_match:
                agg_name = agg_match.group(1).upper()
                inner_col = clean_identifier(_agg_argument(agg_match.group(2)))
                alias = (
                    clean_identifier(agg_match.group(3)) if agg_match.group(3) else None
                )
                col_obj: dict[str, Any] = {"column": inner_col, "agg": agg_name}
                if alias:
                    col_obj["alias"] = alias
                columns.append(col_obj)
                continue

            # Standard column with optional alias: e.g. users.id AS user_id or users.id
            col_alias_match = re.match(
                r"^([a-zA-Z0-9_\".`\[\]]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$",
                col_expr,
                re.IGNORECASE,
            )
            if col_alias_match and "(" not in col_expr and ")" not in col_expr:
                col_name = clean_identifier(col_alias_match.group(1))
                alias = (
                    clean_identifier(col_alias_match.group(2))
                    if col_alias_match.group(2)
                    else None
                )
                if alias:
                    columns.append({"column": col_name, "alias": alias})
                else:
                    columns.append(col_name)
                continue

            # Complex Raw Expression: CASE WHEN ... or a * b
            as_upper = col_expr.upper()
            as_idx = as_upper.rfind(" AS ")
            if as_idx != -1:
                expr = col_expr[:as_idx].strip()
                alias = clean_identifier(col_expr[as_idx + 4 :].strip())
                columns.append(
                    {
                        "column": expr,
                        "raw_expression": expr,
                        "alias": alias,
                    }
                )
            else:
                columns.append(
                    {
                        "column": col_expr,
                        "raw_expression": col_expr,
                        "alias": clean_identifier(col_expr),
                    }
                )

    # 3. Joins
    joins: list[JoinSpec] = []
    for jc in join_clauses:
        on_idx = jc["content"].upper().find(" ON ")
        if on_idx == -1:
            continue

        table_part = jc["content"][:on_idx].strip()
        on_part = jc["content"][on_idx + 4 :].strip()

        target_table_tokens = table_part.split()
        target_table = clean_identifier(target_table_tokens[0])

        on_match = re.match(
            r"([a-zA-Z0-9_\".`\[\]]+)\s*=\s*([a-zA-Z0-9_\".`\[\]]+)", on_part
        )
        left_table = primary_table
        left_col = "id"
        right_col = "id"

        if on_match:
            left_expr = clean_identifier(on_match.group(1))
            right_expr = clean_identifier(on_match.group(2))

            l_parts = left_expr.split(".")
            r_parts = right_expr.split(".")

            if r_parts[0] == target_table and len(l_parts) > 1:
                left_table = l_parts[0]
                left_col = l_parts[1]
                right_col = r_parts[1]
            elif l_parts[0] == target_table and len(r_parts) > 1:
                left_table = r_parts[0]
                left_col = r_parts[1]
                right_col = l_parts[1]
            else:
                left_col = l_parts[-1]
                right_col = r_parts[-1]

        j_clean_type = jc["type"].upper().replace(" JOIN", "").strip()
        joins.append(
            JoinSpec(
                table=target_table,
                type=j_clean_type,
                left_table=left_table,
                left_col=left_col,
                right_col=right_col,
                on=[
                    {
                        "left": f"{left_table}.{left_col}",
                        "right": f"{target_table}.{right_col}",
                    }
                ],
            )
        )

    # 4. Filters (WHERE)
    filters: list[FilterSpec] = []
    filter_join = "AND"

    where_content = clause_map.get("WHERE")
    if where_content:
        condition_chunks = split_where_conditions(where_content)
        # A filter's combiner is the operator joining it to the PREVIOUS filter
        # (the delimiter that followed the previous chunk); the first is 'AND'.
        prev_delimiter = "AND"
        for chunk in condition_chunks:
            cond_str = chunk["value"].strip()
            combiner = prev_delimiter
            next_delim = str(chunk.get("delimiter") or "AND").upper()
            prev_delimiter = "OR" if next_delim == "OR" else "AND"
            if prev_delimiter == "OR":
                filter_join = "OR"

            found_op = find_top_level_operator(cond_str)
            if found_op:
                matched_op, op_index, op_length = found_op
                col_str = clean_identifier(cond_str[:op_index].strip())
                after_op = cond_str[op_index + op_length :].strip()

                val: Any = ""
                if matched_op in ("IS NULL", "IS NOT NULL"):
                    val = None
                elif matched_op in ("IN", "NOT IN"):
                    val = [
                        parse_literal_value(v.strip())
                        for v in re.sub(r"^\(|\)$", "", after_op).split(",")
                    ]
                elif matched_op == "BETWEEN":
                    val = after_op.strip()
                else:
                    val = parse_literal_value(after_op)

                col_parts = col_str.split(".")
                table_prefix = primary_table
                col_name = col_str
                if len(col_parts) > 1:
                    table_prefix = col_parts[0]
                    col_name = ".".join(col_parts[1:])

                filters.append(
                    FilterSpec(
                        column=col_name,
                        op=matched_op,
                        value=val,
                        table_prefix=table_prefix,
                        combiner=combiner,
                    )
                )
            else:
                filters.append(
                    FilterSpec(
                        column=cond_str,
                        op="RAW",
                        value="",
                        table_prefix=primary_table,
                        combiner=combiner,
                    )
                )

        # Mirror the client contract: per-filter combiners are only emitted once
        # the expression actually mixes in OR.
        if filter_join != "OR":
            for f in filters:
                f.combiner = None

    # 5. Order By
    order_by: list[OrderBySpec] = []
    order_content = clause_map.get("ORDER BY")
    if order_content:
        sort_chunks = split_top_level(order_content, r"^,")
        for sc in sort_chunks:
            parts = sc["value"].strip().split()
            col_str = clean_identifier(parts[0])
            dir_str = (
                parts[1].lower()
                if len(parts) > 1 and parts[1].upper() == "DESC"
                else "asc"
            )

            col_parts = col_str.split(".")
            table_prefix = primary_table
            col_name = col_str
            if len(col_parts) > 1:
                table_prefix = col_parts[0]
                col_name = ".".join(col_parts[1:])

            order_by.append(
                OrderBySpec(
                    column=col_name,
                    direction=dir_str,
                    table_prefix=table_prefix,
                )
            )

    # 6. Pagination (LIMIT & OFFSET)
    limit = 50
    offset = 0

    limit_content = clause_map.get("LIMIT")
    if limit_content:
        l_match = re.match(r"^(\d+)", limit_content)
        if l_match:
            limit = int(l_match.group(1))

    offset_content = clause_map.get("OFFSET")
    if offset_content:
        o_match = re.match(r"^(\d+)", offset_content)
        if o_match:
            offset = int(o_match.group(1))

    return QuerySpec(
        table=primary_table,
        columns=columns,
        joins=joins,
        filters=filters,
        filter_join=filter_join,
        order_by=order_by,
        limit=limit,
        offset=offset,
        distinct=is_distinct,
        ctes=ctes,
        window_functions=window_functions,
    )


def parse_sql_to_dict(sql: str, dialect: str = "postgres") -> dict[str, Any] | None:
    """Convenience function returning dictionary representation of parsed QuerySpec."""
    spec = parse_sql_to_spec(sql, dialect=dialect)
    return spec.to_dict() if spec is not None else None
