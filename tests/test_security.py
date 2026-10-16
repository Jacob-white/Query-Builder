import pytest

from query_builder.dialects import get_dialect
from query_builder.security import SecurityError, resolve_ownership_predicate


def test_resolve_ownership_direct_user_id():
    dialect = get_dialect("postgres")
    tables_meta = {
        "projects": {
            "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "title"}],
            "has_user_id": True,
            "user_col": "user_id",
        }
    }
    params = []
    predicate = resolve_ownership_predicate(
        dialect, tables_meta, "t1", "projects", 42, params
    )
    assert predicate == '"t1"."user_id" = %s'
    assert params == [42]


def test_resolve_ownership_multi_hop_chain():
    dialect = get_dialect("postgres")
    tables_meta = {
        "projects": {
            "columns": [{"name": "id"}, {"name": "user_id"}],
            "has_user_id": True,
            "user_col": "user_id",
        },
        "tasks": {
            "columns": [{"name": "id"}, {"name": "project_id"}],
            "has_user_id": False,
        },
        "evidence": {
            "columns": [{"name": "id"}, {"name": "task_id"}],
            "has_user_id": False,
        },
    }
    ownership_paths = {
        "tasks": [[("project_id", "projects", "id")]],
        "evidence": [[("task_id", "tasks", "id"), ("project_id", "projects", "id")]],
    }
    params = []
    predicate = resolve_ownership_predicate(
        dialect,
        tables_meta,
        "t1",
        "evidence",
        42,
        params,
        ownership_paths=ownership_paths,
    )
    assert "EXISTS" in predicate
    assert '"tasks"' in predicate
    assert '"projects"' in predicate
    assert params == [42]


def test_resolve_ownership_fails_closed_when_unresolvable():
    dialect = get_dialect("postgres")
    tables_meta = {
        "orphaned_table": {
            "columns": [{"name": "id"}, {"name": "val"}],
            "has_user_id": False,
        }
    }
    params = []
    with pytest.raises(SecurityError) as exc:
        resolve_ownership_predicate(
            dialect, tables_meta, "t1", "orphaned_table", 42, params
        )
    assert "refusing to query it without tenant isolation" in str(exc.value)


def test_security_cross_join_variations():
    from query_builder.security import (
        calculate_ast_complexity,
        check_cartesian_products,
    )

    spec_cross = {
        "table": "orders",
        "joins": [{"table": "users", "type": "CROSS JOIN"}],
    }
    score = calculate_ast_complexity(spec_cross)
    assert score >= 10
    with pytest.raises(SecurityError, match="Cartesian product detected"):
        check_cartesian_products(spec_cross)

    spec_full = {
        "table": "orders",
        "joins": [
            {
                "table": "users",
                "type": "FULL OUTER JOIN",
                "left_col": "user_id",
                "right_col": "id",
            }
        ],
    }
    score_full = calculate_ast_complexity(spec_full)
    assert score_full >= 10


def test_masked_column_inference_blocked_in_filters_having_order_by():
    from query_builder.policy import (
        SecurityPolicy,
        TenantContext,
        apply_security_policy,
    )

    policy = SecurityPolicy(
        column_masking={"employees": ["ssn", "salary"]},
        sensitive_column_patterns=[r"(?i)token"],
    )
    viewer_ctx = TenantContext(tenant_id="t1", roles=["viewer"])
    admin_ctx = TenantContext(tenant_id="t1", roles=["admin"])

    # 1. Filter on masked column: blocked for viewer (adversarial), allowed for admin (control)
    spec_filter = {
        "table": "employees",
        "columns": ["id", "name"],
        "filters": [{"column": "ssn", "op": "eq", "value": "000-00-0000"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_filter, context=viewer_ctx, policy=policy)
    admin_res = apply_security_policy(spec_filter, context=admin_ctx, policy=policy)
    assert len(admin_res["filters"]) >= 1

    # 2. Filter on sensitive pattern column: blocked for viewer (adversarial), allowed for admin (control)
    spec_token = {
        "table": "employees",
        "columns": ["id", "name"],
        "filters": [{"column": "api_token", "op": "eq", "value": "secret"}],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'api_token' is forbidden.",
    ):
        apply_security_policy(spec_token, context=viewer_ctx, policy=policy)
    admin_res_token = apply_security_policy(
        spec_token, context=admin_ctx, policy=policy
    )
    assert len(admin_res_token["filters"]) >= 1

    # 3. Having on masked column: blocked for viewer (adversarial), allowed for admin (control)
    spec_having = {
        "table": "employees",
        "columns": ["id", "name"],
        "having": [{"column": "salary", "agg": "avg", "op": "gt", "value": 50000}],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'salary' is forbidden.",
    ):
        apply_security_policy(spec_having, context=viewer_ctx, policy=policy)
    admin_res_having = apply_security_policy(
        spec_having, context=admin_ctx, policy=policy
    )
    assert len(admin_res_having["having"]) == 1

    # 4. Order by on masked column: blocked for viewer (adversarial), allowed for admin (control)
    spec_order = {
        "table": "employees",
        "columns": ["id", "name"],
        "order_by": [{"column": "ssn", "direction": "asc"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_order, context=viewer_ctx, policy=policy)
    admin_res_order = apply_security_policy(
        spec_order, context=admin_ctx, policy=policy
    )
    assert len(admin_res_order["order_by"]) == 1

    # 5. Order by string on masked column: blocked for viewer (adversarial), allowed for admin (control)
    spec_order_str = {
        "table": "employees",
        "columns": ["id", "name"],
        "order_by": ["ssn DESC"],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_order_str, context=viewer_ctx, policy=policy)
    admin_res_order_str = apply_security_policy(
        spec_order_str, context=admin_ctx, policy=policy
    )
    assert len(admin_res_order_str["order_by"]) == 1

    # 6. Subquery filter projecting masked column (adversarial)
    spec_subq = {
        "table": "orders",
        "columns": ["id"],
        "filters": [
            {
                "column": "user_id",
                "op": "in",
                "subquery": {
                    "table": "employees",
                    "columns": [{"column": "ssn", "masked": True}],
                },
            }
        ],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_subq, context=viewer_ctx, policy=policy)

    # 7. Subquery projecting masked column by name
    spec_subq_name = {
        "table": "orders",
        "columns": ["id"],
        "filters": [
            {
                "column": "user_id",
                "op": "in",
                "subquery": {
                    "table": "employees",
                    "columns": ["salary"],
                },
            }
        ],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'salary' is forbidden.",
    ):
        apply_security_policy(spec_subq_name, context=viewer_ctx, policy=policy)

    # 8. Nested filters containing masked column
    spec_nested = {
        "table": "employees",
        "columns": ["id"],
        "filters": [{"filters": [{"column": "salary", "op": "gt", "value": 50000}]}],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'salary' is forbidden.",
    ):
        apply_security_policy(spec_nested, context=viewer_ctx, policy=policy)

    # 9. Expression filter containing masked column
    spec_expr_flt = {
        "table": "employees",
        "columns": ["id"],
        "filters": [{"expression": "salary + 100 > 50000"}],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'salary' is forbidden.",
    ):
        apply_security_policy(spec_expr_flt, context=viewer_ctx, policy=policy)

    # 10. Having expression containing masked column
    spec_expr_having = {
        "table": "employees",
        "columns": ["id"],
        "having": [{"expression": "AVG(salary) > 50000"}],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'salary' is forbidden.",
    ):
        apply_security_policy(spec_expr_having, context=viewer_ctx, policy=policy)

    # 11. Order by expression containing masked column
    spec_expr_order = {
        "table": "employees",
        "columns": ["id"],
        "order_by": [{"expression": "salary DESC"}],
    }
    with pytest.raises(
        SecurityError,
        match="Filtering or sorting on masked column 'salary' is forbidden.",
    ):
        apply_security_policy(spec_expr_order, context=viewer_ctx, policy=policy)

    # 12. Clean expressions and subqueries allowed for viewer (control)
    spec_clean = {
        "table": "employees",
        "columns": ["id", "name"],
        "filters": [
            {"expression": "id > 10"},
            {
                "column": "id",
                "op": "in",
                "subquery": {
                    "table": "departments",
                    "columns": ["id"],
                },
            },
        ],
        "having": [{"expression": "COUNT(id) > 1"}],
        "order_by": [{"expression": "id ASC"}],
    }
    clean_res = apply_security_policy(spec_clean, context=viewer_ctx, policy=policy)
    assert len(clean_res["filters"]) >= 2


def test_having_order_by_spec_attributes_and_to_dict():
    from query_builder.models import HavingSpec, OrderBySpec

    h = HavingSpec(
        column="total",
        agg="sum",
        op="gt",
        value=100,
        tablePrefix="orders",
        table="orders_tbl",
        id="h1",
    )
    assert h.table_prefix == "orders"
    assert h.table == "orders_tbl"
    assert h.id == "h1"
    h_dict = h.to_dict()
    assert h_dict["table_prefix"] == "orders"
    assert h_dict["table"] == "orders_tbl"
    assert h_dict["id"] == "h1"

    o = OrderBySpec(
        column="created_at",
        direction="desc",
        tablePrefix="orders",
        table="orders_tbl",
        id="o1",
    )
    assert o.table_prefix == "orders"
    assert o.table == "orders_tbl"
    assert o.id == "o1"
    o_dict = o.to_dict()
    assert o_dict["table_prefix"] == "orders"
    assert o_dict["table"] == "orders_tbl"
    assert o_dict["id"] == "o1"


def test_table_alias_and_join_masking_and_clac_side_channel():
    from query_builder.policy import (
        SecurityPolicy,
        TenantContext,
        apply_security_policy,
    )

    viewer_ctx = TenantContext(tenant_id="t1", roles=["viewer"])
    admin_ctx = TenantContext(tenant_id="t1", roles=["admin"])
    mask_policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        column_masking={"users": ["ssn"]},
    )

    # 1. Projected column with base table alias is masked (adversarial)
    spec_alias_col = {
        "table": "users",
        "alias": "u",
        "columns": ["u.ssn"],
    }
    res_alias_col = apply_security_policy(
        spec_alias_col, context=viewer_ctx, policy=mask_policy
    )
    assert res_alias_col["columns"][0]["masked"] is True
    assert res_alias_col["columns"][0]["alias"] == "ssn_masked"

    # 2. Filter on aliased masked column blocked (adversarial)
    spec_alias_flt = {
        "table": "users",
        "alias": "u",
        "columns": ["id"],
        "filters": [{"table": "u", "column": "ssn", "op": "eq", "value": "123"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_alias_flt, context=viewer_ctx, policy=mask_policy)

    # Control: admin can filter on aliased column
    admin_res_flt = apply_security_policy(
        spec_alias_flt, context=admin_ctx, policy=mask_policy
    )
    assert len(admin_res_flt["filters"]) == 1

    # 3. Unprefixed column on joined table is masked in projection (adversarial)
    spec_join_col = {
        "table": "orders",
        "joins": [{"table": "users"}],
        "columns": ["ssn"],
    }
    res_join_col = apply_security_policy(
        spec_join_col, context=viewer_ctx, policy=mask_policy
    )
    assert res_join_col["columns"][0]["masked"] is True

    # 4. Unprefixed filter on joined table masked column blocked (adversarial)
    spec_join_flt = {
        "table": "orders",
        "joins": [{"table": "users"}],
        "columns": ["orders.id"],
        "filters": [{"column": "ssn", "op": "eq", "value": "secret"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_join_flt, context=viewer_ctx, policy=mask_policy)

    # 5. CLAC with table alias blocked for unauthorized role (adversarial)
    clac_policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        column_permissions={
            "users": {"restricted_columns": ["ssn"], "allowed_roles": ["admin"]}
        },
    )
    spec_clac_alias = {
        "table": "users",
        "alias": "u",
        "columns": ["u.ssn"],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(spec_clac_alias, context=viewer_ctx, policy=clac_policy)

    # Control: admin role allowed
    admin_clac_res = apply_security_policy(
        spec_clac_alias, context=admin_ctx, policy=clac_policy
    )
    assert len(admin_clac_res["columns"]) == 1

    # 6. CLAC filter side-channel blocked for unauthorized role (adversarial)
    spec_clac_flt = {
        "table": "users",
        "alias": "u",
        "columns": ["id"],
        "filters": [{"table": "u", "column": "ssn", "op": "eq", "value": "123"}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(spec_clac_flt, context=viewer_ctx, policy=clac_policy)

    # Control: admin role allowed filter
    admin_clac_flt_res = apply_security_policy(
        spec_clac_flt, context=admin_ctx, policy=clac_policy
    )
    assert len(admin_clac_flt_res["filters"]) == 1

    # 7. CLAC nested filter blocked for unauthorized role
    spec_clac_nested = {
        "table": "users",
        "alias": "u",
        "columns": ["id"],
        "filters": [{"filters": [{"column": "ssn", "op": "eq", "value": "123"}]}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(spec_clac_nested, context=viewer_ctx, policy=clac_policy)

    # 8. CLAC column expression blocked for unauthorized role
    spec_clac_expr_col = {
        "table": "users",
        "columns": [{"expression": "users.ssn || '-ext'"}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_expr_col, context=viewer_ctx, policy=clac_policy
        )

    # 9. CLAC filter expression blocked for unauthorized role
    spec_clac_expr_flt = {
        "table": "users",
        "columns": ["id"],
        "filters": [{"expression": "users.ssn IS NOT NULL"}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_expr_flt, context=viewer_ctx, policy=clac_policy
        )

    # 10. CLAC having clause blocked for unauthorized role (expression and column dict)
    spec_clac_having_expr = {
        "table": "users",
        "columns": ["id"],
        "having": [{"expression": "COUNT(users.ssn) > 0"}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_having_expr, context=viewer_ctx, policy=clac_policy
        )

    spec_clac_having_col = {
        "table": "users",
        "columns": ["id"],
        "having": [{"column": "ssn", "agg": "count", "op": "gt", "value": 0}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_having_col, context=viewer_ctx, policy=clac_policy
        )

    # 11. CLAC order_by clause blocked for unauthorized role (string, dict, and expression)
    spec_clac_order_str = {
        "table": "users",
        "columns": ["id"],
        "order_by": ["ssn desc"],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_order_str, context=viewer_ctx, policy=clac_policy
        )

    spec_clac_order_dict = {
        "table": "users",
        "columns": ["id"],
        "order_by": [{"column": "ssn", "direction": "desc", "table": "users"}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_order_dict, context=viewer_ctx, policy=clac_policy
        )

    spec_clac_order_expr = {
        "table": "users",
        "columns": ["id"],
        "order_by": [{"expression": "users.ssn ASC"}],
    }
    with pytest.raises(SecurityError, match="Access to restricted column 'ssn'"):
        apply_security_policy(
            spec_clac_order_expr, context=viewer_ctx, policy=clac_policy
        )

    # 12. Masking on having and order_by (dict and string)
    spec_mask_having = {
        "table": "users",
        "columns": ["id"],
        "having": [{"column": "ssn", "agg": "count", "tablePrefix": "users"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_mask_having, context=viewer_ctx, policy=mask_policy)

    spec_mask_order_str = {
        "table": "users",
        "columns": ["id"],
        "order_by": ["ssn ASC"],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(
            spec_mask_order_str, context=viewer_ctx, policy=mask_policy
        )

    spec_mask_order_dict = {
        "table": "users",
        "columns": ["id"],
        "order_by": [{"column": "ssn", "tablePrefix": "users"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(
            spec_mask_order_dict, context=viewer_ctx, policy=mask_policy
        )

    # 13. Column expression containing masked column
    spec_mask_expr_col = {
        "table": "users",
        "columns": [{"expression": "ssn || '-masked'"}],
    }
    with pytest.raises(
        SecurityError,
        match="Access to masked column 'ssn' in expression is forbidden.",
    ):
        apply_security_policy(
            spec_mask_expr_col, context=viewer_ctx, policy=mask_policy
        )

    # 14. Join table alias resolution with schema prefix
    spec_join_alias = {
        "table": "users",
        "joins": [{"table": "accounts", "alias": "acc"}],
        "columns": ["public.acc.balance"],
    }
    alias_policy = SecurityPolicy(
        enforce_tenant_isolation=False,
        column_masking={"accounts": ["balance"]},
    )
    res_join_alias = apply_security_policy(
        spec_join_alias, context=viewer_ctx, policy=alias_policy
    )
    assert res_join_alias["columns"][0]["masked"] is True

    # 15. Non-dict filters and having expressions with masked columns
    spec_mask_having_expr = {
        "table": "users",
        "columns": ["id"],
        "filters": [None],
        "having": [{"expression": "AVG(ssn) > 100"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(
            spec_mask_having_expr, context=viewer_ctx, policy=mask_policy
        )

    # 16. Order-by expression with masked column
    spec_mask_order_expr = {
        "table": "users",
        "columns": ["id"],
        "order_by": [{"expression": "users.ssn ASC"}],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(
            spec_mask_order_expr, context=viewer_ctx, policy=mask_policy
        )

    # 17. Subquery passed via 'value' key with masked column
    spec_val_subq = {
        "table": "users",
        "columns": ["id"],
        "filters": [
            {
                "column": "id",
                "op": "in",
                "value": {"table": "users", "columns": ["ssn"]},
            }
        ],
    }
    with pytest.raises(
        SecurityError, match="Filtering or sorting on masked column 'ssn' is forbidden."
    ):
        apply_security_policy(spec_val_subq, context=viewer_ctx, policy=mask_policy)

    # 18. Non-dict filter element with CLAC
    spec_clac_none = {
        "table": "users",
        "columns": ["id"],
        "filters": [None],
    }
    res_clac_none = apply_security_policy(
        spec_clac_none, context=viewer_ctx, policy=clac_policy
    )
    assert len(res_clac_none["columns"]) == 1
