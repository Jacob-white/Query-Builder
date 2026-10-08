"""Golden-snapshot tests for the linear-time regex rewrites.

The expected values below and in ``tests/fixtures/regex_golden_*.json`` were produced
by running the ORIGINAL (pre-rewrite, super-linear) implementations over the same
inputs; the original code is intentionally not kept in the repository.  Two kinds of
snapshots are checked against the current implementation:

* hand-picked tables (``*_TABLE`` below), and
* seeded randomized corpora stored as JSON fixtures (input, expected output).

See ``tests/test_regex_linear_timing.py`` for the adversarial linear-time tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from query_builder import parser as P
from query_builder._regex_utils import strip_block_comments, strip_trailing_semicolons
from query_builder.ai.byo_provider import _find_json_object_text
from query_builder.connectors.neo4j import _match_simple_select
from query_builder.nlq import providers as NP
from query_builder.pool import mask_credentials
from query_builder.security import URI_CREDENTIAL_REGEX

FIXTURES = Path(__file__).parent / "fixtures"


def golden(name: str) -> dict[str, list[Any]]:
    with (FIXTURES / f"regex_golden_{name}.json").open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def jsonable(value: Any) -> Any:
    """Normalise tuples etc. the way the fixtures were serialised."""
    return json.loads(json.dumps(value))


def check_corpus(
    corpus: list[Any], fn: Callable[[Any], Any], minimum: int = 300
) -> None:
    assert len(corpus) >= minimum
    for text, expected in corpus:
        assert jsonable(fn(text)) == expected, text


# ---------------------------------------------------------------------------------
# "Views": normalise results to the values the callers actually use
# ---------------------------------------------------------------------------------


def new_cte(text: str) -> Any:
    m = P._CTE_DEF_RE.match(text)
    return None if m is None else (*m.groups()[:3], m.group(4).strip())


def new_window(text: str) -> Any:
    m = P._match_window_expr(text)
    if m is None:
        return None
    return (m.func, m.args.strip(), m.over.strip(), m.alias)


def new_partition(text: str) -> Any:
    return P._clause_body(text, P._PARTITION_BY_RE, P._PARTITION_TERMINATOR_RE)


def new_order(text: str) -> Any:
    return P._clause_body(text, P._ORDER_BY_RE, P._ORDER_TERMINATOR_RE)


def new_date_trunc(text: str) -> Any:
    m = P._DATE_TRUNC_RE.match(text)
    if m is None:
        return None
    return (m.group(1), P._arg_after_comma(m.group(2)), m.group(3))


def new_datetrunc(text: str) -> Any:
    m = P._DATETRUNC_RE.match(text)
    if m is None:
        return None
    return (m.group(1), P._arg_after_comma(m.group(2)), m.group(3))


def new_filter_agg(text: str) -> Any:
    m = P._FILTER_AGG_RE.match(text)
    if m is None or not P._valid_filter_condition(m.group(3)):
        return None
    # group 3 (the condition) is never read by the parser; only its existence matters
    return (m.group(1), P._agg_argument(m.group(2)), m.group(4))


def new_agg(text: str) -> Any:
    m = P._AGG_RE.match(text)
    if m is None:
        return None
    return (m.group(1), P._agg_argument(m.group(2)), m.group(3))


def new_neo4j(text: str) -> Any:
    m = _match_simple_select(text)
    if m is None:
        return None

    def free(group: str | None) -> Any:
        return None if group is None else (bool(group), group.strip())

    # what ``_Neo4jCursorAdapter.execute`` reads: stripped text, split ``from``, truthiness
    return (
        m.select.strip(),
        m.from_.split(),
        free(m.where),
        free(m.order),
        m.skip,
        m.limit,
        m.offset,
    )


def new_filter(pattern: Any, text: str) -> Any:
    m = pattern.search(text)
    return None if m is None else m.groups()


# ---------------------------------------------------------------------------------
# Golden corpora (fixtures)
# ---------------------------------------------------------------------------------
PARSER = golden("parser")
MISC = golden("misc")


def test_golden_cte_and_window() -> None:
    check_corpus(PARSER["cte"], new_cte)
    check_corpus(PARSER["window"], new_window)


def test_golden_partition_and_order() -> None:
    check_corpus(PARSER["partition"], new_partition)
    check_corpus(PARSER["order"], new_order)


def test_golden_trunc_and_aggregates() -> None:
    check_corpus(PARSER["date_trunc"], new_date_trunc)
    check_corpus(PARSER["datetrunc"], new_datetrunc)
    check_corpus(PARSER["agg"], new_agg)
    check_corpus(PARSER["filter_agg"], new_filter_agg)


def test_golden_where_splitting_and_operators() -> None:
    check_corpus(PARSER["split_where"], P.split_where_conditions)
    check_corpus(PARSER["operator"], P.find_top_level_operator)


def test_golden_neo4j_and_column_phrase() -> None:
    check_corpus(MISC["neo4j"], new_neo4j)
    check_corpus(MISC["column_phrase"], NP._match_column_phrase)


@pytest.mark.parametrize(
    ("key", "pattern"),
    [("gt", NP._GT_FILTER_RE), ("lt", NP._LT_FILTER_RE), ("eq", NP._EQ_FILTER_RE)],
)
def test_golden_nlq_filter_patterns(key: str, pattern: Any) -> None:
    check_corpus(MISC[key], lambda t: new_filter(pattern, t), 300)


def test_golden_secrets_json_comments_semicolons() -> None:
    check_corpus(MISC["uri"], lambda t: URI_CREDENTIAL_REGEX.sub(r"\g<1>***\g<3>", t))
    check_corpus(MISC["pool"], mask_credentials)
    check_corpus(MISC["json_object"], _find_json_object_text)
    check_corpus(MISC["block_comments"], strip_block_comments)
    check_corpus(MISC["semicolons"], strip_trailing_semicolons)


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
