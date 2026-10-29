"""Secure mode of the built-in HTTP server: the server, not the client, chooses tenant, policy and
connection. Real sqlite data (two tenants), a real server, real HTTP requests.

Every refusal is paired with a CONTROL against the default (request-trusting) server, which accepts
the same request, so a passing test shows secure mode is what stopped it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from query_builder.connectors.registry import get_connector
from query_builder.pool import ConnectionPool, ConnectionPoolManager
from query_builder.server import create_server
from query_builder.server_security import (
    SECURE_ENDPOINTS,
    SecureRequestError,
    ServerSecurity,
    header_tenant_resolver,
    insecure_mode_notice,
    secure_request,
)

SPEC = {"table": "orders", "columns": ["id", "amount", "tenant_id"]}
ACME = {"X-Tenant-ID": "acme"}
RIVAL = {"X-Tenant-ID": "rival"}


class Client:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, dict[str, str]]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                raw, status, hdrs = res.read(), res.status, dict(res.headers)
        except urllib.error.HTTPError as err:
            raw, status, hdrs = err.read(), err.code, dict(err.headers)
        try:
            return status, json.loads(raw), hdrs
        except ValueError:
            return status, raw.decode("utf-8", "replace"), hdrs

    def post(self, path: str, body: Any, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
        return self.request("POST", path, body, headers)


def error_code(out: Any) -> str | None:
    return out["error"]["code"] if isinstance(out, dict) and "error" in out else None


def tenants(out: Any) -> list[str]:
    return sorted({r["tenant_id"] for r in out["rows"]})


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = str(tmp_path_factory.mktemp("secure") / "orders.db")
    con = sqlite3.connect(path)
    con.execute("create table orders (id integer, amount integer, tenant_id text)")
    con.executemany(
        "insert into orders values (?, ?, ?)",
        [(1, 10, "acme"), (2, 20, "acme"), (3, 999, "rival")],
    )
    con.commit()
    con.close()
    return path


def _manager(db_path: str) -> ConnectionPoolManager:
    mgr = ConnectionPoolManager()
    mgr.register_pool(
        "default",
        ConnectionPool(
            factory=lambda: get_connector("sqlite", database=db_path).connect(),
            max_size=2,
        ),
        metadata={"connector": "sqlite", "dialect": "sqlite"},
    )
    return mgr


def _serve(**kwargs: Any) -> tuple[Any, Client]:
    server = create_server("127.0.0.1", 0, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, Client(int(server.server_address[1]))


@pytest.fixture(scope="module")
def secure(db_path: str) -> Iterator[Client]:
    server, client = _serve(
        connection_pool_manager=_manager(db_path),
        security=ServerSecurity(
            tenant_resolver=header_tenant_resolver("X-Tenant-ID"), require_tenant=True
        ),
    )
    yield client
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def default(db_path: str) -> Iterator[Client]:
    """The default server: trusts whatever the request says (the control)."""
    server, client = _serve(connection_pool_manager=_manager(db_path))
    yield client
    server.shutdown()
    server.server_close()


# ------------------------------------------------------------------ it works
def test_each_tenant_sees_only_its_own_rows(secure: Client) -> None:
    for headers, expected in ((ACME, ["acme"]), (RIVAL, ["rival"])):
        status, out, _ = secure.post("/api/v1/execute", {"spec": SPEC}, headers)
        assert status == 200, out
        assert tenants(out) == expected


def test_the_tenant_comes_from_the_header_whatever_case_it_is_sent_in(
    secure: Client,
) -> None:
    status, out, _ = secure.post(
        "/api/v1/execute", {"spec": SPEC}, {"x-tenant-id": "acme"}
    )
    assert status == 200 and tenants(out) == ["acme"]


@pytest.mark.parametrize(
    "path", ["/api/v1/execute", "/api/query", "/api/v1/query/execute"]
)
def test_every_execute_alias_is_isolated(secure: Client, path: str) -> None:
    key = "query" if path.endswith("query/execute") else "spec"
    status, out, _ = secure.post(path, {key: SPEC}, ACME)
    assert status == 200, out
    assert tenants(out) == ["acme"]


def test_compile_returns_tenant_filtered_sql(secure: Client) -> None:
    status, out, _ = secure.post(
        "/api/v1/compile", {"spec": SPEC, "dialect": "sqlite"}, ACME
    )
    assert status == 200 and "tenant_id" in out["sql"].split("WHERE")[-1]


def test_health_docs_and_validate_need_no_tenant(secure: Client) -> None:
    assert secure.request("GET", "/health")[0] == 200
    assert secure.request("GET", "/docs")[0] == 200
    assert (
        secure.post("/api/v1/validate", {"sql": "select 1"})[0] == 200
    )  # validation only


# -------------------------------------------------- fail closed on the tenant
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Tenant-ID": ""},
        {"X-Tenant-ID": "   "},
        {"X-Tenant-ID": "a,b"},
        {"X-Tenant-ID": "x" * 500},
    ],
    ids=["missing", "empty", "blank", "list", "too-long"],
)
def test_no_usable_tenant_means_no_rows(
    secure: Client, headers: dict[str, str]
) -> None:
    status, out, _ = secure.post("/api/v1/execute", {"spec": SPEC}, headers)
    assert status == 401 and error_code(out) == "TENANT_REQUIRED"
    assert "rows" not in out


def test_control_the_default_server_returns_every_tenant_without_one(
    default: Client,
) -> None:
    status, out, _ = default.post(
        "/api/v1/execute", {"spec": SPEC, "connection_id": "default"}
    )
    assert status == 200 and tenants(out) == ["acme", "rival"]


def test_a_crashing_resolver_fails_closed(db_path: str) -> None:
    def boom(headers: Any) -> str:
        raise RuntimeError("auth backend down")

    server, client = _serve(
        connection_pool_manager=_manager(db_path),
        security=ServerSecurity(tenant_resolver=boom, require_tenant=True),
    )
    try:
        status, out, _ = client.post("/api/v1/execute", {"spec": SPEC}, ACME)
        assert status == 401 and error_code(out) == "TENANT_REQUIRED"
    finally:
        server.shutdown()
        server.server_close()


def test_a_real_authenticator_can_replace_the_header(db_path: str) -> None:
    tokens = {"token-acme": "acme", "token-rival": "rival"}

    def bearer(headers: Any) -> str | None:
        value = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
        return tokens.get(value.removeprefix("Bearer "))

    server, client = _serve(
        connection_pool_manager=_manager(db_path),
        security=ServerSecurity(tenant_resolver=bearer, require_tenant=True),
    )
    try:
        ok = client.post(
            "/api/v1/execute", {"spec": SPEC}, {"Authorization": "Bearer token-rival"}
        )
        assert tenants(ok[1]) == ["rival"]
        bad = client.post(
            "/api/v1/execute", {"spec": SPEC}, {"Authorization": "Bearer forged"}
        )
        assert bad[0] == 401
        assert (
            client.post("/api/v1/execute", {"spec": SPEC}, ACME)[0] == 401
        )  # the header means nothing
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------ the client may not choose what the server chooses
@pytest.mark.parametrize(
    "field",
    [
        ("tenant_id", "rival"),
        ("policy", {"tenant_column": "tenant_id"}),
        ("config", {"database": "/etc/other.db"}),
        ("connector", "sqlite"),
    ],
    ids=["tenant_id", "policy", "config", "connector"],
)
def test_client_supplied_fields_are_refused_not_ignored(
    secure: Client, field: tuple[str, Any]
) -> None:
    status, out, _ = secure.post(
        "/api/v1/execute", {"spec": SPEC, field[0]: field[1]}, ACME
    )
    assert status == 403 and error_code(out) == "FORBIDDEN_FIELD"
    assert field[0] in out["error"]["message"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("tenant_id", "rival"),
        ("policy", {"tenant_column": "tenant_id"}),
        ("config", {"database": ":memory:"}),
        ("connector", "sqlite"),
    ],
)
def test_control_the_default_server_does_not_refuse_what_the_client_sends(
    default: Client, name: str, value: Any
) -> None:
    status, out, _ = default.post(
        "/api/v1/execute", {"spec": SPEC, "connection_id": "default", name: value}
    )
    assert error_code(out) != "FORBIDDEN_FIELD"


def test_a_client_naming_another_tenant_is_refused_even_with_a_valid_header(
    secure: Client,
) -> None:
    status, out, _ = secure.post(
        "/api/v1/execute", {"spec": SPEC, "tenant_id": "rival"}, ACME
    )
    assert status == 403 and "rows" not in out


def test_control_a_default_server_lets_the_client_pick_any_tenant(
    default: Client,
) -> None:
    status, out, _ = default.post(
        "/api/v1/execute",
        {"spec": SPEC, "tenant_id": "rival", "connection_id": "default"},
    )
    assert status == 200 and tenants(out) == ["rival"]


def test_the_client_cannot_pick_the_connection(secure: Client) -> None:
    status, out, _ = secure.post(
        "/api/v1/execute", {"spec": SPEC, "connection_id": "somewhere-else"}, ACME
    )
    assert status == 200 and tenants(out) == [
        "acme"
    ]  # the server's own connection was used


def test_a_missing_default_connection_is_reported_not_guessed(db_path: str) -> None:
    server, client = _serve(
        connection_pool_manager=ConnectionPoolManager(),  # nothing registered
        security=ServerSecurity(
            tenant_resolver=header_tenant_resolver(), require_tenant=True
        ),
    )
    try:
        status, out, _ = client.post("/api/v1/execute", {"spec": SPEC}, ACME)
        assert status == 404 and error_code(out) == "UNKNOWN_CONNECTION"
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------- raw SQL
def test_raw_sql_is_refused_even_with_a_tenant(secure: Client) -> None:
    status, out, _ = secure.post(
        "/api/v1/execute", {"sql": "select * from orders"}, ACME
    )
    assert status == 403 and error_code(out) == "RAW_SQL_FORBIDDEN"


def test_control_the_default_server_returns_everything_for_raw_sql(
    default: Client,
) -> None:
    status, out, _ = default.post(
        "/api/v1/execute",
        {
            "sql": "select * from orders",
            "connection_id": "default",
            "tenant_id": "acme",
        },
    )
    assert status == 200 and tenants(out) == [
        "acme",
        "rival",
    ]  # the limitation secure mode closes


def test_raw_sql_can_be_allowed_by_the_operator(db_path: str) -> None:
    server, client = _serve(
        connection_pool_manager=_manager(db_path),
        security=ServerSecurity(
            tenant_resolver=header_tenant_resolver(),
            require_tenant=True,
            allow_raw_sql=True,
        ),
    )
    try:
        status, out, _ = client.post(
            "/api/v1/execute", {"sql": "select * from orders"}, ACME
        )
        assert status == 200  # the operator accepted that raw SQL is not isolated
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------- the policy cannot be widened
def test_a_filter_naming_the_other_tenant_returns_nothing(secure: Client) -> None:
    spec = {**SPEC, "filters": [{"column": "tenant_id", "op": "eq", "value": "rival"}]}
    status, out, _ = secure.post("/api/v1/execute", {"spec": spec}, ACME)
    assert status == 200 and out["rows"] == []


def test_an_or_filter_cannot_widen_the_enforced_predicate(secure: Client) -> None:
    spec = {
        **SPEC,
        "filters": [
            {"column": "tenant_id", "op": "eq", "value": "rival", "combiner": "OR"},
            {"column": "id", "op": "gt", "value": 0, "combiner": "OR"},
        ],
    }
    status, out, _ = secure.post("/api/v1/execute", {"spec": spec}, ACME)
    assert status == 200 and tenants(out) == ["acme"]


def test_a_cte_over_the_tenant_table_is_isolated(secure: Client) -> None:
    spec = {
        "table": "c",
        "columns": ["id", "tenant_id"],
        "ctes": [{"name": "c", "query": SPEC}],
    }
    status, out, _ = secure.post("/api/v1/execute", {"spec": spec}, ACME)
    assert status == 200 and tenants(out) == ["acme"]


# ------------------------------------------------------------ the endpoint allow-list
BLOCKED = [
    ("GET", "/api/v1/connections"),
    ("POST", "/api/v1/connections"),
    ("POST", "/api/v1/connections/test"),
    ("POST", "/api/v1/connections/cancel"),
    ("DELETE", "/api/v1/connections/default"),
    ("POST", "/api/v1/introspect"),
    ("POST", "/api/v1/stream"),
    ("POST", "/api/query/stream"),
    ("POST", "/api/v1/export"),
    ("POST", "/api/v1/export/stream"),
    ("GET", "/api/v1/templates"),
    ("POST", "/api/v1/templates"),
    ("DELETE", "/api/v1/templates/x"),
    ("GET", "/api/v1/telemetry"),
    ("POST", "/api/v1/nlq/translate"),
    ("POST", "/api/v1/nlq/explain"),
    ("GET", "/api/v1/nlq/providers"),
    ("GET", "/no/such/path"),
]


@pytest.mark.parametrize(("method", "path"), BLOCKED)
def test_endpoints_outside_the_allow_list_are_refused(
    secure: Client, method: str, path: str
) -> None:
    body = {"spec": SPEC} if method == "POST" else None
    status, out, _ = secure.request(method, path, body, ACME)
    assert status == 403 and error_code(out) == "NOT_AVAILABLE_IN_SECURE_MODE"


def test_control_the_default_server_serves_the_same_endpoints(default: Client) -> None:
    assert default.request("GET", "/api/v1/connections")[0] == 200
    assert default.request("GET", "/api/v1/telemetry")[0] == 200


def test_the_operator_can_extend_the_allow_list(db_path: str) -> None:
    server, client = _serve(
        connection_pool_manager=_manager(db_path),
        security=ServerSecurity(
            tenant_resolver=header_tenant_resolver(),
            extra_endpoints=frozenset({("GET", "/api/v1/telemetry")}),
        ),
    )
    try:
        assert client.request("GET", "/api/v1/telemetry", None, ACME)[0] == 200
        assert client.request("GET", "/api/v1/connections", None, ACME)[0] == 403
    finally:
        server.shutdown()
        server.server_close()


# -------------------------------------------------------------------------- CORS
def test_cors_origin_for_behavior() -> None:
    security = ServerSecurity(
        tenant_resolver=header_tenant_resolver(),
        cors_origins=("https://trusted.com",),
    )
    assert security.cors_origin_for("https://trusted.com") == "https://trusted.com"
    assert security.cors_origin_for("https://untrusted.com") is None
    assert security.cors_origin_for(None) is None
    assert security.cors_origin_for("") is None

    empty_cors_security = ServerSecurity(
        tenant_resolver=header_tenant_resolver(),
    )
    assert empty_cors_security.cors_origin_for("https://trusted.com") is None
    assert empty_cors_security.cors_origin_for(None) is None


def test_secure_mode_sends_no_wildcard_cors(secure: Client) -> None:
    _, _, headers = secure.post(
        "/api/v1/execute", {"spec": SPEC}, {**ACME, "Origin": "https://evil.example"}
    )
    assert "Access-Control-Allow-Origin" not in headers
    _, _, plain = secure.request("GET", "/health")
    assert "Access-Control-Allow-Origin" not in plain


def test_listed_origins_are_echoed_and_others_are_not(db_path: str) -> None:
    server, client = _serve(
        connection_pool_manager=_manager(db_path),
        security=ServerSecurity(
            tenant_resolver=header_tenant_resolver(),
            cors_origins=("https://app.example",),
        ),
    )
    try:
        _, _, ok = client.request(
            "GET", "/health", None, {"Origin": "https://app.example"}
        )
        _, _, other = client.request(
            "GET", "/health", None, {"Origin": "https://evil.example"}
        )
        assert ok["Access-Control-Allow-Origin"] == "https://app.example"
        assert "Access-Control-Allow-Origin" not in other
    finally:
        server.shutdown()
        server.server_close()


def test_control_the_default_server_allows_any_origin(default: Client) -> None:
    _, _, headers = default.request(
        "GET", "/health", None, {"Origin": "https://evil.example"}
    )
    assert headers["Access-Control-Allow-Origin"] == "*"


# ------------------------------------------------------ the checker itself (no HTTP)
def _check(
    body: Any,
    headers: dict[str, str] | None = None,
    path: str = "/api/v1/execute",
    **kw: Any,
) -> Any:
    security = ServerSecurity(
        tenant_resolver=header_tenant_resolver(), require_tenant=True, **kw
    )
    return secure_request(
        security, "POST", path, headers or ACME, body, lambda cid: True
    )


def test_a_non_object_body_is_a_bad_request() -> None:
    with pytest.raises(SecureRequestError) as err:
        _check(["not", "an", "object"])
    assert err.value.status == 400


def test_the_returned_body_carries_no_tenant_or_policy_and_a_rewritten_spec() -> None:
    out = _check({"spec": SPEC})
    assert "tenant_id" not in out and "policy" not in out
    assert out["connection_id"] == "default"
    assert out["spec"] != SPEC  # the tenant predicate was added


def test_the_original_body_is_not_mutated() -> None:
    body = {"spec": dict(SPEC)}
    _check(body)
    assert body == {"spec": SPEC}


def test_the_secure_endpoints_are_a_small_fixed_set() -> None:
    assert SECURE_ENDPOINTS == {
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


# ------------------------------------------------------------------ the notice
def test_the_default_mode_notice_says_what_is_unprotected() -> None:
    text = "\n".join(insecure_mode_notice("serve"))
    assert "no authentication" in text and "tenant_id" in text and "--insecure" in text
    assert "SECURE_DEPLOYMENT.md" in text


def test_the_mcp_notice_names_the_agent_as_the_source_of_settings() -> None:
    text = "\n".join(insecure_mode_notice("mcp"))
    assert "AI agent" in text and "no tenant context" in text


def test_there_is_no_notice_in_secure_mode() -> None:
    assert insecure_mode_notice("serve", secure=True) == []


# ------------------------------------------- a policy failure must fail CLOSED, never open
def test_a_policy_failure_refuses_the_request_instead_of_running_the_raw_spec(
    db_path: str,
) -> None:
    """Isolation is enforced but no tenant resolves and the operator did not require one: binding
    the tenant raises. The request must be refused; running the unfiltered spec would leak."""
    from query_builder.config import (
        SecurityProfile,
        configure_security,
        reset_security_config,
    )

    configure_security(
        SecurityProfile.from_name("production")
    )  # enforce_tenant_isolation on
    try:
        server, client = _serve(
            connection_pool_manager=_manager(db_path),
            security=ServerSecurity(
                tenant_resolver=header_tenant_resolver(), require_tenant=False
            ),
        )
        try:
            status, out, _ = client.post("/api/v1/execute", {"spec": SPEC})
            assert status == 403 and error_code(out) == "FORBIDDEN"
            assert "rows" not in out
        finally:
            server.shutdown()
            server.server_close()
    finally:
        reset_security_config()


def test_secure_request_raises_when_the_policy_cannot_be_applied() -> None:
    from query_builder.config import (
        SecurityProfile,
        configure_security,
        reset_security_config,
    )

    configure_security(SecurityProfile.from_name("production"))
    try:
        security = ServerSecurity(
            tenant_resolver=header_tenant_resolver(), require_tenant=False
        )
        with pytest.raises(SecureRequestError) as err:
            secure_request(
                security,
                "POST",
                "/api/v1/compile",
                {},
                {"spec": SPEC},
                lambda _id: True,
            )
        assert err.value.status == 403 and err.value.code == "FORBIDDEN"
    finally:
        reset_security_config()


def test_explain_requires_tenant_in_secure_mode(
    secure: Client, default: Client
) -> None:
    # Adversarial: in secure mode, omitting tenant header fails closed with 401
    status, out, _ = secure.post("/api/v1/explain", {"spec": SPEC})
    assert status == 401 and error_code(out) == "TENANT_REQUIRED"

    # Control: in default mode, same request succeeds
    status, out, _ = default.post("/api/v1/explain", {"spec": SPEC})
    assert status == 200


def test_explain_with_tenant_header_succeeds(secure: Client) -> None:
    status, out, _ = secure.post("/api/v1/explain", {"spec": SPEC}, headers=ACME)
    assert status == 200


# ------------------------------------------------------------- tenant required logic
def test_tenant_required_logic() -> None:
    from query_builder.config import (
        SecurityProfile,
        configure_security,
        reset_security_config,
    )

    # Test 1: require_tenant is True
    sec1 = ServerSecurity(tenant_resolver=header_tenant_resolver(), require_tenant=True)
    assert sec1.tenant_required() is True

    # Test 2: require_tenant is False
    sec2 = ServerSecurity(
        tenant_resolver=header_tenant_resolver(), require_tenant=False
    )
    assert sec2.tenant_required() is False

    # Test 3: require_tenant is None, global config enforce_tenant_isolation is True
    try:
        configure_security(SecurityProfile.from_name("production"))
        sec3 = ServerSecurity(
            tenant_resolver=header_tenant_resolver(), require_tenant=None
        )
        assert sec3.tenant_required() is True
    finally:
        reset_security_config()

    # Test 4: require_tenant is None, global config enforce_tenant_isolation is False
    try:
        configure_security(SecurityProfile.from_name("development"))
        sec4 = ServerSecurity(
            tenant_resolver=header_tenant_resolver(), require_tenant=None
        )
        assert sec4.tenant_required() is False
    finally:
        reset_security_config()
