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


def test_export_dataset_dict_without_columns_infers_from_rows():
    data = {"rows": [{"a": 1, "b": "hello"}]}
    payload, mime, ext = export_dataset(data, format="csv")
    assert mime == MIME_TYPES["csv"]
    assert ext == "csv"
    assert "a,b\n1,hello\n" in payload.decode("utf-8")


def test_export_jsonl_and_ndjson():
    data = [{"id": 1, "val": "A"}, {"id": 2, "val": "B"}]
    payload1, mime1, ext1 = export_dataset(data, format="jsonl")
    assert mime1 == "application/x-ndjson"
    assert ext1 == "jsonl"
    lines1 = payload1.decode("utf-8").strip().split("\n")
    assert len(lines1) == 2
    assert json.loads(lines1[0]) == {"id": 1, "val": "A"}

    payload2, mime2, ext2 = export_dataset(data, format="ndjson")
    assert mime2 == "application/x-ndjson"
    assert ext2 == "jsonl"
    assert payload1 == payload2

    # Empty rows
    empty_payload, _, _ = export_dataset([], format="jsonl")
    assert empty_payload == b""


def test_export_arrow():
    import polars as pl

    data = [{"id": 1, "val": "A"}, {"id": 2, "val": "B"}]
    payload, mime, ext = export_dataset(data, format="arrow")
    assert mime == "application/vnd.apache.arrow.stream"
    assert ext == "arrow"

    df = pl.read_ipc_stream(io.BytesIO(payload))
    assert len(df) == 2
    assert df["id"].to_list() == [1, 2]

    # Non-dict rows with columns
    data_tuples = {"columns": ["x", "y"], "rows": [[10, 20], [30, 40]]}
    payload_tuples, _, _ = export_dataset(data_tuples, format="arrow")
    df_tuples = pl.read_ipc_stream(io.BytesIO(payload_tuples))
    assert df_tuples.columns == ["x", "y"]
    assert len(df_tuples) == 2

    # Empty rows with columns
    payload_empty_cols, _, _ = export_dataset(
        {"columns": ["c1"], "rows": []}, format="arrow"
    )
    df_empty = pl.read_ipc_stream(io.BytesIO(payload_empty_cols))
    assert df_empty.columns == ["c1"]
    assert len(df_empty) == 0

    # Totally empty
    payload_empty, _, _ = export_dataset([], format="arrow")
    df_totally_empty = pl.read_ipc_stream(io.BytesIO(payload_empty))
    assert len(df_totally_empty) == 0


def test_stream_export_dataset_csv():
    from query_builder.export import stream_export_dataset

    # From QueryResult
    qr = QueryResult(
        sql="SELECT id, name FROM users",
        params=[],
        columns=["id", "name"],
        rows=[
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ],
        count=3,
        limit=50,
        offset=0,
    )
    stream_iter, mime, ext = stream_export_dataset(qr, format="csv", chunk_size=2)
    assert mime == MIME_TYPES["csv"]
    assert ext == "csv"
    chunks = list(stream_iter)
    assert len(chunks) >= 2
    full_csv = b"".join(chunks).decode("utf-8")
    assert "id,name\n" in full_csv
    assert "1,Alice\n" in full_csv
    assert "3,Charlie\n" in full_csv

    # From generator of tuples
    def gen_rows():
        yield [10, "ten"]
        yield [20, "twenty"]

    stream_iter2, _, _ = stream_export_dataset(
        gen_rows(), format="csv", columns=["num", "word"], chunk_size=1
    )
    full_csv2 = b"".join(list(stream_iter2)).decode("utf-8")
    assert full_csv2 == "num,word\n10,ten\n20,twenty\n"

    # From generator of scalars
    def gen_scalars():
        yield 100
        yield None

    stream_iter3, _, _ = stream_export_dataset(
        gen_scalars(), format="csv", chunk_size=1
    )
    full_csv3 = b"".join(list(stream_iter3)).decode("utf-8")
    assert "100\n" in full_csv3

    # Empty list with no columns
    stream_empty, _, _ = stream_export_dataset([], format="csv")
    assert b"".join(list(stream_empty)) == b""

    # Empty list with columns
    stream_empty_cols, _, _ = stream_export_dataset(
        [], format="csv", columns=["col1", "col2"]
    )
    assert b"".join(list(stream_empty_cols)).decode("utf-8") == "col1,col2\n"

    # List of non-dict rows without columns
    stream_list_tuples, _, _ = stream_export_dataset([[1, 2], [3, 4]], format="csv")
    assert b"".join(list(stream_list_tuples)).decode("utf-8") == "1,2\n3,4\n"


def test_stream_export_dataset_json_and_jsonl():
    from query_builder.export import stream_export_dataset

    data = [{"id": 1, "tag": "prod"}, {"id": 2, "tag": "dev"}]

    # JSONL
    stream_jsonl, mime_jl, ext_jl = stream_export_dataset(
        data, format="jsonl", chunk_size=1
    )
    assert mime_jl == "application/x-ndjson"
    assert ext_jl == "jsonl"
    chunks_jl = list(stream_jsonl)
    assert len(chunks_jl) == 2
    full_jl = b"".join(chunks_jl).decode("utf-8")
    lines = [json.loads(line) for line in full_jl.strip().split("\n")]
    assert len(lines) == 2
    assert lines[0]["id"] == 1

    # NDJSON alias
    stream_ndjson, mime_nd, ext_nd = stream_export_dataset(data, format="ndjson")
    assert mime_nd == "application/x-ndjson"
    assert ext_nd == "jsonl"
    assert b"".join(list(stream_ndjson)) == full_jl.encode("utf-8")

    # JSON array streaming
    stream_json, mime_j, ext_j = stream_export_dataset(
        data, format="json", chunk_size=1
    )
    assert mime_j == "application/json"
    assert ext_j == "json"
    full_json = b"".join(list(stream_json)).decode("utf-8")
    parsed_json = json.loads(full_json)
    assert parsed_json == data

    # Empty JSON array streaming
    empty_json, _, _ = stream_export_dataset([], format="json")
    assert json.loads(b"".join(list(empty_json)).decode("utf-8")) == []


def test_stream_export_dataset_arrow_and_parquet():
    import polars as pl
    from query_builder.export import stream_export_dataset

    data = [{"a": 1, "b": 1.5}, {"a": 2, "b": 2.5}]

    # Arrow
    stream_arrow, mime_ar, ext_ar = stream_export_dataset(
        data, format="arrow", chunk_size=1
    )
    assert mime_ar == "application/vnd.apache.arrow.stream"
    assert ext_ar == "arrow"
    full_arrow = b"".join(list(stream_arrow))
    df_ar = pl.read_ipc_stream(io.BytesIO(full_arrow))
    assert len(df_ar) == 2
    assert df_ar["a"].to_list() == [1, 2]

    # Arrow with columns and non-dict rows
    data_dict = {"columns": ["k", "v"], "rows": [["k1", "v1"], ["k2", "v2"]]}
    stream_ar_rows, _, _ = stream_export_dataset(data_dict, format="arrow")
    df_ar_rows = pl.read_ipc_stream(io.BytesIO(b"".join(list(stream_ar_rows))))
    assert df_ar_rows.columns == ["k", "v"]

    # Arrow empty
    stream_ar_empty, _, _ = stream_export_dataset([], format="arrow", columns=["c1"])
    df_ar_empty = pl.read_ipc_stream(io.BytesIO(b"".join(list(stream_ar_empty))))
    assert df_ar_empty.columns == ["c1"]
    assert len(df_ar_empty) == 0

    # Parquet
    stream_parq, mime_pq, ext_pq = stream_export_dataset(
        data, format="parquet", chunk_size=1
    )
    assert mime_pq == "application/vnd.apache.parquet"
    assert ext_pq == "parquet"
    full_parq = b"".join(list(stream_parq))
    df_pq = pl.read_parquet(io.BytesIO(full_parq))
    assert len(df_pq) == 2
    assert df_pq["a"].to_list() == [1, 2]

    # Parquet with columns and non-dict rows
    stream_pq_rows, _, _ = stream_export_dataset(data_dict, format="parquet")
    df_pq_rows = pl.read_parquet(io.BytesIO(b"".join(list(stream_pq_rows))))
    assert df_pq_rows.columns == ["k", "v"]

    # Parquet empty
    stream_pq_empty, _, _ = stream_export_dataset([], format="parquet", columns=["p1"])
    df_pq_empty = pl.read_parquet(io.BytesIO(b"".join(list(stream_pq_empty))))
    assert df_pq_empty.columns == ["p1"]
    assert len(df_pq_empty) == 0


def test_stream_export_dataset_excel():
    from query_builder.export import stream_export_dataset

    data = [{"title": "Doc1", "count": 10}, {"title": "Doc2", "count": 20}]
    stream_excel, mime_xl, ext_xl = stream_export_dataset(
        data, format="excel", chunk_size=1
    )
    assert mime_xl == MIME_TYPES["excel"]
    assert ext_xl == "xlsx"
    full_xl = b"".join(list(stream_excel))
    zf = zipfile.ZipFile(io.BytesIO(full_xl))
    assert "xl/worksheets/sheet1.xml" in zf.namelist()
    xml_content = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "Doc1" in xml_content
    assert "Doc2" in xml_content

    # xlsx format alias with explicit columns
    stream_xlsx, _, ext_xx = stream_export_dataset(
        data, format="xlsx", columns=["title", "count"]
    )
    assert ext_xx == "xlsx"
    zf2 = zipfile.ZipFile(io.BytesIO(b"".join(list(stream_xlsx))))
    assert "xl/workbook.xml" in zf2.namelist()


def test_stream_export_dataset_validations_and_errors():
    from query_builder.export import stream_export_dataset

    # Format not string
    with pytest.raises(ExportError, match="Export format must be a string"):
        stream_export_dataset([{"a": 1}], format=999)  # type: ignore

    # Unsupported format
    with pytest.raises(ExportError, match="Unsupported export format"):
        stream_export_dataset([{"a": 1}], format="proto")

    # Unsupported data type
    with pytest.raises(ExportError, match="Unsupported data type"):
        stream_export_dataset(12345, format="csv")

    # Dict missing rows key
    with pytest.raises(ExportError, match="must contain 'rows' key"):
        stream_export_dataset({"wrong": []}, format="csv")

    # Dict with non-list rows
    with pytest.raises(ExportError, match="'rows' must be a list"):
        stream_export_dataset({"rows": "bad"}, format="csv")

    # Dict without columns with empty rows
    stream_empty_dict, _, _ = stream_export_dataset({"rows": []}, format="csv")
    assert b"".join(list(stream_empty_dict)) == b""

    # Dict without columns with non-empty rows infers columns
    stream_dict_infers, _, _ = stream_export_dataset(
        {"rows": [{"inferred": 123}]}, format="csv"
    )
    assert "inferred\n123\n" in b"".join(list(stream_dict_infers)).decode("utf-8")


def test_export_edge_cases_and_exporter_direct():
    import polars as pl
    from query_builder.export import (
        ArrowStreamExporter,
        CsvStreamExporter,
        ExcelStreamExporter,
        JsonStreamExporter,
        ParquetStreamExporter,
    )

    # 1. export_dataset with non-dict rows and no columns for arrow
    payload, _, _ = export_dataset([[100, 200]], format="arrow")
    df = pl.read_ipc_stream(io.BytesIO(payload))
    assert len(df) == 2

    # 2. CsvStreamExporter with columns=None and dict rows
    csv_exp = CsvStreamExporter(columns=None, chunk_size=1)
    res = list(csv_exp.export_stream([{"dynamic": "val"}]))
    assert "dynamic\nval\n" in b"".join(res).decode("utf-8")

    # 3. CsvStreamExporter with columns given but empty row_iterator
    csv_exp_empty = CsvStreamExporter(columns=["empty_col"])
    res_empty = list(csv_exp_empty.export_stream([]))
    assert b"".join(res_empty).decode("utf-8") == "empty_col\n"

    # 4. JsonStreamExporter with multiple items and chunk_size=2 (tests both loop yield and trailing batch)
    json_exp = JsonStreamExporter(chunk_size=2)
    json_res = b"".join(list(json_exp.export_stream([{"k": 1}, {"k": 2}, {"k": 3}])))
    assert json.loads(json_res.decode("utf-8")) == [{"k": 1}, {"k": 2}, {"k": 3}]

    # 5. ArrowStreamExporter direct with non-dict rows and no columns
    arrow_exp1 = ArrowStreamExporter(columns=None)
    data1 = b"".join(list(arrow_exp1.export_stream([[55, 66]])))
    assert len(pl.read_ipc_stream(io.BytesIO(data1))) == 2

    # 6. ArrowStreamExporter direct with empty rows and no columns
    arrow_exp2 = ArrowStreamExporter(columns=None)
    data2 = b"".join(list(arrow_exp2.export_stream([])))
    assert len(pl.read_ipc_stream(io.BytesIO(data2))) == 0

    # 7. ParquetStreamExporter direct with non-dict rows and no columns
    parq_exp1 = ParquetStreamExporter(columns=None)
    pdata1 = b"".join(list(parq_exp1.export_stream([[77, 88]])))
    assert len(pl.read_parquet(io.BytesIO(pdata1))) == 2

    # 8. ParquetStreamExporter direct with empty rows and no columns
    parq_exp2 = ParquetStreamExporter(columns=None)
    pdata2 = b"".join(list(parq_exp2.export_stream([])))
    assert len(pl.read_parquet(io.BytesIO(pdata2))) == 0

    # 9. ExcelStreamExporter direct with columns=None and dict rows
    excel_exp = ExcelStreamExporter(columns=None)
    xdata = b"".join(list(excel_exp.export_stream([{"title": "test"}])))
    zf = zipfile.ZipFile(io.BytesIO(xdata))
    assert "xl/workbook.xml" in zf.namelist()
