"""Render a compiled query with its values written in, so it can be pasted into a SQL window and run.

``QueryCompiler.compile`` always returns SQL with bind placeholders and a separate parameter list; that is what keeps a
value from ever being read as SQL, and nothing here changes it. This module produces a second rendering for a *person*:
the same statement with each placeholder replaced by the value as a SQL literal. Execute the bound form; show or download
this one.

It is deliberately strict. A placeholder is replaced only where it is a placeholder, never inside a quoted identifier, a
string literal or a comment, and the number of placeholders must equal the number of values. Anything that does not line
up, or a dialect whose placeholders are not positional (``$param``, ``@param``), gives ``None`` rather than a wrong
statement.
"""

from __future__ import annotations

import datetime
import decimal
import math
from collections.abc import Sequence
from typing import Any

#: Dialects whose string literals treat a backslash as an escape character. A backslash in a value must be doubled there
#: to stay one backslash; everywhere else it is an ordinary character and doubling it would change the value.
BACKSLASH_ESCAPE_DIALECTS = frozenset(
    {
        "mysql",
        "mariadb",
        "tidb",
        "singlestore",
        "doris",
        "apache_doris",
        "pydoris",
        "starrocks",
        "oceanbase",
        "clickhouse",
        "clickhouse_native",
        "clickhouse_tcp",
        "bigquery",
        "snowflake",
        "databricks",
        "spark",
        "spark_sql",
        "sparksql",
        "pyspark",
        "hive",
        "apache_hive",
        "pyhive",
    }
)

#: Placeholder styles that stand for "the next value" and so can be replaced in order.
POSITIONAL_PLACEHOLDERS = ("%s", "?")


def sql_literal(value: Any, *, backslash_escapes: bool = False) -> str:
    """One value as a SQL literal: numbers as they are, booleans TRUE/FALSE, None NULL, the rest a quoted string."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return "NULL" if math.isnan(value) or math.isinf(value) else repr(value)
    if isinstance(value, (int, decimal.Decimal)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        value = value.isoformat()
    text = str(value).replace("\x00", "")
    if backslash_escapes:
        text = text.replace("\\", "\\\\")
    return "'" + text.replace("'", "''") + "'"


def _skip_quoted(sql: str, start: int) -> int:
    """Index just past the quoted run (string literal or quoted identifier) that opens at ``start``."""
    quote = sql[start]
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == quote:
            if (
                i + 1 < n and sql[i + 1] == quote
            ):  # a doubled quote is a quote inside the run
                i += 2
                continue
            return i + 1
        i += 1
    return n


def inline_params(
    sql: str,
    params: Sequence[Any],
    *,
    placeholder: str = "%s",
    backslash_escapes: bool = False,
) -> str | None:
    """``sql`` with each ``placeholder`` replaced by the matching value, or None when that cannot be done correctly.

    ``placeholder`` is the dialect's bind marker. Only the positional ones (``%s``, ``?``) are supported. A value that
    contains the marker is not substituted again, and a marker inside quotes or a comment is left alone.
    """
    if placeholder not in POSITIONAL_PLACEHOLDERS:
        return None
    values = list(params)
    out: list[str] = []
    used = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in "'\"`":
            end = _skip_quoted(sql, i)
            out.append(sql[i:end])
            i = end
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            out.append(sql[i:end])
            i = end
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(sql[i:end])
            i = end
        elif sql.startswith(placeholder, i):
            if used >= len(values):
                return None
            out.append(sql_literal(values[used], backslash_escapes=backslash_escapes))
            used += 1
            i += len(placeholder)
        elif placeholder == "%s" and sql.startswith(
            "%%", i
        ):  # a driver-style escaped percent sign
            out.append("%")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out) if used == len(values) else None


__all__ = [
    "BACKSLASH_ESCAPE_DIALECTS",
    "POSITIONAL_PLACEHOLDERS",
    "inline_params",
    "sql_literal",
]
