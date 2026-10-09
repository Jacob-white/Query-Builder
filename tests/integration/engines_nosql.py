"""
NoSQL / graph / document / wide-column / key-value engines and cloud-database emulators.

Containers: ``docker/compose.nosql.yml`` (profile ``nosql``). Run one engine per batch:

    python scripts/it_batch.py --label arango --engines arangodb \
        --compose docker/compose.nosql.yml --profile nosql --services arangodb

Engines flagged ``emulated=True`` run against a vendor emulator of a cloud product; a pass
there is real evidence but the status tier is ``emulated``, never ``certified``.
Native seeders use the vendor drivers, never the connector under test.

Classes with NO live evidence possible here (documented, deliberately not faked):

* ``MongoDBAtlasSQLConnector`` - the Atlas SQL Interface exists only on Atlas Data Federation
  (a cloud service); a local MongoDB does not speak it, and passing against plain MongoDB would
  be evidence for the MongoDB class, not for this one.
* ``NeptuneConnector`` / ``AsyncNeptuneConnector`` - Amazon Neptune is cloud-only (no emulator;
  a plain Neo4j/Gremlin server is not Neptune: IAM-signed endpoints, Neptune-specific openCypher
  behaviour).
* ``TimestreamConnector`` / ``AsyncTimestreamConnector`` - the only local emulation is
  LocalStack Pro (commercial licence); the community image does not ship Timestream.
"""

from __future__ import annotations

import os
from typing import Any

from tests.integration import smoke
from tests.integration.engines import Engine, register

PEOPLE = smoke.PEOPLE
SPEC_PEOPLE = smoke.SPEC_PEOPLE
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


# =====================================================================  SurrealDB
def _surreal_native(e: Engine) -> Any:
    from surrealdb import Surreal

    db = Surreal(f"ws://{e.host}:{e.port_}")
    db.signin({"username": e.user_, "password": e.password_})
    db.use(e.env("NAMESPACE", "qb"), e.database_)
    return db


def _seed_surreal(e: Engine) -> None:
    db = _surreal_native(e)
    try:
        db.query("REMOVE TABLE IF EXISTS qbit_people")
        db.query("DEFINE TABLE qbit_people SCHEMALESS")
        for i, n, a in PEOPLE:
            db.query(f"CREATE qbit_people:{i} SET id_num = {i}, name = '{n}', age = {a}")
    finally:
        db.close()


def _surreal_count(e: Engine) -> int:
    db = _surreal_native(e)
    try:
        res = db.query("SELECT count() AS c FROM qbit_people GROUP ALL")
        return int(res[0]["c"]) if res else 0
    finally:
        db.close()


def _surreal_cleanup(e: Engine) -> None:
    db = _surreal_native(e)
    try:
        db.query("REMOVE TABLE IF EXISTS qbit_people")
    finally:
        db.close()


def _kw_surreal(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": f"ws://{e.host}:{e.port_}/rpc",
        "namespace": e.env("NAMESPACE", "qb"),
        "database": e.database_,
        "username": e.user_,
        "password": o.get("password") or e.password_,
    }


register(
    Engine(
        name="surrealdb",
        connector="surrealdb",
        async_connector="async_surrealdb",
        tier="extended",
        family="",
        drivers=("surrealdb",),
        pip="surrealdb",
        port=43800,
        user="root",
        connector_factory=_kw_surreal,
        service="surrealdb",
        container_port=8000,
    )
)
smoke.SMOKE["surrealdb"] = smoke.Smoke(
    seed=_seed_surreal,
    table="qbit_people",
    columns={"name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=BY_AGE,
    writes=[
        "DELETE qbit_people",
        "UPDATE qbit_people SET age = 0",
        "CREATE qbit_people SET name = 'x', age = 1",
        "INSERT INTO qbit_people { name: 'x', age: 1 }",
        "UPSERT qbit_people:9 SET age = 1",
        "REMOVE TABLE qbit_people",
        "DEFINE TABLE hacked SCHEMALESS",
        "SELECT * FROM qbit_people; DELETE qbit_people",
    ],
    check=_count_check(_surreal_count),
    cleanup=_surreal_cleanup,
)


# =====================================================================  Memgraph
def _memgraph_driver(e: Engine) -> Any:
    from neo4j import GraphDatabase

    return GraphDatabase.driver(f"bolt://{e.host}:{e.port_}", auth=None)


def _seed_memgraph(e: Engine) -> None:
    with _memgraph_driver(e) as driver, driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
        for pid, name, age in PEOPLE:
            session.run(
                "CREATE (:Person {id: $id, name: $name, age: $age})",
                id=pid, name=name, age=age,
            ).consume()  # fmt: skip


def _memgraph_count(e: Engine) -> int:
    with _memgraph_driver(e) as driver, driver.session() as session:
        return int(session.run("MATCH (p:Person) RETURN count(p) AS c").single()["c"])


def _memgraph_cleanup(e: Engine) -> None:
    with _memgraph_driver(e) as driver, driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()


def _kw_memgraph(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"uri": f"bolt://{e.host}:{e.port_}"}


register(
    Engine(
        name="memgraph",
        connector="memgraph",
        async_connector="async_memgraph",
        tier="extended",
        family="",
        drivers=("neo4j",),
        pip="neo4j",
        port=43687,
        password="",
        connector_factory=_kw_memgraph,
        service="memgraph",
        container_port=7687,
    )
)
smoke.SMOKE["memgraph"] = smoke.Smoke(
    seed=_seed_memgraph,
    table="Person",
    columns={"name", "age"},
    read="MATCH (p:Person) RETURN p.name AS name, p.age AS age ORDER BY p.age",
    expected=BY_AGE,
    writes=[
        "MATCH (n) DETACH DELETE n",
        "CREATE (n:Hacked {x: 1})",
        "MATCH (p:Person) SET p.age = 0",
        "MERGE (n:Other {id: 1})",
        "MATCH (p:Person) REMOVE p.age",
        "MATCH (p:Person) WITH p DELETE p",
        "CALL mg.load_all() YIELD *",
        "DROP GRAPH",
    ],
    check=_count_check(_memgraph_count),
    cleanup=_memgraph_cleanup,
)


# =====================================================================  ScyllaDB
def _scylla_session(e: Engine) -> Any:
    from cassandra.cluster import Cluster

    cluster = Cluster([e.host], port=e.port_)
    return cluster, cluster.connect()


def _seed_scylla(e: Engine) -> None:
    cluster, session = _scylla_session(e)
    try:
        session.execute(
            f"CREATE KEYSPACE IF NOT EXISTS {e.database_} WITH replication = "
            "{'class': 'SimpleStrategy', 'replication_factor': 1}"
        )
        session.execute(f"DROP TABLE IF EXISTS {e.database_}.qbit_people")
        session.execute(
            f"CREATE TABLE {e.database_}.qbit_people (id int PRIMARY KEY, name text, age int)"
        )
        for pid, name, age in PEOPLE:
            session.execute(
                f"INSERT INTO {e.database_}.qbit_people (id, name, age) VALUES (%s, %s, %s)",
                (pid, name, age),
            )
    finally:
        cluster.shutdown()


def _scylla_count(e: Engine) -> int:
    cluster, session = _scylla_session(e)
    try:
        return int(session.execute(f"SELECT COUNT(*) FROM {e.database_}.qbit_people").one()[0])
    finally:
        cluster.shutdown()


def _kw_scylla(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {"contact_points": [e.host], "port": e.port_, "keyspace": e.database_}


register(
    Engine(
        name="scylladb",
        connector="scylladb",
        tier="extended",
        family="",
        drivers=("cassandra.cluster",),
        pip="cassandra-driver",
        port=43042,
        password="",
        connector_factory=_kw_scylla,
        service="scylladb",
        container_port=9042,
    )
)
smoke.SMOKE["scylladb"] = smoke.Smoke(
    seed=_seed_scylla,
    table="qbit_people",
    columns={"id", "name", "age"},
    read="SELECT name, age FROM qbit_people",
    expected=BY_AGE,
    writes=[
        "DELETE FROM qbit_people WHERE id = 1",
        "UPDATE qbit_people SET age = 0 WHERE id = 1",
        "INSERT INTO qbit_people (id, name, age) VALUES (9, 'x', 1)",
        "TRUNCATE qbit_people",
        "DROP TABLE qbit_people",
        "BEGIN BATCH INSERT INTO qbit_people (id, name, age) VALUES (9, 'x', 1) APPLY BATCH",
    ],
    check=_count_check(_scylla_count),
)


# =====================================================================  DynamoDB (local)
def _dynamo_client(e: Engine) -> Any:
    import boto3

    return boto3.client(
        "dynamodb",
        region_name="us-east-1",
        endpoint_url=f"http://{e.host}:{e.port_}",
        aws_access_key_id="qbit",
        aws_secret_access_key="qbit-secret",
    )


def _seed_dynamo(e: Engine) -> None:
    client = _dynamo_client(e)
    if "qbit_people" in client.list_tables()["TableNames"]:
        client.delete_table(TableName="qbit_people")
    client.create_table(
        TableName="qbit_people",
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "N"}],
        BillingMode="PAY_PER_REQUEST",
    )
    for pid, name, age in PEOPLE:
        client.put_item(
            TableName="qbit_people",
            Item={"id": {"N": str(pid)}, "name": {"S": name}, "age": {"N": str(age)}},
        )


def _dynamo_count(e: Engine) -> int:
    return int(_dynamo_client(e).scan(TableName="qbit_people", Select="COUNT")["Count"])


def _dynamo_cleanup(e: Engine) -> None:
    client = _dynamo_client(e)
    if "qbit_people" in client.list_tables()["TableNames"]:
        client.delete_table(TableName="qbit_people")


def _kw_dynamo(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "region_name": "us-east-1",
        "endpoint_url": f"http://{e.host}:{e.port_}",
        "aws_access_key_id": "qbit",
        "aws_secret_access_key": "qbit-secret",
    }


register(
    Engine(
        name="dynamodb",
        connector="dynamodb",
        tier="extended",
        family="",
        drivers=("boto3",),
        pip="boto3",
        port=43001,
        password="",
        connector_factory=_kw_dynamo,
        service="dynamodb",
        container_port=8000,
        emulated=True,  # amazon/dynamodb-local, not the AWS service
    )
)
smoke.SMOKE["dynamodb"] = smoke.Smoke(
    seed=_seed_dynamo,
    table="qbit_people",
    columns={"id", "name", "age"},
    read='SELECT name, age FROM "qbit_people"',
    expected=BY_AGE,
    writes=[
        'DELETE FROM "qbit_people" WHERE id = 1',
        "UPDATE \"qbit_people\" SET age = 0 WHERE id = 1",
        "INSERT INTO \"qbit_people\" VALUE {'id': 9, 'name': 'x', 'age': 1}",
    ],
    check=_count_check(_dynamo_count),
    cleanup=_dynamo_cleanup,
)


# =====================================================================  Firestore (emulator)
def _firestore_client(e: Engine) -> Any:
    from google.cloud import firestore

    # the client library switches to the emulator (insecure channel, no credentials) on this
    os.environ["FIRESTORE_EMULATOR_HOST"] = f"{e.host}:{e.port_}"
    return firestore.Client(project="qb-it")


def _seed_firestore(e: Engine) -> None:
    client = _firestore_client(e)
    coll = client.collection("qbit_people")
    for doc in coll.stream():
        doc.reference.delete()
    for pid, name, age in PEOPLE:
        coll.document(str(pid)).set({"id": pid, "name": name, "age": age})


def _firestore_count(e: Engine) -> int:
    return len(list(_firestore_client(e).collection("qbit_people").stream()))


def _firestore_cleanup(e: Engine) -> None:
    for doc in _firestore_client(e).collection("qbit_people").stream():
        doc.reference.delete()


def _kw_firestore(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    os.environ["FIRESTORE_EMULATOR_HOST"] = f"{e.host}:{e.port_}"
    return {"project": "qb-it"}


register(
    Engine(
        name="firestore",
        connector="firestore",
        async_connector="async_firestore",
        tier="extended",
        family="",
        drivers=("google.cloud.firestore",),
        pip="google-cloud-firestore",
        port=43080,
        password="",
        connector_factory=_kw_firestore,
        service="firestore",
        container_port=8080,
        emulated=True,  # Firebase/gcloud Firestore emulator, not the Google service
    )
)
smoke.SMOKE["firestore"] = smoke.Smoke(
    seed=_seed_firestore,
    table="qbit_people",
    columns={"id", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=BY_AGE,
    writes=[
        "DELETE FROM qbit_people",
        "UPDATE qbit_people SET age = 0",
        "INSERT INTO qbit_people (id, name, age) VALUES (9, 'x', 1)",
        "DROP TABLE qbit_people",
    ],
    spec=SPEC_PEOPLE,
    check=_count_check(_firestore_count),
    cleanup=_firestore_cleanup,
)


# =====================================================================  Bigtable (emulator)
BT_PROJECT, BT_INSTANCE = "qb-it", "qb-it-instance"


def _bigtable_instance(e: Engine) -> Any:
    from google.cloud import bigtable

    os.environ["BIGTABLE_EMULATOR_HOST"] = f"{e.host}:{e.port_}"
    return bigtable.Client(project=BT_PROJECT, admin=True).instance(BT_INSTANCE)


def _seed_bigtable(e: Engine) -> None:
    from google.cloud.bigtable import column_family

    instance = _bigtable_instance(e)
    table = instance.table("qbit_people")
    if table.exists():
        table.delete()
    table.create(column_families={"cf": column_family.MaxVersionsGCRule(1)})
    for pid, name, age in PEOPLE:
        row = table.direct_row(str(pid).encode())
        row.set_cell("cf", b"name", name.encode())
        row.set_cell("cf", b"age", str(age).encode())  # Bigtable stores bytes
        row.commit()


def _bigtable_count(e: Engine) -> int:
    return len(list(_bigtable_instance(e).table("qbit_people").read_rows()))


def _bigtable_cleanup(e: Engine) -> None:
    table = _bigtable_instance(e).table("qbit_people")
    if table.exists():
        table.delete()


def _kw_bigtable(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    os.environ["BIGTABLE_EMULATOR_HOST"] = f"{e.host}:{e.port_}"
    return {"project_id": BT_PROJECT, "instance_id": BT_INSTANCE, "admin": True}


register(
    Engine(
        name="bigtable",
        connector="bigtable",
        async_connector="async_bigtable",
        tier="extended",
        family="",
        drivers=("google.cloud.bigtable",),
        pip="google-cloud-bigtable",
        port=43086,
        password="",
        connector_factory=_kw_bigtable,
        service="bigtable",
        container_port=8086,
        emulated=True,  # `gcloud beta emulators bigtable`, not the Google service
    )
)
smoke.SMOKE["bigtable"] = smoke.Smoke(
    seed=_seed_bigtable,
    table="qbit_people",
    columns={"row_key", "cf.name", "cf.age"},
    read='SELECT "cf.name" AS name, "cf.age" AS age FROM qbit_people ORDER BY "cf.age"',
    expected=[{"name": r["name"], "age": str(r["age"])} for r in BY_AGE],  # bytes -> text
    writes=[
        "DELETE FROM qbit_people WHERE row_key = '1'",
        "UPDATE qbit_people SET \"cf.age\" = 0",
        "INSERT INTO qbit_people (row_key) VALUES ('9')",
        "DROP TABLE qbit_people",
    ],
    spec={
        "table": "qbit_people",
        "columns": [
            {"column": "cf.name", "alias": "name"},
            {"column": "cf.age", "alias": "age"},
        ],
        "order_by": [{"column": "cf.age", "direction": "asc"}],
        "limit": 10,
    },
    spec_expected=[{"name": r["name"], "age": str(r["age"])} for r in BY_AGE],
    check=_count_check(_bigtable_count),
    cleanup=_bigtable_cleanup,
)


# =====================================================================  Couchbase
def _cb_http(
    e: Engine, port: int, path: str, data: dict[str, Any] | None = None, auth: bool = True
) -> Any:
    """Minimal REST client (urllib) for the cluster-init / bucket / query endpoints."""
    import base64
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(f"http://{e.host}:{port}{path}", data=body)
    if auth:
        token = base64.b64encode(f"{e.user_}:{e.password_}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed http target
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        raise RuntimeError(f"{path}: HTTP {exc.code}: {raw[:300]}") from exc
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _cb_n1ql(e: Engine, statement: str) -> Any:
    out = _cb_http(e, 8093, "/query/service", {"statement": statement})
    if isinstance(out, dict) and out.get("status") != "success":
        raise RuntimeError(f"N1QL failed: {statement[:80]}: {out.get('errors')}")
    return out


def _cb_retry(fn: Any, what: str, tries: int = 60, delay: float = 2.0) -> Any:
    import time

    last: Exception | None = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - service still starting
            last = exc
            time.sleep(delay)
    raise RuntimeError(f"couchbase: {what} did not succeed: {last}")


def _seed_couchbase(e: Engine) -> None:
    import time

    bucket = e.database_
    _cb_retry(lambda: _cb_http(e, 8091, "/pools", auth=False), "REST API")
    # cluster init (idempotent: errors once initialised are tolerated)
    for path, data in (
        ("/pools/default", {"memoryQuota": 256, "indexMemoryQuota": 256}),
        ("/node/controller/setupServices", {"services": "kv,n1ql,index"}),
        ("/settings/web", {"port": 8091, "username": e.user_, "password": e.password_}),
    ):
        try:
            _cb_http(e, 8091, path, data, auth=False)  # fresh node: no credentials yet
        except RuntimeError:
            pass
    with_index = {"storageMode": "plasma"}
    try:
        _cb_http(e, 8091, "/settings/indexes", with_index)
    except RuntimeError:
        _cb_http(e, 8091, "/settings/indexes", {"storageMode": "forestdb"})
    buckets = _cb_http(e, 8091, "/pools/default/buckets")
    if not any(b.get("name") == bucket for b in buckets):
        _cb_http(
            e,
            8091,
            "/pools/default/buckets",
            {"name": bucket, "ramQuota": 128, "bucketType": "couchbase", "flushEnabled": 1},
        )

    def healthy() -> None:
        info = _cb_http(e, 8091, f"/pools/default/buckets/{bucket}")
        if not all(n.get("status") == "healthy" for n in info["nodes"]):
            raise RuntimeError("bucket not healthy")

    _cb_retry(healthy, "bucket health")
    try:
        _cb_http(
            e, 8091, f"/pools/default/buckets/{bucket}/scopes/_default/collections",
            {"name": "qbit_people"},
        )  # fmt: skip
    except RuntimeError as exc:
        if "already exists" not in str(exc):
            raise
    ks = f"default:`{bucket}`.`_default`.`qbit_people`"
    _cb_retry(lambda: _cb_n1ql(e, f"CREATE PRIMARY INDEX IF NOT EXISTS ON {ks}"), "primary index")
    time.sleep(1)
    _cb_retry(lambda: _cb_n1ql(e, f"DELETE FROM {ks}"), "cleanup")
    for pid, name, age in PEOPLE:
        _cb_retry(
            lambda pid=pid, name=name, age=age: _cb_n1ql(
                e,
                f"UPSERT INTO {ks} (KEY, VALUE) VALUES ('p{pid}', "
                f'{{"id": {pid}, "name": "{name}", "age": {age}}})',
            ),
            "insert",
            tries=15,
        )


def _couchbase_count(e: Engine) -> int:
    ks = f"default:`{e.database_}`.`_default`.`qbit_people`"
    out = _cb_n1ql(e, f"SELECT COUNT(*) AS c FROM {ks}")
    return int(out["results"][0]["c"])


def _kw_couchbase(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "connstr": f"couchbase://{e.host}",
        "username": e.user_,
        "password": o.get("password") or e.password_,
        "bucket_name": e.database_,
        "scope_name": "_default",
    }


register(
    Engine(
        name="couchbase",
        connector="couchbase",
        tier="extended",
        family="",
        drivers=("couchbase",),
        pip="couchbase",
        port=43091,
        user="Administrator",
        database="qb_it",
        connector_factory=_kw_couchbase,
        service="couchbase",
        container_port=8091,
    )
)
smoke.SMOKE["couchbase"] = smoke.Smoke(
    seed=_seed_couchbase,
    table="qbit_people",
    columns={"id", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=BY_AGE,
    writes=[
        "DELETE FROM qbit_people",
        "UPDATE qbit_people SET age = 0",
        "INSERT INTO qbit_people (KEY, VALUE) VALUES ('p9', {'name': 'x'})",
        "UPSERT INTO qbit_people (KEY, VALUE) VALUES ('p9', {'name': 'x'})",
        "MERGE INTO qbit_people t USING [{'k': 'p1'}] s ON KEY s.k WHEN MATCHED THEN DELETE",
        "DROP COLLECTION qbit_people",
    ],
    check=_count_check(_couchbase_count),
)


# =====================================================================  Cosmos DB (Linux emulator)
# The emulator's documented, published well-known key (not a secret).
COSMOS_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
)


def _cosmos_client(e: Engine) -> Any:
    from azure.cosmos import CosmosClient

    return CosmosClient(
        f"http://{e.host}:{e.port_}", credential=COSMOS_KEY, connection_verify=False
    )


def _cosmos_container(e: Engine) -> Any:
    return _cosmos_client(e).get_database_client(e.database_).get_container_client(
        "qbit_people"
    )


def _seed_cosmos(e: Engine) -> None:
    import time

    from azure.cosmos import PartitionKey

    client = None
    for _ in range(60):  # the emulator accepts TCP before it serves requests
        try:
            client = _cosmos_client(e)
            client.create_database_if_not_exists(e.database_)
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    assert client is not None
    db = client.create_database_if_not_exists(e.database_)
    try:
        db.delete_container("qbit_people")
    except Exception:  # noqa: BLE001, S110 - first run
        pass
    container = db.create_container("qbit_people", partition_key=PartitionKey(path="/id"))
    for pid, name, age in PEOPLE:
        container.upsert_item({"id": str(pid), "name": name, "age": age})


def _cosmos_count(e: Engine) -> int:
    items = _cosmos_container(e).query_items(
        "SELECT VALUE COUNT(1) FROM c", enable_cross_partition_query=True
    )
    return int(next(iter(items)))


def _cosmos_cleanup(e: Engine) -> None:
    try:
        _cosmos_client(e).get_database_client(e.database_).delete_container("qbit_people")
    except Exception:  # noqa: BLE001, S110
        pass


def _kw_cosmos(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": f"http://{e.host}:{e.port_}",
        "key": COSMOS_KEY,
        "database": e.database_,
        "connection_verify": False,
    }


register(
    Engine(
        name="cosmosdb",
        connector="cosmosdb",
        async_connector="async_cosmosdb",
        tier="extended",
        family="",
        drivers=("azure.cosmos",),
        pip="azure-cosmos",
        port=43081,
        password="",
        connector_factory=_kw_cosmos,
        service="cosmosdb",
        container_port=8081,
        emulated=True,  # Azure Cosmos DB Linux (vNext) emulator, not the Azure service
    )
)
smoke.SMOKE["cosmosdb"] = smoke.Smoke(
    seed=_seed_cosmos,
    table="qbit_people",
    columns={"id", "name", "age"},
    read="SELECT c.name, c.age FROM qbit_people c ORDER BY c.age",
    expected=BY_AGE,
    writes=[
        "DELETE FROM qbit_people",
        "UPDATE qbit_people SET age = 0",
        "INSERT INTO qbit_people (id) VALUES ('9')",
    ],
    check=_count_check(_cosmos_count),
    cleanup=_cosmos_cleanup,
)


# =====================================================================  Spanner (emulator)
# Spanner is real SQL (GoogleSQL) and the connector compiles QuerySpecs, so the smoke battery
# exercises both the native read and the compiled spec. DDL goes through the admin API, DML
# through a transaction (the emulator has no other entry point).
SP_PROJECT, SP_INSTANCE, SP_DATABASE = "qb-it", "qb-it-instance", "qb_it"


def _spanner_database(e: Engine) -> Any:
    from google.cloud import spanner

    os.environ["SPANNER_EMULATOR_HOST"] = f"{e.host}:{e.port_}"
    client = spanner.Client(project=SP_PROJECT)
    instance = client.instance(
        SP_INSTANCE,
        configuration_name=f"projects/{SP_PROJECT}/instanceConfigs/emulator-config",
        display_name="qbit",
        node_count=1,
    )
    if not instance.exists():
        instance.create().result(120)
    database = instance.database(SP_DATABASE)
    if not database.exists():
        database.create().result(120)
    return database


def _seed_spanner(e: Engine) -> None:
    database = _spanner_database(e)
    database.update_ddl(["DROP TABLE IF EXISTS qbit_people"]).result(120)
    database.update_ddl(
        [
            "CREATE TABLE qbit_people (id INT64 NOT NULL, name STRING(100), age INT64) "
            "PRIMARY KEY (id)"
        ]
    ).result(120)
    with database.batch() as batch:
        batch.insert(
            table="qbit_people",
            columns=("id", "name", "age"),
            values=[(i, n, a) for i, n, a in PEOPLE],
        )


def _spanner_count(e: Engine) -> int:
    with _spanner_database(e).snapshot() as snap:
        return int(list(snap.execute_sql("SELECT COUNT(*) FROM qbit_people"))[0][0])


def _spanner_cleanup(e: Engine) -> None:
    _spanner_database(e).update_ddl(["DROP TABLE IF EXISTS qbit_people"]).result(120)


def _kw_spanner(e: Engine, o: dict[str, Any]) -> dict[str, Any]:
    os.environ["SPANNER_EMULATOR_HOST"] = f"{e.host}:{e.port_}"
    return {"instance_id": SP_INSTANCE, "database_id": SP_DATABASE, "project": SP_PROJECT}


register(
    Engine(
        name="spanner",
        connector="spanner",
        tier="extended",
        family="",
        drivers=("google.cloud.spanner_dbapi",),
        pip="google-cloud-spanner",
        port=43010,
        password="",
        connector_factory=_kw_spanner,
        service="spanner",
        container_port=9010,
        emulated=True,  # Cloud Spanner emulator, not the Google service
    )
)
smoke.SMOKE["spanner"] = smoke.Smoke(
    seed=_seed_spanner,
    table="qbit_people",
    columns={"id", "name", "age"},
    read="SELECT name, age FROM qbit_people ORDER BY age",
    expected=BY_AGE,
    writes=smoke.SQL_WRITES,
    spec=SPEC_PEOPLE,
    check=_count_check(_spanner_count),
    cleanup=_spanner_cleanup,
)
