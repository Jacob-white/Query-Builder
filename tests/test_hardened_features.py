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
