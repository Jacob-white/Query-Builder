"""
Smoke batteries for NON-SQL engines (document, key-value, search, graph, wide
column). They share the standard "people" dataset, seeded through each vendor's
native client, and check what the connector claims to do: connect, report health,
introspect the seeded object, run a native read through the real connector class,
and refuse writes sent through the raw path.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tests.integration.engines import Engine

PEOPLE = [(1, "alice", 30), (2, "bob", 45), (3, "carol", 28)]
BY_AGE = [
    {"name": "carol", "age": 28},
    {"name": "alice", "age": 30},
    {"name": "bob", "age": 45},
]


@dataclass
class Smoke:
    seed: Callable[[Engine], None]
    table: str  # name expected in introspection
    columns: set[str]  # subset of columns expected in introspection
    read: str  # native read statement sent through connector.execute(sql=...)
    expected: list[dict[str, Any]]  # rows it must return (order-insensitive)
    writes: list[str]  # raw statements that must be rejected
    #: QuerySpec the connector compiles itself (None = engine has no SQL compiler)
    spec: dict[str, Any] | None = None
    spec_expected: list[dict[str, Any]] = field(default_factory=lambda: BY_AGE)
    check: Callable[[Engine], list[dict[str, Any]]] | None = None  # native re-read
    cleanup: Callable[[Engine], None] | None = None
    key: str = "name"  # row key used to order for comparison
    #: test name -> reason, for defects found and REPORTED but not fixed here.
    #: They run as strict xfails, so they flip to failures once fixed and never
    #: count towards a `certified` tier.
    known_issues: dict[str, str] = field(default_factory=dict)


SPEC_PEOPLE = {
    "table": "qbit_people",
    "columns": ["name", "age"],
    "order_by": [{"column": "age", "direction": "asc"}],
    "limit": 10,
}
SQL_WRITES = [
    "DELETE FROM qbit_people",
    "UPDATE qbit_people SET age = 0",
    "INSERT INTO qbit_people (id, name, age) VALUES (9, 'x', 1)",
    "DROP TABLE qbit_people",
]


# ------------------------------------------------------------------- seeders
def _seed_es(e: Engine, flavor: str) -> None:
    if flavor == "elasticsearch":
        from elasticsearch import Elasticsearch

        client = Elasticsearch(f"http://{e.host}:{e.port_}")
    else:
        from opensearchpy import OpenSearch

        client = OpenSearch(hosts=[{"host": e.host, "port": e.port_}])
    if client.indices.exists(index="qbit_people"):
        client.indices.delete(index="qbit_people")
    for pid, name, age in PEOPLE:
        body = {"id": pid, "name": name, "age": age}
        if flavor == "elasticsearch":
            client.index(index="qbit_people", id=pid, document=body)
        else:
            client.index(index="qbit_people", id=pid, body=body)
    client.indices.refresh(index="qbit_people")


def _seed_mongo(e: Engine) -> None:
    import pymongo

    client = pymongo.MongoClient(f"mongodb://{e.host}:{e.port_}")
    client.drop_database(e.database_)
    client[e.database_]["qbit_people"].insert_many(
        [{"id": i, "name": n, "age": a} for i, n, a in PEOPLE]
    )
    client.close()


def _seed_redis(e: Engine) -> None:
    import redis

    r = redis.Redis(host=e.host, port=e.port_)
    r.flushall()
    r.execute_command(
        "FT.CREATE", "qbit_people", "ON", "HASH", "PREFIX", "1", "qbit:",
        "SCHEMA", "name", "TEXT", "SORTABLE", "age", "NUMERIC", "SORTABLE",
    )  # fmt: skip
    for pid, name, age in PEOPLE:
        r.hset(f"qbit:{pid}", mapping={"name": name, "age": age})
    time.sleep(0.5)  # let the index catch up
    r.close()


def _seed_neo4j(e: Engine) -> None:
    from neo4j import GraphDatabase

    with (
        GraphDatabase.driver(
            f"bolt://{e.host}:{e.port_}", auth=(e.user_, e.password_)
        ) as driver,
        driver.session() as session,
    ):
        session.run("MATCH (n) DETACH DELETE n").consume()
        for pid, name, age in PEOPLE:
            session.run(
                "CREATE (:Person {id: $id, name: $name, age: $age})",
                id=pid, name=name, age=age,
            ).consume()  # fmt: skip


def _seed_cassandra(e: Engine) -> None:
    from cassandra.cluster import Cluster

    cluster = Cluster([e.host], port=e.port_)
    session = cluster.connect()
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
    cluster.shutdown()


# -------------------------------------------------------------- native re-reads
def _es_count(flavor: str) -> Callable[[Engine], list[dict[str, Any]]]:
    def check(e: Engine) -> list[dict[str, Any]]:
        if flavor == "elasticsearch":
            from elasticsearch import Elasticsearch

            client = Elasticsearch(f"http://{e.host}:{e.port_}")
        else:
            from opensearchpy import OpenSearch

            client = OpenSearch(hosts=[{"host": e.host, "port": e.port_}])
        client.indices.refresh(index="qbit_people")
        return [{"count": client.count(index="qbit_people")["count"]}]

    return check


def _mongo_check(e: Engine) -> list[dict[str, Any]]:
    import pymongo

    client = pymongo.MongoClient(f"mongodb://{e.host}:{e.port_}")
    return [{"count": client[e.database_]["qbit_people"].count_documents({})}]


def _redis_check(e: Engine) -> list[dict[str, Any]]:
    import redis

    r = redis.Redis(host=e.host, port=e.port_)
    return [{"count": len(r.keys("qbit:*"))}]


def _neo4j_check(e: Engine) -> list[dict[str, Any]]:
    from neo4j import GraphDatabase

    with GraphDatabase.driver(
        f"bolt://{e.host}:{e.port_}", auth=(e.user_, e.password_)
    ) as driver:
        records, _, _ = driver.execute_query(
            "MATCH (p:Person) RETURN count(p) AS count"
        )
        return [{"count": records[0]["count"]}]


def _cassandra_check(e: Engine) -> list[dict[str, Any]]:
    from cassandra.cluster import Cluster

    cluster = Cluster([e.host], port=e.port_)
    session = cluster.connect()
    count = session.execute(f"SELECT COUNT(*) FROM {e.database_}.qbit_people").one()[0]
    cluster.shutdown()
    return [{"count": count}]


SMOKE: dict[str, Smoke] = {
    "elasticsearch": Smoke(
        seed=lambda e: _seed_es(e, "elasticsearch"),
        table="qbit_people",
        columns={"name", "age"},
        read="SELECT name, age FROM qbit_people ORDER BY age",
        expected=BY_AGE,
        writes=SQL_WRITES,
        spec=SPEC_PEOPLE,
        check=_es_count("elasticsearch"),
    ),
    "opensearch": Smoke(
        seed=lambda e: _seed_es(e, "opensearch"),
        table="qbit_people",
        columns={"name", "age"},
        read="SELECT name, age FROM qbit_people ORDER BY age",
        expected=BY_AGE,
        writes=SQL_WRITES,
        spec=SPEC_PEOPLE,
        check=_es_count("opensearch"),
    ),
    "mongodb": Smoke(
        seed=_seed_mongo,
        table="qbit_people",
        columns={"name", "age"},
        read="SELECT name, age FROM qbit_people ORDER BY age",
        expected=BY_AGE,
        writes=SQL_WRITES,
        spec=SPEC_PEOPLE,
        check=_mongo_check,
        known_issues={
            "test_query_spec_compiled_and_executed": (
                "pymongosql rejects the compiler's table aliases and double-quoted "
                "identifiers and SILENTLY returns no rows for the compiled SQL"
            )
        },
    ),
    "redis": Smoke(
        seed=_seed_redis,
        table="qbit_people",
        columns={"name", "age"},
        read="FT.SEARCH qbit_people *",
        expected=[],  # shape checked separately: RediSearch replies are nested
        writes=["FLUSHALL", "FT.DROPINDEX qbit_people", "SET k v", "DEL qbit:1"],
        check=_redis_check,
    ),
    "neo4j": Smoke(
        seed=_seed_neo4j,
        table="Person",
        columns={"name", "age"},
        read="MATCH (p:Person) RETURN p.name AS name, p.age AS age ORDER BY p.age",
        expected=BY_AGE,
        writes=[
            "MATCH (n) DETACH DELETE n",
            "CREATE (n:Hacked {x: 1})",
            "MATCH (p:Person) SET p.age = 0",
            "MERGE (n:Other {id: 1})",
        ],
        check=_neo4j_check,
    ),
    "cassandra": Smoke(
        seed=_seed_cassandra,
        table="qbit_people",
        columns={"id", "name", "age"},
        read="SELECT name, age FROM qbit_people",
        expected=[r for r in BY_AGE],
        writes=[
            "DELETE FROM qbit_people WHERE id = 1",
            "UPDATE qbit_people SET age = 0 WHERE id = 1",
            "INSERT INTO qbit_people (id, name, age) VALUES (9, 'x', 1)",
            "TRUNCATE qbit_people",
            "DROP TABLE qbit_people",
        ],
        check=_cassandra_check,
    ),
}
