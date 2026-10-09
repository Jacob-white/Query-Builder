"""Differential test: validator vs the real PostgreSQL parser (oracle 2b, ``pglast``).

``pglast`` embeds libpg_query, i.e. the actual PostgreSQL grammar.  For every input that
PostgreSQL parses we extract the statement list, statement kinds, relations (RangeVar),
CTE names and function calls from the real parse tree, and assert NO FALSE NEGATIVES: if
the tree shows a second statement, a non-SELECT statement, SELECT INTO / locking, a DML
node, a restricted relation/schema, or a dangerous function, ``validate_sql_ast`` must
reject (for ``dialect="postgres"`` and for ``dialect=None``).
"""

from __future__ import annotations

import json

import pytest
from hypothesis import event, given

from query_builder.ast_validator import validate_sql_ast
from tests import _sqlgen as g

pglast_parser = pytest.importorskip("pglast.parser")

pytestmark = pytest.mark.fuzz

RESTRICTED_RELS = {
    "auth_user",
    "pg_class",
    "pg_shadow",
    "pg_authid",
    "pg_roles",
    "pg_user",
    "sqlite_master",
}
RESTRICTED_SCHEMAS = {"pg_catalog", "information_schema", "public"}
DANGEROUS_FUNCS = {
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "query_to_xml",
    "pg_sleep",
    "set_config",
    "pg_terminate_backend",
    "load_file",
}
DML_NODES = {"InsertStmt", "UpdateStmt", "DeleteStmt", "MergeStmt"}


def _walk(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            out.append((k, v))
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def pg_findings(sql: str) -> list[str] | None:
    """Danger reasons according to PostgreSQL's own parser, or None if it won't parse."""
    try:
        tree = json.loads(pglast_parser.parse_sql_json(sql))
    except Exception:  # noqa: BLE001 - not valid PostgreSQL
        return None
    reasons: list[str] = []
    stmts = tree.get("stmts", [])
    if len(stmts) > 1:
        reasons.append("multiple statements")
    for s in stmts:
        kind = next(iter(s.get("stmt", {})), None)
        if kind != "SelectStmt":
            reasons.append(f"statement kind {kind}")
    nodes: list = []
    _walk(tree, nodes)
    ctes = {v.get("ctename", "").lower() for k, v in nodes if k == "CommonTableExpr"}
    for k, v in nodes:
        if k == "SelectStmt":
            if v.get("intoClause"):
                reasons.append("SELECT INTO")
            if v.get("lockingClause"):
                reasons.append("locking clause")
        elif k in DML_NODES:
            reasons.append(f"DML {k}")
        elif k == "RangeVar":
            rel = v.get("relname", "").lower()
            schema = v.get("schemaname", "").lower()
            if schema in RESTRICTED_SCHEMAS:
                reasons.append(f"restricted schema {schema}")
            if rel in RESTRICTED_RELS and not (rel in ctes and not schema):
                reasons.append(f"restricted relation {rel}")
        elif k == "FuncCall":
            names = [
                f.get("String", {}).get("sval", "").lower()
                for f in v.get("funcname", [])
            ]
            if names and names[-1] in DANGEROUS_FUNCS:
                reasons.append(f"dangerous function {names[-1]}")
    return reasons


def _check(sql: str) -> bool:
    reasons = pg_findings(sql)
    if not reasons:
        return False
    for dialect in (None, "postgres"):
        res = validate_sql_ast(sql, dialect=dialect)
        assert not res["valid"], (
            f"FALSE NEGATIVE (dialect={dialect}): {sql!r} accepted; PostgreSQL parse shows {reasons}"
        )
    return True


@given(g.sql_inputs)
def test_no_false_negatives_vs_postgres_parser(sql: str) -> None:
    event(f"pg dangerous: {_check(sql)}")


@pytest.mark.parametrize("sql", g.SEEDS)
def test_seed_corpus_vs_postgres_parser(sql: str) -> None:
    _check(sql)


def test_oracle_is_not_vacuous() -> None:
    assert pg_findings("SELECT * FROM auth_user")
    assert pg_findings("TABLE auth_user")  # TABLE x is a SelectStmt in PostgreSQL
    assert pg_findings("SELECT 1; SELECT 2")
    assert pg_findings("SELECT pg_read_file('x')")
    assert pg_findings("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")
    assert pg_findings("SELECT 1 FROM orders") == []
    assert pg_findings("SELEKT") is None
    assert sum(bool(pg_findings(s)) for s in g.SEEDS) >= 30
