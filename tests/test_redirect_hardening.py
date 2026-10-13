"""First-party HTTP code must never follow a redirect.

A redirect is followed AFTER ``validate_network_target`` passed, to an address nobody checked
(``302 Location: http://169.254.169.254/...``). Each scenario here puts a *canary* server behind a
redirecting one: a canary hit means the redirect was followed. Every case has a control with the
plain client (which follows redirects) so the scenario is known to be able to fail.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

requests = pytest.importorskip("requests")

from query_builder.connectors import influxdb  # noqa: E402
from query_builder.connectors._promql import (  # noqa: E402
    PromQLRequestError,
    RequestsBase,
    _check,
)
from query_builder.connectors.d1 import _D1Cursor  # noqa: E402


class Canary(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def _hit(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).hits.append(f"{self.command} {self.path}")
        body = json.dumps({"status": "success", "data": [], "success": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _hit  # noqa: N815

    def log_message(self, *args: Any) -> None:
        pass


def _serve(handler: type[http.server.BaseHTTPRequestHandler]) -> tuple[Any, int]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, int(srv.server_address[1])


@contextmanager
def redirecting_to_a_canary(status: int = 302) -> Iterator[tuple[str, list[str]]]:
    """Yields ``(url_of_redirecting_server, canary_hits)``."""
    canary_cls = type("C", (Canary,), {"hits": []})
    canary, canary_port = _serve(canary_cls)

    class Redirect(http.server.BaseHTTPRequestHandler):
        def _go(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(status)
            self.send_header("Location", f"http://127.0.0.1:{canary_port}/internal")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = _go  # noqa: N815

        def log_message(self, *args: Any) -> None:
            pass

    front, front_port = _serve(Redirect)
    try:
        yield f"http://127.0.0.1:{front_port}", canary_cls.hits
    finally:
        for srv in (front, canary):
            srv.shutdown()
            srv.server_close()


@contextmanager
def plain_server() -> Iterator[str]:
    srv, port = _serve(type("P", (Canary,), {"hits": []}))
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_control_a_plain_requests_client_follows_the_redirect(status: int) -> None:
    with redirecting_to_a_canary(status) as (url, hits):
        requests.get(url + "/x", timeout=5)
        assert hits, "the scenario must be able to reach the canary"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_prometheus_requests_adapter_does_not_follow_redirects(status: int) -> None:
    with redirecting_to_a_canary(status) as (url, hits):
        client = RequestsBase(url)
        res = client.get("/api/v1/query", params={"query": "up"})
        assert hits == []
        assert res.status_code == status
        with pytest.raises(PromQLRequestError, match="redirects are not followed"):
            _check(res, "/api/v1/query")
        client.close()


def test_prometheus_requests_adapter_still_works_without_a_redirect() -> None:
    with plain_server() as url:
        client = RequestsBase(url)
        res = client.get("/api/v1/query")
        assert _check(res, "/api/v1/query")["status"] == "success"
        client.close()


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_d1_does_not_follow_a_redirect_and_says_so(status: int) -> None:
    with redirecting_to_a_canary(status) as (url, hits):
        cursor = _D1Cursor(url + "/client/v4/query", {"Authorization": "Bearer x"})
        with pytest.raises(RuntimeError, match="redirected"):
            cursor.execute("select 1")
        assert hits == []  # the SQL payload never reached the redirect target


def test_d1_control_a_plain_post_would_have_followed() -> None:
    with redirecting_to_a_canary(307) as (url, hits):
        requests.post(url, json={"sql": "select 1"}, timeout=5)
        assert hits  # 307 keeps the method and body


def test_d1_still_parses_a_normal_response() -> None:
    with plain_server() as url:
        cursor = _D1Cursor(url, {})
        cursor.execute("select 1")  # canary answers {"success": true, "data": []}
        assert cursor.description is None or isinstance(cursor.description, list)


class _FakeInflux(influxdb.InfluxDBConnector):  # type: ignore[misc]
    def __init__(self, host: str) -> None:
        self.host = host


def test_influx_version_probe_does_not_follow_redirects() -> None:
    with redirecting_to_a_canary() as (url, hits):
        version = _FakeInflux(url)._server_version()
        assert hits == []
        assert version == "InfluxDB 3.0 / IOx SQL Engine"  # fell back, did not crash


@pytest.mark.parametrize(
    "host",
    [
        "file:///etc/passwd",
        "ftp://127.0.0.1/x",
        "gopher://127.0.0.1/",
        "data:text/plain,hi",
    ],
)
def test_influx_version_probe_speaks_only_http(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a non-http(s) URL must never be opened")

    monkeypatch.setattr(influxdb._NO_REDIRECT_OPENER, "open", boom)
    assert _FakeInflux(host)._server_version() == "InfluxDB 3.0 / IOx SQL Engine"


def test_influx_version_probe_still_reads_the_version_header() -> None:
    class Ping(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("x-influxdb-version", "3.1.4")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    srv, port = _serve(Ping)
    try:
        assert (
            _FakeInflux(f"http://127.0.0.1:{port}")._server_version()
            == "InfluxDB 3.1.4"
        )
    finally:
        srv.shutdown()
        srv.server_close()
