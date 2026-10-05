"""
Security Configuration & Profiles Module.
=========================================
Provides strongly typed, hierarchical configuration dataclasses, pre-built
environment profiles (development, production, strict), zero-code environment
variable overrides, and thread-safe global framework configuration state.
"""

from __future__ import annotations

import copy
import math
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------

VALID_MASKING_STRATEGIES: set[str] = {"hash", "partial", "redact"}

DEFAULT_SENSITIVE_COLUMN_PATTERNS: list[str] = [
    r"(?i)(password|passwd|pwd|secret|token|ssn|credit_card|api[_-]?key|auth)"
]

DEFAULT_SENSITIVE_KEY_PATTERNS: list[str] = [
    r"(?i)(password|passwd|pwd|secret|token|key|auth|api[_-]?key)"
]


# ---------------------------------------------------------------------------
# Hierarchical Security Configuration Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NetworkSecurityConfig:
    """Network egress, SSRF defense, and transport encryption security configuration."""

    allow_private_networks: bool = False
    allowed_hostnames: list[str] = field(default_factory=list)
    blocked_hostnames: list[str] = field(default_factory=list)
    enforce_tls: bool = True
    verify_ssl_certs: bool = True
    ca_bundle_path: str | None = None
    socket_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.socket_timeout_seconds)
            or self.socket_timeout_seconds <= 0
        ):
            raise ValueError(
                f"socket_timeout_seconds must be positive, got {self.socket_timeout_seconds}"
            )
        if not isinstance(self.allowed_hostnames, list):
            self.allowed_hostnames = list(self.allowed_hostnames)
        if not isinstance(self.blocked_hostnames, list):
            self.blocked_hostnames = list(self.blocked_hostnames)
        if self.ca_bundle_path is not None and not self.ca_bundle_path.strip():
            self.ca_bundle_path = None


@dataclass
class ExecutionSecurityConfig:
    """Execution sandboxing, query complexity governors, and pagination limits."""

    enforce_read_only_session: bool = True
    statement_timeout_ms: int = 5000
    max_rows_limit: int = 1000
    max_join_depth: int = 5
    max_complexity_score: int = 100
    prevent_cartesian_products: bool = True

    def __post_init__(self) -> None:
        if self.statement_timeout_ms < 0:
            raise ValueError(
                f"statement_timeout_ms must be non-negative, got {self.statement_timeout_ms}"
            )
        if self.max_rows_limit <= 0:
            raise ValueError(
                f"max_rows_limit must be greater than 0, got {self.max_rows_limit}"
            )
        if self.max_join_depth < 0:
            raise ValueError(
                f"max_join_depth must be non-negative, got {self.max_join_depth}"
            )
        if self.max_complexity_score <= 0:
            raise ValueError(
                f"max_complexity_score must be greater than 0, got {self.max_complexity_score}"
            )


@dataclass
class ValidationSecurityConfig:
    """AST safety validation, statement whitelisting, and syntax constraints."""

    validate_ast: bool = True
    allowed_statements: list[str] = field(default_factory=lambda: ["SELECT"])
    allow_system_catalogs: bool = False
    filter_sql_comments: bool = True
    allow_cte: bool = True
    allow_recursive_cte: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_statements, list):
            self.allowed_statements = list(self.allowed_statements)
        self.allowed_statements = [
            s.strip().upper() for s in self.allowed_statements if s.strip()
        ]
        if not self.allowed_statements:
            raise ValueError("allowed_statements cannot be empty")


@dataclass
class PrivacySecurityConfig:
    """Tenant isolation, sensitive column pattern matching, and column masking."""

    enforce_tenant_isolation: bool = True
    tenant_column: str = "tenant_id"
    sensitive_column_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_COLUMN_PATTERNS)
    )
    masking_strategy: str = "redact"

    def __post_init__(self) -> None:
        if not self.tenant_column or not self.tenant_column.strip():
            raise ValueError("tenant_column cannot be empty")
        self.tenant_column = self.tenant_column.strip()
        strategy = self.masking_strategy.strip().lower()
        if strategy not in VALID_MASKING_STRATEGIES:
            raise ValueError(
                f"Invalid masking_strategy: '{self.masking_strategy}'. "
                f"Must be one of {sorted(VALID_MASKING_STRATEGIES)}"
            )
        self.masking_strategy = strategy
        if not isinstance(self.sensitive_column_patterns, list):
            self.sensitive_column_patterns = list(self.sensitive_column_patterns)
        for pattern in self.sensitive_column_patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex in sensitive_column_patterns: '{pattern}': {e}"
                ) from e


@dataclass
class LoggingSecurityConfig:
    """Credential sanitization, parameter redaction, and audit telemetry emission."""

    mask_credentials: bool = True
    redact_parameters: bool = False
    emit_audit_events: bool = True
    sensitive_key_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_SENSITIVE_KEY_PATTERNS)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.sensitive_key_patterns, list):
            self.sensitive_key_patterns = list(self.sensitive_key_patterns)
        for pattern in self.sensitive_key_patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex in sensitive_key_patterns: '{pattern}': {e}"
                ) from e


@dataclass
class SecurityConfig:
    """Root configuration container composing all security sub-systems."""

    network: NetworkSecurityConfig = field(default_factory=NetworkSecurityConfig)
    execution: ExecutionSecurityConfig = field(default_factory=ExecutionSecurityConfig)
    validation: ValidationSecurityConfig = field(
        default_factory=ValidationSecurityConfig
    )
    privacy: PrivacySecurityConfig = field(default_factory=PrivacySecurityConfig)
    logging: LoggingSecurityConfig = field(default_factory=LoggingSecurityConfig)
    profile: str = "production"

    def to_dict(self) -> dict[str, Any]:
        """Convert security config into a nested dictionary."""
        return asdict(self)

    def copy(self) -> SecurityConfig:
        """Create an independent deep copy of the security config."""
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Pre-built Environment Profiles
# ---------------------------------------------------------------------------


class SecurityProfile:
    """Pre-built security profile factories for different runtime environments."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    STRICT = "strict"

    @classmethod
    def development(cls) -> SecurityConfig:
        """Relaxed profile for local Docker and workstation developer workflows."""
        return SecurityConfig(
            network=NetworkSecurityConfig(
                allow_private_networks=True,
                allowed_hostnames=[],
                blocked_hostnames=[],
                enforce_tls=False,
                verify_ssl_certs=False,
                ca_bundle_path=None,
                socket_timeout_seconds=30.0,
            ),
            execution=ExecutionSecurityConfig(
                enforce_read_only_session=False,
                statement_timeout_ms=30000,
                max_rows_limit=5000,
                max_join_depth=10,
                max_complexity_score=500,
                prevent_cartesian_products=False,
            ),
            validation=ValidationSecurityConfig(
                validate_ast=True,
                allowed_statements=["SELECT", "EXPLAIN", "SHOW", "DESCRIBE"],
                allow_system_catalogs=True,
                filter_sql_comments=False,
                allow_cte=True,
                allow_recursive_cte=True,
            ),
            privacy=PrivacySecurityConfig(
                enforce_tenant_isolation=False,
                tenant_column="tenant_id",
                masking_strategy="redact",
            ),
            logging=LoggingSecurityConfig(
                mask_credentials=True,
                redact_parameters=False,
                emit_audit_events=False,
            ),
            profile=cls.DEVELOPMENT,
        )

    @classmethod
    def production(cls) -> SecurityConfig:
        """Hardened zero-trust defaults for staging and production environments."""
        return SecurityConfig(
            network=NetworkSecurityConfig(
                allow_private_networks=False,
                allowed_hostnames=[],
                blocked_hostnames=[],
                enforce_tls=True,
                verify_ssl_certs=True,
                ca_bundle_path=None,
                socket_timeout_seconds=10.0,
            ),
            execution=ExecutionSecurityConfig(
                enforce_read_only_session=True,
                statement_timeout_ms=5000,
                max_rows_limit=1000,
                max_join_depth=5,
                max_complexity_score=100,
                prevent_cartesian_products=True,
            ),
            validation=ValidationSecurityConfig(
                validate_ast=True,
                allowed_statements=["SELECT"],
                allow_system_catalogs=False,
                filter_sql_comments=True,
                allow_cte=True,
                allow_recursive_cte=False,
            ),
            privacy=PrivacySecurityConfig(
                enforce_tenant_isolation=True,
                tenant_column="tenant_id",
                masking_strategy="redact",
            ),
            logging=LoggingSecurityConfig(
                mask_credentials=True,
                redact_parameters=False,
                emit_audit_events=True,
            ),
            profile=cls.PRODUCTION,
        )

    @classmethod
    def strict(cls) -> SecurityConfig:
        """Ultra-hardened profile for regulated financial and healthcare environments."""
        return SecurityConfig(
            network=NetworkSecurityConfig(
                allow_private_networks=False,
                allowed_hostnames=[],
                blocked_hostnames=[],
                enforce_tls=True,
                verify_ssl_certs=True,
                ca_bundle_path=None,
                socket_timeout_seconds=5.0,
            ),
            execution=ExecutionSecurityConfig(
                enforce_read_only_session=True,
                statement_timeout_ms=2000,
                max_rows_limit=250,
                max_join_depth=3,
                max_complexity_score=50,
                prevent_cartesian_products=True,
            ),
            validation=ValidationSecurityConfig(
                validate_ast=True,
                allowed_statements=["SELECT"],
                allow_system_catalogs=False,
                filter_sql_comments=True,
                allow_cte=True,
                allow_recursive_cte=False,
            ),
            privacy=PrivacySecurityConfig(
                enforce_tenant_isolation=True,
                tenant_column="tenant_id",
                masking_strategy="hash",
            ),
            logging=LoggingSecurityConfig(
                mask_credentials=True,
                redact_parameters=True,
                emit_audit_events=True,
            ),
            profile=cls.STRICT,
        )

    @classmethod
    def from_name(cls, name: str) -> SecurityConfig:
        """Instantiate a security config profile by name."""
        normalized = name.strip().lower()
        if normalized in (cls.DEVELOPMENT, "dev"):
            return cls.development()
        if normalized in (cls.PRODUCTION, "prod"):
            return cls.production()
        if normalized in (cls.STRICT,):
            return cls.strict()
        raise ValueError(
            f"Unknown security profile: '{name}'. "
            f"Supported profiles: '{cls.DEVELOPMENT}', '{cls.PRODUCTION}', '{cls.STRICT}'."
        )


# ---------------------------------------------------------------------------
# Environment Variable Parsing Helpers
# ---------------------------------------------------------------------------


def _parse_bool(val: str, var_name: str) -> bool:
    clean = val.strip().lower()
    if clean in ("true", "1", "yes", "t", "on"):
        return True
    if clean in ("false", "0", "no", "f", "off"):
        return False
    raise ValueError(
        f"Invalid boolean value for environment variable {var_name}: '{val}'. "
        "Expected one of 'true', 'false', '1', '0', 'yes', 'no'."
    )


def _parse_int(val: str, var_name: str) -> int:
    try:
        return int(val.strip())
    except ValueError as e:
        raise ValueError(
            f"Invalid integer value for environment variable {var_name}: '{val}'"
        ) from e


def _parse_float(val: str, var_name: str) -> float:
    try:
        return float(val.strip())
    except ValueError as e:
        raise ValueError(
            f"Invalid float value for environment variable {var_name}: '{val}'"
        ) from e


def _parse_list(val: str) -> list[str]:
    return [item.strip() for item in val.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Environment Variable Loader
# ---------------------------------------------------------------------------


def load_security_config_from_env(
    env: Mapping[str, str] | None = None,
) -> SecurityConfig:
    """
    Load a SecurityConfig instance from environment variables.

    If env is None, defaults to os.environ.
    Resolves base profile from QB_SECURITY_PROFILE (defaulting to 'production')
    and overrides any explicitly set QB_* environment variables.
    """
    source = os.environ if env is None else env

    profile_name = source.get("QB_SECURITY_PROFILE", "production")
    config = SecurityProfile.from_name(profile_name)

    # --- Network Overrides ---
    if "QB_ALLOW_PRIVATE_NETWORKS" in source:
        config.network.allow_private_networks = _parse_bool(
            source["QB_ALLOW_PRIVATE_NETWORKS"], "QB_ALLOW_PRIVATE_NETWORKS"
        )
    if "QB_ENFORCE_TLS" in source:
        config.network.enforce_tls = _parse_bool(
            source["QB_ENFORCE_TLS"], "QB_ENFORCE_TLS"
        )
    if "QB_VERIFY_SSL_CERTS" in source:
        config.network.verify_ssl_certs = _parse_bool(
            source["QB_VERIFY_SSL_CERTS"], "QB_VERIFY_SSL_CERTS"
        )
    if "QB_CA_BUNDLE_PATH" in source:
        ca_path = source["QB_CA_BUNDLE_PATH"].strip()
        config.network.ca_bundle_path = ca_path if ca_path else None
    if "QB_SOCKET_TIMEOUT_SECONDS" in source:
        config.network.socket_timeout_seconds = _parse_float(
            source["QB_SOCKET_TIMEOUT_SECONDS"], "QB_SOCKET_TIMEOUT_SECONDS"
        )
        if (
            not math.isfinite(config.network.socket_timeout_seconds)
            or config.network.socket_timeout_seconds <= 0
        ):
            raise ValueError(
                f"QB_SOCKET_TIMEOUT_SECONDS must be positive, got {config.network.socket_timeout_seconds}"
            )
    if "QB_ALLOWED_HOSTNAMES" in source:
        config.network.allowed_hostnames = _parse_list(source["QB_ALLOWED_HOSTNAMES"])
    if "QB_BLOCKED_HOSTNAMES" in source:
        config.network.blocked_hostnames = _parse_list(source["QB_BLOCKED_HOSTNAMES"])

    # --- Execution Overrides ---
    if "QB_ENFORCE_READ_ONLY" in source:
        config.execution.enforce_read_only_session = _parse_bool(
            source["QB_ENFORCE_READ_ONLY"], "QB_ENFORCE_READ_ONLY"
        )
    if "QB_STATEMENT_TIMEOUT_MS" in source:
        config.execution.statement_timeout_ms = _parse_int(
            source["QB_STATEMENT_TIMEOUT_MS"], "QB_STATEMENT_TIMEOUT_MS"
        )
        if config.execution.statement_timeout_ms < 0:
            raise ValueError(
                f"QB_STATEMENT_TIMEOUT_MS must be non-negative, got {config.execution.statement_timeout_ms}"
            )
    if "QB_MAX_ROWS_LIMIT" in source:
        config.execution.max_rows_limit = _parse_int(
            source["QB_MAX_ROWS_LIMIT"], "QB_MAX_ROWS_LIMIT"
        )
        if config.execution.max_rows_limit <= 0:
            raise ValueError(
                f"QB_MAX_ROWS_LIMIT must be greater than 0, got {config.execution.max_rows_limit}"
            )
    if "QB_MAX_JOIN_DEPTH" in source:
        config.execution.max_join_depth = _parse_int(
            source["QB_MAX_JOIN_DEPTH"], "QB_MAX_JOIN_DEPTH"
        )
        if config.execution.max_join_depth < 0:
            raise ValueError(
                f"QB_MAX_JOIN_DEPTH must be non-negative, got {config.execution.max_join_depth}"
            )
    if "QB_MAX_COMPLEXITY_SCORE" in source:
        config.execution.max_complexity_score = _parse_int(
            source["QB_MAX_COMPLEXITY_SCORE"], "QB_MAX_COMPLEXITY_SCORE"
        )
        if config.execution.max_complexity_score <= 0:
            raise ValueError(
                f"QB_MAX_COMPLEXITY_SCORE must be greater than 0, got {config.execution.max_complexity_score}"
            )
    if "QB_PREVENT_CARTESIAN_PRODUCTS" in source:
        config.execution.prevent_cartesian_products = _parse_bool(
            source["QB_PREVENT_CARTESIAN_PRODUCTS"], "QB_PREVENT_CARTESIAN_PRODUCTS"
        )

    # --- Validation Overrides ---
    if "QB_VALIDATE_AST" in source:
        config.validation.validate_ast = _parse_bool(
            source["QB_VALIDATE_AST"], "QB_VALIDATE_AST"
        )
    if "QB_ALLOWED_STATEMENTS" in source:
        stmts = [
            s.strip().upper()
            for s in _parse_list(source["QB_ALLOWED_STATEMENTS"])
            if s.strip()
        ]
        if not stmts:
            raise ValueError("QB_ALLOWED_STATEMENTS cannot be empty")
        config.validation.allowed_statements = stmts
    if "QB_ALLOW_SYSTEM_CATALOGS" in source:
        config.validation.allow_system_catalogs = _parse_bool(
            source["QB_ALLOW_SYSTEM_CATALOGS"], "QB_ALLOW_SYSTEM_CATALOGS"
        )
    if "QB_FILTER_SQL_COMMENTS" in source:
        config.validation.filter_sql_comments = _parse_bool(
            source["QB_FILTER_SQL_COMMENTS"], "QB_FILTER_SQL_COMMENTS"
        )
    if "QB_ALLOW_CTE" in source:
        config.validation.allow_cte = _parse_bool(
            source["QB_ALLOW_CTE"], "QB_ALLOW_CTE"
        )
    if "QB_ALLOW_RECURSIVE_CTE" in source:
        config.validation.allow_recursive_cte = _parse_bool(
            source["QB_ALLOW_RECURSIVE_CTE"], "QB_ALLOW_RECURSIVE_CTE"
        )

    # --- Privacy Overrides ---
    if "QB_ENFORCE_TENANT_ISOLATION" in source:
        config.privacy.enforce_tenant_isolation = _parse_bool(
            source["QB_ENFORCE_TENANT_ISOLATION"], "QB_ENFORCE_TENANT_ISOLATION"
        )
    if "QB_TENANT_COLUMN" in source:
        col = source["QB_TENANT_COLUMN"].strip()
        if not col:
            raise ValueError("QB_TENANT_COLUMN cannot be empty")
        config.privacy.tenant_column = col
    if "QB_MASKING_STRATEGY" in source:
        strat = source["QB_MASKING_STRATEGY"].strip().lower()
        if strat not in VALID_MASKING_STRATEGIES:
            raise ValueError(
                f"Invalid QB_MASKING_STRATEGY: '{strat}'. Must be one of {sorted(VALID_MASKING_STRATEGIES)}"
            )
        config.privacy.masking_strategy = strat
    if "QB_SENSITIVE_COLUMN_PATTERNS" in source:
        pats = _parse_list(source["QB_SENSITIVE_COLUMN_PATTERNS"])
        for p in pats:
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex in QB_SENSITIVE_COLUMN_PATTERNS: '{p}': {e}"
                ) from e
        config.privacy.sensitive_column_patterns = pats

    # --- Logging Overrides ---
    if "QB_MASK_CREDENTIALS" in source:
        config.logging.mask_credentials = _parse_bool(
            source["QB_MASK_CREDENTIALS"], "QB_MASK_CREDENTIALS"
        )
    if "QB_REDACT_PARAMETERS" in source:
        config.logging.redact_parameters = _parse_bool(
            source["QB_REDACT_PARAMETERS"], "QB_REDACT_PARAMETERS"
        )
    if "QB_EMIT_AUDIT_EVENTS" in source:
        config.logging.emit_audit_events = _parse_bool(
            source["QB_EMIT_AUDIT_EVENTS"], "QB_EMIT_AUDIT_EVENTS"
        )
    if "QB_SENSITIVE_KEY_PATTERNS" in source:
        pats = _parse_list(source["QB_SENSITIVE_KEY_PATTERNS"])
        for p in pats:
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex in QB_SENSITIVE_KEY_PATTERNS: '{p}': {e}"
                ) from e
        config.logging.sensitive_key_patterns = pats

    return config


# ---------------------------------------------------------------------------
# Global Framework Configuration State
# ---------------------------------------------------------------------------

_GLOBAL_CONFIG: SecurityConfig | None = None
_CONFIG_LOCK = threading.RLock()


def get_security_config() -> SecurityConfig:
    """
    Retrieve the active global SecurityConfig instance.

    Thread-safe. Lazily initializes from environment variables if not already set.
    """
    global _GLOBAL_CONFIG
    with _CONFIG_LOCK:
        if _GLOBAL_CONFIG is None:
            _GLOBAL_CONFIG = load_security_config_from_env()
        return _GLOBAL_CONFIG


def configure_security(
    config: SecurityConfig | None = None,
    **overrides: Any,
) -> SecurityConfig:
    """
    Configure the global framework security settings.

    Thread-safe. Accepts either a full SecurityConfig instance or keyword overrides
    targeting sub-configs or specific security properties.
    """
    global _GLOBAL_CONFIG
    with _CONFIG_LOCK:
        if config is not None:
            base = config.copy()
        elif _GLOBAL_CONFIG is not None:
            base = _GLOBAL_CONFIG.copy()
        else:
            base = load_security_config_from_env()

        for key, val in overrides.items():
            if key == "profile":
                if isinstance(val, str):
                    base = SecurityProfile.from_name(val)
                else:
                    raise ValueError(
                        f"profile override must be a string, got {type(val).__name__}"
                    )
            elif key == "network":
                if not isinstance(val, NetworkSecurityConfig):
                    raise ValueError(
                        f"network override must be a NetworkSecurityConfig, got {type(val).__name__}"
                    )
                base.network = copy.deepcopy(val)
            elif key == "execution":
                if not isinstance(val, ExecutionSecurityConfig):
                    raise ValueError(
                        f"execution override must be a ExecutionSecurityConfig, got {type(val).__name__}"
                    )
                base.execution = copy.deepcopy(val)
            elif key == "validation":
                if not isinstance(val, ValidationSecurityConfig):
                    raise ValueError(
                        f"validation override must be a ValidationSecurityConfig, got {type(val).__name__}"
                    )
                base.validation = copy.deepcopy(val)
            elif key == "privacy":
                if not isinstance(val, PrivacySecurityConfig):
                    raise ValueError(
                        f"privacy override must be a PrivacySecurityConfig, got {type(val).__name__}"
                    )
                base.privacy = copy.deepcopy(val)
            elif key == "logging":
                if not isinstance(val, LoggingSecurityConfig):
                    raise ValueError(
                        f"logging override must be a LoggingSecurityConfig, got {type(val).__name__}"
                    )
                base.logging = copy.deepcopy(val)
            elif hasattr(base.network, key):
                setattr(base.network, key, val)
                base.network.__post_init__()
            elif hasattr(base.execution, key):
                setattr(base.execution, key, val)
                base.execution.__post_init__()
            elif hasattr(base.validation, key):
                setattr(base.validation, key, val)
                base.validation.__post_init__()
            elif hasattr(base.privacy, key):
                setattr(base.privacy, key, val)
                base.privacy.__post_init__()
            elif hasattr(base.logging, key):
                setattr(base.logging, key, val)
                base.logging.__post_init__()
            else:
                raise ValueError(f"Unknown security configuration override: '{key}'")

        _GLOBAL_CONFIG = base
        return _GLOBAL_CONFIG


def reset_security_config() -> None:
    """
    Reset the global security configuration state to None.

    Thread-safe. The next get_security_config() call will re-initialize
    from environment variables or production defaults.
    """
    global _GLOBAL_CONFIG
    with _CONFIG_LOCK:
        _GLOBAL_CONFIG = None


# ---------------------------------------------------------------------------
# Unified Query Builder Configuration
# ---------------------------------------------------------------------------


@dataclass
class QueryBuilderConfig:
    """
    Unified configuration dataclass for the Query-Builder engine.

    Covers default SQL dialects, security profiles/configs, custom dialect overrides,
    custom database connectors, and custom filter operators.
    """

    default_dialect: str = "postgres"
    security: SecurityConfig = field(default_factory=get_security_config)
    dialects: dict[str, Any] = field(default_factory=dict)
    connectors: dict[str, Any] = field(default_factory=dict)
    custom_operators: dict[str, Any] = field(default_factory=dict)
    default_limit: int = 100

    def copy(self) -> QueryBuilderConfig:
        """Create a deep copy of the configuration."""
        return QueryBuilderConfig(
            default_dialect=self.default_dialect,
            security=self.security.copy(),
            dialects=dict(self.dialects),
            connectors=dict(self.connectors),
            custom_operators=dict(self.custom_operators),
            default_limit=self.default_limit,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the configuration to a dictionary."""
        return {
            "default_dialect": self.default_dialect,
            "security": self.security.to_dict(),
            "dialects": {k: str(v) for k, v in self.dialects.items()},
            "connectors": {k: str(v) for k, v in self.connectors.items()},
            "custom_operators": {k: str(v) for k, v in self.custom_operators.items()},
            "default_limit": self.default_limit,
        }


_GLOBAL_QB_CONFIG: QueryBuilderConfig | None = None


def get_query_builder_config() -> QueryBuilderConfig:
    """
    Retrieve the active global QueryBuilderConfig instance.

    Thread-safe. Lazily initializes with defaults if not already configured.
    """
    global _GLOBAL_QB_CONFIG
    with _CONFIG_LOCK:
        if _GLOBAL_QB_CONFIG is None:
            _GLOBAL_QB_CONFIG = QueryBuilderConfig()
        return _GLOBAL_QB_CONFIG


def configure_query_builder(
    config: QueryBuilderConfig | None = None,
    default_dialect: str | None = None,
    security: SecurityConfig | None = None,
    profile: str | None = None,
    dialects: dict[str, Any] | None = None,
    connectors: dict[str, Any] | None = None,
    custom_operators: dict[str, Any] | None = None,
    default_limit: int | None = None,
    **security_kwargs: Any,
) -> QueryBuilderConfig:
    """
    Configure global settings for the Query-Builder engine.

    Thread-safe. Supports setting default dialects, applying security profiles,
    registering custom dialects, connectors, and filter operators.
    """
    global _GLOBAL_QB_CONFIG
    with _CONFIG_LOCK:
        if config is not None:
            base = config.copy()
        elif _GLOBAL_QB_CONFIG is not None:
            base = _GLOBAL_QB_CONFIG.copy()
        else:
            base = QueryBuilderConfig()

        if default_dialect is not None:
            base.default_dialect = default_dialect.lower().strip()

        if profile is not None:
            if isinstance(profile, str):
                base.security = SecurityProfile.from_name(profile)
                configure_security(base.security)
            else:
                raise ValueError(
                    f"profile override must be a string, got {type(profile).__name__}"
                )

        if security is not None:
            base.security = security.copy()
            configure_security(base.security)

        if security_kwargs:
            base.security = configure_security(base.security, **security_kwargs)

        if default_limit is not None:
            if default_limit <= 0:
                raise ValueError(f"default_limit must be positive, got {default_limit}")
            base.default_limit = default_limit

        if dialects:
            from query_builder.dialects import register_dialect

            for d_name, d_val in dialects.items():
                register_dialect(d_name, d_val)
                base.dialects[d_name] = d_val

        if connectors:
            from query_builder.connectors.registry import register_connector

            for c_name, c_val in connectors.items():
                register_connector(c_name, c_val)
                base.connectors[c_name] = c_val

        if custom_operators:
            from query_builder.compiler import register_filter_operator

            for op_name, op_val in custom_operators.items():
                register_filter_operator(op_name, op_val)
                base.custom_operators[op_name] = op_val

        _GLOBAL_QB_CONFIG = base
        return _GLOBAL_QB_CONFIG


def reset_query_builder_config() -> None:
    """
    Reset the global query builder configuration state to None.

    Thread-safe. Unregisters any custom dialects, connectors, or operators
    that were registered via configure_query_builder.
    """
    global _GLOBAL_QB_CONFIG
    with _CONFIG_LOCK:
        if _GLOBAL_QB_CONFIG is not None:
            if _GLOBAL_QB_CONFIG.custom_operators:
                from query_builder.compiler import unregister_filter_operator

                for op_name in list(_GLOBAL_QB_CONFIG.custom_operators.keys()):
                    unregister_filter_operator(op_name)
            if _GLOBAL_QB_CONFIG.dialects:
                from query_builder.dialects import unregister_dialect

                for d_name in list(_GLOBAL_QB_CONFIG.dialects.keys()):
                    unregister_dialect(d_name)
            if _GLOBAL_QB_CONFIG.connectors:
                from query_builder.connectors.registry import unregister_connector

                for c_name in list(_GLOBAL_QB_CONFIG.connectors.keys()):
                    unregister_connector(c_name)
        _GLOBAL_QB_CONFIG = None


__all__ = [
    "DEFAULT_SENSITIVE_COLUMN_PATTERNS",
    "DEFAULT_SENSITIVE_KEY_PATTERNS",
    "VALID_MASKING_STRATEGIES",
    "ExecutionSecurityConfig",
    "LoggingSecurityConfig",
    "NetworkSecurityConfig",
    "PrivacySecurityConfig",
    "QueryBuilderConfig",
    "SecurityConfig",
    "SecurityProfile",
    "ValidationSecurityConfig",
    "configure_query_builder",
    "configure_security",
    "get_query_builder_config",
    "get_security_config",
    "load_security_config_from_env",
    "reset_query_builder_config",
    "reset_security_config",
]
