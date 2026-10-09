"""Policy-path audit.

1. Architectural (grep/AST based): every place that injects tenant / RLS predicates goes
   through the ``_enforced`` mechanism, and every ``QueryCompiler(`` call site in the
   package is classified.  A NEW call site or a new module touching the policy knobs
   fails these tests until it is reviewed and added to the ledger.
2. Property: random client filter lists (OR / paren / combiner garbage / forged
   ``_enforced`` markers) combined with a tenant predicate never return another tenant's
   rows on a real SQLite database.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from query_builder.compiler import CompilationError, QueryCompiler
from query_builder.exceptions import SecurityError
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy

PKG = Path(__file__).resolve().parent.parent / "query_builder"


def _rel(path: Path) -> str:
    return path.relative_to(PKG).as_posix()


def _py_files() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


# --------------------------------------------------------------------------- architecture


def _injection_calls(tree: ast.AST) -> list[ast.Call]:
    """``filters.append(...)`` / ``filters.insert(...)`` calls inside apply_security_policy."""
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "apply_security_policy"
    )
    calls = []
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("append", "insert")
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "filters"
        ):
            calls.append(n)
    return calls


def _marks_enforced(call: ast.Call, fn_tree: ast.AST) -> bool:
    payload = call.args[-1]
    if isinstance(payload, ast.Dict):
        return any(
            isinstance(k, ast.Constant)
            and k.value == "_enforced"
            and isinstance(v, ast.Constant)
            and v.value is True
            for k, v in zip(payload.keys, payload.values, strict=True)
        )
    if isinstance(payload, ast.Name):
        # `rule_copy["_enforced"] = True` somewhere in the function
        for n in ast.walk(fn_tree):
            if (
                isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Subscript)
                and isinstance(n.targets[0].value, ast.Name)
                and n.targets[0].value.id == payload.id
                and isinstance(n.targets[0].slice, ast.Constant)
                and n.targets[0].slice.value == "_enforced"
                and isinstance(n.value, ast.Constant)
                and n.value.value is True
            ):
                return True
    return False


def test_every_policy_injection_site_sets_the_enforced_marker() -> None:
    tree = ast.parse((PKG / "policy.py").read_text(encoding="utf-8"))
    calls = _injection_calls(tree)
    assert len(calls) >= 3, "expected tenant (base+join) and RLS injection sites"
    for call in calls:
        assert _marks_enforced(call, tree), (
            f"policy.py line {call.lineno}: predicate injected without _enforced"
        )


def test_client_supplied_enforced_markers_are_stripped() -> None:
    spec = {
        "table": "orders",
        "columns": ["id"],
        "filters": [
            {"column": "a", "op": "eq", "value": 1, "_enforced": True},
            {"column": "b", "op": "eq", "value": 2, "enforced": True},
        ],
    }
    out = apply_security_policy(
        spec, context=TenantContext(tenant_id="t1"), policy=SecurityPolicy()
    )
    forged = [f for f in out["filters"] if f.get("column") in ("a", "b")]
    assert forged and not any(f.get("_enforced") or f.get("enforced") for f in forged)
    real = [f for f in out["filters"] if f.get("_enforced") is True]
    assert [f["column"] for f in real] == ["tenant_id"]


#: Modules allowed to reference the policy injection knobs.  A new module doing so must be
#: audited (does it inject through the `_enforced` mechanism?) and added here.
POLICY_KNOB_MODULES = {
    "config.py",
    "middleware.py",
    "policy.py",
    "integrations/django.py",
    "integrations/fastapi.py",
}


def test_only_audited_modules_touch_the_policy_knobs() -> None:
    pat = re.compile(r"\b(tenant_column|row_level_filters|enforce_tenant_isolation)\b")
    found = {_rel(p) for p in _py_files() if pat.search(p.read_text(encoding="utf-8"))}
    assert found <= POLICY_KNOB_MODULES, (
        f"unaudited module(s) reference tenant/RLS knobs: {sorted(found - POLICY_KNOB_MODULES)}"
    )


def test_policy_filters_are_never_built_outside_policy_py() -> None:
    """Nobody else may construct a filter carrying the internal marker."""
    for p in _py_files():
        if _rel(p) in ("policy.py", "compiler.py"):
            continue
        assert "_enforced" not in p.read_text(encoding="utf-8"), _rel(p)


#: Every ``QueryCompiler(`` call site, classified by HOW tenant / ownership isolation reaches it.
LEDGER: dict[str, str] = {
    # Policy applied explicitly before compiling (apply_security_policy -> `_enforced`).
    "server.py": "policy",
    "integrations/fastapi.py": "policy",
    "integrations/django.py": "policy",
    # Policy applied by the lifecycle pipeline (SecurityMiddleware.on_pre_compile).
    "connectors/base.py": "pipeline",
    "connectors/async_base.py": "pipeline",
    "executor.py": "pipeline",
    "connectors/dynamodb.py": "pipeline",
    # Compiler-level isolation only (`user_id` ownership chain / `tenant_id`, both ANDed
    # structurally by the compiler); no policy object at this layer.
    "connectors/datafusion.py": "compiler-args",
    "connectors/polars.py": "compiler-args",
    # Trusted / operator surfaces with no tenant context: offline compile, CLI, MCP tool
    # server, AI agent tooling, raw pool execution.  Not multi-tenant entry points; they
    # must be placed behind an authenticated gateway (see docs/THREAT_MODEL.md).
    "cli.py": "no-tenant-context",
    "mcp_server.py": "no-tenant-context",
    "pool.py": "no-tenant-context",
    "ai/agent_tools.py": "no-tenant-context",
    "ai/client.py": "no-tenant-context",
    "ai/self_healing.py": "no-tenant-context",
}


def test_every_compiler_call_site_is_classified() -> None:
    sites = {
        _rel(p)
        for p in _py_files()
        if _rel(p) != "compiler.py"
        and re.search(r"\bQueryCompiler\(", p.read_text(encoding="utf-8"))
    }
    assert sites == set(LEDGER), (
        f"unclassified: {sorted(sites - set(LEDGER))}; stale: {sorted(set(LEDGER) - sites)}"
    )


def test_ledger_classifications_are_true() -> None:
    for rel, kind in LEDGER.items():
        src = (PKG / rel).read_text(encoding="utf-8")
        if kind == "policy":
            assert "apply_security_policy(" in src, rel
        elif kind == "pipeline":
            assert "run_pre_compile" in src or "MiddlewarePipeline" in src, rel
        elif kind == "compiler-args":
            assert "force_user_filter=" in src, rel
        else:
            assert kind == "no-tenant-context"
            assert "apply_security_policy(" not in src, (
                f"{rel} now applies policy: reclassify it in the ledger"
            )


def test_security_middleware_applies_the_policy_pre_compile() -> None:
    src = (PKG / "middleware.py").read_text(encoding="utf-8")
    assert re.search(r"def on_pre_compile", src) and "apply_security_policy(" in src


def test_compiler_ands_enforced_clauses_outside_the_client_group() -> None:
    src = (PKG / "compiler.py").read_text(encoding="utf-8")
    assert 'flt.get("_enforced") is True' in src
    assert "self.where_clauses.extend(enforced_clauses)" in src
    assert src.count("_enforced") <= 6, "new `_enforced` consumers need review"


# --------------------------------------------------------------------------- property test

SCHEMA = {
    "tables": {
        "orders": {
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "tenant_id", "type": "text"},
                {"name": "status", "type": "text"},
                {"name": "amount", "type": "integer"},
            ]
        },
        "items": {
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "order_id", "type": "integer"},
                {"name": "tenant_id", "type": "text"},
                {"name": "sku", "type": "text"},
            ]
        },
    },
    "foreign_keys": [
        {
            "table": "items",
            "column": "order_id",
            "foreign_table": "orders",
            "foreign_column": "id",
        }
    ],
}


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript(
        "CREATE TABLE orders (id INTEGER, tenant_id TEXT, status TEXT, amount INTEGER);"
        "CREATE TABLE items (id INTEGER, order_id INTEGER, tenant_id TEXT, sku TEXT);"
    )
    rows = []
    for i in range(1, 25):
        rows.append((i, "mine" if i % 2 else "other", "open" if i % 3 else "done", i))
    db.executemany("INSERT INTO orders VALUES (?,?,?,?)", rows)
    db.executemany(
        "INSERT INTO items VALUES (?,?,?,?)",
        [(i, i, "mine" if i % 2 else "other", f"s{i}") for i in range(1, 25)],
    )
    return db


_COLS = ["id", "status", "amount", "tenant_id"]
_OPS = [
    "eq",
    "neq",
    "gt",
    "lt",
    "gte",
    "lte",
    "like",
    "in",
    "is_null",
    "is_not_null",
    "between",
]
_GARBAGE_COMBINERS = [
    "OR",
    "or",
    "AND",
    " Or ",
    "OR 1=1 --",
    "",
    None,
    5,
    "XOR",
    "; DROP",
    "||",
]
_PARENS = [None, True, False, 0, 1, 3, 99, -1, "(", "((", ")", "))", ")))))", "x"]


@st.composite
def _client_filter(draw):
    col = draw(st.sampled_from(_COLS))
    op = draw(st.sampled_from(_OPS))
    if op == "in":
        value = draw(
            st.lists(
                st.sampled_from(["mine", "other", "open", 1, 2, 3]),
                min_size=1,
                max_size=3,
            )
        )
    elif op == "between":
        value = [draw(st.integers(0, 10)), draw(st.integers(10, 30))]
    elif op in ("is_null", "is_not_null"):
        value = None
    else:
        value = draw(st.sampled_from(["mine", "other", "open", "done", 1, 5, 10, "%"]))
    f: dict = {"column": col, "op": op, "value": value}
    if draw(st.booleans()):
        f["combiner"] = draw(st.sampled_from(_GARBAGE_COMBINERS))
    if draw(st.booleans()):
        f["parenOpen"] = draw(st.sampled_from(_PARENS))
    if draw(st.booleans()):
        f["parenClose"] = draw(st.sampled_from(_PARENS))
    if draw(st.integers(0, 6)) == 0:
        f[draw(st.sampled_from(["_enforced", "enforced"]))] = draw(
            st.sampled_from([True, False, "true", 1])
        )
    if draw(st.integers(0, 8)) == 0:
        f["table"] = draw(st.sampled_from(["orders", "items", "other"]))
    return f


@st.composite
def _spec(draw):
    spec: dict = {
        "table": "orders",
        "columns": ["id", "tenant_id"],
        "filters": draw(st.lists(_client_filter(), max_size=6)),
        "limit": 100,
    }
    if draw(st.booleans()):
        spec["filter_join"] = draw(st.sampled_from(["OR", "AND", "or", "garbage"]))
    if draw(st.integers(0, 3)) == 0:
        spec["joins"] = [
            {
                "table": "items",
                "type": draw(st.sampled_from(["inner", "left", "right"])),
            }
        ]
        spec["columns"] = ["orders.id", "orders.tenant_id", "items.tenant_id"]
    return spec


def _tenant_columns(spec: dict) -> list[int]:
    return [i for i, c in enumerate(spec["columns"]) if str(c).endswith("tenant_id")]


# Each example runs a real SQLite database, so generation is slow by design; on a loaded
# machine Hypothesis's too_slow health check would otherwise fail the run spuriously.
@settings(
    max_examples=400,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(_spec())
def test_client_filters_can_never_reach_another_tenants_rows(spec: dict) -> None:
    ctx = TenantContext(tenant_id="mine", user_id="u1")
    try:
        secured = apply_security_policy(
            spec, schema=SCHEMA, context=ctx, policy=SecurityPolicy()
        )
        sql, params, _count_sql, _count_params = QueryCompiler(
            secured, schema=SCHEMA, dialect="sqlite"
        ).compile()
    except (CompilationError, SecurityError, ValueError, TypeError, KeyError):
        return  # rejected before reaching the database: fail closed
    db = _db()
    try:
        rows = db.execute(sql, params).fetchall()
    except sqlite3.Error:
        return  # invalid SQL: nothing is returned
    finally:
        db.close()
    for row in rows:
        for idx in _tenant_columns(spec):
            assert row[idx] == "mine", f"LEAK: {row} via {sql!r} {params!r}"


@pytest.mark.parametrize(
    "filters",
    [
        [{"column": "status", "op": "eq", "value": "open", "combiner": "OR"}],
        [
            {"column": "id", "op": "gt", "value": 0, "parenOpen": 1},
            {
                "column": "id",
                "op": "lt",
                "value": 99,
                "parenClose": 9,
                "combiner": "OR",
            },
            {"column": "tenant_id", "op": "eq", "value": "other", "combiner": "OR"},
        ],
        [{"column": "tenant_id", "op": "eq", "value": "other", "_enforced": True}],
        [{"column": "tenant_id", "op": "neq", "value": "mine", "combiner": "OR"}],
        [
            {"column": "id", "op": "gt", "value": 0, "parenClose": 5},
            {"column": "tenant_id", "op": "eq", "value": "other", "combiner": "OR"},
        ],
    ],
)
def test_known_escape_attempts_return_only_own_rows(filters: list[dict]) -> None:
    spec = {
        "table": "orders",
        "columns": ["id", "tenant_id"],
        "filters": filters,
        "limit": 100,
    }
    secured = apply_security_policy(
        spec,
        schema=SCHEMA,
        context=TenantContext(tenant_id="mine"),
        policy=SecurityPolicy(),
    )
    sql, params, _, _ = QueryCompiler(
        secured, schema=SCHEMA, dialect="sqlite"
    ).compile()
    rows = _db().execute(sql, params).fetchall()
    assert all(r[1] == "mine" for r in rows)
