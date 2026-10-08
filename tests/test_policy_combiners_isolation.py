"""Policy predicates (tenant / RLS) must stay outside the client's filter group."""

from __future__ import annotations

import sqlite3

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.nlq.validator import NlqAstValidator
from query_builder.parser import parse_sql_to_spec
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy

CTX = TenantContext(tenant_id="acme", user_id="u1")


def _f(col: str, val: object, combiner: str | None = None, **kw: object) -> dict:
    d: dict = {"column": col, "op": "eq", "value": val}
    if combiner is not None:
        d["combiner"] = combiner
    d.update(kw)
    return d


def _compile(spec: dict, policy: SecurityPolicy | None = None):
    secured = apply_security_policy(
        spec, context=CTX, policy=policy or SecurityPolicy()
    )
    return QueryCompiler(secured, dialect="sqlite").compile()


def _where(sql: str) -> str:
    return sql.split("WHERE", 1)[1].split("LIMIT")[0]


def test_mixed_and_or_keeps_tenant_outside_group() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filters": [_f("a", 1, "AND"), _f("b", 2, "AND"), _f("c", 3, "OR")],
    }
    sql, params, count_sql, count_params = _compile(spec)
    w = _where(sql)
    assert '"tenant_id" = ? AND (' in w
    assert w.count("(") == 1 and w.rstrip().endswith(")")
    assert "OR" in w.split("AND (", 1)[1]
    assert params[:4] == ["acme", 1, 2, 3]
    assert count_params == params[:4]
    assert '"tenant_id" = ? AND (' in count_sql


def test_filter_join_or_does_not_or_tenant() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filter_join": "OR",
        "filters": [_f("a", 1), _f("b", 2)],
    }
    sql, params, _, _ = _compile(spec)
    assert '"tenant_id" = ? AND (' in _where(sql)
    assert params[:3] == ["acme", 1, 2]


def test_hidden_first_filter_or_combiner_is_harmless() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filters": [_f("a", 1, "OR"), _f("b", 2, "OR")],
    }
    sql, _, _, _ = _compile(spec)
    assert '"tenant_id" = ? AND (' in _where(sql)


def test_rls_rules_and_ed_outside_group() -> None:
    policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        row_level_filters={
            "orders": [{"column": "owner", "op": "eq", "value": "$user_id"}]
        },
    )
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filter_join": "OR",
        "filters": [_f("a", 1), _f("b", 2)],
    }
    sql, params, _, _ = _compile(spec, policy)
    assert '"owner" = ? AND (' in _where(sql)
    assert params[:3] == ["u1", 1, 2]


def test_rls_rule_combiner_ignored() -> None:
    policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        row_level_filters={
            "orders": [
                {"column": "owner", "op": "eq", "value": "$user_id", "combiner": "OR"}
            ]
        },
    )
    spec = {"table": "orders", "columns": ["id"], "filters": [_f("a", 1, "OR")]}
    sql, _, _, _ = _compile(spec, policy)
    assert " OR " not in _where(sql)


def test_forged_enforced_flag_stripped_and_tenant_still_injected() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filters": [
            _f("region", "x", "AND", _enforced=True, enforced=True),
            _f("c", 3, "OR"),
        ],
    }
    secured = apply_security_policy(spec, context=CTX, policy=SecurityPolicy())
    assert sum(1 for f in secured["filters"] if f.get("_enforced")) == 1
    assert all("enforced" not in f for f in secured["filters"])
    sql, _, _, _ = QueryCompiler(secured, dialect="sqlite").compile()
    w = _where(sql)
    # The forged-flag client predicate stays inside the OR-able group.
    assert '"tenant_id" = ? AND (' in w
    assert w.count("region") == 1 and w.index("region") > w.index("AND (")
    assert "OR" in w.split("AND (", 1)[1]


def test_unbalanced_client_parens_cannot_escape_group() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filters": [
            _f("a", 1, "AND", parenClose=3),
            _f("b", 2, "OR", parenOpen=True),
        ],
    }
    sql, _, _, _ = _compile(spec)
    w = _where(sql)
    depth = 0
    for ch in w:
        depth += ch == "("
        depth -= ch == ")"
        assert depth >= 0
    assert depth == 0
    assert '"tenant_id" = ? AND (' in w


def test_invalid_combiner_falls_back_to_filter_join() -> None:
    spec = {
        "table": "t",
        "columns": ["id"],
        "filter_join": "garbage",
        "filters": [_f("a", 1, "XOR; DROP"), _f("b", 2, "nope")],
    }
    sql, _, _, _ = QueryCompiler(spec, dialect="sqlite").compile()
    assert "XOR" not in sql and "DROP" not in sql and "garbage" not in sql
    assert " AND " in _where(sql) and " OR " not in _where(sql)


def test_join_tenant_predicate_enforced() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "joins": [
            {
                "table": "items",
                "type": "INNER",
                "left_col": "id",
                "right_col": "order_id",
            }
        ],
        "filter_join": "OR",
        "filters": [_f("a", 1), _f("b", 2)],
    }
    sql, params, _, _ = _compile(spec)
    w = _where(sql)
    assert w.count('"tenant_id" = ?') == 2
    assert w.index("AND (") > w.rindex('"tenant_id" = ?')
    assert params[:4] == ["acme", "acme", 1, 2]


def test_end_to_end_sqlite_no_cross_tenant_rows(tmp_path) -> None:
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from query_builder.connectors.sqlite import SQLiteConnector
    from query_builder.integrations.fastapi import create_query_builder_router

    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE orders (id INTEGER, tenant_id TEXT, a INTEGER, b INTEGER, c INTEGER)"
    )
    con.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?)",
        [
            (1, "acme", 1, 1, 0),
            (2, "acme", 0, 0, 0),
            (3, "other", 0, 0, 1),
            (4, "other", 1, 1, 1),
        ],
    )
    con.commit()
    con.close()

    connector = SQLiteConnector(str(db), check_same_thread=False)
    app = FastAPI()
    app.include_router(
        create_query_builder_router(connector, tenant_resolver=lambda r: "acme")
    )
    client = TestClient(app)

    bodies = [
        {"filters": [_f("a", 1, "AND"), _f("b", 1, "AND"), _f("c", 1, "OR")]},
        {"filter_join": "OR", "filters": [_f("a", 1), _f("c", 1)]},
        {"filters": [_f("c", 1, "OR"), _f("a", 1, "OR")]},
    ]
    for extra in bodies:
        spec = {"table": "orders", "columns": ["id", "tenant_id"], **extra}
        resp = client.post("/execute", json={"spec": spec})
        assert resp.status_code == 200, resp.text
        flat = str(resp.json())
        assert "other" not in flat, flat
        assert "acme" in flat, flat


def test_nlq_validator_preserves_combiner_equals_compiler() -> None:
    spec = {
        "table": "t",
        "columns": ["id"],
        "filter_join": "OR",
        "filters": [_f("a", 1, "AND"), _f("b", 2, "AND"), _f("c", 3, "OR")],
    }
    direct = QueryCompiler(spec, dialect="sqlite").compile()[0]
    assert direct.count(" OR ") == 1
    validated, _ = NlqAstValidator(schema=None).validate(spec)
    assert [f.get("combiner") for f in validated["filters"]] == ["AND", "AND", "OR"]
    via = QueryCompiler(validated, dialect="sqlite").compile()[0]
    assert via.count(" OR ") == 1 and via.count(" AND ") == direct.count(" AND ")


def test_validator_drops_invalid_combiner() -> None:
    spec = {
        "table": "t",
        "columns": ["id"],
        "filters": [_f("a", 1, "evil"), _f("b", 2, "or")],
    }
    validated, _ = NlqAstValidator(schema=None).validate(spec)
    assert "combiner" not in validated["filters"][0]
    assert validated["filters"][1]["combiner"] == "OR"


def test_parse_roundtrip_preserves_precedence() -> None:
    spec = parse_sql_to_spec("SELECT id FROM t WHERE a = 1 AND b = 2 OR c = 3")
    assert spec.filter_join == "OR"
    assert [f.combiner for f in spec.filters] == ["AND", "AND", "OR"]
    sql = QueryCompiler(spec.to_dict(), dialect="sqlite").compile()[0]
    w = _where(sql)
    assert w.count(" AND ") == 1 and w.count(" OR ") == 1
    assert w.index(" AND ") < w.index(" OR ")


def test_parse_all_and_emits_no_combiners() -> None:
    spec = parse_sql_to_spec("SELECT id FROM t WHERE a = 1 AND b = 2")
    assert spec.filter_join == "AND"
    assert all(f.combiner is None for f in spec.filters)
