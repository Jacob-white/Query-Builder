from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

from query_builder.cli import main
from query_builder.compiler import QueryCompiler
from query_builder.dialects import BaseDialect
from query_builder.exceptions import SecurityError
from query_builder.join_solver import find_best_join_condition
from query_builder.server import QueryBuilderHandler


def test_cli_vector_and_schema_explorer_edge_cases(tmp_path, capsys):
    # 1. CLI with vector as JSON string array and top_k
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        json.dumps({"table": "items", "columns": ["id"]}), encoding="utf-8"
    )

    code = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--vector",
            "[0.1, 0.2, 0.3]",
            "--top-k",
            "15",
            "--dialect",
            "sqlite",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "SELECT" in out

    # 1b. CLI with vector without top-k
    code = main(
        [
            "compile",
            "--spec",
            str(spec_file),
            "--vector",
            "[0.1, 0.2, 0.3]",
            "--dialect",
            "sqlite",
        ]
    )
    assert code == 0
    capsys.readouterr()

    # 2. CLI with top_k when vector_search already in spec_data
    spec_file_vs = tmp_path / "spec_vs.json"
    spec_file_vs.write_text(
        json.dumps(
            {"table": "items", "vector_search": {"vector": [0.5, 0.6], "top_k": 3}}
        ),
        encoding="utf-8",
    )
    code = main(
        ["compile", "--spec", str(spec_file_vs), "--top-k", "20", "--dialect", "sqlite"]
    )
    assert code == 0
    capsys.readouterr()

    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({"tables": {}}), encoding="utf-8")

    # 3. Schema explorer: table not found with --json
    code = main(
        ["schema", "--schema", str(schema_file), "--table", "nonexistent", "--json"]
    )
    assert code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["success"] is False
    assert "not found" in data["error"]

    # 4. Schema explorer: detailed table view with comments, outgoing FKs, and incoming FKs
    mock_exploration = {
        "table_count": 2,
        "column_count": 4,
        "foreign_key_count": 2,
        "hubs": ["orders"],
        "user_isolated_count": 1,
        "tables": {
            "orders": {
                "name": "orders",
                "has_user_id": True,
                "comment": "Orders table description",
                "column_count": 3,
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    },
                    {
                        "name": "user_id",
                        "data_type": "int",
                        "is_primary": False,
                        "is_nullable": False,
                    },
                    {
                        "name": "total",
                        "data_type": "float",
                        "is_primary": False,
                        "is_nullable": True,
                    },
                ],
                "outgoing_fks": [
                    {
                        "column": "user_id",
                        "foreign_table": "users",
                        "foreign_column": "id",
                    }
                ],
                "incoming_fks": [
                    {
                        "table": "order_items",
                        "column": "order_id",
                        "foreign_column": "id",
                    }
                ],
            },
            "users": {
                "name": "users",
                "has_user_id": False,
                "comment": None,
                "column_count": 1,
                "columns": [
                    {
                        "name": "id",
                        "data_type": "int",
                        "is_primary": True,
                        "is_nullable": False,
                    }
                ],
                "outgoing_fks": [],
                "incoming_fks": [],
            },
        },
    }

    with patch("query_builder.schema.explore_schema", return_value=mock_exploration):
        # Human-readable table inspection for orders (with comment and FKs)
        code = main(["schema", "--schema", str(schema_file), "--table", "orders"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Table: orders [user-isolated]" in out
        assert "Comment: Orders table description" in out
        assert "Outgoing Foreign Keys:" in out
        assert "Incoming References:" in out

        # Human-readable table inspection for users (without comment and without FKs)
        code = main(["schema", "--schema", str(schema_file), "--table", "users"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Table: users" in out
        assert "Comment:" not in out
        assert "Outgoing Foreign Keys:" not in out

        # Human-readable schema overview with hubs and user_isolated_count
        code = main(["schema", "--schema", str(schema_file)])
        assert code == 0
        out = capsys.readouterr().out
        assert "Hub Tables: orders" in out
        assert "User-Isolated Tables: 1" in out

    # 4b. Schema overview without hubs and without user_isolated_count
    mock_exploration_simple = {
        "table_count": 1,
        "column_count": 1,
        "foreign_key_count": 0,
        "tables": {
            "simple": {
                "name": "simple",
                "has_user_id": False,
                "comment": None,
                "column_count": 1,
                "columns": [],
                "outgoing_fks": [],
                "incoming_fks": [],
            }
        },
    }
    with patch(
        "query_builder.schema.explore_schema", return_value=mock_exploration_simple
    ):
        code = main(["schema", "--schema", str(schema_file)])
        assert code == 0
        out = capsys.readouterr().out
        assert "Schema Overview: 1 tables" in out
        assert "Hub Tables:" not in out
        assert "User-Isolated Tables:" not in out

    # 5. Schema explorer exception handling
    with patch(
        "query_builder.schema.explore_schema",
        side_effect=RuntimeError("Introspection crash"),
    ):
        code = main(["schema", "--schema", str(schema_file), "--json"])
        assert code == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["success"] is False
        assert "Introspection crash" in data["error"]

        code = main(["schema", "--schema", str(schema_file)])
        assert code == 1
        err = capsys.readouterr().err
        assert "Schema Explorer error: Introspection crash" in err


def test_server_streaming_and_explain_edge_cases():
    def make_handler(body_dict: dict, path: str = "/api/v1/stream"):
        handler = QueryBuilderHandler.__new__(QueryBuilderHandler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(json.dumps(body_dict)))}
        handler.rfile = io.BytesIO(json.dumps(body_dict).encode("utf-8"))
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    # 1. Streaming: batch_size <= 0 and missing both spec and sql
    h_bad_req = make_handler({"batch_size": -5})
    h_bad_req.do_POST()
    assert "BAD_REQUEST" in h_bad_req.wfile.getvalue().decode("utf-8")

    # 2. Streaming with raw sql instead of spec
    h_raw_sql = make_handler({"sql": "SELECT 1 AS num", "connector": "sqlite"})
    h_raw_sql.do_POST()
    assert h_raw_sql.send_response.called
    response_body = h_raw_sql.wfile.getvalue().decode("utf-8")
    assert "event: meta" in response_body
    assert "event: done" in response_body

    # 3. Streaming with tenant_id and policy
    h_tenant = make_handler(
        {
            "spec": {"table": "items", "columns": ["id"]},
            "tenant_id": "tenant_abc",
            "policy": {"tenant_column": "tenant_id", "strict_mode": False},
            "connector": "sqlite",
        }
    )
    h_tenant.do_POST()
    assert h_tenant.send_response.called

    # 4. Streaming SecurityError -> 403
    with patch(
        "query_builder.server.get_connector",
        side_effect=SecurityError("Blocked by security"),
    ):
        h_sec = make_handler({"spec": {"table": "items"}, "connector": "sqlite"})
        h_sec.do_POST()
        assert "FORBIDDEN" in h_sec.wfile.getvalue().decode("utf-8")

    # 5. Streaming general Exception -> 400
    with patch(
        "query_builder.server.get_connector", side_effect=RuntimeError("Connector down")
    ):
        h_err = make_handler({"spec": {"table": "items"}, "connector": "sqlite"})
        h_err.do_POST()
        assert "STREAM_ERROR" in h_err.wfile.getvalue().decode("utf-8")

    # 6. Explain with raw_explain
    h_exp_raw = make_handler(
        {"raw_explain": [{"id": 1, "detail": "SCAN TABLE items"}], "dialect": "sqlite"},
        path="/api/v1/explain",
    )
    h_exp_raw.do_POST()
    assert h_exp_raw.send_response.called

    # 7. Explain with raw sql (calling connector successfully)
    h_exp_sql = make_handler(
        {"sql": "SELECT 1 AS num", "connector": "sqlite"}, path="/api/v1/explain"
    )
    h_exp_sql.do_POST()
    assert h_exp_sql.send_response.called

    # 8. Explain with raw sql where connector fails (fallback to estimate_plan_from_spec)
    with patch("query_builder.server.get_connector", side_effect=RuntimeError("No DB")):
        h_exp_sql_fallback = make_handler(
            {"sql": "SELECT * FROM items", "connector": "sqlite"},
            path="/api/v1/explain",
        )
        h_exp_sql_fallback.do_POST()
        assert h_exp_sql_fallback.send_response.called

    # 9. Explain without spec, raw_explain, or sql -> 400
    h_exp_empty = make_handler({}, path="/api/v1/explain")
    h_exp_empty.do_POST()
    assert "BAD_REQUEST" in h_exp_empty.wfile.getvalue().decode("utf-8")

    # 10. Explain general exception -> 400
    with patch(
        "query_builder.server.estimate_plan_from_spec",
        side_effect=RuntimeError("Explain planner error"),
    ):
        h_exp_crash = make_handler({"spec": {"table": "items"}}, path="/api/v1/explain")
        h_exp_crash.do_POST()
        assert "EXPLAIN_ERROR" in h_exp_crash.wfile.getvalue().decode("utf-8")


def test_join_solver_fallback_meta_branches():
    # raw_left / raw_right not dict and not having to_dict
    schema = {
        "tables": {
            "users": 12345,
            "posts": "invalid_meta",
        },
        "foreign_keys": [],
    }
    res = find_best_join_condition("users", "posts", schema_data=schema)
    assert res["is_fk"] is False


def test_dialects_format_text_search_branches():
    d = BaseDialect()
    expr = d.format_text_search(["title", "description"])
    assert "CASE WHEN title LIKE" in expr
    assert "CASE WHEN description LIKE" in expr


def test_compiler_edge_branches():
    # 523->537: vector_search with allow_unknown_keys=True
    vs_spec = {
        "table": "items",
        "vector_search": {"vector": [0.1, 0.2], "some_custom_key": "val"},
    }
    c1 = QueryCompiler(vs_spec, allow_unknown_keys=True)
    sql1, params1, _, _ = c1.compile()
    assert "SELECT" in sql1

    # 577->595: hybrid_search with allow_unknown_keys=True
    hs_spec = {
        "table": "items",
        "hybrid_search": {
            "vector": [0.1, 0.2],
            "custom_meta": 123,
            "text_columns": [],  # covers 1257->1261 and 1608->1622 (empty text columns)
        },
    }
    c2 = QueryCompiler(hs_spec, allow_unknown_keys=True)
    sql2, params2, _, _ = c2.compile()
    assert "SELECT" in sql2

    # 1608->1622: hybrid_search with include_scores=False and text_columns=[]
    hs_spec_no_scores_empty = {
        "table": "items",
        "hybrid_search": {
            "vector": [0.1, 0.2],
            "text_columns": [],
            "include_scores": False,
        },
    }
    c_hs1 = QueryCompiler(hs_spec_no_scores_empty)
    sql_hs1, params_hs1, _, _ = c_hs1.compile()
    assert "ORDER BY" in sql_hs1

    # 1608->1609: hybrid_search with include_scores=False and text_columns=["title"]
    hs_spec_no_scores_text = {
        "table": "items",
        "hybrid_search": {
            "vector": [0.1, 0.2],
            "query_text": "laptop",
            "text_columns": ["title"],
            "include_scores": False,
        },
    }
    c_hs2 = QueryCompiler(hs_spec_no_scores_text)
    sql_hs2, params_hs2, _, _ = c_hs2.compile()
    assert "ORDER BY" in sql_hs2

    # Line 1630: search_spec_val is object with .vector but no .top_k
    class CustomVecWithoutTopK:
        vector = [0.1, 0.2]

    c3 = QueryCompiler(
        {"table": "items", "vector_search": CustomVecWithoutTopK()},
        allow_unknown_keys=True,
    )
    sql3, params3, _, _ = c3.compile()
    assert "SELECT" in sql3


def test_vector_connectors_param_fallback_branches():
    from query_builder.connectors.chroma import _ChromaCursorAdapter
    from query_builder.connectors.lancedb import _LanceDBCursorAdapter
    from query_builder.connectors.milvus import _MilvusCursorAdapter
    from query_builder.connectors.pinecone import _PineconeCursorAdapter
    from query_builder.connectors.qdrant import _QdrantCursorAdapter
    from query_builder.connectors.weaviate import _WeaviateCursorAdapter

    lance_tbl_mock = MagicMock()
    lance_tbl_mock.search.return_value.limit.return_value.to_arrow.return_value.schema = []
    lance_tbl_mock.search.return_value.limit.return_value.to_arrow.return_value.to_pylist.return_value = []
    lance_conn = MagicMock(spec=["open_table", "table_names"])
    lance_conn.open_table.return_value = lance_tbl_mock

    adapters = [
        _ChromaCursorAdapter(MagicMock(spec=["query"])),
        _LanceDBCursorAdapter(lance_conn),
        _MilvusCursorAdapter(MagicMock(spec=["search", "list_collections"])),
        _PineconeCursorAdapter(MagicMock(spec=["query", "list_indexes"])),
        _QdrantCursorAdapter(MagicMock(spec=["search", "get_collections"])),
        _WeaviateCursorAdapter(MagicMock(spec=["collections"])),
    ]

    for cur in adapters:
        # 1. Non-list non-str param
        cur.execute("SELECT * FROM items WHERE score > 0.5", [12345])
        assert hasattr(cur, "fetchall")

        # 2. Str param that parses to non-list JSON
        cur.execute(
            "SELECT * FROM items WHERE vector_search = 1", ['{"not": "a_list"}']
        )
        assert hasattr(cur, "fetchall")

        # 3. Str param with valid JSON list
        cur.execute(
            "SELECT * FROM items WHERE vector_search = 1 LIMIT 5", ["[0.1, 0.2]"]
        )
        assert hasattr(cur, "fetchall")

        # 4. Without FROM clause
        cur.execute("SELECT 1 WHERE score > 0.5 LIMIT 5", [[0.1, 0.2]])
        assert hasattr(cur, "fetchall")

        # 5. Without LIMIT clause
        cur.execute("SELECT * FROM items WHERE score > 0.5", [[0.1, 0.2]])
        assert hasattr(cur, "fetchall")

    # LanceDB specific string-param branches (71->76 and 74->76):
    cur_lance = _LanceDBCursorAdapter(lance_conn)
    cur_lance.execute("SELECT * FROM items WHERE distance = 1", ["not valid json"])
    cur_lance.execute("SELECT * FROM items WHERE distance = 1", ['{"not": "list"}'])

    # Pinecone specific branches (67->81, 77->79):
    pc_conn = MagicMock(spec=["query", "list_indexes"])
    pc_conn.query.return_value = {"matches": []}
    pc_cur = _PineconeCursorAdapter(pc_conn)
    # top_k in params[1]
    pc_cur.execute("SELECT * FROM items WHERE distance = 1", [[0.1, 0.2], 5])
    # invalid JSON string starting with [
    pc_cur.execute("SELECT * FROM items WHERE distance = 1", ["[not valid json"])
    # string not starting with [
    pc_cur.execute("SELECT * FROM items WHERE distance = 1", ["some_string"])
    # 67->81: params is None
    pc_cur.execute("SELECT * FROM items")
    # 77->79: json.loads returns non-list
    with patch("json.loads", return_value={"not": "list"}):
        pc_cur.execute("SELECT * FROM items WHERE distance = 1", ["[something]"])
