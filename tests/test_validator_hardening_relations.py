"""Relation extraction + SQL-executing function deny-list (ISSUE 2)."""

from __future__ import annotations

import pytest

from query_builder.ast_validator import validate_sql_ast


def _invalid(sql: str) -> dict:
    res = validate_sql_ast(sql)
    assert res["valid"] is False, f"expected denial for: {sql!r} -> {res}"
    return res


def _valid(sql: str) -> dict:
    res = validate_sql_ast(sql)
    assert res["valid"] is True, f"expected valid for: {sql!r} -> {res['violations']}"
    return res


@pytest.mark.parametrize(
    "sql",
    [
        # PostgreSQL `TABLE name` shorthand
        "SELECT * FROM (TABLE auth_user) t",
        "WITH x AS (TABLE auth_user) SELECT * FROM x",
        "SELECT * FROM t UNION TABLE auth_user",
        "SELECT * FROM t UNION ALL TABLE public.auth_user",
        "SELECT * FROM (TABLE ONLY auth_user) t",
        # MySQL / MariaDB STRAIGHT_JOIN
        "SELECT * FROM t STRAIGHT_JOIN auth_user ON 1=1",
        "SELECT * FROM t straight_join `auth_user` ON 1=1",
        # JOIN variants
        "SELECT * FROM t NATURAL JOIN auth_user",
        "SELECT * FROM t NATURAL LEFT JOIN auth_user",
        "SELECT * FROM t LEFT OUTER JOIN auth_user ON t.id = auth_user.id",
        "SELECT * FROM t CROSS JOIN auth_user",
        "SELECT * FROM t CROSS APPLY auth_user",
        "SELECT * FROM t JOIN LATERAL auth_user ON true",
        "SELECT * FROM t, LATERAL auth_user",
        "SELECT * FROM t JOIN u USING auth_user",
        # comma joins (also nested / after a join / after ONLY)
        "SELECT * FROM t, auth_user",
        "SELECT * FROM t JOIN u ON t.a = u.a, auth_user",
        "SELECT * FROM t, ONLY auth_user",
        "SELECT * FROM (SELECT 1 FROM a, b, credentials) s",
        "SELECT * FROM t, (SELECT 1) s, auth_user",
        # schema-qualified / quoted
        "SELECT * FROM mydb.public.auth_user",
        'SELECT * FROM "auth_user"',
        "SELECT * FROM [dbo].[auth_user]",
        "SELECT * FROM mysql.user",
        "SELECT * FROM t JOIN information_schema.tables ON 1=1",
        "SELECT * FROM db..auth_user",
        # `FROM #x` newline: MySQL `#` comment
        "SELECT * FROM #x\nauth_user",
        # dollar quoting hiding a quote
        "SELECT $$ ' $$ FROM auth_user WHERE x = $$ ' $$",
    ],
)
def test_restricted_relation_in_any_position_is_denied(sql: str) -> None:
    res = _invalid(sql)
    assert any(
        "restricted" in v.lower() or "denied" in v.lower() for v in res["violations"]
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT query_to_xml('select * from auth_user', true, false, '')",
        "SELECT * FROM query_to_xml('select * from auth_user', true, false, '') x",
        "SELECT query_to_xml_and_xmlschema('select 1', true, false, '')",
        "SELECT table_to_xml('auth_user', true, false, '')",
        "SELECT cursor_to_xml('c', 5, false, false, '')",
        "SELECT schema_to_xml('public', true, false, '')",
        "SELECT database_to_xml(true, false, '')",
        "SELECT * FROM dblink('dbname=x', 'select * from auth_user') AS t(a int)",
        "SELECT dblink_exec('dbname=x', 'drop table t')",
        "SELECT dblink_connect('x')",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(1, '/tmp/x')",
        "SELECT set_config('x', 'y', false)",
        "SELECT * FROM OPENROWSET('SQLNCLI', 'Server=x;', 'select 1')",
        "SELECT * FROM OPENQUERY(srv, 'select * from auth_user')",
        "SELECT xp_cmdshell('whoami')",
        "SELECT xp_dirtree('c:\\')",
        "SELECT sp_oacreate('x', 1)",
        "SELECT extractvalue(1, concat(0x7e, version()))",
        "SELECT updatexml(1, concat(0x7e, version()), 1)",
        "SELECT load_extension('x')",
        "SELECT readfile('/etc/passwd')",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('s3://x')",
        "SELECT * FROM query('select * from auth_user')",
        "SELECT dbms_xmlgen.getxml('select * from auth_user') FROM dual",
        "SELECT utl_http.request('http://x') FROM dual",
        "SELECT * FROM url('http://x', CSV)",
        "SELECT * FROM remote('h', db, t)",
        "SELECT * FROM identifier('auth_user')",
        "SELECT * FROM \"dblink\"('a', 'b') t",
        "SELECT pg_catalog.pg_read_file ('/x')",
        "SELECT * FROM t WHERE a = query_to_xml ('select 1', true, false, '') IS NULL",
    ],
)
def test_sql_executing_and_file_reading_functions_are_denied(sql: str) -> None:
    _invalid(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t",
        "SELECT table_name FROM t",
        "SELECT t.table_name, t.table FROM t",
        "SELECT 'TABLE auth_user' AS note FROM t",
        "SELECT * FROM table1",
        "SELECT * FROM table1 JOIN table2 ON table1.id = table2.id",
        "SELECT * FROM t1 STRAIGHT_JOIN t2 ON t1.a = t2.a",
        "SELECT * FROM t1 NATURAL JOIN t2",
        "SELECT * FROM t1 JOIN t2 USING (id)",
        "SELECT * FROM t1, t2, t3 WHERE t1.a = t2.a",
        "SELECT * FROM (TABLE orders) o",
        "WITH x AS (TABLE orders) SELECT * FROM x",
        "SELECT * FROM t, LATERAL (SELECT 1) s",
        "SELECT 'dblink(' AS note FROM t",
        "SELECT 'query_to_xml(''select 1'')' AS note FROM t",
        "SELECT a AS file, b AS url FROM t",
        "SELECT COUNT(*), MAX(a), COALESCE(b, 0) FROM t GROUP BY c",
        "SELECT extract(year FROM d) FROM t",
        "SELECT * FROM auth_user_stats",  # different table, only a prefix match
        "SELECT a.user_profile FROM t a",  # column, not the restricted USER_PROFILE table
    ],
)
def test_legitimate_queries_stay_valid(sql: str) -> None:
    res = validate_sql_ast(sql)
    assert res["valid"] is True, f"{sql!r}: {res['violations']}"


def test_custom_restricted_tables_use_the_same_extraction() -> None:
    res = validate_sql_ast(
        "SELECT * FROM (TABLE secrets) s", restricted_tables={"SECRETS"}
    )
    assert res["valid"] is False
    assert validate_sql_ast(
        "SELECT * FROM (TABLE auth_user) s", restricted_tables={"X"}
    )["valid"]
