"""CSV export must not let a cell run as a spreadsheet formula.

A value that starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return is read by Excel and LibreOffice as a
formula when the file is opened, and a query can return text someone else typed (or a column alias a caller chose). The
exporters prefix such *text* with an apostrophe. Numbers, ``None`` and booleans are not text and are left alone, so a
negative number stays a number. The ``.xlsx`` writer stores text as inline strings, which are never evaluated, so only the
CSV paths needed this.

Each adversarial case has a control in ``test_the_opt_out_writes_the_text_as_it_was``: the same scenario with the
protection off must show the dangerous cell, so a passing test proves the code and not a scenario that cannot fail.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

import pytest

from query_builder.export import (
    CsvStreamExporter,
    csv_safe_cell,
    export_dataset,
    stream_export_dataset,
)

DANGEROUS = [
    "=1+1",
    '=HYPERLINK("http://x","y")',
    "+SUM(A1:A9)",
    "-2+3",
    "@SUM(A1)",
    "\t=1",
    "\r=1",
    "=cmd|' /C calc'!A0",
]


def read_back(payload: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(payload.decode("utf-8"))))


@pytest.mark.parametrize("text", DANGEROUS)
def test_text_that_starts_like_a_formula_gets_an_apostrophe(text: str) -> None:
    assert csv_safe_cell(text) == "'" + text


@pytest.mark.parametrize(
    "value",
    ["plain", "", "a=1", "1+1", "x@y.com", "'=already quoted", " =1", "é"],
)
def test_other_text_is_untouched(value: str) -> None:
    assert csv_safe_cell(value) == value


@pytest.mark.parametrize("value", [5, -5, 0, 2.5, -2.5, Decimal("-1.50"), float("inf")])
def test_numbers_are_not_text_and_are_untouched(value: Any) -> None:
    assert csv_safe_cell(value) == value


@pytest.mark.parametrize("value", [None, True, False])
def test_none_and_booleans_are_untouched(value: Any) -> None:
    assert csv_safe_cell(value) is value


def test_other_objects_are_read_as_the_text_the_csv_writer_would_write() -> None:
    class Evil:
        def __str__(self) -> str:
            return "=1+1"

    assert csv_safe_cell(Evil()) == "'=1+1"
    assert (
        csv_safe_cell(b"=1") == "b'=1'"
    )  # the bytes repr, as the csv writer writes it


# --- export_dataset ---------------------------------------------------------------------------------------------------


def test_a_formula_cell_is_neutralised_and_a_negative_number_is_not() -> None:
    payload, _, _ = export_dataset(
        [{"note": "=1+1", "balance": -5, "ratio": -2.5}], format="csv"
    )
    header, row = read_back(payload)
    assert header == ["note", "balance", "ratio"]
    assert row == ["'=1+1", "-5", "-2.5"]


def test_list_rows_and_scalar_rows_are_neutralised_too() -> None:
    as_lists, _, _ = export_dataset(
        {"columns": ["a", "b"], "rows": [["=1", -1], ["@x", 2]]}, format="csv"
    )
    assert read_back(as_lists)[1:] == [["'=1", "-1"], ["'@x", "2"]]
    scalars, _, _ = export_dataset({"columns": [], "rows": ["=1", "ok"]}, format="csv")
    assert read_back(scalars) == [["'=1"], ["ok"]]


@pytest.mark.parametrize("alias", ["=SUM(1)", "+x", "-x", "@x"])
def test_a_column_name_that_looks_like_a_formula_is_neutralised(alias: str) -> None:
    payload, _, _ = export_dataset([{alias: "v"}], format="csv")
    assert read_back(payload)[0] == ["'" + alias]


def test_the_opt_out_writes_the_text_as_it_was() -> None:
    # The control: the dangerous scenario with the protection off must show the dangerous cell.
    payload, _, _ = export_dataset(
        [{"=1+1": "=1+1"}], format="csv", neutralize_formulas=False
    )
    assert read_back(payload) == [["=1+1"], ["=1+1"]]
    safe, _, _ = export_dataset([{"=1+1": "=1+1"}], format="csv")
    assert read_back(safe) == [["'=1+1"], ["'=1+1"]]


def test_other_formats_are_not_changed_by_the_option() -> None:
    on, _, _ = export_dataset([{"a": "=1"}], format="json")
    off, _, _ = export_dataset([{"a": "=1"}], format="json", neutralize_formulas=False)
    assert on == off and b'"=1"' in on


# --- streaming ---------------------------------------------------------------------------------------------------------


def test_the_streaming_exporter_neutralises_values_and_headers() -> None:
    chunks, _, _ = stream_export_dataset(
        [{"=h": "=1", "n": -3}], format="csv", chunk_size=1
    )
    rows = read_back(b"".join(chunks))
    assert rows == [["'=h", "n"], ["'=1", "-3"]]


def test_the_streaming_exporter_opt_out_is_the_control() -> None:
    chunks, _, _ = stream_export_dataset(
        [{"=h": "=1"}], format="csv", neutralize_formulas=False
    )
    assert read_back(b"".join(chunks)) == [["=h"], ["=1"]]


def test_the_stream_class_takes_the_option_directly() -> None:
    data = [{"a": "@x"}]
    safe = b"".join(CsvStreamExporter().export_stream(data))
    raw = b"".join(CsvStreamExporter(neutralize_formulas=False).export_stream(data))
    assert read_back(safe)[1] == ["'@x"] and read_back(raw)[1] == ["@x"]


def test_a_chunk_boundary_does_not_skip_neutralising() -> None:
    rows = [{"a": "=1"} for _ in range(5)]
    chunks, _, _ = stream_export_dataset(rows, format="csv", chunk_size=2)
    assert read_back(b"".join(chunks))[1:] == [["'=1"]] * 5


def test_neutralising_is_linear_for_a_hostile_cell() -> None:
    import time

    big = "=" + "A" * 2_000_000
    started = time.perf_counter()
    assert csv_safe_cell(big).startswith("'=")
    assert time.perf_counter() - started < 1.0
