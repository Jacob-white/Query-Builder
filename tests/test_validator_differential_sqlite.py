"""Differential test: validator vs SQLite itself (oracle 1).

SQLite is the ground truth for what a statement *does*.  For every generated/mutated
input we execute it (under an authorizer that records, and where needed denies, every
action) against an in-memory database seeded with a fake restricted table ``auth_user``.
Invariant (NO FALSE NEGATIVES): if the oracle shows the restricted table being read, a
write/DDL/ATTACH/PRAGMA-style action, or more than one statement executing, then
``validate_sql_ast`` must reject the input.
"""

from __future__ import annotations

import sqlite3

import pytest
from hypothesis import event, given

from query_builder.ast_validator import validate_sql_ast
from tests import _sqlgen as g

pytestmark = pytest.mark.fuzz

RESTRICTED_NAMES = {
    "auth_user",
    "sqlite_master",
    "sqlite_schema",
    "sqlite_temp_master",
    "sqlite_temp_schema",
}
_READ_ONLY_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}
_DENY = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}


def _fresh_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(
        "CREATE TABLE auth_user (id INTEGER, password TEXT);"
        "INSERT INTO auth_user VALUES (1, 'secret');"
        "CREATE TABLE orders (id INTEGER, name TEXT, amount REAL);"
        "INSERT INTO orders VALUES (1, 'a', 1.5);"
        "CREATE TABLE customers (id INTEGER, name TEXT);"
        "CREATE TABLE t (a, b); CREATE TABLE t1 (a, b); CREATE TABLE items (a, b);"
    )
    return db


class Oracle:
    def __init__(self) -> None:
        self.restricted_read = False
        self.writes: list[str] = []
        self.statements = 0
        self.functions: set[str] = set()


def run_oracle(sql: str) -> Oracle:
    o = Oracle()
    db = _fresh_db()
    # Authorizer events are only *pending* until the statement is actually stepped (the
    # trace callback fires): a statement that fails to prepare (syntax error) never
    # executes and so reads nothing.
    pending = {"read": False, "writes": []}

    def auth(action, a1, a2, dbname, src):
        if action == sqlite3.SQLITE_READ and (a1 or "").lower() in RESTRICTED_NAMES:
            pending["read"] = True
        elif action == sqlite3.SQLITE_FUNCTION:
            o.functions.add((a2 or "").lower())
        elif action not in _READ_ONLY_ACTIONS:
            pending["writes"].append(str(action))
            if action in _DENY:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def trace(stmt):
        if not stmt.lstrip().startswith("--"):
            o.statements += 1
            o.restricted_read = o.restricted_read or pending["read"]
            o.writes.extend(pending["writes"])
            pending["read"], pending["writes"] = False, []

    steps = {"n": 0}

    def progress():
        steps["n"] += 1
        return 1 if steps["n"] > 2000 else 0

    db.set_authorizer(auth)
    db.set_trace_callback(trace)
    db.set_progress_handler(progress, 100)
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000)
    try:
        # Authorization happens at prepare time, so reads are observed even when the
        # statement later fails (e.g. "no such table" in a deeper position).
        db.executescript(sql)
    except Exception:  # noqa: BLE001 - errors are expected for most mutated inputs
        pass
    finally:
        db.close()
    return o


def _dangerous(o: Oracle) -> bool:
    return o.restricted_read or bool(o.writes) or o.statements > 1


def _check(sql: str) -> bool:
    o = run_oracle(sql)
    if not _dangerous(o):
        return False
    for dialect in (None, "sqlite"):
        res = validate_sql_ast(sql, dialect=dialect)
        assert not res["valid"], (
            f"FALSE NEGATIVE (dialect={dialect}): {sql!r} accepted but SQLite "
            f"restricted_read={o.restricted_read} writes={o.writes} statements={o.statements}"
        )
    return True


@given(g.sql_inputs)
def test_no_false_negatives_vs_sqlite(sql: str) -> None:
    event(f"oracle dangerous: {_check(sql)}")


@pytest.mark.parametrize("sql", g.SEEDS)
def test_seed_corpus_vs_sqlite(sql: str) -> None:
    _check(sql)


def test_oracle_is_not_vacuous() -> None:
    """The oracle must actually flag the dangerous seeds (guards against a dead harness)."""
    assert run_oracle("SELECT * FROM auth_user").restricted_read
    assert run_oracle("SELECT * FROM 'auth_user'").restricted_read
    assert run_oracle("SELECT 1; SELECT 2").statements == 2
    assert run_oracle("SELECT 1; DROP TABLE orders").writes
    assert run_oracle("SELECT 1").statements == 1 and not _dangerous(
        run_oracle("SELECT 1")
    )
    dangerous = sum(_dangerous(run_oracle(s)) for s in g.SEEDS)
    assert dangerous >= 30
