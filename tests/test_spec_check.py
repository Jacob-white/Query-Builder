"""``check_columns``: a spec may only name columns that exist, and a bad one is refused with a reason before it compiles.

The compiler checks identifier shape and SQL safety, not that a column exists, so a made-up or misspelt column (a person's
typo, or one an AI helper invented) reaches the database and comes back as a driver error. ``check_columns(spec, schema)``
refuses it first with a message that names the column and the table, suggests the likeliest real column and lists what
exists, which is also what a caller needs to send back to a model for a repair. Anything that is not a plain column of a
listed table is left alone: expressions, CASE columns, ``*``, aliases, sub-queries and tables the schema does not list.
"""

from __future__ import annotations

from typing import Any

import pytest

from query_builder import (
    SchemaSnapshot,
    SpecColumnError,
    ValidationError,
    check_columns,
)

SCHEMA: dict[str, Any] = {
    "tables": {
        "orders": {
            "name": "orders",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "order_number", "type": "TEXT"},
                {"name": "status", "type": "TEXT"},
                {"name": "customer_id", "type": "INTEGER"},
            ],
        },
        "customers": {
            "name": "customers",
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "region", "type": "TEXT"},
                {"name": "full_name", "type": "TEXT"},
            ],
        },
    }
}

JOIN = {
    "type": "INNER",
    "table": "customers",
    "left_table": "orders",
    "left_col": "customer_id",
    "right_col": "id",
}


def refused(spec: dict[str, Any], schema: Any = SCHEMA) -> SpecColumnError:
    with pytest.raises(SpecColumnError) as caught:
        check_columns(spec, schema)
    return caught.value


# --- refused: each names the column, the table and what exists -------------------------------------------------------


def test_a_made_up_column_is_refused_with_the_real_ones_listed() -> None:
    error = refused(
        {"table": "orders", "columns": ["orders.id", "orders.no_such_column"]}
    )
    said = str(error)
    assert "no_such_column" in said and "orders" in said and "order_number" in said
    assert error.column == "orders.no_such_column" and error.table == "orders"
    assert "order_number" in error.available


def test_the_error_is_a_validation_error_so_existing_handlers_catch_it() -> None:
    assert isinstance(
        refused({"table": "orders", "columns": ["orders.zzz"]}), ValidationError
    )


def test_a_made_up_column_written_as_an_object_is_refused() -> None:
    assert "zzz" in str(
        refused(
            {"table": "orders", "columns": [{"column": "orders.zzz", "alias": "x"}]}
        )
    )


def test_a_made_up_bare_column_is_read_as_a_column_of_the_base_table() -> None:
    assert refused({"table": "orders", "columns": ["zzz"]}).table == "orders"


def test_a_made_up_column_in_a_filter_is_refused() -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.id"],
        "filters": [{"column": "orders.zzz", "op": "eq", "value": "x"}],
    }
    assert "zzz" in str(refused(spec))


def test_a_filter_with_a_table_prefix_key_is_checked_against_that_table() -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.id"],
        "joins": [JOIN],
        "filters": [
            {"column": "zzz", "tablePrefix": "customers", "op": "eq", "value": 1}
        ],
    }
    assert refused(spec).table == "customers"


def test_a_made_up_column_in_a_sort_is_refused() -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.id"],
        "order_by": [{"column": "orders.zzz", "direction": "asc"}],
    }
    assert "zzz" in str(refused(spec))


def test_a_made_up_column_of_a_joined_table_is_refused() -> None:
    error = refused(
        {"table": "orders", "columns": ["orders.id", "customers.zzz"], "joins": [JOIN]}
    )
    assert error.table == "customers" and "region" in error.available


def test_a_column_of_a_table_that_is_not_in_the_query_is_refused_and_says_to_join_it() -> (
    None
):
    said = str(
        refused({"table": "orders", "columns": ["orders.id", "customers.region"]})
    )
    assert (
        "customers" in said
        and "not in this query" in said
        and "Join customers first" in said
    )


def test_a_near_miss_is_answered_with_the_column_it_probably_meant() -> None:
    assert (
        refused({"table": "orders", "columns": ["orders.order_numbr"]}).suggestions[0]
        == "order_number"
    )


def test_a_name_that_is_part_of_a_real_column_is_suggested_first() -> None:
    # "number" is inside order_number: a better guess than whatever merely looks alike.
    error = refused({"table": "orders", "columns": ["orders.number"]})
    assert error.suggestions[0] == "order_number"
    assert "Did you mean order_number" in str(error)


def test_with_nothing_close_there_is_no_suggestion_and_the_columns_are_still_listed() -> (
    None
):
    error = refused({"table": "orders", "columns": ["orders.qqqqqqqq"]})
    assert (
        error.suggestions == []
        and "Did you mean" not in str(error)
        and "The columns of orders are:" in str(error)
    )


def test_a_very_wide_table_lists_only_the_first_sixty_columns() -> None:
    wide = {
        "tables": {"wide": {"columns": [{"name": f"c{i:03d}"} for i in range(100)]}}
    }
    said = str(refused({"table": "wide", "columns": ["wide.zzz"]}, wide))
    assert "c059" in said and "c060" not in said and "..." in said


# --- accepted: the same shapes, right, pass --------------------------------------------------------------------------


def test_real_columns_across_a_join_pass() -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.id", {"column": "customers.region", "alias": "area"}],
        "joins": [JOIN],
        "filters": [{"column": "customers.region", "op": "eq", "value": "east"}],
        "order_by": [{"column": "orders.id", "direction": "asc"}],
    }
    check_columns(spec, SCHEMA)


def test_a_joined_table_given_an_alias_is_found_by_either_name() -> None:
    spec = {
        "table": "orders",
        "columns": ["c.region"],
        "joins": [{**JOIN, "alias": "c"}],
    }
    check_columns(spec, SCHEMA)
    assert (
        refused(
            {"table": "orders", "columns": ["c.zzz"], "joins": [{**JOIN, "alias": "c"}]}
        ).table
        == "customers"
    )


def test_a_count_over_every_row_is_not_mistaken_for_a_column() -> None:
    check_columns(
        {"table": "orders", "columns": [{"column": "*", "agg": "count", "alias": "n"}]},
        SCHEMA,
    )
    check_columns({"table": "orders", "columns": ["*"]}, SCHEMA)


# --- left alone: things that are not a column of a listed table -------------------------------------------------------


def test_expressions_case_columns_aliases_sub_queries_and_unlisted_tables_are_not_this_checks_business() -> (
    None
):
    check_columns(
        {
            "table": "orders",
            "columns": [
                {"expression": "1", "alias": "one"},
                {"case_when": [], "alias": "c"},
            ],
        },
        SCHEMA,
    )
    check_columns(
        {
            "table": "orders",
            "columns": [{"column": "orders.id", "alias": "ident"}],
            "order_by": [{"column": "ident"}],
        },
        SCHEMA,
    )
    check_columns(
        {
            "table": "recent",
            "columns": ["recent.anything"],
            "ctes": [{"name": "recent", "query": {}}],
        },
        SCHEMA,
    )
    check_columns({"table": "mystery", "columns": ["mystery.id"]}, SCHEMA)


def test_a_sub_query_in_the_join_list_is_not_checked_against_the_schema() -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.id", "recent.anything"],
        "joins": [
            {
                "type": "INNER",
                "table": "recent",
                "left_table": "orders",
                "left_col": "id",
                "right_col": "id",
            }
        ],
        "ctes": [{"name": "recent", "query": {}}],
    }
    check_columns(spec, SCHEMA)


def test_a_filter_on_a_sub_query_is_left_alone() -> None:
    spec = {
        "table": "orders",
        "columns": ["orders.id"],
        "filters": [
            {"column": "orders.id", "op": "in", "subquery": {"table": "customers"}}
        ],
    }
    check_columns(spec, SCHEMA)


@pytest.mark.parametrize(
    "junk", [None, [], "columns", 7, [None], [{}], [["a"]], [{"column": 5}]]
)
def test_malformed_columns_do_not_crash_the_check(junk: Any) -> None:
    check_columns({"table": "orders", "columns": junk}, SCHEMA)


@pytest.mark.parametrize(
    "spec", [None, [], "x", {}, {"table": 5}, {"table": None}, {"columns": ["id"]}]
)
def test_a_spec_that_is_not_a_spec_is_left_for_the_compiler(spec: Any) -> None:
    check_columns(spec, SCHEMA)


def test_an_empty_or_unusable_schema_checks_nothing() -> None:
    for schema in (None, {}, {"tables": {}}, [], "x"):
        check_columns({"table": "orders", "columns": ["orders.zzz"]}, schema)


# --- the shapes a schema can come in -------------------------------------------------------------------------------------


def test_a_bare_mapping_of_tables_is_accepted_as_a_schema() -> None:
    assert (
        refused({"table": "orders", "columns": ["orders.zzz"]}, SCHEMA["tables"]).table
        == "orders"
    )


def test_columns_may_be_plain_names_or_a_name_to_type_mapping() -> None:
    as_names = {"tables": {"orders": {"columns": ["id", "status"]}}}
    as_mapping = {
        "tables": {"orders": {"columns": {"id": "INTEGER", "status": "TEXT"}}}
    }
    for schema in (as_names, as_mapping):
        check_columns({"table": "orders", "columns": ["orders.status"]}, schema)
        assert refused(
            {"table": "orders", "columns": ["orders.zzz"]}, schema
        ).available == ["id", "status"]


def test_a_schema_snapshot_is_accepted() -> None:
    snapshot = SchemaSnapshot(tables=SCHEMA["tables"])
    assert (
        refused({"table": "orders", "columns": ["orders.zzz"]}, snapshot).table
        == "orders"
    )


def test_a_table_name_is_matched_case_sensitively_like_the_compiler_does() -> None:
    check_columns(
        {"table": "Orders", "columns": ["Orders.zzz"]}, SCHEMA
    )  # not a listed table: left alone
