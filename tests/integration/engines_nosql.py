"""
NoSQL / graph / document / wide-column / key-value engines and cloud-database emulators.

Containers: ``docker/compose.nosql.yml`` (profile ``nosql``). Run one engine per batch:

    python scripts/it_batch.py --label arango --engines arangodb \
        --compose docker/compose.nosql.yml --profile nosql --services arangodb

Engines flagged ``emulated=True`` run against a vendor emulator of a cloud product; a pass
there is real evidence but the status tier is ``emulated``, never ``certified``.
Native seeders use the vendor drivers, never the connector under test.
"""

from __future__ import annotations

import os
from typing import Any

from tests.integration import smoke
from tests.integration.engines import Engine, register

PEOPLE = smoke.PEOPLE
BY_AGE = smoke.BY_AGE


def _count_check(fn: Any) -> Any:
    return lambda e: [{"count": fn(e)}]


# =====================================================================  ArangoDB
def _arango_db(e: Engine, system: bool = False) -> Any:
    from arango import ArangoClient

    client = ArangoClient(hosts=f"http://{e.host}:{e.port_}")
    return client.db(
        "_system" if system else e.database_,
        username=e.user_,
        password=e.password_,
    )


def _seed_arango(e: Engine) -> None:
    sysdb = _arango_db(e, system=True)
    if not sysdb.has_database(e.database_):
        sysdb.create_database(e.database_)
    db = _arango_db(e)
    if db.has_collection("qbit_people"):
        db.delete_collection("qbit_people")
    col = db.create_collection("qbit_people")
    col.insert_many([{"_key": str(i), "id": i, "name": n, "age": a} for i, n, a in PEOPLE])


def _arango_count(e: Engine) -> int:
    return _arango_db(e).collection("qbit_people").count()


def _arango_cleanup(e: Engine) -> None:
    db = _arango_db(e)
    if db.has_collection("qbit_people"):
        db.delete_collection("qbit_people")


def _kw_arango(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "hosts": f"http://{e.host}:{e.port_}",
        "database": e.database_,
        "username": e.user_,
        "password": o.get("password") or e.password_,
    }


register(
    Engine(
        name="arangodb",
        connector="arangodb",
        async_connector="async_arangodb",
        tier="extended",
        family="",
        drivers=("arango",),
        pip="python-arango",
        port=43529,
        user="root",
        connector_factory=_kw_arango,
        service="arangodb",
        container_port=8529,
    )
)
smoke.SMOKE["arangodb"] = smoke.Smoke(
    seed=_seed_arango,
    table="qbit_people",
    columns={"name", "age"},
    read="FOR p IN qbit_people SORT p.age RETURN {name: p.name, age: p.age}",
    expected=BY_AGE,
    writes=[
        "FOR p IN qbit_people REMOVE p IN qbit_people",
        "FOR p IN qbit_people UPDATE p WITH {age: 0} IN qbit_people",
        "INSERT {name: 'x', age: 1} INTO qbit_people",
        "FOR p IN qbit_people REPLACE p WITH {name: 'x'} IN qbit_people",
        "UPSERT {name: 'zed'} INSERT {name: 'zed', age: 1} UPDATE {} IN qbit_people",
        "FOR p IN qbit_people FILTER p.age > 0 REMOVE p IN qbit_people RETURN OLD",
    ],
    check=_count_check(_arango_count),
    cleanup=_arango_cleanup,
)

_ = os  # reserved for env-driven switches in later engines
