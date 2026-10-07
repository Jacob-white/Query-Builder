"""
Tests for Query-Builder Model Context Protocol (MCP) Server.
"""

import io
import json

import pytest

from query_builder.mcp_server import MCP_PROTOCOL_VERSION, McpServer


class TestMcpServer:
    def test_initialize(self):
        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }
        resp = server.handle_request(req)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "query-builder"

    def test_ping(self):
        server = McpServer()
        req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        resp = server.handle_request(req)
        assert resp["id"] == 2
        assert resp["result"] == {}

    def test_tools_list(self):
        server = McpServer()
        req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
        resp = server.handle_request(req)
        tools = resp["result"]["tools"]
        assert len(tools) == 7
        tool_names = [t["name"] for t in tools]
        assert "query_builder_compile" in tool_names
        assert "query_builder_validate" in tool_names
        assert "query_builder_explain_and_advise" in tool_names
        assert "query_builder_get_complexity" in tool_names
        assert "query_builder_introspect" in tool_names
        assert "query_builder_execute" in tool_names
        assert "query_builder_join_path" in tool_names

    def test_tools_call_compile(self):
        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "query_builder_compile",
                "arguments": {
                    "spec": {
                        "table": "users",
                        "columns": ["id", "username"],
                        "limit": 5,
                    },
                    "dialect": "postgres",
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 4
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert 'FROM "users"' in content["sql"]
        assert content["params"] == [5, 0]

    def test_tools_call_validate(self):
        server = McpServer()
        # Safe query
        req_safe = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "query_builder_validate",
                "arguments": {"sql": "SELECT id, name FROM users WHERE active = 1;"},
            },
        }
        resp_safe = server.handle_request(req_safe)
        content_safe = json.loads(resp_safe["result"]["content"][0]["text"])
        assert content_safe["valid"] is True
        assert content_safe["is_read_only"] is True

        # Mutation query
        req_bad = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "query_builder_validate",
                "arguments": {"sql": "DROP TABLE users;"},
            },
        }
        resp_bad = server.handle_request(req_bad)
        content_bad = json.loads(resp_bad["result"]["content"][0]["text"])
        assert content_bad["valid"] is False
        assert content_bad["is_read_only"] is False

    def test_tools_call_explain_and_advise(self):
        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "query_builder_explain_and_advise",
                "arguments": {
                    "spec": {
                        "table": "orders",
                        "columns": ["id", "total"],
                        "filters": [{"column": "status", "op": "eq", "value": "paid"}],
                    }
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 7
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "plan" in content
        assert "performance" in content
        assert "recommended_indexes" in content

    def test_tools_call_get_complexity(self):
        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "query_builder_get_complexity",
                "arguments": {
                    "spec": {"table": "logs", "columns": ["id", "msg"]}
                },
            },
        }
        resp = server.handle_request(req)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["complexity_score"] >= 2
        assert content["is_safe"] is True

    def test_tools_call_introspect(self, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test_mcp.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);")
        conn.close()

        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "query_builder_introspect",
                "arguments": {
                    "connector": "sqlite",
                    "config": {"database": db_path},
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 10
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "tables" in content
        assert "products" in content["tables"]
        assert len(content["tables"]["products"]["columns"]) == 3

    def test_tools_call_execute_sql(self, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test_exec.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (id, name) VALUES (1, 'Alice');")
        conn.commit()
        conn.close()

        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "query_builder_execute",
                "arguments": {
                    "sql": "SELECT id, name FROM users WHERE id = 1;",
                    "connector": "sqlite",
                    "config": {"database": db_path},
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 11
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert len(content["rows"]) == 1
        assert content["rows"][0]["name"] == "Alice"

    def test_tools_call_execute_spec(self, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test_exec_spec.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT);")
        conn.execute("INSERT INTO items (id, title) VALUES (1, 'Book');")
        conn.commit()
        conn.close()

        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "query_builder_execute",
                "arguments": {
                    "spec": {
                        "table": "items",
                        "columns": ["id", "title"],
                        "limit": 5,
                    },
                    "connector": "sqlite",
                    "config": {"database": db_path},
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 12
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["count"] == 1
        assert content["rows"][0]["title"] == "Book"

    def test_tools_call_execute_mutation_blocked(self, tmp_path):
        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "query_builder_execute",
                "arguments": {
                    "sql": "DROP TABLE users;",
                    "connector": "sqlite",
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 13
        assert resp["result"]["isError"] is True
        assert "Security violation" in resp["result"]["content"][0]["text"]

    def test_tools_call_join_path(self):
        server = McpServer()
        schema = {
            "tables": {
                "users": {"columns": [{"name": "id"}]},
                "orders": {"columns": [{"name": "id"}, {"name": "user_id"}]},
            },
            "foreign_keys": [
                {
                    "table": "orders",
                    "column": "user_id",
                    "foreign_table": "users",
                    "foreign_column": "id",
                }
            ],
        }
        req = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "query_builder_join_path",
                "arguments": {
                    "active_tables": ["users"],
                    "target_table": "orders",
                    "schema": schema,
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 14
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "path" in content
        assert len(content["path"]) == 1
        assert content["path"][0]["table"] == "orders"

    def test_unknown_method(self):
        server = McpServer()
        req = {"jsonrpc": "2.0", "id": 99, "method": "unknown/route"}
        resp = server.handle_request(req)
        assert resp["error"]["code"] == -32601

    def test_run_stdio_stream(self):
        input_lines = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}) + "\n"
        )
        stdin = io.StringIO(input_lines)
        stdout = io.StringIO()

        server = McpServer(stdin=stdin, stdout=stdout)
        server.run_stdio()

        output_str = stdout.getvalue()
        lines = [json.loads(l) for l in output_str.strip().split("\n")]
        assert len(lines) == 2
        assert lines[0]["id"] == 1
        assert lines[1]["id"] == 2
        assert lines[1]["result"]["serverInfo"]["name"] == "query-builder"

    def test_invalid_request_not_dict(self):
        server = McpServer()
        resp = server.handle_request([1, 2, 3])  # type: ignore[arg-type]
        assert resp["error"]["code"] == -32600

    def test_tools_call_validate_spec(self):
        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "query_builder_validate",
                "arguments": {
                    "spec": {"table": "users", "columns": ["id", "email"]},
                    "dialect": "sqlite",
                },
            },
        }
        resp = server.handle_request(req)
        assert resp["id"] == 15
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["valid"] is True

    def test_tools_call_stringified_arguments(self, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test_str_args.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE metrics (id INTEGER PRIMARY KEY, score REAL);")
        conn.execute("INSERT INTO metrics VALUES (1, 95.5);")
        conn.commit()
        conn.close()

        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {
                "name": "query_builder_execute",
                "arguments": {
                    "spec": json.dumps({"table": "metrics", "columns": ["id", "score"]}),
                    "connector": "sqlite",
                    "config": json.dumps({"database": db_path}),
                },
            },
        }
        resp = server.handle_request(req)
        assert not resp["result"]["isError"]
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["count"] == 1

    @pytest.mark.anyio
    async def test_async_event_loop_safety(self, tmp_path):
        import sqlite3

        db_path = str(tmp_path / "test_async_safe.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INT);")
        conn.close()

        server = McpServer()
        req = {
            "jsonrpc": "2.0",
            "id": 17,
            "method": "tools/call",
            "params": {
                "name": "query_builder_introspect",
                "arguments": {
                    "connector": "sqlite",
                    "config": {"database": db_path},
                },
            },
        }
        # Run inside active event loop
        resp = server.handle_request(req)
        assert not resp["result"]["isError"]

