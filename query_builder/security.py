"""
Tenant Isolation, Security Validation, Sandboxing & Network Egress Governance.
==============================================================================
Provides fail-closed user and tenant isolation predicate resolution,
network SSRF egress validation, credential and secret scrubbing,
AST complexity scoring, Cartesian product detection, and column masking.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

from query_builder.config import SecurityProfile  # noqa: F401
from query_builder.dialects import IDENTIFIER_REGEX, BaseDialect
from query_builder.exceptions import SecurityError
from query_builder.models import QuerySpec


class AliasCounter:
    """Thread-safe counter generating unique correlation aliases for subqueries."""

    def __init__(self, prefix: str = "_own") -> None:
        self._n = 0
        self._prefix = prefix

    def next(self) -> str:
        self._n += 1
        return f"{self._prefix}{self._n}"


MAX_OWNERSHIP_CHAIN_DEPTH = 10


def _build_chain_exists(
    dialect: BaseDialect,
    tables_meta: dict[str, Any],
    from_alias: str,
    chain: list[tuple[str, str, str]],
    user_id: Any,
    params: list[Any],
    counter: AliasCounter,
    current_depth: int = 0,
    visited_tables: set[str] | None = None,
) -> str:
    """
    Builds a (possibly nested) EXISTS clause walking `chain` from `from_alias`
    to the user-owned table at the end of the chain, appending bind params in
    left-to-right order matching the returned SQL text.

    Guards against recursion overflow and cyclic ownership loops.
    """
    if not chain:
        raise SecurityError("Ownership chain cannot be empty.")

    if current_depth >= MAX_OWNERSHIP_CHAIN_DEPTH:
        raise SecurityError(
            f"Ownership chain depth exceeded maximum allowed limit ({MAX_OWNERSHIP_CHAIN_DEPTH})."
        )

    hop = chain[0]
    if not isinstance(hop, (tuple, list)) or len(hop) != 3:
        raise SecurityError(f"Invalid ownership chain element format: {hop}")

    fk_col, target_table, target_pk = hop
    for name, label in (
        (target_table, "target table"),
        (fk_col, "foreign key column"),
        (target_pk, "target PK column"),
    ):
        if not isinstance(name, str) or not IDENTIFIER_REGEX.match(name):
            raise SecurityError(
                f"Invalid {label} identifier in ownership chain: '{name}'"
            )
        if any(len(p) > 128 for p in name.split(".")):
            raise SecurityError(
                f"{label} identifier part exceeds maximum allowed length (128): '{name}'"
            )

    if not isinstance(from_alias, str) or not IDENTIFIER_REGEX.match(from_alias):
        raise SecurityError(f"Invalid alias in ownership chain: '{from_alias}'")

    visited = set(visited_tables) if visited_tables is not None else set()
    if target_table in visited:
        raise SecurityError(
            f"Cyclic ownership path detected at table '{target_table}'."
        )
    visited.add(target_table)

    tmp_alias = counter.next()
    q = dialect.quote_identifier
    conditions = [f"{q(tmp_alias)}.{q(target_pk)} = {q(from_alias)}.{q(fk_col)}"]

    if len(chain) == 1:
        tgt_info = (
            tables_meta.get(target_table, {}) if isinstance(tables_meta, dict) else {}
        )
        user_col = tgt_info.get("user_col", "user_id")
        if not isinstance(user_col, str) or not IDENTIFIER_REGEX.match(user_col):
            raise SecurityError(f"Invalid user column identifier: '{user_col}'")
        conditions.append(f"{q(tmp_alias)}.{q(user_col)} = {dialect.placeholder}")
        params.append(user_id)
    else:
        nested = _build_chain_exists(
            dialect,
            tables_meta,
            tmp_alias,
            chain[1:],
            user_id,
            params,
            counter,
            current_depth=current_depth + 1,
            visited_tables=visited,
        )
        conditions.append(nested)

    where = " AND ".join(conditions)
    return f"EXISTS (SELECT 1 FROM {q(target_table)} {q(tmp_alias)} WHERE {where})"


def resolve_ownership_predicate(
    dialect: BaseDialect,
    tables_meta: dict[str, Any],
    alias: str,
    table: str,
    user_id: Any,
    params: list[Any],
    counter: AliasCounter | None = None,
    ownership_paths: dict[str, list[list[tuple[str, str, str]]]] | None = None,
) -> str:
    """
    Returns a SQL boolean expression asserting the row at `alias` (of `table`)
    is owned by `user_id`, appending any needed bind params to `params`.

    Fails closed: if `user_id` is None, or if `table` has no direct user column
    and no registered ownership chain, raises SecurityError instead of returning
    an unfiltered predicate.
    """
    if user_id is None:
        raise SecurityError("Tenant isolation requires a valid, non-null user_id.")
    if not isinstance(table, str) or not IDENTIFIER_REGEX.match(table):
        raise SecurityError(
            f"Invalid table identifier for ownership resolution: '{table}'"
        )
    if not isinstance(alias, str) or not IDENTIFIER_REGEX.match(alias):
        raise SecurityError(f"Invalid alias for ownership resolution: '{alias}'")

    meta = tables_meta if isinstance(tables_meta, dict) else {}
    tbl_info = meta.get(table, {})
    q = dialect.quote_identifier

    # 1. Direct user ownership column
    if tbl_info.get("has_user_id") or "user_id" in [
        c.get("name") if isinstance(c, dict) else str(c)
        for c in tbl_info.get("columns", [])
    ]:
        user_col = tbl_info.get("user_col", "user_id")
        if not isinstance(user_col, str) or not IDENTIFIER_REGEX.match(user_col):
            raise SecurityError(f"Invalid user column identifier: '{user_col}'")
        params.append(user_id)
        return f"{q(alias)}.{q(user_col)} = {dialect.placeholder}"

    # 2. Multi-hop ownership chain resolution
    paths = ownership_paths or {}
    chains = paths.get(table)
    if not chains or not isinstance(chains, list):
        raise SecurityError(
            f"Table '{table}' has no resolvable ownership path; refusing to query it without tenant isolation."
        )

    ctr = counter or AliasCounter()
    or_parts = [
        _build_chain_exists(
            dialect, meta, alias, chain, user_id, params, ctr, visited_tables={table}
        )
        for chain in chains
    ]
    return "(" + " OR ".join(or_parts) + ")"


# ---------------------------------------------------------------------------
# SSRF & Network Target Validation
# ---------------------------------------------------------------------------

#: Endpoints that hand out instance / task credentials. Blocked whatever the policy, and
#: whether written as an IP or reached through an IPv6 form that embeds the IPv4 address.
CLOUD_METADATA_IPS: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = {
    ipaddress.ip_address(
        "169.254.169.254"
    ),  # AWS / GCP / Azure / DigitalOcean / OCI IMDS
    ipaddress.ip_address("169.254.169.253"),  # AWS DNS
    ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS over IPv6
    ipaddress.ip_address("169.254.170.2"),  # AWS ECS / Fargate task credentials
    ipaddress.ip_address("169.254.170.23"),  # AWS EKS Pod Identity Agent
    ipaddress.ip_address("fd00:ec2::23"),  # AWS EKS Pod Identity Agent (IPv6)
    ipaddress.ip_address("168.63.129.16"),  # Azure WireServer
    ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud metadata
    ipaddress.ip_address("192.0.0.192"),  # Oracle Cloud (legacy) metadata
}

CLOUD_METADATA_HOSTNAMES: set[str] = {
    "metadata.google.internal",
    "metadata.internal",
    "metadata",
    "instance-data",
}

CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
IPV6_ULA_NETWORK = ipaddress.ip_network("fc00::/7")
IPV6_LINK_LOCAL_NETWORK = ipaddress.ip_network("fe80::/10")


IPV6_SITE_LOCAL_NETWORK = ipaddress.ip_network("fec0::/10")
IPV6_NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")
IPV6_NAT64_LOCAL_NETWORK = ipaddress.ip_network("64:ff9b:1::/48")
IPV6_IPV4_COMPAT_NETWORK = ipaddress.ip_network("::/96")
IPV6_6TO4_NETWORK = ipaddress.ip_network("2002::/16")
IPV6_TEREDO_NETWORK = ipaddress.ip_network("2001::/32")


def _embedded_ipv4(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> list[ipaddress.IPv4Address]:
    """IPv4 addresses an IPv6 address can tunnel to (mapped, NAT64, 6to4, Teredo, compat)."""
    if not isinstance(ip_obj, ipaddress.IPv6Address):
        return []
    out: list[ipaddress.IPv4Address] = []
    if ip_obj.ipv4_mapped is not None:
        out.append(ip_obj.ipv4_mapped)
    raw = int(ip_obj)
    if ip_obj in IPV6_NAT64_NETWORK or ip_obj in IPV6_IPV4_COMPAT_NETWORK:
        out.append(ipaddress.IPv4Address(raw & 0xFFFFFFFF))
    if ip_obj.sixtofour is not None:
        out.append(ip_obj.sixtofour)
    teredo = ip_obj.teredo
    if teredo is not None:
        out.extend(teredo)
    return out


def _is_cloud_metadata(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks if IP (or any IPv4 it embeds) is a known cloud instance metadata endpoint."""
    if ip_obj in CLOUD_METADATA_IPS:
        return True
    return any(v4 in CLOUD_METADATA_IPS for v4 in _embedded_ipv4(ip_obj))


def _is_private_or_restricted(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Checks whether IP belongs to private, loopback, link-local, or restricted subnets."""
    if _is_cloud_metadata(ip_obj):
        return True

    if any(_is_private_or_restricted(v4) for v4 in _embedded_ipv4(ip_obj)):
        return True

    if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
        return True
    if ip_obj.is_reserved or ip_obj.is_multicast or ip_obj.is_unspecified:
        return True

    if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in CGNAT_NETWORK:
        return True
    return bool(
        isinstance(ip_obj, ipaddress.IPv6Address)
        and (
            ip_obj in IPV6_ULA_NETWORK
            or ip_obj in IPV6_LINK_LOCAL_NETWORK
            or ip_obj in IPV6_SITE_LOCAL_NETWORK
            or ip_obj in IPV6_NAT64_LOCAL_NETWORK
            or ip_obj in IPV6_TEREDO_NETWORK
        )
    )


# ---------------------------------------------------------------------------
# DNS resolution (single, injectable) and address pinning
# ---------------------------------------------------------------------------

Resolver = Callable[[str, int], list[str]]


def _default_resolver(host: str, port: int) -> list[str]:
    """System resolver: every address (IPv4 and IPv6) the host currently maps to."""
    infos = socket.getaddrinfo(host, port or 0, proto=socket.IPPROTO_TCP)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


_resolver: Resolver = _default_resolver


def set_dns_resolver(resolver: Resolver | None) -> Resolver:
    """Replaces the process-wide resolver (None restores the system one); returns the
    previous one.  Used by tests (fake / rebinding resolvers) and by deployments that
    resolve through a vetted internal DNS service."""
    global _resolver
    previous = _resolver
    _resolver = resolver or _default_resolver
    return previous


@contextmanager
def dns_resolver(resolver: Resolver) -> Iterator[None]:
    previous = set_dns_resolver(resolver)
    try:
        yield
    finally:
        set_dns_resolver(previous)


_UNICODE_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})


def _normalize_host(host: Any) -> str:
    """Lower-cases, folds ideographic dots and drops a trailing root dot
    (``metadata.google.internal.`` is the same name as ``metadata.google.internal``)."""
    h = str(host).strip().lower().translate(_UNICODE_DOTS)
    while h.endswith(".") and len(h) > 1:
        h = h[:-1]
    return h


@dataclass(frozen=True)
class ResolvedTarget:
    """Outcome of resolving and validating a network target ONCE.

    ``addresses`` are all addresses the name resolved to; every one of them passed the
    egress policy.  ``pinned_address`` is the address a connection must use (so the
    validated DNS answer and the connected-to address cannot differ: no TOCTOU /
    DNS-rebinding window).  It is ``None`` when the host is an IP literal / localhost
    (nothing to pin) or the name did not resolve and ``fail_closed`` was not requested.
    """

    host: str
    port: int | None
    addresses: tuple[str, ...] = ()
    pinned_address: str | None = None


def resolve_and_validate_target(
    host: str,
    port: int | None = None,
    network_config: Any | None = None,
    *,
    resolver: Resolver | None = None,
    fail_closed: bool = False,
) -> ResolvedTarget:
    """Resolves ``host`` exactly once, validates EVERY resolved address, and returns the
    validated address to connect to.

    Unlike :func:`validate_network_target` (which validates and lets the driver resolve
    again), the caller connects to ``ResolvedTarget.pinned_address`` and so can never see
    a different DNS answer than the one that was validated.  ``fail_closed`` turns an
    unresolvable name into a ``SecurityError`` instead of the legacy "let the driver
    fail" fallback (which would leave a rebinding window: NXDOMAIN now, 10.0.0.5 later).
    """
    if network_config is None:
        from query_builder.config import get_security_config

        network_config = get_security_config().network
    collected: list[str] = []
    _validate_host_target(
        host,
        port,
        network_config,
        resolver=resolver,
        collect=collected,
        fail_closed=fail_closed,
    )
    pinned = collected[0] if collected else None
    return ResolvedTarget(
        host=_normalize_host(host),
        port=port,
        addresses=tuple(collected),
        pinned_address=pinned,
    )


def _validate_host_target(
    host: str,
    port: int | None,
    network_config: Any,
    *,
    resolver: Resolver | None = None,
    collect: list[str] | None = None,
    fail_closed: bool = False,
) -> None:
    """Validates an individual host/IP network egress target against SSRF rules.

    When ``collect`` is given, the validated addresses (the IP literal, or every address
    the name resolved to) are appended to it so the caller can pin the connection.
    """
    clean_host = _normalize_host(host)
    if not clean_host:
        return

    unbracketed_host = clean_host.strip("[]")

    # Hostname Whitelisting and Blacklisting
    if network_config.blocked_hostnames:
        for b in network_config.blocked_hostnames:
            pat = b.strip().lower()
            if pat.startswith("*.") and (
                clean_host.endswith(pat[1:])
                or clean_host == pat[2:]
                or unbracketed_host.endswith(pat[1:])
                or unbracketed_host == pat[2:]
            ):
                raise SecurityError(
                    f"Target host '{host}' is in blocked hostnames list."
                )
            if clean_host == pat or unbracketed_host == pat:
                raise SecurityError(
                    f"Target host '{host}' is in blocked hostnames list."
                )

    if network_config.allowed_hostnames:
        allowed = False
        for a in network_config.allowed_hostnames:
            pat = a.strip().lower()
            if pat.startswith("*.") and (
                clean_host.endswith(pat[1:])
                or clean_host == pat[2:]
                or unbracketed_host.endswith(pat[1:])
                or unbracketed_host == pat[2:]
            ):
                allowed = True
                break
            if clean_host == pat or unbracketed_host == pat:
                allowed = True
                break
        if not allowed:
            raise SecurityError(
                f"Target host '{host}' is not in allowed hostnames list."
            )

    # Cloud metadata hostname rejection
    if (
        clean_host in CLOUD_METADATA_HOSTNAMES
        or unbracketed_host in CLOUD_METADATA_HOSTNAMES
        or clean_host.endswith(".google.internal")
        or unbracketed_host.endswith(".google.internal")
    ):
        raise SecurityError(f"Access to cloud metadata target '{host}' is forbidden.")

    # IP Literal Check (supporting bracketed IPv4/IPv6 notation)
    try:
        ip_obj = ipaddress.ip_address(unbracketed_host)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False

    if is_ip_literal:
        if _is_cloud_metadata(ip_obj):
            raise SecurityError(
                f"Access to cloud metadata IP target '{host}' is strictly forbidden."
            )
        if not network_config.allow_private_networks and _is_private_or_restricted(
            ip_obj
        ):
            raise SecurityError(
                f"Access to private/internal network target '{host}' is forbidden."
            )
        if collect is not None:
            collect.append(str(ip_obj))
        return

    # Localhost check for hostnames
    if clean_host in ("localhost", "localhost.localdomain") or unbracketed_host in (
        "localhost",
        "localhost.localdomain",
    ):
        if not network_config.allow_private_networks:
            raise SecurityError(
                f"Access to loopback target '{host}' is forbidden when allow_private_networks is False."
            )
        return

    # DNS resolution: every returned address must pass.  The legacy path falls back to
    # "let the driver fail" for unresolvable names; ``fail_closed`` rejects them instead.
    try:
        resolved_strs = (resolver or _resolver)(unbracketed_host, port or 0)
        if fail_closed and not resolved_strs:
            raise SecurityError(f"Host '{host}' did not resolve to any address.")
        for resolved_ip_str in resolved_strs:
            resolved_ip = ipaddress.ip_address(resolved_ip_str)
            if _is_cloud_metadata(resolved_ip):
                raise SecurityError(
                    f"Host '{host}' resolves to forbidden cloud metadata IP '{resolved_ip_str}'."
                )
            if not network_config.allow_private_networks and _is_private_or_restricted(
                resolved_ip
            ):
                raise SecurityError(
                    f"Host '{host}' resolves to forbidden private/internal IP '{resolved_ip_str}'."
                )
            if collect is not None:
                collect.append(str(resolved_ip))
    except (socket.gaierror, socket.herror, OSError) as exc:
        if fail_closed:
            raise SecurityError(f"Host '{host}' could not be resolved.") from exc
        # Graceful offline fallback for unresolvable test or mock hostnames


_DSN_HOST_KEYS = ("hostname", "host", "server", "address", "addr", "data source")
_DSN_PORT_KEYS = ("port",)


def _parse_keyvalue_dsn(raw: str) -> tuple[str, int | None] | None:
    """Host/port of a ``KEY=value;KEY=value`` DSN (Db2, ODBC, ...), else ``None``.

    Such a string is not a ``host:port`` pair, so it must not be validated as one.
    ``None`` is returned for anything that is not a key/value list or names no host."""
    if "=" not in raw or "://" in raw:
        return None
    pairs: dict[str, str] = {}
    for part in raw.split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            pairs.setdefault(key.strip().lower(), value.strip())
    host_value = next((pairs[k] for k in _DSN_HOST_KEYS if pairs.get(k)), None)
    if host_value is None:
        return None
    port: int | None = None
    port_text = next((pairs[k] for k in _DSN_PORT_KEYS if pairs.get(k)), None)
    # ``Server=tcp:host,1433`` / ``host:1433`` carry the port in the host value.
    if host_value.lower().startswith("tcp:"):
        host_value = host_value[4:]
    if "," in host_value:
        host_value, _, port_text = host_value.partition(",")
    elif host_value.count(":") == 1:
        host_value, _, port_text = host_value.partition(":")
    if port_text:
        try:
            port = int(port_text.strip())
        except ValueError:
            port = None
    return host_value.strip(), port


#: Config keys / attribute names that carry a network address (``host``, ``db_host``,
#: ``gateway_url``, ``hosts``, ``bootstrap_servers``, ``connstr``, ``conninfo``, ...).
_ADDRESS_KEY_RE = re.compile(
    r"(?:^|_)(?:host|hosts|hostname|hostaddr|server|servers|address|addresses|addr|"
    r"endpoint|endpoints|url|urls|uri|uris|dsn|connstr|connection_string|conninfo|"
    r"node|nodes|broker|brokers|contact_points|seeds)$"
)
_KV_HOST_KEYS = frozenset(
    {"host", "hostname", "hostaddr", "server", "address", "addr", "data source"}
)
_INSECURE_SCHEMES = ("http", "ws", "ftp", "telnet")
_SCHEME_PREFIX_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.\-]*:)*$")
_TNS_HOST_RE = re.compile(r"\(\s*host\s*=\s*([^)\s]+)\s*\)", re.IGNORECASE)


def is_address_key(name: str) -> bool:
    """True when a config key / attribute name looks like it carries a network address."""
    return bool(_ADDRESS_KEY_RE.search(name.lower()))


def _split_hostport(token: str) -> tuple[str, int | None] | None:
    """``host``, ``host:port``, ``[v6]`` or ``[v6]:port`` -> ``(host, port)``; else ``None``."""
    token = token.strip()
    if not token or token.startswith(("/", ".", "~")) or "\\" in token:
        return None  # a unix socket or file path, not a network address
    if token.startswith("["):
        end = token.find("]")
        if end == -1:
            return None
        rest = token[end + 1 :]
        port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None
        return token[1:end], port
    if token.count(":") == 1:
        host, _, port_text = token.partition(":")
        return (host, int(port_text) if port_text.isdigit() else None) if host else None
    return token, None


def _authority_targets(authority: str) -> list[tuple[str, int | None]]:
    """Targets of ``[user[:pw]@]host[:port][,host[:port]...]`` (userinfo is dropped)."""
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    found = [_split_hostport(part) for part in authority.split(",")]
    return [t for t in found if t is not None]


def _keyvalue_targets(raw: str) -> list[tuple[str, int | None]] | None:
    """Targets of a ``KEY=value`` list separated by ``;`` (ODBC, Db2) or blanks (libpq).

    ``None`` when ``raw`` is not such a list. A host value may be a comma list
    (``host=a,b port=1,2``) and may carry a ``tcp:`` prefix or a ``,port`` suffix.
    """
    if "=" not in raw or "://" in raw:
        return None
    parts = raw.split(";") if ";" in raw else raw.split()
    pairs: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition("=")
        if sep and key.strip():
            pairs.setdefault(key.strip().lower(), value.strip().strip("'\""))
    if not pairs:
        return None
    out: list[tuple[str, int | None]] = []
    port_text = pairs.get("port", "")
    for key in _KV_HOST_KEYS:
        found_value = pairs.get(key)
        if not found_value:
            continue
        value = (
            found_value[4:] if found_value.lower().startswith("tcp:") else found_value
        )
        if "," in value and key in ("server", "data source", "address", "addr"):
            value, _, port_text = value.partition(",")  # ``Server=tcp:host,1433``
        for token in value.split(","):
            target = _split_hostport(token)
            if target is None:
                continue
            host, inline_port = target
            first_port = port_text.split(",")[0].strip()
            out.append(
                (
                    host,
                    inline_port or (int(first_port) if first_port.isdigit() else None),
                )
            )
    return out


def extract_address_targets(raw: str) -> list[tuple[str, int | None]]:
    """Every ``(host, port)`` a connection string / URL / address list may connect to.

    Understands URLs (also ``jdbc:vendor://...``, multi-host ``a:1,b:2``, userinfo),
    ``KEY=value`` DSNs, Oracle ``//host:port/svc`` and TNS descriptors, ``user@host:port/db``
    and plain comma lists. Unix sockets and file paths yield nothing.
    """
    raw = raw.strip()
    if not raw:
        return []
    if "(" in raw and _TNS_HOST_RE.search(raw):
        return [(h, None) for h in _TNS_HOST_RE.findall(raw)]
    kv = _keyvalue_targets(raw)
    if kv is not None:
        return kv
    marker = raw.find("//")
    if marker != -1 and _SCHEME_PREFIX_RE.match(raw[:marker]):
        authority = re.split(r"[/?#;]", raw[marker + 2 :], maxsplit=1)[0]
        return _authority_targets(authority)
    if raw.startswith(("/", ".", "~")):
        return []
    return _authority_targets(raw.split("/", 1)[0])


def _address_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [item for item in value if isinstance(item, str)]
    return []


def collect_target_config(owner: Any) -> dict[str, Any]:
    """``owner.config`` plus every address-like attribute the connector stored on itself
    (``gateway_url``, ``supabase_url``, ``servers``, ...), for the network-egress check."""
    config = getattr(owner, "config", None)
    target = dict(config) if config else {}
    for name in ("port", "flight_endpoint", "connection_string", "dsn", "server"):
        value = getattr(owner, name, None)
        if value is not None and name not in target:
            target[name] = value
    for name, value in vars(owner).items():
        if (
            not name.startswith("_")
            and name not in target
            and is_address_key(name)
            and _address_strings(value)
        ):
            target[name] = value
    return target


#: Keys whose value the first pass of ``validate_network_target`` already treats as a URL
#: (single-host ``scheme://`` form) ...
_FIRST_PASS_URL_KEYS = frozenset(
    {"url", "uri", "connection_string", "dsn", "endpoint", "flight_endpoint"}
)
#: ... and keys it already treats as a plain host name.
_FIRST_PASS_HOST_KEYS = _FIRST_PASS_URL_KEYS | frozenset(
    {"host", "hostname", "address", "server", "contact_points"}
)


def _first_pass_covers(
    key: str, raw: str, targets: list[tuple[str, int | None]]
) -> bool:
    """True when the first pass already validates ``raw`` exactly (so a second pass would
    only add a DNS lookup, and another chance for a rebinding answer)."""
    raw = raw.strip()
    if "://" in raw:
        return (
            key in _FIRST_PASS_URL_KEYS
            and len(targets) <= 1
            and not raw.lower().startswith("jdbc:")
        )
    return (
        key in _FIRST_PASS_HOST_KEYS and len(targets) == 1 and targets[0] == (raw, None)
    )


def _validate_address_keys(
    config: dict[str, Any], network_config: Any, already: set[tuple[str, int | None]]
) -> None:
    """Validate every address found under any address-like config key.

    This is what catches ``host="a,169.254.169.254"``, ``host="169.254.169.254:80"``,
    libpq ``host=... port=...``, JDBC / Oracle / TNS strings and driver-specific keys
    (``hosts``, ``servers``, ``connstr``, ``gateway_url``, ...) that name no host in the
    shapes the first pass understands.
    """
    for key, value in config.items():
        if not isinstance(key, str) or not is_address_key(key):
            continue
        for raw in _address_strings(value):
            targets = extract_address_targets(raw)
            if _first_pass_covers(key, raw, targets):
                continue  # resolved (and pinned) once already: no second DNS lookup
            for host, port in targets:
                if (host, port) in already:
                    continue
                already.add((host, port))
                validate_network_target(
                    host=host, port=port, network_config=network_config
                )
            if "://" in raw:
                if "," in raw.split("://", 1)[1].split("/", 1)[0]:
                    # a multi-host URL cannot be url-split; apply the TLS-scheme rule here
                    scheme = raw.split("://", 1)[0].lower()
                    if network_config.enforce_tls and scheme in _INSECURE_SCHEMES:
                        raise SecurityError(
                            f"TLS is enforced but URL uses insecure scheme: '{scheme}'"
                        )
                else:
                    parsed = urllib.parse.urlsplit(raw)
                    if parsed.scheme and parsed.hostname:  # keep the TLS-scheme rule
                        validate_network_target(url=raw, network_config=network_config)


def validate_network_target(
    host: str | None = None,
    port: int | None = None,
    url: str | None = None,
    config: dict[str, Any] | Any | None = None,
    network_config: Any | None = None,
) -> None:
    """
    Validates a network egress target against SSRF attacks, private subnet rules,
    hostname whitelists/blacklists, and transport security policies.

    Fails closed:
    - Blocks loopback, RFC 1918, link-local, CGNAT, and IPv6 ULA when allow_private_networks=False.
    - Cloud metadata (169.254.169.254, etc.) is strictly forbidden regardless of allow_private_networks.
    - Validates CA bundle file existence and enforces TLS when configured.
    """
    # 1. Resolve network_config
    if network_config is None:
        from query_builder.config import (
            NetworkSecurityConfig,
            SecurityConfig,
            get_security_config,
        )

        if isinstance(config, NetworkSecurityConfig):
            network_config = config
        elif isinstance(config, SecurityConfig):
            network_config = config.network
        elif isinstance(config, dict) and "security" in config:
            sec = config["security"]
            if isinstance(sec, SecurityConfig):
                network_config = sec.network
            elif isinstance(sec, NetworkSecurityConfig):
                network_config = sec
            else:
                network_config = get_security_config().network
        elif isinstance(config, dict) and "network" in config:
            net = config["network"]
            network_config = (
                net
                if isinstance(net, NetworkSecurityConfig)
                else get_security_config().network
            )
        else:
            network_config = get_security_config().network

    # 2. CA bundle file existence check
    if network_config.ca_bundle_path and not os.path.exists(
        network_config.ca_bundle_path
    ):
        raise SecurityError(
            f"CA bundle file does not exist: {network_config.ca_bundle_path}"
        )

    # 3. Extract connection properties from config if not provided
    if config is not None and isinstance(config, dict):
        if host is None:
            host = (
                config.get("host")
                or config.get("hostname")
                or config.get("address")
                or config.get("server")
            )
        if port is None:
            port = config.get("port")

        candidate_urls: list[str] = []
        for key in (
            "url",
            "uri",
            "connection_string",
            "dsn",
            "endpoint",
            "flight_endpoint",
        ):
            val = config.get(key)
            if val is not None:
                val_str = str(val).strip()
                if val_str and val_str not in candidate_urls:
                    candidate_urls.append(val_str)

        for raw_str in candidate_urls:
            kv_target = _parse_keyvalue_dsn(raw_str)
            if kv_target is not None:
                kv_host, kv_port = kv_target
                if host is None:
                    host = kv_host
                elif kv_host != host:
                    validate_network_target(
                        host=kv_host,
                        port=kv_port or port,
                        network_config=network_config,
                    )
                if port is None and kv_port is not None:
                    port = kv_port
                continue
            if "://" in raw_str:
                if "," in raw_str.split("://", 1)[1].split("/", 1)[0]:
                    continue  # multi-host (replica set): validated host by host below
                if url is None:
                    url = raw_str
                elif raw_str != url:
                    validate_network_target(
                        url=raw_str,
                        network_config=network_config,
                    )
            else:
                if ":" in raw_str and not raw_str.startswith("["):
                    parts = raw_str.rsplit(":", 1)
                    raw_host = parts[0]
                    raw_port = None
                    try:
                        raw_port = int(parts[1])
                    except ValueError:
                        pass
                else:
                    raw_host = raw_str
                    raw_port = None

                if host is None:
                    host = raw_host
                elif raw_host != host:
                    validate_network_target(
                        host=raw_host,
                        port=raw_port or port,
                        network_config=network_config,
                    )
                if port is None and raw_port is not None:
                    port = raw_port

        contact_points = config.get("contact_points")
        if contact_points:
            if isinstance(contact_points, str):
                pts = [p.strip() for p in contact_points.split(",") if p.strip()]
            elif isinstance(contact_points, (list, tuple, set)):
                pts = list(contact_points)
            else:
                pts = [contact_points]
            for pt in pts:
                pt_host = str(pt).strip()
                pt_port = port
                if ":" in pt_host and not pt_host.startswith("["):
                    p_parts = pt_host.rsplit(":", 1)
                    pt_host = p_parts[0]
                    try:
                        pt_port = int(p_parts[1])
                    except ValueError:
                        pass
                validate_network_target(
                    host=pt_host,
                    port=pt_port,
                    network_config=network_config,
                )

        _validate_address_keys(config, network_config, set())

    parsed_url = None
    if url:
        try:
            parsed_url = urllib.parse.urlsplit(url)
        except ValueError as exc:
            raise SecurityError(f"Invalid network target URL '{url}': {exc}") from exc

    # 4. Enforce TLS settings
    if network_config.enforce_tls:
        if parsed_url:
            scheme = parsed_url.scheme.lower()
            if scheme in ("http", "ws", "ftp", "telnet"):
                raise SecurityError(
                    f"TLS is enforced but URL uses insecure scheme: '{scheme}'"
                )
        if config is not None and isinstance(config, dict):
            ssl_val = config.get("ssl")
            tls_val = config.get("tls")
            sslmode_val = str(config.get("sslmode", "")).lower()
            if (
                ssl_val is False
                or tls_val is False
                or sslmode_val in ("disable", "disabled")
            ):
                raise SecurityError(
                    "TLS is enforced but SSL/TLS is explicitly disabled in configuration."
                )

    # 5. Extract host/port from URL if needed
    url_host: str | None = None
    url_port: int | None = None
    if parsed_url:
        if parsed_url.hostname:
            url_host = parsed_url.hostname
        try:
            if parsed_url.port is not None:
                url_port = parsed_url.port
        except ValueError as exc:
            raise SecurityError(f"Invalid network target URL port: {exc}") from exc

    # 6. Default host and port from URL if not specified
    if host is None:
        host = url_host
    if port is None:
        port = url_port

    # Validate primary port
    if port is not None:
        try:
            port_num = int(port)
            if not (1 <= port_num <= 65535):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise SecurityError(f"Invalid network port: {port}") from exc

    # Validate distinct URL port if both were provided
    if url_port is not None and url_port != port and not (1 <= url_port <= 65535):
        raise SecurityError(f"Invalid network port: {url_port}")

    # If no host is targeted, validation succeeds
    if host is None:
        return

    # 7. Validate primary host target
    _validate_host_target(host, port, network_config)

    # 8. If URL provided a distinct hostname, validate it as well
    if url_host is not None and (
        str(url_host).strip().lower() != str(host).strip().lower()
        or (url_port is not None and url_port != port)
    ):
        _validate_host_target(url_host, url_port or port, network_config)


# ---------------------------------------------------------------------------
# Secret Scrubbing
# ---------------------------------------------------------------------------

DEFAULT_SCRUB_PATTERNS: list[str] = [
    r"(?i)(password|passwd|pwd|secret|token)",
    r"(?i)(?:^|[\s_-])(auth|authorization|api[_-]?key|private[_-]?key|secret[_-]?key)(?:$|[\s_-])",
    r"(?i)(?:^|[\s-])key(?:$|[\s-])",
]

# A URI scheme starts with a letter, but only the first letter of a run of scheme
# characters can start a match: anchoring at the run start (and absorbing its leading
# digits/punctuation into group 1, which the replacement re-emits) keeps the scan linear.
URI_CREDENTIAL_REGEX = re.compile(
    r"(?<![a-zA-Z0-9+.-])([0-9+.-]*[a-zA-Z][a-zA-Z0-9+.-]*://[^/:@]+:)([^@/]+)(@)"
)
BEARER_TOKEN_REGEX = re.compile(r"(?i)\b(bearer\s+)[^\s,;'\"\]]+")
KEY_VALUE_SECRET_REGEX = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|auth)\s*([:=])\s*([^\s,;'\"\]]+|[\"'][^\"']+[\"'])"
)


def _mask_uri(m: re.Match[str]) -> str:
    return f"{m.group(1)}***{m.group(3)}"


def _mask_bearer(m: re.Match[str]) -> str:
    return f"{m.group(1)}***"


def _mask_key_value(m: re.Match[str]) -> str:
    return f"{m.group(1)}{m.group(2)}***"


def _scrub_string(text: str) -> str:
    """Sanitizes connection URI credentials, bearer tokens, and key-value secrets in text.

    Replacements are functions rather than template strings on purpose: on Python 3.11 and
    earlier, ``re.sub`` with a template string imports a module through ``builtins.__import__``
    while it runs, so scrubbing an error message while a caller (or a test) has that hook
    patched would itself raise ImportError and mask the original error.
    """
    text = URI_CREDENTIAL_REGEX.sub(_mask_uri, text)
    text = BEARER_TOKEN_REGEX.sub(_mask_bearer, text)
    text = KEY_VALUE_SECRET_REGEX.sub(_mask_key_value, text)
    return text


def scrub_secrets(value: Any, patterns: list[str] | None = None) -> Any:
    """
    Recursively scrubs sensitive keys, connection passwords, tokens, and API credentials
    from dictionaries, lists, tuples, sets, strings, and exception representations.
    """
    active_patterns = patterns or DEFAULT_SCRUB_PATTERNS
    compiled_patterns = [re.compile(p) for p in active_patterns]

    def _scrub(val: Any) -> Any:
        if isinstance(val, dict):
            new_dict: dict[str, Any] = {}
            for k, v in val.items():
                k_str = str(k)
                if any(p.search(k_str) for p in compiled_patterns):
                    new_dict[k] = "***"
                else:
                    new_dict[k] = _scrub(v)
            return new_dict
        if isinstance(val, list):
            return [_scrub(item) for item in val]
        if isinstance(val, tuple):
            return tuple(_scrub(item) for item in val)
        if isinstance(val, set):
            return {_scrub(item) for item in val}
        if isinstance(val, str):
            return _scrub_string(val)
        if isinstance(val, Exception):
            return type(val)(_scrub_string(str(val)))
        return val

    return _scrub(value)


# ---------------------------------------------------------------------------
# AST Complexity & Execution Sandboxing
# ---------------------------------------------------------------------------


def calculate_ast_complexity(spec: dict[str, Any] | QuerySpec) -> int:
    """
    Calculates deterministic AST complexity score across projections, joins,
    filters, subqueries, group by, order by, and window functions.
    """
    if isinstance(spec, QuerySpec) or hasattr(spec, "__dataclass_fields__"):
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore[arg-type]  # narrowed to a dataclass by the __dataclass_fields__ check
    elif isinstance(spec, dict):
        spec_dict = spec
    else:
        return 0

    table = spec_dict.get("table")
    if isinstance(table, (dict, QuerySpec)) or hasattr(table, "__dataclass_fields__"):
        subq_tbl: Any = (
            table.get("subquery", table)
            if isinstance(table, dict) and "subquery" in table
            else table
        )
        sub_score = (
            calculate_ast_complexity(subq_tbl)
            if isinstance(subq_tbl, (dict, QuerySpec))
            or hasattr(subq_tbl, "__dataclass_fields__")
            else 0
        )
        if sub_score == 0:
            return 0
        score = 5 + sub_score
    elif isinstance(table, str) and table.strip():
        score = 1  # Base query table
    else:
        return 0

    # Projections / columns
    for col in spec_dict.get("columns", []):
        score += 1
        if isinstance(col, dict):
            if col.get("agg") or col.get("aggregation") or col.get("func"):
                score += 2
            if col.get("distinct"):
                score += 1
        elif isinstance(col, str):
            col_upper = col.upper()
            if any(
                agg in col_upper for agg in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX(")
            ):
                score += 2

    # Joins
    for join in spec_dict.get("joins", []):
        if isinstance(join, dict):
            j_type = str(join.get("type", "LEFT")).upper()
        else:
            j_type = str(getattr(join, "type", "LEFT")).upper()

        if j_type.startswith(("CROSS", "FULL")):
            score += 10
        else:
            score += 5

    # Filters
    for flt in spec_dict.get("filters", []):
        score += 2
        op = flt.get("op", "") if isinstance(flt, dict) else getattr(flt, "op", "")
        if str(op).lower() in ("like", "ilike", "regex", "matches"):
            score += 3
        val = flt.get("value") if isinstance(flt, dict) else getattr(flt, "value", None)
        subq = (
            flt.get("subquery")
            if isinstance(flt, dict)
            else getattr(flt, "subquery", None)
        )
        target_subq = (
            subq
            if isinstance(subq, (dict, QuerySpec))
            else (val if isinstance(val, (dict, QuerySpec)) else None)
        )
        if target_subq is not None:
            score += 10 + calculate_ast_complexity(target_subq)

    # Group By
    group_by = spec_dict.get("group_by", [])
    if group_by:
        score += 3 + len(group_by)

    # Having
    having = spec_dict.get("having", [])
    if having:
        score += 3 + (2 * len(having))

    # Order By
    order_by = spec_dict.get("order_by", [])
    if order_by:
        score += 2 + len(order_by)

    # Subqueries / CTEs
    ctes = spec_dict.get("ctes") or spec_dict.get("subqueries") or []
    for cte in ctes:
        score += 10
        if isinstance(cte, dict):
            cte_query = cte.get("query") or cte
            if isinstance(cte_query, (dict, QuerySpec)):
                score += calculate_ast_complexity(cte_query)
        elif isinstance(cte, QuerySpec):
            score += calculate_ast_complexity(cte)
        elif hasattr(cte, "query"):
            cte_query = getattr(cte, "query", None)
            if isinstance(cte_query, (dict, QuerySpec)):
                score += calculate_ast_complexity(cte_query)

    # Window functions
    win_funcs = spec_dict.get("window_functions") or spec_dict.get("window")
    if win_funcs:
        score += 5 * len(win_funcs) if isinstance(win_funcs, list) else 5

    # Vector search
    if spec_dict.get("vector_search"):
        score += 5

    # Hybrid search
    if spec_dict.get("hybrid_search"):
        score += 8

    # Set Operations
    set_ops = spec_dict.get("set_operations") or []
    for so in set_ops:
        score += 10
        if isinstance(so, dict):
            q = so.get("query")
            if isinstance(q, (dict, QuerySpec)):
                score += calculate_ast_complexity(q)
        elif hasattr(so, "query"):
            q = so.query
            if isinstance(q, (dict, QuerySpec)):
                score += calculate_ast_complexity(q)

    # Case When columns
    cols = spec_dict.get("columns") or []
    for c in cols:
        if isinstance(c, dict) and "case_when" in c:
            cw = c["case_when"]
            branches = (
                cw.get("branches", [])
                if isinstance(cw, dict)
                else getattr(cw, "branches", [])
            )
            score += 2 * max(1, len(branches))

    # Grouping Type
    if spec_dict.get("grouping_type"):
        score += 4

    return score


def check_cartesian_products(spec: dict[str, Any] | QuerySpec) -> None:
    """
    Validates query specification to detect unbounded Cartesian products,
    missing join conditions, or prohibited CROSS JOIN expressions.
    """
    if isinstance(spec, QuerySpec) or hasattr(spec, "__dataclass_fields__"):
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore[arg-type]  # narrowed to a dataclass by the __dataclass_fields__ check
    elif isinstance(spec, dict):
        spec_dict = spec
    else:
        return

    joins = spec_dict.get("joins", [])
    if not joins:
        return

    for join in joins:
        if isinstance(join, dict):
            j_tbl = join.get("table", "unknown")
            j_type = str(join.get("type", "LEFT")).upper()
            on_conds = join.get("on")
            left_col = join.get("left_col") or join.get("left")
            right_col = join.get("right_col") or join.get("right")
            has_fk = bool(join.get("foreign_key") or join.get("relationship"))
        else:
            j_tbl = getattr(join, "table", "unknown")
            j_type = str(getattr(join, "type", "LEFT")).upper()
            on_conds = getattr(join, "on", None)
            left_col = getattr(join, "left_col", None)
            right_col = getattr(join, "right_col", None)
            has_fk = False

        if j_type.strip().startswith("CROSS"):
            raise SecurityError(
                f"Cartesian product detected: explicit CROSS JOIN on table '{j_tbl}' is forbidden."
            )

        has_on = bool(on_conds) and (
            len(on_conds) > 0 if isinstance(on_conds, (list, tuple)) else True
        )
        has_cols = bool(left_col and right_col)

        if not has_on and not has_cols and not has_fk:
            raise SecurityError(
                f"Cartesian product detected: join on table '{j_tbl}' lacks join conditions or foreign key relations."
            )


# ---------------------------------------------------------------------------
# Privacy Governance & Column Masking
# ---------------------------------------------------------------------------


def apply_column_masking(value: Any, strategy: str = "redact") -> Any:
    """
    Applies data masking strategy ('redact', 'hash', 'md5', 'sha256', 'null',
    'partial', 'partial_email', 'partial_phone', 'last4') to a given value.
    """
    if value is None:
        return None

    strat = strategy.lower().strip()
    if strat == "redact":
        return "[REDACTED]"
    if strat == "null":
        return None
    if strat in ("hash", "sha256"):
        val_str = str(value)
        return hashlib.sha256(val_str.encode("utf-8")).hexdigest()
    if strat == "md5":
        val_str = str(value)
        return hashlib.md5(val_str.encode("utf-8"), usedforsecurity=False).hexdigest()
    if strat == "partial":
        val_str = str(value)
        if len(val_str) <= 2:
            return "***"
        if len(val_str) <= 4:
            return f"{val_str[0]}***{val_str[-1]}"
        return f"{val_str[:2]}***{val_str[-2:]}"
    if strat == "partial_email":
        val_str = str(value)
        if "@" in val_str:
            local, domain = val_str.split("@", 1)
            prefix = local[:2] if len(local) >= 2 else local[:1]
            return f"{prefix}***@{domain}"
        return f"{val_str[:2]}***@***" if len(val_str) >= 2 else "***@***"
    if strat == "partial_phone":
        val_str = str(value)
        return f"***-***-{val_str[-4:]}" if len(val_str) >= 4 else "***"
    if strat == "last4":
        val_str = str(value)
        return f"****{val_str[-4:]}" if len(val_str) >= 4 else "****"
    raise ValueError(
        f"Unknown masking strategy: '{strategy}'. Supported strategies: "
        "'redact', 'hash', 'md5', 'sha256', 'null', 'partial', 'partial_email', 'partial_phone', 'last4'."
    )
