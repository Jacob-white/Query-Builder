"""
Multi-Format Tabular Data Export Engine.
=========================================
Serializes query results into CSV, JSON, Parquet, and Excel (.xlsx) formats.
Excel export is zero-dependency OpenXML packaging via Python standard library.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from query_builder.models import QueryResult


class ExportError(Exception):
    """Raised when data export fails or format is unsupported."""


SUPPORTED_FORMATS: set[str] = {"csv", "json", "parquet", "excel", "xlsx"}

MIME_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "parquet": "application/vnd.apache.parquet",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "json": "json",
    "parquet": "parquet",
    "excel": "xlsx",
    "xlsx": "xlsx",
}


def _col_letter(col_idx: int) -> str:
    """Converts 0-based column index to Excel column letter (e.g. 0 -> A, 26 -> AA)."""
    result: list[str] = []
    idx = col_idx + 1
    while idx > 0:
        idx, remainder = divmod(idx - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _xml_escape(val: str) -> str:
    """Escapes XML special characters in string values."""
    return (
        val.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _generate_xlsx(columns: list[str], rows: list[Any]) -> bytes:
    """Generates a valid OpenXML spreadsheet (.xlsx) without external dependencies."""
    buf = io.BytesIO()

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
        '  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
        "</Types>"
    )

    pkg_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\n'
        "</Relationships>"
    )

    wb_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>\n'
        "</Relationships>"
    )

    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        "  <sheets>\n"
        '    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>\n'
        "  </sheets>\n"
        "</workbook>"
    )

    row_xml_parts: list[str] = []
    current_row = 1

    if columns:
        header_cells: list[str] = []
        for c_idx, col in enumerate(columns):
            ref = f"{_col_letter(c_idx)}{current_row}"
            header_cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(str(col))}</t></is></c>'
            )
        row_xml_parts.append(f'<row r="{current_row}">{"".join(header_cells)}</row>')
        current_row += 1

    for row in rows:
        row_cells: list[str] = []
        if isinstance(row, dict):
            for c_idx, col in enumerate(columns):
                val = row.get(col)
                ref = f"{_col_letter(c_idx)}{current_row}"
                if val is None:
                    row_cells.append(f'<c r="{ref}"/>')
                elif isinstance(val, bool):
                    b_val = "1" if val else "0"
                    row_cells.append(f'<c r="{ref}" t="b"><v>{b_val}</v></c>')
                elif isinstance(val, (int, float)):
                    row_cells.append(f'<c r="{ref}"><v>{val}</v></c>')
                else:
                    s_val = _xml_escape(str(val))
                    row_cells.append(
                        f'<c r="{ref}" t="inlineStr"><is><t>{s_val}</t></is></c>'
                    )
        elif isinstance(row, (list, tuple)):
            for c_idx, val in enumerate(row):
                ref = f"{_col_letter(c_idx)}{current_row}"
                if val is None:
                    row_cells.append(f'<c r="{ref}"/>')
                elif isinstance(val, bool):
                    b_val = "1" if val else "0"
                    row_cells.append(f'<c r="{ref}" t="b"><v>{b_val}</v></c>')
                elif isinstance(val, (int, float)):
                    row_cells.append(f'<c r="{ref}"><v>{val}</v></c>')
                else:
                    s_val = _xml_escape(str(val))
                    row_cells.append(
                        f'<c r="{ref}" t="inlineStr"><is><t>{s_val}</t></is></c>'
                    )
        else:
            ref = f"A{current_row}"
            if row is None:
                row_cells.append(f'<c r="{ref}"/>')
            elif isinstance(row, bool):
                b_val = "1" if row else "0"
                row_cells.append(f'<c r="{ref}" t="b"><v>{b_val}</v></c>')
            elif isinstance(row, (int, float)):
                row_cells.append(f'<c r="{ref}"><v>{row}</v></c>')
            else:
                s_val = _xml_escape(str(row))
                row_cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{s_val}</t></is></c>'
                )

        row_xml_parts.append(f'<row r="{current_row}">{"".join(row_cells)}</row>')
        current_row += 1

    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
        f"  <sheetData>{''.join(row_xml_parts)}</sheetData>\n"
        "</worksheet>"
    )

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", pkg_rels_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1_xml)

    return buf.getvalue()


def export_dataset(
    data: QueryResult | dict[str, Any] | list[dict[str, Any]],
    format: str = "csv",
) -> tuple[bytes, str, str]:
    """Exports dataset to specified tabular format.

    Returns:
        tuple[bytes, str, str]: (payload_bytes, mime_type, file_extension)
    Raises:
        ExportError: If format is unsupported or data cannot be serialized.
    """
    if not isinstance(format, str):
        raise ExportError("Export format must be a string.")

    fmt = format.strip().lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ExportError(
            f"Unsupported export format '{format}'. Supported formats: {sorted(SUPPORTED_FORMATS)}"
        )

    rows: list[Any]
    columns: list[str]

    if isinstance(data, QueryResult):
        rows = data.rows
        columns = list(data.columns)
    elif isinstance(data, dict):
        if "rows" not in data:
            raise ExportError("Dictionary input must contain 'rows' key.")
        raw_rows = data["rows"]
        if not isinstance(raw_rows, list):
            raise ExportError("'rows' must be a list.")
        rows = raw_rows
        cols = data.get("columns")
        if cols is not None and isinstance(cols, list):
            columns = [str(c) for c in cols]
        elif rows and isinstance(rows[0], dict):
            columns = list(rows[0].keys())
        else:
            columns = []
    elif isinstance(data, list):
        rows = data
        if rows and isinstance(rows[0], dict):
            columns = list(rows[0].keys())
        else:
            columns = []
    else:
        raise ExportError(f"Unsupported data type for export: {type(data).__name__}")

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        if columns:
            writer.writerow(columns)
        for row in rows:
            if isinstance(row, dict):
                writer.writerow(
                    [
                        row.get(col, "") if row.get(col) is not None else ""
                        for col in columns
                    ]
                )
            elif isinstance(row, (list, tuple)):
                writer.writerow([val if val is not None else "" for val in row])
            else:
                writer.writerow([row if row is not None else ""])
        payload = buf.getvalue().encode("utf-8")
        return payload, MIME_TYPES["csv"], EXTENSIONS["csv"]

    if fmt == "json":
        json_str = json.dumps(rows, indent=2, default=str)
        return json_str.encode("utf-8"), MIME_TYPES["json"], EXTENSIONS["json"]

    if fmt == "parquet":
        import polars as pl

        pbuf = io.BytesIO()
        if rows:
            if all(isinstance(r, dict) for r in rows):
                df = pl.DataFrame(rows)
            elif columns:
                df = pl.DataFrame(rows, schema=columns, orient="row")
            else:
                df = pl.DataFrame(rows)
        elif columns:
            df = pl.DataFrame({col: [] for col in columns})
        else:
            df = pl.DataFrame()
        df.write_parquet(pbuf)
        return (
            pbuf.getvalue(),
            MIME_TYPES["parquet"],
            EXTENSIONS["parquet"],
        )

    # Excel / xlsx
    xlsx_bytes = _generate_xlsx(columns, rows)
    return xlsx_bytes, MIME_TYPES[fmt], EXTENSIONS[fmt]
