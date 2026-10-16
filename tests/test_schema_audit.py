"""``audit_schema``: gaps in what a schema tells a query builder or an AI helper about the data.

A caller that joins only on declared links cannot follow an ``..._id`` column that has none, and a table or column with no
description is a guess about meaning. The audit lists those gaps from the schema alone (names, links and descriptions,
never row data), so they can be fixed before a user trips on them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from query_builder import SchemaAudit, SchemaSnapshot, audit_schema


def table(
    columns: list[tuple[str, str | None]],
    links: list[tuple[str, str]] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "columns": [{"name": n, "type": "TEXT", "description": d} for n, d in columns],
        "foreign_keys": [
            {"column": c, "foreign_table": t, "foreign_column": "id"}
            for c, t in links or []
        ],
    }


TABLES = {
    "orders": table(
        [
            ("id", "Primary key"),
            ("customer_id", None),
            ("region_id", None),
            ("note", None),
        ],
        links=[("region_id", "regions")],
        description="An order.",
    ),
    "customers": table([("id", None)]),
    "regions": table([("id", "Primary key")], description="A sales region."),
}


def test_an_id_column_with_no_link_whose_name_is_a_table_is_a_missing_link() -> None:
    report = audit_schema({"tables": TABLES})
    assert report.missing_links == [("orders", "customer_id", "customers")]


def test_a_linked_column_and_a_primary_key_are_not_reported() -> None:
    report = audit_schema({"tables": TABLES})
    assert ("orders", "region_id", "regions") not in report.missing_links
    assert all(column != "id" for _, column, _ in report.missing_links)


def test_the_name_may_carry_a_prefix_and_still_find_its_table() -> None:
    tables = {
        "orders": table([("id", None), ("parent_customer_id", None)]),
        "customers": table([("id", None)]),
    }
    assert audit_schema({"tables": tables}).missing_links == [
        ("orders", "parent_customer_id", "customers")
    ]


def test_an_id_column_that_names_no_table_is_listed_apart_not_as_a_missing_link() -> (
    None
):
    tables = {**TABLES, "orders": table([("id", None), ("mystery_id", None)])}
    report = audit_schema({"tables": tables})
    assert (
        report.missing_links == []
        and ("orders", "mystery_id") in report.unexplained_ids
    )


def test_a_column_that_points_at_its_own_table_is_not_a_missing_link() -> None:
    tables = {"orders": table([("id", None), ("orders_id", None)])}
    assert audit_schema({"tables": tables}).missing_links == []


def test_tables_and_columns_with_no_description_are_counted() -> None:
    report = audit_schema({"tables": TABLES})
    assert report.undescribed_tables == ["customers"]
    assert report.undescribed_columns["orders"] == 3  # customer_id, region_id, note
    assert "regions" not in report.undescribed_columns


def test_an_empty_description_counts_as_none() -> None:
    tables = {"orders": table([("id", "  ")], description="")}
    report = audit_schema({"tables": tables})
    assert report.undescribed_tables == ["orders"] and report.undescribed_columns == {
        "orders": 1
    }


# --- the parameters that keep a caller's own conventions out of the library -----------------------------------------------


def test_names_and_prefixes_that_are_not_expected_to_link_can_be_given() -> None:
    tables = {
        "orders": table(
            [
                ("id", None),
                ("legacy_customer_id", None),
                ("ext_customer_id", None),
                ("trace_id", None),
                ("customer_id", None),
            ]
        ),
        "customers": table([("id", None)]),
        "trace": table([("id", None)]),
    }
    plain = audit_schema({"tables": tables})
    assert {c for _, c, _ in plain.missing_links} == {
        "legacy_customer_id",
        "ext_customer_id",
        "customer_id",
    }  # trace_id is a built-in exception
    tuned = audit_schema({"tables": tables}, not_link_prefixes=("legacy_", "ext_"))
    assert [c for _, c, _ in tuned.missing_links] == ["customer_id"]


def test_a_known_non_link_is_left_out_and_everything_else_is_still_reported() -> None:
    tables = {
        "orders": table([("id", None), ("customer_id", None), ("region_id", None)]),
        "customers": table([("id", None)]),
        "regions": table([("id", None)]),
    }
    report = audit_schema(
        {"tables": tables}, known_not_links={("orders", "customer_id")}
    )
    assert report.missing_links == [("orders", "region_id", "regions")]


def test_tables_with_an_ignored_prefix_are_not_audited_at_all() -> None:
    tables = {
        "ext_notes": table([("id", None), ("customer_id", None)]),
        "customers": table([("id", None)]),
    }
    report = audit_schema({"tables": tables}, ignore_prefixes=("ext_",))
    assert report.missing_links == [] and "ext_notes" not in report.undescribed_tables


# --- the shapes a schema comes in ------------------------------------------------------------------------------------------


def test_the_snapshot_shape_with_top_level_foreign_keys_and_comments() -> None:
    schema = {
        "tables": {
            "orders": {
                "comment": "An order.",
                "columns": [
                    {"name": "id", "comment": "Key"},
                    {"name": "customer_id"},
                    {"name": "region_id", "comment": "Region"},
                ],
            },
            "customers": {"comment": None, "columns": [{"name": "id"}]},
            "regions": {
                "comment": "A region.",
                "columns": [{"name": "id", "comment": "Key"}],
            },
        },
        "foreign_keys": [
            {
                "table": "orders",
                "column": "region_id",
                "foreign_table": "regions",
                "foreign_column": "id",
            }
        ],
        "relationships": [
            {
                "source_table": "orders",
                "source_column": "customer_id",
                "target_table": "customers",
                "target_column": "id",
            }
        ],
    }
    report = audit_schema(schema)
    assert (
        report.missing_links == []
    )  # region_id by foreign key, customer_id by relationship
    assert report.undescribed_tables == [
        "customers"
    ] and report.undescribed_columns == {"orders": 1, "customers": 1}


def test_a_schema_snapshot_object_is_accepted() -> None:
    snapshot = SchemaSnapshot(
        tables={
            "orders": {"columns": [{"name": "id"}, {"name": "customer_id"}]},
            "customers": {"columns": [{"name": "id"}]},
        },
    )
    assert audit_schema(snapshot).missing_links == [
        ("orders", "customer_id", "customers")
    ]


def test_columns_may_be_plain_names() -> None:
    schema = {
        "tables": {
            "orders": {"columns": ["id", "customer_id"]},
            "customers": {"columns": ["id"]},
        }
    }
    assert audit_schema(schema).missing_links == [
        ("orders", "customer_id", "customers")
    ]


@pytest.mark.parametrize(
    "junk",
    [
        None,
        {},
        [],
        "x",
        5,
        {"tables": None},
        {"tables": {"a": None}},
        {"tables": {"a": {"columns": None}}},
    ],
)
def test_an_unusable_schema_gives_an_empty_report_not_an_error(junk: Any) -> None:
    report = audit_schema(junk)
    assert report.missing_links == [] and report.unexplained_ids == []


def test_the_report_converts_to_plain_data_for_json() -> None:
    report = audit_schema({"tables": TABLES})
    data = report.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["missing_links"] == [
        {"table": "orders", "column": "customer_id", "target": "customers"}
    ]
    assert isinstance(report, SchemaAudit)
    assert (
        report.clean is False
        and audit_schema({"tables": {"a": table([("id", "k")], description="d")}}).clean
        is True
    )


def test_the_report_counts_what_it_audited() -> None:
    report = audit_schema({"tables": TABLES})
    assert (report.tables, report.columns) == (3, 6)
    skipped = audit_schema({"tables": TABLES}, ignore_prefixes=("reg",))
    assert (skipped.tables, skipped.columns) == (2, 5)
    assert report.to_dict()["tables"] == 3 and report.to_dict()["clean"] is False
