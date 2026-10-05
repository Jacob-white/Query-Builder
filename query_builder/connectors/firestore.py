"""
Google Cloud Firestore Document Database Connector.
===================================================
Provides Google Cloud Firestore connectivity via google-cloud-firestore,
dual sync and async execution protocols, and collection schema introspection.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_firestore
from query_builder.connectors.registry import register_connector


class _FirestoreCursorAdapter:
    """Adapts a Firestore Client into a standard DB-API cursor interface."""

    def __init__(self, connection: Any) -> None:
        self.conn = connection
        self.description: list[tuple[str, ...]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean_sql = sql.strip().rstrip(";").strip()
        if hasattr(self.conn, "cursor"):
            cur = self.conn.cursor()
            try:
                if params:
                    cur.execute(clean_sql, params)
                else:
                    cur.execute(clean_sql)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                if hasattr(cur, "close"):
                    cur.close()
        elif (
            clean_sql == "collections" or clean_sql.upper().startswith("SHOW")
        ) and hasattr(self.conn, "collections"):
            colls = self.conn.collections()
            self.description = [("collection_name",)]
            self._rows = [[getattr(c, "id", str(c))] for c in colls]
        elif hasattr(self.conn, "collection"):
            import re

            m = re.search(
                r"\b(?:FROM|INTO|UPDATE|TABLE)\s+[`\"\[]?([a-zA-Z0-9_.-]+)[`\"\]]?",
                clean_sql,
                re.IGNORECASE,
            )
            coll_name = m.group(1) if m else "users"
            try:
                coll_ref = self.conn.collection(coll_name)
                docs = (
                    list(coll_ref.limit(10).stream())
                    if hasattr(coll_ref, "limit")
                    else []
                )
                if docs:
                    first_dict = (
                        docs[0].to_dict() if hasattr(docs[0], "to_dict") else {}
                    )
                    keys = ["id"] + list(first_dict.keys())
                    self.description = [(k,) for k in keys]
                    rows = []
                    for d in docs:
                        dd = d.to_dict() if hasattr(d, "to_dict") else {}
                        rows.append(
                            [getattr(d, "id", "")] + [dd.get(k) for k in keys[1:]]
                        )
                    self._rows = rows
                else:
                    self.description = [("id",), ("data",)]
                    self._rows = []
            except Exception:  # noqa: BLE001
                self.description = [("id",), ("data",)]
                self._rows = []
        elif hasattr(self.conn, "execute"):
            res = (
                self.conn.execute(clean_sql, params)
                if params
                else self.conn.execute(clean_sql)
            )
            self.description = getattr(res, "description", None)
            if hasattr(res, "fetchall"):
                self._rows = list(res.fetchall())
            elif isinstance(res, (list, tuple)):
                self._rows = list(res)
            else:
                self._rows = []
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def fetchmany(self, size: int = 1) -> list[list[Any]]:
        if not self._rows:
            return []
        res = self._rows[:size]
        self._rows = self._rows[size:]
        return res

    def close(self) -> None:
        self._rows = []


@register_connector("firestore", aliases=["google_firestore", "gcp_firestore"])
class FirestoreConnector(BaseConnector):
    """Connector for Google Cloud Firestore document database."""

    dialect_name = "firestore"

    def __init__(
        self,
        project: str | None = None,
        database: str = "(default)",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.project = project
        self.database = database

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("google.cloud.firestore", "google.cloud.firestore_v1"):
            try:
                driver = __import__(mod_name, fromlist=["Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'google-cloud-firestore' is not installed. "
                "Install with: pip install 'query-builder-engine[firestore]'"
            )

        try:
            client_cls = getattr(driver, "Client", driver)
            self._connection = client_cls(
                project=self.project, database=self.database, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Google Cloud Firestore: {exc}"
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
            adapter = _FirestoreCursorAdapter(conn)
            try:
                yield adapter
            finally:
                adapter.close()

    def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = self.connect()
        if hasattr(conn, "collections"):
            list(conn.collections())
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Google Cloud Firestore",
            "latency_ms": round(latency_ms, 2),
        }

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_firestore(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Firestore schema: {exc}"
                ) from exc


@register_connector(
    "async_firestore", aliases=["async_google_firestore", "async_gcp_firestore"]
)
class AsyncFirestoreConnector(AsyncBaseConnector):
    """Asynchronous connector for Google Cloud Firestore."""

    dialect_name = "firestore"

    def __init__(
        self,
        project: str | None = None,
        database: str = "(default)",
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.project = project
        self.database = database

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver = None
        for mod_name in ("google.cloud.firestore", "google.cloud.firestore_v1"):
            try:
                driver = __import__(mod_name, fromlist=["AsyncClient", "Client"])
                break
            except ImportError:
                continue

        if driver is None:
            raise DriverNotInstalledError(
                "'google-cloud-firestore' is not installed. "
                "Install with: pip install 'query-builder-engine[firestore]'"
            )

        try:
            client_cls = getattr(
                driver, "AsyncClient", getattr(driver, "Client", driver)
            )
            self._connection = client_cls(
                project=self.project, database=self.database, **self.config
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Google Cloud Firestore: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        if hasattr(conn, "cursor"):
            cur = conn.cursor()
        else:
            cur = _FirestoreCursorAdapter(conn)

        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            desc = cur.description or []
            col_names = [col[0] for col in desc]
            rows = cur.fetchall() or []
            dict_rows = [dict(zip(col_names, r)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            if hasattr(cur, "close"):
                cur.close()

    async def test_connection(self) -> dict[str, Any]:
        start = time.perf_counter()
        conn = await self.connect()
        if hasattr(conn, "collections"):
            res = conn.collections()
            if hasattr(res, "__await__"):
                await res
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "healthy",
            "dialect": self.dialect_name,
            "engine_version": "Google Cloud Firestore",
            "latency_ms": round(latency_ms, 2),
        }

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        cur = (
            conn.cursor() if hasattr(conn, "cursor") else _FirestoreCursorAdapter(conn)
        )
        try:
            return introspect_firestore(cur, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Firestore schema: {exc}"
            ) from exc
        finally:
            if hasattr(cur, "close"):
                cur.close()
