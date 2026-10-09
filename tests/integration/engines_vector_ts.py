"""
Vector stores, time-series and analytics/observability engines for the live suite.

Compose: ``docker/compose.vector_ts.yml`` (profile ``vector_ts``). Run through
``scripts/it_batch.py``, one engine per batch, e.g.::

    python scripts/it_batch.py --label qdrant --engines qdrant \
        --compose docker/compose.vector_ts.yml --profile vector_ts --services qdrant

Vector stores are not SQL engines: the connector compiles a QuerySpec (including
``vector_search``) to the SQL-shaped text of its dialect and its cursor adapter interprets
that text against the vendor client. They are therefore exercised through the NON-SQL smoke
battery (``smoke.SMOKE``) plus ``test_vector_ts.py`` (vector search, filters, introspection of
a real collection), never through the SQL conformance battery.
"""

from __future__ import annotations

from typing import Any

from tests.integration import smoke
from tests.integration.engines import Engine, register

PEOPLE = smoke.PEOPLE
#: 4-d vectors: alice, bob, carol are orthogonal axes, so nearest-neighbour order is exact
VECTORS = {1: [1.0, 0.0, 0.0, 0.0], 2: [0.0, 1.0, 0.0, 0.0], 3: [0.0, 0.0, 1.0, 0.0]}
QUERY_VECTOR = [1.0, 0.1, 0.0, 0.0]  # nearest: alice, then bob, then carol


# ---------------------------------------------------------------- Qdrant
def _kw_qdrant(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"host": e.host, "port": e.port_}


def _seed_qdrant(e: Engine) -> None:
    from qdrant_client import QdrantClient, models

    client = QdrantClient(host=e.host, port=e.port_)
    if client.collection_exists("qbit_people"):
        client.delete_collection("qbit_people")
    client.create_collection(
        "qbit_people",
        vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
    )
    client.upsert(
        "qbit_people",
        points=[
            models.PointStruct(
                id=pid, vector=VECTORS[pid], payload={"name": name, "age": age}
            )
            for pid, name, age in PEOPLE
        ],
        wait=True,
    )
    client.close()


def _check_qdrant(e: Engine) -> list[dict[str, Any]]:
    from qdrant_client import QdrantClient

    client = QdrantClient(host=e.host, port=e.port_)
    try:
        return [{"count": client.count("qbit_people", exact=True).count}]
    finally:
        client.close()


register(
    Engine(
        name="qdrant",
        connector="qdrant",
        async_connector="async_qdrant",
        tier="extended",
        family="",
        drivers=("qdrant_client",),
        pip="qdrant-client",
        port=44333,
        container_port=6333,
        service="qdrant",
        password="",
        connector_factory=_kw_qdrant,
    )
)

smoke.SMOKE["qdrant"] = smoke.Smoke(
    seed=_seed_qdrant,
    table="qbit_people",
    columns={"id", "vector", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_check_qdrant,
)
