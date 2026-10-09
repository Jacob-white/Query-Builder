"""Mock tests for the Apache Drill REST adapter and client-side parameter inlining."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import drill as dr
from query_builder.connectors.base import QueryExecutionError


class _Rest:
    """A pydrill-shaped client: only ``perform_request``."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[Any, ...]] = []

    def perform_request(self, method: str, url: str, **kw: Any) -> Any:
        self.calls.append((method, url, kw))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return (None, item, 0.0)


def test_has_attr_variants() -> None:
    assert dr._has_attr(object(), "__class__")
    assert not dr._has_attr(object(), "nope")
    plain = MagicMock()
    assert not dr._has_attr(plain, "execute")  # not yet touched
    plain.execute  # noqa: B018 - touching creates the child
    assert dr._has_attr(plain, "execute")
    spec = MagicMock(spec=["execute"])
    assert dr._has_attr(spec, "execute") and not dr._has_attr(spec, "fetchall")


def test_drill_literal_rendering_and_rejections() -> None:
    lit = dr._drill_literal
    assert lit(None) == "NULL"
    assert (lit(True), lit(False)) == ("TRUE", "FALSE")
    assert lit(7) == "7" and lit(1.5) == "1.5"
    assert lit("it's") == "'it''s'"
    assert lit("a\\b") == "'a\\b'"  # backslash is literal in Drill
    assert lit(3 + 0j) == "'(3+0j)'"  # non-str objects are stringified, then quoted
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="non-finite"):
            lit(bad)
    with pytest.raises(ValueError, match="NUL"):
        lit("a\x00b")


def test_inline_params_substitution_and_guards() -> None:
    assert dr.inline_params("SELECT 1", None) == "SELECT 1"
    assert dr.inline_params("SELECT %s", []) == "SELECT %s"
    assert (
        dr.inline_params("SELECT * FROM t WHERE a = %s AND b = %s", [1, "x'; DROP"])
        == "SELECT * FROM t WHERE a = 1 AND b = 'x''; DROP'"
    )
    # placeholders inside quoted text/identifiers are left alone; doubled quotes stay quoted
    assert (
        dr.inline_params("SELECT '%s it''s %s', `c%s`, \"d\" FROM t WHERE x = %s", [9])
        == "SELECT '%s it''s %s', `c%s`, \"d\" FROM t WHERE x = 9"
    )
    # a payload that is itself a placeholder is never re-expanded
    assert dr.inline_params("a=%s AND b=%s", ["%s", 2]) == "a='%s' AND b=2"
    with pytest.raises(ValueError, match="more placeholders"):
        dr.inline_params("a=%s AND b=%s", [1])
    with pytest.raises(ValueError, match="parameters supplied"):
        dr.inline_params("a=%s", [1, 2])
    assert dr.inline_params("a LIKE '50%'", None) == "a LIKE '50%'"


def test_rest_query_success_sets_types_and_default_schema() -> None:
    rest = _Rest(
        [
            {
                "queryState": "COMPLETED",
                "columns": ["a", "b"],
                "metadata": ["INT", "VARCHAR"],
                "rows": [{"a": 1, "b": "x"}],
            }
        ]
    )
    cur = dr._DrillCursorAdapter(rest, default_schema="dfs.tmp", timeout_s=7)
    cur.execute("SELECT a, b FROM t WHERE a = %s;", [1])
    method, url, kw = rest.calls[0]
    assert (method, url) == ("POST", "/query.json")
    assert kw["params"] == {"request_timeout": 7}
    assert kw["body"] == {
        "queryType": "SQL",
        "query": "SELECT a, b FROM t WHERE a = 1",
        "defaultSchema": "dfs.tmp",
    }
    assert cur.description == [("a", "INT"), ("b", "VARCHAR")]
    assert cur.fetchone() == [1, "x"]
    assert cur.fetchone() is None
    assert cur.fetchall() == []
    cur.close()


def test_rest_query_handles_untyped_columns_list_rows_and_default_timeout() -> None:
    rest = _Rest([{"columns": ["a", "b"], "rows": [{"a": 1}], "metadata": ["INT"]}])
    cur = dr._DrillCursorAdapter(rest)
    cur.execute("SELECT a, b FROM t")
    assert rest.calls[0][2]["params"] == {"request_timeout": 300}
    assert "defaultSchema" not in rest.calls[0][2]["body"]
    assert cur.description == [("a", "INT"), ("b", None)]
    assert cur.fetchall() == [[1, None]]  # a column absent from the row is None
    # a non-dict reply is an empty result, not a crash
    rest2 = _Rest(["garbage"])
    cur2 = dr._DrillCursorAdapter(rest2)
    cur2.execute("SELECT 1")
    assert cur2.description == [] and cur2.fetchall() == []


def test_rest_query_failed_state_reports_profile_error() -> None:
    rest = _Rest(
        [
            {"queryState": "FAILED", "queryId": "q1"},
            RuntimeError("profile not ready"),
            {"error": ""},
            {"error": " VALIDATION ERROR: Table 'x' not found "},
        ]
    )
    cur = dr._DrillCursorAdapter(rest)
    with patch.object(dr.time, "sleep") as sleep, pytest.raises(QueryExecutionError) as ei:
        cur.execute("SELECT * FROM x")
    assert "FAILED: VALIDATION ERROR: Table 'x' not found" in str(ei.value)
    assert sleep.call_count == 2
    assert rest.calls[1][:2] == ("GET", "/profiles/q1.json")


def test_failure_message_without_detail_or_query_id() -> None:
    cur = dr._DrillCursorAdapter(_Rest([]))
    assert "no error detail reported" in cur._failure_message({}, "FAILED")
    assert cur._failure_message({"errorMessage": "boom"}, "FAILED").endswith("boom")
    rest = _Rest([{"error": ""}] * 6)
    cur2 = dr._DrillCursorAdapter(rest)
    with patch.object(dr.time, "sleep"):
        msg = cur2._failure_message({"queryId": "q"}, "CANCELED")
    assert msg == "Apache Drill query CANCELED: no error detail reported"
    assert len(rest.calls) == 6


def test_rest_query_timeout_cancels_running_query() -> None:
    class ReadTimeout(Exception):
        pass

    sql = "SELECT  *   FROM big"
    rest = _Rest(
        [
            ReadTimeout("slow"),
            {
                "runningQueries": [
                    {"query": "SELECT 1", "queryId": "other"},
                    {"query": "SELECT * FROM big", "queryId": "q9"},
                ]
            },
            {},
        ]
    )
    cur = dr._DrillCursorAdapter(rest)
    with pytest.raises(ReadTimeout):
        cur.execute(sql)
    assert [c[1] for c in rest.calls] == [
        "/query.json",
        "/profiles.json",
        "/profiles/cancel/q9",
    ]
    # "timed out" text also triggers it; other errors do not
    rest2 = _Rest([RuntimeError("request timed out"), RuntimeError("cancel fails")])
    cur2 = dr._DrillCursorAdapter(rest2)
    with pytest.raises(RuntimeError, match="timed out"):
        cur2.execute("SELECT 1")
    assert len(rest2.calls) == 2  # the cancel attempt failed silently
    rest3 = _Rest([RuntimeError("connection refused")])
    with pytest.raises(RuntimeError, match="refused"):
        dr._DrillCursorAdapter(rest3).execute("SELECT 1")
    assert len(rest3.calls) == 1


def test_execute_via_dbapi_connection_with_and_without_params() -> None:
    inner = MagicMock()
    inner.description = [("c",)]
    inner.fetchall.return_value = [(1,)]
    target = MagicMock(spec=["cursor"])
    target.cursor.return_value = inner
    ad = dr._DrillCursorAdapter(target)
    ad.execute("SELECT c FROM t WHERE a = %s;", [3])
    inner.execute.assert_called_once_with("SELECT c FROM t WHERE a = %s", [3])
    assert ad.description == [("c",)] and ad.fetchall() == [(1,)]
    inner.close.assert_called_once()
    ad.execute("SELECT 1")
    inner.execute.assert_called_with("SELECT 1")
    # a cursor without fetchall yields no rows
    inner2 = MagicMock(spec=["execute", "close"])
    target.cursor.return_value = inner2
    ad.execute("SELECT 2")
    assert ad.fetchall() == []


def test_execute_via_query_only_client() -> None:
    client = MagicMock(spec=["query"])
    res = MagicMock()
    res.columns = ["a", "b"]
    res.rows = [{"a": 1, "b": 2}, [10, 20], [30], 99]
    client.query.return_value = res
    ad = dr._DrillCursorAdapter(client)
    ad.execute("SELECT a, b FROM t WHERE a = %s", [1])
    client.query.assert_called_once_with("SELECT a, b FROM t WHERE a = 1")
    assert ad.description == [("a",), ("b",)]
    assert ad.fetchall() == [[1, 2], [10, 20], [30, [30]], [99, 99]]


def test_execute_via_cursor_like_target_and_fallthrough() -> None:
    cur = MagicMock(spec=["execute", "fetchall", "description"])
    cur.description = [("x",)]
    cur.fetchall.return_value = [(5,)]
    ad = dr._DrillCursorAdapter(cur)
    ad.execute("SELECT x FROM t WHERE a = %s;", [1])
    cur.execute.assert_called_once_with("SELECT x FROM t WHERE a = %s", [1])
    assert ad.fetchall() == [(5,)]
    ad.execute("SELECT x")
    cur.execute.assert_called_with("SELECT x")
    only_exec = MagicMock(spec=["execute"])
    ad2 = dr._DrillCursorAdapter(only_exec)
    ad2.execute("SELECT 1")
    assert ad2.fetchall() == []
    ad3 = dr._DrillCursorAdapter(object())  # nothing usable
    ad3.execute("SELECT 1")
    assert ad3.description is None and ad3.fetchall() == []
