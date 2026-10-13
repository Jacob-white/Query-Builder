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
- [ ] put your **own authentication** in front of `query-builder serve` and `query-builder mcp`, and
      derive the tenant id and policy on the server side (section 4)
- [ ] add **network-level egress controls** (section 6)
- [ ] verify what is actually enforced (section 7)

## 2. Know the default

The configuration object defaults to the `production` profile, but a connector created **without an
explicit `security=` while `QB_SECURITY_PROFILE` is unset** relaxes two things:

| | unset (and no `security=`) | `development` | `production` / `strict` |
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
| **`query-builder serve`** (HTTP) | the **connector and its connection settings** (`config`), the **`tenant_id`**, the security **`policy`**, the spec and SQL: all taken from the request body | **none built in** | applied **only if the request carries `tenant_id` or `policy`** |
| **`query-builder mcp`** (AI agents) | the connector name and its settings, from the tool call | none built in | none (no tenant context) |
| **CLI** | the flags and config the operator types | the operator | none |

For the HTTP server this was verified end to end (production profile, `QB_ENFORCE_TENANT_ISOLATION=true`,
real rows): a request with `tenant_id: "acme"` returned only the `acme` rows, and the **same request with no
`tenant_id` returned every tenant's rows**. Any caller can also name another tenant. The server therefore
does not isolate tenants by itself; it applies whatever tenant the request names. Consequences:

- Do not expose `serve` or `mcp` directly. It binds `127.0.0.1` by default; keep it there and put an
  authenticating gateway in front.
- Have the gateway **set or overwrite** `tenant_id` and `policy` from the authenticated identity, and strip
  any value the client sent. Never trust them from the browser.
- Do not let the client choose the connection. Fix the connector and its settings server-side (or an
  allow-list of connection ids); a client that can send `config` can point the connector anywhere your
  network policy allows, and can supply its own credentials.
- An AI agent connected to `mcp` supplies the connection settings in the tool call, so everything in
  section 3 applies to it too. Give it the narrowest read-only role and an allow-list.

Raw SQL (`sql=`) is validated but **not** rewritten to add tenant predicates: for tenant isolation of raw
SQL use specs, or a database role with row-level security ([THREAT_MODEL.md](THREAT_MODEL.md) section 3.4).

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
