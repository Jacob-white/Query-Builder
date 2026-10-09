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
from collections.abc import Iterable, Iterator
from typing import Any, Protocol

from query_builder.models import QueryResult


class ExportError(Exception):
    """Raised when data export fails or format is unsupported."""


SUPPORTED_FORMATS: set[str] = {
    "csv",
    "json",
    "parquet",
    "excel",
    "xlsx",
    "jsonl",
    "ndjson",
    "arrow",
}

SUPPORTED_STREAM_FORMATS: set[str] = SUPPORTED_FORMATS

MIME_TYPES: dict[str, str] = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "parquet": "application/vnd.apache.parquet",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "jsonl": "application/x-ndjson",
    "ndjson": "application/x-ndjson",
    "arrow": "application/vnd.apache.arrow.stream",
}

EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "json": "json",
    "parquet": "parquet",
    "excel": "xlsx",
    "xlsx": "xlsx",
    "jsonl": "jsonl",
    "ndjson": "jsonl",
    "arrow": "arrow",
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

    if fmt in ("jsonl", "ndjson"):
        lines = [json.dumps(r, default=str) for r in rows]
        payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        return payload, MIME_TYPES[fmt], EXTENSIONS[fmt]

    if fmt == "arrow":
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
        df.write_ipc_stream(pbuf)
        return (
            pbuf.getvalue(),
            MIME_TYPES["arrow"],
            EXTENSIONS["arrow"],
        )

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


# ==============================================================================
# Streaming Exporters with Memory-Budgeted Chunking
# ==============================================================================


class StreamExporter(Protocol):
    """Structural type shared by every streaming exporter."""

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]: ...


class CsvStreamExporter:
    """Streams tabular data as CSV byte chunks."""

    def __init__(
        self, columns: list[str] | None = None, chunk_size: int = 1000
    ) -> None:
        self.columns = columns
        self.chunk_size = max(1, chunk_size)

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]:
        cols = list(self.columns) if self.columns is not None else None
        header_emitted = False
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        count = 0

        for row in row_iterator:
            if cols is None and isinstance(row, dict):
                cols = list(row.keys())
            if not header_emitted and cols:
                writer.writerow(cols)
                header_emitted = True

            if isinstance(row, dict):
                row_cols = cols if cols is not None else list(row.keys())
                writer.writerow(
                    [row.get(c, "") if row.get(c) is not None else "" for c in row_cols]
                )
            elif isinstance(row, (list, tuple)):
                writer.writerow([val if val is not None else "" for val in row])
            else:
                writer.writerow([row if row is not None else ""])

            count += 1
            if count >= self.chunk_size:
                yield buf.getvalue().encode("utf-8")
                buf.seek(0)
                buf.truncate(0)
                count = 0

        if not header_emitted and cols:
            writer.writerow(cols)

        data = buf.getvalue().encode("utf-8")
        if data:
            yield data


class JsonlStreamExporter:
    """Streams rows as line-delimited JSON byte chunks."""

    def __init__(self, chunk_size: int = 1000) -> None:
        self.chunk_size = max(1, chunk_size)

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]:
        lines: list[str] = []
        for row in row_iterator:
            lines.append(json.dumps(row, default=str))
            if len(lines) >= self.chunk_size:
                yield ("\n".join(lines) + "\n").encode("utf-8")
                lines = []
        if lines:
            yield ("\n".join(lines) + "\n").encode("utf-8")


class JsonStreamExporter:
    """Streams rows as formatted JSON array byte chunks."""

    def __init__(self, chunk_size: int = 1000) -> None:
        self.chunk_size = max(1, chunk_size)

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]:
        yield b"[\n"
        first = True
        batch: list[str] = []
        for row in row_iterator:
            prefix = "  " if first else "  ,"
            first = False
            batch.append(prefix + json.dumps(row, default=str))
            if len(batch) >= self.chunk_size:
                yield ("\n".join(batch) + "\n").encode("utf-8")
                batch = []
        if batch:
            yield ("\n".join(batch) + "\n").encode("utf-8")
        yield b"]\n"


class ArrowStreamExporter:
    """Streams Apache Arrow IPC stream in byte chunks."""

    def __init__(
        self, columns: list[str] | None = None, chunk_size: int = 1000
    ) -> None:
        self.columns = columns
        self.chunk_size = max(1, chunk_size)

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]:
        import polars as pl

        cols = list(self.columns) if self.columns is not None else None
        rows = list(row_iterator)
        pbuf = io.BytesIO()
        if rows:
            if all(isinstance(r, dict) for r in rows):
                df = pl.DataFrame(rows)
            elif cols:
                df = pl.DataFrame(rows, schema=cols, orient="row")
            else:
                df = pl.DataFrame(rows)
        elif cols:
            df = pl.DataFrame({col: [] for col in cols})
        else:
            df = pl.DataFrame()

        df.write_ipc_stream(pbuf)
        data = pbuf.getvalue()
        chunk_bytes = max(4096, self.chunk_size * 64)
        for i in range(0, len(data), chunk_bytes):
            yield data[i : i + chunk_bytes]


class ParquetStreamExporter:
    """Streams Parquet format in byte chunks."""

    def __init__(
        self, columns: list[str] | None = None, chunk_size: int = 1000
    ) -> None:
        self.columns = columns
        self.chunk_size = max(1, chunk_size)

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]:
        import polars as pl

        cols = list(self.columns) if self.columns is not None else None
        rows = list(row_iterator)
        pbuf = io.BytesIO()
        if rows:
            if all(isinstance(r, dict) for r in rows):
                df = pl.DataFrame(rows)
            elif cols:
                df = pl.DataFrame(rows, schema=cols, orient="row")
            else:
                df = pl.DataFrame(rows)
        elif cols:
            df = pl.DataFrame({col: [] for col in cols})
        else:
            df = pl.DataFrame()

        df.write_parquet(pbuf)
        data = pbuf.getvalue()
        chunk_bytes = max(4096, self.chunk_size * 64)
        for i in range(0, len(data), chunk_bytes):
            yield data[i : i + chunk_bytes]


class ExcelStreamExporter:
    """Streams OpenXML Excel (.xlsx) file in byte chunks."""

    def __init__(
        self, columns: list[str] | None = None, chunk_size: int = 1000
    ) -> None:
        self.columns = columns
        self.chunk_size = max(1, chunk_size)

    def export_stream(self, row_iterator: Iterable[Any]) -> Iterator[bytes]:
        rows = list(row_iterator)
        cols = list(self.columns) if self.columns is not None else None
        if cols is None and rows and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
        xlsx_bytes = _generate_xlsx(cols or [], rows)
        chunk_bytes = max(4096, self.chunk_size * 64)
        for i in range(0, len(xlsx_bytes), chunk_bytes):
            yield xlsx_bytes[i : i + chunk_bytes]


def stream_export_dataset(
    data: Any,
    format: str = "csv",
    columns: list[str] | None = None,
    chunk_size: int = 1000,
) -> tuple[Iterator[bytes], str, str]:
    """Streams dataset export in chunks yielding bytes, along with (mime_type, file_extension).

    Returns:
        tuple[Iterator[bytes], str, str]: (chunk_iterator, mime_type, file_extension)
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

    resolved_cols = list(columns) if columns is not None else None
    row_iter: Iterable[Any]

    if isinstance(data, QueryResult):
        row_iter = data.rows
        resolved_cols = list(data.columns)
    elif isinstance(data, dict):
        if "rows" not in data:
            raise ExportError("Dictionary input must contain 'rows' key.")
        raw_rows = data["rows"]
        if not isinstance(raw_rows, list):
            raise ExportError("'rows' must be a list.")
        row_iter = raw_rows
        cols = data.get("columns")
        if cols is not None and isinstance(cols, list):
            resolved_cols = [str(c) for c in cols]
        elif raw_rows and isinstance(raw_rows[0], dict):
            resolved_cols = list(raw_rows[0].keys())
        else:
            resolved_cols = []
    elif isinstance(data, list):
        row_iter = data
        if resolved_cols is None:
            if data and isinstance(data[0], dict):
                resolved_cols = list(data[0].keys())
            else:
                resolved_cols = []
    elif hasattr(data, "__iter__"):
        row_iter = data
    else:
        raise ExportError(f"Unsupported data type for export: {type(data).__name__}")

    mime_type = MIME_TYPES[fmt]
    ext = EXTENSIONS[fmt]

    exporter: StreamExporter
    if fmt == "csv":
        exporter = CsvStreamExporter(columns=resolved_cols, chunk_size=chunk_size)
    elif fmt in ("jsonl", "ndjson"):
        exporter = JsonlStreamExporter(chunk_size=chunk_size)
    elif fmt == "json":
        exporter = JsonStreamExporter(chunk_size=chunk_size)
    elif fmt == "parquet":
        exporter = ParquetStreamExporter(columns=resolved_cols, chunk_size=chunk_size)
    elif fmt == "arrow":
        exporter = ArrowStreamExporter(columns=resolved_cols, chunk_size=chunk_size)
    else:  # excel, xlsx
        exporter = ExcelStreamExporter(columns=resolved_cols, chunk_size=chunk_size)

    return exporter.export_stream(row_iter), mime_type, ext
