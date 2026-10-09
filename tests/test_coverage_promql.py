"""Mock tests for the shared PromQL plumbing and the Prometheus/VictoriaMetrics connectors."""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from query_builder.connectors import _promql as pq
from query_builder.connectors import prometheus as prom
from query_builder.connectors import victoriametrics as vm
from query_builder.connectors.base import (
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)

# ----------------------------------------------------------------- build_request


def test_build_request_wraps_expressions_and_forwards_read_paths() -> None:
    assert pq.build_request("up{job='a'};") == (
        "/api/v1/query",
        [("query", "up{job='a'}")],
    )
    path, params = pq.build_request("/api/v1/query_range?query=up&step=15&empty=")
    assert path == "/api/v1/query_range"
    assert params == [("query", "up"), ("step", "15"), ("empty", "")]
    assert (
        pq.build_request("/prometheus/api/v1/labels")[0] == "/prometheus/api/v1/labels"
    )
    assert pq.build_request("/api/v1/label/job/values")[0] == "/api/v1/label/job/values"
    assert pq.build_request("/-/ready") == ("/-/ready", [])
    # a scheme-relative host is dropped: only the path is ever sent to the configured base URL
    assert pq.build_request("//evil.example/api/v1/query")[0] == "/api/v1/query"


@pytest.mark.parametrize(
    "stmt",
    [
        "",
        "   ;  ",
        "/api/v1/admin/tsdb/delete_series?match[]={__name__=~'.+'}",
        "/api/v1/admin/tsdb/snapshot",
        "/-/quit",
        "/-/reload",
        "/api/v1/write",
        "/api/v1/query/../admin/tsdb/clean_tombstones",
    ],
)
def test_build_request_refuses_non_read_endpoints(stmt: str) -> None:
    with pytest.raises(pq.PromQLRequestError):
        pq.build_request(stmt)


# ---------------------------------------------------------------- shape_response


def test_num_converts_or_keeps() -> None:
    assert pq._num("1.5") == 1.5
    assert pq._num("NaN") != pq._num("NaN")  # float nan
    assert pq._num("abc") == "abc"
    assert pq._num(None) is None


def test_shape_response_result_types() -> None:
    vector = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"job": "a", "i": "1"}, "value": [10, "2"]},
                {"metric": {"job": "b"}, "value": [11, "x"]},
                {"metric": {}},
            ],
        },
    }
    desc, rows = pq.shape_response("/api/v1/query", vector)
    assert desc == [("i",), ("job",), ("timestamp",), ("value",)]
    assert rows == [["1", "a", 10, 2.0], [None, "b", 11, "x"], [None, None, None, None]]
    matrix = {
        "data": {
            "resultType": "matrix",
            "result": [{"metric": {"job": "a"}, "values": [[1, "1"], [2, "2"]]}],
        }
    }
    desc, rows = pq.shape_response("/api/v1/query_range", matrix)
    assert desc == [("job",), ("timestamp",), ("value",)]
    assert rows == [["a", 1, 1.0], ["a", 2, 2.0]]
    scalar = {"status": "success", "data": {"resultType": "scalar", "result": [5, "7"]}}
    assert pq.shape_response("/api/v1/query", scalar) == (
        [("timestamp",), ("value",)],
        [[5, 7.0]],
    )
    string = {"data": {"resultType": "string", "result": [5, "hello"]}}
    assert pq.shape_response("/api/v1/query", string)[1] == [[5, "hello"]]


def test_shape_response_lists_dicts_and_scalars() -> None:
    series = {"data": [{"__name__": "up", "job": "a"}, {"__name__": "up", "i": "1"}]}
    desc, rows = pq.shape_response("/api/v1/series", series)
    assert desc == [("__name__",), ("i",), ("job",)]
    assert rows == [["up", None, "a"], ["up", "1", None]]
    assert pq.shape_response("/api/v1/labels", {"data": ["a", "b"]}) == (
        [("label",)],
        [["a"], ["b"]],
    )
    assert pq.shape_response("/api/v1/label/job/values", {"data": ["x"]}) == (
        [("value",)],
        [["x"]],
    )
    assert pq.shape_response("/api/v1/metadata", {"data": {"up": [1]}}) == (
        [("data",)],
        [[json.dumps({"up": [1]})]],
    )
    assert pq.shape_response("/x", {"status": "success", "data": 5}) == (
        [("data",)],
        [[5]],
    )
    assert pq.shape_response("/x", {"data": []}) == ([("value",)], [])


def test_shape_response_errors() -> None:
    with pytest.raises(pq.PromQLRequestError, match="bad_data: parse error"):
        pq.shape_response(
            "/api/v1/query",
            {"status": "error", "errorType": "bad_data", "error": "parse error"},
        )
    with pytest.raises(pq.PromQLRequestError, match="error: boom"):
        pq.shape_response("/x", "boom")


# ----------------------------------------------------------------- http plumbing


def test_is_http_client_by_module() -> None:
    assert pq.is_http_client(type("C", (), {"__module__": "httpx._client"})())
    assert pq.is_http_client(pq.RequestsBase.__new__(pq.RequestsBase))
    assert not pq.is_http_client(MagicMock())


def test_requests_base_get_and_close() -> None:
    session = MagicMock()
    fake_requests = MagicMock()
    fake_requests.Session.return_value = session
    with patch.dict(sys.modules, {"requests": fake_requests}):
        base = pq.RequestsBase("http://h:9090/", timeout=5, verify=False)
    assert base.base_url == "http://h:9090" and session.verify is False
    base.get("/api/v1/query", params=[("query", "up")])
    session.get.assert_called_once_with(
        "http://h:9090/api/v1/query", params=[("query", "up")], timeout=5
    )
    base.close()
    session.close.assert_called_once()


def _res(body: Any, status: int = 200, bad_json: bool = False) -> Any:
    res = MagicMock()
    res.status_code = status
    if bad_json:
        res.json.side_effect = ValueError("no json")
    else:
        res.json.return_value = body
    return res


def test_check_http_status_health_and_bodies() -> None:
    ok = {"status": "success", "data": []}
    assert pq._check(_res(ok), "/api/v1/query") == ok
    assert pq._check(_res(None, bad_json=True), "/api/v1/query") == {
        "status": "success",
        "data": [],
    }
    assert pq._check(_res(None, bad_json=True), "/-/ready") == {
        "status": "success",
        "data": {"ok": True},
    }
    with pytest.raises(pq.PromQLRequestError, match="HTTP 400.*bad query"):
        pq._check(_res({"error": "bad query"}, 400), "/api/v1/query")
    with pytest.raises(pq.PromQLRequestError, match="request failed"):
        pq._check(_res(None, 503, bad_json=True), "/api/v1/query")
    with pytest.raises(pq.PromQLRequestError, match="request failed"):
        pq._check(_res(["not a dict"], 500), "/api/v1/query")


def test_prom_sync_and_async_adapters_forward_params() -> None:
    conn = MagicMock()
    conn.get.return_value = _res({"status": "success", "data": ["a"]})
    desc, rows = pq.PromSync(conn).request("/api/v1/labels")
    conn.get.assert_called_once_with("/api/v1/labels", params=[])
    assert (desc, rows) == ([("label",)], [["a"]])

    async def get(path: str, params: Any = None) -> Any:
        return _res({"status": "success", "data": ["z"]})

    aconn = SimpleNamespace(get=get)
    assert asyncio.run(pq.PromAsync(aconn).request("/api/v1/labels"))[1] == [["z"]]
    with pytest.raises(pq.PromQLRequestError):
        pq.PromSync(conn).request("/api/v1/admin/tsdb/delete_series")


def _plan_answers(plan: Any, answers: dict[str, Any]) -> Any:
    request = next(plan)
    try:
        while True:
            sql = request[1]["sql"]
            value = answers[sql]
            request = (
                plan.throw(value) if isinstance(value, Exception) else plan.send(value)
            )
    except StopIteration as done:
        return done.value


def test_introspect_plan_metadata_labels_and_unsupported_metadata() -> None:
    meta = json.dumps({"up": [{"type": "gauge", "help": "alive"}], "x": []})
    answers = {
        "/api/v1/label/__name__/values": ([("value",)], [["up"], ["x"]]),
        "/api/v1/metadata": ([("data",)], [[meta]]),
        "/api/v1/labels?match[]=up": ([("label",)], [["__name__"], ["job"]]),
        "/api/v1/labels?match[]=x": ([("label",)], []),
    }
    raw = _plan_answers(pq.promql_introspect_plan(), answers)
    up = {c["name"]: c for c in raw["tables"]["up"]["columns"]}
    assert set(up) == {"timestamp", "value", "job"}
    assert raw["tables"]["up"]["comment"] == "gauge: alive"
    assert raw["tables"]["x"]["comment"] is None
    # servers without /metadata still introspect
    answers["/api/v1/metadata"] = pq.PromQLRequestError("404")
    raw2 = _plan_answers(pq.promql_introspect_plan(), answers)
    assert (
        set(raw2["tables"]) == {"up", "x"} and raw2["tables"]["up"]["comment"] is None
    )
    answers["/api/v1/metadata"] = ([("data",)], [])
    raw3 = _plan_answers(pq.promql_introspect_plan(max_metrics=1), answers)
    assert set(raw3["tables"]) == {"up"}


# ---------------------------------------------------------- connector variations


class _HttpxLike:
    """Looks like an httpx client to ``is_http_client``."""

    __module__ = "httpx"

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.routes = routes or {}
        self.requested: list[str] = []

    def get(self, path: str, params: Any = None) -> Any:
        self.requested.append(path)
        value = self.routes.get(path, {"status": "success", "data": []})
        if isinstance(value, Exception):
            raise value
        return _res(value)


class _AsyncHttpxLike(_HttpxLike):
    __module__ = "httpx"

    async def get(self, path: str, params: Any = None) -> Any:  # type: ignore[override]
        return super().get(path, params)

    async def aclose(self) -> None:
        return None


@pytest.mark.parametrize("module", [prom, vm])
def test_sync_introspection_over_http_wraps_failures(module: Any) -> None:
    cls = (
        module.PrometheusConnector
        if module is prom
        else module.VictoriaMetricsConnector
    )
    good = _HttpxLike(
        {
            "/api/v1/label/__name__/values": {"status": "success", "data": ["up"]},
            "/api/v1/labels?match[]=up": {"status": "success", "data": ["job"]},
        }
    )
    snap = cls(connection=good).introspect_schema()
    assert "up" in snap["tables"]
    bad = _HttpxLike({"/api/v1/label/__name__/values": RuntimeError("conn refused")})
    with pytest.raises(IntrospectionError, match="conn refused"):
        cls(connection=bad).introspect_schema()


@pytest.mark.parametrize("module", [prom, vm])
def test_async_introspection_over_http_wraps_failures(module: Any) -> None:
    cls = (
        module.AsyncPrometheusConnector
        if module is prom
        else module.AsyncVictoriaMetricsConnector
    )
    bad = _AsyncHttpxLike({"/api/v1/label/__name__/values": RuntimeError("down")})
    with pytest.raises(IntrospectionError, match="down"):
        asyncio.run(cls(connection=bad).introspect_schema())


def test_prometheus_connect_driver_selection() -> None:
    httpx = MagicMock()
    with patch.dict(sys.modules, {"httpx": httpx}):
        conn = prom.PrometheusConnector(url="http://p:9090", timeout=3)
        assert conn.connect() is httpx.Client.return_value
        httpx.Client.assert_called_once_with(base_url="http://p:9090", timeout=3)
    no_httpx = {"httpx": None}
    requests_mod = MagicMock()
    with patch.dict(sys.modules, {**no_httpx, "requests": requests_mod}):
        got = prom.PrometheusConnector(url="http://p:9090").connect()
    assert isinstance(got, pq.RequestsBase) and got.base_url == "http://p:9090"
    client_mod = MagicMock()
    with patch.dict(
        sys.modules, {**no_httpx, "requests": None, "prometheus_api_client": client_mod}
    ):
        assert (
            prom.PrometheusConnector().connect()
            is client_mod.PrometheusConnect.return_value
        )
    bare = SimpleNamespace()
    with patch.dict(
        sys.modules, {**no_httpx, "requests": None, "prometheus_api_client": bare}
    ):
        assert prom.PrometheusConnector().connect() is bare
    with (
        patch.dict(
            sys.modules, {**no_httpx, "requests": None, "prometheus_api_client": None}
        ),
        pytest.raises(DriverNotInstalledError),
    ):
        prom.PrometheusConnector().connect()
    broken = MagicMock()
    broken.Client.side_effect = RuntimeError("tls")
    with (
        patch.dict(sys.modules, {"httpx": broken}),
        pytest.raises(ConnectionFailedError),
    ):
        prom.PrometheusConnector().connect()


def test_victoriametrics_connect_driver_selection() -> None:
    httpx = MagicMock()
    with patch.dict(sys.modules, {"httpx": httpx, "requests": None}):
        assert vm.VictoriaMetricsConnector().connect() is httpx.Client.return_value
    session_only = SimpleNamespace(Session=MagicMock())
    with patch.dict(sys.modules, {"httpx": None, "requests": session_only}):
        assert isinstance(vm.VictoriaMetricsConnector().connect(), pq.RequestsBase)
    with (
        patch.dict(sys.modules, {"httpx": None, "requests": None}),
        pytest.raises(DriverNotInstalledError),
    ):
        vm.VictoriaMetricsConnector().connect()
