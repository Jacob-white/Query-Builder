"""SSRF / DNS-rebinding hardening: every resolved address is validated, the name is resolved
once, and the connection is pinned to the validated address (no TOCTOU window)."""

from __future__ import annotations

import socket
import sys
from unittest.mock import MagicMock

import pytest

from query_builder.config import NetworkSecurityConfig, SecurityConfig
from query_builder.connectors.postgres import PostgresConnector
from query_builder.security import (
    SecurityError,
    dns_resolver,
    resolve_and_validate_target,
    set_dns_resolver,
    validate_network_target,
)

PUBLIC_A = "93.184.216.34"
PUBLIC_B = "151.101.1.69"


class SequenceResolver:
    """Returns a different answer on every call (a rebinding attacker's DNS server)."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append((host, port))
        idx = min(len(self.calls) - 1, len(self.answers) - 1)
        return self.answers[idx]


def _net(**kw) -> NetworkSecurityConfig:
    kw.setdefault("allow_private_networks", False)
    kw.setdefault("enforce_tls", False)
    return NetworkSecurityConfig(**kw)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",
        "169.254.10.10",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd00:ec2::254",
        "fec0::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
        "2002:7f00:1::1",  # 6to4 of 127.0.0.1
        "2002:a9fe:a9fe::1",  # 6to4 of 169.254.169.254
        "::7f00:1",  # IPv4-compatible 127.0.0.1
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
    ],
)
def test_every_special_address_is_rejected_when_resolved(ip: str) -> None:
    with pytest.raises(SecurityError):
        resolve_and_validate_target(
            "evil.example", 5432, _net(), resolver=SequenceResolver([ip])
        )


@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",
        "::ffff:169.254.169.254",
        "fd00:ec2::254",
        "64:ff9b::a9fe:a9fe",
        "2002:a9fe:a9fe::1",
    ],
)
def test_cloud_metadata_is_forbidden_even_when_private_networks_are_allowed(
    ip: str,
) -> None:
    with pytest.raises(SecurityError, match="metadata"):
        resolve_and_validate_target(
            "evil.example",
            5432,
            _net(allow_private_networks=True),
            resolver=SequenceResolver([ip]),
        )


def test_all_addresses_of_a_multi_record_answer_are_validated() -> None:
    # A public A record next to a private one: the attacker hopes only the first is checked.
    for answer in ([PUBLIC_A, "10.0.0.5"], ["10.0.0.5", PUBLIC_A], [PUBLIC_A, "::1"]):
        with pytest.raises(SecurityError):
            resolve_and_validate_target(
                "evil.example", 80, _net(), resolver=SequenceResolver(answer)
            )


def test_resolves_once_and_pins_the_first_validated_address() -> None:
    r = SequenceResolver([PUBLIC_A, PUBLIC_B], ["10.0.0.5"])
    t = resolve_and_validate_target("db.example", 5432, _net(), resolver=r)
    assert t.addresses == (PUBLIC_A, PUBLIC_B)
    assert t.pinned_address == PUBLIC_A
    assert len(r.calls) == 1  # the rebound second answer is never even requested


def test_ip_literals_are_validated_and_pinned_without_dns() -> None:
    r = SequenceResolver(["10.0.0.5"])
    t = resolve_and_validate_target(PUBLIC_A, 443, _net(), resolver=r)
    assert t.pinned_address == PUBLIC_A and r.calls == []
    with pytest.raises(SecurityError):
        resolve_and_validate_target("10.0.0.5", 443, _net(), resolver=r)
    t6 = resolve_and_validate_target("[2606:4700::1111]", 443, _net(), resolver=r)
    assert t6.pinned_address == "2606:4700::1111"


@pytest.mark.parametrize(
    "host",
    [
        "metadata.google.internal.",
        "METADATA.GOOGLE.INTERNAL",
        "metadata。google。internal",
        "metadata．google．internal",
        "instance-data.",
    ],
)
def test_metadata_hostname_variants_are_forbidden(host: str) -> None:
    with pytest.raises(SecurityError, match="metadata"):
        validate_network_target(
            host=host, network_config=_net(allow_private_networks=True)
        )


def test_unresolvable_host_legacy_fallback_vs_fail_closed() -> None:
    def nxdomain(host: str, port: int) -> list[str]:
        raise socket.gaierror("nxdomain")

    # Legacy behaviour (kept): validation passes, the driver fails later.
    with dns_resolver(nxdomain):
        validate_network_target(host="ghost.example", network_config=_net())
    t = resolve_and_validate_target("ghost.example", 80, _net(), resolver=nxdomain)
    assert t.pinned_address is None
    # Fail-closed: no rebinding window for "NXDOMAIN now, private IP at connect time".
    with pytest.raises(SecurityError, match="could not be resolved"):
        resolve_and_validate_target(
            "ghost.example", 80, _net(), resolver=nxdomain, fail_closed=True
        )
    with pytest.raises(SecurityError, match="did not resolve"):
        resolve_and_validate_target(
            "ghost.example", 80, _net(), resolver=lambda h, p: [], fail_closed=True
        )


def test_set_dns_resolver_roundtrip() -> None:
    r = SequenceResolver(["10.0.0.5"])
    previous = set_dns_resolver(r)
    try:
        with pytest.raises(SecurityError):
            validate_network_target(host="x.example", network_config=_net())
        assert r.calls
    finally:
        set_dns_resolver(previous)
    set_dns_resolver(None)


# ------------------------------------------------------------------ connector wiring


@pytest.fixture
def fake_psycopg(monkeypatch):
    driver = MagicMock()
    monkeypatch.setitem(sys.modules, "psycopg", driver)
    return driver


def _sec(**net) -> SecurityConfig:
    sec = SecurityConfig()
    sec.network = _net(**net)
    sec.execution.enforce_read_only_session = False
    return sec


def test_postgres_connects_to_the_validated_address(fake_psycopg) -> None:
    r = SequenceResolver([PUBLIC_A], [PUBLIC_B], ["10.0.0.5"])
    c = PostgresConnector(security=_sec(), host="db.example", port=5432, dbname="x")
    with dns_resolver(r):
        c.connect()
    kwargs = fake_psycopg.connect.call_args.kwargs
    # call 1 = legacy validation, call 2 = the pinned resolution; the connect itself does
    # no resolution of its own (libpq `hostaddr`), so the third (rebound) answer is unused.
    assert kwargs["hostaddr"] == PUBLIC_B
    assert kwargs["host"] == "db.example"
    assert len(r.calls) == 2


def test_rebinding_between_validation_and_pin_is_refused(fake_psycopg) -> None:
    r = SequenceResolver([PUBLIC_A], ["10.0.0.5"])
    c = PostgresConnector(security=_sec(), host="db.example", port=5432)
    with dns_resolver(r), pytest.raises(SecurityError):
        c.connect()
    fake_psycopg.connect.assert_not_called()


def test_postgres_pinning_can_be_disabled_and_skips_ip_hosts(fake_psycopg) -> None:
    r = SequenceResolver([PUBLIC_A])
    off = PostgresConnector(
        security=_sec(pin_resolved_addresses=False), host="db.example", port=5432
    )
    with dns_resolver(r):
        off.connect()
    assert "hostaddr" not in fake_psycopg.connect.call_args.kwargs

    fake_psycopg.connect.reset_mock()
    lit = PostgresConnector(security=_sec(), host=PUBLIC_A, port=5432)
    with dns_resolver(r):
        lit.connect()
    kwargs = fake_psycopg.connect.call_args.kwargs
    assert kwargs["hostaddr"] == PUBLIC_A  # literal: pinned trivially


def test_explicit_hostaddr_and_dsn_configs_are_left_alone(fake_psycopg) -> None:
    c = PostgresConnector(security=_sec(), host=PUBLIC_A, hostaddr=PUBLIC_B)
    c.connect()
    assert fake_psycopg.connect.call_args.kwargs["hostaddr"] == PUBLIC_B
    fake_psycopg.connect.reset_mock()
    d = PostgresConnector(security=_sec(), dsn="postgresql://u@db.example/x")
    with dns_resolver(SequenceResolver([PUBLIC_A])):
        d.connect()
    assert "hostaddr" not in fake_psycopg.connect.call_args.kwargs


def test_fail_closed_option_blocks_unresolvable_connector_hosts(fake_psycopg) -> None:
    def nxdomain(host: str, port: int) -> list[str]:
        raise socket.gaierror("nxdomain")

    c = PostgresConnector(
        security=_sec(fail_closed_on_dns_error=True), host="ghost.example", port=5432
    )
    with dns_resolver(nxdomain), pytest.raises(SecurityError):
        c.connect()
    fake_psycopg.connect.assert_not_called()
