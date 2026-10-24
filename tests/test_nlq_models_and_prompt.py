"""
Tests for NLQ models, schema serialization, and prompt construction.
"""

from __future__ import annotations

from query_builder.models import QuerySpec
from query_builder.nlq.models import (
    NlqError,
    NlqExplainResult,
    NlqProviderError,
    NlqResult,
    NlqTranslateRequest,
    NlqValidationError,
)
from query_builder.nlq.prompt import (
    build_explain_prompt,
    build_system_prompt,
    build_user_prompt,
    get_few_shot_exemplars,
    serialize_schema_for_prompt,
)


def test_nlq_error_hierarchy() -> None:
    base = NlqError("base error")
    assert isinstance(base, Exception)

    val_err = NlqValidationError("validation error")
    assert isinstance(val_err, NlqError)

    prov_err = NlqProviderError("provider error")
    assert isinstance(prov_err, NlqError)


def test_nlq_result_and_explain_result_to_dict() -> None:
    qs = QuerySpec(table="users", columns=["id", "name"])
    res = NlqResult(
        spec={"table": "users", "columns": ["id", "name"]},
        query_spec=qs,
        confidence=0.95,
        explanation="Selects id and name from users.",
        provider="mock",
        model="mock-v1",
        tokens_used=120,
        warnings=["table schema was inferred"],
    )
    d = res.to_dict()
    assert d["spec"]["table"] == "users"
    assert d["confidence"] == 0.95
    assert d["provider"] == "mock"
    assert d["tokens_used"] == 120
    assert d["warnings"] == ["table schema was inferred"]

    explain_res = NlqExplainResult(
        summary="User query",
        explanation="Detailed description",
        steps=["Step 1", "Step 2"],
        provider="mock",
    )
    ed = explain_res.to_dict()
    assert ed["summary"] == "User query"
    assert ed["steps"] == ["Step 1", "Step 2"]
    assert ed["provider"] == "mock"


def test_nlq_translate_request_defaults() -> None:
    req = NlqTranslateRequest(prompt="Show all users")
    assert req.prompt == "Show all users"
    assert req.provider == "mock"
    assert req.dialect == "postgres"
    assert req.schema is None
    assert req.temperature == 0.0
    assert req.max_tokens == 1024


def test_serialize_schema_for_prompt() -> None:
    # 1. None schema
    assert "No explicit schema provided" in serialize_schema_for_prompt(None)

    # 2. Empty schema
    assert "No explicit schema provided" in serialize_schema_for_prompt({})

    # 3. Rich schema with dict columns, list columns, and foreign keys
    schema = {
        "tables": {
            "users": {
                "columns": {
                    "id": {"data_type": "INTEGER", "primary_key": True},
                    "email": {"data_type": "VARCHAR"},
                    "score": "FLOAT",
                },
                "foreign_keys": [],
            },
            "orders": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True},
                    {"name": "user_id", "type": "INTEGER"},
                    "created_at",
                ],
                "foreign_keys": [
                    {
                        "column": "user_id",
                        "target_table": "users",
                        "target_column": "id",
                    }
                ],
            },
            "invalid_table": "not_a_dict",
        }
    }
    serialized = serialize_schema_for_prompt(schema)
    assert "Table `users`:" in serialized
    assert "id: INTEGER (PK)" in serialized
    assert "score: FLOAT" in serialized
    assert "Table `orders`:" in serialized
    assert "user_id -> users.id" in serialized
    assert "created_at" in serialized

    # 4. Edge cases: non-dict tables, non-dict/list columns, non-dict fks, empty cols
    edge_schema = {
        "tables": {
            "empty_tbl": {
                "columns": {},
                "foreign_keys": ["not_a_dict", {"column": ""}],
            },
            "bad_col_types": {
                "columns": [123],
                "foreign_keys": "not_a_list",
            },
            "string_cols": {
                "columns": "invalid_columns",
            },
        }
    }
    edge_serialized = serialize_schema_for_prompt(edge_schema)
    assert "no columns listed" in edge_serialized
    assert "Table `bad_col_types`:" in edge_serialized

    # 5. tables as string
    assert "Database Schema:" in serialize_schema_for_prompt({"tables": "not_a_dict"})


def test_prompt_builders_and_exemplars() -> None:
    exemplars = get_few_shot_exemplars()
    assert len(exemplars) >= 3
    for ex in exemplars:
        assert "prompt" in ex
        assert "spec" in ex

    sys_p = build_system_prompt("Schema text", dialect="duckdb")
    assert "Target SQL Dialect: duckdb" in sys_p
    assert "Schema text" in sys_p
    assert "FEW-SHOT EXAMPLES" in sys_p

    user_p = build_user_prompt("Find all active products")
    assert (
        'Translate this request into QuerySpec JSON:\n"Find all active products"'
        == user_p
    )

    explain_p = build_explain_prompt({"table": "orders", "limit": 10}, dialect="sqlite")
    assert "Target Dialect: sqlite" in explain_p
    assert '"table": "orders"' in explain_p


def test_multishot_prompt_and_mock_refinement() -> None:
    from query_builder.nlq.service import NlqService

    current_spec = {
        "table": "users",
        "columns": ["id", "email"],
        "joins": [],
        "filters": [],
        "filter_join": "AND",
        "order_by": [],
        "limit": 50,
        "distinct": False,
    }
    history = [
        {
            "prompt": "Show users",
            "spec": current_spec,
            "explanation": "Selects users.",
        }
    ]
    multi_p = build_user_prompt(
        "Only active users limit 10",
        current_spec=current_spec,
        history=history,
    )
    assert "CONVERSATION HISTORY" in multi_p
    assert "CURRENT ACTIVE QUERYSPEC ON CANVAS" in multi_p
    assert '"Only active users limit 10"' in multi_p

    service = NlqService()
    res = service.translate(
        NlqTranslateRequest(
            prompt="where status = active sorted by email descending limit 10",
            provider="mock",
            current_spec=current_spec,
            history=history,
        )
    )
    assert res.spec["table"] == "users"
    assert res.spec["limit"] == 10
    assert any(f.get("column") == "status" for f in res.spec.get("filters", []))
    assert len(res.follow_ups) > 0
    assert "follow_ups" in res.to_dict()


def test_nlq_prompt_compact_fks_and_validator_alias_resolution() -> None:
    from unittest.mock import MagicMock, patch

    from query_builder.compiler import QueryCompiler
    from query_builder.nlq.providers import GeminiProvider, MockNlqProvider
    from query_builder.nlq.service import NlqService
    from query_builder.nlq.validator import NlqAstValidator

    # 1. Top-level foreign_keys + >90 tables compact mode (both dict and list column formats)
    many_tables: dict[str, dict[str, object]] = {}
    for idx in range(95):
        if idx % 2 == 0:
            many_tables[f"tbl_{idx}"] = {
                "columns": {f"c_{c}": {"data_type": "INT"} for c in range(15)}
            }
        else:
            many_tables[f"tbl_{idx}"] = {
                "columns": [{"name": f"c_{c}", "type": "INT"} for c in range(15)]
            }
    big_schema = {
        "tables": many_tables,
        "foreign_keys": [
            {
                "table": "tbl_0",
                "column": "c_1",
                "foreign_table": "tbl_1",
                "foreign_column": "c_0",
            },
            "not_a_dict",
        ],
    }
    prompt_str = serialize_schema_for_prompt(big_schema)
    assert "c_1 -> tbl_1.c_0" in prompt_str
    assert "..." in prompt_str

    # 2. build_user_prompt history edge branches (non-dict turn, missing explanation/spec, empty current_spec)
    up_hist_only = build_user_prompt(
        "Filter rows",
        current_spec={},
        history=["not_a_dict", {"content": "hello"}],  # type: ignore[list-item]
    )
    assert "Turn 2 User: 'hello'" in up_hist_only

    # 3. MockNlqProvider current_spec preservation of joins, filters, order_by, limit
    mock_prov = MockNlqProvider()
    ast_out, _ = mock_prov.generate_ast(
        "also filter age > 21",
        schema={"tables": {"users": {"columns": {"id": "INT", "age": "INT"}}}},
        current_spec={
            "table": "users",
            "columns": ["id"],
            "joins": [{"table": "orders", "left_col": "id", "right_col": "user_id"}],
            "filters": [{"column": "status", "op": "=", "value": "active"}],
            "order_by": [{"column": "id", "direction": "DESC"}],
            "limit": 25,
        },
    )
    assert ast_out["table"] == "users"
    assert ast_out["columns"] == ["id"]
    assert len(ast_out["joins"]) == 1
    assert len(ast_out["filters"]) == 2
    assert ast_out["order_by"] == [{"column": "id", "direction": "DESC"}]
    assert ast_out["limit"] == 25

    # 4. GeminiProvider 2.5 thinkingConfig branch
    gem = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
    with patch.object(
        gem,
        "_execute_http",
        return_value=('{"table": "users", "columns": ["id"]}', 10),
    ) as mock_http:
        gem.generate_ast("show users")
        assert mock_http.call_args[0][1]["generationConfig"]["thinkingConfig"] == {
            "thinkingBudget": 0
        }
    with patch.object(
        gem,
        "_execute_http",
        return_value=('{"summary": "s", "explanation": "e", "steps": []}', 5),
    ) as mock_exp:
        gem.explain_query({"table": "users"})
        assert mock_exp.call_args[0][1]["generationConfig"]["thinkingConfig"] == {
            "thinkingBudget": 0
        }

    # 5. NlqService inline explanation branch
    svc = NlqService()
    fake_prov = MagicMock()
    fake_prov.model = "custom-v1"
    fake_prov.generate_ast.return_value = (
        {
            "table": "users",
            "columns": ["id"],
            "explanation": "Inline explanation text",
            "follow_ups": ["Next prompt 1"],
        },
        15,
    )
    with patch("query_builder.nlq.service.get_nlq_provider", return_value=fake_prov):
        res_inline = svc.translate({"prompt": "show users", "provider": "mock"})
        assert res_inline.explanation == "Inline explanation text"
        assert res_inline.follow_ups == ["Next prompt 1"]

    # 6. NlqAstValidator _resolve_column and having alias resolution
    val_schema = {
        "tables": {
            "engine_hobby_progression": {
                "columns": {"id": {"type": "INT"}, "title": {"type": "TEXT"}}
            },
            "engine_work_session": {
                "columns": {
                    "id": {"type": "INT"},
                    "hobby_id": {"type": "INT"},
                    "minutes_spent": {"type": "INT"},
                }
            },
        }
    }
    validator = NlqAstValidator(schema=val_schema)
    validated, _ = validator.validate(
        {
            "table": "engine_hobby_progression",
            "joins": [
                {
                    "table": "engine_work_session",
                    "type": "LEFT JOIN",
                    "left_table": "engine_hobby_progression",
                    "left_col": "engine_hobby_progression.id",
                    "right_col": "engine_work_session.hobby_id",
                }
            ],
            "columns": [
                "hp.title",
                "engine_hobby_progression.id",
                "minutes_spent",
                {"column": "ws.id", "agg": "COUNT", "distinct": True, "alias": "cnt"},
                {"expression": "1 + 1", "alias": "two", "tablePrefix": "hp"},
            ],
            "filters": [
                {
                    "column": "x.minutes_spent",
                    "op": ">",
                    "value": 10,
                    "tablePrefix": "ws",
                    "combiner": "OR",
                }
            ],
            "having": [
                {"column": "cnt", "op": ">", "value": 1},
                {"column": "*", "agg": "COUNT_DISTINCT", "op": ">", "value": 0},
            ],
            "order_by": [{"column": "work.minutes_spent", "direction": "DESC"}],
            "rollup": True,
        }
    )
    assert "engine_hobby_progression.title" in validated["columns"]
    assert "engine_work_session.minutes_spent" in validated["columns"]
    assert validated["having"][0]["agg"] == "count_distinct"
    assert validated["having"][1]["agg"] == "count_distinct"

    # Single candidate fallback in _resolve_column
    assert (
        validator._resolve_column(
            "engine_hobby_progression",
            "unknown_alias.unknown_col",
            ["engine_hobby_progression"],
        )
        == "unknown_col"
    )
    assert (
        validator._resolve_column(
            "unlisted_tbl",
            "unlisted_tbl.col1",
            ["unlisted_tbl"],
        )
        == "unlisted_tbl.col1"
    )

    # 7. QueryCompiler having alias resolution
    comp = QueryCompiler(
        {
            "table": "engine_hobby_progression",
            "columns": [
                "title",
                {"column": "id", "agg": "COUNT", "alias": "total_items"},
            ],
            "having": [{"column": "total_items", "op": "gt", "value": 2}],
        },
        schema=val_schema,
        dialect="sqlite",
    )
    sql_str, _ = comp.compile()[0:2]
    assert "HAVING COUNT(" in sql_str


def test_fastapi_nlq_routes_and_sqlite_introspection_edges(tmp_path) -> None:
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from query_builder.connectors.introspection import introspect_sqlite
    from query_builder.connectors.sqlite import SQLiteConnector
    from query_builder.integrations.fastapi import create_query_builder_router
    from query_builder.nlq.service import NlqService

    db_file = tmp_path / "test_nlq_routes.sqlite"
    import sqlite3

    with sqlite3.connect(db_file) as raw_conn:
        raw_conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        raw_conn.commit()

    conn = SQLiteConnector(database=str(db_file))
    app = FastAPI()
    app.include_router(
        create_query_builder_router(connector=conn, nlq_service=NlqService())
    )
    client = TestClient(app)

    # 1. POST /nlq with nlq_service
    r_nlq = client.post(
        "/nlq",
        json={
            "prompt": "show users",
            "current_spec": {"table": "users", "columns": ["id"]},
            "history": [{"prompt": "hi"}],
        },
    )
    assert r_nlq.status_code == 200
    assert r_nlq.json()["spec"]["table"] == "users"
    assert len(r_nlq.json()["follow_ups"]) > 0

    # 2. Ungrounded table fallback in POST /nlq
    bad_nlq_svc = MagicMock()
    bad_nlq_svc.default_provider = "mock"
    bad_nlq_svc.translate.return_value = {
        "spec": {"table": "nonexistent_table", "columns": ["bad_col"]},
        "explanation": "Fallback test",
        "confidence": 0.5,
        "warnings": [],
    }
    app2 = FastAPI()
    app2.include_router(
        create_query_builder_router(connector=conn, nlq_service=bad_nlq_svc)
    )
    client2 = TestClient(app2)
    r_fb = client2.post("/nlq/translate", json={"prompt": "show nonexistent"})
    assert r_fb.status_code == 200
    assert r_fb.json()["spec"]["table"] == "users"
    assert any("Mapped ungrounded table" in w for w in r_fb.json()["warnings"])

    # 3. POST /nlq/explain (valid, missing spec -> 400, dict return, error -> 400)
    r_exp = client.post(
        "/nlq/explain", json={"spec": {"table": "users", "columns": ["id"]}}
    )
    assert r_exp.status_code == 200
    assert "explanation" in r_exp.json()

    r_exp_missing = client.post("/nlq/explain", json={})
    assert r_exp_missing.status_code == 400

    bad_nlq_svc.explain.return_value = {"summary": "dict return", "explanation": "ok"}
    r_exp_dict = client2.post("/nlq/explain", json={"spec": {"table": "users"}})
    assert r_exp_dict.status_code == 200
    assert r_exp_dict.json()["summary"] == "dict return"

    bad_nlq_svc.explain.return_value = 12345
    assert client2.post("/nlq/explain", json={"spec": {"table": "users"}}).json() == {}

    bad_nlq_svc.explain.side_effect = RuntimeError("explain failure")
    assert (
        client2.post("/nlq/explain", json={"spec": {"table": "users"}}).status_code
        == 400
    )

    # 4. GET /nlq/providers
    r_prov = client.get("/nlq/providers")
    assert r_prov.status_code == 200
    assert "providers" in r_prov.json()

    # 5. introspect_sqlite virtual table tokenizer/module skip & re-raise
    fake_cursor = MagicMock()
    fake_cursor.fetchall.side_effect = [
        [("fts_tbl",), ("good_tbl",)],
        [(0, "id", "INTEGER", 1, None, 1)],
    ]

    def fake_exec(sql: str) -> None:
        if 'table_info("fts_tbl")' in sql:
            raise sqlite3.OperationalError("unknown tokenizer: custom_tok")
        if 'foreign_key_list("good_tbl")' in sql:
            raise sqlite3.OperationalError("no such module: fts5")

    fake_cursor.execute.side_effect = fake_exec
    snap = introspect_sqlite(fake_cursor)
    assert "good_tbl" in snap["tables"]
    assert "fts_tbl" not in snap["tables"]

    # Non-virtual table error in table_info and foreign_key_list re-raises
    import pytest

    from query_builder.connectors.base import ConnectionFailedError, IntrospectionError

    err_cursor1 = MagicMock()
    err_cursor1.fetchall.return_value = [("broken_tbl",)]
    err_cursor1.execute.side_effect = [
        None,
        sqlite3.OperationalError("disk I/O error"),
    ]
    with pytest.raises(IntrospectionError):
        introspect_sqlite(err_cursor1)

    err_cursor2 = MagicMock()
    err_cursor2.fetchall.side_effect = [
        [("broken_fk_tbl",)],
        [(0, "id", "INTEGER", 1, None, 1)],
    ]
    err_cursor2.execute.side_effect = [
        None,
        None,
        sqlite3.OperationalError("database disk image is malformed"),
    ]
    with pytest.raises(IntrospectionError):
        introspect_sqlite(err_cursor2)

    # 6. SQLiteConnector WAL read-only fallback and non-ro OperationalError
    from unittest.mock import patch

    ro_conn = SQLiteConnector(database=str(db_file))
    real_connect = sqlite3.connect
    calls = 0

    class _FailingFirstConn:
        def __init__(self, inner: sqlite3.Connection) -> None:
            self._inner = inner

        def execute(self, sql: str) -> sqlite3.Cursor:
            if "SELECT 1 FROM sqlite_master" in sql:
                raise sqlite3.OperationalError("unable to open database file")
            return self._inner.execute(sql)

        def close(self) -> None:
            self._inner.close()

    def flaky_ro_connect(target: str, **kw: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _FailingFirstConn(real_connect(str(db_file)))
        return real_connect(str(db_file))

    with patch("sqlite3.connect", side_effect=flaky_ro_connect):
        c_handle = ro_conn.connect()
        assert c_handle is not None
        ro_conn.close()

    mem_conn = SQLiteConnector(database=":memory:")
    with (
        patch(
            "sqlite3.connect",
            side_effect=sqlite3.OperationalError("out of memory"),
        ),
        pytest.raises(ConnectionFailedError),
    ):
        mem_conn.connect()
