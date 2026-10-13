# Security Policy — Query-Builder ⚡

At **Query-Builder**, security is a foundational architectural pillar. Owned and maintained by **HobbyHabbit LLC** under the **MIT License**, Query-Builder is a dynamic query compilation and execution engine supporting over 198 database connector variants, designed to enforce zero-trust query isolation, defense-in-depth SQL injection prevention, and strict multi-tenant data governance.

This document outlines our security policies, vulnerability reporting procedures, defensive architecture, and configuration best practices for developers.

---

## 1. Supported Versions

We provide security patches, bug fixes, and vulnerability reviews for the following versions:

| Version | Supported | Status |
| :--- | :--- | :--- |
| Latest release (`1.x`; `2.x` once released) | :white_check_mark: | Beta: security fixes land on the latest release only |
| Older releases | :x: | Unsupported — please upgrade |

The project is classified **Beta** on PyPI (`Development Status :: 4 - Beta`). Public APIs may
still change between major versions; see `CHANGELOG.md`.

---

## 2. Reporting a Vulnerability

We deeply appreciate the efforts of security researchers and developers in identifying potential security issues. We adhere to **Coordinated Vulnerability Disclosure (CVD)** principles.

### A. How to Report
- **Email**: Send vulnerability reports directly to `security@hobbyhabbit.com`, `support@hobbyhabbit.com`, and `jake@hobbyhabbit.com`.
- **Subject Line**: `[SECURITY VULNERABILITY] Query-Builder — <Brief Description>`
- **GitHub Private Vulnerability Reporting**: You may also report vulnerabilities privately via GitHub's [Advisory Submission Portal](https://github.com/Jacob-white/Query-Builder/security/advisories/new).

### B. What to Include
To help us triage and remediate issues quickly, please include:
1. **Description**: Clear explanation of the vulnerability and its potential impact.
2. **Component Affected**: Specify affected modules (e.g., `ast_validator.py`, `connectors/base.py`, `security.py`, `policy.py`).
3. **Proof-of-Concept (PoC)**: Minimal reproducible Python snippet, curl command, or JSON `QuerySpec`.
4. **Environment**: Python version, database dialect, driver version, and operating system.

### C. Response SLA
- **Initial Acknowledgment**: Within **24 hours** of receipt.
- **Triage & Severity Assessment**: Within **48 hours**.
- **Remediation & Patch Deployment**: Critical issues are prioritized for patch release within **7 days**.
- **Coordinated Public Disclosure**: We follow a standard 90-day disclosure timeline, allowing users sufficient time to upgrade before details are made public.

> [!IMPORTANT]
> **Please do NOT file public GitHub issues for suspected security vulnerabilities.** Always use private channels to protect users and systems in production.

---

## 3. Threat Model & Defense-in-Depth Architecture

Query-Builder protects against the primary attack vectors targeting dynamic query engines:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        APPLICATION LAYER                               │
│           (HobbyHabbit, Firm Network, Third-Party Apps)                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│               QUERY BUILDER COMPILATION & AST VALIDATOR                │
│  - Strict Parameter Binding          - Single-Statement Lock           │
│  - AST Mutation Pattern Detection    - Literal-Stripped Heuristic Scan │
│  - Identifier Regex Whitelisting     - BFS Foreign-Key Join Solver     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  SECURITY POLICY & GOVERNANCE LAYER                    │
│  - Fail-Closed Tenant Isolation      - FK Ownership Chain Traversal    │
│  - Column Masking (Redact/Hash)      - AST Complexity Score Governor   │
│  - Cartesian Product Detection       - Structured Audit Telemetry      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  CONNECTOR & NETWORK EGRESS LAYER                      │
│  - Connection-Time SSRF Egress Check - Bracketed Host Normalization    │
│  - Cloud Metadata IP Blockade        - Automatic Secret Scrubbing      │
│  - Read-Only Session Sandboxing      - Statement Timeout Enforcement   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  DATABASE INFRASTRUCTURE (TARGET)                      │
│  - Least-Privilege DB User           - Engine Row-Level Security       │
│  - Read-Only Replica Routing         - Enforced Wire TLS / SSL         │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1. AST Safety Validation (`query_builder/ast_validator.py`)
- **Single-Statement Enforcement**: Queries containing multiple statements (semicolon chaining like `SELECT 1; DROP TABLE users;`) are unconditionally rejected.
- **Strict Read-Only Locking**: Disallows all mutation keywords (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `CREATE`, `EXEC`, `COPY`, `MERGE`, `DO`, `PRAGMA`).
- **Literal Stripping**: Scans strip string literals (`'value'`) before running heuristic checks, preventing false-positive blocks on benign data while stopping evasion attempts.
- **System Schema Isolation**: Queries referencing administrative or credential schemas (`pg_catalog`, `information_schema`, `sqlite_master`, `mysql.user`, `sys.*`) are blocked unless explicitly allowed.

### 3.2. Network Egress & SSRF Protection (`query_builder/security.py`)

> **Default network policy - read this before exposing a server.**
> The *configuration* default is the `production` profile (private networks blocked, TLS enforced). But a connector created **without an explicit `security=` argument while `QB_SECURITY_PROFILE` is not set** applies a more permissive default: it **allows private and internal addresses** (loopback, RFC 1918, link-local, CGNAT, IPv6 ULA) and **does not enforce TLS**, so databases on your own network work out of the box.
>
> What that means: by default the network-egress check and the connect-time egress guard block only the **cloud credential endpoints** (`169.254.169.254` and the others listed below). **Internal services stay reachable**, so a user-supplied host, a DNS-rebinding answer or a redirect aimed at them is **not** stopped.
>
> `query-builder serve`, the MCP server and the CLI create connectors from request-, tool- or flag-supplied settings and pass no `security=`, so they get this default. If connection settings can come from end users or an AI agent, **set `QB_SECURITY_PROFILE=production` (or `strict`) in the process environment**, or pass an explicit `SecurityConfig` when you create connectors, and add network-level egress controls (see the last bullet below). Under `production` / `strict` private networks are blocked and TLS is enforced (the `development` profile is as permissive as the unset default); to reach an internal database on purpose, opt in explicitly with `allow_private_networks=True` and restrict the targets with `allowed_hostnames`. A request cannot weaken the policy by sending its own `security` value (it is rejected).
>
> The environment variables are read once, lazily, the first time the configuration is needed and then cached: set them before the process starts, not after the first connector has been created. Each setting is independent (for example `QB_ALLOW_PRIVATE_NETWORKS=false` on its own does not turn TLS enforcement on).
>
> To check what applies to a given connector, call `effective_network_config(connector)` (in `query_builder.connectors.base`): it returns the policy that connector will actually enforce.

- **Target Host Validation**: `validate_network_target()` validates all connector target hostnames and IPs prior to socket creation.
- **Private Subnet & Loopback Blocking**: Automatically blocks RFC1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopbacks (`127.0.0.0/8`, `::1`), and IPv6 unique-local addresses unless `allow_private_networks=True`. **This is the effective default only when a profile is selected** (`QB_SECURITY_PROFILE`) or an explicit `security=` is passed; with neither, connectors allow private networks - see the default-policy note above.
- **Cloud Metadata Service Blockade**: Unconditionally blocks requests targeting cloud metadata IPs (`169.254.169.254`) and hostnames (`metadata.google.internal`, `instance-data`).
- **Bracketed Host Normalization**: Strips bracketed host literals (e.g. `[169.254.169.254]` or `[::1]`) so attackers cannot bypass pre-DNS CIDR filters.
- **Every address shape is read**: URLs (including `jdbc:` and multi-host replica-set URLs), `KEY=value` DSNs (libpq, ODBC, Db2), Oracle `//host` and TNS descriptors, `user:pw@host`, comma host lists and driver-specific keys (`hosts`, `servers`, `connstr`, `gateway_url`, ...) are parsed by one shared parser (`extract_address_targets`), and the address attributes a connector keeps outside its config are included.
- **Connect-time egress guard** (`query_builder/egress_guard.py`, on by default; `network.connect_time_guard = False` disables it): validation checks the address a connector is *configured* with, but a driver resolves the name again and an HTTP client may follow a redirect, so the real destination can change afterwards. While a connector runs `connect`, `execute`, `execute_raw`, `introspect_schema` or `test_connection`, every `socket.connect` it makes is checked against the same policy. A rebound DNS answer or a `302 Location: http://169.254.169.254/` is refused before any packet is sent. The guard is per thread / asyncio task, so it never touches the host application's other sockets.
- **No redirects in first-party HTTP code**: the Prometheus/VictoriaMetrics adapter, Cloudflare D1 and the InfluxDB version probe do not follow redirects (the InfluxDB probe also speaks only `http(s)`).
- **Credential endpoints beyond IMDS**: besides `169.254.169.254` the policy always blocks the AWS ECS (`169.254.170.2`) and EKS Pod Identity (`169.254.170.23`, `fd00:ec2::23`) credential endpoints, Azure WireServer (`168.63.129.16`), Alibaba Cloud (`100.100.100.200`) and the legacy Oracle Cloud endpoint (`192.0.0.192`), also when written as an IPv6 form that embeds them.
- **What this does not protect against - add network-level controls**: the guard sees Python sockets only. It does **not** see drivers that connect in C without Python's `socket` (libpq, `mysqlclient`, `ibm_db`, ODBC, `oracledb` thick mode), event loops that bypass `socket.connect` (`uvloop`), or threads a driver starts on its own (for example a MongoDB monitor thread). Those are validated at connect time and, for PostgreSQL, pinned, but a rebound answer can still reach them. Query-level server-side fetches (a database function that downloads a URL) and `HTTP_PROXY`/`HTTPS_PROXY` environment variables (traffic goes to the proxy, which the check never saw) are outside this layer. The only complete protection is at the network: block `169.254.169.254` and the other credential endpoints at the firewall or Kubernetes `NetworkPolicy`, require IMDSv2 with a hop limit of 1 (AWS), and run the service in a segment with an egress allow-list.
- **Wildcard Allowlisting**: Supports declarative domain patterns (e.g., `*.rds.amazonaws.com`).

### 3.3. Database Session Sandboxing (`query_builder/connectors/base.py`)
- **Session Read-Only Mode**: Automatically configures the database session in read-only mode (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;`, `SET readonly = 1;`, `?mode=ro`).
- **Statement Timeout Enforcement**: Applies connector-level and query-level execution timeouts, terminating runaway or denial-of-service queries.
- **Server-Side Pagination Clamping**: Caps query `LIMIT` at `max_rows_limit` (default: 1,000) to prevent memory exhaustion and large-payload exfiltration.
- **AST Complexity Governors**: Evaluates query depth, join counts, and nested expressions, rejecting overly complex queries before driver dispatch.
- **Cartesian Product Prevention**: Detects and rejects disconnected tables or accidental `CROSS JOIN` operations.

### 3.4. Fail-Closed Tenant Isolation (`query_builder/policy.py`)
- **Fail-Closed Execution**: If tenant isolation is enabled and no valid `TenantContext` is provided, execution halts immediately with `SecurityError`.
- **Relational Ownership Chains**: Recursively walks foreign-key relationship graphs using `_build_chain_exists()` to verify ownership of child and junction records.
- **Cyclic Traversal & Depth Limits**: Halts execution if ownership graph traversal exceeds depth 10 or encounters cyclic relationships.

### 3.5. Universal Secret Scrubbing & Data Governance
- **Scrubbing in Logs & Repr**: `scrub_secrets()` automatically sanitizes passwords, tokens, API keys, and connection strings from `__repr__`, `__str__`, and exception cause trees while preserving relational keys (`primary_key`, `foreign_key`).
- **Sensitive Column Masking**: Dynamic regex filters identify sensitive attributes (`password`, `secret`, `ssn`, `api_key`) during schema introspection and query compilation.
- **Masking Strategies**: Supports `redact` (`REDACTED`), `hash` (SHA-256), and `partial` masking (`jo***@domain.com`, `***-**-1234`).
- **Audit Telemetry**: Structured `AuditEvent` records are emitted for all operations with sanitized bind parameters.

---

## 4. Developer Configuration & Security Profiles

Query-Builder is **Secure by Default** but designed to be **ergonomic to configure** across third-party projects.

### 4.1. Pre-Built Security Profiles (`query_builder/config.py`)

Developers can select pre-built profiles matching their deployment environment:

```python
from query_builder import configure_security, SecurityProfile

# 1. Local Development (Docker, localhost, relaxed TLS)
configure_security(SecurityProfile.development())

# 2. Production (Hardened zero-trust defaults)
configure_security(SecurityProfile.production())

# 3. Strict Compliance (Finance, Healthcare, Defense)
configure_security(SecurityProfile.strict())
```

| Security Control | `development` | `production` (Default) | `strict` |
| :--- | :--- | :--- | :--- |
| **Allow Private Subnets (`localhost`, `10.x`, `192.168.x`)** | :white_check_mark: Allowed | :x: Blocked | :x: Blocked |
| **Cloud Metadata Block (`169.254.169.254`)** | :x: Blocked | :x: Blocked | :x: Blocked |
| **Enforce TLS / SSL** | Optional (`False`) | Required (`True`) | Required (`True`) |
| **Verify SSL Certificates** | Optional (`False`) | Required (`True`) | Required (`True`) |
| **Read-Only Session Mode** | Enabled | Enabled | Enabled |
| **Statement Timeout** | `30,000 ms` | `5,000 ms` | `2,000 ms` |
| **Max Rows Pagination Ceiling** | `5,000` | `1,000` | `250` |
| **Max Allowed Join Depth** | `10` | `5` | `3` |
| **AST Complexity Score Cap** | `100` | `50` | `25` |
| **Allow System Catalogs (`pg_catalog`)** | :white_check_mark: Allowed | :x: Blocked | :x: Blocked |
| **Tenant Isolation Required** | Optional | Required | Required |
| **Secret Scrubbing in Logs/Errors** | Enabled | Enabled | Enabled |

---

### 4.2. Zero-Code Environment Variables (Twelve-Factor App)

In containerized environments (Docker, Kubernetes, AWS ECS), security settings can be tuned via environment variables without modifying source code:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `QB_SECURITY_PROFILE` | `str` | `production` | Active profile: `development`, `production`, or `strict`. This is the default of the *config object*; a connector created without `security=` while this is **unset** relaxes private networks and TLS (section 3.2). |
| `QB_ALLOW_PRIVATE_NETWORKS` | `bool` | unset | `true` / `false`. **Unset means private networks are allowed** unless `QB_SECURITY_PROFILE` is set; set `false` to forbid `localhost` and private RFC1918 IPs |
| `QB_ALLOWED_HOSTS` | `list[str]` | `None` | Comma-separated list of allowed hostnames (supports `*.domain.com`) |
| `QB_BLOCKED_HOSTS` | `list[str]` | `169.254.169.254` | Comma-separated list of blocked hostnames or IPs |
| `QB_ENFORCE_TLS` | `bool` | unset | `true` / `false`. **Unset means TLS is not enforced** unless `QB_SECURITY_PROFILE` is set (then `production` / `strict` enforce it); set `true` to enforce encrypted transport across database drivers |
| `QB_VERIFY_SSL_CERTS` | `bool` | `true` | Verify TLS/SSL certificates against trusted CA roots |
| `QB_ENFORCE_READ_ONLY` | `bool` | `true` | Lock database sessions into read-only transaction mode |
| `QB_STATEMENT_TIMEOUT_MS` | `int` | `5000` | Query execution timeout in milliseconds |
| `QB_MAX_ROWS_LIMIT` | `int` | `1000` | Hard server-side pagination ceiling |
| `QB_MAX_JOIN_DEPTH` | `int` | `5` | Maximum number of relational joins per query |
| `QB_MAX_AST_COMPLEXITY` | `int` | `50` | Maximum AST complexity score allowed |
| `QB_VALIDATE_AST` | `bool` | `true` | Enforce AST syntax tree safety validation |
| `QB_ALLOW_SYSTEM_CATALOGS` | `bool` | `false` | Permit access to administrative catalog schemas |
| `QB_ENFORCE_TENANT_ISOLATION`| `bool` | `true` | Enforce fail-closed tenant predicate injection |
| `QB_MASK_SENSITIVE_COLUMNS` | `bool` | `true` | Mask credentials/PII during introspection & preview |
| `QB_MASKING_STRATEGY` | `str` | `redact` | Masking mode: `redact`, `hash`, or `partial` |
| `QB_ENABLE_AUDIT_LOG` | `bool` | `true` | Emit structured audit events |

---

### 4.3. Per-Connector & Per-Query Overrides

```python
from query_builder.connectors import PostgresConnector
from query_builder.config import SecurityConfig, NetworkSecurityConfig

# 1. Instance-Level Security Configuration
connector = PostgresConnector(
    host="db.internal.example.com",
    security=SecurityConfig(
        network=NetworkSecurityConfig(allow_private_networks=True, enforce_tls=True)
    ),
)

# 2. Per-Query Execution Timeout & Sandboxing Override
result = connector.execute(
    query_spec,
    statement_timeout_ms=3000,
    validate_ast=True,
)
```

---

## 5. Security Best Practices for Integrators

When embedding Query-Builder into web applications (e.g. Django, FastAPI, Flask, React):

1. **Use Dedicated Read-Only Database Roles**:
   Never configure connectors with database credentials holding `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `ALTER` permissions. Always create a dedicated read-only role:
   ```sql
   CREATE ROLE query_builder_readonly WITH LOGIN PASSWORD 'strong_password';
   GRANT CONNECT ON DATABASE analytics TO query_builder_readonly;
   GRANT USAGE ON SCHEMA public, reporting TO query_builder_readonly;
   GRANT SELECT ON ALL TABLES IN SCHEMA public, reporting TO query_builder_readonly;
   ```
2. **Never Disable AST Validation in Production**:
   Keep `validate_ast = True` enabled for all user-facing or visual query endpoints.
3. **Always Bind Tenant Context**:
   In multi-tenant applications, always supply a valid `TenantContext` containing the verified user/tenant ID extracted from authenticated session tokens (e.g., JWT).
4. **Enforce Database-Level Row-Level Security (RLS)**:
   For mission-critical multi-tenant databases, pair Query-Builder's application-level predicate injection with PostgreSQL Row-Level Security (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`) as defense-in-depth.
5. **Keep Dependencies Updated**:
   Regularly update Query-Builder, driver packages, and `sqlparse` to maintain protection against evolving AST injection and parser edge cases.
5. **Set a security profile for anything that accepts connection settings from users or agents**:
   Run `query-builder serve` / `query-builder mcp` / your own endpoint with `QB_SECURITY_PROFILE=production` (or `strict`), or pass an explicit `SecurityConfig`. The unset default allows internal networks and does not enforce TLS (section 3.2). Also add network-level egress controls - a firewall or Kubernetes `NetworkPolicy` denying `169.254.169.254` and the other credential endpoints, IMDSv2 with a hop limit of 1, an egress allow-list - because the in-process checks do not cover every driver (section 3.2 and `docs/THREAT_MODEL.md` section 3.6).

---

## 6. Audit & Test Invariants

Query-Builder maintains strict test invariants to guarantee security integrity:
- **Coverage floors enforced in CI**: Python statement + branch coverage must stay at or above 99%
  (`[tool.coverage.report] fail_under` in `pyproject.toml`); the React package enforces
  99% statements / 96% branches / 99% functions / 99% lines (`vitest.config.ts`).
- **Suppressions are rare and reviewed**: a handful of `# pragma: no cover` / `/* v8 ignore */`
  exemptions exist for genuinely unreachable branches; new ones need a justification in review.
- **Adversarial Regression Testing**: The test suites include adversarial cases for SSRF bypasses,
  bracketed hosts, unicode normalization, ReDoS-prone patterns and concurrency races, and run on every
  pull request.

## 6a. Supply-Chain Controls

- **CI on every pull request** (`.github/workflows/ci.yml`): `pip-audit` on the resolved runtime
  dependencies (accepted findings are listed with justification in
  `.github/pip-audit-allowlist.txt`), `pnpm audit --audit-level high` for the React package and the
  starter frontend, GitHub dependency review, and CycloneDX SBOM generation (uploaded as a build artifact).
- **Dependabot** (`.github/dependabot.yml`) proposes weekly updates for pip, npm and GitHub Actions;
  third-party actions are pinned to commit SHAs.
- **Release process** (`.github/workflows/release.yml`, `docs/RELEASING.md`): releases are built from a
  tag in CI, published to PyPI via trusted publishing (OIDC, no long-lived PyPI token) and to npm with
  `--provenance`, and ship with SBOMs and SHA-256 checksums. This pipeline requires one-time maintainer
  setup (see `docs/RELEASING.md`); **no release has been published through it yet**, so provenance
  attestations exist only for releases made after that setup.

---

## 7. Ownership & License

Query-Builder is owned and maintained by **HobbyHabbit LLC** and licensed under the **MIT License**. For enterprise licensing inquiries or commercial support, contact `support@hobbyhabbit.com`.

---

*Last Updated: October 2026 — HobbyHabbit LLC Security Team*
