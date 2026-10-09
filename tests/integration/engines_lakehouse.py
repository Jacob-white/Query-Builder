"""
Lakehouse / distributed query engines (family "lakehouse"): Presto, Drill, Spark Thrift
Server, HiveServer2, Kyuubi, Flink SQL Gateway, Pinot, Druid, Dremio, Impala, ksqlDB.

Containers: ``docker/compose.lakehouse.yml`` (profile ``lakehouse``). Run ONE engine per
``scripts/it_batch.py`` batch, e.g.::

    python scripts/it_batch.py --label presto --engines presto \
        --compose docker/compose.lakehouse.yml --profile lakehouse --services presto
"""

from __future__ import annotations

from typing import Any

from tests.integration import dataset
from tests.integration.engines import Engine, Native, register

# Presto/Drill: no constraints, VARCHAR strings; same DDL shape as Trino.
dataset.FAMILIES.setdefault("presto", dataset.FAMILIES["trino"])
dataset.FAMILIES.setdefault("drill", dataset.FAMILIES["trino"])


# --------------------------------------------------------------------------- Presto
def _presto_native(e: Engine) -> Native:
    import prestodb

    conn = prestodb.dbapi.connect(
        host=e.host, port=e.port_, user=e.user_, catalog="memory", schema="default"
    )

    def run(sql: str) -> Any:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()

    return Native(run, conn.close)


def _kw_presto(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog": "memory",
        "schema_name": "default",
        "host": e.host,
        "port": e.port_,
        "user": e.user_,
    }


register(
    Engine(
        name="presto",
        connector="prestodb",
        async_connector="async_prestodb",
        tier="extended",
        family="presto",
        drivers=("prestodb",),
        pip="presto-python-client",
        port=42080,
        user="qb",
        password="",
        connector_factory=_kw_presto,
        native_factory=_presto_native,
        service="presto",
        container_port=8080,
        unsupported={
            "introspect_pk": "Presto memory catalog has no primary keys",
            "introspect_fk": "Presto memory catalog has no foreign keys",
            "case_sensitive_identifiers": "Presto folds identifiers to lower case",
            "statement_timeout": "Presto timeouts are session properties, not applied",
            "db_read_only": "no read-only login in the memory catalog",
        },
    )
)

# --------------------------------------------------------------------------- Drill
DRILL_WS = "dfs.tmp"


def _drill_rest(e: Engine, sql: str) -> list[dict[str, Any]]:
    """Seed/cleanup over Drill's REST API directly (not through the connector under test)."""
    import requests

    r = requests.post(
        f"http://{e.host}:{e.port_}/query.json",
        json={"queryType": "SQL", "query": sql},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("queryState") not in (None, "COMPLETED"):
        raise RuntimeError(f"Drill query failed: {sql[:120]}")
    return data.get("rows", [])


def _drill_lit(value: Any, sql_type: str) -> str:
    if value is None:
        return f"CAST(NULL AS {sql_type})"
    if isinstance(value, int):
        return f"CAST({value} AS INTEGER)"
    return "CAST('" + str(value).replace("'", "''") + "' AS VARCHAR)"


def _drill_ctas(table: str, cols: list[str], rows: list[tuple[Any, ...]]) -> str:
    types = []
    for i in range(len(cols)):
        sample = next((r[i] for r in rows if r[i] is not None), 0)
        types.append("INTEGER" if isinstance(sample, int) else "VARCHAR")
    selects = []
    for row in rows:
        parts = [
            f"{_drill_lit(v, t)} AS `{c}`"
            for v, c, t in zip(row, cols, types, strict=True)
        ]
        selects.append("SELECT " + ", ".join(parts))
    return f"CREATE TABLE {DRILL_WS}.`{table}` AS " + " UNION ALL ".join(selects)


class DrillEngine(Engine):
    """Drill has no INSERT for file tables: tables are created with CTAS from literals."""

    def seed(self) -> None:
        self.cleanup()
        d = dataset
        _drill_rest(self, _drill_ctas(d.T_DEPT, ["id", "name"], d.DEPARTMENTS))
        _drill_rest(
            self,
            _drill_ctas(
                d.T_EMP,
                ["id", "name", "dept_id", "salary", "age", "email"],
                d.EMPLOYEES,
            ),
        )
        _drill_rest(
            self,
            _drill_ctas(
                d.T_RES,
                ["id", "select", "group", "order", "MixedCase", d.UNICODE_COL],
                d.RESERVED,
            ),
        )
        _drill_rest(self, _drill_ctas(d.T_MIXED, ["id", "val"], [(1, "mixed")]))

    def cleanup(self) -> None:
        for t in (dataset.T_EMP, dataset.T_RES, dataset.T_MIXED, dataset.T_DEPT):
            try:
                _drill_rest(self, f"DROP TABLE IF EXISTS {DRILL_WS}.`{t}`")
            except Exception:  # noqa: BLE001, S110
                pass


def _kw_drill(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"host": e.host, "port": e.port_, "schema_name": DRILL_WS}


_DRILL_COLS = "INFORMATION_SCHEMA.`COLUMNS`"
register(
    DrillEngine(
        name="drill",
        connector="drill",
        async_connector="async_drill",
        tier="extended",
        family="drill",
        drivers=("pydrill",),
        pip="pydrill",
        port=42047,
        user="",
        password="",
        connector_factory=_kw_drill,
        slow_sql=(
            f"SELECT COUNT(*) FROM {_DRILL_COLS} a JOIN {_DRILL_COLS} b "
            "ON a.TABLE_CATALOG = b.TABLE_CATALOG JOIN "
            f"{_DRILL_COLS} c ON a.TABLE_CATALOG = c.TABLE_CATALOG"
        ),
        service="drill",
        container_port=8047,
        unsupported={
            "introspect_pk": "Drill file tables carry no key constraints",
            "introspect_fk": "Drill file tables carry no key constraints",
            "introspect_not_null": "Drill file tables (parquet via CTAS) have no NOT NULL constraints",
            "case_sensitive_identifiers": "Drill identifiers are case-insensitive",
            "db_read_only": "Drill has no read-only login without authentication set up",
        },
    )
)
