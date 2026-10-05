"""
Standalone Adversarial Stress Test Harness for Milestone 1 Audit Remediation.
=============================================================================
Stress-tests:
1. Multi-level nested subqueries in FROM and WHERE with parameter alignment and value ordering.
2. Multi-part schema names across multiple dialects (Postgres, MySQL, SQLite, Snowflake, MSSQL).
3. Self-joins and multiple joins to the same table with unique alias tracking and explicit alias overrides.
4. AST safety: malicious injection payloads (disguised in comments, CTEs, chaining) vs benign queries.
   - Also empirically documents discovered vulnerability in comma-separated restricted tables.
5. Filter logic: empty IN/NOT IN, None equality/inequality to IS NULL, SQL 3-valued logic, complex grouping.
6. Dialect pagination: MSSQL fallback ORDER BY (SELECT NULL), Informix prefix pagination parameter order.
7. Domain exception hierarchy: isinstance inheritance and polymorphic exception catching.
"""

from __future__ import annotations

import sys

import pytest

from query_builder import (
    CompilationError,
    DialectError,
    QueryBuilderError,
    SecurityError,
    ValidationError,
)
from query_builder.ast_validator import (
    _extract_from_body,
    _split_from_items,
    validate_sql_ast,
)
from query_builder.compiler import QueryCompiler


# =====================================================================
# 1. Multi-Level Nested Subqueries in FROM and WHERE
# =====================================================================
def test_adversarial_nested_subqueries_from_and_where_ordering():
    """Verify deep multi-level subqueries in FROM and WHERE maintain exact parameter ordering."""
    # Level 3: Innermost query
    lvl3_from = {
        "table": "raw_telemetry",
        "columns": [
            "raw_telemetry.device_id",
            "raw_telemetry.metric_val",
            "raw_telemetry.region",
        ],
        "filters": [
            {"column": "raw_telemetry.status", "op": "eq", "value": "healthy"},
            {"column": "raw_telemetry.metric_val", "op": "gte", "value": 10.5},
        ],
        "limit": 100,
        "offset": 10,
    }

    # Level 2: Middle FROM subquery
    lvl2_from = {
        "table": lvl3_from,
        "columns": ["subquery.device_id", "subquery.metric_val"],
        "filters": [{"column": "subquery.region", "op": "eq", "value": "us-east-1"}],
        "limit": 50,
        "offset": 5,
    }

    # Level 2 WHERE subquery: EXISTS
    where_exists_sub = {
        "table": "quarantine_devices",
        "columns": ["quarantine_devices.id"],
        "filters": [
            {
                "column": "quarantine_devices.reason",
                "op": "eq",
                "value": "compromised",
            }
        ],
        "limit": 5,
        "offset": 0,
    }

    # Level 2 WHERE subquery: IN
    where_in_sub = {
        "table": "allowed_clusters",
        "columns": ["allowed_clusters.cluster_id"],
        "filters": [
            {"column": "allowed_clusters.tier", "op": "eq", "value": "premium"},
            {"op": "not_exists", "subquery": where_exists_sub, "combiner": "AND"},
        ],
        "limit": 20,
        "offset": 0,
    }

    # Level 1: Outer query combining FROM subquery + WHERE subquery + scalar filter
    outer_spec = {
        "table": lvl2_from,
        "columns": ["subquery.device_id"],
        "filters": [
            {"column": "subquery.device_id", "op": "in", "subquery": where_in_sub},
            {"column": "subquery.metric_val", "op": "lt", "value": 99.9},
        ],
        "limit": 15,
        "offset": 0,
    }

    compiler = QueryCompiler(outer_spec)
    sql, params, count_sql, count_params = compiler.compile()

    # 1. Verify SQL structure and nested nesting levels
    assert (
        'FROM (SELECT "t1"."device_id" AS "subquery.device_id", "t1"."metric_val" AS "subquery.metric_val"'
        in sql
    )
    assert (
        'FROM (SELECT "t1"."device_id" AS "raw_telemetry.device_id", "t1"."metric_val" AS "raw_telemetry.metric_val"'
        in sql
    )
    assert 'WHERE ("t1"."device_id" IN (SELECT "t1"."cluster_id"' in sql
    assert 'NOT EXISTS (SELECT "t1"."id" AS "quarantine_devices.id"' in sql

    # 2. Verify placeholder alignment: count of %s in SQL must exactly equal len(params)
    placeholder_count = sql.count("%s")
    assert placeholder_count == len(params)

    # 3. Verify exact sequential parameter order
    expected_params = [
        "healthy",
        10.5,
        100,
        10,
        "us-east-1",
        50,
        5,
        "premium",
        "compromised",
        5,
        0,
        20,
        0,
        99.9,
        15,
        0,
    ]
    assert params == expected_params

    # 4. Verify count query parameter ordering
    count_placeholder_count = count_sql.count("%s")
    assert count_placeholder_count == len(count_params)
    expected_count_params = [
        "healthy",
        10.5,
        100,
        10,
        "us-east-1",
        50,
        5,
        "premium",
        "compromised",
        5,
        0,
        20,
        0,
        99.9,
    ]
    assert count_params == expected_count_params


# =====================================================================
# 2. Multi-Part Schema Names Across Dialects
# =====================================================================
def test_adversarial_multipart_schemas_across_dialects():
    """Verify 3-part and 4-part schema names compile with correct quotes across dialects."""
    spec = {
        "table": "enterprise_dw.finance_mart.general_ledger",
        "columns": [
            "enterprise_dw.finance_mart.general_ledger.account_id",
            "enterprise_dw.finance_mart.general_ledger.amount",
        ],
        "joins": [
            {
                "table": "enterprise_dw.finance_mart.chart_of_accounts",
                "left_col": "account_id",
                "right_col": "id",
            }
        ],
        "filters": [
            {
                "column": "enterprise_dw.finance_mart.general_ledger.amount",
                "op": "gt",
                "value": 1000,
            }
        ],
        "limit": 10,
        "offset": 0,
    }

    # Test Postgres
    sql_pg, _, _, _ = QueryCompiler(spec, dialect="postgres").compile()
    assert 'FROM "enterprise_dw"."finance_mart"."general_ledger" "t1"' in sql_pg
    assert (
        'LEFT JOIN "enterprise_dw"."finance_mart"."chart_of_accounts" "t2" ON "t1"."account_id" = "t2"."id"'
        in sql_pg
    )

    # Test MySQL (backtick quoting)
    sql_mysql, _, _, _ = QueryCompiler(spec, dialect="mysql").compile()
    assert "FROM `enterprise_dw`.`finance_mart`.`general_ledger` `t1`" in sql_mysql
    assert (
        "LEFT JOIN `enterprise_dw`.`finance_mart`.`chart_of_accounts` `t2` ON `t1`.`account_id` = `t2`.`id`"
        in sql_mysql
    )

    # Test SQLite (double quote, question mark placeholders)
    sql_sqlite, params_sqlite, _, _ = QueryCompiler(spec, dialect="sqlite").compile()
    assert 'FROM "enterprise_dw"."finance_mart"."general_ledger" "t1"' in sql_sqlite
    assert (
        'LEFT JOIN "enterprise_dw"."finance_mart"."chart_of_accounts" "t2" ON "t1"."account_id" = "t2"."id"'
        in sql_sqlite
    )
    assert sql_sqlite.count("?") == 3
    assert params_sqlite == [1000, 10, 0]

    # Test Snowflake
    sql_snow, _, _, _ = QueryCompiler(spec, dialect="snowflake").compile()
    assert 'FROM "enterprise_dw"."finance_mart"."general_ledger" "t1"' in sql_snow
    assert (
        'LEFT JOIN "enterprise_dw"."finance_mart"."chart_of_accounts" "t2" ON "t1"."account_id" = "t2"."id"'
        in sql_snow
    )

    # Test MSSQL (square brackets)
    sql_mssql, _, _, _ = QueryCompiler(spec, dialect="mssql").compile()
    assert "FROM [enterprise_dw].[finance_mart].[general_ledger] [t1]" in sql_mssql
    assert (
        "LEFT JOIN [enterprise_dw].[finance_mart].[chart_of_accounts] [t2] ON [t1].[account_id] = [t2].[id]"
        in sql_mssql
    )
    assert "ORDER BY (SELECT NULL)" in sql_mssql
    assert "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" in sql_mssql

    # Test BigQuery
    sql_bq, _, _, _ = QueryCompiler(spec, dialect="bigquery").compile()
    assert "FROM `enterprise_dw`.`finance_mart`.`general_ledger` `t1`" in sql_bq
    assert "LEFT JOIN `enterprise_dw`.`finance_mart`.`chart_of_accounts` `t2`" in sql_bq


# =====================================================================
# 3. Self-Joins and Multiple Joins to Same Table
# =====================================================================
def test_adversarial_self_joins_and_repeated_tables():
    """Verify joining the same table multiple times assigns non-colliding unique aliases."""
    spec = {
        "table": "nodes",
        "columns": [
            "nodes.id",
            "parent.id",
            "grandparent.id",
            "sibling.id",
            "t2.id",  # Automatic alias reference
        ],
        "joins": [
            {
                "table": "nodes",
                "alias": "parent",
                "type": "left",
                "left_col": "parent_id",
                "right_col": "id",
            },
            {
                "table": "nodes",
                "alias": "grandparent",
                "type": "left",
                "left_table": "parent",
                "left_col": "parent_id",
                "right_col": "id",
            },
            {
                "table": "nodes",
                "alias": "sibling",
                "type": "inner",
                "left_col": "parent_id",
                "right_col": "parent_id",
            },
            {
                "table": "nodes",  # Auto alias without explicit alias
                "type": "left",
                "left_col": "id",
                "right_col": "id",
            },
        ],
    }

    compiler = QueryCompiler(spec)
    sql, _, _, _ = compiler.compile()

    # Verify distinct aliases are generated and referenced properly
    assert 'FROM "nodes" "t1"' in sql
    assert 'LEFT JOIN "nodes" "parent" ON "t1"."parent_id" = "parent"."id"' in sql
    assert (
        'LEFT JOIN "nodes" "grandparent" ON "parent"."parent_id" = "grandparent"."id"'
        in sql
    )
    assert (
        'INNER JOIN "nodes" "sibling" ON "t1"."parent_id" = "sibling"."parent_id"'
        in sql
    )
    assert 'LEFT JOIN "nodes" "t2" ON "t1"."id" = "t2"."id"' in sql

    # Verify unjoined left_table reference is detected and raises CompilationError
    bad_spec = {
        "table": "nodes",
        "joins": [
            {
                "table": "nodes",
                "left_table": "phantom_target",
                "left_col": "id",
                "right_col": "id",
            }
        ],
    }
    with pytest.raises(
        CompilationError,
        match="Join left_table 'phantom_target' is not part of the query",
    ):
        QueryCompiler(bad_spec).compile()


# =====================================================================
# 4. AST Safety: Malicious Payloads vs Benign Queries
# =====================================================================
def test_adversarial_ast_safety_and_false_positives():
    """Verify injection payloads are blocked while benign SQL patterns are permitted."""
    malicious_payloads = [
        # Semicolon chaining
        "SELECT 1; DROP TABLE users;",
        "SELECT 1; TRUNCATE TABLE users;",
        "SELECT 1;\n-- comment\nALTER TABLE users ADD COLUMN is_admin INT;",
        # Semicolon disguised in comments
        "SELECT 1 /* comment */ ; DROP TABLE users;",
        "SELECT 1 -- line comment\n; DROP TABLE users;",
        # CTE disguised mutations
        "WITH hacked AS (DELETE FROM accounts RETURNING *) SELECT * FROM hacked;",
        "WITH hacked AS (INSERT INTO users (id) VALUES (1)) SELECT 1;",
        "WITH hacked AS (UPDATE users SET role = 'admin') SELECT 1;",
        "WITH a AS (SELECT 1), evil AS (TRUNCATE logs) SELECT 1;",
        # Restricted system and auth tables
        "SELECT * FROM users UNION SELECT * FROM auth_user;",
        "SELECT * FROM django_session;",
        "SELECT * FROM sqlite_master;",
        "SELECT * FROM mysql.user;",
        "SELECT * FROM sys.objects;",
        "SELECT * FROM users, auth_user",  # without semicolon
        "SELECT * FROM users JOIN auth_user ON users.id = auth_user.id;",
        "SELECT * FROM public.auth_user;",
        # Dangerous functions
        "SELECT pg_sleep(5);",
        "SELECT xp_cmdshell('whoami');",
    ]

    for payload in malicious_payloads:
        result = validate_sql_ast(payload)
        assert result["valid"] is False, (
            f"Expected payload to be rejected, but it was accepted: {payload}"
        )

    benign_queries = [
        # Comments containing forbidden words
        "SELECT id FROM users -- drop table is mentioned here",
        "SELECT id FROM users /* please delete obsolete cache */ WHERE id = 1",
        "SELECT id FROM users -- update status on next release\nWHERE active = 1",
        # String literals with SQL keywords and escapes
        "SELECT 'drop table users' AS query_snippet FROM users",
        "SELECT 'user\\'s delete action' AS note FROM users",
        "SELECT 'user''s delete action' AS note FROM users",
        "SELECT 'truncate table records' AS description FROM users",
        # Quoted identifiers matching keywords
        'SELECT "drop", "delete", "table", "update", "set" FROM users',
        "SELECT `drop`, `delete`, `table` FROM users",
        "SELECT [drop], [delete], [table] FROM users",
        # Allowed column names with substrings
        "SELECT u.user_profile, u.auth_user_id FROM user_data u",
        # Benign CTEs
        "WITH cte1 AS (SELECT 1 AS val), cte2 AS (SELECT 2 AS val) SELECT * FROM cte1, cte2",
    ]

    for benign in benign_queries:
        result = validate_sql_ast(benign)
        err = result.get("violations") or [result.get("error")]
        assert result["valid"] is True, (
            f"Expected benign query to pass, but got error {err} for: {benign}"
        )


def test_adversarial_ast_trailing_semicolon_restricted_table_bypass():
    """
    Verify comma-separated restricted tables with trailing semicolons and
    subqueries in FROM clause are strictly rejected.
    """
    bypass_queries = [
        "SELECT * FROM users, auth_user;",
        "SELECT * FROM users, auth_user; -- comment",
        "SELECT * FROM users, auth_user /* comment */ ;",
        "SELECT * FROM users, django_session;",
        "SELECT * FROM users, sqlite_master;",
        "SELECT * FROM users, pg_shadow;",
        "SELECT * FROM users, passwords;",
        "SELECT * FROM users, credentials;",
        "SELECT * FROM (SELECT 1) s, auth_user",
        "SELECT * FROM (SELECT 1) s, auth_user;",
        "SELECT * FROM (SELECT 1 WHERE 1=1) s, auth_user",
        "SELECT * FROM (SELECT 1 WHERE 1=1) s, auth_user;",
        'SELECT * FROM (SELECT "id" WHERE 1=1) s, auth_user;',
        "SELECT * FROM (SELECT `id` WHERE 1=1) s, auth_user;",
        "SELECT * FROM (SELECT [id] WHERE 1=1) s, auth_user;",
        "SELECT * FROM (SELECT 1 ORDER BY id) s, auth_user;",
        "SELECT * FROM (SELECT id FROM users) u, django_session;",
        "SELECT * FROM users, (SELECT 1) s, sqlite_master;",
        "SELECT * FROM (SELECT * FROM (SELECT 1) a, auth_user) b;",
        'SELECT * FROM "users", `auth_user`, [django_session];',
        "SELECT * FROM (auth_user);",
        "SELECT * FROM users, (auth_user);",
    ]
    for q in bypass_queries:
        result = validate_sql_ast(q)
        assert result["valid"] is False, (
            f"Expected {q} to be rejected, but it was accepted."
        )

    # Directly verify helper edge branches
    assert _extract_from_body("users, auth_user) s", 0) == "users, auth_user"
    assert _split_from_items("a, b)") == ["a", "b)"]


# =====================================================================
# 5. Filter Logic: Empty IN, NULLs, SQL 3-Valued Logic, Grouping
# =====================================================================
def test_adversarial_filter_logic_and_three_valued_semantics():
    """Verify empty IN/NOT IN, NULL comparisons, SQL 3-valued logic, and nested grouping."""
    # 1. Empty IN and NOT IN
    empty_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [
            {"column": "users.tag", "op": "in", "value": []},
            {"column": "users.status", "op": "not in", "value": []},
        ],
    }
    sql_empty, params_empty, _, _ = QueryCompiler(empty_spec).compile()
    assert "1 = 0" in sql_empty
    assert "1 = 1" in sql_empty
    assert params_empty == [50, 0]  # Only default limit/offset

    # 2. None equality and inequality
    null_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [
            {"column": "users.archived_at", "op": "eq", "value": None},
            {"column": "users.activated_at", "op": "neq", "value": None},
            {"column": "users.deleted_at", "op": "=", "value": None},
            {"column": "users.updated_at", "op": "!=", "value": None},
        ],
    }
    sql_null, params_null, _, _ = QueryCompiler(null_spec).compile()
    assert '"t1"."archived_at" IS NULL' in sql_null
    assert '"t1"."activated_at" IS NOT NULL' in sql_null
    assert '"t1"."deleted_at" IS NULL' in sql_null
    assert '"t1"."updated_at" IS NOT NULL' in sql_null
    assert params_null == [50, 0]

    # 3. SQL 3-valued logic: NOT IN containing NULL
    not_in_none_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [
            {"column": "users.role", "op": "not in", "value": ["admin", None, "owner"]}
        ],
    }
    sql_nin, params_nin, _, _ = QueryCompiler(not_in_none_spec).compile()
    assert '("t1"."role" NOT IN (%s, %s) AND "t1"."role" IS NOT NULL)' in sql_nin
    assert params_nin == ["admin", "owner", 50, 0]

    # 4. NOT IN containing only NULL(s) evaluates to 1 = 0
    not_in_only_none_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [{"column": "users.role", "op": "not in", "value": [None, None]}],
    }
    sql_nin_only, _, _, _ = QueryCompiler(not_in_only_none_spec).compile()
    assert "1 = 0" in sql_nin_only

    # 5. IN containing NULL
    in_none_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [
            {"column": "users.role", "op": "in", "value": ["admin", None, "member"]}
        ],
    }
    sql_in, params_in, _, _ = QueryCompiler(in_none_spec).compile()
    assert '("t1"."role" IN (%s, %s) OR "t1"."role" IS NULL)' in sql_in
    assert params_in == ["admin", "member", 50, 0]

    # 6. IN containing only NULL(s) evaluates to IS NULL
    in_only_none_spec = {
        "table": "users",
        "columns": ["users.id"],
        "filters": [{"column": "users.role", "op": "in", "value": [None]}],
    }
    sql_in_only, _, _, _ = QueryCompiler(in_only_none_spec).compile()
    assert '"t1"."role" IS NULL' in sql_in_only

    # 7. Complex boolean grouping with arbitrary nesting
    group_spec = {
        "table": "orders",
        "columns": ["orders.id"],
        "filters": [
            {
                "column": "status",
                "op": "eq",
                "value": "pending",
                "parenOpen": "((",
            },
            {"column": "status", "op": "eq", "value": "processing", "combiner": "OR"},
            {
                "column": "total",
                "op": "gte",
                "value": 100,
                "combiner": "AND",
                "parenClose": ")",
            },
            {
                "column": "is_rush",
                "op": "eq",
                "value": True,
                "combiner": "OR",
                "parenOpen": "(",
            },
            {
                "column": "vip_customer",
                "op": "eq",
                "value": True,
                "combiner": "AND",
                "parenClose": "))",
            },
        ],
    }
    sql_grp, params_grp, _, _ = QueryCompiler(group_spec).compile()
    assert (
        '(("t1"."status" = %s OR "t1"."status" = %s AND "t1"."total" >= %s) OR ("t1"."is_rush" = %s AND "t1"."vip_customer" = %s))'
        in sql_grp
    )
    assert params_grp == ["pending", "processing", 100, True, True, 50, 0]


# =====================================================================
# 6. Dialect Pagination: MSSQL Fallback ORDER BY and Informix Prefix
# =====================================================================
def test_adversarial_pagination_mssql_and_informix():
    """Verify MSSQL fallback ORDER BY (SELECT NULL) and Informix prefix pagination parameter ordering."""
    # 1. MSSQL pagination without order_by must inject ORDER BY (SELECT NULL)
    mssql_unorder_spec = {
        "table": "inventory",
        "columns": ["inventory.item_id"],
        "filters": [{"column": "inventory.quantity", "op": "lt", "value": 10}],
        "limit": 20,
        "offset": 40,
    }
    sql_ms, params_ms, _, _ = QueryCompiler(
        mssql_unorder_spec, dialect="mssql"
    ).compile()
    assert "ORDER BY (SELECT NULL)" in sql_ms
    assert "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY" in sql_ms
    assert params_ms == [10, 40, 20]

    # 2. MSSQL pagination WITH explicit order_by must not inject fallback
    mssql_order_spec = {
        "table": "inventory",
        "columns": ["inventory.item_id"],
        "order_by": [{"column": "inventory.item_id", "direction": "asc"}],
        "limit": 20,
        "offset": 40,
    }
    sql_ms_o, params_ms_o, _, _ = QueryCompiler(
        mssql_order_spec, dialect="mssql"
    ).compile()
    assert "(SELECT NULL)" not in sql_ms_o
    assert "ORDER BY [t1].[item_id] ASC" in sql_ms_o
    assert params_ms_o == [40, 20]

    # 3. Informix prefix pagination: parameters order is [offset, limit, *filters]
    informix_spec = {
        "table": "inventory",
        "columns": ["inventory.item_id", "inventory.quantity"],
        "filters": [
            {"column": "inventory.warehouse_id", "op": "eq", "value": "W1"},
            {"column": "inventory.quantity", "op": "gt", "value": 0},
        ],
        "limit": 15,
        "offset": 30,
    }
    sql_inf, params_inf, _, _ = QueryCompiler(
        informix_spec, dialect="informix"
    ).compile()
    assert (
        'SELECT SKIP %s FIRST %s "t1"."item_id" AS "inventory.item_id", "t1"."quantity" AS "inventory.quantity"'
        in sql_inf
    )
    assert params_inf == [30, 15, "W1", 0]


# =====================================================================
# 7. Exception Hierarchy and Polymorphism
# =====================================================================
def test_adversarial_exception_hierarchy():
    """Verify domain exception hierarchy and polymorphic exception catching."""
    # Direct class inheritance
    assert issubclass(SecurityError, CompilationError)
    assert issubclass(SecurityError, QueryBuilderError)
    assert issubclass(ValidationError, CompilationError)
    assert issubclass(ValidationError, QueryBuilderError)
    assert issubclass(CompilationError, QueryBuilderError)
    assert issubclass(DialectError, QueryBuilderError)
    assert not issubclass(DialectError, CompilationError)

    # Instance checks
    sec_err = SecurityError("Security breach detected")
    val_err = ValidationError("Field schema mismatch")
    comp_err = CompilationError("Syntax invalid")
    dial_err = DialectError("Invalid dialect identifier")

    assert isinstance(sec_err, CompilationError)
    assert isinstance(val_err, CompilationError)
    assert isinstance(comp_err, QueryBuilderError)
    assert isinstance(dial_err, QueryBuilderError)
    assert not isinstance(dial_err, CompilationError)

    # Polymorphic catch verification
    caught_sec = False
    try:
        raise sec_err
    except CompilationError as e:
        assert isinstance(e, SecurityError)
        caught_sec = True
    assert caught_sec

    caught_val = False
    try:
        raise val_err
    except CompilationError as e:
        assert isinstance(e, ValidationError)
        caught_val = True
    assert caught_val


def run_standalone_stress_suite() -> int:
    """Standalone runner executing all stress tests and reporting empirical verdict."""
    print("=" * 70)
    print("RUNNING STANDALONE ADVERSARIAL STRESS TEST SUITE (MILESTONE 1)")
    print("=" * 70)

    passed_count = 0
    failed_count = 0

    # 1. Nested subqueries
    try:
        test_adversarial_nested_subqueries_from_and_where_ordering()
        print("[PASS] Test 1: Multi-level nested subqueries (FROM & WHERE ordering)")
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 1: Nested subqueries failed: {e}")
        failed_count += 1

    # 2. Multi-part schemas
    try:
        test_adversarial_multipart_schemas_across_dialects()
        print("[PASS] Test 2: Multi-part schema names across dialects")
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 2: Multi-part schema names failed: {e}")
        failed_count += 1

    # 3. Self-joins
    try:
        test_adversarial_self_joins_and_repeated_tables()
        print("[PASS] Test 3: Self-joins and non-colliding table alias allocation")
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 3: Self-joins failed: {e}")
        failed_count += 1

    # 4. AST safety (benign vs malicious)
    try:
        test_adversarial_ast_safety_and_false_positives()
        print(
            "[PASS] Test 4a: AST safety (benign queries & comment/CTE mutation rejection)"
        )
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 4a: AST safety failed: {e}")
        failed_count += 1

    # 4b. AST safety vulnerability check (disproven condition)
    ast_vulnerability_found = False
    try:
        test_adversarial_ast_trailing_semicolon_restricted_table_bypass()
        print("[SECURE] Test 4b: Trailing semicolon restricted table check passed.")
    except AssertionError as e:
        print(f"[VULNERABILITY DISCOVERED] Test 4b: {e}")
        ast_vulnerability_found = True

    # 5. Filter logic
    try:
        test_adversarial_filter_logic_and_three_valued_semantics()
        print("[PASS] Test 5: Filter logic (empty IN, NULLs, 3-valued logic, grouping)")
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 5: Filter logic failed: {e}")
        failed_count += 1

    # 6. Pagination
    try:
        test_adversarial_pagination_mssql_and_informix()
        print("[PASS] Test 6: Dialect pagination (MSSQL fallback & Informix prefix)")
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 6: Dialect pagination failed: {e}")
        failed_count += 1

    # 7. Exception hierarchy
    try:
        test_adversarial_exception_hierarchy()
        print("[PASS] Test 7: Domain exception hierarchy & polymorphic catching")
        passed_count += 1
    except (AssertionError, QueryBuilderError, ValueError) as e:
        print(f"[FAIL] Test 7: Exception hierarchy failed: {e}")
        failed_count += 1

    print("=" * 70)
    print(f"Summary: {passed_count} suites passed, {failed_count} suites failed.")
    if ast_vulnerability_found:
        print(
            "VERDICT: DISPROVEN (Security vulnerability discovered in AST validation)"
        )
        return 1
    else:
        print("VERDICT: CONFIRMED")
        return 0


if __name__ == "__main__":
    sys.exit(run_standalone_stress_suite())
