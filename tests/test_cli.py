import json

from query_builder.cli import main


def test_cli_validate_valid(capsys):
    ret = main(
        ["validate", "--json", "SELECT legal_name FROM production.firm_master LIMIT 5;"]
    )
    assert ret == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["valid"] is True
    assert res["statement_type"] == "SELECT"


def test_cli_validate_mutation_blocked(capsys):
    ret = main(["validate", "--json", "DELETE FROM production.firm_master;"])
    assert ret == 1
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["valid"] is False
    assert res["injection_risk"] == "CRITICAL"


def test_cli_compile(capsys, tmp_path):
    spec = {
        "table": "users",
        "columns": ["users.id", "users.email"],
        "limit": 5,
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))

    ret = main(["compile", "--spec", str(spec_file), "--dialect", "postgres"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "--- Main SQL ---" in captured.out
    assert 'FROM "users" "t1"' in captured.out


def test_cli_compile_inline_json_with_schema(capsys, tmp_path):
    schema = {"tables": {"users": {"columns": [{"name": "id"}]}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    inline_spec = '{"table": "users", "columns": ["users.id"]}'
    ret = main(["compile", "--spec", inline_spec, "--schema", str(schema_file)])
    assert ret == 0
    captured = capsys.readouterr()
    assert 'FROM "users" "t1"' in captured.out


def test_cli_compile_error_returns_one(capsys, tmp_path):
    schema = {"tables": {"users": {"columns": [{"name": "id"}]}}}
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    inline_spec = '{"table": "nonexistent"}'
    ret = main(["compile", "--spec", inline_spec, "--schema", str(schema_file)])
    assert ret == 1
    captured = capsys.readouterr()
    assert "Compilation error" in captured.err


def test_cli_join_path(capsys, tmp_path):
    schema = {
        "tables": {
            "a": {"columns": [{"name": "id"}]},
            "b": {"columns": [{"name": "id"}, {"name": "a_id"}]},
        },
        "foreign_keys": [
            {
                "table": "b",
                "column": "a_id",
                "foreign_table": "a",
                "foreign_column": "id",
            }
        ],
    }
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps(schema))

    ret = main(
        ["join-path", "--active", "a", "--target", "b", "--schema", str(schema_file)]
    )
    assert ret == 0
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert len(res) == 1
    assert res[0]["table"] == "b"


def test_cli_serve_argument_parsing(capsys):
    from unittest.mock import MagicMock, patch

    mock_server = MagicMock()
    mock_server.server_address = ("127.0.0.1", 9000)
    mock_server.serve_forever.side_effect = None

    with patch(
        "query_builder.server.create_server", return_value=mock_server
    ) as mock_create:
        ret = main(["serve", "--host", "0.0.0.0", "--port", "9000"])
        assert ret == 0
        mock_create.assert_called_once_with(host="0.0.0.0", port=9000)
        mock_server.serve_forever.assert_called_once()
        captured = capsys.readouterr()
        assert "Query Builder server listening" in captured.out


def test_cli_serve_keyboard_interrupt(capsys):
    from unittest.mock import MagicMock, patch

    mock_server = MagicMock()
    mock_server.server_address = ("127.0.0.1", 8000)
    mock_server.serve_forever.side_effect = KeyboardInterrupt

    with patch("query_builder.server.create_server", return_value=mock_server):
        ret = main(["serve"])
        assert ret == 0
        mock_server.server_close.assert_called_once()
        captured = capsys.readouterr()
        assert "Shutting down server..." in captured.out
