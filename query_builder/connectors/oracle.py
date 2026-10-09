"""
Oracle Database Connector.
==========================
Provides ANSI quoting, OFFSET-FETCH pagination, and user/all_tables schema introspection.

Oracle drivers (``oracledb`` / ``cx_Oracle``) bind positionally with ``:1, :2, ...`` while the
compiler emits ``%s``; every cursor the connector hands out translates the placeholders
(outside string literals, quoted identifiers and comments) before the statement reaches the
driver.
"""

from __future__ import annotations

import contextlib
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
)
from query_builder.connectors.introspection import introspect_oracle


def to_numbered_binds(sql: str) -> str:
    """Rewrite ``%s`` placeholders to Oracle ``:1, :2, ...`` binds.

    Single-quoted literals (``''`` escapes), double-quoted identifiers, ``--`` and ``/* */``
    comments are copied verbatim, so a literal ``'%s'`` or a column called ``"%s"`` is never
    rewritten.
    """
    if "%s" not in sql:
        return sql
    out: list[str] = []
    i, n, bind = 0, len(sql), 0
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(sql[i:j])
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(sql[i:j])
            i = j
        elif sql.startswith("%s", i):
            bind += 1
            out.append(f":{bind}")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


class _OracleCursor:
    """Cursor proxy translating ``%s`` placeholders to numbered binds."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(self, sql: str, params: Any = None) -> Any:
        if params:
            return self._cursor.execute(to_numbered_binds(sql), list(params))
        return self._cursor.execute(sql)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def __iter__(self) -> Any:
        return iter(self._cursor)


class OracleConnector(BaseConnector):
    """Connector for Oracle Database."""

    dialect_name = "oracle"

    def __init__(
        self,
        owner: str | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.owner = owner

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("oracledb", "cx_Oracle"):
            try:
                driver = __import__(mod_name)
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'oracledb' nor 'cx_Oracle' is installed. "
                "Install with: pip install 'query-builder-engine[oracle]'"
            )

        try:
            self._connection = driver.connect(**self.config)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Oracle: {exc}") from exc

    def get_cursor(self) -> Any:  # type: ignore[override]
        return _wrap_cursor_context(super().get_cursor())

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        # python-oracledb: per-round-trip call timeout (milliseconds) on the connection
        conn = getattr(cursor, "connection", None) or self._connection
        with contextlib.suppress(
            Exception
        ):  # driver without call_timeout (old cx_Oracle)
            conn.call_timeout = int(timeout_ms)

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur:
            cur.execute("SELECT 1 FROM DUAL")
            cur.fetchone()
        version = getattr(self._connection, "version", None)
        info["engine_version"] = (
            f"Oracle Database {version}"
            if isinstance(version, str)
            else "Oracle Database"
        )
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            return introspect_oracle(
                cur, owner=self.owner, filter_sensitive=filter_sensitive
            )


class _wrap_cursor_context:  # noqa: N801 - context manager adapter
    """Wraps the base ``get_cursor()`` context manager so the yielded cursor translates binds."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __enter__(self) -> Any:
        cur = self._inner.__enter__()
        # an injected cursor (tests) or a mock is passed through untouched
        return _OracleCursor(cur) if hasattr(cur, "execute") else cur

    def __exit__(self, *exc: Any) -> Any:
        return self._inner.__exit__(*exc)
