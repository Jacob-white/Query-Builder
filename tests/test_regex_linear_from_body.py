"""``_extract_from_body`` matches the original slice-per-character implementation."""

from __future__ import annotations

import random
import re
import time

from query_builder.ast_validator import _IDENTIFIER_QUOTES, _extract_from_body


def _old_extract_from_body(sql: str, start_idx: int) -> str:
    """The original implementation (verbatim): re.match on ``sql[i:]`` per character."""
    depth = 0
    i = start_idx
    length = len(sql)
    while i < length:
        ch = sql[i]
        if ch in _IDENTIFIER_QUOTES:
            quote_close = _IDENTIFIER_QUOTES[ch]
            j = i + 1
            while j < length and sql[j] != quote_close:
                j += 1
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
            else:
                break
        elif ch == ";" or (
            depth == 0
            and re.match(
                r"^(WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|UNION|INTERSECT|EXCEPT|WINDOW|FETCH|FOR)\b",
                sql[i:],
                re.IGNORECASE,
            )
        ):
            break
        i += 1
    return sql[start_idx:i].strip()


TABLE = [
    ("users, auth_user) s", 0, "users, auth_user"),
    ("a JOIN b ON x WHERE y", 0, "a JOIN b ON x"),
    ("t group  by x", 0, "t"),
    ("t1, (select 1 where 1) q order by z", 0, "t1, (select 1 where 1) q"),
    ('"w""here" , b limit 3', 0, '"w""here" , b'),
    ("x; y", 0, "x"),
    ("format x", 0, "format x"),
    ("t [where] u forx", 0, "t [where] u forx"),
]


def test_table_from_original() -> None:
    for sql, start, expected in TABLE:
        assert _old_extract_from_body(sql, start) == expected
        assert _extract_from_body(sql, start) == expected


def test_random_matches_original() -> None:
    rng = random.Random(61)
    atoms = [
        "WHERE",
        "where",
        "GROUP  BY",
        "ORDER\tBY",
        "FOR",
        "format",
        "FETCH",
        "(",
        ")",
        ";",
        '"',
        "`",
        "[",
        "]",
        "a",
        " ",
        ",",
        "LIMIT",
        "x1",
        "\n",
    ]
    for _ in range(8000):
        sql = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 16)))
        start = rng.randint(0, 2)
        assert _extract_from_body(sql, start) == _old_extract_from_body(sql, start)


def test_long_input_is_linear() -> None:
    sql = "table_a, " * 25_000 + "table_b"
    start = time.perf_counter()
    assert _extract_from_body(sql, 0) == sql
    assert time.perf_counter() - start < 2.0
    sql = "a " + "(" * 50_000
    start = time.perf_counter()
    _extract_from_body(sql, 0)
    assert time.perf_counter() - start < 2.0
