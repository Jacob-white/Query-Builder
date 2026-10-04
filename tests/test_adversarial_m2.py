"""
Adversarial Stress Test Suite for Milestone 2.
Empirical verification of security boundaries, edge cases, vulnerabilities, and failure modes.
"""

import hashlib
import socket
from unittest.mock import patch

import pytest

from query_builder.config import (
    ExecutionSecurityConfig,
    NetworkSecurityConfig,
    PrivacySecurityConfig,
    SecurityConfig,
    ValidationSecurityConfig,
)
from query_builder.middleware import (
    SecurityMiddleware,
)
from query_builder.security import (
    SecurityError,
    apply_column_masking,
    calculate_ast_complexity,
    check_cartesian_products,
    scrub_secrets,
    validate_network_target,
)
from query_builder.telemetry import (
    TelemetryCollector,
)

# ===========================================================================
# 1. Network Target Validation Adversarial Tests
# ===========================================================================


class TestNetworkTargetAdversarial:
    """Stress-tests validate_network_target against bypasses, malformed inputs, and edge cases."""

    def test_cloud_metadata_ipv4_mapped_ipv6(self):
        """Test IPv4-mapped IPv6 representation of cloud metadata (::ffff:169.254.169.254)."""
        cfg = NetworkSecurityConfig(allow_private_networks=True)
        # Should be blocked even when allow_private_networks is True
        with pytest.raises(SecurityError, match="cloud metadata"):
            validate_network_target(host="::ffff:169.254.169.254", network_config=cfg)

    def test_cloud_metadata_aws_ipv6(self):
        """Test AWS IPv6 metadata address fd00:ec2::254."""
        cfg = NetworkSecurityConfig(allow_private_networks=True)
        with pytest.raises(SecurityError, match="cloud metadata"):
            validate_network_target(host="fd00:ec2::254", network_config=cfg)

    def test_cloud_metadata_url_bracketed_ipv6(self):
        """Test URL containing bracketed IPv6 address https://[fd00:ec2::254]:443/latest."""
        cfg = NetworkSecurityConfig(allow_private_networks=False, enforce_tls=True)
        with pytest.raises(SecurityError, match="cloud metadata"):
            validate_network_target(
                url="https://[fd00:ec2::254]:443/latest", network_config=cfg
            )

    def test_bracketed_host_ssrf_bypass_vulnerability(self):
        """Verify bracketed host string does not bypass IP validation.
        When host='[169.254.169.254]' is provided directly (or in config), validate_network_target
        safely strips brackets and detects forbidden cloud metadata.
        """
        cfg = NetworkSecurityConfig(allow_private_networks=False)
        with pytest.raises(SecurityError, match="cloud metadata"):
            validate_network_target(host="[169.254.169.254]", network_config=cfg)

    def test_cgnat_shared_address_space(self):
        """Test Carrier-Grade NAT (RFC 6598: 100.64.0.0/10) blocking."""
        cfg = NetworkSecurityConfig(allow_private_networks=False)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="100.64.0.1", network_config=cfg)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="100.127.255.254", network_config=cfg)

        # Permitted when allow_private_networks is True
        cfg_allow = NetworkSecurityConfig(allow_private_networks=True)
        validate_network_target(host="100.64.0.1", network_config=cfg_allow)

    def test_ipv6_unique_local_and_link_local(self):
        """Test IPv6 ULA (fc00::/7) and link-local (fe80::/10) blocking."""
        cfg = NetworkSecurityConfig(allow_private_networks=False)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="fc00::1", network_config=cfg)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="fd12:3456:789a::1", network_config=cfg)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="fe80::1", network_config=cfg)

    def test_localhost_and_loopback_aliases(self):
        """Test various loopback representations."""
        cfg = NetworkSecurityConfig(allow_private_networks=False)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="127.0.0.1", network_config=cfg)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="127.0.0.2", network_config=cfg)
        with pytest.raises(SecurityError, match="private/internal"):
            validate_network_target(host="::1", network_config=cfg)
        with pytest.raises(SecurityError, match="loopback"):
            validate_network_target(host="localhost", network_config=cfg)
        with pytest.raises(SecurityError, match="loopback"):
            validate_network_target(host="localhost.localdomain", network_config=cfg)

    def test_cloud_metadata_hostnames(self):
        """Test known cloud metadata hostnames."""
        cfg = NetworkSecurityConfig(allow_private_networks=True)
        for host in [
            "metadata.google.internal",
            "metadata.internal",
            "metadata",
            "instance-data",
            "foo.google.internal",
        ]:
            with pytest.raises(SecurityError, match="cloud metadata"):
                validate_network_target(host=host, network_config=cfg)

    def test_insecure_schemes_under_enforce_tls(self):
        """Test that plain HTTP and ws schemes are rejected when TLS is enforced."""
        cfg = NetworkSecurityConfig(enforce_tls=True)
        with pytest.raises(SecurityError, match="insecure scheme"):
            validate_network_target(
                url="http://db.example.com:5432/db", network_config=cfg
            )
        with pytest.raises(SecurityError, match="insecure scheme"):
            validate_network_target(
                url="ws://db.example.com:5432/db", network_config=cfg
            )
        with pytest.raises(SecurityError, match="insecure scheme"):
            validate_network_target(
                url="ftp://db.example.com:21/dump", network_config=cfg
            )

    def test_port_boundaries(self):
        """Test port validation boundary conditions."""
        cfg = NetworkSecurityConfig(allow_private_networks=True, enforce_tls=False)
        # Valid ports
        validate_network_target(host="db.example.com", port=1, network_config=cfg)
        validate_network_target(host="db.example.com", port=65535, network_config=cfg)

        # Invalid ports
        for bad_port in [0, -1, 65536, 100000, "invalid_port"]:
            with pytest.raises(SecurityError, match="Invalid network port"):
                validate_network_target(
                    host="db.example.com", port=bad_port, network_config=cfg
                )

    def test_dns_resolution_private_ip_detection(self):
        """Test that DNS resolving to private IP is caught and rejected."""
        cfg = NetworkSecurityConfig(allow_private_networks=False)
        mock_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 5432))
        ]
        with (
            patch("socket.getaddrinfo", return_value=mock_addr_info),
            pytest.raises(
                SecurityError, match="resolves to forbidden private/internal IP"
            ),
        ):
            validate_network_target(
                host="my-internal-db.example.com", network_config=cfg
            )

    def test_dns_resolution_metadata_ip_detection(self):
        """Test that DNS resolving to cloud metadata IP is caught even if allow_private_networks=True."""
        cfg = NetworkSecurityConfig(allow_private_networks=True)
        mock_addr_info = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
        ]
        with (
            patch("socket.getaddrinfo", return_value=mock_addr_info),
            pytest.raises(
                SecurityError, match="resolves to forbidden cloud metadata IP"
            ),
        ):
            validate_network_target(
                host="evil-redirect.example.com", network_config=cfg
            )


# ===========================================================================
# 2. Secret Scrubbing Adversarial Tests
# ===========================================================================


class TestSecretScrubbingAdversarial:
    """Stress-tests scrub_secrets against deeply nested, varied, and tricky inputs."""

    def test_deeply_nested_structures(self):
        """Test scrubbing nested within dicts, lists, tuples, and sets."""
        payload = {
            "level1": [
                (
                    {"password": "secret_value_123"},
                    {"token": "bearer_abc"},
                ),
                {"api_key": "xyz_api_key"},
            ],
            "auth_header": "Bearer secret_bearer_token_xyz",
            "db_uri": "postgres://admin:super_secret_pw@db.internal:5432/app",
            "safe_data": {"user_id": 42, "status": "active"},
        }
        scrubbed = scrub_secrets(payload)
        assert scrubbed["level1"][0][0]["password"] == "***"
        assert scrubbed["level1"][0][1]["token"] == "***"
        assert scrubbed["level1"][1]["api_key"] == "***"
        assert "secret_bearer_token_xyz" not in scrubbed["auth_header"]
        assert "super_secret_pw" not in scrubbed["db_uri"]
        assert "***" in scrubbed["auth_header"]
        assert "***" in scrubbed["db_uri"]
        assert scrubbed["safe_data"]["user_id"] == 42

    def test_overmatching_key_substring_behavior(self):
        """Verify schema metadata keys and benign words containing 'key' are preserved."""
        data = {
            "primary_key": "id",
            "foreign_key": "user_id",
            "hockey": "sport",
        }
        res = scrub_secrets(data)
        assert res["primary_key"] == "id"
        assert res["foreign_key"] == "user_id"
        assert res["hockey"] == "sport"

    def test_key_value_string_scrubbing(self):
        """Test string sanitization for key-value secret pairs."""
        text = "Connecting with password=mySecretPassword and api_key='secret-123' token: abcdef"
        scrubbed = scrub_secrets(text)
        assert "mySecretPassword" not in scrubbed
        assert "secret-123" not in scrubbed
        assert "abcdef" not in scrubbed

    def test_exception_scrubbing(self):
        """Test sanitizing secrets within an Exception instance."""
        exc = ValueError(
            "Failed connection to postgres://user:topsecret@localhost:5432/db"
        )
        scrubbed_exc = scrub_secrets(exc)
        assert isinstance(scrubbed_exc, ValueError)
        assert "topsecret" not in str(scrubbed_exc)
        assert "***" in str(scrubbed_exc)

    def test_custom_patterns(self):
        """Test custom regex patterns for scrubbing dict keys."""
        custom_patterns = [r"(?i)(ssn|credit_card)"]
        payload = {"ssn": "000-12-3456", "safe_column": "kept"}
        scrubbed = scrub_secrets(payload, patterns=custom_patterns)
        assert scrubbed["ssn"] == "***"
        assert scrubbed["safe_column"] == "kept"

    def test_string_scrubbing_ignores_custom_patterns(self):
        """Empirical observation: _scrub_string does not use custom patterns parameter when scrubbing strings."""
        custom_patterns = [r"(?i)custom_secret_\d+"]
        text = "custom_secret_12345"
        res = scrub_secrets(text, patterns=custom_patterns)
        assert res == "custom_secret_12345"


# ===========================================================================
# 3. AST Complexity & Cartesian Product Adversarial Tests
# ===========================================================================


class TestASTComplexityAndCartesianAdversarial:
    """Stress-tests calculate_ast_complexity and check_cartesian_products."""

    def test_ast_complexity_deeply_nested_subqueries(self):
        """Calculate complexity of deeply nested subqueries without stack overflow."""
        inner = {"table": "t1", "columns": ["id"]}
        for i in range(2, 20):
            inner = {
                "table": f"t{i}",
                "columns": ["id", {"agg": "COUNT", "name": "cnt"}],
                "filters": [{"column": "x", "op": "in", "value": inner}],
            }
        score = calculate_ast_complexity(inner)
        assert score > 100

    def test_ast_complexity_complex_query(self):
        """Test scoring of query with CTEs, joins, aggregates, filters, grouping."""
        spec = {
            "table": "orders",
            "columns": [
                "id",
                {"aggregation": "SUM", "name": "total", "distinct": True},
                "COUNT(items)",
            ],
            "joins": [
                {
                    "table": "customers",
                    "type": "LEFT",
                    "on": ["orders.c_id = customers.id"],
                },
                {"table": "rates", "type": "CROSS"},
            ],
            "filters": [
                {"column": "status", "op": "like", "value": "active%"},
            ],
            "group_by": ["id", "c_id"],
            "having": [{"column": "total", "op": "gt", "value": 100}],
            "order_by": ["total DESC"],
            "ctes": [{"table": "rates", "columns": ["currency", "rate"]}],
            "window": True,
        }
        score = calculate_ast_complexity(spec)
        assert score >= 40

    def test_cartesian_product_detection(self):
        """Detect missing join conditions and prohibited CROSS JOINs."""
        # 1. Prohibited CROSS JOIN
        cross_spec = {
            "table": "orders",
            "joins": [{"table": "items", "type": "CROSS"}],
        }
        with pytest.raises(SecurityError, match="explicit CROSS JOIN"):
            check_cartesian_products(cross_spec)

        # 2. Join lacking conditions
        unbounded_spec = {
            "table": "orders",
            "joins": [{"table": "items", "type": "LEFT"}],
        }
        with pytest.raises(SecurityError, match="lacks join conditions"):
            check_cartesian_products(unbounded_spec)

        # 3. Join with valid left_col / right_col passes
        valid_spec = {
            "table": "orders",
            "joins": [
                {
                    "table": "items",
                    "type": "LEFT",
                    "left_col": "item_id",
                    "right_col": "id",
                }
            ],
        }
        check_cartesian_products(valid_spec)

        # 4. Join with foreign_key relation passes
        fk_spec = {
            "table": "orders",
            "joins": [
                {"table": "items", "type": "LEFT", "foreign_key": "fk_order_item"}
            ],
        }
        check_cartesian_products(fk_spec)


# ===========================================================================
# 4. Column Masking Adversarial Tests
# ===========================================================================


class TestColumnMaskingAdversarial:
    """Stress-tests apply_column_masking across boundaries and types."""

    def test_partial_masking_short_and_unicode_strings(self):
        """Verify partial masking on short, empty, and unicode strings."""
        assert apply_column_masking("", "partial") == "***"
        assert apply_column_masking("a", "partial") == "***"
        assert apply_column_masking("ab", "partial") == "***"
        assert apply_column_masking("abc", "partial") == "a***c"
        assert apply_column_masking("abcd", "partial") == "a***d"
        assert apply_column_masking("abcde", "partial") == "ab***de"
        assert apply_column_masking("secret_data_here", "partial") == "se***re"

        # Unicode handling (single codepoint characters)
        assert apply_column_masking("你好世界", "partial") == "你***界"
        assert apply_column_masking("😀😁😂🤣😃", "partial") == "😀😁***🤣😃"

    def test_hash_masking_determinism(self):
        """Verify SHA-256 hash masking."""
        raw = "sensitive_email@example.com"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert apply_column_masking(raw, "hash") == expected

    def test_redact_and_none(self):
        """Verify redact strategy and None passthrough."""
        assert apply_column_masking("anything", "redact") == "[REDACTED]"
        assert apply_column_masking(None, "redact") is None
        assert apply_column_masking(None, "hash") is None
        assert apply_column_masking(None, "partial") is None

    def test_invalid_strategy_raises_value_error(self):
        """Verify that unrecognized strategy raises ValueError."""
        with pytest.raises(ValueError, match="Unknown masking strategy"):
            apply_column_masking("test", "non_existent_strategy")


# ===========================================================================
# 5. SecurityMiddleware & Policy Integration Adversarial Tests
# ===========================================================================


class TestSecurityMiddlewareAdversarial:
    """Stress-tests SecurityMiddleware lifecycle interceptor."""

    def test_pre_compile_complexity_rejection(self):
        """Middleware rejects queries exceeding max_complexity_score."""
        cfg = SecurityConfig(
            execution=ExecutionSecurityConfig(max_complexity_score=10),
        )
        mw = SecurityMiddleware(config=cfg)
        complex_spec = {
            "table": "orders",
            "columns": ["a", "b", "c", "d"],
            "joins": [
                {"table": "t1", "left_col": "x", "right_col": "y"},
                {"table": "t2", "left_col": "x", "right_col": "y"},
            ],
        }
        with pytest.raises(SecurityError, match="AST complexity score"):
            mw.on_pre_compile(complex_spec, {})

    def test_pre_compile_join_depth_rejection(self):
        """Middleware rejects queries exceeding max_join_depth."""
        cfg = SecurityConfig(
            execution=ExecutionSecurityConfig(max_join_depth=2),
        )
        mw = SecurityMiddleware(config=cfg)
        spec = {
            "table": "t",
            "joins": [
                {"table": "j1", "left_col": "a", "right_col": "b"},
                {"table": "j2", "left_col": "a", "right_col": "b"},
                {"table": "j3", "left_col": "a", "right_col": "b"},
            ],
        }
        with pytest.raises(SecurityError, match="Query join depth"):
            mw.on_pre_compile(spec, {})

    def test_post_compile_mutations_and_cte(self):
        """Middleware rejects mutating queries and unauthorized CTEs."""
        cfg = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=True),
            validation=ValidationSecurityConfig(
                allow_cte=False, allow_recursive_cte=False
            ),
        )
        mw = SecurityMiddleware(config=cfg)

        with pytest.raises(SecurityError, match="mutating statement detected"):
            mw.on_post_compile({"main_sql": "DELETE FROM users WHERE id = 1"}, {})

        with pytest.raises(SecurityError, match="CTEs.*are forbidden"):
            mw.on_post_compile(
                {"main_sql": "WITH cte AS (SELECT 1) SELECT * FROM cte"}, {}
            )

    def test_post_compile_mutation_false_positive_on_string_literal(self):
        """Verify that SecurityMiddleware does not produce false positives on valid read-only SELECT
        queries with string literals containing words like 'delete' or 'drop'.
        """
        cfg = SecurityConfig(
            execution=ExecutionSecurityConfig(enforce_read_only_session=True),
        )
        mw = SecurityMiddleware(config=cfg)
        sql = "SELECT is_deleted, 'cannot delete record' AS note FROM production.firm_master WHERE name = 'drop';"
        res = mw.on_post_compile({"main_sql": sql}, {})
        assert res == {"main_sql": sql}

    def test_post_compile_system_catalogs(self):
        """Middleware blocks queries touching system catalogs."""
        cfg = SecurityConfig(
            validation=ValidationSecurityConfig(allow_system_catalogs=False),
        )
        mw = SecurityMiddleware(config=cfg)
        for sql in [
            "SELECT * FROM pg_catalog.pg_tables",
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM sqlite_master",
        ]:
            with pytest.raises(
                SecurityError, match="system catalog tables is forbidden"
            ):
                mw.on_post_compile({"main_sql": sql}, {})

    def test_post_execute_dynamic_masking_and_row_ceiling(self):
        """Middleware applies row limit and column masking on post_execute."""
        cfg = SecurityConfig(
            execution=ExecutionSecurityConfig(max_rows_limit=2),
            privacy=PrivacySecurityConfig(
                sensitive_column_patterns=[r"(?i)email|ssn"],
                masking_strategy="hash",
            ),
        )
        mw = SecurityMiddleware(config=cfg)
        result = {
            "rows": [
                {"id": 1, "email": "a@example.com", "name": "Alice"},
                {"id": 2, "email": "b@example.com", "name": "Bob"},
                {"id": 3, "email": "c@example.com", "name": "Charlie"},
            ]
        }
        res = mw.on_post_execute(result, {})
        assert len(res["rows"]) == 2
        assert res["truncated"] is True
        # Email should be hashed
        assert res["rows"][0]["email"] == hashlib.sha256(b"a@example.com").hexdigest()
        assert res["rows"][0]["name"] == "Alice"


# ===========================================================================
# 6. Telemetry & Concurrent Audit Logging Adversarial Tests
# ===========================================================================


class TestTelemetryAdversarial:
    """Stress-tests TelemetryCollector under concurrency and edge cases."""

    def test_concurrent_audit_logging(self):
        """Ensure thread safety when logging audit events concurrently."""
        import concurrent.futures

        collector = TelemetryCollector(max_size=500)

        def log_events(thread_idx: int):
            for i in range(50):
                collector.record_audit_event(
                    event_type="security_violation",
                    action="validate",
                    resource=f"table_{thread_idx}_{i}",
                    tenant_id=f"tenant_{thread_idx}",
                    details={"password": "should_be_scrubbed"},
                    error_message=f"token=secret_{i} leaked",
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(log_events, idx) for idx in range(5)]
            for f in futures:
                f.result()

        events = collector.get_recent_audit_events(limit=500)
        assert len(events) == 250
        for ev in events:
            assert ev["details"]["password"] == "***"
            assert "***" in ev["error_message"]
