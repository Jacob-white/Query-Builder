"""``query-builder schema --audit``: the schema audit from the command line.

Exit status is 1 when an id column names a table but has no declared link (the gap that breaks joins), so it can gate a
build. Descriptions that are missing are reported but do not fail the run: they are a content gap, not a broken join.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from query_builder.cli import main

GAPS = {
    "tables": {
        "orders": {
            "comment": "An order.",
            "columns": [
                {"name": "id", "comment": "Key"},
                {"name": "customer_id", "comment": "Who"},
            ],
        },
        "customers": {
            "comment": "A customer.",
            "columns": [{"name": "id", "comment": "Key"}],
        },
    }
}
LINKED = {
    **GAPS,
    "foreign_keys": [
        {
            "table": "orders",
            "column": "customer_id",
            "foreign_table": "customers",
            "foreign_column": "id",
        }
    ],
}
UNDESCRIBED = {"tables": {"orders": {"columns": [{"name": "id"}]}}}


@pytest.fixture
def schema_file(tmp_path: Path):
    def write(data: dict) -> str:
        path = tmp_path / "schema.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    return write


def test_a_missing_link_is_reported_and_fails_the_run(schema_file, capsys) -> None:
    code = main(["schema", "--schema", schema_file(GAPS), "--audit"])
    out = capsys.readouterr().out
    assert code == 1
    assert "orders.customer_id" in out and "customers" in out


def test_a_schema_with_its_links_declared_passes(schema_file, capsys) -> None:
    code = main(["schema", "--schema", schema_file(LINKED), "--audit"])
    assert code == 0
    assert "0 id columns" in capsys.readouterr().out


def test_missing_descriptions_are_reported_but_do_not_fail(schema_file, capsys) -> None:
    code = main(["schema", "--schema", schema_file(UNDESCRIBED), "--audit"])
    out = capsys.readouterr().out
    assert code == 0
    assert (
        "1 of 1 tables have no description" in out
        and "1 of 1 columns have no description" in out
    )


def test_json_output_is_the_report_as_data(schema_file, capsys) -> None:
    code = main(["schema", "--schema", schema_file(GAPS), "--audit", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    assert data["success"] is True
    assert data["audit"]["missing_links"] == [
        {"table": "orders", "column": "customer_id", "target": "customers"}
    ]
    assert data["audit"]["clean"] is False


def test_the_options_for_what_to_ignore_are_accepted(schema_file, capsys) -> None:
    code = main(
        [
            "schema",
            "--schema",
            schema_file(GAPS),
            "--audit",
            "--known-not-link",
            "orders.customer_id",
        ]
    )
    assert code == 0 and "orders.customer_id" not in capsys.readouterr().out
    code = main(
        [
            "schema",
            "--schema",
            schema_file(GAPS),
            "--audit",
            "--ignore-table-prefix",
            "ord",
        ]
    )
    assert code == 0


def test_a_malformed_known_not_link_is_an_error_not_a_crash(
    schema_file, capsys
) -> None:
    code = main(
        [
            "schema",
            "--schema",
            schema_file(GAPS),
            "--audit",
            "--known-not-link",
            "no_dot_here",
            "--json",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["success"] is False


def test_an_unreadable_schema_is_an_error_in_both_modes(tmp_path: Path, capsys) -> None:
    missing = str(tmp_path / "nope.json")
    assert main(["schema", "--schema", missing, "--audit"]) == 1
    assert "Schema Explorer error" in capsys.readouterr().err
    assert main(["schema", "--schema", missing, "--audit", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["success"] is False


def test_without_the_flag_the_schema_command_is_unchanged(schema_file, capsys) -> None:
    code = main(["schema", "--schema", schema_file(GAPS), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and "audit" not in data
