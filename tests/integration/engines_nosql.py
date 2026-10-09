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
