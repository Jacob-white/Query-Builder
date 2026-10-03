"""
Tests for Security Policy & Fail-Closed RLS Policy Engine.
==========================================================
Verifies tenant isolation, table allow/denylists, dynamic attribute resolution,
column masking, fail-closed enforcement, and full branch coverage.
"""

from __future__ import annotations

import pytest

from query_builder.models import (
    FilterSpec,
    JoinSpec,
    QuerySpec,
    SchemaSnapshot,
)
from query_builder.policy import (
    SecurityPolicy,
    TenantContext,
    apply_security_policy,
)
from query_builder.security import SecurityError


def test_tenant_context_creation():
    ctx = TenantContext(tenant_id="tenant_1")
    assert ctx.tenant_id == "tenant_1"
    assert ctx.user_id is None
    assert ctx.roles == []
    assert ctx.attributes == {}

    custom = TenantContext(
        tenant_id="t1",
        user_id="u1",
        roles=["analyst"],
        attributes={"dept": "finance"},
    )
    assert custom.user_id == "u1"
    assert custom.roles == ["analyst"]
    assert custom.attributes["dept"] == "finance"


def test_security_policy_creation():
    policy = SecurityPolicy()
    assert policy.enforce_tenant_isolation is True
    assert policy.tenant_column == "tenant_id"
    assert policy.allowed_tables is None
    assert policy.restricted_tables == []

    custom = SecurityPolicy(
        allowed_tables=["users", "orders"],
        restricted_tables=["secrets"],
        tenant_column="org_id",
        enforce_tenant_isolation=False,
    )
    assert custom.allowed_tables == ["users", "orders"]
    assert custom.tenant_column == "org_id"
    assert custom.enforce_tenant_isolation is False


def test_apply_policy_injects_tenant_filter():
    spec = {"table": "orders", "columns": ["id", "amount"]}
    ctx = TenantContext(tenant_id="t_100")
    result = apply_security_policy(spec, context=ctx)
    assert len(result["filters"]) == 1
    flt = result["filters"][0]
    assert flt["column"] == "tenant_id"
    assert flt["op"] == "eq"
    assert flt["value"] == "t_100"
    assert flt["table"] == "orders"


def test_apply_policy_preserves_existing_filters():
    spec = {
        "table": "orders",
        "filters": [{"column": "status", "op": "eq", "value": "shipped"}],
    }
    ctx = TenantContext(tenant_id="t_100")
    result = apply_security_policy(spec, context=ctx)
    assert len(result["filters"]) == 2
    assert result["filters"][0]["column"] == "tenant_id"
    assert result["filters"][1]["column"] == "status"


def test_apply_policy_does_not_duplicate_tenant_filter():
    spec = {
        "table": "orders",
        "filters": [
            {
                "column": "tenant_id",
                "op": "eq",
                "value": "t_100",
                "table": "orders",
            }
        ],
    }
    ctx = TenantContext(tenant_id="t_100")
    result = apply_security_policy(spec, context=ctx)
    assert len(result["filters"]) == 1


def test_apply_policy_with_query_spec_dataclass():
    qspec = QuerySpec(
        table="users",
        columns=["id", "email"],
        filters=[FilterSpec(column="active", op="eq", value=True)],
    )
    ctx = TenantContext(tenant_id="t_200")
    result = apply_security_policy(qspec, context=ctx)
    assert isinstance(result, dict)
    assert result["table"] == "users"
    assert len(result["filters"]) == 2
    assert result["filters"][0]["column"] == "tenant_id"


def test_fail_closed_missing_context():
    spec = {"table": "users"}
    with pytest.raises(SecurityError, match="no TenantContext provided"):
        apply_security_policy(spec, context=None)


def test_fail_closed_empty_tenant_id():
    spec = {"table": "users"}
    with pytest.raises(SecurityError, match="tenant_id is missing or empty"):
        apply_security_policy(spec, context=TenantContext(tenant_id=""))

    with pytest.raises(SecurityError, match="tenant_id is missing or empty"):
        apply_security_policy(spec, context=TenantContext(tenant_id="   "))


def test_allowed_tables_permitted():
    policy = SecurityPolicy(allowed_tables=["users", "orders"])
    ctx = TenantContext(tenant_id="t1")
    spec = {"table": "users"}
    res = apply_security_policy(spec, context=ctx, policy=policy)
    assert res["table"] == "users"


def test_allowed_tables_forbidden():
    policy = SecurityPolicy(allowed_tables=["users", "orders"])
    ctx = TenantContext(tenant_id="t1")

    # Base table forbidden
    with pytest.raises(SecurityError, match="forbidden by allowed_tables"):
        apply_security_policy({"table": "salaries"}, context=ctx, policy=policy)

    # Joined table forbidden
    with pytest.raises(SecurityError, match="forbidden by allowed_tables"):
        apply_security_policy(
            {
                "table": "users",
                "joins": [{"table": "salaries", "type": "INNER"}],
            },
            context=ctx,
            policy=policy,
        )


def test_restricted_tables_forbidden():
    policy = SecurityPolicy(restricted_tables=["admin_passwords"])
    ctx = TenantContext(tenant_id="t1")
    with pytest.raises(SecurityError, match="restricted table"):
        apply_security_policy({"table": "admin_passwords"}, context=ctx, policy=policy)


def test_restricted_tables_joined_table_forbidden():
    policy = SecurityPolicy(restricted_tables=["admin_secrets"])
    ctx = TenantContext(tenant_id="t1")
    with pytest.raises(SecurityError, match="restricted table"):
        apply_security_policy(
            {
                "table": "users",
                "joins": [JoinSpec(table="admin_secrets", type="LEFT")],
            },
            context=ctx,
            policy=policy,
        )


def test_row_level_filters_injected():
    policy = SecurityPolicy(
        row_level_filters={
            "orders": [{"column": "status", "op": "eq", "value": "active"}]
        }
    )
    ctx = TenantContext(tenant_id="t1")
    res = apply_security_policy({"table": "orders"}, context=ctx, policy=policy)
    # 1 tenant filter + 1 row level filter
    assert len(res["filters"]) == 2
    assert res["filters"][1]["column"] == "status"
    assert res["filters"][1]["value"] == "active"


def test_dynamic_attribute_resolution():
    policy = SecurityPolicy(
        row_level_filters={
            "orders": [
                {"column": "owner_id", "op": "eq", "value": "$user_id"},
                {"column": "org_code", "op": "eq", "value": "$tenant_id"},
                {"column": "region", "op": "eq", "value": "$attr.region"},
            ]
        }
    )
    ctx = TenantContext(
        tenant_id="t_dyn",
        user_id="u_dyn",
        attributes={"region": "US-EAST"},
    )
    res = apply_security_policy({"table": "orders"}, context=ctx, policy=policy)
    filters = res["filters"]
    assert any(
        f.get("column") == "owner_id" and f.get("value") == "u_dyn" for f in filters
    )
    assert any(
        f.get("column") == "org_code" and f.get("value") == "t_dyn" for f in filters
    )
    assert any(
        f.get("column") == "region" and f.get("value") == "US-EAST" for f in filters
    )


def test_column_masking_applied():
    policy = SecurityPolicy(column_masking={"employees": ["ssn", "salary"]})
    ctx = TenantContext(tenant_id="t1", roles=["viewer"])
    spec = {
        "table": "employees",
        "columns": [
            "id",
            "name",
            "ssn",
            {"column": "salary", "table": "employees"},
            123,  # non-string, non-dict column passthrough
        ],
    }
    res = apply_security_policy(spec, context=ctx, policy=policy)
    cols = res["columns"]
    assert cols[0] == "id"
    assert cols[1] == "name"
    assert cols[2] == {"column": "ssn", "alias": "ssn_masked", "masked": True}
    assert cols[3] == {
        "column": "salary",
        "table": "employees",
        "alias": "salary_masked",
        "masked": True,
    }
    assert cols[4] == 123


def test_column_masking_bypassed_for_admin():
    policy = SecurityPolicy(column_masking={"employees": ["ssn", "salary"]})
    ctx = TenantContext(tenant_id="t1", roles=["ADMIN"])
    spec = {
        "table": "employees",
        "columns": ["id", "ssn", {"column": "salary"}],
    }
    res = apply_security_policy(spec, context=ctx, policy=policy)
    assert res["columns"] == ["id", "ssn", {"column": "salary"}]


def test_apply_policy_missing_table_raises():
    ctx = TenantContext(tenant_id="t1")
    with pytest.raises(SecurityError, match="missing required 'table'"):
        apply_security_policy({"table": ""}, context=ctx)

    with pytest.raises(SecurityError, match="missing required 'table'"):
        apply_security_policy({}, context=ctx)

    with pytest.raises(SecurityError, match="Unsupported spec type"):
        apply_security_policy(12345, context=ctx)  # type: ignore


def test_policy_joins_schema_awareness():
    schema = SchemaSnapshot(
        tables={
            "accounts": {"columns": [{"name": "id"}, {"name": "tenant_id"}]},
            "audit_log": {
                "columns": [{"name": "id"}]  # No tenant_id column!
            },
        }
    )
    policy = SecurityPolicy()
    ctx = TenantContext(tenant_id="t_join")
    spec = {
        "table": "orders",
        "joins": [
            {"table": "accounts", "type": "LEFT"},
            {"table": "audit_log", "type": "LEFT"},
        ],
    }
    res = apply_security_policy(spec, schema=schema, context=ctx, policy=policy)
    filters = res["filters"]
    # Should inject tenant filter for 'orders' and 'accounts', but NOT for 'audit_log'
    tables_filtered = [f.get("table") for f in filters]
    assert "orders" in tables_filtered
    assert "accounts" in tables_filtered
    assert "audit_log" not in tables_filtered


def test_policy_as_dict():
    policy_dict = {"enforce_tenant_isolation": False}
    res = apply_security_policy({"table": "public_data"}, policy=policy_dict)
    assert res["table"] == "public_data"


def test_policy_join_with_non_string_table():
    ctx = TenantContext(tenant_id="t1")
    spec = {"table": "users", "joins": [{"table": None}, {"invalid": 1}]}
    res = apply_security_policy(spec, context=ctx)
    assert res["table"] == "users"


def test_policy_existing_filter_with_table_prefix():
    ctx = TenantContext(tenant_id="t1")
    spec = {
        "table": "users",
        "filters": [
            {
                "column": "tenant_id",
                "op": "eq",
                "value": "t1",
                "tablePrefix": "users",
            }
        ],
    }
    res = apply_security_policy(spec, context=ctx)
    assert len(res["filters"]) == 1


def test_policy_join_with_existing_tenant_filter():
    ctx = TenantContext(tenant_id="t1")
    spec = {
        "table": "orders",
        "joins": [{"table": "items"}],
        "filters": [
            {
                "column": "tenant_id",
                "op": "eq",
                "value": "t1",
                "tablePrefix": "items",
            }
        ],
    }
    res = apply_security_policy(spec, context=ctx)
    # 1 for orders (injected), 1 existing for items
    assert len(res["filters"]) == 2


def test_policy_join_table_not_in_schema():
    schema = {"tables": {"other": {"columns": []}}}
    ctx = TenantContext(tenant_id="t1")
    spec = {"table": "orders", "joins": [{"table": "items"}]}
    res = apply_security_policy(spec, schema=schema, context=ctx)
    # Injected for both since items is not explicitly lacking tenant_column in schema
    assert len(res["filters"]) == 2


def test_policy_row_level_filter_with_existing_table_prefix():
    policy = SecurityPolicy(
        row_level_filters={
            "orders": [
                {
                    "column": "flag",
                    "op": "eq",
                    "value": 1,
                    "tablePrefix": "orders",
                }
            ]
        }
    )
    ctx = TenantContext(tenant_id="t1")
    res = apply_security_policy({"table": "orders"}, context=ctx, policy=policy)
    assert len(res["filters"]) == 2


def test_policy_column_masking_dict_unmasked_and_qualified():
    policy = SecurityPolicy(column_masking={"users": ["ssn"]})
    ctx = TenantContext(tenant_id="t1", roles=["viewer"])
    spec = {
        "table": "users",
        "columns": [
            {"column": "unmasked_column"},
            "users.ssn",  # Qualified string column
        ],
    }
    res = apply_security_policy(spec, context=ctx, policy=policy)
    cols = res["columns"]
    assert cols[0] == {"column": "unmasked_column"}
    assert cols[1] == {"column": "ssn", "alias": "ssn_masked", "masked": True}


def test_policy_join_with_empty_schema_dict():
    ctx = TenantContext(tenant_id="t1")
    spec = {"table": "orders", "joins": [{"table": "items"}]}
    res = apply_security_policy(spec, schema={}, context=ctx)
    assert len(res["filters"]) == 2
