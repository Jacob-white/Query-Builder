"""
InfluxDB v3 / IOx Time-Series SQL Engine Connector.
===================================================
Provides InfluxDB 3.0 Apache Arrow Flight SQL connectivity,
time-series measurement querying, and schema introspection.
"""

from __future__ import annotations

import contextlib
import re
import urllib.request
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.registry import register_connector

_PLACEHOLDER = re.compile(r"%s")


class _InfluxCursorAdapter:
    """Adapts InfluxDBClient3 or PyArrow Flight SQL client into a DB-API cursor interface."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        if hasattr(self.client, "query"):
            if params and type(self.client).__module__.startswith("influxdb_client_3"):
                # InfluxDB 3 binds named parameters ($p0) through ``query_parameters``;
                # it has no positional ``%s`` style, and silently dropping them would run
                # the statement with unbound placeholders.
                counter = iter(range(len(params)))
                sql = _PLACEHOLDER.sub(lambda _m: f"$p{next(counter)}", sql)
                table_or_res = self.client.query(
                    sql,
                    query_parameters={f"p{i}": v for i, v in enumerate(params)},
                )
            else:
                table_or_res = self.client.query(sql)
            if hasattr(table_or_res, "column_names") and hasattr(
                table_or_res, "to_pylist"
            ):
                self.description = [(col,) for col in table_or_res.column_names]
                pylist = table_or_res.to_pylist()
                self._rows = [
                    [row.get(col) for col in table_or_res.column_names]
                    for row in pylist
                ]
            elif hasattr(table_or_res, "fetchall"):
                self.description = getattr(table_or_res, "description", None)
                self._rows = list(table_or_res.fetchall())
            elif isinstance(table_or_res, (list, tuple)):
                self.description = None
                self._rows = [
                    list(r.values())
                    if hasattr(r, "values")
                    else (list(r) if isinstance(r, (list, tuple)) else [r])
                    for r in table_or_res
                ]
            else:
                self.description = None
                self._rows = []
        elif hasattr(self.client, "execute"):
            if params:
                self.client.execute(sql, params)
            else:
                self.client.execute(sql)
            self.description = getattr(self.client, "description", None)
            if hasattr(self.client, "fetchall"):
                self._rows = list(self.client.fetchall())

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("influxdb", aliases=["iox", "influx"])
class InfluxDBConnector(BaseConnector):
    """Connector for InfluxDB v3 / IOx time-series SQL engine."""

    dialect_name = "influxdb"

    def __init__(
        self,
        host: str = "localhost",
        token: str | None = None,
        database: str = "default",
        connection: Any = None,
        cursor: Any = None,
        schema_name: str = "iox",
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host = host
        self.token = token
        self.database = database
        self.schema_name = schema_name
        self.config.setdefault("host", host)
        self.config.setdefault("database", database)
        self.config.setdefault("schema_name", schema_name)
        if token is not None:
            self.config.setdefault("token", token)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in (
            "influxdb_client_3",
            "influxdb3_python",
            "influxdb3_client",
            "flightsql",
            "pyarrow.flight",
        ):
            try:
                driver = __import__(mod_name, fromlist=["flight", "client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "Neither 'influxdb3-python' nor 'flightsql' is installed. "
                "Install with: pip install 'query-builder-engine[influxdb]'"
            )

        try:
            cfg = {
                k: v
                for k, v in self.config.items()
                if k not in ("host", "token", "database", "schema_name")
            }
            if hasattr(driver, "connect"):
                self._connection = driver.connect(
                    host=self.host,
                    token=self.token,
                    database=self.database,
                    **cfg,
                )
            elif hasattr(driver, "InfluxDBClient3"):
                client = driver.InfluxDBClient3(
                    host=self.host,
                    token=self.token,
                    database=self.database,
                    **cfg,
                )
                self._connection = client
            else:
                self._connection = driver
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to InfluxDB 3.0 at {self.host}: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield self._cursor
            return

        conn = self.connect()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
            try:
                yield cur
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        else:
            adapter = _InfluxCursorAdapter(conn)
            yield adapter

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = self._server_version()
        info["database"] = self.database
        return info

    def _server_version(self) -> str:
        """Server version from the ``/ping`` response header (falls back to the product name)."""
        base = self.host if "//" in self.host else f"http://{self.host}"
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/ping", timeout=5) as res:  # noqa: S310
                version = res.headers.get("x-influxdb-version")
        except Exception:  # noqa: BLE001 - version is informational
            version = None
        return f"InfluxDB {version}" if version else "InfluxDB 3.0 / IOx SQL Engine"

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur,
                    schema_name=self.schema_name,
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect InfluxDB schema for '{self.database}': {exc}"
                ) from exc


IOxConnector = InfluxDBConnector

__all__ = [
    "IOxConnector",
    "InfluxDBConnector",
    "_InfluxCursorAdapter",
]
