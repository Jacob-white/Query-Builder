"""False-positive measurement: a corpus of ~200 realistic benign analytical queries.

The validator must accept every one of them (0% false-positive rate), both through the
generic path (``dialect=None``) and, for dialect-tagged entries, with that dialect.
"""

from __future__ import annotations

import pytest

from query_builder.ast_validator import validate_sql_ast
from tests._benign_corpus import BENIGN_CORPUS


def test_corpus_size() -> None:
    assert len(BENIGN_CORPUS) >= 200


@pytest.mark.parametrize(("sql", "dialect"), BENIGN_CORPUS)
def test_benign_query_is_accepted(sql: str, dialect: str | None) -> None:
    res = validate_sql_ast(sql, dialect=dialect)
    assert res["valid"], f"FALSE POSITIVE ({dialect}): {sql!r}: {res['violations']}"


def test_false_positive_rate_is_zero() -> None:
    rejected = [
        (sql, d)
        for sql, d in BENIGN_CORPUS
        if not validate_sql_ast(sql, dialect=d)["valid"]
    ]
    rate = len(rejected) / len(BENIGN_CORPUS)
    assert rate == 0.0, (
        f"FP rate {rate:.1%} on {len(BENIGN_CORPUS)} queries: {rejected[:5]}"
    )
