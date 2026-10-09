"""Property/fuzz tests for the validator that need no external oracle.

* robustness: arbitrary text never raises and always returns the documented shape;
* metamorphic: inserting whitespace / every comment style between tokens never turns a
  rejected dangerous query into an accepted one, nor a benign one into a rejection;
* every dangerous seed in the corpus is rejected for every dialect.

Run the long profile occasionally: ``HYPOTHESIS_PROFILE=deep python -m pytest -m fuzz -q``.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from query_builder.ast_validator import validate_sql_ast
from tests import _sqlgen as g
from tests._benign_corpus import BENIGN_CORPUS

pytestmark = pytest.mark.fuzz

_SHAPE = {
    "valid",
    "ast_validated",
    "statement_type",
    "is_read_only",
    "violations",
    "injection_risk",
    "message",
}

# Seeds that touch no restricted table / function but are still dangerous or malformed,
# and seeds that are expected to be accepted are excluded from the "must reject" set.
_MUST_ACCEPT_SEEDS = {"SELECT * FROM orders AS auth_user"}


@given(st.text(max_size=300))
def test_arbitrary_text_never_raises(text: str) -> None:
    res = validate_sql_ast(text)
    assert _SHAPE <= set(res)
    assert isinstance(res["valid"], bool)
    if res["valid"]:
        assert res["violations"] == []


@given(g.sql_inputs)
def test_generated_inputs_never_raise_and_are_consistent(sql: str) -> None:
    res = validate_sql_ast(sql)
    assert _SHAPE <= set(res)
    assert res["valid"] == (not res["violations"])


def _dangerous_seeds() -> list[str]:
    """Rejected seeds that can be split on spaces without breaking a literal/comment."""
    plain = [
        s
        for s in g.SEEDS
        if not any(c in s for c in "'\"$#\n\\") and "--" not in s and "/*" not in s
    ]
    return [s for s in plain if not validate_sql_ast(s)["valid"]]


@given(st.data())
def test_comment_and_whitespace_insertion_cannot_unblock(data) -> None:
    seed = data.draw(st.sampled_from(_dangerous_seeds()))
    parts = seed.split(" ")
    out = parts[0]
    for p in parts[1:]:
        out += " " + data.draw(g.SEPARATORS) + " " + p
    assert not validate_sql_ast(out)["valid"], out
    assert not validate_sql_ast(out, dialect="sqlite")["valid"], out


# Nested block comments are deliberately rejected (their meaning differs between engines),
# so they are excluded from the "benign stays benign" metamorphic test.
_PORTABLE_SEPARATORS = g.SEPARATORS.filter(lambda sep: "nested" not in sep)

_CLEAN_BENIGN = [
    (s, d)
    for s, d in BENIGN_CORPUS
    if not any(c in s for c in "'\"`$%?:@[\\")
    and "--" not in s
    and "/*" not in s
    and "\n" not in s
]


@given(st.data())
def test_comment_and_whitespace_insertion_cannot_block_benign(data) -> None:
    sql, dialect = data.draw(st.sampled_from(_CLEAN_BENIGN))
    parts = sql.split(" ")
    out = parts[0]
    for p in parts[1:]:
        out += " " + data.draw(_PORTABLE_SEPARATORS) + " " + p
    assert validate_sql_ast(out, dialect=dialect)["valid"], out


@pytest.mark.parametrize("sql", [s for s in g.SEEDS if s not in _MUST_ACCEPT_SEEDS])
@pytest.mark.parametrize(
    "dialect", [None, "postgres", "mysql", "sqlite", "duckdb", "mssql", "snowflake"]
)
def test_every_dangerous_seed_rejected_in_every_dialect(
    sql: str, dialect: str | None
) -> None:
    # A few seeds are only dangerous in some dialects (e.g. `$$` quoting is PostgreSQL's);
    # those are covered by the oracle suites, so only the dialect-independent ones here.
    dialect_specific = ("$$", "$a$", "# c", "'\\")
    if any(tok in sql for tok in dialect_specific) and dialect is not None:
        pytest.skip("dialect-specific lexing; covered by the differential oracles")
    res = validate_sql_ast(sql, dialect=dialect)
    if sql in {"SELECT 1 # c\n; DROP TABLE orders"} and dialect not in (None, "mysql"):
        pytest.skip("`#` is not a comment outside MySQL")
    assert not res["valid"], f"{sql!r} accepted for dialect {dialect}"
