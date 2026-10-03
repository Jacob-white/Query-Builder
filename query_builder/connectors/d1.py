"""
Cloudflare D1 Serverless Edge SQL Database Connector.
======================================================
Provides SQLite-dialect execution via Cloudflare D1 REST API and schema introspection.
"""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_sqlite


class _D1Cursor:
    """Minimal DB-API cursor interface wrapping Cloudflare D1 HTTP REST responses."""

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self.headers = headers
        self._rows: list[list[Any]] = []
        self.description: list[tuple[str, ...]] | None = None

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        import requests

        payload = {"sql": sql, "params": params or []}
        resp = requests.post(self.url, json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            msg = errors[0].get("message") if errors else "Unknown D1 error"
            raise RuntimeError(f"Cloudflare D1 query execution failed: {msg}")

        result_list = data.get("result") or []
        result = result_list[0] if result_list else {}
        results_rows = result.get("results") or []
        if results_rows:
            keys = list(results_rows[0].keys())
            self.description = [(k,) for k in keys]
            self._rows = [[r.get(k) for k in keys] for r in results_rows]
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


class _D1Client:
    """Connection abstraction providing cursor creation for Cloudflare D1."""

    def __init__(self, account_id: str, database_id: str, api_token: str) -> None:
        self.url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/"
            f"d1/database/{database_id}/query"
        )
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def cursor(self) -> _D1Cursor:
        return _D1Cursor(self.url, self.headers)

    def close(self) -> None:
        pass


class D1Connector(BaseConnector):
    """Connector for Cloudflare D1 serverless edge SQL database."""

    dialect_name = "d1"

    def __init__(
        self,
        account_id: str = "",
        database_id: str = "",
        api_token: str = "",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.account_id = account_id
        self.database_id = database_id
        self.api_token = api_token

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection

        try:
            import requests  # noqa: F401
        except ImportError as err:
            raise DriverNotInstalledError(
                "requests is not installed. "
                "Install with: pip install 'query-builder-engine[d1]'"
            ) from err

        if not self.account_id or not self.database_id or not self.api_token:
            raise ConnectionFailedError(
                "Cloudflare D1 requires account_id, database_id, and api_token."
            )

        try:
            self._connection = _D1Client(
                self.account_id, self.database_id, self.api_token
            )
            return self._connection
        except Exception as exc:
            raise ConnectionFailedError(
                f"Failed to connect to Cloudflare D1: {exc}"
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        info = super().test_connection()
        info["engine_version"] = "Cloudflare D1 REST"
        info["database_id"] = self.database_id
        return info

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_sqlite(cur, filter_sensitive=filter_sensitive)
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Cloudflare D1 schema: {exc}"
                ) from exc


CloudflareD1Connector = D1Connector
