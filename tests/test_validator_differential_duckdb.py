"""Differential test: validator vs DuckDB's own parser (oracle 2a).

``duckdb.extract_statements`` yields the statement list and kinds; ``json_serialize_sql``
yields the real parse tree of a SELECT (parse only, nothing is executed).  Invariant (NO
FALSE NEGATIVES): if DuckDB shows more than one statement, a non-SELECT statement, a
restricted base table (not shadowed by a CTE) or a file-reading/dangerous table function,
``validate_sql_ast`` must reject, for ``dialect="duckdb"`` and ``dialect=None``.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import event, given

from query_builder.ast_validator import validate_sql_ast
from tests import _sqlgen as g

duckdb = pytest.importorskip("duckdb")

pytestmark = pytest.mark.fuzz

RESTRICTED_RELS = {"auth_user", "sqlite_master", "pg_class"}
RESTRICTED_SCHEMAS = {"pg_catalog", "information_schema", "public"}
DANGEROUS = (
    "read_csv",
    "read_parquet",
    "read_json",
    "read_text",
    "read_blob",
    "query",
    "query_table",
    "sniff_csv",
    "glob",
    "pragma_",
    "load_extension",
    "pg_sleep",
    "sleep",
)

_CONN = duckdb.connect()


def _walk(node, out):
    if isinstance(node, dict):
        out.append(node)
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def duck_findings(sql: str) -> list[str] | None:
    try:
        stmts = duckdb.extract_statements(sql)
    except Exception:  # noqa: BLE001 - not valid DuckDB
        return None
    reasons: list[str] = []
    if len(stmts) > 1:
        reasons.append("multiple statements")
    for s in stmts:
        if s.type != duckdb.StatementType.SELECT:
            reasons.append(f"statement type {s.type}")
    if reasons or len(stmts) != 1:
        return reasons
    try:
        raw = _CONN.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
        tree = json.loads(raw)
    except Exception:  # noqa: BLE001
        return reasons
    if tree.get("error"):
        return reasons
    nodes: list[dict] = []
    _walk(tree, nodes)
    ctes = {
        e.get("key", "").lower()
        for n in nodes
        for e in (n.get("cte_map", {}) or {}).get("map", [])
        if isinstance(e, dict)
    }
    for n in nodes:
        t = n.get("type")
        if t == "BASE_TABLE":
            rel = str(n.get("table_name", "")).lower()
            schema = str(n.get("schema_name", "")).lower()
            if schema in RESTRICTED_SCHEMAS:
                reasons.append(f"restricted schema {schema}")
            if rel in RESTRICTED_RELS and not (rel in ctes and not schema):
                reasons.append(f"restricted relation {rel}")
            if "/" in rel or rel.endswith((".csv", ".parquet", ".json")):
                reasons.append(f"file replacement scan {rel}")
        elif "function_name" in n:
            fn = str(n["function_name"]).lower()
            if fn.startswith(DANGEROUS):
                reasons.append(f"dangerous function {fn}")
    return reasons


def _check(sql: str) -> bool:
    reasons = duck_findings(sql)
    if not reasons:
        return False
    for dialect in (None, "duckdb"):
        res = validate_sql_ast(sql, dialect=dialect)
        assert not res["valid"], (
            f"FALSE NEGATIVE (dialect={dialect}): {sql!r} accepted; DuckDB parse shows {reasons}"
        )
    return True


@given(g.sql_inputs)
def test_no_false_negatives_vs_duckdb_parser(sql: str) -> None:
    event(f"duckdb dangerous: {_check(sql)}")


@pytest.mark.parametrize(
    "sql",
    g.SEEDS
    + [
        "FROM auth_user",
        "SELECT * FROM 'data.csv'",
        "SELECT * FROM read_csv_auto('x')",
    ],
)
def test_seed_corpus_vs_duckdb_parser(sql: str) -> None:
    _check(sql)


def test_oracle_is_not_vacuous() -> None:
    assert duck_findings("SELECT * FROM auth_user")
    assert duck_findings("FROM auth_user")  # DuckDB FROM-first syntax
    assert duck_findings("TABLE auth_user")
    assert duck_findings("SELECT 1; SELECT 2")
    assert duck_findings("SELECT 1; DROP TABLE x")
    assert duck_findings("SELECT * FROM read_csv('x')")
    assert duck_findings("SELECT * FROM 'a.csv'")
    assert duck_findings("SELECT 1 FROM orders") == []
    assert sum(bool(duck_findings(s)) for s in g.SEEDS) >= 30
