"""
Neo4j Graph Database Cypher-SQL Mapping Connector.
==================================================
Provides Neo4j connectivity via official neo4j Bolt driver, dual sync and async
execution protocols, Cypher-SQL translation, cursor adapters, and graph schema introspection.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_neo4j
from query_builder.connectors.registry import register_connector


def _has_attr(target: Any, attr: str) -> bool:
    if hasattr(target, "_mock_children"):
        if getattr(target, "_mock_methods", None) is not None:
            return hasattr(target, attr)
        return attr in target._mock_children
    return hasattr(target, attr)


class _Neo4jCursorAdapter:
    """Adapts Neo4j Driver / Session into a DB-API cursor interface."""

    def __init__(self, driver_or_session: Any) -> None:
        self.target = driver_or_session
        self.description: list[tuple[str]] | None = None
        self._rows: list[list[Any]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        clean = sql.strip().rstrip(";").strip()
        # Translate trivial SQL test queries or standard SELECT to Cypher if needed
        cypher_query = clean
        if clean.upper() in ("SELECT 1", "SELECT 1;", "SELECT 1 FROM DUAL"):
            cypher_query = "RETURN 1 AS val"
        elif clean.upper().startswith("SELECT") and not clean.upper().startswith(
            (
                "MATCH",
                "RETURN",
                "CALL",
                "SHOW",
                "CREATE",
                "MERGE",
                "DELETE",
                "SET",
                "UNWIND",
            )
        ):
            m = re.match(
                r"^SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<from>[^\s]+(?:\s+[^\s]+)?)"
                r"(?:\s+WHERE\s+(?P<where>.+?))?"
                r"(?:\s+ORDER\s+BY\s+(?P<order>.+?))?"
                r"(?:\s+SKIP\s+(?P<skip>[^\s]+))?"
                r"(?:\s+LIMIT\s+(?P<limit>[^\s]+))?"
                r"(?:\s+OFFSET\s+(?P<offset>[^\s]+))?$",
                clean,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                select_p = m.group("select").strip()
                from_p = m.group("from").strip()
                where_p = m.group("where")
                order_p = m.group("order")
                skip_p = m.group("skip") or m.group("offset")
                limit_p = m.group("limit")

                from_tokens = from_p.replace("`", "").replace('"', "").split()
                tbl = from_tokens[0]
                alias = from_tokens[1] if len(from_tokens) > 1 else tbl

                cypher = f"MATCH (`{alias}`:`{tbl}`)"
                if where_p:
                    cypher += f" WHERE {where_p.strip()}"
                if select_p.upper() in ("COUNT(*)", "COUNT(1)"):
                    cypher += " RETURN count(*)"
                elif select_p == f"`{alias}`.*" or select_p == "*":
                    cypher += f" RETURN `{alias}`"
                else:
                    cypher += f" RETURN {select_p}"
                if order_p:
                    cypher += f" ORDER BY {order_p.strip()}"
                if skip_p:
                    cypher += f" SKIP {skip_p.strip()}"
                if limit_p:
                    cypher += f" LIMIT {limit_p.strip()}"
                cypher_query = cypher

        if _has_attr(self.target, "cursor") and not _has_attr(self.target, "fetchall"):
            cur = self.target.cursor()
            try:
                if params:
                    cur.execute(clean, params)
                else:
                    cur.execute(clean)
                self.description = getattr(cur, "description", None)
                self._rows = list(cur.fetchall()) if hasattr(cur, "fetchall") else []
            finally:
                with contextlib.suppress(Exception):
                    cur.close()
        elif _has_attr(self.target, "execute") or _has_attr(self.target, "fetchall"):
            if params:
                self.target.execute(clean, params)
            else:
                self.target.execute(clean)
            self.description = getattr(self.target, "description", None)
            self._rows = (
                list(self.target.fetchall()) if hasattr(self.target, "fetchall") else []
            )
        elif _has_attr(self.target, "session") or _has_attr(self.target, "run"):
            created_session = False
            if _has_attr(self.target, "session"):
                session = self.target.session()
                created_session = True
            else:
                session = self.target
            try:
                parameters: dict[str, Any] = {}
                if params:
                    if isinstance(params, dict):
                        parameters = params
                    elif "$param" in cypher_query:
                        tokens = cypher_query.split("$param")
                        new_parts = [tokens[0]]
                        for i, token in enumerate(tokens[1:]):
                            p_name = f"p{i}"
                            parameters[p_name] = params[i] if i < len(params) else None
                            new_parts.append(f"${p_name}{token}")
                        cypher_query = "".join(new_parts)
                    elif "%s" in cypher_query or "?" in cypher_query:
                        p_idx = 0

                        def _replace_param(match: Any) -> str:
                            nonlocal p_idx
                            name = f"p{p_idx}"
                            parameters[name] = (
                                params[p_idx] if p_idx < len(params) else None
                            )
                            p_idx += 1
                            return f"${name}"

                        cypher_query = re.sub(r"%s|\?", _replace_param, cypher_query)
                    else:
                        parameters = {f"p{i}": p for i, p in enumerate(params)}
                result = session.run(cypher_query, parameters)
                keys = getattr(result, "keys", None)
                if callable(keys):
                    keys = keys()
                records = list(result)
                if keys:
                    self.description = [(str(k),) for k in keys]
                elif records and hasattr(records[0], "keys"):
                    self.description = [(str(k),) for k in records[0]]
                else:
                    self.description = [("val",)]

                self._rows = []
                for rec in records:
                    if hasattr(rec, "values") or isinstance(rec, dict):
                        self._rows.append(list(rec.values()))
                    elif isinstance(rec, (list, tuple)):
                        self._rows.append(list(rec))
                    else:
                        self._rows.append([rec])
            finally:
                if created_session and hasattr(session, "close"):
                    with contextlib.suppress(Exception):
                        session.close()
        else:
            self.description = None
            self._rows = []

    def fetchone(self) -> list[Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[list[Any]]:
        res = self._rows
        self._rows = []
        return res

    def close(self) -> None:
        pass


@register_connector("neo4j", aliases=["cypher", "neo4j_sql"])
class Neo4jConnector(BaseConnector):
    """Connector for Neo4j graph database via Cypher-SQL mapping."""

    dialect_name = "neo4j"

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        database: str = "neo4j",
        auth: tuple[str, str] | None = None,
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.uri = uri
        self.database = database
        self.auth = auth

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver_mod = None
        for mod_name in ("neo4j", "neo4j.v1", "py2neo"):
            try:
                driver_mod = __import__(mod_name, fromlist=["GraphDatabase"])
                break
            except ImportError:
                continue

        if driver_mod is None:
            raise DriverNotInstalledError(
                "'neo4j' is not installed. "
                "Install with: pip install 'query-builder-engine[neo4j]'"
            )

        try:
            gd = getattr(driver_mod, "GraphDatabase", None)
            if gd and hasattr(gd, "driver"):
                auth = self.auth or (
                    self.config.get("user", "neo4j"),
                    self.config.get("password", ""),
                )
                self._connection = gd.driver(self.uri, auth=auth)
            else:
                self._connection = driver_mod
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Neo4j graph database: {exc}"
            ) from exc

    @contextlib.contextmanager
    def get_cursor(self) -> Any:
        if self._cursor is not None:
            yield _Neo4jCursorAdapter(self._cursor)
            return

        conn = self.connect()
        yield _Neo4jCursorAdapter(conn)

    def apply_statement_timeout(self, cursor: Any, timeout_ms: int) -> None:
        pass

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        with self.get_cursor() as cur, contextlib.suppress(Exception):
            cur.execute("CALL dbms.components() YIELD name, versions;")
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if rows and len(rows) > 0 and len(rows[0]) > 0:
                if len(rows[0]) > 1 and rows[0][1]:
                    ver = (
                        rows[0][1][0]
                        if isinstance(rows[0][1], (list, tuple)) and len(rows[0][1]) > 0
                        else str(rows[0][1])
                    )
                    info["engine_version"] = f"Neo4j {ver}".strip()
                elif rows[0][0]:
                    info["engine_version"] = f"Neo4j {rows[0][0]}".strip()
        info["database"] = self.database
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            conn = getattr(cur, "target", cur)
            try:
                return introspect_neo4j(conn, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Neo4j database '{self.database}': {exc}"
                ) from exc


@register_connector("async_neo4j", aliases=["async_cypher"])
class AsyncNeo4jConnector(AsyncBaseConnector):
    """Asynchronous connector for Neo4j graph database."""

    dialect_name = "neo4j"

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        database: str = "neo4j",
        auth: tuple[str, str] | None = None,
        connection: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, **config)
        self.uri = uri
        self.database = database
        self.auth = auth

    async def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        driver_mod = None
        for mod_name in ("neo4j", "neo4j.v1"):
            try:
                driver_mod = __import__(
                    mod_name, fromlist=["AsyncGraphDatabase", "GraphDatabase"]
                )
                break
            except ImportError:
                continue

        if driver_mod is None:
            raise DriverNotInstalledError(
                "'neo4j' is not installed. "
                "Install with: pip install 'query-builder-engine[neo4j]'"
            )

        try:
            agd = getattr(driver_mod, "AsyncGraphDatabase", None)
            gd = getattr(driver_mod, "GraphDatabase", None)
            target_cls = agd or gd
            auth = self.auth or (
                self.config.get("user", "neo4j"),
                self.config.get("password", ""),
            )
            if target_cls and hasattr(target_cls, "driver"):
                self._connection = target_cls.driver(self.uri, auth=auth)
            else:
                self._connection = driver_mod
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect asynchronously to Neo4j: {exc}"
            ) from exc

    async def execute_raw(
        self, sql: str, params: list[Any] | None = None
    ) -> tuple[list[str], list[dict[str, Any]], float]:
        conn = await self.connect()
        start = time.perf_counter()
        adapter = _Neo4jCursorAdapter(conn)
        try:
            adapter.execute(sql, params)
            desc = adapter.description or []
            col_names = [col[0] for col in desc]
            rows = adapter.fetchall() or []
            dict_rows = [dict(zip(col_names, r, strict=False)) for r in rows]
            latency_ms = (time.perf_counter() - start) * 1000.0
            return col_names, dict_rows, latency_ms
        finally:
            adapter.close()

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        conn = await self.connect()
        try:
            return introspect_neo4j(conn, filter_sensitive=filter_sensitive)
        except Exception as exc:
            raise IntrospectionError(
                f"Failed to introspect Neo4j database '{self.database}': {exc}"
            ) from exc
