import pytest

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import QueryCompiler, validate_query_spec
from query_builder.exceptions import (
    CompilationError,
    ValidationError,
)
from query_builder.models import QuerySpec


def test_ast_validator_comments_and_escapes():
    # Single-line and multiline comments containing forbidden keywords
    res1 = validate_sql_ast("SELECT id FROM users -- drop old column\nWHERE active = 1")
    assert res1["valid"] is True

    res2 = validate_sql_ast(
        "SELECT id FROM users /* delete obsolete records */ WHERE active = 1"
    )
    assert res2["valid"] is True

    # Escaped string literals containing mutation patterns
    res3 = validate_sql_ast("SELECT 'user\\'s drop action' AS note FROM users")
    assert res3["valid"] is True

    res4 = validate_sql_ast("SELECT 'pg_catalog.tables' AS cat FROM users")
    assert res4["valid"] is True

    # Quoted identifiers matching keywords
    res5 = validate_sql_ast('SELECT u."drop", u."set" FROM users u')
    assert res5["valid"] is True

    # Projection with column named user_profile
    res6 = validate_sql_ast("SELECT u.user_profile FROM user_data u")
    assert res6["valid"] is True

    # Comma-separated tables in FROM clause targeting restricted tables
    res7 = validate_sql_ast("SELECT * FROM users, auth_user")
    assert res7["valid"] is False
    assert any("AUTH_USER" in v for v in res7["violations"])

    res8 = validate_sql_ast("SELECT * FROM users, sys.sql_logins")
    assert res8["valid"] is False
    assert any("SYS.SQL_LOGINS" in v for v in res8["violations"])

    # Multiple CTE definitions with comma and AS (...)
    res9 = validate_sql_ast(
        "WITH a AS (SELECT 1 AS x), b AS (SELECT 2 AS y) SELECT a.x, b.y FROM a, b"
    )
    assert res9["valid"] is True

    # Unclosed or malformed CTE
    res10 = validate_sql_ast("WITH a AS (SELECT 1)")
    assert res10["valid"] is False


def test_compiler_multipart_schemas():
    spec = {
        "table": "catalog.analytics.events",
        "columns": ["catalog.analytics.events.id", "catalog.analytics.events.action"],
        "joins": [
            {
                "table": "catalog.analytics.users",
                "left_col": "user_id",
                "right_col": "id",
            }
        ],
    }
    compiler = QueryCompiler(spec)
    sql, _, _, _ = compiler.compile()
    assert 'FROM "catalog"."analytics"."events" "t1"' in sql
    assert 'LEFT JOIN "catalog"."analytics"."users" "t2"' in sql
    assert '"t1"."user_id" = "t2"."id"' in sql


def test_compiler_self_joins_and_aliases():
    # Self-join with auto unique alias allocation
    spec_self = {
        "table": "employees",
        "columns": ["employees.id", "employees.name"],
        "joins": [
            {
                "table": "employees",
                "left_col": "manager_id",
                "right_col": "id",
            }
        ],
    }
    compiler_self = QueryCompiler(spec_self)
    sql_self, _, _, _ = compiler_self.compile()
    assert 'FROM "employees" "t1"' in sql_self
    assert 'LEFT JOIN "employees" "t2" ON "t1"."manager_id" = "t2"."id"' in sql_self

    # Multiple joins to the same table
    spec_multi = {
        "table": "orders",
        "columns": ["orders.id"],
        "joins": [
            {
                "table": "addresses",
                "left_col": "billing_address_id",
                "right_col": "id",
            },
            {
                "table": "addresses",
                "left_col": "shipping_address_id",
                "right_col": "id",
            },
        ],
    }
    compiler_multi = QueryCompiler(spec_multi)
    sql_multi, _, _, _ = compiler_multi.compile()
    assert 'LEFT JOIN "addresses" "t2"' in sql_multi
    assert 'LEFT JOIN "addresses" "t3"' in sql_multi

    # Explicit join alias
    spec_explicit = {
        "table": "employees",
        "columns": ["employees.id", "mgr.name"],
        "joins": [
            {
                "table": "employees",
                "alias": "mgr",
                "left_col": "manager_id",
                "right_col": "id",
            }
        ],
    }
    compiler_explicit = QueryCompiler(spec_explicit)
    sql_explicit, _, _, _ = compiler_explicit.compile()
    assert (
        'LEFT JOIN "employees" "mgr" ON "t1"."manager_id" = "mgr"."id"' in sql_explicit
    )
    assert '"mgr"."name" AS "mgr.name"' in sql_explicit

    # Unjoined left_table raises error
    spec_bad_left = {
        "table": "orders",
        "joins": [
            {
                "table": "items",
                "left_table": "nonexistent_table",
                "left_col": "item_id",
                "right_col": "id",
            }
        ],
    }
    with pytest.raises(
        CompilationError,
        match="Join left_table 'nonexistent_table' is not part of the query",
    ):
        QueryCompiler(spec_bad_left).compile()


def test_compiler_count_wildcard_projections():
    # COUNT(*) with alias
    spec1 = {
        "table": "orders",
        "columns": [{"column": "*", "agg": "count", "alias": "total_orders"}],
    }
    sql1, _, _, _ = QueryCompiler(spec1).compile()
    assert 'SELECT COUNT(*) AS "total_orders"' in sql1

    # COUNT(*) without alias
    spec2 = {
        "table": "orders",
        "columns": [{"column": "*", "agg": "count"}],
    }
    sql2, _, _, _ = QueryCompiler(spec2).compile()
    assert 'SELECT COUNT(*) AS "count_all"' in sql2

    # Wildcard in dict without agg
    spec3 = {
        "table": "orders",
        "columns": [{"column": "*"}],
    }
    sql3, _, _, _ = QueryCompiler(spec3).compile()
    assert 'SELECT "t1".*' in sql3

    # COUNT(DISTINCT *) error
    spec_distinct = {
        "table": "orders",
        "columns": [{"column": "*", "agg": "count_distinct"}],
    }
    with pytest.raises(
        CompilationError, match="COUNT\\(DISTINCT \\*\\) is not supported"
    ):
        QueryCompiler(spec_distinct).compile()

    # Unsupported aggregate on *
    spec_avg = {
        "table": "orders",
        "columns": [{"column": "*", "agg": "avg"}],
    }
    with pytest.raises(
        CompilationError, match="Aggregate 'avg' cannot be applied to '\\*'"
    ):
        QueryCompiler(spec_avg).compile()


def test_compiler_filter_negation_nulls_and_grouping():
    # Equality and inequality with None
    spec_nulls = {
        "table": "users",
        "filters": [
            {"column": "deleted_at", "op": "eq", "value": None},
            {"column": "confirmed_at", "op": "neq", "value": None},
            {"column": "archived_at", "op": "is_null"},
            {"column": "updated_at", "op": "is_not_null"},
        ],
    }
    sql_nulls, params_nulls, _, _ = QueryCompiler(spec_nulls).compile()
    assert '"t1"."deleted_at" IS NULL' in sql_nulls
    assert '"t1"."confirmed_at" IS NOT NULL' in sql_nulls
    assert '"t1"."archived_at" IS NULL' in sql_nulls
    assert '"t1"."updated_at" IS NOT NULL' in sql_nulls
    assert len(params_nulls) == 2  # limit=50, offset=0

    # Empty IN and NOT IN
    spec_empty = {
        "table": "users",
        "filters": [
            {"column": "status", "op": "in", "value": []},
            {"column": "role", "op": "not in", "value": []},
        ],
    }
    sql_empty, _, _, _ = QueryCompiler(spec_empty).compile()
    assert "1 = 0" in sql_empty
    assert "1 = 1" in sql_empty

    # NOT IN with None (3-valued logic)
    spec_not_in_none = {
        "table": "users",
        "filters": [
            {"column": "status", "op": "not in", "value": ["admin", None, "owner"]},
        ],
    }
    sql_not_in_none, params_not_in_none, _, _ = QueryCompiler(
        spec_not_in_none
    ).compile()
    assert (
        '("t1"."status" NOT IN (%s, %s) AND "t1"."status" IS NOT NULL)'
        in sql_not_in_none
    )
    assert None not in params_not_in_none
    assert "admin" in params_not_in_none
    assert "owner" in params_not_in_none

    # NOT IN with only None
    spec_not_in_only_none = {
        "table": "users",
        "filters": [{"column": "status", "op": "not in", "value": [None]}],
    }
    sql_only_none, _, _, _ = QueryCompiler(spec_not_in_only_none).compile()
    assert "1 = 0" in sql_only_none

    # IN with None
    spec_in_none = {
        "table": "users",
        "filters": [{"column": "status", "op": "in", "value": ["active", None]}],
    }
    sql_in_none, _, _, _ = QueryCompiler(spec_in_none).compile()
    assert '("t1"."status" IN (%s) OR "t1"."status" IS NULL)' in sql_in_none

    # IN with only None
    spec_in_only_none = {
        "table": "users",
        "filters": [{"column": "status", "op": "in", "value": [None]}],
    }
    sql_in_only_none, _, _, _ = QueryCompiler(spec_in_only_none).compile()
    assert '"t1"."status" IS NULL' in sql_in_only_none

    # Negated operators
    spec_negated = {
        "table": "users",
        "filters": [
            {"column": "email", "op": "not_like", "value": "%@test.com"},
            {"column": "name", "op": "not_ilike", "value": "admin%"},
            {"column": "bio", "op": "not_contains", "value": "spam"},
            {"column": "code", "op": "not_starts_with", "value": "TEST_"},
            {"column": "slug", "op": "not_ends_with", "value": "_temp"},
            {"column": "age", "op": "not_between", "value": [18, 65]},
        ],
    }
    sql_neg, _, _, _ = QueryCompiler(spec_negated).compile()
    assert '"t1"."email" NOT LIKE %s' in sql_neg
    assert 'NOT ("t1"."name" ILIKE %s)' in sql_neg
    assert 'NOT ("t1"."bio" ILIKE %s)' in sql_neg
    assert 'NOT ("t1"."code" ILIKE %s)' in sql_neg
    assert 'NOT ("t1"."slug" ILIKE %s)' in sql_neg
    assert '"t1"."age" NOT BETWEEN %s AND %s' in sql_neg

    # Filter grouping with parenOpen, parenClose, and combiner
    spec_grouped = {
        "table": "users",
        "filters": [
            {"column": "role", "op": "eq", "value": "admin", "parenOpen": "("},
            {
                "column": "role",
                "op": "eq",
                "value": "owner",
                "parenClose": ")",
                "combiner": "OR",
            },
            {"column": "is_active", "op": "eq", "value": True, "combiner": "AND"},
        ],
    }
    sql_grp, _, _, _ = QueryCompiler(spec_grouped).compile()
    assert (
        '(("t1"."role" = %s OR "t1"."role" = %s) AND "t1"."is_active" = %s)' in sql_grp
    )


def test_compiler_subqueries_from_and_where():
    # FROM subquery
    sub_spec = {
        "table": "orders",
        "columns": [
            "orders.user_id",
            {"column": "orders.amount", "agg": "sum", "alias": "total_spent"},
        ],
        "filters": [{"column": "orders.status", "op": "eq", "value": "completed"}],
    }
    main_spec = {
        "table": sub_spec,
        "columns": ["subquery.user_id", "subquery.total_spent"],
        "filters": [{"column": "subquery.total_spent", "op": "gt", "value": 100}],
    }
    compiler = QueryCompiler(main_spec)
    sql, params, _, count_params = compiler.compile()
    assert 'FROM (SELECT "t1"."user_id" AS "orders.user_id"' in sql
    assert 'AS "t1"' in sql
    assert '"t1"."total_spent" > %s' in sql
    # Parameters: completed (subquery), 100 (outer WHERE), then 50, 0 (OUTER limit and
    # offset). The nested subquery gets no implicit page LIMIT: it would silently
    # truncate the inner result set.
    assert params == ["completed", 100, 50, 0]
    assert sql.count("LIMIT") == 1
    assert count_params == ["completed", 100]

    # WHERE subquery with IN
    dept_sub = {
        "table": "departments",
        "columns": ["departments.id"],
        "filters": [{"column": "departments.active", "op": "eq", "value": True}],
    }
    where_in_spec = {
        "table": "employees",
        "columns": ["employees.name"],
        "filters": [
            {"column": "employees.dept_id", "op": "in", "subquery": dept_sub},
            {
                "column": "employees.role",
                "op": "not in",
                "subquery": {
                    "table": "restricted_roles",
                    "columns": ["restricted_roles.name"],
                },
            },
        ],
    }
    sql_in, params_in, _, _ = QueryCompiler(where_in_spec).compile()
    assert 'IN (SELECT "t1"."id" AS "departments.id"' in sql_in
    assert 'FROM "departments" "t1"' in sql_in
    assert 'NOT IN (SELECT "t1"."name" AS "restricted_roles.name"' in sql_in
    assert 'FROM "restricted_roles" "t1"' in sql_in
    assert True in params_in

    # WHERE subquery with EXISTS / NOT EXISTS
    exists_sub = {
        "table": "projects",
        "columns": ["projects.id"],
        "filters": [{"column": "projects.lead_id", "op": "eq", "value": 42}],
    }
    where_exists_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [
            {"op": "exists", "subquery": exists_sub},
            {"op": "not_exists", "subquery": exists_sub, "combiner": "AND"},
        ],
    }
    sql_ex, params_ex, _, _ = QueryCompiler(where_exists_spec).compile()
    assert 'EXISTS (SELECT "t1"."id" AS "projects.id"' in sql_ex
    assert 'NOT EXISTS (SELECT "t1"."id" AS "projects.id"' in sql_ex
    assert 42 in params_ex

    # Comparison operator with subquery
    scalar_sub = {
        "table": "salaries",
        "columns": [{"column": "salaries.amount", "agg": "avg", "alias": "avg_sal"}],
    }
    comp_sub_spec = {
        "table": "employees",
        "columns": ["employees.name"],
        "filters": [{"column": "employees.salary", "op": "gt", "subquery": scalar_sub}],
    }
    sql_scalar, _, _, _ = QueryCompiler(comp_sub_spec).compile()
    assert '"t1"."salary" > (SELECT AVG("t1"."amount") AS "avg_sal"' in sql_scalar


def test_compiler_dialects_and_having():
    # MSSQL fallback ORDER BY (SELECT NULL)
    mssql_spec = {
        "table": "users",
        "columns": ["users.id"],
        "limit": 10,
        "offset": 20,
    }
    sql_mssql, params_mssql, _, _ = QueryCompiler(mssql_spec, dialect="mssql").compile()
    assert "ORDER BY (SELECT NULL)" in sql_mssql
    assert "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" in sql_mssql
    assert params_mssql == [20, 10]

    # Informix prefix pagination placement
    informix_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [{"column": "users.active", "op": "eq", "value": True}],
        "limit": 10,
        "offset": 5,
    }
    sql_inf, params_inf, _, _ = QueryCompiler(
        informix_spec, dialect="informix"
    ).compile()
    assert 'SELECT SKIP %s FIRST %s "t1"."id" AS "users.id"' in sql_inf
    # Informix parameters order: offset, limit, where_params
    assert params_inf == [5, 10, True]

    # HAVING COUNT(*)
    having_spec = {
        "table": "orders",
        "columns": ["orders.user_id", {"column": "orders.id", "agg": "count"}],
        "having": [
            {"column": "*", "agg": "count", "op": "gte", "value": 3},
        ],
    }
    sql_hvg, params_hvg, _, _ = QueryCompiler(having_spec).compile()
    assert "HAVING COUNT(*) >= %s" in sql_hvg
    assert 3 in params_hvg

    # HAVING with invalid aggregate on * raises CompilationError
    bad_hvg_spec = {
        "table": "orders",
        "columns": ["orders.user_id"],
        "having": [{"column": "*", "agg": "sum", "op": "gt", "value": 10}],
    }
    with pytest.raises(
        CompilationError, match="Aggregate 'sum' cannot be applied to '\\*' in HAVING"
    ):
        QueryCompiler(bad_hvg_spec, validate_spec=False).compile()


def test_validation_spec_rules():
    # Spec with subquery in table
    sub = {"table": "users", "columns": ["id"]}
    validate_query_spec({"table": sub, "columns": ["id"]})

    # Spec with QuerySpec in table
    q_sub = QuerySpec(table="users", columns=["id"])
    validate_query_spec({"table": q_sub, "columns": ["id"]})

    # Join with alias
    validate_query_spec(
        {
            "table": "users",
            "joins": [
                {
                    "table": "logs",
                    "alias": "l",
                    "left_col": "id",
                    "right_col": "user_id",
                }
            ],
        }
    )

    # Filter with subquery
    validate_query_spec(
        {
            "table": "users",
            "filters": [
                {
                    "column": "id",
                    "op": "in",
                    "subquery": {"table": "logs", "columns": ["user_id"]},
                }
            ],
        }
    )

    # Filter exists without subquery raises ValidationError
    with pytest.raises(
        ValidationError, match="EXISTS filter requires a nested subquery"
    ):
        validate_query_spec(
            {"table": "users", "filters": [{"op": "exists", "value": 123}]}
        )

    # Filter with invalid operator
    with pytest.raises(ValidationError, match="Unsupported filter operator"):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "bad_op", "value": 1}],
            }
        )

    # Filter between invalid bounds
    with pytest.raises(
        ValidationError, match="BETWEEN filter requires exactly 2 bounds"
    ):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "between", "value": [1]}],
            }
        )

    # Filter in with > 1000 items
    with pytest.raises(ValidationError, match="exceeds maximum limit"):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "in", "value": list(range(1001))}],
            }
        )

    # Filter in comma-separated with > 1000 items
    csv_1001 = ",".join(str(i) for i in range(1001))
    with pytest.raises(ValidationError, match="exceeds maximum limit"):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "in", "value": csv_1001}],
            }
        )


def test_compiler_alias_edge_branches():
    comp = QueryCompiler({"table": "users"})
    comp.table_aliases["t1"] = "t1"
    comp.table_aliases["t2"] = "t2"
    alias = comp._generate_unique_alias()
    assert alias == "t3"

    # _get_alias with explicit_alias
    a_exp = comp._get_alias("users", explicit_alias="u_custom")
    assert a_exp == "u_custom"

    # _get_alias errors
    with pytest.raises(CompilationError, match="Invalid table name"):
        comp._get_alias("")
    with pytest.raises(CompilationError, match="Invalid table identifier name"):
        comp._get_alias("bad;table")

    # _get_alias with default_alias that is non-numeric
    a_def = comp._get_alias("orders", default_alias="custom_alias")
    assert a_def == "custom_alias"

    # _resolve_column_ref target_alias branches
    comp.table_aliases["default_tbl"] = "t1"
    res1 = comp._resolve_column_ref("col", "default_tbl", target_alias="t2")
    assert res1[0] == "t2"
    res2 = comp._resolve_column_ref("default_tbl.col", "default_tbl", target_alias="t2")
    assert res2[0] == "t2"


def test_ast_validator_remaining_branches():
    # Comma separated with restricted table in 2nd part of qualified name
    res1 = validate_sql_ast("SELECT * FROM users, myschema.passwords")
    assert not res1["valid"]
    assert any("PASSWORDS" in v for v in res1["violations"])

    # Comma separated with empty item
    res2 = validate_sql_ast("SELECT * FROM users, ")
    assert res2["valid"]

    # Direct test of _extract_cte_root_statement
    import sqlparse

    from query_builder.ast_validator import _extract_cte_root_statement

    stmt = sqlparse.parse("WITH a AS (SELECT 1), b AS (SELECT 2) SELECT * FROM a")[0]
    kw = _extract_cte_root_statement(stmt)
    assert kw == "SELECT"

    # Test in_cte_def and Parenthesis token in _extract_cte_root_statement
    t_with = sqlparse.sql.Token(sqlparse.tokens.Keyword.CTE, "WITH")
    t_as = sqlparse.sql.Token(sqlparse.tokens.Keyword.CTE, "AS")
    t_paren = sqlparse.sql.Parenthesis(
        [
            sqlparse.sql.Token(sqlparse.tokens.Punctuation, "("),
            sqlparse.sql.Token(sqlparse.tokens.Punctuation, ")"),
        ]
    )
    t_select = sqlparse.sql.Token(sqlparse.tokens.Keyword, "SELECT")
    dummy_stmt = sqlparse.sql.Statement([t_with, t_as, t_paren, t_select])
    assert _extract_cte_root_statement(dummy_stmt) == "SELECT"

    # Parenthesized root statement
    t_outer_paren = sqlparse.sql.Parenthesis(
        [
            sqlparse.sql.Token(sqlparse.tokens.Punctuation, "("),
            sqlparse.sql.Token(sqlparse.tokens.Keyword, "SELECT"),
            sqlparse.sql.Token(sqlparse.tokens.Punctuation, ")"),
        ]
    )
    dummy_stmt_paren = sqlparse.sql.Statement([t_with, t_outer_paren])
    assert _extract_cte_root_statement(dummy_stmt_paren) == "SELECT"


def test_informix_full_clauses():
    spec = {
        "table": "orders",
        "columns": ["orders.user_id", {"column": "orders.amount", "agg": "sum"}],
        "joins": [{"table": "users", "left_col": "user_id", "right_col": "id"}],
        "filters": [{"column": "orders.status", "op": "eq", "value": "paid"}],
        "having": [{"column": "orders.amount", "agg": "sum", "op": "gt", "value": 100}],
        "order_by": [{"column": "orders.user_id", "direction": "DESC"}],
        "limit": 10,
        "offset": 5,
    }
    sql, _, _, _ = QueryCompiler(spec, dialect="informix").compile()
    assert "SELECT SKIP %s FIRST %s" in sql
    assert "LEFT JOIN" in sql
    assert "WHERE" in sql
    assert "GROUP BY" in sql
    assert "HAVING" in sql
    assert "ORDER BY" in sql

    # Suffix pagination with empty limit_offset_str
    from query_builder.dialects import BaseDialect

    class NoPaginationDialect(BaseDialect):
        def format_limit_offset(self, limit: int, offset: int):
            return "", []

    sql_no_pag, _, _, _ = QueryCompiler(
        {"table": "users"}, dialect=NoPaginationDialect()
    ).compile()
    assert "LIMIT" not in sql_no_pag


def test_filter_grouping_edge_branches():
    spec = {
        "table": "users",
        "filters": [
            {"column": "a", "op": "eq", "value": 1, "parenOpen": True},
            {
                "column": "b",
                "op": "eq",
                "value": 2,
                "parenOpen": 2,
                "parenClose": True,
                "combiner": "OR",
            },
            {
                "column": "c",
                "op": "eq",
                "value": 3,
                "parenOpen": "bad_open",
                "parenClose": "bad_close",
                "combiner": "AND",
            },
            {
                "column": "d",
                "op": "eq",
                "value": 4,
                "parenClose": 2,
            },
        ],
    }
    sql, _, _, _ = QueryCompiler(spec).compile()
    assert "WHERE" in sql


def test_compiler_multihop_auto_join():
    schema = {
        "tables": {
            "orders": {"columns": ["id", "user_id"]},
            "users": {"columns": ["id", "org_id"]},
            "organizations": {"columns": ["id", "name"]},
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            },
            {
                "table": "users",
                "column": "org_id",
                "foreign_table": "organizations",
                "foreign_column": "id",
            },
        ],
    }
    spec = {
        "table": "orders",
        "columns": ["orders.id", "organizations.name"],
        "joins": [
            {"table": "users"},
            {"table": "organizations"},
        ],
    }
    sql, _, _, _ = QueryCompiler(spec, schema=schema).compile()
    assert 'LEFT JOIN "organizations"' in sql


def test_coverage_100_percent_closure():
    # 1. AST validator 537->523 (non-restricted 2nd part of qualified table)
    res_non_rest = validate_sql_ast("SELECT * FROM users, myschema.mytable")
    assert res_non_rest["valid"]

    # 2. validate_query_spec col == "*"
    validate_query_spec({"table": "users", "columns": ["*"]})
    validate_query_spec({"table": "users", "columns": [{"column": "*"}]})
    validate_query_spec({"table": "users", "columns": [{"column": "users.*"}]})

    # 3. QueryCompiler middleware hooks
    from query_builder.middleware import LifecycleInterceptor

    class DummyHook(LifecycleInterceptor):
        def on_pre_compile(self, spec, ctx):
            return spec

        def on_post_compile(self, comp, ctx):
            return comp

    comp_mw = QueryCompiler({"table": "users"}, middleware=[DummyHook()])
    sql_mw, _, _, _ = comp_mw.compile()
    assert "FROM" in sql_mw

    # 4. _get_alias cached hits for table_name and clean
    comp = QueryCompiler({"table": "users"})
    comp.table_aliases["schema.users"] = "t1"
    assert comp._get_alias("schema.users") == "t1"
    comp.table_aliases["users"] = "t1"
    assert comp._get_alias("users") == "t1"
    assert comp._get_alias("dw.users") == "t1"

    # _resolve_column_ref unaliased table allocating new alias
    res_new = comp._resolve_column_ref("brand_new_table.col", "default")
    assert res_new[0] == "t2"

    # 5. Wildcard projection with table name: "users.*"
    comp_wild = QueryCompiler({"table": "users", "columns": ["users.*"]})
    sql_wild, _, _, _ = comp_wild.compile()
    assert '"t1".*' in sql_wild

    # 6. EXISTS without subquery and validate_spec=False
    with pytest.raises(
        CompilationError, match="EXISTS filter requires a nested subquery"
    ):
        QueryCompiler(
            {"table": "users", "filters": [{"op": "exists"}]}, validate_spec=False
        ).compile()

    # 7. Non-negated starts_with and ends_with
    spec_se = {
        "table": "users",
        "filters": [
            {"column": "name", "op": "starts_with", "value": "A"},
            {"column": "name", "op": "ends_with", "value": "Z"},
        ],
    }
    _, params_se, _, _ = QueryCompiler(spec_se).compile()
    assert "A%" in params_se
    assert "%Z" in params_se

    # 8. Filter grouping with invalid combiner and multichar paren strings
    spec_paren = {
        "table": "users",
        "filters": [
            {"column": "a", "op": "eq", "value": 1, "parenOpen": "("},
            {
                "column": "b",
                "op": "eq",
                "value": 2,
                "parenClose": ")",
                "combiner": "INVALID_COMBINER",
            },
        ],
    }
    sql_p, _, _, _ = QueryCompiler(spec_paren).compile()
    assert "WHERE" in sql_p

    # 9. Having with valid aggregate on base table column, and invalid op ignored
    spec_h = {
        "table": "users",
        "columns": ["users.dept", {"column": "users.salary", "agg": "avg"}],
        "having": [
            {"column": "users.salary", "agg": "avg", "op": "gt", "value": 50000},
            {"column": "users.salary", "agg": "avg", "op": "bad_op", "value": 1},
        ],
    }
    sql_h, _, _, _ = QueryCompiler(spec_h, validate_spec=False).compile()
    assert "HAVING AVG" in sql_h

    # 10. Informix query without joins
    sql_inf_no_join, _, _, _ = QueryCompiler(
        {"table": "users", "limit": 10}, dialect="informix"
    ).compile()
    assert "SELECT SKIP %s FIRST %s" in sql_inf_no_join
    assert "JOIN" not in sql_inf_no_join
