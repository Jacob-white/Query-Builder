"""Opt-in secure mode for the built-in HTTP server (``create_server(security=...)``).

By default the server trusts the request: the connection settings (``connector`` / ``config``), the
``tenant_id`` and the security ``policy`` all come from the request body, there is no
authentication, and tenant isolation is applied only when the request happens to carry a tenant.
That is a reference microservice for a trusted caller, not a security boundary.

Secure mode turns the server into one. Everything below is enforced in ONE place, before any
route handler runs (:func:`secure_request`), so no endpoint can be forgotten:

* only a small allow-list of endpoints is served (compile, validate, execute, explain, health,
  docs); connection management, templates, telemetry, NLQ, streaming and export are refused;
* the client may not send ``tenant_id``, ``policy``, ``config`` or ``connector`` - the tenant comes
  from the operator's ``tenant_resolver`` (your authentication), the policy from the operator,
  the connection from a pool the operator registered;
* raw SQL is refused (it is validated but cannot be rewritten to add tenant predicates);
* when tenant isolation is enabled and no tenant resolves, the request fails closed (401);
* the spec is rewritten once with the resolved tenant and the server-side policy;
* no CORS headers are sent unless origins are listed.

See docs/SECURE_DEPLOYMENT.md.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from query_builder.config import get_security_config
from query_builder.exceptions import SecurityError
from query_builder.policy import SecurityPolicy, TenantContext, apply_security_policy

__all__ = [
    "SECURE_ENDPOINTS",
    "SecureRequestError",
    "ServerSecurity",
    "header_tenant_resolver",
    "insecure_mode_notice",
    "secure_request",
]

#: ``(method, path)`` pairs served in secure mode (aliases included).
SECURE_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("POST", "/api/v1/compile"),
        ("POST", "/api/v1/validate"),
        ("POST", "/api/v1/execute"),
        ("POST", "/api/query"),
        ("POST", "/api/v1/query/execute"),
        ("POST", "/api/v1/explain"),
        ("POST", "/api/query/explain"),
    }
)
_EXECUTE_PATHS = frozenset({"/api/v1/execute", "/api/query", "/api/v1/query/execute"})
_SPEC_PATHS = _EXECUTE_PATHS | {"/api/v1/compile"}
_EXPLAIN_PATHS = frozenset({"/api/v1/explain", "/api/query/explain"})
#: fields a client must never choose in secure mode
_FORBIDDEN_FIELDS = ("tenant_id", "policy", "config")
_MAX_TENANT_ID_LENGTH = 128

TenantResolver = Callable[[Mapping[str, str]], str | None]


class SecureRequestError(Exception):
    """A request refused by secure mode; carries the HTTP status and error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def header_tenant_resolver(header: str = "X-Tenant-ID") -> TenantResolver:
    """Resolve the tenant from a request header.

    **Only safe behind a reverse proxy that authenticates the caller and sets (overwrites) this
    header**: a header the client can send is exactly as trustworthy as a body field. For real
    authentication pass your own resolver (verify a token, return the tenant it names).
    """
    wanted = header.lower()

    def resolve(headers: Mapping[str, str]) -> str | None:
        for name, value in headers.items():
            if name.lower() == wanted:
                text = str(value).strip()
                if text and len(text) <= _MAX_TENANT_ID_LENGTH and "," not in text:
                    return text
        return None

    return resolve


@dataclass(frozen=True)
class ServerSecurity:
    """Secure-mode settings for :func:`query_builder.server.create_server`."""

    #: ``headers -> tenant id`` (``None`` = unauthenticated / unknown). Your authentication.
    tenant_resolver: TenantResolver
    #: applied to every spec together with the resolved tenant; never taken from the client
    policy: SecurityPolicy | None = None
    #: schema used for ownership chains; never taken from the client
    schema: dict[str, Any] | None = None
    #: pool used when the request names none; pools are registered by the operator
    default_connection_id: str = "default"
    #: ``None`` follows ``privacy.enforce_tenant_isolation`` of the active security config
    require_tenant: bool | None = None
    #: allow raw ``sql`` (validated but NOT isolated per tenant); off by default
    allow_raw_sql: bool = False
    #: extra ``(method, path)`` endpoints the operator takes responsibility for
    extra_endpoints: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    #: origins that may call the server from a browser; empty = no CORS headers at all
    cors_origins: tuple[str, ...] = ()

    def allowed(self, method: str, path: str) -> bool:
        return (method, path) in SECURE_ENDPOINTS or (
            method,
            path,
        ) in self.extra_endpoints

    def tenant_required(self) -> bool:
        if self.require_tenant is not None:
            return self.require_tenant
        return bool(get_security_config().privacy.enforce_tenant_isolation)

    def cors_origin_for(self, origin: str | None) -> str | None:
        return origin if origin and origin in self.cors_origins else None


def secure_request(
    security: ServerSecurity,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: Any,
    has_pool: Callable[[str], bool],
) -> Any:
    """Check a request against secure mode and return the body the handler may see.

    Raises :class:`SecureRequestError` to refuse it. The returned body carries no tenant or policy
    (so the handler's own policy step is a no-op), a registered ``connection_id`` for execute
    endpoints, and specs already rewritten for the resolved tenant.
    """
    if not security.allowed(method, path):
        raise SecureRequestError(
            403,
            "NOT_AVAILABLE_IN_SECURE_MODE",
            f"{method} {path} is not served in secure mode",
        )
    if method != "POST":
        return body
    if not isinstance(body, dict):
        raise SecureRequestError(
            400, "BAD_REQUEST", "Request body must be a JSON object."
        )

    forbidden = [name for name in _FORBIDDEN_FIELDS if name in body]
    if path in _EXECUTE_PATHS | _EXPLAIN_PATHS and "connector" in body:
        forbidden.append("connector")
    if forbidden:
        raise SecureRequestError(
            403,
            "FORBIDDEN_FIELD",
            "In secure mode the server, not the client, chooses: "
            + ", ".join(sorted(forbidden)),
        )
    if (
        not security.allow_raw_sql
        and (body.get("sql") or body.get("raw_sql"))
        and path not in {"/api/v1/validate"}
    ):
        raise SecureRequestError(
            403,
            "RAW_SQL_FORBIDDEN",
            "Raw SQL cannot be isolated per tenant; send a spec.",
        )

    try:
        tenant = security.tenant_resolver(headers)
    except Exception:  # noqa: BLE001 - a failing authenticator must fail closed, not crash
        tenant = None
    if tenant is None and security.tenant_required() and path in _SPEC_PATHS:
        raise SecureRequestError(
            401,
            "TENANT_REQUIRED",
            "No tenant could be resolved for this request.",
        )

    out = dict(body)
    if path in _EXECUTE_PATHS:
        connection_id = security.default_connection_id
        if not has_pool(connection_id):
            raise SecureRequestError(
                404, "UNKNOWN_CONNECTION", "No such connection is registered."
            )
        out["connection_id"] = connection_id
    if path in _SPEC_PATHS:
        context = TenantContext(tenant_id=tenant) if tenant else None
        for key in ("spec", "query"):
            if isinstance(out.get(key), dict):
                try:
                    out[key] = apply_security_policy(
                        out[key],
                        schema=security.schema,
                        context=context,
                        policy=security.policy,
                    )
                except SecurityError as exc:
                    raise SecureRequestError(403, "FORBIDDEN", str(exc)) from None
    return out


def insecure_mode_notice(entry: str, secure: bool = False) -> list[str]:
    """Lines to print at start-up so nobody runs the default mode unaware.

    ``entry`` names the entry point (``serve`` / ``mcp``). Returns nothing in secure mode.
    """
    if secure:
        return []
    from types import SimpleNamespace

    from query_builder.connectors.base import effective_network_config

    lines = [f"query-builder {entry}: SECURITY NOTICE (default mode)"]
    if entry == "serve":
        lines += [
            "  - no authentication: connection settings (`config`), `tenant_id` and `policy` are taken",
            "    from the request body, and tenant isolation applies only if a request carries them",
            "  - run `query-builder serve --secure ...` (or create_server(security=ServerSecurity(...)))",
            "    to have the server, not the client, choose tenant, policy and connection",
        ]
    else:
        lines += [
            "  - no authentication: the connector and its settings come from each tool call, i.e. from",
            "    the AI agent or client, and there is no tenant context",
        ]
    net = effective_network_config(SimpleNamespace(_explicit_security=False))
    if net is not None and (net.allow_private_networks or not net.enforce_tls):
        lines.append(
            "  - network policy: private/internal addresses "
            + ("ALLOWED" if net.allow_private_networks else "blocked")
            + ", TLS "
            + ("enforced" if net.enforce_tls else "NOT enforced")
            + " (set QB_SECURITY_PROFILE=production or pass --profile)"
        )
    lines.append("  - see docs/SECURE_DEPLOYMENT.md")
    return lines
