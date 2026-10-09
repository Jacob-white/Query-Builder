import sqlite3

import pytest

from query_builder.ast_validator import validate_sql_ast
from query_builder.compiler import (
    CompilationError,
    QueryCompiler,
    validate_query_spec,
)
from query_builder.dialects import (
    BaseDialect,
    DialectError,
    MSSQLDialect,
    MySQLDialect,
    get_dialect,
)
from query_builder.executor import execute_compiled_spec, execute_cursor_query
from query_builder.join_solver import (
    _clean_table_name,
    find_best_join_condition,
    find_join_path,
)
from query_builder.security import (
    AliasCounter,
    SecurityError,
    _build_chain_exists,
    resolve_ownership_predicate,
)


def test_ast_validator_hardened_security_and_dos():
    # 1. Max SQL length limit
    huge_sql = "SELECT " + ("a" * 100_001)
    res_len = validate_sql_ast(huge_sql, max_sql_length=1000)
    assert not res_len["valid"]
    assert "exceeds maximum allowed length" in res_len["violations"][0]
    assert res_len["injection_risk"] == "HIGH"

    # 2. Null byte detection
    res_null = validate_sql_ast("SELECT 1\x00; DROP TABLE users;")
    assert not res_null["valid"]
    assert "Null byte detected" in res_null["violations"][0]
    assert res_null["injection_risk"] == "CRITICAL"

    # 3. Obfuscated separator (e.g. fullwidth semicolon \uff1b)
    res_sep = validate_sql_ast("SELECT 1\uff1bDROP TABLE users;")
    assert not res_sep["valid"]
    assert any("Obfuscated statement separator" in v for v in res_sep["violations"])
    assert res_sep["injection_risk"] == "CRITICAL"

    # 4. Disallowed control character (e.g. \x07 bell or \x1b escape)
    res_ctrl = validate_sql_ast("SELECT 1 \x07 FROM users")
    assert not res_ctrl["valid"]
    assert any("Disallowed control character" in v for v in res_ctrl["violations"])

    # 5. Forbidden executable comment syntax (/*!... */)
    res_comm = validate_sql_ast("SELECT 1 /*!50000 , (SELECT * FROM users) */")
    assert not res_comm["valid"]
    assert any("executable comment syntax" in v for v in res_comm["violations"])
    assert res_comm["injection_risk"] == "CRITICAL"

    # 6. Recursive CTE blocked by default
    res_rec = validate_sql_ast(
        "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x<5) SELECT * FROM cnt;"
    )
    assert not res_rec["valid"]
    assert any("WITH RECURSIVE" in v for v in res_rec["violations"])

    # 7. Allowed recursive CTE when explicitly enabled
    res_rec_ok = validate_sql_ast(
        "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x<5) SELECT * FROM cnt;",
        allow_recursive_cte=True,
    )
    assert res_rec_ok["valid"]

    # 8. Token complexity threshold
    res_tokens = validate_sql_ast("SELECT 1 + 2 + 3", max_ast_tokens=2)
    assert not res_tokens["valid"]
    assert any("safety threshold" in v for v in res_tokens["violations"])

    # 9. Dialect injection patterns (LOAD_FILE, OUTFILE, XP_CMDSHELL, etc.)
    assert not validate_sql_ast("SELECT LOAD_FILE('/etc/passwd')")["valid"]
    assert not validate_sql_ast("SELECT * INTO OUTFILE '/tmp/dump.txt' FROM users")[
        "valid"
    ]
    assert not validate_sql_ast(
        "SELECT * FROM users WHERE id = 1 WAITFOR DELAY '0:0:5'"
    )["valid"]
    assert not validate_sql_ast("SELECT xp_cmdshell('whoami')")["valid"]
    assert not validate_sql_ast("SELECT pg_sleep(10)")["valid"]
    assert not validate_sql_ast("SELECT sqlite_master.name FROM sqlite_master")["valid"]

    # 10. Parse exception safety guard
    # Mocking sqlparse to raise an unexpected parse error
    from unittest import mock

    with mock.patch("sqlparse.parse", side_effect=ValueError("Simulated parser crash")):
        res_crash = validate_sql_ast("SELECT 1")
        assert not res_crash["valid"]
        assert "Malformed SQL failed AST parsing" in res_crash["violations"][0]


def test_dialects_hardened_validation():
    dialect = BaseDialect()

    # Identifier validation - part length > 128
    long_part = "a" * 129
    with pytest.raises(DialectError) as exc1:
        dialect.quote_identifier(long_part)
    assert "exceeds maximum allowed length" in str(exc1.value)

    # Alias validation - non-string
    with pytest.raises(DialectError) as exc2:
        dialect.quote_alias(12345)  # type: ignore
    assert "Alias must be a string" in str(exc2.value)

    # Alias validation - length > 256
    with pytest.raises(DialectError) as exc3:
        dialect.quote_alias("a" * 257)
    assert "exceeds maximum limit" in str(exc3.value)

    # Alias validation - control char / null byte
    with pytest.raises(DialectError) as exc4:
        dialect.quote_alias("test\x00alias")
    assert "forbidden control characters" in str(exc4.value)

    with pytest.raises(DialectError) as exc4b:
        dialect.quote_alias("test\x07alias")
    assert "forbidden control characters" in str(exc4b.value)

    # MSSQL and MySQL alias & ident validation
    mssql = MSSQLDialect()
    with pytest.raises(DialectError):
        mssql.quote_identifier(long_part)
    with pytest.raises(DialectError):
        mssql.quote_alias("bad\x00alias")
    with pytest.raises(DialectError):
        mssql.quote_alias(123)  # type: ignore
    with pytest.raises(DialectError):
        mssql.quote_alias("x" * 257)

    mysql = MySQLDialect()
    with pytest.raises(DialectError):
        mysql.quote_identifier(long_part)
    with pytest.raises(DialectError):
        mysql.quote_alias("bad\x00alias")
    with pytest.raises(DialectError):
        mysql.quote_alias(123)  # type: ignore
    with pytest.raises(DialectError):
        mysql.quote_alias("x" * 257)


def test_security_hardened_invariants():
    dialect = get_dialect("postgres")

    # Fail closed on null user_id
    with pytest.raises(SecurityError) as exc1:
        resolve_ownership_predicate(dialect, {}, "t1", "users", None, [])
    assert "requires a valid, non-null user_id" in str(exc1.value)

    # Fail closed on invalid table or alias
    with pytest.raises(SecurityError):
        resolve_ownership_predicate(dialect, {}, "t1", "", 1, [])
    with pytest.raises(SecurityError):
        resolve_ownership_predicate(dialect, {}, "", "users", 1, [])

    # Empty chain in _build_chain_exists
    counter = AliasCounter()
    with pytest.raises(SecurityError) as exc2:
        _build_chain_exists(dialect, {}, "t1", [], 1, [], counter)
    assert "Ownership chain cannot be empty" in str(exc2.value)

    # Max depth exceeded in _build_chain_exists
    chain_hop = ("user_id", "users", "id")
    with pytest.raises(SecurityError) as exc3:
        _build_chain_exists(
            dialect, {}, "t1", [chain_hop], 1, [], counter, current_depth=10
        )
    assert "depth exceeded maximum allowed limit" in str(exc3.value)

    # Invalid hop format
    with pytest.raises(SecurityError):
        _build_chain_exists(dialect, {}, "t1", ["not_a_tuple"], 1, [], counter)  # type: ignore

    # Invalid hop fields
    with pytest.raises(SecurityError):
        _build_chain_exists(dialect, {}, "t1", [("", "users", "id")], 1, [], counter)
    with pytest.raises(SecurityError):
        _build_chain_exists(dialect, {}, "t1", [("user_id", "", "id")], 1, [], counter)
    with pytest.raises(SecurityError):
        _build_chain_exists(
            dialect, {}, "t1", [("user_id", "users", "")], 1, [], counter
        )

    # Cyclic ownership chain
    cyclic_chain = [
        ("account_id", "accounts", "id"),
        ("user_id", "accounts", "id"),  # repeats 'accounts'
    ]
    with pytest.raises(SecurityError) as exc4:
        resolve_ownership_predicate(
            dialect,
            {"items": {}, "accounts": {}},
            "t1",
            "items",
            1,
            [],
            ownership_paths={"items": [cyclic_chain]},
        )
    assert "Cyclic ownership path detected" in str(exc4.value)


def test_join_solver_hardened_invariants():
    # 1. _clean_table_name with non-string / None
    assert _clean_table_name(None) == ""
    assert _clean_table_name(123) == ""
    assert _clean_table_name("") == ""

    # 2. find_best_join_condition with empty/invalid inputs
    fallback = find_best_join_condition("", "orders")
    assert fallback["left_table"] == "t1"
    assert fallback["is_fk"] is False

    fallback2 = find_best_join_condition("users", "")
    assert fallback2["right_table"] == "t2"

    # 3. find_best_join_condition with malformed schema_data
    cond_malformed = find_best_join_condition(
        "users",
        "orders",
        schema_data={"tables": "not_a_dict", "foreign_keys": "not_a_list"},  # type: ignore
    )
    assert cond_malformed["left_table"] == "users"

    # 4. foreign key list contains non-dict item
    cond_fk_bad = find_best_join_condition(
        "users",
        "orders",
        schema_data={"tables": {}, "foreign_keys": ["not_a_dict"]},  # type: ignore
    )
    assert cond_fk_bad["is_fk"] is False

    # 5. find_join_path invalid target or active_tables
    assert find_join_path([], "") == []
    assert find_join_path("not_a_list", "orders") == []  # type: ignore
    assert find_join_path(["users"], "") == []

    # 6. find_join_path exceeds MAX_ACTIVE_TABLES
    active_overflow = [f"tbl_{i}" for i in range(60)]
    path = find_join_path(active_overflow, "target_tbl", schema_data={})
    assert len(path) == 1  # Falls back to direct join from first active

    # 7. find_join_path exceeds MAX_FOREIGN_KEYS
    many_fks = [{"table": f"t_{i}", "foreign_table": f"t_{i + 1}"} for i in range(5005)]
    path_fks = find_join_path(["t_0"], "t_2", schema_data={"foreign_keys": many_fks})
    assert len(path_fks) == 2

    # 8. find_join_path with malformed tables_meta or non-dict FK
    bad_schema = {
        "tables": "invalid",
        "foreign_keys": [None, {"table": "a", "foreign_table": "b"}],
    }
    path_bad = find_join_path(["a"], "b", schema_data=bad_schema)  # type: ignore
    assert len(path_bad) == 1

    # 9. find_join_path with MAX_JOIN_DEPTH enforcement
    # Build a deep linear chain: a -> b -> c -> ... -> l (11 hops)
    deep_fks = [
        {
            "table": chr(ord("a") + i + 1),
            "column": "fk",
            "foreign_table": chr(ord("a") + i),
            "foreign_column": "id",
        }
        for i in range(12)
    ]
    path_deep = find_join_path(
        ["a"], chr(ord("a") + 12), schema_data={"foreign_keys": deep_fks}
    )
    # Cannot reach in 10 hops, falls back to direct join
    assert len(path_deep) == 1


def test_compiler_untrusted_spec_validation():
    # 1. Non-dict spec
    with pytest.raises(CompilationError) as exc1:
        validate_query_spec(["not", "a", "dict"])  # type: ignore
    assert "Query spec must be a dictionary" in str(exc1.value)

    # 2. Unexpected top-level key
    with pytest.raises(CompilationError) as exc2:
        validate_query_spec({"table": "users", "evil_key": "val"})
    assert "Unexpected field(s) in query specification: evil_key" in str(exc2.value)

    # Allow unknown keys when flag set
    validate_query_spec({"table": "users", "evil_key": "val"}, allow_unknown_keys=True)

    # 3. Invalid table name / type
    with pytest.raises(CompilationError):
        validate_query_spec({"table": ""})
    with pytest.raises(CompilationError):
        validate_query_spec({"table": 1234})  # type: ignore
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users; DROP TABLE users;"})

    # 4. Columns validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "columns": "not_a_list"})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "columns": [f"col_{i}" for i in range(101)]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "columns": ["valid_col", "bad;col"]})

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "columns": [12345]})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "columns": [{"column": "name", "unknown_key": 1}]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "columns": [{"column": "bad;col"}]})

    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "columns": [{"column": "name", "agg": "unsupported_agg"}],
            }
        )

    # 5. Joins validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "joins": "not_a_list"})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": f"t_{i}"} for i in range(21)]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "joins": ["not_a_dict"]})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "joins": [{"table": "orders", "unexpected_join_field": 1}],
            }
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "joins": [{"table": ""}]})

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "joins": [{"table": "orders;DROP"}]})

    # 6. Filters validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "filters": "not_a_list"})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "filters": [{"column": f"c_{i}"} for i in range(51)]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "filters": ["not_a_dict"]})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "filters": [{"column": "id", "unexpected_flt": 1}]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "filters": [{"column": "bad;col"}]})

    # 7. Having validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "having": "not_a_list"})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "having": [{"column": f"c_{i}"} for i in range(21)]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "having": ["not_a_dict"]})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "having": [{"column": "id", "unexpected_hvg": 1}]}
        )

    # 8. Order by validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "order_by": "not_a_list"})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "order_by": [{"column": f"c_{i}"} for i in range(21)]}
        )

    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "order_by": ["not_a_dict"]})  # type: ignore

    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "order_by": [{"column": "id", "unexpected_ord": 1}]}
        )

    # 9. Limit, offset, distinct validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "limit": -1})
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "limit": "invalid"})
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "offset": -1})
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "offset": "invalid"})
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "distinct": "not_a_bool"})  # type: ignore

    # 10. IN filter values limit in QueryCompiler.compile()
    oversized_in = {
        "table": "users",
        "filters": [
            {"column": "id", "op": "in", "value": [f"val_{i}" for i in range(1001)]}
        ],
    }
    with pytest.raises(CompilationError) as exc_in:
        QueryCompiler(oversized_in).compile()
    assert "exceeds maximum limit of 1000" in str(exc_in.value)

    # 11. Column reference resolver validation
    compiler = QueryCompiler({"table": "users"})
    with pytest.raises(CompilationError):
        compiler._resolve_column_ref("", "users")
    with pytest.raises(CompilationError):
        compiler._resolve_column_ref("bad;col", "users")
    with pytest.raises(CompilationError):
        compiler._resolve_column_ref("bad;tbl.col", "users")
    with pytest.raises(CompilationError):
        compiler._get_alias("")
    with pytest.raises(CompilationError):
        compiler._get_alias("bad;table")


def test_executor_hardened_validation():
    # 1. Cursor is None
    with pytest.raises(ValueError) as exc1:
        execute_cursor_query(None, "SELECT 1")
    assert "cannot be None" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        execute_compiled_spec(None, {"table": "users"})
    assert "cannot be None" in str(exc2.value)

    # 2. Spec is invalid type
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    with pytest.raises(CompilationError) as exc3:
        execute_compiled_spec(cur, "not_a_dict")  # type: ignore
    assert "Specification must be a dictionary" in str(exc3.value)

    # 3. statement_timeout_ms <= 0
    with pytest.raises(ValueError) as exc4:
        execute_compiled_spec(cur, {"table": "users"}, statement_timeout_ms=0)
    assert "statement_timeout_ms must be positive" in str(exc4.value)


def test_compiler_and_join_edge_branches():
    # Compiler compile without table when validation bypassed
    compiler = QueryCompiler({"table": None}, validate_spec=False)
    with pytest.raises(CompilationError) as exc:
        compiler.compile()
    assert "Missing required 'table' parameter" in str(exc.value)

    # Join solver with non-list foreign_keys and non-dict table meta in find_join_path
    schema_weird = {
        "tables": {"orphan": "not_a_dict"},
        "foreign_keys": "not_a_list",
    }
    path = find_join_path(["a"], "b", schema_data=schema_weird)  # type: ignore
    assert len(path) == 1


def test_deep_security_audit_ast_validator():
    # 1. CTE with non-SELECT root operations
    res_do = validate_sql_ast("WITH t AS (SELECT 1) DO $$ BEGIN NULL; END $$;")
    assert not res_do["valid"]
    assert "Restricted statement type: DO" in res_do["violations"][0]

    res_merge = validate_sql_ast(
        "WITH t AS (SELECT 1) MERGE INTO target USING source ON (a = b) WHEN MATCHED THEN DELETE;"
    )
    assert not res_merge["valid"]
    assert any(
        "MERGE" in v or "Restricted statement type" in v
        for v in res_merge["violations"]
    )

    res_cte_del = validate_sql_ast("WITH t AS (SELECT 1) DELETE FROM users;")
    assert not res_cte_del["valid"]
    assert any("DELETE" in v for v in res_cte_del["violations"])

    # 2. Valid CTE with parenthesized SELECT root
    res_cte_paren = validate_sql_ast("WITH t AS (SELECT 1) (SELECT * FROM t);")
    assert res_cte_paren["valid"]
    assert res_cte_paren["statement_type"] == "SELECT"

    # 3. Multiple CTE definitions followed by valid SELECT
    res_multi_cte = validate_sql_ast(
        "WITH t1 AS (SELECT 1), t2 AS (SELECT 2) SELECT * FROM t1, t2;"
    )
    assert res_multi_cte["valid"]

    # 4. Top-level parenthesized SELECT and non-SELECT
    res_paren_sel = validate_sql_ast("((SELECT 1))")
    assert res_paren_sel["valid"]
    assert res_paren_sel["statement_type"] == "SELECT"

    res_paren_del = validate_sql_ast("((DELETE FROM users))")
    assert not res_paren_del["valid"]
    assert any("DELETE" in v for v in res_paren_del["violations"])

    # 5. Schema quoting and whitespace evasions
    assert not validate_sql_ast('SELECT * FROM "pg_catalog"."pg_class"')["valid"]
    assert not validate_sql_ast("SELECT * FROM [sys].[objects]")["valid"]
    assert not validate_sql_ast("SELECT * FROM `mysql`.`user`")["valid"]
    assert not validate_sql_ast("SELECT * FROM pg_catalog . pg_class")["valid"]
    assert not validate_sql_ast("SELECT * FROM snowflake.account_usage.users")["valid"]

    # 6. Allowed schemas parameter
    res_allowed = validate_sql_ast(
        'SELECT * FROM "pg_catalog"."analytics_data"', allowed_schemas=["pg_catalog"]
    )
    assert res_allowed["valid"]

    # 7. Qualified sensitive tables
    assert not validate_sql_ast("SELECT * FROM mysql.user")["valid"]
    assert not validate_sql_ast("SELECT * FROM sys.objects")["valid"]
    assert not validate_sql_ast("SELECT * FROM public.auth_user")["valid"]

    # 8. CALL, REPLACE INTO, and WAITFOR with comments
    assert not validate_sql_ast("CALL my_stored_proc()")["valid"]
    assert not validate_sql_ast("REPLACE INTO users (id) VALUES (1)")["valid"]
    assert not validate_sql_ast("SELECT 1 WAITFOR/**/DELAY '0:0:5'")["valid"]


def test_deep_input_validation_query_spec():
    # 1. Table validation
    with pytest.raises(CompilationError) as exc:
        validate_query_spec({"table": 123})  # type: ignore
    assert "must be a non-empty string" in str(exc.value)

    with pytest.raises(CompilationError) as exc:
        validate_query_spec({"table": "a" * 129})
    assert "part exceeds maximum allowed length" in str(exc.value)

    with pytest.raises(CompilationError) as exc:
        validate_query_spec({"table": "bad-schema.users"})
    assert "Invalid table identifier name" in str(exc.value)

    # 2. Column validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "columns": [{"column": 123}]})
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "columns": [{"column": "id", "alias": 123}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "columns": [{"column": "id", "alias": "a" * 257}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "columns": [{"column": "id", "alias": "bad\x00alias"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "columns": [{"column": "id", "table": "bad;tbl"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "columns": ["bad;col"]})

    # 3. Join validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "joins": [{"table": None}]})
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": "orders", "left_table": "bad;tbl"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": "orders", "left_col": "bad;col"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": "orders", "right_col": "bad;col"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": "orders", "on": "not_a_list"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": "orders", "on": [{}] * 11}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "joins": [{"table": "orders", "on": ["not_a_dict"]}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "joins": [
                    {"table": "orders", "on": [{"left": "bad;col", "right": "id"}]}
                ],
            }
        )

    # 4. Filter validation
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "filters": [{"column": "id", "tablePrefix": "bad;tbl"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "filters": [{"column": "id", "op": "unsupported_op"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "in", "value": list(range(1001))}],
            }
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "filters": [
                    {"column": "id", "op": "in", "value": ",".join(["1"] * 1001)}
                ],
            }
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "between", "value": [1, 2, 3]}],
            }
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "between", "value": "no_delimiter"}],
            }
        )
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "filter_join": 123})  # type: ignore

    # 5. Having and Order by validation
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "having": [{"column": "bad;col"}]})
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "having": [{"column": "id", "agg": "bad_agg"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "having": [{"column": "id", "op": "bad_op"}]}
        )
    with pytest.raises(CompilationError):
        validate_query_spec({"table": "users", "order_by": [{"column": "bad;col"}]})
    with pytest.raises(CompilationError):
        validate_query_spec(
            {"table": "users", "order_by": [{"column": "id", "tablePrefix": "bad;tbl"}]}
        )

    # 6. Limit and Offset bounds
    with pytest.raises(CompilationError) as exc_lim:
        validate_query_spec({"table": "users", "limit": 10001})
    assert "exceeds maximum allowed limit" in str(exc_lim.value)

    with pytest.raises(CompilationError) as exc_off:
        validate_query_spec({"table": "users", "offset": 1000001})
    assert "exceeds maximum allowed limit" in str(exc_off.value)


def test_tenant_isolation_fail_closed():
    schema = {
        "tables": {
            "public_docs": {
                "columns": [{"name": "id"}, {"name": "title"}],
            }
        }
    }
    # Spec targeting public_docs which does not have client_id or tenant_id
    compiler = QueryCompiler(
        {"table": "public_docs"}, schema=schema, tenant_id="tenant-123"
    )
    with pytest.raises(CompilationError) as exc:
        compiler.compile()
    assert "does not have a client_id or tenant_id column" in str(exc.value)


def test_security_module_hardened_boundaries():
    from query_builder.dialects import BaseDialect

    dialect = BaseDialect()
    ctr = AliasCounter()

    # 1. Invalid hop identifiers
    with pytest.raises(SecurityError) as exc1:
        _build_chain_exists(
            dialect, {}, "t1", [("bad;col", "orders", "id")], "u1", [], ctr
        )
    assert "Invalid foreign key column identifier" in str(exc1.value)

    with pytest.raises(SecurityError) as exc2:
        _build_chain_exists(dialect, {}, "t1", [("fk", "bad;tbl", "id")], "u1", [], ctr)
    assert "Invalid target table identifier" in str(exc2.value)

    with pytest.raises(SecurityError) as exc3:
        _build_chain_exists(
            dialect, {}, "t1", [("fk", "orders", "bad;pk")], "u1", [], ctr
        )
    assert "Invalid target PK column identifier" in str(exc3.value)

    with pytest.raises(SecurityError) as exc4:
        _build_chain_exists(
            dialect, {}, "bad;alias", [("fk", "orders", "id")], "u1", [], ctr
        )
    assert "Invalid alias in ownership chain" in str(exc4.value)

    with pytest.raises(SecurityError) as exc5:
        _build_chain_exists(dialect, {}, "t1", [("fk", "a" * 129, "id")], "u1", [], ctr)
    assert "exceeds maximum allowed length" in str(exc5.value)

    # 2. Invalid user_col in single hop
    meta_bad_col = {"orders": {"user_col": "bad;col"}}
    with pytest.raises(SecurityError) as exc6:
        _build_chain_exists(
            dialect, meta_bad_col, "t1", [("fk", "orders", "id")], "u1", [], ctr
        )
    assert "Invalid user column identifier" in str(exc6.value)

    # 3. Direct table ownership with invalid user_col
    meta_direct_bad = {"users": {"has_user_id": True, "user_col": "bad;col"}}
    with pytest.raises(SecurityError) as exc7:
        resolve_ownership_predicate(dialect, meta_direct_bad, "t1", "users", "u1", [])
    assert "Invalid user column identifier" in str(exc7.value)

    # 4. Immediate self-cycle detection
    paths = {"orders": [[("order_id", "orders", "id")]]}
    with pytest.raises(SecurityError) as exc8:
        resolve_ownership_predicate(
            dialect, {}, "t1", "orders", "u1", [], ownership_paths=paths
        )
    assert "Cyclic ownership path detected" in str(exc8.value)

    # 5. Invalid table or alias in resolve_ownership_predicate
    with pytest.raises(SecurityError):
        resolve_ownership_predicate(dialect, {}, "bad;alias", "users", "u1", [])
    with pytest.raises(SecurityError):
        resolve_ownership_predicate(dialect, {}, "t1", "bad;table", "u1", [])


def test_executor_and_join_solver_edge_hardening():
    # 1. execute_cursor_query with empty SQL
    with pytest.raises(ValueError) as exc:
        execute_cursor_query("fake_cursor", "")
    assert "SQL query must be a non-empty string" in str(exc.value)

    # 2. execute_compiled_spec with AST validation failure on count_sql
    from unittest import mock

    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE test_data (id INT);")

    # Mock validate_sql_ast to fail only when validating count_sql
    real_val = validate_sql_ast

    def mock_val(sql, **kwargs):
        if "COUNT(*)" in sql:
            return {"valid": False, "message": "Simulated count AST injection"}
        return real_val(sql, **kwargs)

    with mock.patch("query_builder.executor.validate_sql_ast", side_effect=mock_val):
        with pytest.raises(CompilationError) as exc_ast:
            execute_compiled_spec(cur, {"table": "test_data"})
        assert "Generated count query failed AST safety validation" in str(
            exc_ast.value
        )

    # 3. Join solver default_join_type validation fallback
    res = find_join_path(["users"], "orders", default_join_type="INVALID_TYPE")
    assert res[0]["type"] == "LEFT JOIN"

    res_inner = find_join_path(["users"], "orders", default_join_type="INNER")
    assert res_inner[0]["type"] == "INNER JOIN"


def test_full_coverage_gap_closure():
    from query_builder.cli import main

    # 1. AST validator CTE punctuation, unclosed CTE, and parenthesis branches
    res_punct = validate_sql_ast(
        "WITH t AS (SELECT 1) , SELECT 1"
    )  # malformed: the AST layer fails closed
    assert not res_punct["valid"]

    res_no_root = validate_sql_ast("WITH t AS (SELECT 1)")
    assert not res_no_root["valid"]

    res_rec = validate_sql_ast(
        "WITH RECURSIVE t AS (SELECT 1) SELECT * FROM t", allow_recursive_cte=True
    )
    assert res_rec["valid"]

    res_empty_p = validate_sql_ast("(( /* empty */ ))")
    assert not res_empty_p["valid"]

    res_num_p = validate_sql_ast("((123))")
    assert not res_num_p["valid"]

    # 2. Spec validation branches
    validate_query_spec({"table": "users", "having": [{"column": None}]})
    validate_query_spec(
        {"table": "users", "columns": None, "joins": None, "filters": None}
    )
    validate_query_spec({"table": "users", "columns": [{"column": None}]})
    validate_query_spec(
        {"table": "users", "having": [{"column": "id", "extra": 1}]},
        allow_unknown_keys=True,
    )
    validate_query_spec(
        {"table": "users", "order_by": [{"column": "id", "extra": 1}]},
        allow_unknown_keys=True,
    )

    # 3. Compiler branches
    # Tenant ID without schema metadata dictionary
    comp_tenant = QueryCompiler({"table": "users"}, tenant_id="t1")
    sql, params, _, _ = comp_tenant.compile()
    assert '"tenant_id" = %s' in sql
    assert params[0] == "t1"

    # Missing target table in join with validation bypassed
    with pytest.raises(CompilationError) as exc_j:
        QueryCompiler(
            {"table": "users", "joins": [{"table": ""}]}, validate_spec=False
        ).compile()
    assert "Missing join target" in str(exc_j.value)

    # Filter with IN values exceeding max limit
    with pytest.raises(CompilationError) as exc_in:
        QueryCompiler(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "in", "value": list(range(1001))}],
            },
            validate_spec=False,
        ).compile()
    assert "exceeds maximum limit" in str(exc_in.value)

    # Filter with invalid BETWEEN value
    with pytest.raises(CompilationError) as exc_bt:
        QueryCompiler(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "between", "value": [1]}],
            },
            validate_spec=False,
        ).compile()
    assert "requires exactly 2 bounds" in str(exc_bt.value)

    # Filter with invalid op
    with pytest.raises(CompilationError) as exc_op:
        QueryCompiler(
            {
                "table": "users",
                "filters": [{"column": "id", "op": "bad_op", "value": 1}],
            },
            validate_spec=False,
        ).compile()
    assert "Unsupported filter operator" in str(exc_op.value)

    # Projection with empty dict
    comp_proj = QueryCompiler({"table": "users", "columns": [{}]}, validate_spec=False)
    sql_proj, _, _, _ = comp_proj.compile()
    assert "FROM" in sql_proj

    # Having with invalid agg/op ignored when bypassing spec validation
    comp_hvg = QueryCompiler(
        {
            "table": "users",
            "having": [{"column": "id", "agg": "bad", "op": "bad", "value": 1}],
        },
        validate_spec=False,
    )
    sql_hvg, _, _, _ = comp_hvg.compile()
    assert "HAVING" not in sql_hvg

    # Aggregation with group by but without having
    comp_agg = QueryCompiler(
        {"table": "users", "columns": ["name", {"column": "id", "agg": "count"}]}
    )
    _, _, count_sql, _ = comp_agg.compile()
    assert "count_subquery" in count_sql

    # Relationship traversal where relationship does not match join table
    schema_custom = {
        "tables": {
            "users": {"columns": ["id"]},
            "orders": {"columns": ["id", "user_id"]},
            "logs": {"columns": ["id"]},
        },
        "relationships": [
            {
                "source_table": "logs",
                "target_table": "users",
                "source_column": "id",
                "target_column": "id",
            }
        ],
        "foreign_keys": [
            {
                "table": "orders",
                "column": "user_id",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ],
    }
    comp_rel = QueryCompiler(
        {"table": "users", "joins": [{"table": "orders"}]},
        schema=schema_custom,
    )
    sql_rel, _, _, _ = comp_rel.compile()
    assert '"user_id"' in sql_rel

    # 4. Join solver edge branches
    # Empty table in foreign_key
    res_fk = find_join_path(
        ["users"],
        "orders",
        schema_data={"foreign_keys": [{"table": "", "foreign_table": "orders"}]},
    )
    assert len(res_fk) >= 1

    # Canonical column without base entity in tables_meta
    res_canon = find_join_path(
        ["users"],
        "orders",
        schema_data={"tables": {"users": {"columns": ["nonexistent_id"]}}},
    )
    assert len(res_canon) >= 1

    # 5. CLI branches
    assert main(["join-path", "--active", "users", "--target", "orders"]) == 0
