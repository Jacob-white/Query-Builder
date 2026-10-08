from query_builder.ast_validator import validate_sql_ast


def test_validate_sql_ast_empty():
    res = validate_sql_ast("")
    assert res["valid"] is False
    assert res["ast_validated"] is False
    assert res["statement_type"] == "NONE"


def test_validate_sql_ast_valid_select():
    res = validate_sql_ast(
        "SELECT legal_name, total_aum FROM production.firm_master WHERE total_aum > 1000000 LIMIT 50;"
    )
    assert res["valid"] is True
    assert res["ast_validated"] is True
    assert res["statement_type"] == "SELECT"
    assert res["injection_risk"] == "NONE"
    assert len(res["violations"]) == 0


def test_validate_sql_ast_valid_cte():
    sql = """
    WITH top_firms AS (
        SELECT firm_master_id, legal_name, total_aum
        FROM production.firm_master
        WHERE total_aum IS NOT NULL
        ORDER BY total_aum DESC
        LIMIT 20
    )
    SELECT * FROM top_firms;
    """
    res = validate_sql_ast(sql, allowed_schemas=["production"])
    assert res["valid"] is True
    assert res["ast_validated"] is True
    assert res["is_read_only"] is True
    assert len(res["violations"]) == 0


def test_validate_sql_ast_blocks_mutations():
    mutations = [
        "DELETE FROM production.firm_master WHERE id = 1;",
        "DROP TABLE production.firm_master;",
        "TRUNCATE production.firm_master;",
        "UPDATE production.firm_master SET legal_name = 'Hacked';",
        "INSERT INTO production.firm_master (legal_name) VALUES ('Test');",
        "ALTER TABLE production.firm_master ADD COLUMN hacked text;",
        "GRANT ALL PRIVILEGES ON DATABASE mydb TO hacker;",
        "REVOKE SELECT ON production.firm_master FROM normal_user;",
    ]
    for sql in mutations:
        res = validate_sql_ast(sql)
        assert res["valid"] is False
        assert res["is_read_only"] is False
        assert res["injection_risk"] == "CRITICAL"


def test_validate_sql_ast_blocks_semicolon_chaining():
    sql = "SELECT legal_name FROM production.firm_master; DROP TABLE production.firm_master;"
    res = validate_sql_ast(sql)
    assert res["valid"] is False
    assert res["statement_type"] == "MULTI_STATEMENT"
    assert res["injection_risk"] == "CRITICAL"
    assert any("Multiple statements" in v for v in res["violations"])


def test_validate_sql_ast_blocks_restricted_system_tables():
    restricted = [
        "SELECT * FROM auth_user;",
        "SELECT * FROM django_session;",
        "SELECT * FROM authtoken_token;",
        "SELECT * FROM pg_shadow;",
        "SELECT * FROM passwords;",
    ]
    for sql in restricted:
        res = validate_sql_ast(sql)
        assert res["valid"] is False
        assert any("restricted" in v.lower() for v in res["violations"])


def test_validate_sql_ast_blocks_restricted_schemas():
    sql = "SELECT * FROM information_schema.tables;"
    res = validate_sql_ast(sql)
    assert res["valid"] is False
    assert any(
        "analytical" in v.lower() or "schema" in v.lower() for v in res["violations"]
    )


def test_validate_sql_ast_permits_safe_set_transaction():
    sql = "SET TRANSACTION READ ONLY; SELECT legal_name FROM production.firm_master;"
    # Semicolon chaining still flags multi statement
    res = validate_sql_ast(sql)
    assert res["valid"] is False
    assert res["statement_type"] == "MULTI_STATEMENT"


def test_validate_sql_ast_comments_only():
    res = validate_sql_ast("; ; ;")
    assert res["valid"] is False
    assert "no executable statements" in res["violations"][0].lower()


def test_validate_sql_ast_disallow_cte():
    sql = "WITH cte AS (SELECT 1 AS val) SELECT * FROM cte;"
    res = validate_sql_ast(sql, allow_cte=False)
    assert res["valid"] is False
    assert any(
        "Common Table Expressions (WITH) are not permitted" in v
        for v in res["violations"]
    )


def test_validate_sql_ast_allowed_schema_exception():
    sql = "SELECT id FROM analytics.sales;"
    res = validate_sql_ast(
        sql,
        allowed_schemas=["analytics"],
        restricted_schema_patterns=[r"\banalytics\."],
    )
    assert res["valid"] is True


def test_validate_sql_ast_unknown_statement_risk_high():
    sql = "CHECKPOINT;"
    res = validate_sql_ast(sql)
    assert res["valid"] is False
    assert res["injection_risk"] == "HIGH"


def test_validate_sql_ast_allows_literals_with_mutation_words():
    sql = "SELECT is_deleted, 'cannot delete record' AS note FROM production.firm_master WHERE name = 'drop';"
    res = validate_sql_ast(sql)
    assert res["valid"] is True
    assert res["ast_validated"] is True
    assert len(res["violations"]) == 0


def test_validate_sql_ast_multipart_restricted_tables():
    restricted_queries = [
        "SELECT * FROM db.schema.auth_user;",
        "SELECT * FROM catalog.db.credentials;",
        "SELECT * FROM [mydb].[myschema].[passwords];",
        'SELECT * FROM "mydb"."myschema"."auth_user";',
        "SELECT * FROM cluster.mysql.user;",
        "SELECT * FROM production.orders JOIN db.auth.auth_user ON orders.user_id = auth_user.id;",
        "SELECT * FROM production.orders, cluster.secure.django_session WHERE orders.id = django_session.id;",
    ]
    for sql in restricted_queries:
        res = validate_sql_ast(sql)
        assert res["valid"] is False, f"Expected {sql} to be blocked"
        assert any("restricted" in v.lower() for v in res["violations"]), (
            f"Expected restriction violation in {res['violations']} for {sql}"
        )


def test_validate_sql_ast_multipart_allowed_tables():
    safe_queries = [
        "SELECT * FROM catalog.sales.orders;",
        "SELECT * FROM catalog.sales.orders, catalog.sales.items;",
        'SELECT * FROM "my_catalog"."my_schema"."customers";',
    ]
    for sql in safe_queries:
        res = validate_sql_ast(sql)
        assert res["valid"] is True, (
            f"Expected {sql} to be valid, got violations: {res['violations']}"
        )
        assert res["ast_validated"] is True
        assert len(res["violations"]) == 0


def test_validate_sql_ast_remediated_bypass_vectors():
    bypass_attacks = [
        "SELECT * FROM db.\tauth_user",
        "SELECT * FROM db.\nauth_user",
        "SELECT * FROM db.schema.\tauth_user",
        "SELECT * FROM db.schema.\nauth_user",
        "SELECT * FROM db.--comment\nauth_user",
        "SELECT * FROM db..auth_user",
        "SELECT * FROM [db]..[auth_user]",
        'SELECT * FROM "db".."auth_user"',
        "SELECT * FROM(auth_user)",
        "SELECT * FROM(db.schema.auth_user)",
        "SELECT * FROM orders INNER JOIN(db.schema.auth_user) ON 1=1",
        "SELECT * FROM ONLY auth_user",
        "SELECT * FROM ONLY db.schema.auth_user",
        "SELECT * FROM orders CROSS APPLY db.schema.auth_user",
        "SELECT * FROM orders OUTER APPLY db.schema.auth_user",
    ]
    for sql in bypass_attacks:
        res = validate_sql_ast(sql)
        assert res["valid"] is False, f"Expected {repr(sql)} to be blocked"
        assert any("restricted" in v.lower() for v in res["violations"]), (
            f"Expected restricted table violation in {res['violations']} for {repr(sql)}"
        )


def test_validate_sql_ast_empty_identifier_segments():
    assert validate_sql_ast('SELECT * FROM ""')["valid"] is True
    assert validate_sql_ast('SELECT * FROM users, ""')["valid"] is True
    assert validate_sql_ast('SELECT * FROM ""..""')["valid"] is True


def test_validate_sql_ast_remediated_spaced_double_dots():
    queries = [
        "SELECT * FROM db . . auth_user",
        "SELECT * FROM db. .auth_user",
        "SELECT * FROM db. . auth_user",
        "SELECT * FROM db . .auth_user",
        "SELECT * FROM db . /*comment*/ . auth_user",
        "SELECT * FROM db./*comment*/.auth_user",
        "SELECT * FROM db . --comment\n . auth_user",
        "SELECT * FROM [db] . . [auth_user]",
        'SELECT * FROM "db" . . "auth_user"',
        "SELECT * FROM `db` . . `auth_user`",
        "SELECT * FROM orders JOIN db . . auth_user ON 1=1",
        "SELECT * FROM orders CROSS APPLY db . . auth_user",
        "SELECT * FROM s . d . . auth_user",
        "SELECT * FROM s . . . auth_user",
        "SELECT * FROM t1, db . . auth_user, t2",
        "SELECT * FROM (SELECT * FROM db . . auth_user)",
        "WITH cte AS (SELECT * FROM db . . auth_user) SELECT * FROM cte",
    ]
    for sql in queries:
        res = validate_sql_ast(sql)
        assert res["valid"] is False, f"Expected {repr(sql)} to be blocked"
        assert any("restricted" in v.lower() for v in res["violations"]), (
            f"Expected restriction violation in {res['violations']} for {repr(sql)}"
        )


def test_validate_sql_ast_remediated_system_schema_double_dots():
    queries = [
        "SELECT * FROM sys . /*comment*/ . tables",
        "SELECT * FROM sys . . objects",
        "SELECT * FROM mysql . . user",
        "SELECT * FROM pg_catalog . . pg_user",
        "SELECT * FROM pg_catalog . . pg_proc",
        "SELECT * FROM information_schema . . columns",
        "SELECT * FROM master..sysdatabases",
        "SELECT * FROM msdb..sysjobs",
    ]
    for sql in queries:
        res = validate_sql_ast(sql)
        assert res["valid"] is False, f"Expected {repr(sql)} to be blocked"
        assert any(
            "analytical" in v.lower()
            or "schema" in v.lower()
            or "restricted" in v.lower()
            for v in res["violations"]
        ), (
            f"Expected schema restriction violation in {res['violations']} for {repr(sql)}"
        )


def test_validate_sql_ast_remediated_lateral_prefix():
    queries = [
        "SELECT * FROM LATERAL auth_user",
        "SELECT * FROM orders JOIN LATERAL auth_user ON 1=1",
        "SELECT * FROM orders CROSS JOIN LATERAL auth_user",
        "SELECT * FROM orders, LATERAL auth_user",
        "SELECT * FROM LATERAL(auth_user)",
        "SELECT * FROM LATERAL (db . . auth_user)",
        "SELECT * FROM (LATERAL auth_user)",
    ]
    for sql in queries:
        res = validate_sql_ast(sql)
        assert res["valid"] is False, f"Expected {repr(sql)} to be blocked"
        assert any("restricted" in v.lower() for v in res["violations"]), (
            f"Expected restriction violation in {res['violations']} for {repr(sql)}"
        )


def test_validate_sql_ast_benign_projections_no_false_positives():
    benign = [
        "SELECT u.user_profile FROM user_data u",
        "SELECT a.passwords, b.credentials FROM my_table a JOIN other_table b ON a.id = b.id",
        "SELECT u.user_profile, u.id FROM user_data u WHERE u.id = 1",
        "SELECT user_data.user_profile FROM user_data",
        "SELECT u.pg_user, u.pg_database FROM app_users u",
        "SELECT o.id, c.user_profile FROM orders o JOIN customers c ON o.customer_id = c.id",
        "SELECT catalog.sales.orders.total FROM catalog.sales.orders",
        "SELECT COUNT(u.user_profile) FROM user_data u GROUP BY u.status",
        "SELECT * FROM user_data WHERE user_profile IS NOT NULL",
    ]
    for sql in benign:
        res = validate_sql_ast(sql)
        assert res["valid"] is True, (
            f"Expected {repr(sql)} to be valid, got violations: {res['violations']}"
        )
        assert res["ast_validated"] is True
        assert len(res["violations"]) == 0
