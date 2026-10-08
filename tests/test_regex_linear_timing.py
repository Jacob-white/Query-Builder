"""Adversarial linear-time tests for regexes that used to backtrack polynomially.

Each input below is the hallmark ReDoS shape for one pattern (CodeQL
``py/polynomial-redos``): whitespace pumped next to a lazy group, repeated start
literals with no terminator, long runs of ``/*`` or ``;`` ...  Before the rewrite most
of these took from several seconds to minutes (the tests only use the public entry
points, so they can be run against the old code to confirm that); now each must finish
well inside the generous bound (CI also runs with coverage enabled).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from query_builder import middleware
from query_builder.adapters.drizzle import from_drizzle
from query_builder.adapters.prisma import from_prisma
from query_builder.ai.byo_provider import BringYourOwnAiProvider
from query_builder.connectors.neo4j import _Neo4jCursorAdapter
from query_builder.nlq.providers import MockNlqProvider
from query_builder.parser import (
    find_top_level_operator,
    parse_sql_to_spec,
    split_where_conditions,
)
from query_builder.pool import mask_credentials
from query_builder.security import scrub_secrets

LIMIT_SECONDS = 2.0
N = 50_000
# the parser walks the text character by character in Python, so its inputs are smaller
PN = 20_000


def assert_fast(fn: Callable[[], Any]) -> Any:
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    assert elapsed < LIMIT_SECONDS, f"took {elapsed:.2f}s"
    return result


# ---------------------------------------------------------------------------------
# parser.py
# ---------------------------------------------------------------------------------

WS_RUNS = [" ", "\t", "\n", " \t\n\r"]


@pytest.mark.parametrize("ws", WS_RUNS)
def test_cte_body_whitespace(ws: str) -> None:
    sql = "WITH c AS (" + ws * PN + "x) y SELECT a FROM t"
    assert_fast(lambda: parse_sql_to_spec(sql))


def test_cte_definition_with_trailing_garbage() -> None:
    sql = "WITH c AS (" + " " * PN + "x) y, d AS (" + " " * PN + "z) w SELECT a FROM c"
    assert_fast(lambda: parse_sql_to_spec(sql))


@pytest.mark.parametrize("ws", WS_RUNS)
def test_window_function_whitespace(ws: str) -> None:
    for sql in (
        "SELECT f(a) OVER (" + ws * PN + "PARTITION BY a) x y z FROM t",
        "SELECT f(" + ws * PN + "a) OVER (b) x y z FROM t",
        "SELECT f(a) OVER (b" + ws * PN + ") x y z FROM t",
    ):
        assert_fast(lambda sql=sql: parse_sql_to_spec(sql))


def test_window_function_repeated_over_and_clauses() -> None:
    body = ") OVER (" * 5000
    assert_fast(lambda: parse_sql_to_spec(f"SELECT f(a{body}b) x y z FROM t"))
    clauses = "PARTITION BY a " * 4000
    assert_fast(lambda: parse_sql_to_spec(f"SELECT f(a) OVER ({clauses}) x y z FROM t"))
    # a ")" before any terminator makes every PARTITION BY / ORDER BY start fail
    nested = "PARTITION BY f(a) " * 3000 + "ORDER BY g(b) " * 3000
    assert_fast(lambda: parse_sql_to_spec(f"SELECT f(a) OVER ({nested}) FROM t"))


@pytest.mark.parametrize("ws", WS_RUNS)
def test_trunc_and_aggregate_whitespace(ws: str) -> None:
    for expr in (
        "DATE_TRUNC('m'," + ws * PN + "c) x y z",
        "DATETRUNC(day," + ws * PN + "c) x y z",
        "COUNT(" + ws * PN + "a b) x y z",
        "COUNT(DISTINCT" + ws * PN + "a b) x y z",
        "SUM(" + ws * PN + "a) FILTER (WHERE" + ws * PN + "x) y z",
    ):
        assert_fast(lambda expr=expr: parse_sql_to_spec(f"SELECT {expr} FROM t"))


@pytest.mark.parametrize("ws", WS_RUNS)
def test_where_split_and_operator_whitespace(ws: str) -> None:
    n = PN // 4
    text = "a" + ws * n + "x" + ws * n + "= 1" + ws * n + "AND" + ws * n + "b"
    assert_fast(lambda: split_where_conditions(text))
    assert_fast(lambda: find_top_level_operator(text))
    sql = f"SELECT a FROM t WHERE {text}"
    assert_fast(lambda: parse_sql_to_spec(sql))


def test_long_runs_of_punctuation() -> None:
    for run in (",", "(", ")", "((", ",,", "'", ";"):
        sql = "SELECT " + run * PN + " a FROM t"
        assert_fast(lambda sql=sql: parse_sql_to_spec(sql))
    assert_fast(lambda: parse_sql_to_spec("SELECT " + "a," * PN + "b FROM t"))
    assert_fast(
        lambda: parse_sql_to_spec("SELECT a FROM t WHERE " + "a = 1 AND " * 10000 + "b")
    )


def test_unterminated_comments_and_trailing_semicolons() -> None:
    assert_fast(lambda: parse_sql_to_spec("/*" * N + "SELECT a FROM t"))
    assert_fast(lambda: parse_sql_to_spec("SELECT a /*" + "/*" * N + " FROM t"))
    assert_fast(lambda: parse_sql_to_spec("SELECT a FROM t" + ";" * N + "x"))
    assert_fast(lambda: parse_sql_to_spec("SELECT a FROM t" + "; " * N + "x"))
    assert parse_sql_to_spec("SELECT a FROM t" + ";" * N) is not None


# ---------------------------------------------------------------------------------
# connectors/neo4j.py
# ---------------------------------------------------------------------------------


class _Session:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run(self, query: str, parameters: Any = None) -> list[Any]:
        self.queries.append(query)
        return []


def _translate(sql: str) -> str:
    session = _Session()
    _Neo4jCursorAdapter(session).execute(sql)
    return session.queries[-1]


def test_neo4j_translation_still_works() -> None:
    assert (
        _translate("SELECT a, b FROM t u WHERE a = 1 ORDER BY b LIMIT 5")
        == "MATCH (`u`:`t`) WHERE a = 1 RETURN a, b ORDER BY b LIMIT 5"
    )


@pytest.mark.parametrize("ws", WS_RUNS)
def test_neo4j_select_whitespace(ws: str) -> None:
    for sql in (
        "SELECT" + ws * N,
        "SELECT" + ws * N + "a",
        "SELECT a" + ws * N + "FROM",
        "SELECT a FROM t WHERE x" + ws * N + "y",
        "SELECT a FROM t WHERE x" + ws * N + "ORDER" + ws * N + "BY" + ws * N + "z",
        "SELECT a FROM t" + ws * N + "u" + ws * N + "v",
    ):
        assert_fast(lambda sql=sql: _translate(sql))


def test_neo4j_select_repeated_keywords() -> None:
    assert_fast(lambda: _translate("SELECT a" + " FROM x y" * 10000))
    assert_fast(lambda: _translate("SELECT a FROM t" + " WHERE x" * 10000))


# ---------------------------------------------------------------------------------
# nlq/providers.py
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("ws", WS_RUNS)
def test_nlq_column_phrase_whitespace(ws: str) -> None:
    provider = MockNlqProvider()
    for prompt in (
        "get x" + ws * N + "y",
        "get" + ws * N + "x",
        "show a" + ws * N + "-",
        "select" + ws * N + "a,b" + ws * N + "!",
    ):
        assert_fast(lambda prompt=prompt: provider.generate_ast(prompt, None))


def test_nlq_repeated_keywords_and_words() -> None:
    provider = MockNlqProvider()
    for prompt in (
        "show " * N + "!",
        "get a, " * 10000 + "!",
        "a" * N,
        "a" * N + " > ",
        "a" * N + " = ",
        "a_1 " * 10000 + "<",
        "from " * 10000,
    ):
        assert_fast(lambda prompt=prompt: provider.generate_ast(prompt, None))


# ---------------------------------------------------------------------------------
# security.py / pool.py / ai/byo_provider.py / middleware.py
# ---------------------------------------------------------------------------------


SECRET_INPUTS = {
    "letters": lambda: "a" * N,
    "dotted": lambda: "a." * N,
    "scheme_chars": lambda: "a1+" * N,
    "uri_long_password": lambda: "a" * N + "://u:" + "p" * N,
    "uri_repeated": lambda: "a://u:p" * 10000,
    "digits_then_letters": lambda: "1" * N + "x" * N,
    "bearer_whitespace": lambda: "bearer" + " " * N + " x",
    "key_value_whitespace": lambda: "password" + " " * N + ":",
}


@pytest.mark.parametrize("name", list(SECRET_INPUTS))
def test_scrub_and_mask_secrets(name: str) -> None:
    text = SECRET_INPUTS[name]()
    assert_fast(lambda: scrub_secrets(text))
    assert_fast(lambda: mask_credentials(text))


def test_credential_masks_still_work() -> None:
    assert scrub_secrets("see postgres://u:secret@h/db now") == (
        "see postgres://u:***@h/db now"
    )
    assert mask_credentials("postgres://u:secret@h/db") == "postgres://u:***@h/db"
    # (the password pattern is greedy up to the next "@", as it always was)
    assert mask_credentials("x ://a:b ://c:d@e") == "x ://a:***@e"


def test_pool_mask_credentials_repeated_uri_starts() -> None:
    assert_fast(lambda: mask_credentials("://a" * 20000))
    assert_fast(lambda: mask_credentials("://a" * 20000 + "@"))


def test_byo_json_extraction_without_closing_brace() -> None:
    class _Provider(BringYourOwnAiProvider):
        def __init__(self, reply: str) -> None:
            self._reply = reply

        def _call_ai_sync(self, *_: Any, **__: Any) -> tuple[Any, int | None]:
            return self._reply, None

    for reply in ("{" * N, "{ " * N + "x", "} " * N, "x{" + "{\n" * N):
        provider = _Provider(reply)
        start = time.perf_counter()
        with pytest.raises(Exception, match="BYO-AI"):
            provider.generate_ast("q", {}, "postgres")
        assert time.perf_counter() - start < LIMIT_SECONDS
    ok = _Provider('noise {"a": 1} tail').generate_ast("q", {}, "postgres")
    assert ok == ({"a": 1}, None)


def test_middleware_comment_stripping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(middleware, "sqlparse", None)
    assert_fast(lambda: middleware._is_mutating_sql("/*" * N + " select 1"))
    assert_fast(lambda: middleware._is_mutating_sql("select 1 /*" + "/*" * N))
    assert middleware._is_mutating_sql("/* c */ delete from t")
    assert not middleware._is_mutating_sql("select 1 /* delete */")


# ---------------------------------------------------------------------------------
# adapters/prisma.py and adapters/drizzle.py
# ---------------------------------------------------------------------------------


def test_prisma_blocks_without_closing_brace() -> None:
    assert_fast(lambda: from_prisma("model a {" * 20000))
    assert_fast(lambda: from_prisma("enum a {" * 20000))
    assert_fast(lambda: from_prisma("model a {" + "{x}" * 20000))


def test_prisma_relation_directive() -> None:
    def model(body: str) -> str:
        return "model a {\n id Int @id\n" + body + "\n}\nmodel b {\n id Int @id\n}"

    assert_fast(lambda: from_prisma(model("x B @relation(fields: [" * 20000)))
    assert_fast(
        lambda: from_prisma(
            model("x B @relation(" + "fields : [a]  references: [b] " * 20000)
        )
    )
    assert_fast(lambda: from_prisma(model("x B @relation(" + "references: [" * 20000)))
    tables = from_prisma(
        "model a {\n id Int @id\n bId Int\n b B @relation(fields: [bId], references: [id])\n}\n"
        "model B {\n id Int @id\n}"
    )
    assert tables["a"].foreign_keys[0].foreign_table == "B"


def test_drizzle_column_call_in_long_identifier() -> None:
    source = (
        "export const t = pgTable('t', {\n  a: " + "w" * N + ",\n  b: text('b'),\n})"
    )
    assert_fast(lambda: from_drizzle(source))
    tables = from_drizzle(source)
    assert [c.name for c in tables["t"].columns] == ["b"]


# ---------------------------------------------------------------------------------
# adapters/drizzle.py: table headers, parenthesis balancing, literal-then-[^X]+ searches
# ---------------------------------------------------------------------------------


def test_drizzle_header_annotations_without_equals() -> None:
    assert_fast(lambda: from_drizzle("const a: T " * 5_000))
    assert_fast(lambda: from_drizzle("export const a:" * 5_000 + " = pgTable('x'"))
    assert_fast(lambda: from_drizzle("const a = pgEnum('x', [" * 2_500))
    assert_fast(lambda: from_drizzle("const a = pgTable('x'" * 2_500))
    assert_fast(lambda: from_drizzle("pgTable('x'" * 5_000 + "= pgTable('y'"))
    assert_fast(lambda: from_drizzle("const " * 10_000 + "= pgTable('y'"))


def test_drizzle_unbalanced_calls_scan_once() -> None:
    assert_fast(lambda: from_drizzle("pgTable('x'" * 5_000))
    assert_fast(lambda: from_drizzle("const a = pgTable('x'" * 2_500 + ")"))
    assert_fast(lambda: from_drizzle("pgTable('x', {" * 4_000 + "'" * 4_000))
    assert_fast(lambda: from_drizzle("pgTable('x' '" * 4_000))


def test_drizzle_column_and_extra_block_searches() -> None:
    head = "export const t = pgTable('t', {\n a: text('a')"
    assert_fast(lambda: from_drizzle(head + ".default(" * 5_000 + "\n})"))
    extra = "\n}, (t) => ({ k: "
    assert_fast(lambda: from_drizzle(head + extra + "primaryKey(" * 5_000 + "}))"))
    assert_fast(
        lambda: from_drizzle(head + extra + "primaryKey({ columns: [" * 2_000 + "}))")
    )


def test_prisma_composite_id_without_closing_bracket() -> None:
    body = "x Int\n@@id([" * 5_000 + " "
    assert_fast(lambda: from_prisma("model a {\n" + body + "\n}"))
    assert_fast(lambda: from_prisma("model a {\n" + "@@id( [a] " * 5_000 + "\n}"))
