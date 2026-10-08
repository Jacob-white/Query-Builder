"""ReDoS / super-linear work guards for ``validate_sql_ast`` (ISSUE 3).

Each of these inputs took between ~1s and minutes on the old regexes (whitespace-ambiguous
``(?:\\s*\\.\\s*)+`` dotted names, the WAITFOR whitespace-or-comment repetition,
quadratic ``[``/``"`` scans, and sqlparse's super-linear grouping on token floods).
"""

from __future__ import annotations

import time

import pytest

from query_builder.ast_validator import MAX_SQL_LENGTH, validate_sql_ast

# Generous on purpose: the slowest case (sqlparse on 8000 parens) takes ~0.15s plain and ~0.45s
# under coverage tracing, while the regressions this guards against took 20s to minutes.
BUDGET_SECONDS = 2.0


def _timed(sql: str, **kwargs) -> tuple[dict, float]:
    start = time.perf_counter()
    res = validate_sql_ast(sql, **kwargs)
    return res, time.perf_counter() - start


CASES: dict[str, str] = {
    "dotted_spaces_60": "SELECT 1 FROM t" + " ." * 60,
    "dotted_spaces_22": "SELECT 1 FROM t" + " ." * 22,
    "dotted_in_schema_pattern": "SELECT 1 FROM public" + " ." * 60 + " x",
    "dotted_multipart": "SELECT a" + " . " * 200 + "b FROM t",
    "waitfor_spaces_26": "SELECT 1 WAITFOR" + " " * 26 + "x",
    "waitfor_spaces_200": "SELECT 1 WAITFOR" + " " * 200 + "x",
    "waitfor_comments": "SELECT 1 WAITFOR" + "/**/ " * 40 + "x",
    "paren_run_after_from": "SELECT 1 FROM " + "(" * 8000,
    "paren_run_closed": "SELECT 1 FROM " + "(" * 150 + "t" + ")" * 150,
    "spaces_100k": "SELECT 1 FROM t WHERE a = 1" + " " * 99_000 + "AND b = 2",
    "dots_100k": "SELECT 1 FROM t" + "." * 99_000,
    "space_dots_100k": "SELECT 1 FROM t" + " ." * 49_000,
    "single_quotes_100k": "SELECT 1 FROM t WHERE a = " + "'" * 99_000,
    "double_quotes_100k": "SELECT 1 FROM t WHERE a = " + '"' * 99_000,
    "backticks_100k": "SELECT 1 FROM t WHERE a = " + "`" * 99_000,
    "open_brackets_100k": "SELECT 1 FROM t WHERE a = " + "[" * 99_000,
    "close_brackets_100k": "SELECT 1 FROM t WHERE a = " + "]" * 99_000,
    "bracket_pairs_100k": "SELECT 1 FROM t WHERE a = " + "[]" * 49_000,
    "block_comments_100k": "SELECT 1 FROM t " + "/**/" * 24_000,
    "open_block_comments_100k": "SELECT 1 FROM t " + "/*" * 49_000,
    "line_comments_100k": "SELECT 1 FROM t" + " --\n" * 24_000,
    "hash_comments_100k": "SELECT 1 FROM t" + " #\n" * 30_000,
    "dollar_run_100k": "SELECT 1 FROM t WHERE a = " + "$" * 99_000,
    "dollar_tags_100k": "SELECT 1 FROM t WHERE a = " + "$a$ " * 24_000,
    "commas_100k": "SELECT 1 FROM t" + ",a" * 49_000,
    "ident_chain_100k": "SELECT a" + ".a" * 49_000 + " FROM t",
    "semicolons_100k": "SELECT 1" + ";" * 99_000,
    "backslashes_100k": "SELECT '" + "\\" * 99_000,
    "all_special_chars_80k": "SELECT 1 FROM t WHERE a = '" + "\\#$[--/*" * 9_000 + "'",
    "mixed_quotes_100k": "SELECT 1 FROM t WHERE a=" + "'\\\"[`#$-/*" * 9_000,
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_pathological_input_finishes_quickly(name: str) -> None:
    sql = CASES[name]
    assert len(sql) <= MAX_SQL_LENGTH or name.endswith("_over_limit")
    res, elapsed = _timed(sql)
    assert elapsed < BUDGET_SECONDS, f"{name}: {elapsed:.2f}s"
    assert isinstance(res["valid"], bool)


def test_over_length_input_is_rejected_immediately() -> None:
    res, elapsed = _timed("SELECT 1 FROM t" + " ." * 200_000)
    assert res["valid"] is False
    assert elapsed < BUDGET_SECONDS


def test_token_flood_is_rejected_before_parsing() -> None:
    # sqlparse grouping is super-linear; the linear pre-check must reject first.
    res, elapsed = _timed(
        "SELECT " + ",".join(f"a{i}" for i in range(9000)) + " FROM t"
    )
    assert res["valid"] is False
    assert any("token count" in v for v in res["violations"])
    assert elapsed < BUDGET_SECONDS

    res, elapsed = _timed("SELECT 1 FROM t" + "/**/" * 20_000)
    assert res["valid"] is False
    assert elapsed < BUDGET_SECONDS


def test_comment_flood_is_rejected_without_parsing() -> None:
    res, elapsed = _timed("SELECT 1 FROM t" + "/**/" * 1_500)
    assert res["valid"] is False
    assert any("comments" in v for v in res["violations"])
    assert elapsed < BUDGET_SECONDS


def test_custom_token_threshold_still_enforced() -> None:
    res = validate_sql_ast("SELECT 1 + 2 + 3", max_ast_tokens=2)
    assert res["valid"] is False
    assert any("safety threshold" in v for v in res["violations"])


def test_normal_queries_unaffected_by_guards() -> None:
    sql = (
        "SELECT a.id, COUNT(*) AS n FROM orders a JOIN items i ON i.order_id = a.id "
        "WHERE a.created > '2024-01-01' /* recent */ GROUP BY a.id ORDER BY n DESC"
    )
    res, elapsed = _timed(sql)
    assert res["valid"] is True
    assert elapsed < BUDGET_SECONDS


def test_restricted_detection_still_works_on_long_dotted_names() -> None:
    # Unambiguous dotted-name handling must not lose detection of schema-qualified names.
    assert validate_sql_ast("SELECT * FROM public . . auth_user")["valid"] is False
    assert validate_sql_ast("SELECT * FROM db . public . auth_user")["valid"] is False
    assert validate_sql_ast("SELECT * FROM pg_catalog   .   pg_class")["valid"] is False
    assert validate_sql_ast("SELECT 1 WAITFOR   DELAY '0:0:5'")["valid"] is False
