"""
Tests for Enterprise Governance & Fine-Grained Security:
- Pre-execution Complexity Quota Governor (max_complexity_score)
- Role-Based Column-Level Access Control (CLAC)
- Multi-dimensional ABAC / RLS dynamic attribute filters
"""

import pytest
from query_builder import (
    SecurityPolicy,
    TenantContext,
    apply_security_policy,
)
from query_builder.security import SecurityError


class TestEnterpriseGovernance:
    def test_complexity_quota_governor_allowed(self):
        policy = SecurityPolicy(max_complexity_score=50, enforce_tenant_isolation=False)
        spec = {
            "table": "users",
            "columns": ["id", "name"],
            "limit": 10,
        }
        res = apply_security_policy(spec, policy=policy)
        assert res["table"] == "users"

    def test_complexity_quota_governor_exceeded(self):
        # Very low ceiling (spec complexity is 14)
        policy = SecurityPolicy(max_complexity_score=10, enforce_tenant_isolation=False)
        spec = {
            "table": "users",
            "columns": ["id", "name"],
            "joins": [
                {"table": "orders", "type": "LEFT", "left_col": "id", "right_col": "user_id"},
                {"table": "profiles", "type": "LEFT", "left_col": "id", "right_col": "user_id"},
            ],
            "filters": [
                {"column": "age", "op": "gte", "value": 18},
                {"column": "active", "op": "eq", "value": True},
            ],
            "limit": 50,
        }
        with pytest.raises(SecurityError, match="exceeds authorized quota ceiling"):
            apply_security_policy(spec, policy=policy)

    def test_column_level_access_control_forbidden(self):
        policy = SecurityPolicy(
            enforce_tenant_isolation=False,
            column_permissions={
                "employees": {
                    "allowed_roles": ["finance", "hr_admin"],
                    "restricted_columns": ["salary", "ssn"],
                }
            },
        )
        context = TenantContext(tenant_id="t1", roles=["engineer"])
        spec = {
            "table": "employees",
            "columns": ["id", "name", "salary"],
        }
        with pytest.raises(SecurityError, match="Access to restricted column 'salary' on table 'employees' requires roles"):
            apply_security_policy(spec, context=context, policy=policy)

    def test_column_level_access_control_allowed(self):
        policy = SecurityPolicy(
            enforce_tenant_isolation=False,
            column_permissions={
                "employees": {
                    "allowed_roles": ["finance", "hr_admin"],
                    "restricted_columns": ["salary", "ssn"],
                }
            },
        )
        context = TenantContext(tenant_id="t1", roles=["finance"])
        spec = {
            "table": "employees",
            "columns": ["id", "name", "salary"],
        }
        res = apply_security_policy(spec, context=context, policy=policy)
        assert len(res["columns"]) == 3

    def test_dynamic_attribute_rls_filter(self):
        policy = SecurityPolicy(
            enforce_tenant_isolation=True,
            row_level_filters={
                "documents": [
                    {"column": "department", "op": "eq", "value": "$attr.dept"},
                    {"column": "clearance", "op": "lte", "value": "$attr.clearance_level"},
                ]
            },
        )
        context = TenantContext(
            tenant_id="acme",
            user_id="u123",
            roles=["member"],
            attributes={"dept": "rnd", "clearance_level": 3},
        )
        spec = {
            "table": "documents",
            "columns": ["id", "title"],
        }
        res = apply_security_policy(spec, context=context, policy=policy)
        filters = res["filters"]

        # Check tenant filter + 2 attribute filters
        dept_filter = next(f for f in filters if f["column"] == "department")
        assert dept_filter["value"] == "rnd"

        clearance_filter = next(f for f in filters if f["column"] == "clearance")
        assert clearance_filter["value"] == 3
