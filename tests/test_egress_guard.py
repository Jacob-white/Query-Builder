"""Robustness tests for the connect-time egress guard (``query_builder.egress_guard``).

The guard checks the REAL destination IP of every ``socket.connect`` made while it is active,
so DNS rebinding and redirects to internal addresses are stopped after ``validate_network_target``
has passed. Every scenario that must be blocked also has a CONTROL run without the guard, so a
passing test proves the guard (and not a broken scenario) is what stops the connection.

Nothing here touches the real network: a recorder sits *underneath* the guard and refuses every
non-loopback destination, so "blocked" means the recorder was never reached.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import socket
import sys
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from query_builder import egress_guard as eg
from query_builder.config import NetworkSecurityConfig, SecurityConfig
from query_builder.connectors.async_base import AsyncBaseConnector
from query_builder.connectors.base import BaseConnector
from query_builder.connectors.registry import ConnectorRegistry
from query_builder.exceptions import SecurityError
from query_builder.security import dns_resolver

META = "169.254.169.254"
PUBLIC = "93.184.216.34"

LOOSE = NetworkSecurityConfig(allow_private_networks=True, enforce_tls=False)
STRICT = NetworkSecurityConfig(allow_private_networks=False, enforce_tls=False)


def _sec(net: NetworkSecurityConfig) -> SecurityConfig:
    sec = SecurityConfig()
    sec.network = net
    sec.execution.enforce_read_only_session = False
    return sec


# --------------------------------------------------------------------------- fixtures
class FakeNet:
    """Records every connection that reaches the layer UNDER the guard."""

    def __init__(self, real_connect: Any, real_connect_ex: Any) -> None:
        self.attempts: list[tuple[str, int | None]] = []
        self._real_connect = real_connect
        self._real_connect_ex = real_connect_ex

    @staticmethod
    def _host(address: Any) -> tuple[str, int | None]:
        if isinstance(address, tuple):
            return str(address[0]), address[1] if len(address) > 1 else None
        return str(address), None

    def _loopback(self, host: str) -> bool:
        return host in ("127.0.0.1", "::1", "localhost")

    def connect(self, sock: socket.socket, address: Any) -> Any:
        host, port = self._host(address)
        self.attempts.append((host, port))
        if self._loopback(host):
            return self._real_connect(sock, address)
        raise ConnectionRefusedError(f"fake network: {host} unreachable")

    def connect_ex(self, sock: socket.socket, address: Any) -> int:
        host, port = self._host(address)
        self.attempts.append((host, port))
        if self._loopback(host):
            return int(self._real_connect_ex(sock, address))
        return 111

    def reached(self, ip: str) -> bool:
        return any(host == ip for host, _ in self.attempts)


@pytest.fixture
def fake_net(monkeypatch: pytest.MonkeyPatch) -> FakeNet:
    eg.install()
    net = FakeNet(eg._original_connect, eg._original_connect_ex)
    monkeypatch.setattr(eg, "_original_connect", net.connect)
    monkeypatch.setattr(eg, "_original_connect_ex", net.connect_ex)
    if eg._original_iocp_connect is not None:  # Windows proactor loop
        real_iocp = eg._original_iocp_connect

        def iocp(proactor: Any, conn: Any, address: Any) -> Any:
            host, port = net._host(address)
            net.attempts.append((host, port))
            if net._loopback(host):
                return real_iocp(proactor, conn, address)
            raise ConnectionRefusedError(f"fake network: {host} unreachable")

        monkeypatch.setattr(eg, "_original_iocp_connect", iocp)
    return net


@pytest.fixture
def rebind(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``rebind.test``: validation (injected resolver) sees a public IP, while the DRIVER's own
    resolution (``socket.getaddrinfo``) now answers with the metadata address."""
    real = socket.getaddrinfo

    def getaddrinfo(host: Any, port: Any, *a: Any, **kw: Any) -> Any:
        if host == "rebind.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (META, port or 0))]
        return real(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    with dns_resolver(lambda host, port: [PUBLIC]):
        yield


@contextlib.contextmanager
def local_server(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[int]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()


def redirector(location: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Redirect(http.server.BaseHTTPRequestHandler):
        def _go(self) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = _go  # noqa: N815

        def log_message(self, *args: Any) -> None:
            pass

    return Redirect


# ------------------------------------------------------------- 1. policy classification
ALWAYS_BLOCKED = [
    "169.254.169.254",
    "169.254.169.253",
    "fd00:ec2::254",
    "::ffff:169.254.169.254",  # IPv4-mapped
    "64:ff9b::a9fe:a9fe",  # NAT64
    "2002:a9fe:a9fe::1",  # 6to4
    "169.254.170.2",  # AWS ECS task credentials
    "169.254.170.23",  # AWS EKS pod identity
    "fd00:ec2::23",  # AWS EKS pod identity (IPv6)
    "168.63.129.16",  # Azure WireServer
    "100.100.100.200",  # Alibaba Cloud metadata
    "192.0.0.192",  # Oracle Cloud (legacy) metadata
]
PRIVATE = [
    "127.0.0.1",
    "10.1.2.3",
    "172.16.0.9",
    "192.168.1.1",
    "::1",
    "fc00::1",
    "fe80::1",
]
PUBLIC_ADDRS = [PUBLIC, "151.101.1.69", "2606:2800:220:1:248:1893:25c8:1946"]


@pytest.mark.parametrize("ip", ALWAYS_BLOCKED)
@pytest.mark.parametrize(
    "net", [LOOSE, STRICT], ids=["private-allowed", "private-denied"]
)
def test_cloud_credential_endpoints_are_blocked_whatever_the_policy(
    ip: str, net: NetworkSecurityConfig
) -> None:
    with pytest.raises(SecurityError, match="Egress guard"):
        eg.check_destination(ip, 80, eg.EgressPolicy.from_network_config(net))


@pytest.mark.parametrize("ip", PRIVATE)
def test_private_ranges_follow_allow_private_networks(ip: str) -> None:
    eg.check_destination(ip, 5432, eg.EgressPolicy.from_network_config(LOOSE))
    with pytest.raises(SecurityError):
        eg.check_destination(ip, 5432, eg.EgressPolicy.from_network_config(STRICT))


@pytest.mark.parametrize("ip", PUBLIC_ADDRS)
@pytest.mark.parametrize(
    "net", [LOOSE, STRICT], ids=["private-allowed", "private-denied"]
)
def test_public_addresses_are_never_blocked(
    ip: str, net: NetworkSecurityConfig
) -> None:
    eg.check_destination(ip, 443, eg.EgressPolicy.from_network_config(net))


def test_a_hostname_allow_list_cannot_apply_to_an_ip_so_it_relaxes_only_private_ranges() -> (
    None
):
    net = NetworkSecurityConfig(
        allow_private_networks=False,
        allowed_hostnames=["db.internal"],
        enforce_tls=False,
    )
    policy = eg.EgressPolicy.from_network_config(net)
    eg.check_destination(
        "10.0.0.5", 5432, policy
    )  # the allow-listed name may resolve here
    with pytest.raises(SecurityError):
        eg.check_destination(META, 5432, policy)  # metadata is never allowed


def test_blocked_hostnames_entry_for_an_ip_is_honoured() -> None:
    net = NetworkSecurityConfig(
        allow_private_networks=True, blocked_hostnames=["10.9.9.9"], enforce_tls=False
    )
    with pytest.raises(SecurityError):
        eg.check_destination("10.9.9.9", 1, eg.EgressPolicy.from_network_config(net))
    eg.check_destination("10.9.9.8", 1, eg.EgressPolicy.from_network_config(net))


def test_ipv6_scope_id_is_ignored_when_classifying() -> None:
    with pytest.raises(SecurityError):
        eg.check_destination(
            "fe80::1%eth0", 1, eg.EgressPolicy.from_network_config(STRICT)
        )


def test_error_names_the_destination_and_nothing_else() -> None:
    with pytest.raises(SecurityError) as err:
        eg.check_destination(META, 8080, eg.EgressPolicy.from_network_config(LOOSE))
    assert f"{META}:8080" in str(err.value)
    assert err.value.__cause__ is None  # no chained internals


def test_with_no_active_guard_checking_is_a_no_op() -> None:
    eg.check_destination(META, 80)


# ------------------------------------------------------------------ 2. the socket hook
def _connect(host: str, port: int = 80) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        s.connect((host, port))


def test_guard_blocks_before_the_connection_reaches_the_network(
    fake_net: FakeNet,
) -> None:
    with eg.egress_guard(LOOSE), pytest.raises(SecurityError):
        _connect(META)
    assert not fake_net.reached(META)


def test_control_without_the_guard_the_same_connection_is_attempted(
    fake_net: FakeNet,
) -> None:
    with pytest.raises(ConnectionRefusedError):
        _connect(META)
    assert fake_net.reached(META)  # the scenario really can reach the network


def test_allowed_destination_passes_through_to_the_network(fake_net: FakeNet) -> None:
    with eg.egress_guard(STRICT), pytest.raises(ConnectionRefusedError):
        _connect(PUBLIC)
    assert fake_net.reached(PUBLIC)


def test_connect_ex_is_guarded_too(fake_net: FakeNet) -> None:
    with eg.egress_guard(LOOSE), socket.socket() as s, pytest.raises(SecurityError):
        s.connect_ex((META, 80))
    assert not fake_net.reached(META)


def test_ipv6_sockets_are_guarded(fake_net: FakeNet) -> None:
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    with eg.egress_guard(LOOSE), socket.socket(socket.AF_INET6) as s:
        with pytest.raises(SecurityError):
            s.connect(("::ffff:169.254.169.254", 80, 0, 0))
    assert not fake_net.attempts


def test_unix_sockets_are_not_affected(fake_net: FakeNet, tmp_path: Any) -> None:
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("no AF_UNIX")
    with eg.egress_guard(STRICT), socket.socket(socket.AF_UNIX) as s:
        with pytest.raises(
            OSError
        ) as err:  # refused/not found by the OS, not by the guard
            s.connect(str(tmp_path / "nope.sock"))
    assert not isinstance(err.value, SecurityError)


def test_a_name_is_resolved_once_checked_and_connected_by_ip(
    fake_net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``connect(("name", port))`` would let the C layer resolve the name a second time."""
    calls: list[str] = []

    def getaddrinfo(host: Any, port: Any, *a: Any, **kw: Any) -> Any:
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    with eg.egress_guard(STRICT), pytest.raises(ConnectionRefusedError):
        _connect("db.example", 5432)
    assert calls == ["db.example"]
    assert fake_net.attempts == [
        (PUBLIC, 5432)
    ]  # connected to the checked IP, not the name


def test_a_name_with_any_bad_answer_is_refused(
    fake_net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    def getaddrinfo(host: Any, port: Any, *a: Any, **kw: Any) -> Any:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (META, port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    with eg.egress_guard(LOOSE), pytest.raises(SecurityError):
        _connect("mixed.example")
    assert not fake_net.attempts


def test_install_is_idempotent() -> None:
    eg.install()
    first = socket.socket.connect
    eg.install()
    assert socket.socket.connect is first and eg.is_installed()


# --------------------------------------------------------------- 3. context semantics
def test_inactive_outside_the_block(fake_net: FakeNet) -> None:
    with eg.egress_guard(LOOSE):
        pass
    with pytest.raises(ConnectionRefusedError):
        _connect(META)  # no SecurityError: the guard is off again


def test_policy_is_restored_after_an_exception(fake_net: FakeNet) -> None:
    with pytest.raises(RuntimeError), eg.egress_guard(LOOSE):
        raise RuntimeError("boom")
    assert eg._policy.get() is None


def test_guards_nest_and_the_inner_policy_wins_then_restores(fake_net: FakeNet) -> None:
    with eg.egress_guard(LOOSE):
        eg.check_destination("10.0.0.1", 1)  # private allowed by the outer policy
        with eg.egress_guard(STRICT):
            with pytest.raises(SecurityError):
                eg.check_destination("10.0.0.1", 1)
        eg.check_destination("10.0.0.1", 1)  # outer policy back


def test_none_network_config_or_switch_off_is_a_no_op(fake_net: FakeNet) -> None:
    off = NetworkSecurityConfig(allow_private_networks=True, connect_time_guard=False)
    for cfg in (None, off):
        with eg.egress_guard(cfg), pytest.raises(ConnectionRefusedError):
            _connect(META)
    assert fake_net.reached(META)


def test_guard_is_per_thread(fake_net: FakeNet) -> None:
    results: dict[str, str] = {}
    gate = threading.Event()

    def guarded() -> None:
        with eg.egress_guard(LOOSE):
            gate.set()
            try:
                _connect(META)
            except SecurityError:
                results["guarded"] = "blocked"
            except OSError:
                results["guarded"] = "reached"

    def bystander() -> None:
        gate.wait(5)
        try:
            _connect(META)
        except SecurityError:
            results["bystander"] = "blocked"
        except OSError:
            results["bystander"] = (
                "reached"  # another thread's guard must not apply here
            )

    threads = [threading.Thread(target=guarded), threading.Thread(target=bystander)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert results == {"guarded": "blocked", "bystander": "reached"}


def test_guard_follows_asyncio_to_thread(fake_net: FakeNet) -> None:
    async def main() -> str:
        with eg.egress_guard(LOOSE):
            try:
                await asyncio.to_thread(_connect, META)
            except SecurityError:
                return "blocked"
            except OSError:
                return "reached"
        return "?"

    assert asyncio.run(main()) == "blocked"


def test_guard_is_per_asyncio_task(fake_net: FakeNet) -> None:
    async def guarded() -> str:
        with eg.egress_guard(LOOSE):
            await asyncio.sleep(
                0.05
            )  # lets the other task run while this guard is active
            try:
                await asyncio.to_thread(_connect, META)
            except SecurityError:
                return "blocked"
            except OSError:
                return "reached"
        return "?"

    async def bystander() -> str:
        await asyncio.sleep(0.01)
        try:
            await asyncio.to_thread(_connect, META)
        except SecurityError:
            return "blocked"
        except OSError:
            return "reached"
        return "?"

    async def main() -> list[str]:
        return list(await asyncio.gather(guarded(), bystander()))

    assert asyncio.run(main()) == ["blocked", "reached"]


# ------------------------------------------------------- 4. real sockets, end to end
def test_real_loopback_connection_follows_the_policy() -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    accepted: list[bytes] = []

    def serve() -> None:
        conn, _ = srv.accept()
        accepted.append(conn.recv(4))
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with eg.egress_guard(STRICT), pytest.raises(SecurityError):
            socket.create_connection(("127.0.0.1", port), timeout=2)
        assert accepted == []  # refused before any packet was sent
        with eg.egress_guard(LOOSE):
            with socket.create_connection(("127.0.0.1", port), timeout=2) as c:
                c.sendall(b"ping")
        thread.join(5)
        assert accepted == [b"ping"]
    finally:
        srv.close()


@pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "WindowsSelectorEventLoopPolicy"),
    reason="needs a loop policy",
)
def test_asyncio_open_connection_is_guarded(fake_net: FakeNet) -> None:
    async def main() -> str:
        with eg.egress_guard(LOOSE):
            try:
                await asyncio.wait_for(asyncio.open_connection(META, 80), 3)
            except SecurityError:
                return "blocked"
            except (TimeoutError, OSError):
                return "reached"
        return "?"

    assert asyncio.run(main()) == "blocked"
    assert not fake_net.reached(META)


# ------------------------------------------------- 5. wired into every connector
class _SyncProbe(BaseConnector):
    """Connects to whatever ``self.target`` resolves to (a stand-in for any driver)."""

    dialect_name = "postgres"

    def __init__(self, target: str = "rebind.test", **kw: Any) -> None:
        super().__init__(**kw)
        self.target = target

    def _dial(self) -> None:
        socket.create_connection((self.target, 5432), timeout=1).close()

    def connect(self) -> Any:
        self._dial()
        return object()

    def execute_raw(self, sql: str, params: Any = None) -> Any:
        self._dial()
        return [], [], 0.0

    def test_connection(self) -> dict[str, Any]:
        self._dial()
        return {}

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        self._dial()
        return {}


class _AsyncProbe(AsyncBaseConnector):
    dialect_name = "postgres"

    def __init__(self, target: str = "rebind.test", **kw: Any) -> None:
        super().__init__(**kw)
        self.target = target

    async def _dial(self) -> None:
        await asyncio.to_thread(
            lambda: socket.create_connection((self.target, 5432), timeout=1)
        )

    async def connect(self) -> Any:
        await self._dial()
        return object()

    async def execute_raw(self, sql: str, params: Any = None) -> Any:
        await self._dial()
        return [], [], 0.0

    async def test_connection(self) -> dict[str, Any]:
        await self._dial()
        return {}

    async def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        await self._dial()
        return {}


SYNC_ENTRY_POINTS = [
    lambda c: c.connect(),
    lambda c: c.execute_raw("select 1"),
    lambda c: c.test_connection(),
    lambda c: c.introspect_schema(),
]
SYNC_IDS = ["connect", "execute_raw", "test_connection", "introspect_schema"]


@pytest.mark.parametrize("call", SYNC_ENTRY_POINTS, ids=SYNC_IDS)
def test_sync_connector_entry_points_stop_a_rebound_connection(
    call: Any, fake_net: FakeNet, rebind: None
) -> None:
    conn = _SyncProbe(security=_sec(LOOSE))
    with pytest.raises(SecurityError):
        call(conn)
    assert not fake_net.reached(META)


@pytest.mark.parametrize("call", SYNC_ENTRY_POINTS, ids=SYNC_IDS)
def test_control_unguarded_connector_reaches_the_rebound_address(
    call: Any, fake_net: FakeNet, rebind: None
) -> None:
    conn = _SyncProbe(
        security=_sec(
            NetworkSecurityConfig(
                allow_private_networks=True, connect_time_guard=False, enforce_tls=False
            )
        )
    )
    with pytest.raises(ConnectionRefusedError):
        call(conn)
    assert fake_net.reached(META)  # same scenario, guard off: it gets through


ASYNC_ENTRY_POINTS = [
    lambda c: c.connect(),
    lambda c: c.execute_raw("select 1"),
    lambda c: c.test_connection(),
    lambda c: c.introspect_schema(),
]


@pytest.mark.parametrize("call", ASYNC_ENTRY_POINTS, ids=SYNC_IDS)
def test_async_connector_entry_points_stop_a_rebound_connection(
    call: Any, fake_net: FakeNet, rebind: None
) -> None:
    conn = _AsyncProbe(security=_sec(LOOSE))
    with pytest.raises(SecurityError):
        asyncio.run(call(conn))
    assert not fake_net.reached(META)


def test_a_legitimate_public_target_is_unaffected(
    fake_net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port))
        ],
    )
    conn = _SyncProbe(target="db.example", security=_sec(STRICT))
    with dns_resolver(lambda h, p: [PUBLIC]), pytest.raises(ConnectionRefusedError):
        conn.connect()  # reaches the (fake) network: not a SecurityError
    assert fake_net.reached(PUBLIC)


# Captured at import: other tests clear the global registry.
_REGISTERED = {cls for cls in ConnectorRegistry._registry.values()}
_GUARDED = ("execute", "execute_raw", "introspect_schema", "test_connection")


def test_every_registered_connector_entry_point_is_guarded() -> None:
    """Structural: no connector class can define an entry point that skips the guard."""
    missing: list[str] = []
    for cls in sorted(_REGISTERED, key=lambda c: c.__name__):
        for name in _GUARDED:
            fn = getattr(cls, name, None)
            if fn is not None and not getattr(fn, "_egress_guarded", False):
                missing.append(f"{cls.__name__}.{name}")
        if not getattr(cls.connect, "_security_wrapped", False):
            missing.append(f"{cls.__name__}.connect")
    assert missing == []
    assert len(_REGISTERED) >= 130


def test_connect_time_guard_defaults_on() -> None:
    assert NetworkSecurityConfig().connect_time_guard is True


# ----------------------------------------------- 6. real client libraries, real redirects
_REDIS_CLASS = ConnectorRegistry._registry.get("redis")


def _follow_to_metadata(client: Any) -> str:
    """Run ``client()`` against a server that 302-redirects to the metadata address."""
    with local_server(redirector(f"http://{META}/latest/meta-data/")) as port:
        try:
            client(f"http://127.0.0.1:{port}/x")
        except SecurityError:
            return "blocked"
        except Exception:  # noqa: BLE001 - connection refused by the fake network
            return "reached"
    return "no-redirect-followed"


def _requests_get(url: str) -> None:
    import requests

    requests.get(url, timeout=3)


def _urllib_get(url: str) -> None:
    import urllib.request

    urllib.request.urlopen(url, timeout=3)  # noqa: S310


def _urllib3_get(url: str) -> None:
    import urllib3

    urllib3.PoolManager().request("GET", url, timeout=3)


def _httpx_follow(url: str) -> None:
    import httpx

    httpx.Client(follow_redirects=True).get(url, timeout=3)


@pytest.mark.parametrize(
    "client",
    [_requests_get, _urllib_get, _urllib3_get, _httpx_follow],
    ids=["requests", "urllib", "urllib3", "httpx-follow"],
)
def test_a_redirect_to_the_metadata_address_is_blocked_for_each_client(
    client: Any, fake_net: FakeNet
) -> None:
    pytest.importorskip("requests")
    if client is _httpx_follow:
        pytest.importorskip("httpx")
    with eg.egress_guard(LOOSE):
        assert _follow_to_metadata(client) == "blocked"
    assert not fake_net.reached(META)


@pytest.mark.parametrize(
    "client",
    [_requests_get, _urllib_get, _urllib3_get, _httpx_follow],
    ids=["requests", "urllib", "urllib3", "httpx-follow"],
)
def test_control_the_same_redirect_reaches_the_metadata_address_without_the_guard(
    client: Any, fake_net: FakeNet
) -> None:
    pytest.importorskip("requests")
    if client is _httpx_follow:
        pytest.importorskip("httpx")
    assert _follow_to_metadata(client) == "reached"
    assert fake_net.reached(META)


def test_aiohttp_redirect_to_the_metadata_address_is_blocked(fake_net: FakeNet) -> None:
    aiohttp = pytest.importorskip("aiohttp")

    async def go() -> str:
        with local_server(redirector(f"http://{META}/")) as port:
            with eg.egress_guard(LOOSE):
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(
                            f"http://127.0.0.1:{port}/x",
                            timeout=aiohttp.ClientTimeout(total=3),
                        ) as r:
                            await r.read()
                except SecurityError:
                    return "blocked"
                except Exception:  # noqa: BLE001
                    return "reached"
        return "no-redirect-followed"

    assert asyncio.run(go()) == "blocked"
    assert not fake_net.reached(META)


def test_control_aiohttp_reaches_the_metadata_address_without_the_guard(
    fake_net: FakeNet,
) -> None:
    aiohttp = pytest.importorskip("aiohttp")

    async def go() -> None:
        with local_server(redirector(f"http://{META}/")) as port:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(
                        f"http://127.0.0.1:{port}/x",
                        timeout=aiohttp.ClientTimeout(total=3),
                    ) as r:
                        await r.read()
            except Exception:  # noqa: BLE001
                pass

    asyncio.run(go())
    assert fake_net.reached(META)


def test_httpx_default_never_follows_so_the_guard_is_not_even_needed(
    fake_net: FakeNet,
) -> None:
    httpx = pytest.importorskip("httpx")
    with local_server(redirector(f"http://{META}/")) as port:
        res = httpx.Client().get(f"http://127.0.0.1:{port}/x", timeout=3)
    assert res.status_code == 302 and not fake_net.reached(META)


@pytest.mark.skipif(_REDIS_CLASS is None, reason="redis connector not registered")
def test_redis_driver_dns_rebinding_is_blocked(fake_net: FakeNet, rebind: None) -> None:
    pytest.importorskip("redis")
    conn = _REDIS_CLASS(host="rebind.test", port=6379, security=_sec(LOOSE))  # type: ignore[misc]
    with pytest.raises(SecurityError):
        conn.test_connection()
    assert not fake_net.reached(META)


@pytest.mark.skipif(_REDIS_CLASS is None, reason="redis connector not registered")
def test_control_redis_driver_reaches_the_rebound_address_without_the_guard(
    fake_net: FakeNet, rebind: None
) -> None:
    redis = pytest.importorskip("redis")
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    off = NetworkSecurityConfig(
        allow_private_networks=True, enforce_tls=False, connect_time_guard=False
    )
    conn = _REDIS_CLASS(
        host="rebind.test",
        port=6379,
        retry=Retry(NoBackoff(), 0),
        security=_sec(off),
    )  # type: ignore[misc]
    with pytest.raises(redis.RedisError):
        conn.test_connection()
    assert fake_net.reached(META)


def test_a_connector_that_skipped_the_base_init_is_still_guarded(
    fake_net: FakeNet, rebind: None
) -> None:
    """Subclasses and test doubles sometimes never call ``BaseConnector.__init__``; the guard
    must neither crash on the missing attributes nor silently stop protecting them."""
    conn = _SyncProbe.__new__(
        _SyncProbe
    )  # no __init__: no _explicit_security, no security
    conn.target = "rebind.test"
    conn._connection = None
    conn.config = {}
    with pytest.raises(SecurityError):
        conn.test_connection()
    assert not fake_net.reached(META)
