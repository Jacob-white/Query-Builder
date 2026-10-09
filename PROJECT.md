# Project: Query-Builder Security Framework Expansion

## Architecture
Query-Builder is expanding with a comprehensive, modular, and developer-configurable Security Framework providing layered configuration models, pre-built environment profiles, zero-trust defaults, and automated secret scrubbing across all database connectors.

1. **Security Configuration Layer (`query_builder/config.py`)**:
   - Hierarchical configuration dataclasses: `SecurityConfig`, `NetworkSecurityConfig`, `ExecutionSecurityConfig`, `ValidationSecurityConfig`, `PrivacySecurityConfig`, `LoggingSecurityConfig`.
   - Environment profiles: `SecurityProfile.development()`, `production()`, `strict()`.
   - Environment variable loader: `load_security_config_from_env()` parsing `QB_*` variables.
   - Global thread-safe configuration manager: `configure_security()`, `get_security_config()`, `reset_security_config()`.

2. **Security & Sandboxing Engine (`query_builder/security.py`, `policy.py`, `middleware.py`, `telemetry.py`)**:
   - Network SSRF validator: `validate_network_target()` enforcing private/cloud metadata blocking (`169.254.169.254`, `127.0.0.1`, RFC 1918, RFC 6598, IPv6 ULA), hostname whitelisting/blacklisting, TLS/SSL enforcement.
   - Secret scrubbing: `scrub_secrets()` sanitizing URIs, passwords, tokens, API keys across dicts, strings, `__repr__`, `__str__`, and exception messages.
   - Execution sandboxing: `calculate_ast_complexity()`, `check_cartesian_products()`, row pagination ceilings, statement timeouts, read-only session enforcement.
   - Privacy & data governance: `apply_column_masking()` (`redact`, `hash`, `partial`) and regex sensitive column patterns.
   - Lifecycle security interceptor: `SecurityMiddleware` in `middleware.py`.
   - Telemetry audit events: `AuditEvent` in `telemetry.py`, parameter redaction, scrubbed execution logs.

3. **Connector Integration Layer (`query_builder/connectors/base.py`, `async_base.py`)**:
   - `BaseConnector` and `AsyncBaseConnector` accepting optional `security: SecurityConfig | None = None`.
   - Automatic secret scrubbing in `repr(connector)`, `str(connector)`, and `ConnectionFailedError`.
   - Dynamic enforcement of execution boundaries, row limits, timeouts, and AST validation in `execute()`.
   - 100% backwards-compatible with all registered connectors (138 classes: 89 sync + 49 async; 306 registered names; see `docs/CONNECTORS.md`) and existing call signatures.

4. **Package Surface (`query_builder/__init__.py`)**:
   - Export all security configuration dataclasses, profile factories, and helper functions in `__all__`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Strongly Typed Configuration Dataclasses | `SecurityConfig` composing `NetworkSecurityConfig`, `ExecutionSecurityConfig`, `ValidationSecurityConfig`, `PrivacySecurityConfig`, `LoggingSecurityConfig` | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Environment Profile Factories | `SecurityProfile.development()`, `production()`, `strict()` providing pre-built profiles | M1 | ORIGINAL_REQUEST §R2 |
| 3 | Environment Variable Overrides | `load_security_config_from_env()` parsing `QB_SECURITY_PROFILE`, `QB_ALLOW_PRIVATE_NETWORKS`, etc. | M1 | ORIGINAL_REQUEST §R2 |
| 4 | Global Security Configuration Management | Thread-safe `configure_security()`, `get_security_config()`, `reset_security_config()` | M1 | ORIGINAL_REQUEST §R2 |
| 5 | Network SSRF & IP Target Validation | `validate_network_target()` blocking private & cloud metadata IPs, hostname filtering, TLS rules | M2 | ORIGINAL_REQUEST §R1 |
| 6 | Execution Sandboxing & Complexity Governance | AST complexity scoring, Cartesian product prevention, row ceilings, statement timeouts | M2 | ORIGINAL_REQUEST §R1 |
| 7 | Privacy Governance & Column Masking | `apply_column_masking()` (`redact`, `hash`, `partial`) and regex sensitive column patterns in `policy.py` | M2 | ORIGINAL_REQUEST §R1 |
| 8 | Secret Scrubbing & Audit Telemetry | `scrub_secrets()`, `AuditEvent` recording, parameter redaction, error message sanitization | M2 | ORIGINAL_REQUEST §R1 |
| 9 | Lifecycle Security Middleware | `SecurityMiddleware(LifecycleInterceptor)` connecting config to query execution lifecycle | M2 | ORIGINAL_REQUEST §R3 |
| 10 | Connector Security & Credential Scrubbing | Base and async connector integration, sanitized `__repr__`/`__str__`, sanitized `ConnectionFailedError` | M3 | ORIGINAL_REQUEST §R3 |
| 11 | Dynamic Execution Boundary Enforcement | Enforcement of row limits, timeouts, complexity scores, and AST validation in connector `execute()` | M3 | ORIGINAL_REQUEST §R3 |
| 12 | Public API Exports & Backwards Compatibility | Exports in `query_builder/__init__.py` and backwards compatibility for all registered connectors (138 classes: 89 sync + 49 async / 306 names, see `docs/CONNECTORS.md`) | M3 | ORIGINAL_REQUEST §R3 |
| 13 | Full-Stack Verification & 100% Coverage Assurance | 100% statement, branch, function test coverage across Python and React, zero linter/formatting errors | M4 | ORIGINAL_REQUEST §R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Security Configuration Architecture & Profiles | `query_builder/config.py`, `tests/test_security_config.py` | None | DONE |
| M2 | Security Validation, Sandboxing, Privacy & Telemetry | `query_builder/security.py`, `policy.py`, `middleware.py`, `telemetry.py`, `tests/test_security_framework.py` | M1 | DONE |
| M3 | Connector Integration & Backwards Compatibility | `query_builder/connectors/base.py`, `async_base.py`, `query_builder/__init__.py`, `tests/test_connector_security.py` | M1, M2 | DONE |
| M4 | Full-Stack Verification & 100% Coverage Assurance | End-to-end test execution, coverage checks, linters (`ruff`, `tsc`), code reviews, audit verification | M1, M2, M3 | DONE |

## Interface Contracts
### Security Configuration (`query_builder/config.py`)
- `NetworkSecurityConfig(allow_private_networks: bool = False, allowed_hostnames: list[str] = [], blocked_hostnames: list[str] = [], enforce_tls: bool = True, verify_ssl_certs: bool = True, ca_bundle_path: str | None = None, socket_timeout_seconds: float = 10.0)`
- `ExecutionSecurityConfig(enforce_read_only_session: bool = True, statement_timeout_ms: int = 5000, max_rows_limit: int = 1000, max_join_depth: int = 5, max_complexity_score: int = 100, prevent_cartesian_products: bool = True)`
- `ValidationSecurityConfig(validate_ast: bool = True, allowed_statements: list[str] = ["SELECT"], allow_system_catalogs: bool = False, filter_sql_comments: bool = True, allow_cte: bool = True, allow_recursive_cte: bool = False)`
- `PrivacySecurityConfig(enforce_tenant_isolation: bool = True, tenant_column: str = "tenant_id", sensitive_column_patterns: list[str] = [...], masking_strategy: str = "redact")`
- `LoggingSecurityConfig(mask_credentials: bool = True, redact_parameters: bool = False, emit_audit_events: bool = True, sensitive_key_patterns: list[str] = [...])`
- `SecurityConfig(network: NetworkSecurityConfig, execution: ExecutionSecurityConfig, validation: ValidationSecurityConfig, privacy: PrivacySecurityConfig, logging: LoggingSecurityConfig, profile: str = "production")`
- `SecurityProfile.development() -> SecurityConfig`
- `SecurityProfile.production() -> SecurityConfig`
- `SecurityProfile.strict() -> SecurityConfig`
- `load_security_config_from_env() -> SecurityConfig`
- `configure_security(config: SecurityConfig | None = None, **overrides: Any) -> SecurityConfig`
- `get_security_config() -> SecurityConfig`
- `reset_security_config() -> None`

### Security Engine (`query_builder/security.py`)
- `validate_network_target(host: str | None = None, port: int | None = None, url: str | None = None, config: dict[str, Any] | None = None, network_config: NetworkSecurityConfig | None = None) -> None`
- `scrub_secrets(value: Any, patterns: list[str] | None = None) -> Any`
- `calculate_ast_complexity(spec: dict[str, Any] | QuerySpec) -> int`
- `check_cartesian_products(spec: dict[str, Any] | QuerySpec) -> None`
- `apply_column_masking(value: Any, strategy: str = "redact") -> Any`

### Connector Security (`query_builder/connectors/base.py`, `async_base.py`)
- `BaseConnector.__init__(..., security: SecurityConfig | None = None, **config)`
- `AsyncBaseConnector.__init__(..., security: SecurityConfig | None = None, **config)`
- `BaseConnector.execute(spec: QuerySpec | None = None, sql: str | None = None, params: list | None = None, timeout_ms: int | None = None, validate_ast: bool | None = None, security: SecurityConfig | None = None) -> QueryResult`
- `AsyncBaseConnector.execute(spec: QuerySpec | None = None, sql: str | None = None, params: list | None = None, timeout_ms: int | None = None, validate_ast: bool | None = None, security: SecurityConfig | None = None) -> QueryResult`

## Code Layout
- Python Backend:
  - `query_builder/config.py`: Core configuration models, environment profiles, and env loaders
  - `query_builder/security.py`: Network validation, secret scrubbing, complexity scoring, Cartesian product checking, column masking, and ownership predicate resolution
  - `query_builder/policy.py`: Sensitive column regex patterns and dynamic column masking
  - `query_builder/middleware.py`: SecurityMiddleware lifecycle interceptor
  - `query_builder/telemetry.py`: AuditEvent recording and parameter redaction
  - `query_builder/connectors/base.py`: SecurityConfig integration, secret scrubbing in __repr__/__str__ and exceptions, dynamic execution boundaries
  - `query_builder/connectors/async_base.py`: AsyncBaseConnector security integration
  - `query_builder/__init__.py`: Public symbol exports
  - `tests/test_security_config.py`: Unit tests for config models, profiles, env loaders, and thread-safety
  - `tests/test_security_framework.py`: Unit tests for SSRF validation, secret scrubbing, AST complexity, Cartesian checks, and masking
  - `tests/test_connector_security.py`: Integration tests for connectors with security configs, credential sanitization, and execution boundaries
