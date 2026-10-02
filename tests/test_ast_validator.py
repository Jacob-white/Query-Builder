from query_builder.ast_validator import validate_sql_ast


def test_validate_sql_ast_empty():
    res = validate_sql_ast("")
    assert res["valid"] is False
    assert res["ast_validated"] is False
    assert res["statement_type"] == "NONE"


def test_validate_sql_ast_valid_select():
    res = validate_sql_ast("SELECT legal_name, total_aum FROM production.firm_master WHERE total_aum > 1000000 LIMIT 50;")
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
    assert any("analytical" in v.lower() or "schema" in v.lower() for v in res["violations"])


def test_validate_sql_ast_permits_safe_set_transaction():
    sql = "SET TRANSACTION READ ONLY; SELECT legal_name FROM production.firm_master;"
    # Semicolon chaining still flags multi statement
    res = validate_sql_ast(sql)
    assert res["valid"] is False
    assert res["statement_type"] == "MULTI_STATEMENT"
