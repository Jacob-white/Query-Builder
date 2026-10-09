"""
Shared HTTP/PromQL plumbing for the Prometheus and VictoriaMetrics connectors.

Both engines speak the Prometheus HTTP API. A statement is either

* a PromQL / MetricsQL expression (run as an instant query), or
* a path starting with ``/`` such as ``/api/v1/query_range?query=up&start=..&end=..&step=15``.

Only an allow-list of READ endpoints can be requested: the same servers expose
``/api/v1/admin/tsdb/delete_series`` and ``/-/quit`` on the same port, and a connector that
promises read-only access must never forward those.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from query_builder.connectors.base import QueryExecutionError

_READ_PATHS = re.compile(
    r"^(?:/prometheus)?/api/v1/(?:"
    r"query|query_range|series|labels|label/[^/]+/values|metadata|targets|"
    r"targets/metadata|rules|alerts|alertmanagers|query_exemplars|export|series/count|"
    r"status/(?:buildinfo|config|flags|runtimeinfo|tsdb|top_queries|active_queries)"
    r")$"
)
_HEALTH_PATHS = {"/-/healthy", "/-/ready", "/health"}


class PromQLRequestError(QueryExecutionError):
    """The statement is not a read request the connector is willing to forward."""


def build_request(sql: str) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(path, query parameters)`` for a statement, rejecting non-read endpoints."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise PromQLRequestError("empty statement")
    if text.startswith("/"):
        parts = urlsplit(text)
        path = parts.path
        if not (_READ_PATHS.match(path) or path in _HEALTH_PATHS):
            raise PromQLRequestError(
                f"endpoint {path!r} is not an allowed read endpoint of the metrics API"
            )
        return path, parse_qsl(parts.query, keep_blank_values=True)
    return "/api/v1/query", [("query", text)]


def _num(value: Any) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def shape_response(path: str, payload: Any) -> tuple[list[tuple[str]], list[list[Any]]]:
    """Turn a Prometheus API JSON body into a DB-API ``description`` and rows."""
    if not isinstance(payload, dict) or payload.get("status") not in (None, "success"):
        err = payload.get("error") if isinstance(payload, dict) else payload
        kind = (
            payload.get("errorType", "error") if isinstance(payload, dict) else "error"
        )
        raise PromQLRequestError(f"{kind}: {err}")
    data = payload.get("data", payload)
    if isinstance(data, dict) and "resultType" in data:
        rtype, result = data["resultType"], data.get("result", [])
        if rtype in ("scalar", "string"):
            return [("timestamp",), ("value",)], [[result[0], _num(result[1])]]
        samples: list[tuple[dict[str, str], Any, Any]] = []
        for series in result:
            labels = series.get("metric", {})
            if rtype == "matrix":
                samples.extend((labels, ts, v) for ts, v in series.get("values", []))
            else:
                ts, v = series.get("value", [None, None])
                samples.append((labels, ts, v))
        names = sorted({k for labels, _, _ in samples for k in labels})
        rows = [
            [labels.get(n) for n in names] + [ts, _num(v)] for labels, ts, v in samples
        ]
        return [(n,) for n in names] + [("timestamp",), ("value",)], rows
    if isinstance(data, list):
        if data and isinstance(data[0], dict):  # /series
            names = sorted({k for d in data for k in d})
            return [(n,) for n in names], [[d.get(n) for n in names] for d in data]
        column = "label" if path.endswith("/labels") else "value"
        return [(column,)], [[item] for item in data]
    if isinstance(data, dict):
        return [("data",)], [[json.dumps(data, default=str)]]
    return [("data",)], [[data]]


def is_http_client(conn: Any) -> bool:
    """A genuine httpx client (or the requests-backed fallback below)."""
    return type(conn).__module__.split(".")[0] in ("httpx", "query_builder")


class RequestsBase:
    """Minimal ``get(path, params)`` over ``requests`` with a base URL (httpx-like)."""

    def __init__(self, base_url: str, timeout: float = 30.0, **kwargs: Any) -> None:
        import requests

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        for key, value in kwargs.items():
            setattr(self.session, key, value)

    def get(self, path: str, params: Any = None) -> Any:
        return self.session.get(
            self.base_url + path, params=params, timeout=self.timeout
        )

    def close(self) -> None:
        self.session.close()


def _check(res: Any, path: str) -> Any:
    try:
        body = res.json()
    except ValueError:
        body = None
    status = getattr(res, "status_code", 200)
    if status >= 400:
        detail = ""
        if isinstance(body, dict):
            detail = str(body.get("error", ""))
        raise PromQLRequestError(
            f"HTTP {status} from {path}: {detail or 'request failed'}"
        )
    if path in _HEALTH_PATHS:
        return {"status": "success", "data": {"ok": True}}
    return body if body is not None else {"status": "success", "data": []}


class PromSync:
    """Adapter exposing ``request(sql)`` over a sync HTTP client (used with ``drive_sync``)."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def request(self, sql: str) -> tuple[list[tuple[str]], list[list[Any]]]:
        path, params = build_request(sql)
        res = self.conn.get(path, params=params)
        return shape_response(path, _check(res, path))


class PromAsync:
    """Same as :class:`PromSync` for ``httpx.AsyncClient``."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    async def request(self, sql: str) -> tuple[list[tuple[str]], list[list[Any]]]:
        path, params = build_request(sql)
        res = await self.conn.get(path, params=params)
        return shape_response(path, _check(res, path))


def promql_introspect_plan(max_metrics: int = 500) -> Any:
    """Metric catalogue: one table per metric, label names as columns (plus timestamp, value)."""
    _, rows = yield ("request", {"sql": "/api/v1/label/__name__/values"})
    metrics = [str(r[0]) for r in rows][:max_metrics]
    try:
        _, meta_rows = yield ("request", {"sql": "/api/v1/metadata"})
        meta = json.loads(meta_rows[0][0]) if meta_rows else {}
    except QueryExecutionError:  # not every compatible server implements /metadata
        meta = {}
    tables: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        _, label_rows = yield (
            "request",
            {"sql": f"/api/v1/labels?match[]={metric}"},
        )
        labels = [str(r[0]) for r in label_rows if r[0] != "__name__"]
        info = meta.get(metric)
        comment = None
        if isinstance(info, list) and info:
            comment = f"{info[0].get('type', '')}: {info[0].get('help', '')}".strip(
                ": "
            )
        cols = [
            {
                "name": "timestamp",
                "data_type": "timestamp",
                "is_nullable": False,
                "is_primary": True,
                "comment": None,
            },
            {
                "name": "value",
                "data_type": "double",
                "is_nullable": False,
                "is_primary": False,
                "comment": None,
            },
        ]
        cols.extend(
            {
                "name": lab,
                "data_type": "string",
                "is_nullable": True,
                "is_primary": False,
                "comment": "label",
            }
            for lab in labels
        )
        tables[metric] = {
            "name": metric,
            "columns": cols,
            "has_user_id": "user_id" in labels,
            "user_col": "user_id" if "user_id" in labels else None,
            "comment": comment,
        }
    return {"tables": tables, "foreign_keys": [], "relationships": []}


def version_plan() -> Any:
    _, rows = yield ("request", {"sql": "/api/v1/status/buildinfo"})
    return json.loads(rows[0][0]) if rows else {}


def version_text(name: str, info: Any) -> str:
    version = info.get("version") if isinstance(info, dict) else None
    return f"{name} {version}" if version else name
