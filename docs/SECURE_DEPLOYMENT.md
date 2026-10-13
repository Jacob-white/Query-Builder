# Secure deployment

For developers who embed Query-Builder in an application and for AI agents that configure it. It states
what you must set yourself, because the library's defaults favour "works on my network" over "safe to
expose". Everything here was checked against the code or by running it; where something is a limit, it
says so. Background: [SECURITY.md](../SECURITY.md), [THREAT_MODEL.md](THREAT_MODEL.md).

## 1. The short version

If connection settings, tenant ids or queries can come from anyone you do not fully trust (end users, a
browser, an AI agent):

- [ ] set `QB_SECURITY_PROFILE=production` (or `strict`) **in the process environment before it starts**,
      or pass an explicit `SecurityConfig` when you create connectors
- [ ] restrict targets: `QB_ALLOW_PRIVATE_NETWORKS=true` only if you need internal databases, together
      with `QB_ALLOWED_HOSTNAMES=<exact hosts>`
- [ ] connect with a **read-only database role**; do not rely on the session setting alone
- [ ] run `query-builder serve` (secure mode is the default; never pass `--insecure`) or call
      `create_server(security=...)`, so the **server** chooses
      tenant, policy and connection, and put your **own authentication** in front of it and of
      `query-builder mcp` (section 4)
- [ ] add **network-level egress controls** (section 6)
- [ ] verify what is actually enforced (section 7)

## 2. Know the default

The configuration object defaults to the `production` profile, but a connector created **without an
explicit `security=`, while `QB_SECURITY_PROFILE` is unset and the application has not configured security**
(`configure_security`, `configure_query_builder`, `serve --profile`) relaxes two things:

| | nothing configured | `development` | `production` / `strict` |
| :--- | :--- | :--- | :--- |
| private / internal addresses | **allowed** | allowed | blocked |
| TLS enforced | **no** | no | yes |
| cloud credential endpoints (`169.254.169.254`, ECS, EKS, Azure WireServer, ...) | blocked | blocked | blocked |

So by default only the cloud credential endpoints are blocked and internal services stay reachable: a
user-supplied host, a DNS-rebinding answer or a redirect aimed at them is **not** stopped. The full
per-profile table of every variable is in [SECURITY.md](../SECURITY.md) section 4.2 (generated from the
code). Three details that bite:

- A variable that is not in that table is **ignored without an error**. `QB_ALLOWED_HOSTS` was once
  documented but never read; the real name is `QB_ALLOWED_HOSTNAMES`.
- Variables are read **once**, when the configuration is first needed, and cached. Setting them after the
  first connector exists has no effect.
- Each setting is independent: `QB_ALLOW_PRIVATE_NETWORKS=false` on its own does not turn TLS on.

## 3. Lock the targets down

Allow only the hosts you mean to reach. This was run against the code:

```bash
export QB_SECURITY_PROFILE=production
export QB_ALLOW_PRIVATE_NETWORKS=true             # only because the database is internal
export QB_ALLOWED_HOSTNAMES="10.0.0.5,db.internal.example"
```

With that, `10.0.0.5` is allowed and everything else is refused: `10.0.0.6`, `127.0.0.1`, a public
address and the metadata endpoint all raise `SecurityError`. Without `QB_ALLOWED_HOSTNAMES`, enabling
private networks lets a caller reach **any** internal host.

## 4. What each entry point trusts

| Entry point | The caller controls | Authentication | Tenant isolation |
| :--- | :--- | :--- | :--- |
| **Library** (you call it) | what your code passes | yours | `TenantContext` you bind |
| **`query-builder serve --insecure`** (and `create_server()` without `security=`) | the **connector and its connection settings** (`config`), the **`tenant_id`**, the security **`policy`**, the spec and SQL: all taken from the request body | **none built in** | applied to a spec **only if the request carries `tenant_id` or `policy`**; raw SQL is never isolated |
| **`query-builder serve`** (secure mode, the default since 2.0) | only the query spec; the tenant comes from **your resolver**, the policy and the connection from the **operator** | your resolver (a header set by your proxy, or a token verifier) | enforced for every spec; **fails closed** (401) when no tenant resolves; raw SQL refused |
| **`query-builder mcp`** (AI agents) | the connector name and its settings, from the tool call | none built in | none (no tenant context) |
| **CLI** | the flags and config the operator types | the operator | none |

### Insecure mode (`--insecure`)

This is what `serve` did before 2.0, and what `create_server()` does when you pass no `security=`. The server trusts the request. This was verified end to end (production profile,
`QB_ENFORCE_TENANT_ISOLATION=true`, real rows): a request with `tenant_id: "acme"` returned only the `acme`
rows, and the **same request with no `tenant_id` returned every tenant's rows**. Any caller can also name
another tenant. When a request does carry a tenant, it is applied on every endpoint that returns rows
(`execute` on an inline or a registered connection, `stream`, `export`, `export/stream`, `compile`); raw
SQL (`sql=`) is validated but **not** rewritten, so it is never isolated.

The server prints a start-up notice (to stderr) saying so; silence it with `--no-security-notice`.

### Secure mode

`serve` (secure mode is its default since 2.0; `--secure` is still accepted) or `create_server(security=ServerSecurity(...))` makes the **server**, not the client,
choose the tenant, the policy and the connection. It is enforced in one place, before any route handler
runs, so no endpoint can be forgotten:

- **Only these endpoints are served:** `/health`, `/openapi.json`, `/docs`, `/api/v1/compile`,
  `/api/v1/validate`, `/api/v1/execute` (and its aliases `/api/query`, `/api/v1/query/execute`) and
  `/api/v1/explain` (and `/api/query/explain`). Connection management, introspection, streaming, export,
  templates, telemetry and NLQ answer `403 NOT_AVAILABLE_IN_SECURE_MODE`. An operator can add endpoints
  explicitly (`extra_endpoints`) and takes responsibility for them.
- **The client may not send `tenant_id`, `policy` or `config` (and not `connector` on execute / explain).**
  Such a request is refused with `403 FORBIDDEN_FIELD`; it is not silently ignored, so a client that
  believes it chose a tenant finds out.
- **The tenant comes from your resolver.** If none resolves, and tenant isolation is enabled
  (`QB_ENFORCE_TENANT_ISOLATION`, on in the `production` and `strict` profiles) or `require_tenant=True`,
  the request fails closed: `401 TENANT_REQUIRED`. A resolver that raises fails closed too.
- **Every spec is rewritten once** with the resolved tenant and the server-side `policy` (and `schema`
  for ownership chains), before the handler sees it. A client filter naming another tenant, an `OR`
  filter and a CTE over the tenant table were all checked and stay isolated.
- **Raw SQL is refused** (`403 RAW_SQL_FORBIDDEN`) because it cannot be isolated per tenant. `/validate`
  still accepts SQL (it executes nothing). An operator can allow it (`allow_raw_sql=True`) and accepts that
  it is not isolated.
- **The connection is the operator's.** Every execute uses `default_connection_id` (default `"default"`),
  a pool registered by the operator; a `connection_id` the client sends is ignored. Clients cannot create
  connections. One server serves one connection; run one server per database.
- **CORS:** no `Access-Control-Allow-Origin` header unless origins are listed (`--allow-origin`); never `*`.
- Secure mode also applies the `production` security profile unless you pass `--profile` or set
  `QB_SECURITY_PROFILE`, so connectors are not left on the permissive default.

Start it with a connections file (the operator registers the connections; clients cannot):

```bash
cat > connections.json <<'EOF'
{"default": {"connector": "postgres",
             "config": {"host": "db.internal.example", "database": "app", "user": "reader"}}}
EOF
export QB_ALLOW_PRIVATE_NETWORKS=true QB_ALLOWED_HOSTNAMES=db.internal.example
query-builder serve --connections connections.json --tenant-header X-Tenant-ID
```

The CLI takes the tenant from a header. **That is only safe behind a reverse proxy that authenticates the
caller and sets (overwrites) the header**; a header a client can send is exactly as trustworthy as a body
field. For real authentication give the server a resolver:

```python
from query_builder.server import create_server, register_connection
from query_builder.server_security import ServerSecurity
from query_builder.pool import get_connection_pool_manager

TOKENS = {"token-acme": "acme"}  # replace with real token verification


def tenant_from_token(headers):
    token = headers.get("Authorization", "").removeprefix("Bearer ")
    return TOKENS.get(token)  # None means unauthenticated: the request is refused


manager = get_connection_pool_manager()
register_connection(manager, "default", "sqlite", {"database": "app.db"})
server = create_server(
    "127.0.0.1",
    8000,
    connection_pool_manager=manager,
    security=ServerSecurity(tenant_resolver=tenant_from_token, require_tenant=True),
)
server.serve_forever()
```

What it does **not** change: it still has no TLS (terminate it at your proxy), the network and database
controls of sections 3, 5 and 6 still apply, and the tenant predicate only protects tables that carry the
tenant column (`QB_TENANT_COLUMN`; pass `ServerSecurity(schema=...)` for ownership chains). It is verified
by `tests/test_server_secure_mode.py` (every refusal has a control against the default server that accepts
the same request) and `tests/test_cli_secure_serve.py`.

### The other entry points

- Do not expose `mcp` directly. An AI agent connected to it supplies the connection settings in the tool
  call, so everything in section 3 applies to it too. Give it the narrowest read-only role and an
  allow-list. It prints the same kind of start-up notice (to stderr, never stdout: stdout is the protocol).
- Raw SQL (`sql=`) is validated but **not** rewritten to add tenant predicates in any mode: for tenant
  isolation of raw SQL use specs, or a database role with row-level security
  ([THREAT_MODEL.md](THREAT_MODEL.md) section 3.4).

## 5. Database role and session

- Connect with a role that can only `SELECT` the tables it needs ([SECURITY.md](../SECURITY.md) section 5).
- The library puts the session into read-only mode where the engine supports it
  (`QB_ENFORCE_READ_ONLY`, per-engine strength in the threat model). It is defence in depth, not the
  boundary: some engines cannot enforce it.
- Keep AST validation on (`QB_VALIDATE_AST`, and never pass `validate_ast=False` for user-facing paths).
- Set a statement timeout and a row ceiling (`QB_STATEMENT_TIMEOUT_MS`, `QB_MAX_ROWS_LIMIT`).

## 6. Network-level controls (the part code cannot do for you)

The in-process checks validate the configured address and, while a connector runs, the destination of
every Python-level socket connection (the connect-time egress guard). They cannot see drivers that
connect in C without Python's `socket` (libpq, `mysqlclient`, `ibm_db`, ODBC), event loops that bypass
`socket.connect` (`uvloop`), threads a driver starts itself, traffic sent through `HTTP_PROXY` /
`HTTPS_PROXY`, or a SQL function that makes the database server fetch a URL. Cover those at the network:

- deny egress to `169.254.169.254` and the other cloud credential endpoints (firewall, security group,
  Kubernetes `NetworkPolicy`);
- on AWS require IMDSv2 and set the hop limit to 1 so a container cannot reach the instance metadata;
- run the service in a segment whose egress is an allow-list of your databases;
- resolve names through a DNS service you control if rebinding is in your threat model.

## 7. Verify what is enforced

```python
from query_builder.connectors.base import effective_network_config
from query_builder.connectors.registry import get_connector
from query_builder.security import validate_network_target

# use your real connector and settings
connector = get_connector("postgres", host="db.internal.example")
policy = effective_network_config(connector)
print("private networks allowed:", policy.allow_private_networks)
print("TLS enforced:            ", policy.enforce_tls)
print("allowed hostnames:       ", policy.allowed_hostnames)

# the cloud credential endpoint must be refused whatever the policy
try:
    validate_network_target(host="169.254.169.254", network_config=policy)
except Exception as exc:
    print("metadata endpoint refused:", exc)
else:
    raise SystemExit("metadata endpoint NOT refused: do not deploy")
```

Run it in the same environment as the service. `effective_network_config(connector)` returns the policy
that connector will really enforce, including the environment overrides.

## 8. What is not protected

Be explicit about these in your own threat model: a malicious database or driver; data the connecting
role may already read; resource exhaustion by legitimate queries; error messages the database returns;
raw SQL against another tenant's data; and everything listed in section 6. See
[THREAT_MODEL.md](THREAT_MODEL.md) section 4 for the full list of non-guarantees.
