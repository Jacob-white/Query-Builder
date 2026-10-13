# Adding a connector

A **connector** opens a connection to one engine, runs compiled SQL (or the engine's native query
language) and reports its schema. A **dialect** ([DIALECT_GUIDE.md](DIALECT_GUIDE.md)) writes the SQL.
Most connectors are small; the work is in the places they must be wired in and in proving them against
the real engine.

Start from the closest existing connector (`vertica.py` and `oceanbase.py` are small SQL examples;
`prometheus.py` is an HTTP one) and copy its shape.

## 1. The connector class

```python
"""Acme DB connector."""

from __future__ import annotations

from typing import Any

from query_builder.connectors.base import (
    BaseConnector,
    ConnectionFailedError,
    DriverNotInstalledError,
    IntrospectionError,
)
from query_builder.connectors.introspection import introspect_information_schema
from query_builder.connectors.registry import register_connector


@register_connector("acme")
class AcmeConnector(BaseConnector):
    """Connector for Acme DB."""

    dialect_name = "acme"  # the key registered in dialects/registry.py

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5000,
        database: str = "main",
        user: str = "reader",
        password: str = "",
        connection: Any = None,
        cursor: Any = None,
        **config: Any,
    ) -> None:
        super().__init__(connection=connection, cursor=cursor, **config)
        self.host, self.port, self.database = host, port, database
        # keep the address where the egress checks look
        self.config.setdefault("host", host)
        self.config.setdefault("port", port)
        self.config.setdefault("user", user)
        self.config.setdefault("password", password)

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            import acme_driver  # imported lazily: the driver is an optional extra
        except ImportError as err:
            raise DriverNotInstalledError(
                "'acme-driver' is not installed. Install with: pip install 'query-builder-engine[acme]'"
            ) from err
        try:
            self._connection = acme_driver.connect(
                database=self.database, **self.config
            )
        except Exception as exc:
            raise ConnectionFailedError(f"Failed to connect to Acme DB: {exc}") from exc
        return self._connection

    def introspect_schema(self, filter_sensitive: bool = True) -> dict[str, Any]:
        with self.get_cursor() as cur:
            try:
                return introspect_information_schema(
                    cur, schema_name=self.database, filter_sensitive=filter_sensitive
                )
            except Exception as exc:
                raise IntrospectionError(
                    f"Failed to introspect Acme DB: {exc}"
                ) from exc
```

Also consider, in this order of importance:

- `apply_statement_timeout(cursor, timeout_ms)`: a real statement timeout. Check it actually cancels a
  slow query on the engine; some drivers ignore a connection-level setting and only honour one on the
  prepared statement (Db2, Informix).
- `apply_read_only(connection)` and `read_only_support` (`"enforced"`, `"best_effort"` or `"none"`):
  say honestly what the engine can enforce ([THREAT_MODEL.md](THREAT_MODEL.md)).
- `test_connection()`, `execute_raw`, and for an async connector the `AsyncBaseConnector` equivalents.
  Every registered async connector must implement `introspect_schema`; a test fails if one inherits the
  empty default.

Typing rules (`docs/TYPING.md`): put the optional import in a function or a module-level
`try/except ImportError` with the name typed `Any`; a `# type: ignore` needs an error code and a reason.

### What the base class already does for you

`BaseConnector.__init_subclass__` wraps your `connect`, `execute`, `execute_raw`,
`introspect_schema` and `test_connection` automatically. You get, without calling anything:

- **network-egress validation** before `connect()` (`validate_network_target`) and the **connect-time
  egress guard** around every method above ([SECURITY.md](../SECURITY.md) section 3.2),
- error mapping (driver exceptions become `QueryExecutionError`),
- secret scrubbing of exceptions and `repr`.

So do **not** re-implement them, and do **not** work around them:

- keep the address in a key or attribute the checks recognise (`host`, `hostname`, `url`, `uri`,
  `endpoint`, `dsn`, `connection_string`, `hosts`, `servers`, `nodes`, `*_url`, ...; see
  `is_address_key` in `query_builder/security.py`). An address kept under an unrecognised name is never
  validated;
- an HTTP client must **not follow redirects** (a redirect is followed after validation, to an address
  nobody checked): `requests` needs `allow_redirects=False`; `httpx` does not follow by default, so do not
  turn it on; `urllib` needs an opener whose redirect handler refuses (see `_RefuseRedirects` in `connectors/influxdb.py`);
- do not open connections from a thread you start yourself: the guard is per thread / asyncio task and
  would not see it (use `asyncio.to_thread`, which carries the context along);
- a driver that connects in C without Python's `socket` (libpq, ODBC, ...) is validated but not guarded;
  say so in the connector's docstring.

## 2. Introspection

Reuse `introspect_information_schema` where the engine has an `information_schema` (options:
`fk_style="mysql"` or `"mssql"`, `placeholder="?"`, `pk_guess=False`, `pk_column_key_fallback`), or write
`introspect_<engine>` in `query_builder/connectors/introspection.py` and return
`normalize_schema_snapshot(...)`. Lessons from engines already run live:

- never guess a primary key by a column named `id` when the engine has a catalog;
- many helpers swallow a failed key query (`contextlib.suppress`) and return no foreign keys, which looks
  like success; assert in a live test that the seeded foreign key **is** found;
- catalogs differ wildly (Vertica `v_catalog`, Informix `sysindexes`, Db2 `SYSCAT`, Derby JDBC metadata):
  see the quirk table in [DIALECT_GUIDE.md](DIALECT_GUIDE.md).

## 3. Wire it in

| Where | What |
| :--- | :--- |
| `query_builder/connectors/<name>.py` | the class, decorated with `@register_connector("name")` |
| `query_builder/connectors/__init__.py` | import it, `ConnectorRegistry.register("name", Cls, aliases=[...])`, add it to `__all__` |
| `query_builder/__init__.py` | import and export the connector (and its dialect) in `__all__` |
| `query_builder/dialects/` | the dialect, registered in `DIALECTS` (`registry.py`), exported, and mapped in `DIALECT_MAP` (`sql_ast.py`) |
| `pyproject.toml` | the extra (`acme = ["acme-driver>=1"]`); `tests/test_packaging.py` enforces: no duplicate requirements, alias extras reference the canonical extra, `all` holds only pure-Python / wheel-everywhere drivers and C-extension drivers go in `all-native` |
| `docs/CONNECTORS.md` | generated: `python scripts/gen_connector_status.py` |
| `CHANGELOG.md` | an entry under *Unreleased* |

Adding a class changes the totals, and `tests/test_connector_status.py::test_docs_cite_the_real_connector_counts`
requires `README.md`, `docs/README.md`, `PROJECT.md` and `MISSING_CONNECTORS_PLAN.md` to quote the new
numbers; update them from `docs/CONNECTORS.md`.

## 4. Unit tests

- Mock the driver (`patch.dict(sys.modules, {"acme_driver": mock})`) and cover: driver missing, connect
  failure, connect success and caching, `test_connection`, `introspect_schema` (success and failure).
  See `tests/test_expanded_connectors.py`.
- Dialect and golden snapshots: [DIALECT_GUIDE.md](DIALECT_GUIDE.md), section 4.
- `tests/test_egress_guard.py` already asserts that **every registered connector** has all its entry
  points guarded, so a new class is covered automatically; do not subclass in a way that bypasses
  `__init_subclass__`.

## 5. Run it against the real engine

Mocks pass on engines that are completely broken; every connector added so far had defects only a real
run showed. Follow [TESTING_LIVE.md](TESTING_LIVE.md) ("Adding engines"): an `Engine` entry in
`tests/integration/engines_<family>.py`, a service in `docker/compose.<family>.yml`, then
`scripts/it_batch.py`. Things that cost time:

- **Healthcheck:** use a binary the image really contains. The OceanBase image has `obclient`, not
  `mysql`; some images have no `curl`; `/dev/tcp` needs `bash`, not `sh`. A healthcheck that can never
  pass looks like "the engine will not start".
- **Dataset:** the engine may reject the standard DDL (no `NOT NULL`, ASCII-only column names). Give it
  its own DDL family in `tests/integration/dataset.py` and declare the limitation.
- **Limitations must prove themselves:** `Limitation(reason, probe=...)`; the probe runs through the
  native driver and the engine must reject the feature. A bare skip can hide a real gap.
- **Drivers that will not install on Windows:** `--linux`. Under Git Bash set
  `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"` or container paths are rewritten.
- **Do not install drivers into your own environment:** `pip install --target <scratch dir>` and put it
  on `PYTHONPATH` (`;`-separated on Windows).
- **Resources:** heavy engines (Doris, OceanBase, Db2) need several GB free; run one engine at a time.
- **Safety:** the suite uses the compose project `qb-integration` only. Never stop, restart or remove
  containers outside it.

Record the result: `python scripts/gen_connector_status.py --record-live tests/integration/.reports/<label>.json`.

## 6. Definition of done

- [ ] connector, dialect, registrations, exports and `DIALECT_MAP` entry
- [ ] optional extra in `pyproject.toml`; `python -m pytest tests/test_packaging.py` passes
- [ ] unit tests; golden snapshots regenerated **and the diff reviewed**
- [ ] a live run against the real engine, with defects fixed and a regression test for each
- [ ] limitations declared with probes; results recorded; `docs/CONNECTORS.md` regenerated
- [ ] documented counts updated; `CHANGELOG.md` entry
- [ ] `ruff check .`, `ruff format --check .`, `python -m mypy query_builder` and the full test suite pass
