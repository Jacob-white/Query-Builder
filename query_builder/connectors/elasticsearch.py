"""
Elasticsearch / OpenSearch SQL Search Connector.
================================================
Translates SQL query specifications to Elasticsearch /_sql REST API requests.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.schema import normalize_schema_snapshot

_MAX_PAGES = 1000


class ElasticsearchCursor:
    """
    Minimal DB-API style cursor over an ``elasticsearch`` client.

    The client exposes ``client.sql.query()`` (the ``/_sql`` endpoint), not
    ``cursor()``/``execute()``. Result pages (``cursor`` tokens) are followed so
    ``fetchall()`` returns every row.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._rows: list[Any] = []
        self._pos = 0
        self.description: list[tuple[Any, ...]] | None = None
        self.rowcount = -1

    def execute(self, sql: str, params: Any = None) -> ElasticsearchCursor:
        statement = sql.strip().rstrip(";").strip()
        kwargs: dict[str, Any] = {"query": statement, "format": "json"}
        if params:
            kwargs["params"] = list(params)
        result = self._client.sql.query(**kwargs)
        columns = [c.get("name", "") for c in result.get("columns", [])]
        rows = list(result.get("rows", []))
        token = result.get("cursor")
        pages = 0
        while token and pages < _MAX_PAGES:
            page = self._client.sql.query(cursor=token, format="json")
            rows.extend(page.get("rows", []))
            token = page.get("cursor")
            pages += 1
        if token:
            with contextlib.suppress(Exception):
                self._client.sql.clear_cursor(cursor=token)
        self.description = [(name, None) for name in columns]
        self._rows, self._pos = rows, 0
        self.rowcount = len(rows)
        return self

    def fetchall(self) -> list[Any]:
        rows, self._pos = self._rows[self._pos :], len(self._rows)
        return rows

    def fetchone(self) -> Any:
        if self._pos >= len(self._rows):
            return None
        self._pos += 1
        return self._rows[self._pos - 1]

    def close(self) -> None:
        self._rows = []


class ElasticsearchConnector(BaseConnector):
    """Connector for Elasticsearch and OpenSearch SQL endpoints."""

    dialect_name = "elasticsearch"

    def __init__(
        self,
        endpoint: str = "http://localhost:9200",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.endpoint = endpoint
        self.config.setdefault("endpoint", endpoint)
        self.config.setdefault("url", endpoint)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            from elasticsearch import Elasticsearch
        except ImportError as err:
            raise DriverNotInstalledError(
                "elasticsearch is not installed. Install with: pip install 'query-builder-engine[elasticsearch]'"
            ) from err

        try:
            cfg = {k: v for k, v in self.config.items() if k not in ("endpoint", "url")}
            self._connection = Elasticsearch(self.endpoint, **cfg)
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Elasticsearch at {self.endpoint}: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Iterator[Any]:
        """Yield a DB-API cursor; wraps elasticsearch clients (no cursor())."""
        if self._cursor is None:
            conn = self.connect()
            if not hasattr(conn, "cursor") and hasattr(conn, "sql"):
                yield ElasticsearchCursor(conn)
                return
        with super().get_cursor() as cur:
            yield cur

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Elasticsearch SQL"
        client = self._connection
        if client is not None and hasattr(client, "info"):
            with contextlib.suppress(Exception):
                number = client.info()["version"]["number"]
                if isinstance(number, str):
                    info["engine_version"] = f"Elasticsearch {number}"
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                cur.execute("SHOW TABLES")
                table_rows = cur.fetchall()
                tables_map: dict[str, dict[str, Any]] = {}

                for row in table_rows:
                    # SHOW TABLES rows are (catalog, name, type, kind); the first
                    # column is the cluster name, not the index.
                    t_name = str(row[1] if len(row) >= 4 else row[0])
                    if t_name.startswith("."):  # system / hidden indices
                        continue
                    cur.execute(f'DESCRIBE "{t_name}"')
                    col_rows = cur.fetchall()
                    cols = []
                    has_user = False
                    for c in col_rows:
                        col_name = str(c[0])
                        if col_name == "user_id":
                            has_user = True
                        cols.append(
                            {
                                "name": col_name,
                                "data_type": str(c[1]).lower(),
                                "is_nullable": True,
                                "is_primary": col_name == "id",
                                "comment": None,
                            }
                        )
                    tables_map[t_name] = {
                        "name": t_name,
                        "columns": cols,
                        "has_user_id": has_user,
                        "user_col": "user_id",
                        "comment": None,
                    }

                return normalize_schema_snapshot(
                    {"tables": tables_map, "foreign_keys": [], "relationships": []},
                    filter_sensitive=filter_sensitive,
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Elasticsearch indices: {exc}"
                ) from exc
