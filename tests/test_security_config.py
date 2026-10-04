"""
Tests for Security Configuration & Profiles Module.
===================================================
Verifies strongly typed dataclass hierarchies, validation post-inits,
pre-built profile presets (development, production, strict), environment
variable parsing and overrides, thread-safe global configuration, and edge cases.
"""

from __future__ import annotations

import concurrent.futures
import os

import pytest

from query_builder.config import (
    DEFAULT_SENSITIVE_COLUMN_PATTERNS,
    DEFAULT_SENSITIVE_KEY_PATTERNS,
    ExecutionSecurityConfig,
    LoggingSecurityConfig,
    NetworkSecurityConfig,
    PrivacySecurityConfig,
    SecurityConfig,
    SecurityProfile,
    ValidationSecurityConfig,
    _parse_bool,
    _parse_float,
    _parse_int,
    _parse_list,
    configure_security,
    get_security_config,
    load_security_config_from_env,
    reset_security_config,
)


@pytest.fixture(autouse=True)
def clean_security_config():
    """Ensure global security state and QB_* env vars are clean before and after each test."""
    reset_security_config()
    saved_env = {k: v for k, v in os.environ.items() if k.startswith("QB_")}
    for k in saved_env:
        os.environ.pop(k, None)
    yield
    reset_security_config()
    for k in list(os.environ.keys()):
        if k.startswith("QB_"):
            os.environ.pop(k, None)
    os.environ.update(saved_env)


# ---------------------------------------------------------------------------
# 1. NetworkSecurityConfig Tests
# ---------------------------------------------------------------------------


def test_network_security_config_defaults():
    cfg = NetworkSecurityConfig()
    assert cfg.allow_private_networks is False
    assert cfg.allowed_hostnames == []
    assert cfg.blocked_hostnames == []
    assert cfg.enforce_tls is True
    assert cfg.verify_ssl_certs is True
    assert cfg.ca_bundle_path is None
    assert cfg.socket_timeout_seconds == 10.0


def test_network_security_config_custom_values():
    cfg = NetworkSecurityConfig(
        allow_private_networks=True,
        allowed_hostnames=["db.internal"],
        blocked_hostnames=["bad.host"],
        enforce_tls=False,
        verify_ssl_certs=False,
        ca_bundle_path="/etc/ssl/certs/ca.pem",
        socket_timeout_seconds=25.5,
    )
    assert cfg.allow_private_networks is True
    assert cfg.allowed_hostnames == ["db.internal"]
    assert cfg.blocked_hostnames == ["bad.host"]
    assert cfg.enforce_tls is False
    assert cfg.verify_ssl_certs is False
    assert cfg.ca_bundle_path == "/etc/ssl/certs/ca.pem"
    assert cfg.socket_timeout_seconds == 25.5


def test_network_security_config_non_list_hostnames():
    cfg = NetworkSecurityConfig(
        allowed_hostnames=("h1", "h2"),  # type: ignore[arg-type]
        blocked_hostnames={"b1"},  # type: ignore[arg-type]
    )
    assert isinstance(cfg.allowed_hostnames, list)
    assert cfg.allowed_hostnames == ["h1", "h2"]
    assert isinstance(cfg.blocked_hostnames, list)
    assert cfg.blocked_hostnames == ["b1"]


def test_network_security_config_ca_bundle_whitespace():
    cfg = NetworkSecurityConfig(ca_bundle_path="   ")
    assert cfg.ca_bundle_path is None


def test_network_security_config_invalid_socket_timeout():
    with pytest.raises(ValueError, match="socket_timeout_seconds must be positive"):
        NetworkSecurityConfig(socket_timeout_seconds=0.0)

    with pytest.raises(ValueError, match="socket_timeout_seconds must be positive"):
        NetworkSecurityConfig(socket_timeout_seconds=-5.0)


# ---------------------------------------------------------------------------
# 2. ExecutionSecurityConfig Tests
# ---------------------------------------------------------------------------


def test_execution_security_config_defaults():
    cfg = ExecutionSecurityConfig()
    assert cfg.enforce_read_only_session is True
    assert cfg.statement_timeout_ms == 5000
    assert cfg.max_rows_limit == 1000
    assert cfg.max_join_depth == 5
    assert cfg.max_complexity_score == 100
    assert cfg.prevent_cartesian_products is True


def test_execution_security_config_custom_values():
    cfg = ExecutionSecurityConfig(
        enforce_read_only_session=False,
        statement_timeout_ms=10000,
        max_rows_limit=2500,
        max_join_depth=8,
        max_complexity_score=250,
        prevent_cartesian_products=False,
    )
    assert cfg.enforce_read_only_session is False
    assert cfg.statement_timeout_ms == 10000
    assert cfg.max_rows_limit == 2500
    assert cfg.max_join_depth == 8
    assert cfg.max_complexity_score == 250
    assert cfg.prevent_cartesian_products is False


def test_execution_security_config_invalid_statement_timeout():
    with pytest.raises(ValueError, match="statement_timeout_ms must be non-negative"):
        ExecutionSecurityConfig(statement_timeout_ms=-1)


def test_execution_security_config_invalid_max_rows_limit():
    with pytest.raises(ValueError, match="max_rows_limit must be greater than 0"):
        ExecutionSecurityConfig(max_rows_limit=0)

    with pytest.raises(ValueError, match="max_rows_limit must be greater than 0"):
        ExecutionSecurityConfig(max_rows_limit=-100)


def test_execution_security_config_invalid_max_join_depth():
    with pytest.raises(ValueError, match="max_join_depth must be non-negative"):
        ExecutionSecurityConfig(max_join_depth=-1)


def test_execution_security_config_invalid_max_complexity_score():
    with pytest.raises(ValueError, match="max_complexity_score must be greater than 0"):
        ExecutionSecurityConfig(max_complexity_score=0)

    with pytest.raises(ValueError, match="max_complexity_score must be greater than 0"):
        ExecutionSecurityConfig(max_complexity_score=-10)


# ---------------------------------------------------------------------------
# 3. ValidationSecurityConfig Tests
# ---------------------------------------------------------------------------


def test_validation_security_config_defaults():
    cfg = ValidationSecurityConfig()
    assert cfg.validate_ast is True
    assert cfg.allowed_statements == ["SELECT"]
    assert cfg.allow_system_catalogs is False
    assert cfg.filter_sql_comments is True
    assert cfg.allow_cte is True
    assert cfg.allow_recursive_cte is False


def test_validation_security_config_custom_and_normalization():
    cfg = ValidationSecurityConfig(
        validate_ast=False,
        allowed_statements=["select", " explain ", ""],
        allow_system_catalogs=True,
        filter_sql_comments=False,
        allow_cte=False,
        allow_recursive_cte=True,
    )
    assert cfg.validate_ast is False
    assert cfg.allowed_statements == ["SELECT", "EXPLAIN"]
    assert cfg.allow_system_catalogs is True
    assert cfg.filter_sql_comments is False
    assert cfg.allow_cte is False
    assert cfg.allow_recursive_cte is True


def test_validation_security_config_non_list_allowed_statements():
    cfg = ValidationSecurityConfig(
        allowed_statements=("select", "show"),  # type: ignore[arg-type]
    )
    assert isinstance(cfg.allowed_statements, list)
    assert cfg.allowed_statements == ["SELECT", "SHOW"]


def test_validation_security_config_empty_allowed_statements():
    with pytest.raises(ValueError, match="allowed_statements cannot be empty"):
        ValidationSecurityConfig(allowed_statements=[])

    with pytest.raises(ValueError, match="allowed_statements cannot be empty"):
        ValidationSecurityConfig(allowed_statements=["   ", ""])


# ---------------------------------------------------------------------------
# 4. PrivacySecurityConfig Tests
# ---------------------------------------------------------------------------


def test_privacy_security_config_defaults():
    cfg = PrivacySecurityConfig()
    assert cfg.enforce_tenant_isolation is True
    assert cfg.tenant_column == "tenant_id"
    assert cfg.masking_strategy == "redact"
    assert cfg.sensitive_column_patterns == DEFAULT_SENSITIVE_COLUMN_PATTERNS


def test_privacy_security_config_custom_values():
    cfg = PrivacySecurityConfig(
        enforce_tenant_isolation=False,
        tenant_column="org_id",
        sensitive_column_patterns=[r"ssn_\d+"],
        masking_strategy="HASH",
    )
    assert cfg.enforce_tenant_isolation is False
    assert cfg.tenant_column == "org_id"
    assert cfg.sensitive_column_patterns == [r"ssn_\d+"]
    assert cfg.masking_strategy == "hash"


def test_privacy_security_config_non_list_patterns():
    cfg = PrivacySecurityConfig(
        sensitive_column_patterns=(r"pwd", r"token"),  # type: ignore[arg-type]
    )
    assert isinstance(cfg.sensitive_column_patterns, list)
    assert cfg.sensitive_column_patterns == [r"pwd", r"token"]


def test_privacy_security_config_empty_tenant_column():
    with pytest.raises(ValueError, match="tenant_column cannot be empty"):
        PrivacySecurityConfig(tenant_column="")

    with pytest.raises(ValueError, match="tenant_column cannot be empty"):
        PrivacySecurityConfig(tenant_column="   ")


def test_privacy_security_config_invalid_masking_strategy():
    with pytest.raises(ValueError, match="Invalid masking_strategy: 'drop'"):
        PrivacySecurityConfig(masking_strategy="drop")


def test_privacy_security_config_invalid_regex_pattern():
    with pytest.raises(ValueError, match="Invalid regex in sensitive_column_patterns"):
        PrivacySecurityConfig(sensitive_column_patterns=["[unclosed_bracket"])


# ---------------------------------------------------------------------------
# 5. LoggingSecurityConfig Tests
# ---------------------------------------------------------------------------


def test_logging_security_config_defaults():
    cfg = LoggingSecurityConfig()
    assert cfg.mask_credentials is True
    assert cfg.redact_parameters is False
    assert cfg.emit_audit_events is True
    assert cfg.sensitive_key_patterns == DEFAULT_SENSITIVE_KEY_PATTERNS


def test_logging_security_config_custom_values():
    cfg = LoggingSecurityConfig(
        mask_credentials=False,
        redact_parameters=True,
        emit_audit_events=False,
        sensitive_key_patterns=[r"custom_secret"],
    )
    assert cfg.mask_credentials is False
    assert cfg.redact_parameters is True
    assert cfg.emit_audit_events is False
    assert cfg.sensitive_key_patterns == [r"custom_secret"]


def test_logging_security_config_non_list_patterns():
    cfg = LoggingSecurityConfig(
        sensitive_key_patterns=(r"k1", r"k2"),  # type: ignore[arg-type]
    )
    assert isinstance(cfg.sensitive_key_patterns, list)
    assert cfg.sensitive_key_patterns == [r"k1", r"k2"]


def test_logging_security_config_invalid_regex_pattern():
    with pytest.raises(ValueError, match="Invalid regex in sensitive_key_patterns"):
        LoggingSecurityConfig(sensitive_key_patterns=["(?i)[unclosed"])


# ---------------------------------------------------------------------------
# 6. SecurityConfig Root Container Tests
# ---------------------------------------------------------------------------


def test_security_config_defaults():
    cfg = SecurityConfig()
    assert cfg.profile == "production"
    assert isinstance(cfg.network, NetworkSecurityConfig)
    assert isinstance(cfg.execution, ExecutionSecurityConfig)
    assert isinstance(cfg.validation, ValidationSecurityConfig)
    assert isinstance(cfg.privacy, PrivacySecurityConfig)
    assert isinstance(cfg.logging, LoggingSecurityConfig)


def test_security_config_to_dict():
    cfg = SecurityConfig()
    d = cfg.to_dict()
    assert isinstance(d, dict)
    assert d["profile"] == "production"
    assert "network" in d
    assert "execution" in d
    assert "validation" in d
    assert "privacy" in d
    assert "logging" in d
    assert d["network"]["allow_private_networks"] is False
    assert d["execution"]["max_rows_limit"] == 1000


def test_security_config_copy():
    cfg = SecurityConfig(profile="custom")
    copied = cfg.copy()
    assert copied is not cfg
    assert copied.profile == "custom"
    copied.network.allow_private_networks = True
    assert cfg.network.allow_private_networks is False


# ---------------------------------------------------------------------------
# 7. SecurityProfile Factory Tests
# ---------------------------------------------------------------------------


def test_security_profile_development():
    dev = SecurityProfile.development()
    assert dev.profile == "development"
    # Network
    assert dev.network.allow_private_networks is True
    assert dev.network.enforce_tls is False
    assert dev.network.verify_ssl_certs is False
    assert dev.network.socket_timeout_seconds == 30.0
    # Execution
    assert dev.execution.enforce_read_only_session is False
    assert dev.execution.statement_timeout_ms == 30000
    assert dev.execution.max_rows_limit == 5000
    assert dev.execution.max_join_depth == 10
    assert dev.execution.max_complexity_score == 500
    assert dev.execution.prevent_cartesian_products is False
    # Validation
    assert dev.validation.allow_system_catalogs is True
    assert "EXPLAIN" in dev.validation.allowed_statements
    assert dev.validation.filter_sql_comments is False
    assert dev.validation.allow_recursive_cte is True
    # Privacy & Logging
    assert dev.privacy.enforce_tenant_isolation is False
    assert dev.logging.emit_audit_events is False
    assert dev.logging.mask_credentials is True


def test_security_profile_production():
    prod = SecurityProfile.production()
    assert prod.profile == "production"
    # Network
    assert prod.network.allow_private_networks is False
    assert prod.network.enforce_tls is True
    assert prod.network.verify_ssl_certs is True
    assert prod.network.socket_timeout_seconds == 10.0
    # Execution
    assert prod.execution.enforce_read_only_session is True
    assert prod.execution.statement_timeout_ms == 5000
    assert prod.execution.max_rows_limit == 1000
    assert prod.execution.max_join_depth == 5
    assert prod.execution.max_complexity_score == 100
    assert prod.execution.prevent_cartesian_products is True
    # Validation
    assert prod.validation.allow_system_catalogs is False
    assert prod.validation.allowed_statements == ["SELECT"]
    assert prod.validation.filter_sql_comments is True
    assert prod.validation.allow_recursive_cte is False
    # Privacy & Logging
    assert prod.privacy.enforce_tenant_isolation is True
    assert prod.logging.emit_audit_events is True
    assert prod.logging.mask_credentials is True


def test_security_profile_strict():
    strict = SecurityProfile.strict()
    assert strict.profile == "strict"
    # Network
    assert strict.network.allow_private_networks is False
    assert strict.network.socket_timeout_seconds == 5.0
    # Execution
    assert strict.execution.enforce_read_only_session is True
    assert strict.execution.statement_timeout_ms == 2000
    assert strict.execution.max_rows_limit == 250
    assert strict.execution.max_join_depth == 3
    assert strict.execution.max_complexity_score == 50
    assert strict.execution.prevent_cartesian_products is True
    # Validation
    assert strict.validation.allow_system_catalogs is False
    assert strict.validation.allowed_statements == ["SELECT"]
    # Privacy & Logging
    assert strict.privacy.enforce_tenant_isolation is True
    assert strict.privacy.masking_strategy == "hash"
    assert strict.logging.redact_parameters is True
    assert strict.logging.emit_audit_events is True


def test_security_profile_from_name_valid():
    assert SecurityProfile.from_name("development").profile == "development"
    assert SecurityProfile.from_name("dev").profile == "development"
    assert SecurityProfile.from_name("DEVELOPMENT").profile == "development"
    assert SecurityProfile.from_name("production").profile == "production"
    assert SecurityProfile.from_name("prod").profile == "production"
    assert SecurityProfile.from_name("PRODUCTION").profile == "production"
    assert SecurityProfile.from_name("strict").profile == "strict"
    assert SecurityProfile.from_name("STRICT").profile == "strict"


def test_security_profile_from_name_invalid():
    with pytest.raises(ValueError, match="Unknown security profile: 'nonexistent'"):
        SecurityProfile.from_name("nonexistent")


# ---------------------------------------------------------------------------
# 8. Helper Functions Parsing Tests
# ---------------------------------------------------------------------------


def test_parse_bool_variants():
    for val in ("true", "True", "1", "yes", "YES", "t", "T", "on", "ON"):
        assert _parse_bool(val, "TEST_VAR") is True
    for val in ("false", "False", "0", "no", "NO", "f", "F", "off", "OFF"):
        assert _parse_bool(val, "TEST_VAR") is False

    with pytest.raises(
        ValueError, match="Invalid boolean value for environment variable TEST_VAR"
    ):
        _parse_bool("invalid", "TEST_VAR")


def test_parse_int_variants():
    assert _parse_int("123", "VAR") == 123
    assert _parse_int(" -5 ", "VAR") == -5
    with pytest.raises(
        ValueError, match="Invalid integer value for environment variable VAR"
    ):
        _parse_int("abc", "VAR")


def test_parse_float_variants():
    assert _parse_float("12.34", "VAR") == 12.34
    assert _parse_float(" 5 ", "VAR") == 5.0
    with pytest.raises(
        ValueError, match="Invalid float value for environment variable VAR"
    ):
        _parse_float("abc", "VAR")


def test_parse_list_variants():
    assert _parse_list("a, b, c") == ["a", "b", "c"]
    assert _parse_list("  one  , , two , ") == ["one", "two"]
    assert _parse_list("") == []


# ---------------------------------------------------------------------------
# 9. load_security_config_from_env Tests
# ---------------------------------------------------------------------------


def test_load_from_env_default_os_environ():
    cfg = load_security_config_from_env()
    assert cfg.profile == "production"
    assert cfg.network.allow_private_networks is False


def test_load_from_env_empty_source():
    cfg = load_security_config_from_env(env={})
    assert cfg.profile == "production"


def test_load_from_env_profile_selection():
    cfg_dev = load_security_config_from_env(env={"QB_SECURITY_PROFILE": "development"})
    assert cfg_dev.profile == "development"

    cfg_strict = load_security_config_from_env(env={"QB_SECURITY_PROFILE": "strict"})
    assert cfg_strict.profile == "strict"


def test_load_from_env_network_overrides():
    env = {
        "QB_ALLOW_PRIVATE_NETWORKS": "true",
        "QB_ENFORCE_TLS": "false",
        "QB_VERIFY_SSL_CERTS": "false",
        "QB_CA_BUNDLE_PATH": "/custom/ca.pem",
        "QB_SOCKET_TIMEOUT_SECONDS": "22.5",
        "QB_ALLOWED_HOSTNAMES": "host1.internal, host2.internal",
        "QB_BLOCKED_HOSTNAMES": "bad.internal",
    }
    cfg = load_security_config_from_env(env=env)
    assert cfg.network.allow_private_networks is True
    assert cfg.network.enforce_tls is False
    assert cfg.network.verify_ssl_certs is False
    assert cfg.network.ca_bundle_path == "/custom/ca.pem"
    assert cfg.network.socket_timeout_seconds == 22.5
    assert cfg.network.allowed_hostnames == ["host1.internal", "host2.internal"]
    assert cfg.network.blocked_hostnames == ["bad.internal"]


def test_load_from_env_network_ca_bundle_empty():
    env = {"QB_CA_BUNDLE_PATH": "   "}
    cfg = load_security_config_from_env(env=env)
    assert cfg.network.ca_bundle_path is None


def test_load_from_env_network_invalid_timeout():
    with pytest.raises(ValueError, match="QB_SOCKET_TIMEOUT_SECONDS must be positive"):
        load_security_config_from_env(env={"QB_SOCKET_TIMEOUT_SECONDS": "0"})


def test_load_from_env_execution_overrides():
    env = {
        "QB_ENFORCE_READ_ONLY": "false",
        "QB_STATEMENT_TIMEOUT_MS": "15000",
        "QB_MAX_ROWS_LIMIT": "3000",
        "QB_MAX_JOIN_DEPTH": "7",
        "QB_MAX_COMPLEXITY_SCORE": "300",
        "QB_PREVENT_CARTESIAN_PRODUCTS": "false",
    }
    cfg = load_security_config_from_env(env=env)
    assert cfg.execution.enforce_read_only_session is False
    assert cfg.execution.statement_timeout_ms == 15000
    assert cfg.execution.max_rows_limit == 3000
    assert cfg.execution.max_join_depth == 7
    assert cfg.execution.max_complexity_score == 300
    assert cfg.execution.prevent_cartesian_products is False


def test_load_from_env_execution_invalid_timeout():
    with pytest.raises(
        ValueError, match="QB_STATEMENT_TIMEOUT_MS must be non-negative"
    ):
        load_security_config_from_env(env={"QB_STATEMENT_TIMEOUT_MS": "-1"})


def test_load_from_env_execution_invalid_max_rows():
    with pytest.raises(ValueError, match="QB_MAX_ROWS_LIMIT must be greater than 0"):
        load_security_config_from_env(env={"QB_MAX_ROWS_LIMIT": "0"})


def test_load_from_env_execution_invalid_max_join_depth():
    with pytest.raises(ValueError, match="QB_MAX_JOIN_DEPTH must be non-negative"):
        load_security_config_from_env(env={"QB_MAX_JOIN_DEPTH": "-1"})


def test_load_from_env_execution_invalid_complexity():
    with pytest.raises(
        ValueError, match="QB_MAX_COMPLEXITY_SCORE must be greater than 0"
    ):
        load_security_config_from_env(env={"QB_MAX_COMPLEXITY_SCORE": "0"})


def test_load_from_env_validation_overrides():
    env = {
        "QB_VALIDATE_AST": "false",
        "QB_ALLOWED_STATEMENTS": "SELECT, explain",
        "QB_ALLOW_SYSTEM_CATALOGS": "true",
        "QB_FILTER_SQL_COMMENTS": "false",
        "QB_ALLOW_CTE": "false",
        "QB_ALLOW_RECURSIVE_CTE": "true",
    }
    cfg = load_security_config_from_env(env=env)
    assert cfg.validation.validate_ast is False
    assert cfg.validation.allowed_statements == ["SELECT", "EXPLAIN"]
    assert cfg.validation.allow_system_catalogs is True
    assert cfg.validation.filter_sql_comments is False
    assert cfg.validation.allow_cte is False
    assert cfg.validation.allow_recursive_cte is True


def test_load_from_env_validation_invalid_allowed_statements():
    with pytest.raises(ValueError, match="QB_ALLOWED_STATEMENTS cannot be empty"):
        load_security_config_from_env(env={"QB_ALLOWED_STATEMENTS": " ,  , "})


def test_load_from_env_privacy_overrides():
    env = {
        "QB_ENFORCE_TENANT_ISOLATION": "false",
        "QB_TENANT_COLUMN": "customer_id",
        "QB_MASKING_STRATEGY": "partial",
        "QB_SENSITIVE_COLUMN_PATTERNS": "ssn_code, credit_num",
    }
    cfg = load_security_config_from_env(env=env)
    assert cfg.privacy.enforce_tenant_isolation is False
    assert cfg.privacy.tenant_column == "customer_id"
    assert cfg.privacy.masking_strategy == "partial"
    assert cfg.privacy.sensitive_column_patterns == ["ssn_code", "credit_num"]


def test_load_from_env_privacy_empty_tenant_column():
    with pytest.raises(ValueError, match="QB_TENANT_COLUMN cannot be empty"):
        load_security_config_from_env(env={"QB_TENANT_COLUMN": "  "})


def test_load_from_env_privacy_invalid_masking_strategy():
    with pytest.raises(ValueError, match="Invalid QB_MASKING_STRATEGY: 'invalid'"):
        load_security_config_from_env(env={"QB_MASKING_STRATEGY": "invalid"})


def test_load_from_env_privacy_invalid_regex_pattern():
    with pytest.raises(
        ValueError, match="Invalid regex in QB_SENSITIVE_COLUMN_PATTERNS"
    ):
        load_security_config_from_env(env={"QB_SENSITIVE_COLUMN_PATTERNS": "[unclosed"})


def test_load_from_env_logging_overrides():
    env = {
        "QB_MASK_CREDENTIALS": "false",
        "QB_REDACT_PARAMETERS": "true",
        "QB_EMIT_AUDIT_EVENTS": "false",
        "QB_SENSITIVE_KEY_PATTERNS": "api_token, secret_jwt",
    }
    cfg = load_security_config_from_env(env=env)
    assert cfg.logging.mask_credentials is False
    assert cfg.logging.redact_parameters is True
    assert cfg.logging.emit_audit_events is False
    assert cfg.logging.sensitive_key_patterns == ["api_token", "secret_jwt"]


def test_load_from_env_logging_invalid_regex():
    with pytest.raises(ValueError, match="Invalid regex in QB_SENSITIVE_KEY_PATTERNS"):
        load_security_config_from_env(env={"QB_SENSITIVE_KEY_PATTERNS": "[unclosed"})


# ---------------------------------------------------------------------------
# 10. Global Framework Configuration & Thread Safety Tests
# ---------------------------------------------------------------------------


def test_global_config_get_and_lazy_init():
    cfg1 = get_security_config()
    assert cfg1.profile == "production"
    cfg2 = get_security_config()
    assert cfg1 is cfg2


def test_global_config_reset():
    cfg1 = get_security_config()
    reset_security_config()
    cfg2 = get_security_config()
    assert cfg1 is not cfg2


def test_configure_security_with_explicit_instance():
    strict = SecurityProfile.strict()
    updated = configure_security(config=strict)
    assert updated.profile == "strict"
    assert get_security_config().profile == "strict"


def test_configure_security_with_profile_override():
    updated = configure_security(profile="development")
    assert updated.profile == "development"
    assert get_security_config().profile == "development"


def test_configure_security_invalid_profile_type():
    with pytest.raises(ValueError, match="profile override must be a string"):
        configure_security(profile=123)  # type: ignore[arg-type]


def test_configure_security_subconfig_replacements():
    net = NetworkSecurityConfig(allow_private_networks=True)
    exe = ExecutionSecurityConfig(max_rows_limit=500)
    val = ValidationSecurityConfig(allow_system_catalogs=True)
    priv = PrivacySecurityConfig(tenant_column="acc_id")
    log = LoggingSecurityConfig(redact_parameters=True)

    cfg = configure_security(
        network=net,
        execution=exe,
        validation=val,
        privacy=priv,
        logging=log,
    )
    assert cfg.network.allow_private_networks is True
    assert cfg.execution.max_rows_limit == 500
    assert cfg.validation.allow_system_catalogs is True
    assert cfg.privacy.tenant_column == "acc_id"
    assert cfg.logging.redact_parameters is True


def test_configure_security_subconfig_invalid_types():
    with pytest.raises(
        ValueError, match="network override must be a NetworkSecurityConfig"
    ):
        configure_security(network="invalid")  # type: ignore[arg-type]

    with pytest.raises(
        ValueError, match="execution override must be a ExecutionSecurityConfig"
    ):
        configure_security(execution="invalid")  # type: ignore[arg-type]

    with pytest.raises(
        ValueError, match="validation override must be a ValidationSecurityConfig"
    ):
        configure_security(validation="invalid")  # type: ignore[arg-type]

    with pytest.raises(
        ValueError, match="privacy override must be a PrivacySecurityConfig"
    ):
        configure_security(privacy="invalid")  # type: ignore[arg-type]

    with pytest.raises(
        ValueError, match="logging override must be a LoggingSecurityConfig"
    ):
        configure_security(logging="invalid")  # type: ignore[arg-type]


def test_configure_security_granular_field_overrides():
    cfg = configure_security(
        allow_private_networks=True,
        statement_timeout_ms=7500,
        allow_system_catalogs=True,
        tenant_column="org_id",
        redact_parameters=True,
    )
    assert cfg.network.allow_private_networks is True
    assert cfg.execution.statement_timeout_ms == 7500
    assert cfg.validation.allow_system_catalogs is True
    assert cfg.privacy.tenant_column == "org_id"
    assert cfg.logging.redact_parameters is True


def test_configure_security_granular_validation_failure():
    with pytest.raises(ValueError, match="statement_timeout_ms must be non-negative"):
        configure_security(statement_timeout_ms=-10)


def test_configure_security_unknown_override():
    with pytest.raises(
        ValueError, match="Unknown security configuration override: 'non_existent_key'"
    ):
        configure_security(non_existent_key=True)


def test_configure_security_from_none():
    reset_security_config()
    cfg = configure_security(statement_timeout_ms=9000)
    assert cfg.execution.statement_timeout_ms == 9000
    assert get_security_config().execution.statement_timeout_ms == 9000


def test_configure_security_thread_safety():
    reset_security_config()

    def worker(worker_id: int):
        for i in range(15):
            if i % 3 == 0:
                configure_security(statement_timeout_ms=1000 + worker_id)
            elif i % 3 == 1:
                cfg = get_security_config()
                assert cfg is not None
            else:
                cfg = get_security_config()
                assert cfg.execution.statement_timeout_ms >= 1000

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker, i) for i in range(6)]
        for f in futures:
            f.result()

    final_cfg = get_security_config()
    assert final_cfg is not None
