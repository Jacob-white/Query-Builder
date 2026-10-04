"""
Comprehensive Test Suite for Security Framework (Milestone 2).
==============================================================
Validates:
1. SSRF Network Egress Validation & Cloud Metadata Blocking (validate_network_target)
2. Secret, URI & Credential Scrubbing (scrub_secrets)
3. AST Complexity Scoring (calculate_ast_complexity)
4. Cartesian Product Detection (check_cartesian_products)
5. Data & Column Masking Strategies (apply_column_masking)
6. Security Policy Dynamic Regex & Masking (apply_security_policy)
7. Security Middleware Lifecycle Interceptor (SecurityMiddleware)
8. Telemetry Audit Events & Parameter Redaction (AuditEvent, TelemetryCollector)
9. Float NaN / Inf Socket Timeout Validation (NetworkSecurityConfig, load_security_config_from_env)
10. Fail-Closed Tenant Ownership Relational Predicates & Chain Guards (resolve_ownership_predicate)

Guarantees 100% statement and 100% branch test coverage across all touched modules.
"""

from __future__ import annotations

import socket
import tempfile
from unittest.mock import patch

import pytest

from query_builder.config import (
    ExecutionSecurityConfig,
    NetworkSecurityConfig,
    PrivacySecurityConfig,
    SecurityConfig,
    ValidationSecurityConfig,
    load_security_config_from_env,
    reset_security_config,
)
from query_builder.dialects import get_dialect
from query_builder.middleware import (
    LifecycleInterceptor,
    MiddlewarePipeline,
    SecurityMiddleware,
)
from query_builder.models import JoinSpec, QuerySpec
from query_builder.policy import (
    SecurityPolicy,
    TenantContext,
    apply_security_policy,
)
from query_builder.security import (
    AliasCounter,
    SecurityError,
    _build_chain_exists,
    apply_column_masking,
    calculate_ast_complexity,
    check_cartesian_products,
    resolve_ownership_predicate,
    scrub_secrets,
    validate_network_target,
)
from query_builder.telemetry import (
    AuditEvent,
    ExecutionEvent,
    TelemetryCollector,
)


@pytest.fixture(autouse=True)
def clean_security():
    """Isolates global security configuration for each test."""
    reset_security_config()
    yield
    reset_security_config()


# ===========================================================================
# 1. SSRF Network Target Validation Tests
# ===========================================================================


def test_validate_network_target_public_ip_allowed():
    """Verifies that public IPv4 and IPv6 addresses pass network validation."""
    validate_network_target(host="93.184.216.34")  # example.com IP
    validate_network_target(host="8.8.8.8")
    validate_network_target(host="2001:4860:4860::8888")


def test_validate_network_target_private_ips_blocked_by_default():
    """Verifies that RFC 1918 private subnets are blocked when allow_private_networks=False."""
    for ip in ["10.0.0.1", "172.16.0.1", "192.168.1.1", "10.255.255.254"]:
        with pytest.raises(
            SecurityError, match="Access to private/internal network target"
        ):
            validate_network_target(host=ip)


def test_validate_network_target_private_ips_permitted_when_configured():
    """Verifies that private IPs pass when allow_private_networks=True."""
    cfg = NetworkSecurityConfig(allow_private_networks=True)
    validate_network_target(host="10.0.0.1", network_config=cfg)
    validate_network_target(host="192.168.1.100", network_config=cfg)
    validate_network_target(host="172.20.0.5", network_config=cfg)


def test_validate_network_target_cloud_metadata_always_blocked():
    """Verifies that cloud metadata IPs are strictly blocked even when allow_private_networks=True."""
    cfg = NetworkSecurityConfig(allow_private_networks=True)
    for meta_ip in [
        "169.254.169.254",
        "169.254.169.253",
        "fd00:ec2::254",
        "::ffff:169.254.169.254",
    ]:
        with pytest.raises(SecurityError, match="Access to cloud metadata IP target"):
            validate_network_target(host=meta_ip, network_config=cfg)

        with pytest.raises(SecurityError, match="Access to cloud metadata IP target"):
            validate_network_target(
                host=meta_ip,
                network_config=NetworkSecurityConfig(allow_private_networks=False),
            )


def test_validate_network_target_cloud_metadata_hostnames():
    """Verifies that cloud metadata hostnames are forbidden."""
    for host in [
        "metadata.google.internal",
        "metadata.internal",
        "metadata",
        "instance-data",
        "sub.google.internal",
    ]:
        with pytest.raises(SecurityError, match="Access to cloud metadata target"):
            validate_network_target(host=host)


def test_validate_network_target_loopback_and_localhost():
    """Verifies that loopback targets (127.0.0.0/8, ::1, localhost) are blocked by default."""
    for target in [
        "127.0.0.1",
        "127.0.1.1",
        "::1",
        "::ffff:127.0.0.1",
        "localhost",
        "localhost.localdomain",
    ]:
        with pytest.raises(SecurityError, match="forbidden|private/internal|loopback"):
            validate_network_target(host=target)

    # Allowed when allow_private_networks=True
    cfg = NetworkSecurityConfig(allow_private_networks=True)
    validate_network_target(host="127.0.0.1", network_config=cfg)
    validate_network_target(host="localhost", network_config=cfg)
    validate_network_target(host="::1", network_config=cfg)


def test_validate_network_target_restricted_ranges():
    """Verifies CGNAT, link-local, IPv6 ULA, multicast, and unspecified addresses are blocked."""
    restricted = [
        "100.64.0.1",  # CGNAT
        "100.127.255.255",  # CGNAT
        "169.254.1.1",  # Link-local
        "fc00::1",  # IPv6 ULA
        "fd12:3456::1",  # IPv6 ULA
        "fe80::1",  # IPv6 Link-local
        "0.0.0.0",  # Unspecified
        "::",  # Unspecified IPv6
        "224.0.0.1",  # Multicast
        "240.0.0.1",  # Reserved
    ]
    for ip in restricted:
        with pytest.raises(
            SecurityError, match="Access to private/internal network target"
        ):
            validate_network_target(host=ip)


def test_validate_network_target_hostname_whitelist_and_blacklist():
    """Verifies allowed_hostnames and blocked_hostnames enforcement including wildcards."""
    # Whitelist
    wl_cfg = NetworkSecurityConfig(
        allowed_hostnames=["db.prod.internal", "*.safe.corp"],
        allow_private_networks=True,
    )
    validate_network_target(host="db.prod.internal", network_config=wl_cfg)
    validate_network_target(host="app.safe.corp", network_config=wl_cfg)
    validate_network_target(host="safe.corp", network_config=wl_cfg)

    with pytest.raises(SecurityError, match="not in allowed hostnames list"):
        validate_network_target(host="other.corp", network_config=wl_cfg)

    # Blacklist
    bl_cfg = NetworkSecurityConfig(
        blocked_hostnames=["evil.com", "*.attacker.io"],
        allow_private_networks=True,
    )
    with pytest.raises(SecurityError, match="in blocked hostnames list"):
        validate_network_target(host="evil.com", network_config=bl_cfg)
    with pytest.raises(SecurityError, match="in blocked hostnames list"):
        validate_network_target(host="payload.attacker.io", network_config=bl_cfg)
    with pytest.raises(SecurityError, match="in blocked hostnames list"):
        validate_network_target(host="attacker.io", network_config=bl_cfg)

    validate_network_target(host="trusted.com", network_config=bl_cfg)


def test_validate_network_target_tls_enforcement():
    """Verifies that insecure URL schemes and disabled SSL configs are rejected when enforce_tls=True."""
    cfg = NetworkSecurityConfig(enforce_tls=True)

    # Insecure URL schemes
    for insecure_url in [
        "http://api.example.com",
        "ws://stream.example.com",
        "ftp://files.example.com",
    ]:
        with pytest.raises(
            SecurityError, match="TLS is enforced but URL uses insecure scheme"
        ):
            validate_network_target(url=insecure_url, network_config=cfg)

    # Insecure configs
    with pytest.raises(SecurityError, match="SSL/TLS is explicitly disabled"):
        validate_network_target(
            host="db.example.com",
            config={"ssl": False},
            network_config=cfg,
        )

    with pytest.raises(SecurityError, match="SSL/TLS is explicitly disabled"):
        validate_network_target(
            host="db.example.com",
            config={"tls": False},
            network_config=cfg,
        )

    with pytest.raises(SecurityError, match="SSL/TLS is explicitly disabled"):
        validate_network_target(
            host="db.example.com",
            config={"sslmode": "disable"},
            network_config=cfg,
        )

    # Secure URL & config passes
    validate_network_target(url="https://api.example.com:443", network_config=cfg)
    validate_network_target(
        host="db.example.com", config={"ssl": True}, network_config=cfg
    )


def test_validate_network_target_ca_bundle_path():
    """Verifies that CA bundle file existence is verified."""
    with pytest.raises(SecurityError, match="CA bundle file does not exist"):
        validate_network_target(
            host="db.example.com",
            network_config=NetworkSecurityConfig(ca_bundle_path="/nonexistent/ca.pem"),
        )

    with tempfile.NamedTemporaryFile() as tmp:
        validate_network_target(
            host="db.example.com",
            network_config=NetworkSecurityConfig(
                ca_bundle_path=tmp.name, allow_private_networks=True
            ),
        )


def test_validate_network_target_port_validation():
    """Verifies network port bounds checking (1 to 65535)."""
    cfg = NetworkSecurityConfig(allow_private_networks=True)
    validate_network_target(host="localhost", port=5432, network_config=cfg)
    validate_network_target(host="localhost", port="3306", network_config=cfg)

    for invalid_port in [0, 65536, -5, "not-a-port"]:
        with pytest.raises(SecurityError, match="Invalid network port"):
            validate_network_target(
                host="localhost", port=invalid_port, network_config=cfg
            )


def test_validate_network_target_config_extraction_and_defaults():
    """Verifies extraction of host, port, and url from config dict and config objects."""
    # From SecurityConfig
    sec_cfg = SecurityConfig(network=NetworkSecurityConfig(allow_private_networks=True))
    validate_network_target(host="10.0.0.1", config=sec_cfg)

    # From dict with security
    validate_network_target(
        config={
            "host": "10.0.0.1",
            "security": sec_cfg,
        }
    )

    # From dict with network
    validate_network_target(
        config={
            "hostname": "10.0.0.1",
            "port": 5432,
            "network": NetworkSecurityConfig(allow_private_networks=True),
        }
    )

    # From connection_string url
    validate_network_target(
        config={
            "connection_string": "https://api.example.com:443",
        }
    )

    # None host or empty host
    validate_network_target()
    validate_network_target(host="")


def test_validate_network_target_dns_resolution_and_fallback():
    """Verifies DNS resolution catches forbidden IPs and handles unresolvable hosts gracefully."""
    # Mock DNS resolving to private IP
    with (
        patch(
            "socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("192.168.1.50", 5432),
                )
            ],
        ),
        pytest.raises(SecurityError, match="resolves to forbidden private/internal IP"),
    ):
        validate_network_target(host="internal-alias.test")

    # Mock DNS resolving to cloud metadata IP
    with (
        patch(
            "socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("169.254.169.254", 80),
                )
            ],
        ),
        pytest.raises(SecurityError, match="resolves to forbidden cloud metadata IP"),
    ):
        validate_network_target(
            host="meta-alias.test",
            network_config=NetworkSecurityConfig(allow_private_networks=True),
        )

    # Unresolvable mock host triggers graceful offline fallback
    with patch(
        "socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    ):
        validate_network_target(host="unresolvable-mock-db.corp")


# ===========================================================================
# 2. Secret & Credential Scrubbing Tests
# ===========================================================================


def test_scrub_secrets_uri_passwords():
    """Verifies passwords in connection URIs are scrubbed."""
    uri = "postgresql://dbuser:super_secret_pw@db.prod.internal:5432/finance_db"
    scrubbed = scrub_secrets(uri)
    assert scrubbed == "postgresql://dbuser:***@db.prod.internal:5432/finance_db"
    assert "super_secret_pw" not in scrubbed


def test_scrub_secrets_bearer_tokens():
    """Verifies Bearer tokens in headers or strings are scrubbed."""
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    scrubbed = scrub_secrets(text)
    assert scrubbed == "Authorization: Bearer ***"


def test_scrub_secrets_key_value_pairs():
    """Verifies inline key-value secrets in text are scrubbed."""
    text = "Error connecting with password=mySecret123 and api_key: 'top_secret_key'"
    scrubbed = scrub_secrets(text)
    assert "password=***" in scrubbed
    assert "api_key:***" in scrubbed
    assert "mySecret123" not in scrubbed
    assert "top_secret_key" not in scrubbed


def test_scrub_secrets_recursive_structures():
    """Verifies recursive sanitization across dicts, lists, tuples, sets, and exceptions."""
    payload = {
        "user": "alice",
        "password": "secret_password",
        "api_token": "tok_12345",
        "nested": {
            "auth_key": "key_999",
            "items": ["safe", "Bearer 12345", ("password=abc", {"secret": 42})],
            "tags": {"safe_tag"},
        },
        "count": 10,
        "is_active": True,
    }
    scrubbed = scrub_secrets(payload)
    assert scrubbed["password"] == "***"
    assert scrubbed["api_token"] == "***"
    assert scrubbed["nested"]["auth_key"] == "***"
    assert scrubbed["nested"]["items"][1] == "Bearer ***"
    assert scrubbed["nested"]["items"][2][0] == "password=***"
    assert scrubbed["nested"]["items"][2][1]["secret"] == "***"
    assert scrubbed["count"] == 10
    assert scrubbed["is_active"] is True

    # Exceptions
    exc = ValueError("Failed connection with password=foo")
    scrubbed_exc = scrub_secrets(exc)
    assert isinstance(scrubbed_exc, ValueError)
    assert str(scrubbed_exc) == "Failed connection with password=***"


# ===========================================================================
# 3. AST Complexity Scoring Tests
# ===========================================================================


def test_calculate_ast_complexity_basic_and_invalid():
    """Verifies base table scoring and zero score for empty/invalid specs."""
    assert calculate_ast_complexity({}) == 0
    assert calculate_ast_complexity(None) == 0  # type: ignore
    assert calculate_ast_complexity({"table": ""}) == 0

    spec = {"table": "users", "columns": ["id", "username"]}
    # Base table (1) + 2 columns (2) = 3
    assert calculate_ast_complexity(spec) == 3


def test_calculate_ast_complexity_aggregates_and_joins():
    """Verifies complexity scoring for aggregations, distincts, and various join types."""
    spec = {
        "table": "orders",
        "columns": [
            "id",
            {"column": "amount", "agg": "sum"},
            {"column": "status", "distinct": True},
            "COUNT(items)",
        ],
        "joins": [
            {"table": "items", "type": "LEFT"},
            {"table": "audit", "type": "CROSS"},
        ],
    }
    # Base: 1
    # Columns:
    #   'id': 1
    #   sum agg: 1 + 2 = 3
    #   distinct: 1 + 1 = 2
    #   COUNT: 1 + 2 = 3
    # Joins:
    #   LEFT join: 5
    #   CROSS join: 10
    # Total: 1 + 1 + 3 + 2 + 3 + 5 + 10 = 25
    assert calculate_ast_complexity(spec) == 25


def test_calculate_ast_complexity_filters_group_having_order_ctes():
    """Verifies complexity calculation with filters, regex, group by, having, and subqueries."""
    spec = {
        "table": "analytics",
        "columns": ["metric"],
        "filters": [
            {"column": "dt", "op": "eq", "value": "2026-01-01"},
            {"column": "name", "op": "like", "value": "test%"},
            {
                "column": "sub",
                "op": "in",
                "value": {"table": "users", "columns": ["id"]},
            },
        ],
        "group_by": ["metric", "category"],
        "having": [{"column": "cnt", "op": "gt", "value": 5}],
        "order_by": ["metric"],
        "ctes": [{"table": "temp_t", "columns": ["a"]}],
        "window": True,
    }
    # Base: 1
    # Column: 1
    # Filters:
    #   eq: 2
    #   like: 2 + 3 = 5
    #   subquery: 2 + 10 + subquery_complexity(users: 1 + 1 = 2) = 14
    # Group by: 3 + 2 = 5
    # Having: 3 + 2 = 5
    # Order by: 2 + 1 = 3
    # CTEs: 10 + cte_complexity(temp_t: 1 + 1 = 2) = 12
    # Window: 5
    # Total: 1 + 1 + 2 + 5 + 14 + 5 + 5 + 3 + 12 + 5 = 53
    assert calculate_ast_complexity(spec) == 53

    # QuerySpec dataclass compatibility
    qspec = QuerySpec(table="users", columns=["id", "name"])
    assert calculate_ast_complexity(qspec) == 3


# ===========================================================================
# 4. Cartesian Product Detection Tests
# ===========================================================================


def test_check_cartesian_products_valid_joins():
    """Verifies that joins with 'on', column pairs, or foreign keys pass."""
    check_cartesian_products({})
    check_cartesian_products({"table": "users"})

    spec1 = {
        "table": "users",
        "joins": [
            {
                "table": "orders",
                "on": [{"left": "users.id", "right": "orders.user_id"}],
            }
        ],
    }
    check_cartesian_products(spec1)

    spec2 = {
        "table": "users",
        "joins": [{"table": "orders", "left_col": "id", "right_col": "user_id"}],
    }
    check_cartesian_products(spec2)

    spec3 = {
        "table": "users",
        "joins": [{"table": "orders", "foreign_key": "fk_orders_users"}],
    }
    check_cartesian_products(spec3)

    # JoinSpec dataclass
    qspec = QuerySpec(
        table="users",
        joins=[JoinSpec(table="orders", left_col="id", right_col="user_id")],
    )
    check_cartesian_products(qspec)


def test_check_cartesian_products_detects_violations():
    """Verifies that missing conditions and explicit CROSS JOINs raise SecurityError."""
    # Missing join conditions
    spec_unconditional = {
        "table": "users",
        "joins": [{"table": "orders", "type": "LEFT"}],
    }
    with pytest.raises(SecurityError, match="lacks join conditions"):
        check_cartesian_products(spec_unconditional)

    # Empty on list
    spec_empty_on = {
        "table": "users",
        "joins": [{"table": "orders", "on": []}],
    }
    with pytest.raises(SecurityError, match="lacks join conditions"):
        check_cartesian_products(spec_empty_on)

    # Explicit CROSS JOIN
    spec_cross = {
        "table": "users",
        "joins": [
            {
                "table": "orders",
                "type": "CROSS",
                "left_col": "id",
                "right_col": "user_id",
            }
        ],
    }
    with pytest.raises(SecurityError, match="explicit CROSS JOIN"):
        check_cartesian_products(spec_cross)


# ===========================================================================
# 5. Column Masking Strategies Tests
# ===========================================================================


def test_apply_column_masking_strategies():
    """Verifies redact, hash, and partial data masking strategies."""
    assert apply_column_masking(None) is None

    # Redact
    assert apply_column_masking("secret_val", strategy="redact") == "[REDACTED]"

    # Hash
    hashed = apply_column_masking("secret_val", strategy="hash")
    assert len(hashed) == 64
    assert hashed == "5e6e70167de63f62f6a47d68cfdc5db2800f9e58837985183e269e562264581f"

    # Partial
    assert apply_column_masking("ab", strategy="partial") == "***"
    assert apply_column_masking("abcd", strategy="partial") == "a***d"
    assert apply_column_masking("1234567890", strategy="partial") == "12***90"
    assert apply_column_masking(987654321, strategy="partial") == "98***21"

    # Invalid strategy
    with pytest.raises(ValueError, match="Unknown masking strategy"):
        apply_column_masking("val", strategy="invalid_strategy")


# ===========================================================================
# 6. Policy Engine Sensitive Column Patterns & Dynamic Strategies Tests
# ===========================================================================


def test_apply_security_policy_regex_patterns_and_dynamic_strategies():
    """Verifies regex-based sensitive column detection and strategy tagging."""
    policy = SecurityPolicy(
        sensitive_column_patterns=[r"(?i)(token|pwd|ssn)"],
        masking_strategy="hash",
    )
    ctx = TenantContext(tenant_id="t1", roles=["viewer"])
    spec = {
        "table": "users",
        "columns": [
            "id",
            "access_token",
            {"column": "user_pwd", "table": "users"},
            "users.ssn",
        ],
    }
    result = apply_security_policy(spec, context=ctx, policy=policy)
    cols = result["columns"]
    assert cols[0] == "id"
    assert cols[1] == {
        "column": "access_token",
        "alias": "access_token_masked",
        "masked": True,
        "masking_strategy": "hash",
    }
    assert cols[2] == {
        "column": "user_pwd",
        "table": "users",
        "alias": "user_pwd_masked",
        "masked": True,
        "masking_strategy": "hash",
    }
    assert cols[3] == {
        "column": "ssn",
        "alias": "ssn_masked",
        "masked": True,
        "masking_strategy": "hash",
    }


def test_apply_security_policy_with_security_config():
    """Verifies passing SecurityConfig or PrivacySecurityConfig directly to apply_security_policy."""
    sec_cfg = SecurityConfig(
        privacy=PrivacySecurityConfig(
            tenant_column="tenant_id",
            sensitive_column_patterns=[r"(?i)(secret)"],
            masking_strategy="partial",
        )
    )
    ctx = TenantContext(tenant_id="tenant_abc")
    spec = {"table": "accounts", "columns": ["id", "secret_key"]}
    res = apply_security_policy(spec, context=ctx, policy=sec_cfg)
    assert res["columns"][1]["masking_strategy"] == "partial"
    assert res["columns"][1]["masked"] is True


# ===========================================================================
# 7. Security Middleware Lifecycle Interceptor Tests
# ===========================================================================


def test_security_middleware_pre_compile_governance():
    """Verifies pre-compile enforcement of complexity, join depth, row ceilings, and Cartesian checks."""
    config = SecurityConfig(
        execution=ExecutionSecurityConfig(
            max_complexity_score=15,
            max_join_depth=2,
            max_rows_limit=50,
            prevent_cartesian_products=True,
        ),
        privacy=PrivacySecurityConfig(enforce_tenant_isolation=True),
    )
    middleware = SecurityMiddleware(config=config)
    ctx = {"tenant_context": TenantContext(tenant_id="t_mid")}

    # 1. Complexity violation
    spec_high_complexity = {
        "table": "data",
        "columns": [{"column": f"c{i}", "agg": "sum"} for i in range(10)],
        "joins": [
            {
                "table": f"j{i}",
                "on": [{"left": "data.id", "right": f"j{i}.id"}],
            }
            for i in range(2)
        ],
    }
    with pytest.raises(SecurityError, match="AST complexity score"):
        middleware.on_pre_compile(spec_high_complexity, ctx)

    # 2. Join depth violation
    middleware_depth = SecurityMiddleware(
        config=SecurityConfig(
            execution=ExecutionSecurityConfig(
                max_complexity_score=100, max_join_depth=2
            )
        )
    )
    spec_excess_joins = {
        "table": "data",
        "joins": [
            {
                "table": f"j{i}",
                "on": [{"left": "data.id", "right": f"j{i}.id"}],
            }
            for i in range(3)
        ],
    }
    with pytest.raises(SecurityError, match="Query join depth"):
        middleware_depth.on_pre_compile(spec_excess_joins, ctx)

    # 3. Cartesian violation
    spec_cartesian = {
        "table": "data",
        "joins": [{"table": "j1", "type": "CROSS"}],
    }
    with pytest.raises(SecurityError, match="Cartesian product detected"):
        middleware.on_pre_compile(spec_cartesian, ctx)

    # 4. Valid spec gets row limit capped and tenant filter injected
    valid_spec = {"table": "data", "columns": ["id"], "limit": 500}
    transformed = middleware.on_pre_compile(valid_spec, ctx)
    assert transformed["limit"] == 50
    assert len(transformed["filters"]) == 1
    assert transformed["filters"][0]["column"] == "tenant_id"


def test_security_middleware_post_compile_protections():
    """Verifies read-only session, statement validation, CTE guards, and catalog protections."""
    config = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=True),
        validation=ValidationSecurityConfig(
            allowed_statements=["SELECT"],
            allow_cte=True,
            allow_recursive_cte=False,
            allow_system_catalogs=False,
            filter_sql_comments=True,
        ),
    )
    middleware = SecurityMiddleware(config=config)
    ctx = {}

    # Mutating statements rejected
    with pytest.raises(SecurityError, match="Read-only session violation"):
        middleware.on_post_compile({"main_sql": "DELETE FROM users WHERE id = 1"}, ctx)

    with pytest.raises(SecurityError, match="Statement type 'EXPLAIN' is not in"):
        middleware.on_post_compile({"main_sql": "EXPLAIN SELECT 1"}, ctx)

    # Recursive CTE rejected
    with pytest.raises(SecurityError, match="Recursive CTEs are forbidden"):
        middleware.on_post_compile(
            {"main_sql": "WITH RECURSIVE cte AS (SELECT 1) SELECT * FROM cte"},
            ctx,
        )

    # Catalog access rejected
    with pytest.raises(SecurityError, match="Access to system catalog tables"):
        middleware.on_post_compile(
            {"main_sql": "SELECT * FROM pg_catalog.pg_tables"}, ctx
        )

    # Comments filtered
    comp = {
        "main_sql": "SELECT * FROM users -- inline comment\n/* block comment */ WHERE id = 1"
    }
    res = middleware.on_post_compile(comp, ctx)
    assert "--" not in res["main_sql"]
    assert "block comment" not in res["main_sql"]


def test_security_middleware_execution_and_masking():
    """Verifies timeout setting, row truncations, dynamic row masking, and error sanitization."""
    config = SecurityConfig(
        execution=ExecutionSecurityConfig(statement_timeout_ms=2500, max_rows_limit=2),
        privacy=PrivacySecurityConfig(
            sensitive_column_patterns=[r"(?i)(password|token)"],
            masking_strategy="redact",
        ),
    )
    middleware = SecurityMiddleware(config=config)
    ctx = {"tenant_context": TenantContext(tenant_id="t1", roles=["viewer"])}

    # Pre-execute timeout setting
    middleware.on_pre_execute({"host": "93.184.216.34"}, ctx)
    assert ctx["statement_timeout_ms"] == 2500

    # Post-execute row truncation and column masking
    raw_result = {
        "rows": [
            {"id": 1, "username": "alice", "password": "pw1"},
            {"id": 2, "username": "bob", "password": "pw2"},
            {"id": 3, "username": "charlie", "password": "pw3"},
        ]
    }
    post_res = middleware.on_post_execute(raw_result, ctx)
    assert len(post_res["rows"]) == 2
    assert post_res["truncated"] is True
    assert post_res["rows"][0]["password"] == "[REDACTED]"
    assert post_res["rows"][1]["password"] == "[REDACTED]"

    # Admin bypasses row column masking
    admin_ctx = {"tenant_context": TenantContext(tenant_id="t1", roles=["admin"])}
    admin_result = {"rows": [{"id": 1, "password": "real_password"}]}
    admin_post = middleware.on_post_execute(admin_result, admin_ctx)
    assert admin_post["rows"][0]["password"] == "real_password"

    # Non-dict result passthrough
    assert middleware.on_post_execute(None, ctx) is None  # type: ignore

    # Error sanitization
    err_ctx = {}
    middleware.on_error(ValueError("Connection failed: password=supersecret"), err_ctx)
    assert "password=***" in err_ctx["sanitized_error"]
    assert "supersecret" not in err_ctx["sanitized_error"]


def test_security_middleware_pipeline_integration():
    """Verifies SecurityMiddleware running within standard MiddlewarePipeline."""
    pipeline = MiddlewarePipeline([SecurityMiddleware()])
    ctx = {"tenant_context": TenantContext(tenant_id="t1")}
    spec = pipeline.run_pre_compile({"table": "orders", "columns": ["id"]}, ctx)
    assert len(spec["filters"]) == 1


# ===========================================================================
# 8. Telemetry Audit Events & Parameter Redaction Tests
# ===========================================================================


def test_telemetry_audit_events():
    """Verifies recording, querying, and clearing AuditEvents in TelemetryCollector."""
    tc = TelemetryCollector(max_size=5)

    ev = tc.record_audit_event(
        event_type="security_violation",
        action="execute",
        resource="orders",
        status="denied",
        tenant_id="tenant_10",
        user_id="user_20",
        details={"reason": "Cartesian product", "token": "secret_tok"},
        error_message="Failed with password=123",
    )
    assert isinstance(ev, AuditEvent)
    assert ev.details["token"] == "***"
    assert "password=***" in ev.error_message

    events = tc.get_recent_audit_events(limit=10)
    assert len(events) == 1
    assert events[0]["tenant_id"] == "tenant_10"
    assert events[0]["status"] == "denied"

    # Filter by tenant
    assert len(tc.get_recent_audit_events(tenant_id="other")) == 0
    assert len(tc.get_recent_audit_events(tenant_id="tenant_10")) == 1

    tc.clear()
    assert len(tc.get_recent_audit_events()) == 0


def test_telemetry_parameter_redaction_and_error_scrubbing():
    """Verifies redact_parameters=True and error scrubbing in ExecutionEvents."""
    tc = TelemetryCollector()

    # Redacted parameters (list and dict)
    ev1 = tc.record_execution(
        sql="SELECT * FROM users WHERE id = %s AND token = %s",
        latency_ms=10.0,
        parameters=[42, "sensitive_token_abc"],
        redact_parameters=True,
    )
    assert ev1.parameters == ["[REDACTED]", "[REDACTED]"]

    ev2 = tc.record_execution(
        sql="SELECT * FROM users WHERE email = :email",
        latency_ms=8.0,
        parameters={"email": "alice@test.com", "secret": "pwd"},
        redact_parameters=True,
    )
    assert ev2.parameters == {"email": "[REDACTED]", "secret": "[REDACTED]"}

    # Scrubbed error message
    ev_err = tc.record_execution(
        sql="SELECT 1",
        latency_ms=1.0,
        status="error",
        error_message="DB error with password=my_password",
    )
    assert "password=***" in ev_err.error_message
    assert "my_password" not in ev_err.error_message

    dict_repr = ev1.to_dict()
    assert "parameters" in dict_repr


# ===========================================================================
# 9. Float NaN / Inf Socket Timeout Validation Tests
# ===========================================================================


def test_config_socket_timeout_rejects_nan_and_inf():
    """Verifies math.isfinite check prevents NaN and Inf in socket_timeout_seconds."""
    with pytest.raises(ValueError, match="socket_timeout_seconds must be positive"):
        NetworkSecurityConfig(socket_timeout_seconds=float("nan"))

    with pytest.raises(ValueError, match="socket_timeout_seconds must be positive"):
        NetworkSecurityConfig(socket_timeout_seconds=float("inf"))

    with pytest.raises(ValueError, match="socket_timeout_seconds must be positive"):
        NetworkSecurityConfig(socket_timeout_seconds=float("-inf"))

    # Env variable parsing
    with pytest.raises(ValueError, match="QB_SOCKET_TIMEOUT_SECONDS must be positive"):
        load_security_config_from_env(env={"QB_SOCKET_TIMEOUT_SECONDS": "nan"})

    with pytest.raises(ValueError, match="QB_SOCKET_TIMEOUT_SECONDS must be positive"):
        load_security_config_from_env(env={"QB_SOCKET_TIMEOUT_SECONDS": "inf"})


# ===========================================================================
# 10. Fail-Closed Tenant Ownership Relational Predicates & Chain Guards Tests
# ===========================================================================


def test_resolve_ownership_predicate_fail_closed_and_depth_limits():
    """Verifies complete branch coverage of ownership resolution and guards."""
    dialect = get_dialect("postgres")

    # 1. user_id is None
    with pytest.raises(SecurityError, match="requires a valid, non-null user_id"):
        resolve_ownership_predicate(dialect, {}, "t1", "projects", None, [])

    # 2. Invalid table identifier
    with pytest.raises(SecurityError, match="Invalid table identifier"):
        resolve_ownership_predicate(
            dialect, {}, "t1", "invalid table; DROP TABLE", 42, []
        )

    # 3. Invalid alias identifier
    with pytest.raises(SecurityError, match="Invalid alias for ownership"):
        resolve_ownership_predicate(dialect, {}, "invalid-alias!", "projects", 42, [])

    # 4. Invalid user_col identifier in direct table meta
    bad_meta = {
        "projects": {
            "has_user_id": True,
            "user_col": "invalid user col!",
        }
    }
    with pytest.raises(SecurityError, match="Invalid user column identifier"):
        resolve_ownership_predicate(dialect, bad_meta, "t1", "projects", 42, [])

    # 5. Empty ownership chain
    with pytest.raises(SecurityError, match="Ownership chain cannot be empty"):
        resolve_ownership_predicate(
            dialect, {}, "t1", "tasks", 42, [], ownership_paths={"tasks": [[]]}
        )

    # 6. Invalid chain element format (not a 3-element tuple)
    with pytest.raises(SecurityError, match="Invalid ownership chain element"):
        resolve_ownership_predicate(
            dialect,
            {},
            "t1",
            "tasks",
            42,
            [],
            ownership_paths={"tasks": [[("col1", "col2")]]},  # type: ignore
        )

    # 7. Invalid identifier in chain element
    with pytest.raises(SecurityError, match="Invalid target table identifier"):
        resolve_ownership_predicate(
            dialect,
            {},
            "t1",
            "tasks",
            42,
            [],
            ownership_paths={"tasks": [[("id", "invalid table!", "id")]]},
        )

    # 8. Identifier part exceeding 128 characters
    long_name = "a" * 129
    with pytest.raises(SecurityError, match="exceeds maximum allowed length"):
        resolve_ownership_predicate(
            dialect,
            {},
            "t1",
            "tasks",
            42,
            [],
            ownership_paths={"tasks": [[("id", long_name, "id")]]},
        )

    # 9. Invalid alias in hop
    with pytest.raises(SecurityError, match="Invalid alias in ownership chain"):
        _build_chain_exists(
            dialect,
            {},
            "bad-alias!",
            [("id", "projects", "id")],
            42,
            [],
            AliasCounter(),
        )

    # 10. Cyclic ownership path
    cyclic_paths = {"tasks": [[("p_id", "tasks", "id"), ("p_id", "projects", "id")]]}
    with pytest.raises(
        SecurityError, match="Cyclic ownership path detected at table 'tasks'"
    ):
        resolve_ownership_predicate(
            dialect, {}, "t1", "tasks", 42, [], ownership_paths=cyclic_paths
        )

    # 11. Exceeding max ownership chain depth (10)
    deep_chain = [(f"id_{i}", f"tbl_{i}", f"pk_{i}") for i in range(12)]
    deep_paths = {"start_tbl": [deep_chain]}
    with pytest.raises(SecurityError, match="depth exceeded maximum allowed limit"):
        resolve_ownership_predicate(
            dialect, {}, "t1", "start_tbl", 42, [], ownership_paths=deep_paths
        )

    # 12. Invalid user column identifier at end of chain
    chain_meta = {"final_tbl": {"user_col": "invalid-col!"}}
    with pytest.raises(SecurityError, match="Invalid user column identifier"):
        resolve_ownership_predicate(
            dialect,
            chain_meta,
            "t1",
            "t_step",
            42,
            [],
            ownership_paths={"t_step": [[("f_id", "final_tbl", "id")]]},
        )

    # 13. AliasCounter custom prefix
    ac = AliasCounter(prefix="_test")
    assert ac.next() == "_test1"
    assert ac.next() == "_test2"


# ===========================================================================
# 11. Additional Edge Case & Branch Coverage Tests
# ===========================================================================


def test_resolve_ownership_multi_hop_valid():
    """Verifies successful multi-hop relational foreign key resolution."""
    dialect = get_dialect("postgres")
    tables_meta = {
        "projects": {
            "columns": [{"name": "id"}, {"name": "user_id"}],
            "has_user_id": True,
            "user_col": "user_id",
        },
        "tasks": {
            "columns": [{"name": "id"}, {"name": "project_id"}],
            "has_user_id": False,
        },
        "evidence": {
            "columns": [{"name": "id"}, {"name": "task_id"}],
            "has_user_id": False,
        },
    }
    ownership_paths = {
        "tasks": [[("project_id", "projects", "id")]],
        "evidence": [[("task_id", "tasks", "id"), ("project_id", "projects", "id")]],
    }
    params = []
    predicate = resolve_ownership_predicate(
        dialect,
        tables_meta,
        "t1",
        "evidence",
        42,
        params,
        ownership_paths=ownership_paths,
    )
    assert "EXISTS" in predicate
    assert '"tasks"' in predicate
    assert '"projects"' in predicate
    assert params == [42]


def test_resolve_ownership_direct_valid():
    """Verifies direct user ownership column matching."""
    dialect = get_dialect("postgres")
    tables_meta = {
        "projects": {
            "columns": [{"name": "id"}, {"name": "user_id"}],
            "has_user_id": True,
            "user_col": "user_id",
        }
    }
    params = []
    predicate = resolve_ownership_predicate(
        dialect, tables_meta, "t1", "projects", 42, params
    )
    assert predicate == '"t1"."user_id" = %s'
    assert params == [42]


def test_resolve_ownership_unresolvable_raises():
    """Verifies table lacking user_id and ownership paths fails closed."""
    dialect = get_dialect("postgres")
    with pytest.raises(SecurityError, match="has no resolvable ownership path"):
        resolve_ownership_predicate(
            dialect, {}, "t1", "projects", 42, [], ownership_paths={}
        )


def test_build_chain_exists_empty():
    """Verifies _build_chain_exists rejects empty chains."""
    dialect = get_dialect("postgres")
    with pytest.raises(SecurityError, match="Ownership chain cannot be empty"):
        _build_chain_exists(dialect, {}, "t1", [], 42, [], AliasCounter())


def test_validate_network_target_extended_configs():
    """Verifies config dictionary variations, schemes, and extraction branches."""
    # NetworkSecurityConfig passed directly in config
    validate_network_target(
        config=NetworkSecurityConfig(allow_private_networks=True),
        host="10.0.0.1",
    )

    # Invalid objects in security and network dict keys fall back safely
    validate_network_target(config={"security": "not_a_config"}, host="8.8.8.8")
    validate_network_target(config={"network": "not_a_net"}, host="8.8.8.8")

    # URI and DSN extraction
    validate_network_target(config={"uri": "https://example.com:443"})
    validate_network_target(config={"dsn": "https://example.com:443"})

    # URL without port
    validate_network_target(
        url="https://example.com",
        network_config=NetworkSecurityConfig(enforce_tls=True),
    )


def test_ast_complexity_and_cartesian_edge_cases():
    """Verifies distinct columns, missing ops, non-dict specs, and relationship joins."""
    spec = {
        "table": "users",
        "columns": [{"column": "c1", "distinct": True}],
        "filters": [{"column": "x"}],
        "window": False,
    }
    # Base (1) + Column (1+1=2) + Filter (2) = 5
    assert calculate_ast_complexity(spec) == 5

    # check_cartesian_products non-dict non-dataclass
    check_cartesian_products(123)  # type: ignore

    # Relationship and left/right keys in joins
    check_cartesian_products(
        {"table": "users", "joins": [{"table": "o", "relationship": "rel"}]}
    )
    check_cartesian_products(
        {
            "table": "users",
            "joins": [{"table": "o", "left": "id", "right": "u_id"}],
        }
    )


def test_telemetry_extended_metrics_and_events():
    """Verifies hash_query normalization, percentiles, error rates, and empty cases."""
    from query_builder.telemetry import hash_query

    assert hash_query("") == ""
    assert hash_query("   ") == ""
    assert hash_query(123) == ""  # type: ignore

    # ExecutionEvent to_dict without parameters
    ev = ExecutionEvent("h", "sql", None, None, "pg", 1.0, 1, "success", 0.0)
    assert "parameters" not in ev.to_dict()

    tc = TelemetryCollector()
    # Empty metrics
    empty_m = tc.get_metrics()
    assert empty_m["total_queries"] == 0
    assert empty_m["avg_latency_ms"] == 0.0

    # Scalar parameter redaction
    tc.record_execution(
        "SELECT 1",
        1.0,
        status="error",
        parameters="scalar_secret",  # type: ignore
        redact_parameters=True,
    )

    # 100 executions for percentiles
    for i in range(1, 101):
        tc.record_execution(
            f"SELECT {i}",
            float(i),
            status="success",
            tenant_id="tenant_x",
        )

    metrics = tc.get_metrics()
    assert metrics["total_queries"] == 101
    assert metrics["success_count"] == 100
    assert metrics["error_count"] == 1
    assert metrics["active_tenants_count"] == 1

    # Recent events with tenant filter
    recent = tc.get_recent_events(limit=10, tenant_id="tenant_x")
    assert len(recent) == 10
    recent_other = tc.get_recent_events(limit=10, tenant_id="none")
    assert len(recent_other) == 0


def test_lifecycle_interceptor_and_middleware_pipeline_full():
    """Verifies default LifecycleInterceptor hooks, QueryCancelledError, and pipeline runs."""
    from query_builder.middleware import (
        LifecycleInterceptor,
        MiddlewarePipeline,
        QueryCancelledError,
    )

    # QueryCancelledError
    err = QueryCancelledError("cancelled", {"detail": 1})
    assert err.message == "cancelled"
    assert err.context == {"detail": 1}

    # Default hooks
    interceptor = LifecycleInterceptor()
    ctx = {}
    assert interceptor.on_pre_compile({}, ctx) is None
    assert interceptor.on_post_compile({}, ctx) is None
    assert interceptor.on_pre_execute({}, ctx) is None
    assert interceptor.on_post_execute({}, ctx) is None
    assert interceptor.on_error(ValueError(), ctx) is None

    # Pipeline ensure
    p0 = MiddlewarePipeline.ensure(None)
    assert len(p0.interceptors) == 0
    p1 = MiddlewarePipeline.ensure(p0)
    assert p1 is p0
    p2 = MiddlewarePipeline.ensure(interceptor)
    assert len(p2.interceptors) == 1
    p3 = MiddlewarePipeline.ensure([interceptor])
    assert len(p3.interceptors) == 1
    p4 = MiddlewarePipeline.ensure((interceptor,))
    assert len(p4.interceptors) == 1

    with pytest.raises(TypeError, match="Cannot convert str"):
        MiddlewarePipeline.ensure("bad")
    with pytest.raises(TypeError, match="Expected LifecycleInterceptor"):
        p0.add("bad")  # type: ignore

    # Pipeline execution hooks
    class DummyHook(LifecycleInterceptor):
        def on_pre_compile(self, spec, ctx):
            return {"table": "rewritten"}

        def on_post_compile(self, comp, ctx):
            return {"main_sql": "SELECT rewritten"}

        def on_pre_execute(self, plan, ctx):
            return {"cached": True}

        def on_post_execute(self, res, ctx):
            return {"rows": [1]}

        def on_error(self, err, ctx):
            ctx["error_handled"] = True

    pipe = MiddlewarePipeline([DummyHook()])
    assert pipe.run_pre_compile({}, ctx) == {"table": "rewritten"}
    assert pipe.run_post_compile({}, ctx) == {"main_sql": "SELECT rewritten"}
    short, res = pipe.run_pre_execute({}, ctx)
    assert short is True
    assert res == {"cached": True}
    assert pipe.run_post_execute({}, ctx) == {"rows": [1]}

    pipe.run_error(ValueError("test"), ctx)
    assert ctx["error_handled"] is True


def test_security_middleware_extended_paths():
    """Verifies CTE rejection, execution target validation, non-dict rows, and comments."""
    # CTE forbidden
    cfg_no_cte = SecurityConfig(validation=ValidationSecurityConfig(allow_cte=False))
    mid_no_cte = SecurityMiddleware(config=cfg_no_cte)
    with pytest.raises(SecurityError, match="forbidden by validation security"):
        mid_no_cte.on_post_compile(
            {"main_sql": "WITH cte AS (SELECT 1) SELECT * FROM cte"}, {}
        )

    # Execution target with URL in execution_plan
    mid_exec = SecurityMiddleware(
        config=SecurityConfig(
            network=NetworkSecurityConfig(
                allow_private_networks=False, enforce_tls=False
            )
        )
    )
    with pytest.raises(SecurityError, match="private/internal network target"):
        mid_exec.on_pre_execute({"url": "http://127.0.0.1:5432/db"}, {})

    # Post execute with non-dict rows in list
    cfg_mask = SecurityConfig(
        privacy=PrivacySecurityConfig(sensitive_column_patterns=[r"(?i)(pwd)"])
    )
    mid_mask = SecurityMiddleware(config=cfg_mask)
    post_res = mid_mask.on_post_execute(
        {"rows": ["not_a_dict_row", {"pwd": "secret123"}]},
        {"tenant_context": TenantContext(tenant_id="t1", roles=["viewer"])},
    )
    assert post_res["rows"][0] == "not_a_dict_row"
    assert post_res["rows"][1]["pwd"] == "[REDACTED]"


def test_policy_engine_extended_branches():
    """Verifies table allow/denylists, tenant filter injection, and RLS attribute resolution."""
    # Unsupported spec type
    with pytest.raises(SecurityError, match="Unsupported spec type"):
        apply_security_policy(123)  # type: ignore

    # Missing table
    with pytest.raises(SecurityError, match="missing required 'table'"):
        apply_security_policy({})
    with pytest.raises(SecurityError, match="missing required 'table'"):
        apply_security_policy({"table": "  "})

    # Tenant isolation enforced without context
    with pytest.raises(SecurityError, match="no TenantContext provided"):
        apply_security_policy(
            {"table": "users"},
            policy=SecurityPolicy(enforce_tenant_isolation=True),
        )

    # Tenant isolation enforced with empty tenant_id
    with pytest.raises(SecurityError, match="tenant_id is missing or empty"):
        apply_security_policy(
            {"table": "users"},
            context=TenantContext(tenant_id="   "),
            policy=SecurityPolicy(enforce_tenant_isolation=True),
        )

    # Restricted tables
    with pytest.raises(SecurityError, match="restricted table 'secrets' is forbidden"):
        apply_security_policy(
            {"table": "secrets"},
            context=TenantContext(tenant_id="t1"),
            policy=SecurityPolicy(restricted_tables=["secrets"]),
        )

    # Allowed tables violation
    with pytest.raises(SecurityError, match="forbidden by allowed_tables policy"):
        apply_security_policy(
            {"table": "other_table"},
            context=TenantContext(tenant_id="t1"),
            policy=SecurityPolicy(allowed_tables=["users", "orders"]),
        )

    # Join table tenant injection
    spec_join = {
        "table": "orders",
        "joins": [{"table": "items"}],
    }
    res_join = apply_security_policy(
        spec_join,
        context=TenantContext(tenant_id="t1"),
        policy=SecurityPolicy(),
    )
    assert len(res_join["filters"]) == 2

    # RLS filters with $user_id, $tenant_id, $attr.
    rls_policy = SecurityPolicy(
        row_level_filters={
            "orders": [
                {"column": "owner", "op": "eq", "value": "$user_id"},
                {"column": "org", "op": "eq", "value": "$tenant_id"},
                {"column": "dept", "op": "eq", "value": "$attr.department"},
            ]
        }
    )
    ctx_rls = TenantContext(
        tenant_id="t_rls",
        user_id="u_rls",
        attributes={"department": "engineering"},
    )
    res_rls = apply_security_policy(
        {"table": "orders"},
        context=ctx_rls,
        policy=rls_policy,
    )
    # 1 tenant filter + 3 RLS filters = 4 filters
    assert len(res_rls["filters"]) == 4
    vals = [f["value"] for f in res_rls["filters"]]
    assert "u_rls" in vals
    assert "t_rls" in vals
    assert "engineering" in vals

    # Policy as dict
    res_dict_policy = apply_security_policy(
        {"table": "public_data"},
        policy={"enforce_tenant_isolation": False},
    )
    assert res_dict_policy["table"] == "public_data"


def test_full_branch_closure_edge_cases():
    """Validates every remaining branch across all Milestone 2 security modules."""
    from query_builder.models import SchemaSnapshot

    # 1. Telemetry non-redacted parameter scrubbing
    tc = TelemetryCollector()
    ev = tc.record_execution(
        sql="SELECT 1",
        latency_ms=1.0,
        parameters=["password=secret"],
        redact_parameters=False,
    )
    assert ev.parameters == ["password=***"]

    # 2. Security IPv6 multicast, config variants, URL without host
    with pytest.raises(SecurityError, match="private/internal"):
        validate_network_target(host="ff02::1")

    validate_network_target(
        config={"security": NetworkSecurityConfig(allow_private_networks=True)},
        host="10.0.0.1",
    )
    validate_network_target(config={"host": "8.8.8.8", "url": "https://8.8.8.8:443"})
    validate_network_target(url="file:///local/path")

    # 3. Complexity & Cartesian with JoinSpec dataclass and distinct=False
    comp = calculate_ast_complexity(
        {
            "table": "users",
            "columns": [{"column": "c1", "distinct": False}],
            "joins": [JoinSpec(table="orders")],
        }
    )
    assert comp > 0

    with pytest.raises(SecurityError, match="lacks join conditions"):
        check_cartesian_products(
            {"table": "users", "joins": [JoinSpec(table="orders")]}
        )

    # 4. Middleware permissive limits, catalog allowances, comment preservation
    cfg_zero = SecurityConfig(
        execution=ExecutionSecurityConfig(
            max_complexity_score=5000,
            max_join_depth=100,
            max_rows_limit=5000,
            prevent_cartesian_products=False,
            enforce_read_only_session=False,
        ),
        validation=ValidationSecurityConfig(allowed_statements=["SELECT", "INSERT"]),
        privacy=PrivacySecurityConfig(enforce_tenant_isolation=False),
    )
    mid_zero = SecurityMiddleware(config=cfg_zero)
    # Allows cross joins and mutations when disabled
    pre = mid_zero.on_pre_compile(
        {"table": "users", "joins": [{"table": "j", "type": "CROSS"}]}, {}
    )
    assert pre["table"] == "users"
    post_c = mid_zero.on_post_compile({"main_sql": "INSERT INTO users VALUES (1)"}, {})
    assert "INSERT" in post_c["main_sql"]

    # Post execute with non-list rows and limit=0
    assert mid_zero.on_post_execute({"rows": "not_a_list"}, {})["rows"] == "not_a_list"
    assert len(mid_zero.on_post_execute({"rows": [1, 2, 3]}, {})["rows"]) == 3

    # Allow catalogs and comments preserved
    cfg_cat = SecurityConfig(
        validation=ValidationSecurityConfig(allow_system_catalogs=True)
    )
    assert (
        "sqlite_master"
        in SecurityMiddleware(config=cfg_cat).on_post_compile(
            {"main_sql": "SELECT * FROM sqlite_master"}, {}
        )["main_sql"]
    )

    cfg_comm = SecurityConfig(
        validation=ValidationSecurityConfig(filter_sql_comments=False)
    )
    assert (
        "-- comm"
        in SecurityMiddleware(config=cfg_comm).on_post_compile(
            {"main_sql": "SELECT 1 -- comm"}, {}
        )["main_sql"]
    )

    # Pipeline bad hook returns and error deduplication
    class BadPre(LifecycleInterceptor):
        def on_pre_compile(self, s, c):
            return "bad"

    with pytest.raises(TypeError, match="on_pre_compile must return dict"):
        MiddlewarePipeline([BadPre()]).run_pre_compile({}, {})

    class BadPostC(LifecycleInterceptor):
        def on_post_compile(self, comp, c):
            return "bad"

    with pytest.raises(TypeError, match="on_post_compile must return dict"):
        MiddlewarePipeline([BadPostC()]).run_post_compile({}, {})

    class BadPostE(LifecycleInterceptor):
        def on_post_execute(self, r, c):
            return "bad"

    with pytest.raises(TypeError, match="on_post_execute must return dict"):
        MiddlewarePipeline([BadPostE()]).run_post_execute({}, {})

    # Error deduplication
    pipe_err = MiddlewarePipeline([LifecycleInterceptor()])
    err_inst = ValueError("dedup")
    ctx_dedup = {}
    pipe_err.run_error(err_inst, ctx_dedup)
    pipe_err.run_error(err_inst, ctx_dedup)

    # 5. Policy engine QuerySpec input, schema joins, existing filters, non-string cols
    qspec = QuerySpec(table="users", columns=["id"])
    assert (
        apply_security_policy(
            qspec, policy=SecurityPolicy(enforce_tenant_isolation=False)
        )["table"]
        == "users"
    )

    sec_cfg_no_tenant = SecurityConfig(
        privacy=PrivacySecurityConfig(enforce_tenant_isolation=False)
    )
    assert (
        apply_security_policy({"table": "users"}, policy=sec_cfg_no_tenant)["table"]
        == "users"
    )

    # Restricted tables check with table NOT in restricted
    apply_security_policy(
        {"table": "allowed_tbl"},
        policy=SecurityPolicy(
            enforce_tenant_isolation=False, restricted_tables=["other_tbl"]
        ),
    )

    # Schema join where joined table lacks tenant_id
    schema_no_t = SchemaSnapshot(tables={"items": {"columns": [{"name": "id"}]}})
    res_no_t = apply_security_policy(
        {"table": "orders", "joins": [{"table": "items"}]},
        schema=schema_no_t,
        context=TenantContext("t1"),
    )
    assert len(res_no_t["filters"]) == 1  # Only orders gets tenant filter

    # Joined table already has tenant filter
    res_existing_j = apply_security_policy(
        {
            "table": "orders",
            "joins": [{"table": "items"}],
            "filters": [
                {
                    "column": "tenant_id",
                    "op": "eq",
                    "value": "t1",
                    "tablePrefix": "items",
                }
            ],
        },
        context=TenantContext("t1"),
    )
    assert len(res_existing_j["filters"]) == 2

    # RLS rule with tablePrefix and non-string column passthrough
    res_rls_pfx = apply_security_policy(
        {"table": "orders", "columns": [123, {"column": "secret", "alias": "s_alias"}]},
        policy=SecurityPolicy(
            column_masking={"orders": ["secret"]},
            row_level_filters={
                "orders": [
                    {
                        "column": "flag",
                        "op": "eq",
                        "value": 1,
                        "tablePrefix": "orders",
                    }
                ]
            },
        ),
        context=TenantContext("t1", roles=["viewer"]),
    )
    assert res_rls_pfx["columns"][0] == 123
    assert res_rls_pfx["columns"][1]["masked"] is True


def test_final_100_percent_coverage_cases():
    """Closes all remaining edge cases to achieve 100% statement and branch coverage."""
    import ipaddress

    from query_builder.models import FilterSpec
    from query_builder.security import _is_private_or_restricted

    # 1. Security _is_private_or_restricted direct call with cloud metadata IP
    assert _is_private_or_restricted(ipaddress.ip_address("169.254.169.254")) is True

    # 2. validate_network_target with only port in config
    validate_network_target(config={"port": 5432})

    # 3. complexity distinct=False and window=False and joins JoinSpec
    assert (
        calculate_ast_complexity(
            {
                "table": "users",
                "columns": [
                    {"column": "c1", "distinct": True},
                    {"column": "c2", "distinct": False},
                ],
                "window": False,
            }
        )
        > 0
    )

    # 4. Middleware on_pre_compile when limit is already smaller than max_rows_limit
    mid = SecurityMiddleware(
        config=SecurityConfig(execution=ExecutionSecurityConfig(max_rows_limit=500))
    )
    res_lim = mid.on_pre_compile(
        {"table": "users", "limit": 100}, {"tenant_context": TenantContext("t1")}
    )
    assert res_lim["limit"] == 100

    # 5. Middleware post_compile with empty SQL and clean CTE
    assert mid.on_post_compile({"main_sql": ""}, {}) == {"main_sql": ""}
    assert (
        mid.on_post_compile(
            {"main_sql": "WITH cte AS (SELECT 1) SELECT * FROM cte"}, {}
        )
        is not None
    )

    # 6. Pipeline hooks returning None (transparent pass-through)
    pipe_none = MiddlewarePipeline([LifecycleInterceptor()])
    assert pipe_none.run_pre_compile({"table": "users"}, {}) == {"table": "users"}
    assert pipe_none.run_post_compile({"main_sql": "SELECT 1"}, {}) == {
        "main_sql": "SELECT 1"
    }
    is_short, plan = pipe_none.run_pre_execute({"plan": 1}, {})
    assert is_short is False
    assert plan == {"plan": 1}
    assert pipe_none.run_post_execute({"rows": []}, {}) == {"rows": []}

    # 7. Policy existing base tenant filter and non-string join table
    res_base_t = apply_security_policy(
        {
            "table": "orders",
            "filters": [{"column": "tenant_id", "op": "eq", "value": "t1"}],
            "joins": [{"table": None}],
        },
        context=TenantContext("t1"),
    )
    assert len(res_base_t["filters"]) == 1

    # 8. Policy FilterSpec object
    f_spec = FilterSpec(column="tenant_id", op="eq", value="t1", table_prefix="orders")
    res_f_obj = apply_security_policy(
        {"table": "orders", "filters": [f_spec]},
        context=TenantContext("t1"),
    )
    assert len(res_f_obj["filters"]) == 1

    # 9. Admin bypass with column masking configured
    res_admin = apply_security_policy(
        {"table": "users", "columns": ["ssn"]},
        policy=SecurityPolicy(column_masking={"users": ["ssn"]}),
        context=TenantContext("t1", roles=["admin"]),
    )
    assert res_admin["columns"] == ["ssn"]


def test_worker_coverage_gaps_closure():
    """Closes all remaining branch coverage gaps in middleware, policy, and security."""
    from query_builder.config import (
        NetworkSecurityConfig,
        SecurityConfig,
    )
    from query_builder.middleware import SecurityMiddleware
    from query_builder.policy import apply_security_policy
    from query_builder.security import (
        calculate_ast_complexity,
        validate_network_target,
    )

    # 1. middleware 132->138: max_rows_limit <= 0 bypasses row limit ceiling
    mid_zero_lim = SecurityMiddleware(config=SecurityConfig())
    mid_zero_lim.config.execution.max_rows_limit = 0
    res_zero = mid_zero_lim.on_pre_compile(
        {"table": "users", "limit": 999},
        {"tenant_context": TenantContext("t1")},
    )
    assert res_zero["limit"] == 999

    # 2. middleware 187->201: allowed_statements is empty list
    mid_no_allowed = SecurityMiddleware(config=SecurityConfig())
    mid_no_allowed.config.validation.allowed_statements = []
    res_no_allowed = mid_no_allowed.on_post_compile({"main_sql": "SELECT 1"}, {})
    assert res_no_allowed == {"main_sql": "SELECT 1"}

    # 3. middleware 254->263: empty execution_plan and empty context skips network validation
    mid_empty_plan = SecurityMiddleware(config=SecurityConfig())
    assert mid_empty_plan.on_pre_execute({}, {}) is None

    # 4. policy line 103: duck-typed policy without sensitive_column_patterns or tenant_column
    class CustomDuckPolicy:
        def __init__(self) -> None:
            self.enforce_tenant_isolation = False
            self.allowed_tables = None
            self.restricted_tables = []
            self.row_level_filters = {}
            self.column_masking = {}
            self.sensitive_column_patterns = []

    res_duck = apply_security_policy(
        {"table": "users", "columns": ["id"]},
        policy=CustomDuckPolicy(),
    )
    assert res_duck["columns"] == ["id"]

    # 5. security 301->303: port is not None when config is provided
    validate_network_target(
        port=5432,
        config={"host": "localhost"},
        network_config=NetworkSecurityConfig(allow_private_networks=True),
    )

    # 6. security 531->524: column is not dict and not str
    score_non_str_col = calculate_ast_complexity(
        {"table": "users", "columns": [123, 456]}
    )
    assert score_non_str_col > 0

    # 7. security 579->577: CTE is not dict and not QuerySpec (e.g. raw string)
    score_cte_str = calculate_ast_complexity(
        {"table": "users", "ctes": ["WITH raw_cte AS (SELECT 1)"]}
    )
    assert score_cte_str > 0


def test_validate_network_target_bracketed_ips_and_ssrf():
    """Verifies that bracketed IP addresses and hostnames are validated against SSRF boundaries."""
    cfg_strict = NetworkSecurityConfig(allow_private_networks=False, enforce_tls=False)
    cfg_allow = NetworkSecurityConfig(allow_private_networks=True, enforce_tls=False)

    # 1. Cloud metadata IPv4 in brackets is strictly forbidden
    with pytest.raises(SecurityError, match="cloud metadata"):
        validate_network_target(host="[169.254.169.254]", network_config=cfg_strict)
    with pytest.raises(SecurityError, match="cloud metadata"):
        validate_network_target(host="[169.254.169.254]", network_config=cfg_allow)

    # 2. Cloud metadata IPv6 in brackets is strictly forbidden
    with pytest.raises(SecurityError, match="cloud metadata"):
        validate_network_target(host="[fd00:ec2::254]", network_config=cfg_strict)
    with pytest.raises(SecurityError, match="cloud metadata"):
        validate_network_target(host="[fd00:ec2::254]", network_config=cfg_allow)

    # 3. IPv4-mapped IPv6 cloud metadata in brackets is strictly forbidden
    with pytest.raises(SecurityError, match="cloud metadata"):
        validate_network_target(
            host="[::ffff:169.254.169.254]", network_config=cfg_strict
        )

    # 4. Bracketed private IPs blocked when allow_private_networks=False
    with pytest.raises(SecurityError, match="private/internal"):
        validate_network_target(host="[10.0.0.1]", network_config=cfg_strict)
    with pytest.raises(SecurityError, match="private/internal"):
        validate_network_target(host="[192.168.1.1]", network_config=cfg_strict)
    with pytest.raises(SecurityError, match="private/internal"):
        validate_network_target(host="[127.0.0.1]", network_config=cfg_strict)
    with pytest.raises(SecurityError, match="private/internal"):
        validate_network_target(host="[::1]", network_config=cfg_strict)

    # 5. Bracketed private IPs permitted when allow_private_networks=True
    validate_network_target(host="[10.0.0.1]", network_config=cfg_allow)
    validate_network_target(host="[127.0.0.1]", network_config=cfg_allow)
    validate_network_target(host="[::1]", network_config=cfg_allow)

    # 6. Bracketed loopback hostnames
    with pytest.raises(SecurityError, match="loopback"):
        validate_network_target(host="[localhost]", network_config=cfg_strict)
    with pytest.raises(SecurityError, match="loopback"):
        validate_network_target(
            host="[localhost.localdomain]", network_config=cfg_strict
        )
    validate_network_target(host="[localhost]", network_config=cfg_allow)

    # 7. Bracketed blocked and allowed hostnames
    cfg_block = NetworkSecurityConfig(
        blocked_hostnames=["blocked.internal", "*.blocked.com"]
    )
    with pytest.raises(SecurityError, match="blocked hostnames"):
        validate_network_target(host="[blocked.internal]", network_config=cfg_block)
    with pytest.raises(SecurityError, match="blocked hostnames"):
        validate_network_target(host="[sub.blocked.com]", network_config=cfg_block)

    cfg_allowlist = NetworkSecurityConfig(
        allowed_hostnames=["allowed.internal"], allow_private_networks=True
    )
    validate_network_target(host="[allowed.internal]", network_config=cfg_allowlist)
    with pytest.raises(SecurityError, match="not in allowed hostnames"):
        validate_network_target(host="[other.internal]", network_config=cfg_allowlist)

    # 8. Bracketed cloud metadata hostname
    with pytest.raises(SecurityError, match="cloud metadata"):
        validate_network_target(
            host="[metadata.google.internal]", network_config=cfg_allow
        )

    # 9. Malformed bracketed IPv4 in URL raises SecurityError
    with pytest.raises(SecurityError, match="Invalid network target URL"):
        validate_network_target(
            url="http://[169.254.169.254]:80", network_config=cfg_strict
        )


def test_security_middleware_permits_mutation_words_in_literals_and_comments():
    """Verifies that SecurityMiddleware does not reject read-only queries with mutation words in literals or comments."""
    cfg = SecurityConfig(
        execution=ExecutionSecurityConfig(enforce_read_only_session=True)
    )
    mw = SecurityMiddleware(config=cfg)

    # 1. String literal with 'cannot delete'
    res1 = mw.on_post_compile({"main_sql": "SELECT 'cannot delete' AS msg"}, {})
    assert res1 == {"main_sql": "SELECT 'cannot delete' AS msg"}

    # 2. String literal with 'cannot delete record' and 'drop'
    sql2 = "SELECT is_deleted, 'cannot delete record' AS note FROM production.firm_master WHERE name = 'drop';"
    res2 = mw.on_post_compile({"main_sql": sql2}, {})
    assert res2 == {"main_sql": sql2}

    # 3. Column alias named delete (following AS)
    sql3 = "SELECT id AS delete FROM firm_master;"
    res3 = mw.on_post_compile({"main_sql": sql3}, {})
    assert res3 == {"main_sql": sql3}

    # 4. Inline comment containing mutation keywords
    sql4 = "SELECT * FROM users -- comment with DELETE FROM users\nWHERE id = 1;"
    res4 = mw.on_post_compile({"main_sql": sql4}, {})
    assert res4 is not None

    # 5. Block comment containing mutation keywords
    sql5 = "SELECT * FROM users /* block comment mentioning DROP TABLE */ WHERE id = 1;"
    res5 = mw.on_post_compile({"main_sql": sql5}, {})
    assert res5 is not None

    # 6. Multiple string literals with various mutation words
    sql6 = "SELECT id, 'UPDATE record' AS action, 'CREATE view' AS tip FROM orders;"
    res6 = mw.on_post_compile({"main_sql": sql6}, {})
    assert res6 == {"main_sql": sql6}

    # 7. Actual mutating queries are still rejected
    mutating_queries = [
        "DELETE FROM users WHERE id = 1;",
        "DROP TABLE users;",
        "UPDATE users SET name = 'alice';",
        "INSERT INTO users (id) VALUES (1);",
        "TRUNCATE TABLE users;",
        "ALTER TABLE users ADD COLUMN c INT;",
        "CREATE TABLE t (id INT);",
        "EXEC sp_my_proc;",
        "EXECUTE sp_my_proc;",
        "GRANT SELECT ON t TO u;",
        "REVOKE SELECT ON t FROM u;",
        "SELECT 1; DROP TABLE users;",
        "WITH cte AS (SELECT 1) DELETE FROM users WHERE id = 1;",
    ]
    for m_sql in mutating_queries:
        with pytest.raises(SecurityError, match="Read-only session violation"):
            mw.on_post_compile({"main_sql": m_sql}, {})


def test_scrub_secrets_preserves_schema_keys_and_benign_words():
    """Verifies that schema metadata keys and innocent words containing 'key' or 'auth' are preserved."""
    payload = {
        # Schema metadata keys must be preserved
        "primary_key": "id",
        "foreign_key": "user_id",
        "partition_key": "pk_001",
        "sort_key": "sk_001",
        "clustering_key": "cluster_id",
        # Benign dictionary keys containing substring 'key' or 'auth'
        "hockey": "sport",
        "turkey": "country",
        "monkey": "animal",
        "keyboard": "device",
        "author": "Shakespeare",
        "authority": "municipal",
        # Standard attributes
        "user_id": 42,
        "is_active": True,
        # Actual secrets must still be redacted
        "password": "secret_password",
        "user_password": "my_password",
        "passwd": "secret_passwd",
        "pwd": "secret_pwd",
        "secret": "top_secret",
        "client_secret": "cs_12345",
        "secret_key": "sk_abcde",
        "token": "tok_abcdef",
        "access_token": "acc_tok",
        "refresh_token": "ref_tok",
        "auth": "auth_header_val",
        "auth_key": "ak_123",
        "authorization": "Bearer xyz",
        "api_key": "api_key_val",
        "apiKey": "apiKey_val",
        "api-key": "api-key_val",
        "private_key": "priv_key_val",
        "key": "standalone_key_val",
        "Key": "capitalized_key_val",
    }

    scrubbed = scrub_secrets(payload)

    # Assert schema keys and benign words are NOT scrubbed
    assert scrubbed["primary_key"] == "id"
    assert scrubbed["foreign_key"] == "user_id"
    assert scrubbed["partition_key"] == "pk_001"
    assert scrubbed["sort_key"] == "sk_001"
    assert scrubbed["clustering_key"] == "cluster_id"
    assert scrubbed["hockey"] == "sport"
    assert scrubbed["turkey"] == "country"
    assert scrubbed["monkey"] == "animal"
    assert scrubbed["keyboard"] == "device"
    assert scrubbed["author"] == "Shakespeare"
    assert scrubbed["authority"] == "municipal"
    assert scrubbed["user_id"] == 42
    assert scrubbed["is_active"] is True

    # Assert sensitive keys ARE scrubbed
    sensitive_keys = [
        "password",
        "user_password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "auth",
        "auth_key",
        "authorization",
        "api_key",
        "apiKey",
        "api-key",
        "private_key",
        "key",
        "Key",
    ]
    for sk in sensitive_keys:
        assert scrubbed[sk] == "***", f"Expected sensitive key '{sk}' to be scrubbed"
