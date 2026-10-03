"""
Tests for Multi-Format Tabular Data Export Engine.
==================================================
Verifies CSV, JSON, Parquet, and Excel (.xlsx) generation,
data type preservation, XML escaping, edge cases, and error handling.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from query_builder.export import (
    MIME_TYPES,
    ExportError,
    _col_letter,
    _generate_xlsx,
    export_dataset,
)
from query_builder.models import QueryResult


def test_col_letter():
    assert _col_letter(0) == "A"
    assert _col_letter(25) == "Z"
    assert _col_letter(26) == "AA"
    assert _col_letter(27) == "AB"
    assert _col_letter(51) == "AZ"
    assert _col_letter(52) == "BA"


def test_export_csv_from_list_of_dicts():
    data = [
        {"id": 1, "name": "Alpha", "score": 98.5},
        {"id": 2, "name": "Beta", "score": 85.0},
    ]
    payload, mime, ext = export_dataset(data, format="csv")
    assert mime == MIME_TYPES["csv"]
    assert ext == "csv"
    text = payload.decode("utf-8")
    assert "id,name,score\n" in text
    assert "1,Alpha,98.5\n" in text
    assert "2,Beta,85.0\n" in text


def test_export_csv_from_query_result():
    qr = QueryResult(
        sql="SELECT id, name FROM users",
        params=[],
        columns=["id", "name"],
        rows=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        count=2,
        limit=50,
        offset=0,
    )
    payload, mime, ext = export_dataset(qr, format="csv")
    assert mime == MIME_TYPES["csv"]
    assert ext == "csv"
    text = payload.decode("utf-8")
    assert text == "id,name\n1,Alice\n2,Bob\n"


def test_export_csv_from_dict():
    data = {
        "columns": ["code", "desc"],
        "rows": [{"code": "A1", "desc": "Item 1"}],
    }
    payload, _, _ = export_dataset(data, format="csv")
    assert payload.decode("utf-8") == "code,desc\nA1,Item 1\n"


def test_export_csv_escaping_and_nulls():
    data = [
        {"text": 'He said "Hello, world!"\nNext line', "null_val": None},
        {"text": "Simple", "null_val": "Present"},
    ]
    payload, _, _ = export_dataset(data, format="csv")
    text = payload.decode("utf-8")
    assert '"He said ""Hello, world!""' in text
    assert "Simple,Present\n" in text


def test_export_csv_empty_rows():
    # Empty with columns specified
    data = {"columns": ["c1", "c2"], "rows": []}
    payload, _, _ = export_dataset(data, format="csv")
    assert payload.decode("utf-8") == "c1,c2\n"

    # Completely empty list
    payload2, _, _ = export_dataset([], format="csv")
    assert payload2.decode("utf-8") == ""


def test_export_csv_non_dict_rows():
    # Tuple/list rows
    data = {"columns": ["a", "b"], "rows": [[1, 2], (3, None)]}
    payload, _, _ = export_dataset(data, format="csv")
    assert payload.decode("utf-8") == "a,b\n1,2\n3,\n"

    # Scalar rows
    data_scalar = {"columns": ["val"], "rows": [10, None]}
    payload_scalar, _, _ = export_dataset(data_scalar, format="csv")
    assert "val\n10\n" in payload_scalar.decode("utf-8")


def test_export_json_from_list():
    data = [{"id": 1, "value": "test"}]
    payload, mime, ext = export_dataset(data, format="json")
    assert mime == MIME_TYPES["json"]
    assert ext == "json"
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed == [{"id": 1, "value": "test"}]


def test_export_json_from_query_result():
    qr = QueryResult(
        sql="SELECT 1",
        params=[],
        columns=["x"],
        rows=[{"x": 100}],
        count=1,
        limit=10,
        offset=0,
    )
    payload, _, _ = export_dataset(qr, format="json")
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed == [{"x": 100}]


def test_export_json_empty():
    payload, _, _ = export_dataset([], format="json")
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed == []


def test_export_parquet_valid():
    data = [{"id": 1, "name": "foo"}, {"id": 2, "name": "bar"}]
    payload, mime, ext = export_dataset(data, format="parquet")
    assert mime == MIME_TYPES["parquet"]
    assert ext == "parquet"
    assert payload.startswith(b"PAR1")


def test_export_parquet_from_query_result():
    qr = QueryResult(
        sql="SELECT id FROM t",
        params=[],
        columns=["id"],
        rows=[{"id": 42}],
        count=1,
        limit=1,
        offset=0,
    )
    payload, _, _ = export_dataset(qr, format="parquet")
    assert payload.startswith(b"PAR1")


def test_export_parquet_empty_rows():
    # Empty rows with columns
    data = {"columns": ["col1", "col2"], "rows": []}
    payload, _, _ = export_dataset(data, format="parquet")
    assert payload.startswith(b"PAR1")

    # Empty list
    payload_empty, _, _ = export_dataset([], format="parquet")
    assert payload_empty.startswith(b"PAR1")

    # Non-dict rows with columns
    data_tuples = {"columns": ["a", "b"], "rows": [[1, 2], [3, 4]]}
    payload_tuples, _, _ = export_dataset(data_tuples, format="parquet")
    assert payload_tuples.startswith(b"PAR1")

    # Non-dict rows without columns
    data_raw = {"columns": None, "rows": [1, 2, 3]}
    payload_raw, _, _ = export_dataset(data_raw, format="parquet")
    assert payload_raw.startswith(b"PAR1")


def test_export_excel_valid():
    data = [
        {"id": 1, "name": "Item A", "active": True},
        {"id": 2, "name": "Item B", "active": False},
    ]
    payload, mime, ext = export_dataset(data, format="excel")
    assert mime == MIME_TYPES["excel"]
    assert ext == "xlsx"

    # Verify OpenXML archive structure
    zf = zipfile.ZipFile(io.BytesIO(payload))
    namelist = zf.namelist()
    assert "[Content_Types].xml" in namelist
    assert "_rels/.rels" in namelist
    assert "xl/_rels/workbook.xml.rels" in namelist
    assert "xl/workbook.xml" in namelist
    assert "xl/worksheets/sheet1.xml" in namelist

    sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "Item A" in sheet_xml
    assert "Item B" in sheet_xml


def test_export_excel_data_types():
    data = [
        {
            "int_val": 42,
            "float_val": 3.14159,
            "bool_val": True,
            "null_val": None,
            "xml_special": "<tag> & 'quoted' \"double\"",
        }
    ]
    payload, _, _ = export_dataset(data, format="xlsx")
    zf = zipfile.ZipFile(io.BytesIO(payload))
    sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "42" in sheet_xml
    assert "3.14159" in sheet_xml
    assert "&lt;tag&gt; &amp; &apos;quoted&apos; &quot;double&quot;" in sheet_xml


def test_export_excel_empty():
    payload, _, _ = export_dataset([], format="excel")
    zf = zipfile.ZipFile(io.BytesIO(payload))
    assert "xl/worksheets/sheet1.xml" in zf.namelist()


def test_export_excel_non_dict_and_scalar_rows():
    # Sequence of lists/tuples
    data_list = [[1, True, "hello", None], [2, False, "world", 9.9]]
    payload, _, _ = export_dataset(data_list, format="xlsx")
    zf = zipfile.ZipFile(io.BytesIO(payload))
    sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "hello" in sheet_xml

    # Scalar rows without columns
    raw_xlsx = _generate_xlsx([], [10, 3.14, True, False, None, "plain", "<escaped>"])
    zf_scalar = zipfile.ZipFile(io.BytesIO(raw_xlsx))
    sheet_scalar = zf_scalar.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "3.14" in sheet_scalar
    assert "&lt;escaped&gt;" in sheet_scalar


def test_export_case_insensitive_format():
    data = [{"x": 1}]
    _, _mime1, ext1 = export_dataset(data, format="CSV")
    assert ext1 == "csv"
    _, _mime2, ext2 = export_dataset(data, format="Json")
    assert ext2 == "json"
    _, _mime3, ext3 = export_dataset(data, format="PARQUET")
    assert ext3 == "parquet"
    _, _mime4, ext4 = export_dataset(data, format="XLSX")
    assert ext4 == "xlsx"


def test_export_unsupported_format_raises():
    with pytest.raises(ExportError, match="Unsupported export format"):
        export_dataset([{"x": 1}], format="xml")

    with pytest.raises(ExportError, match="Export format must be a string"):
        export_dataset([{"x": 1}], format=123)  # type: ignore


def test_export_invalid_data_raises():
    with pytest.raises(ExportError, match="Unsupported data type"):
        export_dataset("invalid_string", format="csv")  # type: ignore

    with pytest.raises(ExportError, match="must contain 'rows' key"):
        export_dataset({"missing_rows": 1}, format="csv")

    with pytest.raises(ExportError, match="'rows' must be a list"):
        export_dataset({"rows": "not_a_list"}, format="csv")
