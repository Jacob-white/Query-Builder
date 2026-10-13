"""Connect-time egress guard: the network policy, enforced where the connection is made.

``validate_network_target`` checks the address a connector is *configured* with. Between that
check and the moment a socket really connects, two things can change the destination:

* **DNS rebinding** - the driver resolves the name again and an attacker-controlled DNS server
  now answers with an internal address (the cloud-metadata IP, a private service);
* **redirects** - an HTTP client follows ``302 Location: http://169.254.169.254/...``.

This module closes both for every Python-socket-based driver by checking the *real
destination IP of every ``socket.connect``* made while a guard is active, against the same
policy ``validate_network_target`` uses (:func:`query_builder.security._validate_host_target`).
A guard is activated around ``connect``, ``execute``, ``execute_raw``, ``introspect_schema``
and ``test_connection`` of every connector (see ``BaseConnector.__init_subclass__``).

What it does **not** cover (use network-level egress controls for these; see SECURITY.md):

* drivers that connect in C without going through Python's ``socket`` (libpq, mysqlclient,
  ibm_db, ODBC, oracledb thick mode, ...);
* event loops that bypass ``socket.connect`` (``uvloop``); the Windows proactor loop is hooked;
* background threads a driver starts on its own (they do not inherit the guard).

The guard is active only inside ``with egress_guard(...)`` and only for the current thread /
asyncio task (a :class:`contextvars.ContextVar`), so it never affects the host application's
other sockets.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import ipaddress
import socket
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from query_builder.exceptions import SecurityError
from query_builder.security import _validate_host_target

__all__ = [
    "EgressPolicy",
    "check_destination",
    "egress_guard",
    "install",
    "is_installed",
]


@dataclass(frozen=True)
class EgressPolicy:
    """The network policy applied to every connection made while a guard is active."""

    #: ``NetworkSecurityConfig`` with hostname allow-lists folded away: an allow-list is a
    #: statement about *names*, which a socket no longer has. Metadata / blocked-address rules
    #: and (unless private networks are allowed or a name allow-list is in use) the
    #: private-range rule still apply.
    network_config: Any

    @classmethod
    def from_network_config(cls, network_config: Any) -> EgressPolicy:
        derived = copy.copy(network_config)
        derived.allow_private_networks = bool(
            network_config.allow_private_networks or network_config.allowed_hostnames
        )
        derived.allowed_hostnames = []
        return cls(derived)


_policy: contextvars.ContextVar[EgressPolicy | None] = contextvars.ContextVar(
    "query_builder_egress_policy", default=None
)

# What the guard delegates to. Module globals (looked up at call time) so tests can put a
# recorder underneath the guard and observe that a blocked connection never reaches it.
_original_connect: Any = None
_original_connect_ex: Any = None
_original_iocp_connect: Any = None
_install_lock = threading.Lock()
_installed = False


def check_destination(
    host: str, port: int | None, policy: EgressPolicy | None = None
) -> None:
    """Raise :class:`SecurityError` if connecting to the IP literal ``host`` breaks the policy.

    ``policy`` defaults to the one active in this context; with none active this is a no-op.
    """
    active = policy if policy is not None else _policy.get()
    if active is None:
        return
    literal = host.split("%", 1)[0].strip("[]")  # drop an IPv6 scope id
    try:
        _validate_host_target(literal, port, active.network_config)
    except SecurityError as exc:
        where = f"{literal}:{port}" if port else literal
        raise SecurityError(
            f"Egress guard: connection to '{where}' refused ({exc})"
        ) from None


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0].strip("[]"))
    except ValueError:
        return False
    return True


def _check_socket_address(sock: socket.socket, address: Any) -> Any:
    """Check ``address`` for ``sock`` and return the address to connect to.

    A name (instead of an IP literal) is resolved once here, every answer is checked and the
    connection goes to the first checked address - so the name is not resolved a second time
    by the C ``connect`` where it could be rebound.
    """
    if _policy.get() is None or sock.family not in (
        socket.AF_INET,
        socket.AF_INET6,
    ):
        return address
    if not isinstance(address, tuple) or len(address) < 2:
        return address
    host, port = address[0], address[1]
    if not isinstance(host, str):
        return address
    if _is_ip_literal(host):
        check_destination(host, port)
        return address
    infos = socket.getaddrinfo(host, port, sock.family, sock.type)
    if not infos:
        return address  # let the C connect report the failure
    for info in infos:
        check_destination(str(info[4][0]), port)
    return (infos[0][4][0], *infos[0][4][1:])


def _guarded_connect(self: socket.socket, address: Any) -> Any:
    target = _check_socket_address(self, address)
    return _original_connect(self, target)


def _guarded_connect_ex(self: socket.socket, address: Any) -> Any:
    target = _check_socket_address(self, address)
    return _original_connect_ex(self, target)


def _guarded_iocp_connect(self: Any, conn: Any, address: Any) -> Any:
    if _policy.get() is not None and isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, str) and _is_ip_literal(host):
            check_destination(host, address[1] if len(address) > 1 else None)
    return _original_iocp_connect(self, conn, address)


def install() -> None:
    """Hook ``socket.socket.connect`` / ``connect_ex`` (and the Windows proactor). Idempotent."""
    global _installed, _original_connect, _original_connect_ex, _original_iocp_connect
    with _install_lock:
        if _installed:
            return
        _original_connect = socket.socket.connect
        _original_connect_ex = socket.socket.connect_ex
        socket.socket.connect = _guarded_connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign,assignment]
        if sys.platform == "win32":
            with contextlib.suppress(Exception):
                from asyncio import windows_events

                _original_iocp_connect = windows_events.IocpProactor.connect
                windows_events.IocpProactor.connect = _guarded_iocp_connect  # type: ignore[method-assign]
        _installed = True


def is_installed() -> bool:
    return _installed


@contextlib.contextmanager
def egress_guard(network_config: Any) -> Iterator[None]:
    """Enforce ``network_config`` on every socket connection made inside the block.

    ``None`` (security disabled) or ``connect_time_guard=False`` makes this a no-op. Guards
    nest; leaving a block (also by exception) restores the previous policy.
    """
    if network_config is None or not getattr(
        network_config, "connect_time_guard", True
    ):
        yield
        return
    install()
    token = _policy.set(EgressPolicy.from_network_config(network_config))
    try:
        yield
    finally:
        _policy.reset(token)
