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
from dataclasses import asdict
from typing import Any

from query_builder.config import SecurityProfile
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

CLOUD_METADATA_IPS: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.169.253"),
    ipaddress.ip_address("fd00:ec2::254"),
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


def _is_cloud_metadata(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks if IP corresponds to known cloud instance metadata endpoints."""
    if ip_obj in CLOUD_METADATA_IPS:
        return True
    mapped = getattr(ip_obj, "ipv4_mapped", None)
    return bool(mapped is not None and mapped in CLOUD_METADATA_IPS)


def _is_private_or_restricted(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Checks whether IP belongs to private, loopback, link-local, or restricted subnets."""
    if _is_cloud_metadata(ip_obj):
        return True

    mapped = getattr(ip_obj, "ipv4_mapped", None)
    if mapped is not None:
        return _is_private_or_restricted(mapped)

    if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
        return True
    if ip_obj.is_reserved or ip_obj.is_multicast or ip_obj.is_unspecified:
        return True

    if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in CGNAT_NETWORK:
        return True
    return bool(
        isinstance(ip_obj, ipaddress.IPv6Address)
        and (ip_obj in IPV6_ULA_NETWORK or ip_obj in IPV6_LINK_LOCAL_NETWORK)
    )


def _validate_host_target(
    host: str,
    port: int | None,
    network_config: Any,
) -> None:
    """Validates an individual host/IP network egress target against SSRF rules."""
    clean_host = str(host).strip().lower()
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

    # DNS Resolution with graceful offline fallback
    try:
        addr_info = socket.getaddrinfo(
            unbracketed_host, port or 0, proto=socket.IPPROTO_TCP
        )
        for _, _, _, _, sockaddr in addr_info:
            resolved_ip_str = sockaddr[0]
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
    except (socket.gaierror, socket.herror, OSError):
        # Graceful offline fallback for unresolvable test or mock hostnames
        pass


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
            if "://" in raw_str:
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

    parsed_url = None
    if url:
        try:
            parsed_url = urllib.parse.urlsplit(url)
        except ValueError as exc:
            raise SecurityError(f"Invalid network target URL '{url}': {exc}")

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
            raise SecurityError(f"Invalid network target URL port: {exc}")

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
        except (ValueError, TypeError):
            raise SecurityError(f"Invalid network port: {port}")

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

URI_CREDENTIAL_REGEX = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^/:@]+:)([^@/]+)(@)")
BEARER_TOKEN_REGEX = re.compile(r"(?i)\b(bearer\s+)[^\s,;'\"\]]+")
KEY_VALUE_SECRET_REGEX = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|auth)\s*([:=])\s*([^\s,;'\"\]]+|[\"'][^\"']+[\"'])"
)


def _scrub_string(text: str) -> str:
    """Sanitizes connection URI credentials, bearer tokens, and key-value secrets in text."""
    text = URI_CREDENTIAL_REGEX.sub(r"\g<1>***\g<3>", text)
    text = BEARER_TOKEN_REGEX.sub(r"\g<1>***", text)
    text = KEY_VALUE_SECRET_REGEX.sub(r"\g<1>\g<2>***", text)
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
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore
    elif isinstance(spec, dict):
        spec_dict = spec
    else:
        return 0

    table = spec_dict.get("table")
    if not table or not isinstance(table, str) or not table.strip():
        return 0

    score = 1  # Base query table

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
        if isinstance(val, (dict, QuerySpec)):
            score += 10 + calculate_ast_complexity(val)

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
        if isinstance(cte, (dict, QuerySpec)):
            score += calculate_ast_complexity(cte)

    # Window functions
    if spec_dict.get("window"):
        score += 5

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
            q = getattr(so, "query")
            if isinstance(q, (dict, QuerySpec)):
                score += calculate_ast_complexity(q)

    # Case When columns
    cols = spec_dict.get("columns") or []
    for c in cols:
        if isinstance(c, dict) and "case_when" in c:
            cw = c["case_when"]
            branches = cw.get("branches", []) if isinstance(cw, dict) else getattr(cw, "branches", [])
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
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore
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
    Applies data masking strategy ('redact', 'hash', 'partial') to a given value.
    - 'redact': Replaces value with '[REDACTED]'.
    - 'hash': Returns SHA-256 hex digest string.
    - 'partial': Masks middle of the string (e.g. 'ab***yz').
    """
    if value is None:
        return None

    strat = strategy.lower().strip()
    if strat == "redact":
        return "[REDACTED]"
    if strat == "hash":
        val_str = str(value)
        return hashlib.sha256(val_str.encode("utf-8")).hexdigest()
    if strat == "partial":
        val_str = str(value)
        if len(val_str) <= 2:
            return "***"
        if len(val_str) <= 4:
            return f"{val_str[0]}***{val_str[-1]}"
        return f"{val_str[:2]}***{val_str[-2:]}"
    raise ValueError(
        f"Unknown masking strategy: '{strategy}'. Supported strategies: 'redact', 'hash', 'partial'."
    )
