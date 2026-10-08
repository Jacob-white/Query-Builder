"""Differential tests for the linear-time regex rewrites.

Every rewritten regex / scanner in ``query_builder`` is compared with a frozen copy of
the ORIGINAL implementation (regexes below are verbatim copies of the pre-rewrite
patterns) in two ways:

* hand-picked tables whose expected values were captured by running the original
  implementation before the rewrite, and
* seeded randomized comparison on thousands of generated strings (hypothesis-style:
  the generators mix structured templates with arbitrary whitespace and noise).

See ``tests/test_regex_linear_timing.py`` for the adversarial linear-time tests.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from typing import Any

import pytest

from query_builder import parser as P
from query_builder._regex_utils import strip_block_comments, strip_trailing_semicolons
from query_builder.ai.byo_provider import _find_json_object_text
from query_builder.connectors.neo4j import _match_simple_select
from query_builder.nlq import providers as NP
from query_builder.pool import mask_credentials
from query_builder.security import URI_CREDENTIAL_REGEX

I = re.IGNORECASE
S = re.DOTALL

# ---------------------------------------------------------------------------------
# Frozen original patterns (verbatim from the code before the rewrite)
# ---------------------------------------------------------------------------------
OLD_CTE = re.compile(
    r"^([a-zA-Z0-9_\"`\[\]]+)(?:\s*\(([^\)]+)\))?\s+AS\s*(?:(MATERIALIZED|NOT\s+MATERIALIZED)\s*)?\(\s*([\s\S]*)\s*\)$",
    I,
)
OLD_WINDOW = re.compile(
    r"^([a-zA-Z0-9_]+)\s*\(\s*(.*?)\s*\)\s+OVER\s*\(\s*(.*?)\s*\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$",
    I | S,
)
OLD_PARTITION = r"\bPARTITION\s+BY\s+([^)]*?)(?=\bORDER\s+BY\b|\bROWS\b|\bRANGE\b|$)"
OLD_ORDER = r"\bORDER\s+BY\s+([^)]*?)(?=\bROWS\b|\bRANGE\b|$)"
OLD_DATE_TRUNC = re.compile(
    r"^DATE_TRUNC\s*\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*,\s*([^\)]+)\s*\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$",
    I,
)
OLD_DATETRUNC = re.compile(
    r"^DATETRUNC\s*\(\s*([a-zA-Z0-9_]+)\s*,\s*([^\)]+)\s*\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$",
    I,
)
OLD_FILTER_AGG = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(?:DISTINCT\s+)?([^\)]+)\s*\)\s+FILTER\s*\(\s*WHERE\s+([^\)]+)\s*\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$",
    I,
)
OLD_AGG = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(?:DISTINCT\s+)?([^\)]+)\s*\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_\"`\[\]]+))?$",
    I,
)
OLD_NEO4J = re.compile(
    r"^SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<from>[^\s]+(?:\s+[^\s]+)?)"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+ORDER\s+BY\s+(?P<order>.+?))?"
    r"(?:\s+SKIP\s+(?P<skip>[^\s]+))?"
    r"(?:\s+LIMIT\s+(?P<limit>[^\s]+))?"
    r"(?:\s+OFFSET\s+(?P<offset>[^\s]+))?$",
    I | S,
)
OLD_COLUMN_PHRASE = re.compile(
    r"\b(?:show|select|find|get)\s+([a-zA-Z0-9_,\s]+?)\s+(?:from|where|order|limit|sorted|$)"
)
OLD_GT = re.compile(r"([a-zA-Z0-9_]+)\s*(?:>|greater than|more than)\s*([0-9]+)")
OLD_LT = re.compile(r"([a-zA-Z0-9_]+)\s*(?:<|less than)\s*([0-9]+)")
OLD_EQ = re.compile(r"([a-zA-Z0-9_]+)\s*(?:=|equals)\s*['\"]?([a-zA-Z0-9_-]+)['\"]?")
OLD_URI_CREDENTIAL = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^/:@]+:)([^@/]+)(@)")
OLD_POOL_URI = re.compile(r"(://[^:]+:)([^@]+)(@)", I)
OLD_BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
OLD_BLOCK_COMMENT_DOTALL = re.compile(r"/\*.*?\*/", S)
OLD_SEMICOLONS = re.compile(r";+\s*$")
OLD_JSON_OBJECT = re.compile(r"\{.*\}", S)

# ---------------------------------------------------------------------------------
# Frozen original functions (verbatim copies from the pre-rewrite parser)
# ---------------------------------------------------------------------------------
ALLOWED_OPERATORS = P.ALLOWED_OPERATORS


def _old_split_where_conditions(text: str) -> list[dict[str, str]]:
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
            rest = text[i:]
            if not in_between and re.match(r"^\bBETWEEN\s+", rest, re.IGNORECASE):
                in_between = True
                i += 7
                continue

            match = re.match(r"^\s+(AND|OR)\s+", rest, re.IGNORECASE)
            if match and match.start() == 0:
                delim = match.group(1).upper()
                if in_between and delim == "AND":
                    in_between = False
                    i += len(match.group(0))
                    continue

                parts.append(
                    {
                        "value": text[last_index:i].strip(),
                        "delimiter": delim,
                    }
                )
                i += len(match.group(0))
                last_index = i
                in_between = False
                continue

        i += 1

    if last_index < text_len:
        val = text[last_index:].strip()
        parts.append({"value": val, "delimiter": ""})

    return [p for p in parts if p["value"]]


def _old_find_top_level_operator(cond_str: str) -> tuple[str, int, int] | None:
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
            rest = cond_str[i:]
            for op in ALLOWED_OPERATORS:
                is_symbol = bool(re.match(r"^[><=!]+$", op))
                matched = False
                match_len = 0
                match_offset = 0

                if is_symbol:
                    match = re.match(r"^\s*(" + re.escape(op) + r")(?![><=])", rest)
                    if match and match.start() == 0:
                        match_offset = match.group(0).index(op)
                        match_len = len(op)
                        matched = True
                else:
                    escaped_op = re.sub(r"\s+", r"\\s+", op)
                    match = re.match(
                        r"^\s+(" + escaped_op + r")(\s+|$)", rest, re.IGNORECASE
                    )
                    if match and match.start() == 0:
                        match_offset = match.start(1)
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


# ---------------------------------------------------------------------------------
# "Views": normalise old and new results to the values the callers actually use
# ---------------------------------------------------------------------------------


def old_cte(text: str) -> Any:
    m = OLD_CTE.match(text)
    return None if m is None else (*m.groups()[:3], m.group(4).strip())


def new_cte(text: str) -> Any:
    m = P._CTE_DEF_RE.match(text)
    return None if m is None else (*m.groups()[:3], m.group(4).strip())


def old_window(text: str) -> Any:
    m = OLD_WINDOW.match(text)
    if m is None:
        return None
    return (m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4))


def new_window(text: str) -> Any:
    m = P._match_window_expr(text)
    if m is None:
        return None
    return (m.func, m.args.strip(), m.over.strip(), m.alias)


def old_partition(text: str) -> Any:
    m = re.search(OLD_PARTITION, text, I)
    return None if m is None else m.group(1)


def new_partition(text: str) -> Any:
    return P._clause_body(text, P._PARTITION_BY_RE, P._PARTITION_TERMINATOR_RE)


def old_order(text: str) -> Any:
    m = re.search(OLD_ORDER, text, I)
    return None if m is None else m.group(1)


def new_order(text: str) -> Any:
    return P._clause_body(text, P._ORDER_BY_RE, P._ORDER_TERMINATOR_RE)


def old_date_trunc(text: str) -> Any:
    m = OLD_DATE_TRUNC.match(text)
    return None if m is None else m.groups()


def new_date_trunc(text: str) -> Any:
    m = P._DATE_TRUNC_RE.match(text)
    if m is None:
        return None
    return (m.group(1), P._arg_after_comma(m.group(2)), m.group(3))


def old_datetrunc(text: str) -> Any:
    m = OLD_DATETRUNC.match(text)
    return None if m is None else m.groups()


def new_datetrunc(text: str) -> Any:
    m = P._DATETRUNC_RE.match(text)
    if m is None:
        return None
    return (m.group(1), P._arg_after_comma(m.group(2)), m.group(3))


def old_filter_agg(text: str) -> Any:
    m = OLD_FILTER_AGG.match(text)
    if m is None:
        return None
    # group 3 (the condition) is never read by the parser; only its existence matters
    return (m.group(1), m.group(2), m.group(4))


def new_filter_agg(text: str) -> Any:
    m = P._FILTER_AGG_RE.match(text)
    if m is None or not P._valid_filter_condition(m.group(3)):
        return None
    return (m.group(1), P._agg_argument(m.group(2)), m.group(4))


def old_agg(text: str) -> Any:
    m = OLD_AGG.match(text)
    return None if m is None else m.groups()


def new_agg(text: str) -> Any:
    m = P._AGG_RE.match(text)
    if m is None:
        return None
    return (m.group(1), P._agg_argument(m.group(2)), m.group(3))


def old_neo4j(text: str) -> Any:
    m = OLD_NEO4J.match(text)
    if m is None:
        return None
    return _neo4j_view(
        m.group("select"),
        m.group("from"),
        m.group("where"),
        m.group("order"),
        m.group("skip"),
        m.group("limit"),
        m.group("offset"),
    )


def new_neo4j(text: str) -> Any:
    m = _match_simple_select(text)
    if m is None:
        return None
    return _neo4j_view(m.select, m.from_, m.where, m.order, m.skip, m.limit, m.offset)


def _neo4j_view(sel, frm, where, order, skip, limit, offset) -> Any:
    """What ``_Neo4jCursorAdapter.execute`` reads: stripped text + truthiness."""

    def free(group: str | None) -> Any:
        return None if group is None else (bool(group), group.strip())

    # the cursor applies .split() to ``from`` and uses skip/limit/offset verbatim
    return (sel.strip(), frm.split(), free(where), free(order), skip, limit, offset)


def old_column_phrase(text: str) -> Any:
    m = OLD_COLUMN_PHRASE.search(text)
    return None if m is None else m.group(1).strip()


def old_filter(pattern: re.Pattern[str], text: str) -> Any:
    m = pattern.search(text)
    return None if m is None else m.groups()


def new_filter(pattern: re.Pattern[str], text: str) -> Any:
    m = pattern.search(text)
    return None if m is None else m.groups()


def old_json_object(text: str) -> Any:
    m = OLD_JSON_OBJECT.search(text)
    return None if m is None else m.group(0)


# ---------------------------------------------------------------------------------
# Random generators
# ---------------------------------------------------------------------------------
WS = ["", " ", "  ", "   ", "    ", "\t", "\n", " \n\t ", "      ", "\r\n"]


class Gen:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def ws(self) -> str:
        return self.rng.choice(WS)

    def ws1(self) -> str:
        return self.rng.choice(WS[1:])

    def pick(self, *options: str) -> str:
        return self.rng.choice(options)

    def noise(self, atoms: list[str], low: int = 1, high: int = 10) -> str:
        return "".join(
            self.rng.choice(atoms) for _ in range(self.rng.randint(low, high))
        )

    def alias(self) -> str:
        return self.pick(
            "",
            "",
            self.ws1() + "x",
            self.ws1() + "AS" + self.ws1() + "x",
            self.ws1() + "AS" + self.ws(),
            self.ws1() + '"y"',
            self.ws1() + "as" + self.ws1() + "AS",
            self.ws1() + "z" + self.ws1() + "w",
        )


SQL_ATOMS = [
    "(",
    ")",
    ",",
    " ",
    "  ",
    "\n",
    "\t",
    "   ",
    "AS",
    "OVER",
    "FILTER",
    "WHERE",
    "DISTINCT",
    "PARTITION BY",
    "ORDER BY",
    "ROWS",
    "RANGE",
    "a",
    "b.c",
    "x",
    "'month'",
    "COUNT",
    "SUM",
    "MATERIALIZED",
    "NOT",
    "=",
    "1",
]


def gen_window(g: Gen) -> str:
    if g.rng.random() < 0.25:
        return g.noise(SQL_ATOMS, 2, 14)
    body = g.pick(
        "",
        "PARTITION BY a",
        "PARTITION BY a, b ORDER BY c DESC",
        "ORDER BY b",
        "ORDER BY b ROWS 1",
        "PARTITION BY x" + g.ws() + ")" + g.ws() + "ORDER BY y",
        "PARTITION BY a " * g.rng.randint(1, 3) + ")",
        "ORDER BY a RANGE x",
        "partition by a order by b",
        "PARTITION BY a" + g.ws1(),
    )
    args = g.pick("", "a", "a, b", "a)", "f(a)", ")")
    return (
        f"{g.pick('ROW_NUMBER', 'SUM', 'rank')}{g.ws()}({g.ws()}{args}{g.ws()})"
        f"{g.ws1()}OVER{g.ws()}({g.ws()}{body}{g.ws()}){g.alias()}"
        + g.pick("", "", ")", " OVER (x)", "\n")
    )


def gen_trunc(g: Gen) -> str:
    if g.rng.random() < 0.2:
        return g.noise(SQL_ATOMS, 2, 14)
    arg = g.pick("c", "t.c", " ", "", "a b", "c)", "  c  ", ")")
    if g.rng.random() < 0.5:
        return (
            f"{g.pick('DATE_TRUNC', 'date_trunc')}{g.ws()}({g.ws()}"
            f"{g.pick(chr(39), chr(34))}{g.pick('month', 'd')}{g.pick(chr(39), chr(34))}"
            f"{g.ws()},{g.ws()}{arg}{g.ws()}){g.alias()}"
        )
    return (
        f"DATETRUNC{g.ws()}({g.ws()}{g.pick('day', 'm')}{g.ws()},{g.ws()}{arg}"
        f"{g.ws()}){g.alias()}"
    )


def gen_agg(g: Gen) -> str:
    if g.rng.random() < 0.2:
        return g.noise(SQL_ATOMS, 2, 14)
    distinct = g.pick("", "", "DISTINCT" + g.ws1(), "DISTINCT" + g.ws(), "distinct ")
    arg = g.pick("a", "t.a", "*", "", "DISTINCT", " ", "a b", "(", "a,b")
    head = f"{g.pick('COUNT', 'sum', 'AVG', 'MIN', 'max')}{g.ws()}({g.ws()}{distinct}{arg}{g.ws()})"
    if g.rng.random() < 0.5:
        cond = g.pick("a = 1", "", " ", "x", "a)", "  ", "a = 'b'")
        head += (
            f"{g.ws1()}FILTER{g.ws()}({g.ws()}WHERE{g.pick('', ' ', '  ', chr(9), g.ws())}"
            f"{cond}{g.ws()})"
        )
    return head + g.alias() + g.pick("", "", ")", "\n")


def gen_cte(g: Gen) -> str:
    if g.rng.random() < 0.2:
        return g.noise(SQL_ATOMS, 2, 14)
    cols = g.pick("", g.ws() + "(a, b)", g.ws() + "(a)", g.ws() + "()", g.ws() + "(a")
    mat = g.pick("", "MATERIALIZED", "NOT" + g.ws1() + "MATERIALIZED", "NOT")
    return (
        f"{g.pick('c', 'cte_1', '[x]', 'a.b')}{cols}{g.ws1()}AS{g.ws()}{mat}{g.ws()}"
        f"({g.ws()}{g.pick('SELECT a FROM t', '', ' ', 'x (y) z', '(')}{g.ws()})"
        + g.pick("", "", " ", "\n", ")", "x")
    )


def gen_neo4j(g: Gen) -> str:
    if g.rng.random() < 0.15:
        return g.noise(
            ["SELECT", "FROM", "WHERE", "ORDER BY", "SKIP", "LIMIT", "OFFSET"]
            + ["a", "b", "t", "1", " ", "  ", "   ", "    ", "\n", "x.y", "`t`"],
            2,
            16,
        )
    sel = g.pick("*", "a", "a, b", "count(*)", "FROM", "a FROM b", " ", "WHERE x")
    frm = g.pick("t", "`t`", "t u", "t WHERE", "t ORDER", "FROM", "t u v")
    out = f"{g.pick('SELECT', 'select')}{g.ws1()}{sel}{g.ws1()}{g.pick('FROM', 'from')}{g.ws1()}{frm}"
    if g.rng.random() < 0.5:
        out += f"{g.ws1()}WHERE{g.ws1()}{g.pick('a = 1', 'x', ' ', 'a  =  b', 'ORDER BY z')}"
    if g.rng.random() < 0.4:
        out += (
            f"{g.ws1()}ORDER{g.ws1()}BY{g.ws1()}{g.pick('a', 'a DESC', ' ', 'a  ,  b')}"
        )
    for kw in ("SKIP", "LIMIT", "OFFSET"):
        if g.rng.random() < 0.25:
            out += f"{g.ws1()}{kw}{g.ws1()}{g.pick('5', '10', 'x')}"
    if g.rng.random() < 0.3:
        out += g.pick(" extra", "\n", g.ws1() + "WHERE", "  x  y")
    return out


COLUMN_ATOMS = [
    "show",
    "select",
    "find",
    "get",
    "from",
    "where",
    "order",
    "limit",
    "sorted",
    "a",
    "b,c",
    "all",
    "name",
    ",",
    " ",
    "  ",
    "   ",
    "    ",
    "\n",
    "\t",
    "-",
    "!",
    "fromage",
    "target",
    "x_1",
    "9",
    "SHOW",
    "\n\n",
]


def gen_column_phrase(g: Gen) -> str:
    if g.rng.random() < 0.5:
        return g.noise(COLUMN_ATOMS, 1, 14)
    cols = g.pick("name, age", "a", "all", "x_1,y", "a  b", "-", "!", "a-b", "", "  ")
    end = g.pick(
        "from users",
        "where x",
        "order by a",
        "limit 5",
        "sorted by a",
        "",
        "\n",
        "fromage",
        "-",
        "show a from b",
    )
    return (
        g.pick("", "please ", "x")
        + f"{g.pick('show', 'select', 'find', 'get')}{g.ws1()}{cols}{g.ws()}{end}"
        + g.pick("", "", " get all from t", g.ws1())
    )


FILTER_ATOMS = [
    "a",
    "xyz",
    "_",
    "1",
    "9",
    ">",
    "<",
    "=",
    " ",
    "  ",
    "\n",
    "greater than",
    "more than",
    "less than",
    "equals",
    "'",
    '"',
    "-",
    "greater",
    "than",
    "!",
]


def gen_filter(g: Gen) -> str:
    return g.noise(FILTER_ATOMS, 1, 14)


URI_ATOMS = [
    "a",
    "B",
    "1",
    "+",
    ".",
    "-",
    "http",
    "postgres",
    "://",
    ":",
    "@",
    "/",
    "user",
    "pw",
    " ",
    "x",
    "9p",
    "://u:p@",
    "s3",
    "\n",
]


def gen_uri(g: Gen) -> str:
    if g.rng.random() < 0.4:
        return g.noise(URI_ATOMS, 1, 16)
    return (
        g.pick("", "1", "+-", "9a.", "x ")
        + g.pick("postgres", "http", "a", "A1+.-b", "s3")
        + g.pick("://", "://", ":/", "//")
        + g.pick("u", "us er", "u@x", "", "u/v")
        + g.pick(":", ":", "::", "")
        + g.pick("p", "p w", "", "@", "p@", "p/q")
        + g.pick("@", "@", "")
        + g.pick("host", "h:5432/db", " tail ://x:y@z", "@@", "")
    )


def gen_json(g: Gen) -> str:
    return g.noise(["{", "}", "a", " ", '"k"', ":", "1", "\n", "{}", "}{"], 0, 14)


COMMENT_ATOMS = ["/*", "*/", "/", "*", "a", " ", "\n", "/**/", "--", "x", "*/*"]


def gen_comment(g: Gen) -> str:
    return g.noise(COMMENT_ATOMS, 0, 16)


SEMI_ATOMS = [";", ";;", " ", "\n", "\t", "a", "b ", "'", ";\n", "  ", ";  ;"]


def gen_semi(g: Gen) -> str:
    return g.noise(SEMI_ATOMS, 0, 12)


COND_ATOMS = [
    "a",
    "b.c",
    "'x'",
    "(a)",
    "(a AND b)",
    " ",
    "  ",
    "\n",
    "\t",
    "   ",
    "=",
    ">=",
    "<=",
    "<>",
    "!=",
    ">",
    "<",
    "IN",
    "NOT IN",
    "IS NULL",
    "IS NOT NULL",
    "IS  NOT   NULL",
    "LIKE",
    "ILIKE",
    "BETWEEN",
    "AND",
    "OR",
    "NOT",
    "1",
    "(1, 2)",
    "'a b'",
    "x",
]


def gen_cond(g: Gen) -> str:
    return g.noise(COND_ATOMS, 1, 14)


def gen_cond_structured(g: Gen) -> str:
    parts = []
    for _ in range(g.rng.randint(1, 3)):
        parts.append(
            g.pick("a", "a.b", "(a)", "'x y'", "f(a, b)")
            + g.ws()
            + g.pick("=", ">=", "<>", "!=", "IN", "NOT IN", "IS NULL", "LIKE", "<", "")
            + g.ws()
            + g.pick("1", "'x'", "(1,2)", "b", "")
        )
    seps = [g.ws1() + g.pick("AND", "OR", "and", "BETWEEN") + g.ws1() for _ in parts]
    return "".join(p + s for p, s in zip(parts, seps, strict=False)) + g.pick("", "x")


# ---------------------------------------------------------------------------------
# Randomized differential tests
# ---------------------------------------------------------------------------------
N = 4000


def _compare(
    gen: Callable[[Gen], str],
    old: Callable[[str], Any],
    new: Callable[[str], Any],
    seed: int,
    min_matches: int,
) -> None:
    g = Gen(seed)
    matches = 0
    for _ in range(N):
        text = gen(g)
        expected = old(text)
        assert new(text) == expected, text
        if expected is not None:
            matches += 1
    assert matches >= min_matches, f"generator rarely matched ({matches})"


def test_random_cte_definition() -> None:
    _compare(gen_cte, old_cte, new_cte, 11, 500)


def test_random_window_expression() -> None:
    _compare(gen_window, old_window, new_window, 12, 500)


def test_random_partition_clause() -> None:
    def gen(g: Gen) -> str:
        if g.rng.random() < 0.5:
            return g.noise(SQL_ATOMS + ["PARTITION BY ", "ORDER BY "], 1, 14)
        return (
            g.pick("", "x ", ")")
            + "PARTITION"
            + g.ws1()
            + "BY"
            + g.ws1()
            + g.pick("a", "a, b", "", "a)", "a ORDER BY b", "a ROWS 1", "a\n")
            + g.pick("", g.ws1() + "ORDER BY b", ")", "\n", g.ws1() + "RANGE x")
            + g.pick("", " PARTITION BY c", ") PARTITION BY d", "\n")
        )

    _compare(gen, old_partition, new_partition, 13, 500)


def test_random_order_clause() -> None:
    def gen(g: Gen) -> str:
        if g.rng.random() < 0.5:
            return g.noise(SQL_ATOMS + ["ORDER BY ", "ROWS ", "RANGE "], 1, 14)
        return (
            g.pick("", "x ", ")")
            + "ORDER"
            + g.ws1()
            + "BY"
            + g.ws1()
            + g.pick("a", "a DESC", "", "a)", "a ROWS 1", "a\n")
            + g.pick("", g.ws1() + "RANGE", ")", "\n", g.ws1() + "ROWS x")
            + g.pick("", " ORDER BY c", ") ORDER BY d", "\n")
        )

    _compare(gen, old_order, new_order, 14, 500)


def test_random_date_trunc() -> None:
    def gen(g: Gen) -> str:
        return gen_trunc(g)

    _compare(gen, old_date_trunc, new_date_trunc, 15, 200)
    _compare(gen, old_datetrunc, new_datetrunc, 16, 200)


def test_random_aggregates() -> None:
    _compare(gen_agg, old_agg, new_agg, 17, 300)
    _compare(gen_agg, old_filter_agg, new_filter_agg, 18, 300)


def test_random_neo4j_select() -> None:
    _compare(gen_neo4j, old_neo4j, new_neo4j, 19, 1000)


def test_random_column_phrase() -> None:
    _compare(
        gen_column_phrase,
        old_column_phrase,
        NP._match_column_phrase,
        20,
        500,
    )


@pytest.mark.parametrize(
    ("old", "new", "seed"),
    [
        (OLD_GT, NP._GT_FILTER_RE, 21),
        (OLD_LT, NP._LT_FILTER_RE, 22),
        (OLD_EQ, NP._EQ_FILTER_RE, 23),
    ],
)
def test_random_nlq_filter_patterns(
    old: re.Pattern[str], new: re.Pattern[str], seed: int
) -> None:
    _compare(
        gen_filter,
        lambda t: old_filter(old, t),
        lambda t: new_filter(new, t),
        seed,
        100,
    )
    # word-structured: leftmost match must start at a word start with the same groups
    g = Gen(seed + 100)
    words = ["xgreater", "a", "b2", "limit", "than", "greater", "5", "x"]
    ops = ["", ">", " > ", "greater than", " less than ", "=", " equals ", "<"]
    for _ in range(N):
        text = "".join(
            g.pick(*words) + g.pick(*ops) + g.pick(*WS, "'", '"') for _ in range(4)
        )
        assert old_filter(old, text) == new_filter(new, text), text


def test_random_uri_credentials() -> None:
    g = Gen(24)
    hits = 0
    for _ in range(N):
        text = gen_uri(g)
        expected = OLD_URI_CREDENTIAL.sub(r"\g<1>***\g<3>", text)
        assert URI_CREDENTIAL_REGEX.sub(r"\g<1>***\g<3>", text) == expected, text
        hits += expected != text
    assert hits >= 300


def test_random_pool_mask_credentials() -> None:
    g = Gen(25)
    hits = 0
    for _ in range(N):
        text = gen_uri(g)
        expected = OLD_POOL_URI.sub(r"\1***\3", text)
        assert mask_credentials(text) == expected, text
        hits += expected != text
    assert hits >= 300


def test_random_json_object_span() -> None:
    g = Gen(26)
    for _ in range(N):
        text = gen_json(g)
        assert _find_json_object_text(text) == old_json_object(text), text


def test_random_block_comments() -> None:
    g = Gen(27)
    for _ in range(N):
        text = gen_comment(g)
        expected = OLD_BLOCK_COMMENT.sub("", text)
        assert strip_block_comments(text) == expected, text
        assert expected == OLD_BLOCK_COMMENT_DOTALL.sub("", text)


def test_random_trailing_semicolons() -> None:
    g = Gen(28)
    for _ in range(N):
        text = gen_semi(g)
        assert strip_trailing_semicolons(text) == OLD_SEMICOLONS.sub("", text), text


def test_random_split_where_conditions() -> None:
    g = Gen(29)
    for i in range(N):
        text = gen_cond(g) if i % 2 else gen_cond_structured(g)
        assert P.split_where_conditions(text) == _old_split_where_conditions(text), text


def test_random_find_top_level_operator() -> None:
    g = Gen(30)
    found = 0
    for i in range(N):
        text = gen_cond(g) if i % 2 else gen_cond_structured(g)
        expected = _old_find_top_level_operator(text)
        assert P.find_top_level_operator(text) == expected, text
        found += expected is not None
    assert found >= 500


PARSE_TABLE = [
    (
        "SELECT ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn, name FROM "
        "emp",
        {
            "columns": [{"alias": "rn", "column": "rn"}, "name"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "emp",
            "window_functions": [
                {
                    "alias": "rn",
                    "arguments": [],
                    "function": "ROW_NUMBER",
                    "order_by": [{"column": "salary", "direction": "desc"}],
                    "partition_by": ["dept"],
                }
            ],
        },
    ),
    (
        "SELECT SUM(amount) OVER (ORDER BY ts) total, id FROM t",
        {
            "columns": [{"alias": "total", "column": "total"}, "id"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
            "window_functions": [
                {
                    "alias": "total",
                    "arguments": ["amount"],
                    "function": "SUM",
                    "order_by": [{"column": "ts", "direction": "asc"}],
                    "partition_by": [],
                }
            ],
        },
    ),
    (
        "SELECT rank ( ) OVER ( PARTITION BY a , b ORDER BY c ROWS 1 ) AS r FROM t",
        {
            "columns": [{"alias": "r", "column": "r"}],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
            "window_functions": [
                {
                    "alias": "r",
                    "arguments": [],
                    "function": "RANK",
                    "order_by": [{"column": "c", "direction": "asc"}],
                    "partition_by": ["a", "b"],
                }
            ],
        },
    ),
    (
        "SELECT DATE_TRUNC('month', created_at) AS m, COUNT(*) AS n FROM orders",
        {
            "columns": [
                {"alias": "m", "column": "created_at", "time_grain": "month"},
                {"agg": "COUNT", "alias": "n", "column": "*"},
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "orders",
        },
    ),
    (
        "SELECT DATETRUNC( day , last_login ) d FROM users",
        {
            "columns": [{"alias": "d", "column": "last_login", "time_grain": "day"}],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "users",
        },
    ),
    (
        "SELECT DATE_TRUNC('month',  created_at   ) FROM t",
        {
            "columns": [
                {
                    "alias": "created_at_month",
                    "column": "created_at",
                    "time_grain": "month",
                }
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT COUNT(DISTINCT user_id) AS u, SUM( amount ) FROM orders",
        {
            "columns": [
                {"agg": "COUNT", "alias": "u", "column": "user_id"},
                {"agg": "SUM", "column": "amount"},
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "orders",
        },
    ),
    (
        "SELECT COUNT( DISTINCT  ) FROM t",
        {
            "columns": [{"agg": "COUNT", "column": ""}],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT SUM(orders.amount) FILTER (WHERE orders.status = 'complete') AS done FROM "
        "orders",
        {
            "columns": [
                {
                    "agg": "SUM",
                    "alias": "done",
                    "column": "orders.amount",
                    "metric": "done",
                }
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "orders",
        },
    ),
    (
        "SELECT COUNT(*) FILTER (WHERE x) c FROM t",
        {
            "columns": [{"agg": "COUNT", "alias": "c", "column": "*", "metric": "c"}],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT COUNT(*) FILTER (WHERE ) c FROM t",
        {
            "columns": [
                {
                    "alias": "COUNT(*) FILTER (WHERE ) c",
                    "column": "COUNT(*) FILTER (WHERE ) c",
                    "raw_expression": "COUNT(*) FILTER (WHERE ) c",
                }
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT COUNT(*) FILTER (WHEREx) c FROM t",
        {
            "columns": [
                {
                    "alias": "COUNT(*) FILTER (WHEREx) c",
                    "column": "COUNT(*) FILTER (WHEREx) c",
                    "raw_expression": "COUNT(*) FILTER (WHEREx) c",
                }
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "WITH a AS (SELECT id FROM t), b (x, y) AS MATERIALIZED (SELECT 1 FROM u) SELECT id "
        "FROM a",
        {
            "columns": ["id"],
            "ctes": [
                {
                    "columns": [],
                    "name": "a",
                    "query": {
                        "columns": ["id"],
                        "distinct": False,
                        "filter_join": "AND",
                        "filters": [],
                        "having": [],
                        "joins": [],
                        "limit": 50,
                        "offset": 0,
                        "order_by": [],
                        "table": "t",
                    },
                    "recursive": False,
                },
                {
                    "columns": ["x", "y"],
                    "materialized": True,
                    "name": "b",
                    "query": {
                        "columns": ["1"],
                        "distinct": False,
                        "filter_join": "AND",
                        "filters": [],
                        "having": [],
                        "joins": [],
                        "limit": 50,
                        "offset": 0,
                        "order_by": [],
                        "table": "u",
                    },
                    "recursive": False,
                },
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "a",
        },
    ),
    (
        "WITH RECURSIVE c AS NOT MATERIALIZED ( SELECT n FROM seq ) SELECT n FROM c",
        {
            "columns": ["n"],
            "ctes": [
                {
                    "columns": [],
                    "materialized": False,
                    "name": "c",
                    "query": {
                        "columns": ["n"],
                        "distinct": False,
                        "filter_join": "AND",
                        "filters": [],
                        "having": [],
                        "joins": [],
                        "limit": 50,
                        "offset": 0,
                        "order_by": [],
                        "table": "seq",
                    },
                    "recursive": True,
                }
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "c",
        },
    ),
    (
        "SELECT a FROM t WHERE a = 1 AND b   IS   NOT NULL OR c BETWEEN 1 AND 2",
        {
            "columns": ["a"],
            "distinct": False,
            "filter_join": "OR",
            "filters": [
                {
                    "column": "a",
                    "combiner": "AND",
                    "op": "=",
                    "table_prefix": "t",
                    "value": 1,
                },
                {
                    "column": "b",
                    "combiner": "AND",
                    "op": "IS NOT NULL",
                    "table_prefix": "t",
                    "value": None,
                },
                {
                    "column": "c",
                    "combiner": "OR",
                    "op": "BETWEEN",
                    "table_prefix": "t",
                    "value": "1 AND 2",
                },
            ],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT a FROM t WHERE a  >=  1   AND   b NOT   IN (1,2)",
        {
            "columns": ["a"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [
                {"column": "a", "op": ">=", "table_prefix": "t", "value": 1},
                {"column": "b", "op": "NOT IN", "table_prefix": "t", "value": [1, 2]},
            ],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT a FROM t WHERE x LIKE 'a%'    ",
        {
            "columns": ["a"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [
                {"column": "x", "op": "LIKE", "table_prefix": "t", "value": "a%"}
            ],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT a FROM t;;  ",
        {
            "columns": ["a"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT a /* c */ FROM t -- tail",
        {
            "columns": ["a"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    (
        "SELECT a /* unterminated FROM t",
        {
            "columns": [
                {
                    "alias": "a /* unterminated",
                    "column": "a /* unterminated",
                    "raw_expression": "a /* unterminated",
                }
            ],
            "distinct": False,
            "filter_join": "AND",
            "filters": [],
            "having": [],
            "joins": [],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
    ("SELECT 0 AS( FROM t", None),
    (
        "SELECT a FROM t JOIN u ON t.id = u.t_id WHERE t.x = 1",
        {
            "columns": ["a"],
            "distinct": False,
            "filter_join": "AND",
            "filters": [{"column": "x", "op": "=", "table_prefix": "t", "value": 1}],
            "having": [],
            "joins": [
                {
                    "left_col": "id",
                    "left_table": "t",
                    "on": [{"left": "t.id", "right": "u.t_id"}],
                    "right_col": "t_id",
                    "table": "u",
                    "type": "LEFT",
                }
            ],
            "limit": 50,
            "offset": 0,
            "order_by": [],
            "table": "t",
        },
    ),
]

CTE_TABLE = [
    ("c AS (SELECT 1)", ("c", None, None, "SELECT 1")),
    ("c AS ( SELECT 1 )", ("c", None, None, "SELECT 1")),
    (
        "c (a, b) AS MATERIALIZED (SELECT a, b FROM t)",
        ("c", "a, b", "MATERIALIZED", "SELECT a, b FROM t"),
    ),
    ("c AS NOT MATERIALIZED(x)", ("c", None, "NOT MATERIALIZED", "x")),
    ("c AS ()", ("c", None, None, "")),
    ("c AS (", None),
    ("c AS", None),
    ("[x] AS (select (1))", ("[x]", None, None, "select (1)")),
    ("c  AS  (  )  ", None),
    ("c AS (SELECT 1) x", None),
    ("0 AS(     ", None),
    ("c AS (\n SELECT 1 \n)", ("c", None, None, "SELECT 1")),
]

WINDOW_TABLE = [
    (
        "ROW_NUMBER() OVER (PARTITION BY a ORDER BY b)",
        ("ROW_NUMBER", "", "PARTITION BY a ORDER BY b", None),
    ),
    ("SUM( a ) OVER ( ORDER BY b ) AS s", ("SUM", "a", "ORDER BY b", "s")),
    ("SUM(a) OVER (b) c d", None),
    ("f(a) OVER (x) OVER (y)", ("f", "a", "x) OVER (y", None)),
    ("f(a) OVER (x) ) y", ("f", "a", "x)", "y")),
    ("f(a) OVER (x", None),
    ("f(a)) OVER (x)", ("f", "a)", "x", None)),
    ("rank()   OVER   (  )  alias", ("rank", "", "", "alias")),
    ("f() OVER (a)  AS", ("f", "", "a", "AS")),
    ("f(a) OVER (\n PARTITION BY a\n)", ("f", "a", "PARTITION BY a", None)),
    ("f(a OVER (x)", None),
]

PARTITION_TABLE = [
    ("PARTITION BY a ORDER BY b", "a "),
    ("PARTITION BY a, b", "a, b"),
    ("PARTITION BY a ROWS 1", "a "),
    ("partition   by  a ) PARTITION BY b ORDER BY c", "b "),
    ("PARTITION BY", None),
    ("PARTITION BY \n", ""),
    ("x PARTITION BY a\n", "a"),
    ("PARTITION BY a ) PARTITION BY b", "b"),
    ("ORDER BY a", None),
]

ORDER_TABLE = [
    ("ORDER BY b DESC", "b DESC"),
    ("ORDER BY b ROWS 1", "b "),
    ("ORDER BY b RANGE x", "b "),
    ("order  by a) ORDER BY c", "c"),
    ("PARTITION BY a ORDER BY b", "b"),
    ("ORDER BY \n", ""),
    ("ORDER BY a)", None),
]

DATE_TRUNC_TABLE = [
    ("DATE_TRUNC('month', c)", ("month", "c", None)),
    ('DATE_TRUNC("d"  ,  c  ) AS x', ("d", "c  ", "x")),
    ("DATE_TRUNC('m',   )", ("m", " ", None)),
    ("DATE_TRUNC('m', ) x", ("m", " ", "x")),
    ("DATE_TRUNC('m',)", None),
    ("DATE_TRUNC('m', a b) y z", None),
    ("DATETRUNC(day, c)", None),
    ("DATETRUNC( day , c ) AS d", None),
    ("DATETRUNC(day,  )", None),
    ("DATETRUNC(day,)", None),
    ("DATETRUNC(day, c", None),
]

DATETRUNC_TABLE = [
    ("DATE_TRUNC('month', c)", None),
    ('DATE_TRUNC("d"  ,  c  ) AS x', None),
    ("DATE_TRUNC('m',   )", None),
    ("DATE_TRUNC('m', ) x", None),
    ("DATE_TRUNC('m',)", None),
    ("DATE_TRUNC('m', a b) y z", None),
    ("DATETRUNC(day, c)", ("day", "c", None)),
    ("DATETRUNC( day , c ) AS d", ("day", "c ", "d")),
    ("DATETRUNC(day,  )", ("day", " ", None)),
    ("DATETRUNC(day,)", None),
    ("DATETRUNC(day, c", None),
]

AGG_TABLE = [
    ("COUNT(*)", ("COUNT", "*", None)),
    ("COUNT( DISTINCT a ) AS n", ("COUNT", "a ", "n")),
    ("sum(DISTINCT   )", ("sum", " ", None)),
    ("SUM( DISTINCT  )", ("SUM", " ", None)),
    ("COUNT(  )", ("COUNT", " ", None)),
    ("COUNT()", None),
    ("MIN( DISTINCTx )", ("MIN", "DISTINCTx ", None)),
    ("AVG(a) b c", None),
    ("MAX(a b)", ("MAX", "a b", None)),
    ("SUM(a) FILTER (WHERE a = 1)", None),
    ("SUM(a) FILTER (WHERE a = 1) AS s", None),
    ("SUM(DISTINCT a) FILTER ( WHERE  x ) y", None),
    ("COUNT(*) FILTER (WHERE )", None),
    ("COUNT(*) FILTER (WHERE  )", None),
    ("COUNT(*) FILTER (WHEREx)", None),
    ("COUNT(*) FILTER (WHERE x", None),
]

FILTER_AGG_TABLE = [
    ("COUNT(*)", None),
    ("COUNT( DISTINCT a ) AS n", None),
    ("sum(DISTINCT   )", None),
    ("SUM( DISTINCT  )", None),
    ("COUNT(  )", None),
    ("COUNT()", None),
    ("MIN( DISTINCTx )", None),
    ("AVG(a) b c", None),
    ("MAX(a b)", None),
    ("SUM(a) FILTER (WHERE a = 1)", ("SUM", "a", None)),
    ("SUM(a) FILTER (WHERE a = 1) AS s", ("SUM", "a", "s")),
    ("SUM(DISTINCT a) FILTER ( WHERE  x ) y", ("SUM", "a", "y")),
    ("COUNT(*) FILTER (WHERE )", None),
    ("COUNT(*) FILTER (WHERE  )", ("COUNT", "*", None)),
    ("COUNT(*) FILTER (WHEREx)", None),
    ("COUNT(*) FILTER (WHERE x", None),
]

NEO4J_TABLE = [
    ("SELECT * FROM t", ("*", ["t"], None, None, None, None, None)),
    (
        "SELECT a, b FROM `t` u WHERE a = 1 ORDER BY b DESC SKIP 5 LIMIT 10",
        ("a, b", ["`t`", "u"], (True, "a = 1"), (True, "b DESC"), "5", "10", None),
    ),
    (
        "SELECT a FROM t WHERE   a   =   1",
        ("a", ["t"], (True, "a   =   1"), None, None, None, None),
    ),
    (
        "SELECT a FROM t WHERE x ORDER BY y OFFSET 3",
        ("a", ["t"], (True, "x"), (True, "y"), None, None, "3"),
    ),
    ("SELECT   FROM t", ("", ["t"], None, None, None, None, None)),
    ("SELECT    FROM t", ("", ["t"], None, None, None, None, None)),
    (
        "SELECT a FROM t WHERE   ORDER BY b",
        ("a", ["t", "WHERE"], None, (True, "b"), None, None, None),
    ),
    (
        "SELECT a FROM t WHERE    ORDER BY b",
        ("a", ["t", "WHERE"], None, (True, "b"), None, None, None),
    ),
    ("SELECT a FROM t u v", None),
    ("SELECT FROM FROM t", ("FROM", ["t"], None, None, None, None, None)),
    ("SELECT a FROM t WHERE", ("a", ["t", "WHERE"], None, None, None, None, None)),
    (
        "select count(*) from t limit 1",
        ("count(*)", ["t"], None, None, None, "1", None),
    ),
    (
        "SELECT a  \n  b FROM   t     WHERE  x      y   z",
        ("a  \n  b", ["t"], (True, "x      y   z"), None, None, None, None),
    ),
    (
        "SELECT a FROM t     WHERE          ORDER      BY    z",
        ("a", ["t", "WHERE"], None, (True, "z"), None, None, None),
    ),
]

COLUMN_PHRASE_TABLE = [
    ("show name, age from users", "name, age"),
    ("show   from users", ""),
    ("show    from users", ""),
    ("select a b c", None),
    ("get all", None),
    ("find x where y", "x"),
    ("show", None),
    ("show   ", ""),
    ("show\n", None),
    ("show a\n", "a"),
    ("get   order", ""),
    ("show  a  from", "a"),
    ("target a from b", None),
    ("show -", None),
    ("get a - from x", None),
    ("list show x limit 5", "x"),
    ("show fromage from x", "fromage"),
    ("SHOW a from b", None),
]

GT_TABLE = [
    ("age > 5", ("age", "5")),
    ("age greater than 10 and x", ("age", "10")),
    ("xgreater than 5", ("x", "5")),
    ("a  <  7", None),
    ("score less than 3", None),
    ("name = 'bob'", None),
    ("status equals active", None),
    ('a="b"', None),
    ("1a > 2", ("1a", "2")),
    ("a>", None),
    ("a > b", None),
    ("foo_bar >= 3", None),
    ("x-y = z", None),
]

LT_TABLE = [
    ("age > 5", None),
    ("age greater than 10 and x", None),
    ("xgreater than 5", None),
    ("a  <  7", ("a", "7")),
    ("score less than 3", ("score", "3")),
    ("name = 'bob'", None),
    ("status equals active", None),
    ('a="b"', None),
    ("1a > 2", None),
    ("a>", None),
    ("a > b", None),
    ("foo_bar >= 3", None),
    ("x-y = z", None),
]

EQ_TABLE = [
    ("age > 5", None),
    ("age greater than 10 and x", None),
    ("xgreater than 5", None),
    ("a  <  7", None),
    ("score less than 3", None),
    ("name = 'bob'", ("name", "bob")),
    ("status equals active", ("status", "active")),
    ('a="b"', ("a", "b")),
    ("1a > 2", None),
    ("a>", None),
    ("a > b", None),
    ("foo_bar >= 3", None),
    ("x-y = z", ("y", "z")),
]

URI_TABLE = [
    ("postgres://u:p@h/db", "postgres://u:***@h/db"),
    ("1postgres://u:p@h", "1postgres://u:***@h"),
    ("x+y://us:pw@host:5432/db", "x+y://us:***@host:5432/db"),
    ("http://h:80/x", "http://h:80/x"),
    ("see a://b:c@d and e://f:g@h", "see a://b:***@d and e://f:***@h"),
    ("9://u:p@h", "9://u:p@h"),
    ("a://:p@h", "a://:p@h"),
    ("a://u:@h", "a://u:@h"),
    ("a://u:p", "a://u:p"),
    ("  proto://user:secret@host  ", "  proto://user:***@host  "),
]

POOL_TABLE = [
    ("postgres://u:p@h/db", "postgres://u:***@h/db"),
    ("://u:p@h", "://u:***@h"),
    ("x ://a:b ://c:d@e", "x ://a:***@e"),
    ("no creds", "no creds"),
    ("://a:b", "://a:b"),
    ("a://u:@h", "a://u:@h"),
    ("://u:p@h ://v:q@w tail", "://u:***@h ://v:***@w tail"),
]

JSON_TABLE = [
    ('{"a": 1}', '{"a": 1}'),
    ('x {"a": {"b": 2}} y', '{"a": {"b": 2}}'),
    ("{", None),
    ("}", None),
    ("} {", None),
    ("{} }", "{} }"),
    ("no braces", None),
    ("pre {a} mid {b} post", "{a} mid {b}"),
    ("{{}", "{{}"),
    ("{ }}", "{ }}"),
]

COMMENT_TABLE = [
    ("a /* c */ b", "a  b"),
    ("a /* c b", "a /* c b"),
    ("/**/", ""),
    ("/*/ x */ y", " y"),
    ("x /* a */ y /* b */ z", "x  y  z"),
    ("/* a /* b */ c */", " c */"),
    ("a */ b", "a */ b"),
    ("/*", "/*"),
    ("no comments", "no comments"),
    ("/*\n multi \n*/x", "x"),
]

SEMI_TABLE = [
    ("a;", "a"),
    ("a;;  ", "a"),
    ("a; ;", "a; "),
    ("a;\n", "a"),
    ("a;b", "a;b"),
    (";", ""),
    (";;;", ""),
    ("a ;  ;  ", "a ;  "),
    ("a", "a"),
    ("a ; x ", "a ; x "),
    ("", ""),
]

SPLIT_WHERE_TABLE = [
    (
        "a = 1 AND b = 2",
        [{"delimiter": "AND", "value": "a = 1"}, {"delimiter": "", "value": "b = 2"}],
    ),
    (
        "a   =   1    OR    b  >  2",
        [
            {"delimiter": "OR", "value": "a   =   1"},
            {"delimiter": "", "value": "b  >  2"},
        ],
    ),
    (
        "a BETWEEN 1 AND 2 AND c = 3",
        [
            {"delimiter": "AND", "value": "a BETWEEN 1 AND 2"},
            {"delimiter": "", "value": "c = 3"},
        ],
    ),
    ("a IS   NOT   NULL", [{"delimiter": "", "value": "a IS   NOT   NULL"}]),
    (
        "a  NOT IN (1, 2) and (b or c)",
        [
            {"delimiter": "AND", "value": "a  NOT IN (1, 2)"},
            {"delimiter": "", "value": "(b or c)"},
        ],
    ),
    ("x LIKE 'a  and  b'", [{"delimiter": "", "value": "x LIKE 'a  and  b'"}]),
    ("  = 1", [{"delimiter": "", "value": "= 1"}]),
    ("a    ", [{"delimiter": "", "value": "a"}]),
    ("a    =", [{"delimiter": "", "value": "a    ="}]),
    (
        "(a AND b) OR c",
        [{"delimiter": "OR", "value": "(a AND b)"}, {"delimiter": "", "value": "c"}],
    ),
    (
        "a IN (1,2) AND b ILIKE 'x'",
        [
            {"delimiter": "AND", "value": "a IN (1,2)"},
            {"delimiter": "", "value": "b ILIKE 'x'"},
        ],
    ),
    ("a<>1", [{"delimiter": "", "value": "a<>1"}]),
    ("a  !=  1", [{"delimiter": "", "value": "a  !=  1"}]),
]

OPERATOR_TABLE = [
    ("a = 1 AND b = 2", ("=", 2, 1)),
    ("a   =   1    OR    b  >  2", ("=", 4, 1)),
    ("a BETWEEN 1 AND 2 AND c = 3", ("BETWEEN", 2, 7)),
    ("a IS   NOT   NULL", ("IS NOT NULL", 2, 15)),
    ("a  NOT IN (1, 2) and (b or c)", ("NOT IN", 3, 6)),
    ("x LIKE 'a  and  b'", ("LIKE", 2, 4)),
    ("  = 1", None),
    ("a    ", None),
    ("a    =", ("=", 5, 1)),
    ("(a AND b) OR c", None),
    ("a IN (1,2) AND b ILIKE 'x'", ("IN", 2, 2)),
    ("a<>1", ("!=", 1, 2)),
    ("a  !=  1", ("!=", 3, 2)),
]


def _check(table: list[tuple[str, Any]], fn: Callable[[str], Any]) -> None:
    for text, expected in table:
        assert fn(text) == expected, text


def test_table_parse_sql_to_spec() -> None:
    for sql, expected in PARSE_TABLE:
        spec = P.parse_sql_to_spec(sql)
        assert (None if spec is None else spec.to_dict()) == expected, sql


def test_table_cte() -> None:
    _check(CTE_TABLE, new_cte)


def test_table_window() -> None:
    _check(WINDOW_TABLE, new_window)


def test_table_partition_and_order() -> None:
    _check(PARTITION_TABLE, new_partition)
    _check(ORDER_TABLE, new_order)


def test_table_trunc_and_aggregates() -> None:
    _check(DATE_TRUNC_TABLE, new_date_trunc)
    _check(DATETRUNC_TABLE, new_datetrunc)
    _check(AGG_TABLE, new_agg)
    _check(FILTER_AGG_TABLE, new_filter_agg)


def test_table_neo4j() -> None:
    _check(NEO4J_TABLE, new_neo4j)


def test_table_column_phrase() -> None:
    _check(COLUMN_PHRASE_TABLE, NP._match_column_phrase)


def test_table_nlq_filters() -> None:
    _check(GT_TABLE, lambda t: new_filter(NP._GT_FILTER_RE, t))
    _check(LT_TABLE, lambda t: new_filter(NP._LT_FILTER_RE, t))
    _check(EQ_TABLE, lambda t: new_filter(NP._EQ_FILTER_RE, t))


def test_table_secrets_json_comments_semicolons() -> None:
    _check(URI_TABLE, lambda t: URI_CREDENTIAL_REGEX.sub(r"\g<1>***\g<3>", t))
    _check(POOL_TABLE, mask_credentials)
    _check(JSON_TABLE, _find_json_object_text)
    _check(COMMENT_TABLE, strip_block_comments)
    _check(SEMI_TABLE, strip_trailing_semicolons)


def test_table_where_splitting() -> None:
    _check(SPLIT_WHERE_TABLE, P.split_where_conditions)
    _check(OPERATOR_TABLE, P.find_top_level_operator)
