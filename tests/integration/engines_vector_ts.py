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

from tests.integration import dataset, smoke
from tests.integration.engines import Engine, Native, register

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


# ---------------------------------------------------------------- Pinecone (emulator)
PINECONE_INDEX = "qbit-people"  # Pinecone index names: lowercase alphanumerics and '-'


def _pinecone_client(e: Engine) -> Any:
    from pinecone import Pinecone

    return Pinecone(api_key="pclocal", host=f"http://{e.host}:{e.port_}")


def _kw_pinecone(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"api_key": "pclocal", "host": f"http://{e.host}:{e.port_}"}


def _pinecone_index(e: Engine, pc: Any) -> Any:
    host = pc.describe_index(PINECONE_INDEX).host
    if "://" not in host:
        host = f"http://{host}"
    return pc.Index(host=host)


def _seed_pinecone(e: Engine) -> None:
    import time

    from pinecone import ServerlessSpec

    pc = _pinecone_client(e)
    if pc.has_index(PINECONE_INDEX):
        pc.delete_index(PINECONE_INDEX)
    pc.create_index(
        name=PINECONE_INDEX,
        dimension=4,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    for _ in range(60):
        if pc.describe_index(PINECONE_INDEX).status["ready"]:
            break
        time.sleep(0.5)
    idx = _pinecone_index(e, pc)
    idx.upsert(
        vectors=[
            {"id": str(pid), "values": VECTORS[pid], "metadata": {"name": n, "age": a}}
            for pid, n, a in PEOPLE
        ]
    )
    for _ in range(60):  # the emulator indexes asynchronously
        if idx.describe_index_stats()["total_vector_count"] >= len(PEOPLE):
            break
        time.sleep(0.5)


def _check_pinecone(e: Engine) -> list[dict[str, Any]]:
    pc = _pinecone_client(e)
    idx = _pinecone_index(e, pc)
    return [{"count": idx.describe_index_stats()["total_vector_count"]}]


register(
    Engine(
        name="pinecone",
        connector="pinecone",
        async_connector="async_pinecone",
        tier="extended",
        family="",
        drivers=("pinecone",),
        pip="pinecone",
        port=44500,
        container_port=44500,
        service="pinecone",
        password="",
        connector_factory=_kw_pinecone,
        emulated=True,
    )
)

smoke.SMOKE["pinecone"] = smoke.Smoke(
    seed=_seed_pinecone,
    table=PINECONE_INDEX,
    columns={"id", "vector", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_check_pinecone,
)


# ---------------------------------------------------------------- BigQuery (emulator)
BQ_PROJECT = "qb-it"
BQ_DATASET = "qb_it"
dataset.FAMILIES["bigquery"] = dataset.Ddl(
    int_t="INT64",
    nint_t="INT64",
    str_t="STRING",
    nstr_t="STRING",
    quote="`",
    pk=False,
    fk=False,
    not_null="",
)


def _bq_client(e: Engine) -> Any:
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import bigquery

    return bigquery.Client(
        project=BQ_PROJECT,
        credentials=AnonymousCredentials(),
        client_options=ClientOptions(api_endpoint=f"http://{e.host}:{e.port_}"),
        default_query_job_config=bigquery.QueryJobConfig(
            default_dataset=f"{BQ_PROJECT}.{BQ_DATASET}"
        ),
    )


def _bq_native(e: Engine) -> Native:
    client = _bq_client(e)

    def run(sql: str) -> Any:
        return list(client.query(sql).result())

    return Native(run, client.close)


def _kw_bigquery(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"dataset": BQ_DATASET, "client": _bq_client(e)}


register(
    Engine(
        name="bigquery_emulator",
        connector="bigquery",
        tier="extended",
        family="bigquery",
        drivers=("google.cloud.bigquery",),
        pip="google-cloud-bigquery",
        port=44050,
        container_port=9050,
        service="bigquery",
        password="",
        connector_factory=_kw_bigquery,
        native_factory=_bq_native,
        emulated=True,
        unsupported={
            "introspect_pk": "BigQuery has no enforced primary keys",
            "introspect_fk": "BigQuery has no enforced foreign keys",
            "statement_timeout": "no per-statement timeout on the emulator",
            "db_read_only": "the emulator has no IAM / read-only identities",
        },
    )
)
