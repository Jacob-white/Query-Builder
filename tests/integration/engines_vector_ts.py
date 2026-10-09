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


# ---------------------------------------------------------------- Weaviate
WEAVIATE_CLASS = "Qbit_people"  # Weaviate class names start with an upper-case letter


def _weaviate_grpc_port(e: Engine) -> int:
    return int(e.env("GRPC_PORT", 50051 if e._in_docker() else 44051))


def _weaviate_client(e: Engine) -> Any:
    import weaviate

    return weaviate.connect_to_custom(
        http_host=e.host,
        http_port=e.port_,
        http_secure=False,
        grpc_host=e.host,
        grpc_port=_weaviate_grpc_port(e),
        grpc_secure=False,
    )


def _kw_weaviate(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": f"http://{e.host}:{e.port_}",
        "grpc_host": e.host,
        "grpc_port": _weaviate_grpc_port(e),
    }


def _seed_weaviate(e: Engine) -> None:
    from weaviate.classes.config import Configure, DataType, Property, VectorDistances
    from weaviate.classes.data import DataObject
    from weaviate.util import generate_uuid5

    client = _weaviate_client(e)
    try:
        if client.collections.exists(WEAVIATE_CLASS):
            client.collections.delete(WEAVIATE_CLASS)
        client.collections.create(
            WEAVIATE_CLASS,
            vectorizer_config=Configure.Vectorizer.none(),
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE
            ),
            properties=[
                Property(name="name", data_type=DataType.TEXT),
                Property(name="age", data_type=DataType.INT),
            ],
        )
        client.collections.get(WEAVIATE_CLASS).data.insert_many(
            [
                DataObject(
                    properties={"name": name, "age": age},
                    vector=VECTORS[pid],
                    uuid=generate_uuid5(str(pid)),
                )
                for pid, name, age in PEOPLE
            ]
        )
    finally:
        client.close()


def _check_weaviate(e: Engine) -> list[dict[str, Any]]:
    client = _weaviate_client(e)
    try:
        agg = client.collections.get(WEAVIATE_CLASS).aggregate.over_all(
            total_count=True
        )
        return [{"count": agg.total_count}]
    finally:
        client.close()


register(
    Engine(
        name="weaviate",
        connector="weaviate",
        async_connector="async_weaviate",
        tier="extended",
        family="",
        drivers=("weaviate",),
        pip="weaviate-client",
        port=44080,
        container_port=8080,
        service="weaviate",
        password="",
        connector_factory=_kw_weaviate,
    )
)

smoke.SMOKE["weaviate"] = smoke.Smoke(
    seed=_seed_weaviate,
    table=WEAVIATE_CLASS,
    columns={"id", "vector", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_check_weaviate,
)


# ---------------------------------------------------------------- Milvus
def _milvus_client(e: Engine) -> Any:
    from pymilvus import MilvusClient

    return MilvusClient(uri=f"http://{e.host}:{e.port_}")


def _kw_milvus(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"uri": f"http://{e.host}:{e.port_}"}


def _seed_milvus(e: Engine) -> None:
    client = _milvus_client(e)
    try:
        if client.has_collection("qbit_people"):
            client.drop_collection("qbit_people")
        client.create_collection(
            collection_name="qbit_people",
            dimension=4,
            metric_type="COSINE",
            auto_id=False,
        )
        client.insert(
            "qbit_people",
            [
                {"id": pid, "vector": VECTORS[pid], "name": name, "age": age}
                for pid, name, age in PEOPLE
            ],
        )
        client.flush("qbit_people")
    finally:
        client.close()


def _check_milvus(e: Engine) -> list[dict[str, Any]]:
    client = _milvus_client(e)
    try:
        rows = client.query("qbit_people", filter="", output_fields=["count(*)"])
        return [{"count": rows[0]["count(*)"]}]
    finally:
        client.close()


register(
    Engine(
        name="milvus",
        connector="milvus",
        async_connector="async_milvus",
        tier="extended",
        family="",
        drivers=("pymilvus",),
        pip="pymilvus",
        port=44530,
        container_port=19530,
        service="milvus",
        password="",
        connector_factory=_kw_milvus,
    )
)

smoke.SMOKE["milvus"] = smoke.Smoke(
    seed=_seed_milvus,
    table="qbit_people",
    columns={"id", "vector", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_check_milvus,
)


# ---------------------------------------------------------------- Prometheus / VictoriaMetrics
#: PromQL reads return labels as strings, so the expected ages are strings
PROM_BY_AGE = [
    {"name": n, "age": str(a)} for _, n, a in sorted(PEOPLE, key=lambda p: p[2])
]
PROM_WRITES = [
    "/api/v1/admin/tsdb/delete_series?match[]=qbit_people_age",
    "/api/v1/admin/tsdb/delete_series?match[]={__name__=~'.%2B'}",
    "/-/quit",
    "/-/reload",
    "DELETE FROM qbit_people_age",
    "DROP TABLE qbit_people_age",
]


def _http_get_json(url: str) -> Any:
    import json
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as res:  # noqa: S310
        return json.loads(res.read())


def _prom_series_count(e: Engine) -> list[dict[str, Any]]:
    data = _http_get_json(
        f"http://{e.host}:{e.port_}/api/v1/query?query=qbit_people_age"
    )
    return [{"count": len(data["data"]["result"])}]


def _wait_series(e: Engine) -> None:
    import time

    for _ in range(120):
        try:
            if _prom_series_count(e)[0]["count"] >= len(PEOPLE):
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("qbit_people_age series never became queryable")


def _seed_prometheus(e: Engine) -> None:
    _wait_series(e)  # the recording rules in compose.vector_ts.yml create the series


def _seed_victoriametrics(e: Engine) -> None:
    import urllib.request

    body = "\n".join(
        f'qbit_people_age{{name="{n}",age="{a}"}} {a}' for _, n, a in PEOPLE
    )
    req = urllib.request.Request(
        f"http://{e.host}:{e.port_}/api/v1/import/prometheus",
        data=body.encode(),
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()  # noqa: S310
    urllib.request.urlopen(  # noqa: S310
        f"http://{e.host}:{e.port_}/internal/force_flush", timeout=15
    ).read()
    _wait_series(e)


def _kw_http(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"url": f"http://{e.host}:{e.port_}"}


for _name, _conn, _aconn, _port, _cport, _svc, _seed in (
    (
        "prometheus",
        "prometheus",
        "async_prometheus",
        44090,
        9090,
        "prometheus",
        _seed_prometheus,
    ),
    (
        "victoriametrics",
        "victoriametrics",
        "async_victoriametrics",
        44428,
        8428,
        "victoriametrics",
        _seed_victoriametrics,
    ),
):
    register(
        Engine(
            name=_name,
            connector=_conn,
            async_connector=_aconn,
            tier="extended",
            family="",
            drivers=("httpx", "requests"),
            pip="httpx",
            port=_port,
            container_port=_cport,
            service=_svc,
            password="",
            connector_factory=_kw_http,
        )
    )
    smoke.SMOKE[_name] = smoke.Smoke(
        seed=_seed,
        table="qbit_people_age",
        columns={"timestamp", "value", "name", "age"},
        read="qbit_people_age",
        expected=PROM_BY_AGE,
        writes=PROM_WRITES,
        spec=None,
        check=_prom_series_count,
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


# ---------------------------------------------------------------- TDengine
TD_DB = "qbit"


def _td_rest(e: Engine, database: str | None = None) -> Any:
    import taosrest

    return taosrest.connect(
        url=f"http://{e.host}:{e.port_}",
        user=e.user_,
        password=e.password_,
        database=database,
    )


def _kw_tdengine(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    # No ``taos`` native client library here: the connector must fall through to taosrest.
    return {
        "database": TD_DB,
        "url": f"http://{e.host}:{e.port_}",
        "user": e.user_,
        "password": o.get("password") or e.password_,
    }


def _seed_tdengine(e: Engine) -> None:
    conn = _td_rest(e)
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TD_DB}")
    cur.execute(f"CREATE DATABASE {TD_DB}")
    cur.execute(f"USE {TD_DB}")
    cur.execute(
        "CREATE TABLE qbit_people (ts TIMESTAMP, id INT, name VARCHAR(20), age INT)"
    )
    for i, (pid, name, age) in enumerate(PEOPLE):
        cur.execute(
            f"INSERT INTO qbit_people VALUES ({1700000000000 + i}, {pid}, '{name}', {age})"
        )
    conn.close()


def _check_tdengine(e: Engine) -> list[dict[str, Any]]:
    conn = _td_rest(e, TD_DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM qbit_people")
    n = cur.fetchall()[0][0]
    conn.close()
    return [{"count": n}]


register(
    Engine(
        name="tdengine",
        connector="tdengine",
        async_connector="async_tdengine",
        tier="extended",
        family="",
        drivers=("taosrest", "taos"),
        pip="taospy",
        port=44041,
        container_port=6041,
        service="tdengine",
        user="root",
        password="taosdata",
        connector_factory=_kw_tdengine,
    )
)

smoke.SMOKE["tdengine"] = smoke.Smoke(
    seed=_seed_tdengine,
    table="qbit_people",
    columns={"ts", "id", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_check_tdengine,
)


# ---------------------------------------------------------------- InfluxDB 3 (Core)
INFLUX_DB = "qbit"


def _influx_post(e: Engine, path: str, body: str = "") -> None:
    import urllib.request

    req = urllib.request.Request(
        f"http://{e.host}:{e.port_}{path}", data=body.encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as res:  # noqa: S310
        res.read()


def _kw_influxdb(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": f"http://{e.host}:{e.port_}",
        "token": "qb-it-token",
        "database": INFLUX_DB,
    }


def _seed_influxdb(e: Engine) -> None:
    lines = "\n".join(
        f'qbit_people id={pid}i,name="{name}",age={age}i {1700000000000000000 + i}'
        for i, (pid, name, age) in enumerate(PEOPLE)
    )
    _influx_post(
        e,
        f"/api/v3/write_lp?db={INFLUX_DB}&precision=nanosecond&accept_partial=false",
        lines,
    )


def _check_influxdb(e: Engine) -> list[dict[str, Any]]:
    import json
    import urllib.request

    req = urllib.request.Request(
        f"http://{e.host}:{e.port_}/api/v3/query_sql",
        data=json.dumps(
            {
                "db": INFLUX_DB,
                "q": "SELECT COUNT(*) AS n FROM qbit_people",
                "format": "json",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as res:  # noqa: S310
        return [{"count": json.loads(res.read())[0]["n"]}]


register(
    Engine(
        name="influxdb",
        connector="influxdb",
        tier="extended",
        family="",
        drivers=("influxdb_client_3",),
        pip="influxdb3-python",
        port=44181,
        container_port=8181,
        service="influxdb3",
        password="",
        connector_factory=_kw_influxdb,
    )
)

smoke.SMOKE["influxdb"] = smoke.Smoke(
    seed=_seed_influxdb,
    table="qbit_people",
    columns={"time", "id", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=smoke.BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=smoke.SPEC_PEOPLE,
    check=_check_influxdb,
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
