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

from tests.integration.engines import Engine, Limitation

PEOPLE = [(1, "alice", 30), (2, "bob", 45), (3, "carol", 28)]
BY_AGE = [
    {"name": "carol", "age": 28},
    {"name": "alice", "age": 30},
    {"name": "bob", "age": 45},
]


def names_of(rows: list[dict[str, Any]]) -> list[Any]:
    """Default extractor: the ``name`` column of each row."""
    return [r.get("name") for r in rows]


@dataclass
class Check:
    """One native read and what it must return (a NATIVE-core category check)."""

    statement: str
    expected: list[Any]
    ordered: bool = False  # compare in order (ordering / pagination) or as a set
    extract: Callable[[list[dict[str, Any]]], list[Any]] = names_of
    expect_count: int | None = None  # compare only len(rows), e.g. LIMIT without ORDER BY
    subset: bool = False  # extracted values must CONTAIN every expected one (nested replies)
    validate_ast: bool = False  # native languages are not SQL: skip the SQL AST validator


#: Values that must round-trip as DATA: quotes, SQL/regex metacharacters, backslash,
#: JSON-looking text, non-ASCII, an injection-looking string. Stored in ``qbit_special``.
SPECIAL_VALUES = [
    "O'Brien",
    'say "hi"',
    "100% _ \\ done",
    '{"a": 1, "b": [2]}',
    "Zoë Ünï ☃",
    "'; DROP TABLE qbit_people; --",
    ".* [a-z]+ (x|y)$",
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
    #: NATIVE-core checks by category: read_filtered, ordering, pagination, value_safety.
    #: A category with neither checks nor a limitation is reported as UNTESTED (skip), which
    #: keeps the engine below the ``certified`` tier.
    checks: dict[str, list[Check]] = field(default_factory=dict)
    #: seeds the ``qbit_special`` object used by the value_safety checks
    extra_seed: Callable[[Engine], None] | None = None
    #: native statements that are invalid; each must surface as a ConnectorError-family error
    bad_queries: list[str] = field(default_factory=list)
    #: category -> Limitation (with a probe through the NATIVE driver where possible)
    limitations: dict[str, Limitation] = field(default_factory=dict)


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
    "TRUNCATE TABLE qbit_people",
    "ALTER TABLE qbit_people ADD COLUMN x INT",
    "CREATE TABLE qbit_new (id INT)",
    "SELECT 1; DROP TABLE qbit_people",
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


# ------------------------------------------------------- special values (value_safety)
def _seed_es_special(e: Engine, flavor: str) -> None:
    mapping = {"properties": {"id": {"type": "integer"}, "name": {"type": "keyword"}}}
    if flavor == "elasticsearch":
        from elasticsearch import Elasticsearch

        client = Elasticsearch(f"http://{e.host}:{e.port_}")
    else:
        from opensearchpy import OpenSearch

        client = OpenSearch(hosts=[{"host": e.host, "port": e.port_}])
    if client.indices.exists(index="qbit_special"):
        client.indices.delete(index="qbit_special")
    if flavor == "elasticsearch":
        client.indices.create(index="qbit_special", mappings=mapping)
    else:
        client.indices.create(index="qbit_special", body={"mappings": mapping})
    for i, value in enumerate(SPECIAL_VALUES, 1):
        body = {"id": i, "name": value}
        if flavor == "elasticsearch":
            client.index(index="qbit_special", id=i, document=body)
        else:
            client.index(index="qbit_special", id=i, body=body)
    client.indices.refresh(index="qbit_special")


def _seed_mongo_special(e: Engine) -> None:
    import pymongo

    client = pymongo.MongoClient(f"mongodb://{e.host}:{e.port_}")
    coll = client[e.database_]["qbit_special"]
    coll.drop()
    coll.insert_many([{"id": i, "name": v} for i, v in enumerate(SPECIAL_VALUES, 1)])
    client.close()


def _seed_redis_special(e: Engine) -> None:
    import redis

    r = redis.Redis(host=e.host, port=e.port_)
    for i, value in enumerate(SPECIAL_VALUES, 1):
        # a prefix outside the qbit_people index (PREFIX "qbit:") so counts stay at 3
        r.hset(f"qbitspecial:{i}", mapping={"name": value})
    r.close()


def _seed_neo4j_special(e: Engine) -> None:
    from neo4j import GraphDatabase

    with (
        GraphDatabase.driver(
            f"bolt://{e.host}:{e.port_}", auth=(e.user_, e.password_)
        ) as driver,
        driver.session() as session,
    ):
        session.run("MATCH (n:Special) DETACH DELETE n").consume()
        for i, value in enumerate(SPECIAL_VALUES, 1):
            session.run(
                "CREATE (:Special {id: $id, name: $name})", id=i, name=value
            ).consume()


def _seed_cassandra_special(e: Engine) -> None:
    from cassandra.cluster import Cluster

    cluster = Cluster([e.host], port=e.port_)
    session = cluster.connect()
    session.execute(f"DROP TABLE IF EXISTS {e.database_}.qbit_special")
    session.execute(
        f"CREATE TABLE {e.database_}.qbit_special (id int PRIMARY KEY, name text)"
    )
    for i, value in enumerate(SPECIAL_VALUES, 1):
        session.execute(
            f"INSERT INTO {e.database_}.qbit_special (id, name) VALUES (%s, %s)",
            (i, value),
        )
    cluster.shutdown()


def _sql_lit(value: str) -> str:
    """SQL string literal (single quotes doubled)."""
    return "'" + value.replace("'", "''") + "'"


def _cypher_lit(value: str) -> str:
    """Cypher string literal (JSON string syntax is valid Cypher)."""
    import json

    return json.dumps(value, ensure_ascii=False)


def _special_sql(table: str) -> list[Check]:
    return [
        Check(f"SELECT name FROM {table} WHERE name = {_sql_lit(v)}", [v])
        for v in SPECIAL_VALUES
    ]


def _leaves(obj: Any) -> list[str]:
    """Every string/bytes leaf of a (possibly nested) reply, in order."""
    out: list[str] = []
    if isinstance(obj, bytes):
        out.append(obj.decode("utf-8", "replace"))
    elif isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += _leaves(k) + _leaves(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            out += _leaves(v)
    elif obj is not None:
        out.append(str(obj))
    return out


def _redis_names(rows: list[dict[str, Any]]) -> list[Any]:
    wanted = {n for _, n, _ in PEOPLE}
    return [leaf for leaf in _leaves(rows) if leaf in wanted]


def _redis_leaves(rows: list[dict[str, Any]]) -> list[Any]:
    return _leaves(rows)


def _redis_probe_sql(e: Engine) -> bool:
    """True when Redis ANSWERED a SQL statement (it must not: no SQL layer)."""
    import redis

    r = redis.Redis(host=e.host, port=e.port_)
    try:
        r.execute_command("SELECT name FROM qbit_people")
        return True
    finally:
        r.close()


def _cassandra_probe_order_by(e: Engine) -> bool:
    """True when Cassandra ACCEPTED ORDER BY on a non-clustering column (it must not)."""
    from cassandra.cluster import Cluster

    cluster = Cluster([e.host], port=e.port_)
    try:
        session = cluster.connect()
        list(
            session.execute(
                f"SELECT name FROM {e.database_}.qbit_people ORDER BY age"
            )
        )
        return True
    finally:
        cluster.shutdown()


_ES_CHECKS: dict[str, list[Check]] = {
    "read_filtered": [
        Check("SELECT name FROM qbit_people WHERE age > 29", ["alice", "bob"]),
        Check(
            "SELECT name FROM qbit_people WHERE age >= 28 AND age < 45",
            ["alice", "carol"],
        ),
    ],
    "ordering": [
        Check(
            "SELECT name FROM qbit_people ORDER BY age DESC",
            ["bob", "alice", "carol"],
            ordered=True,
        )
    ],
    "pagination": [
        Check(
            "SELECT name FROM qbit_people ORDER BY age LIMIT 2",
            ["carol", "alice"],
            ordered=True,
        ),
        Check("SELECT name FROM qbit_people LIMIT 1", [], expect_count=1),
    ],
    "value_safety": _special_sql("qbit_special"),
}
_ES_BAD = ["SELECT name FROM qbit_no_such_index", "SELEC name FROM qbit_people"]


def _es_checks() -> dict[str, list[Check]]:
    return {k: list(v) for k, v in _ES_CHECKS.items()}


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
        checks=_es_checks(),
        extra_seed=lambda e: _seed_es_special(e, "elasticsearch"),
        bad_queries=_ES_BAD,
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
        checks=_es_checks(),
        extra_seed=lambda e: _seed_es_special(e, "opensearch"),
        bad_queries=_ES_BAD,
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
        checks=_es_checks(),
        extra_seed=_seed_mongo_special,
        bad_queries=["SELEC name FROM qbit_people", "SELECT FROM WHERE"],
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
        writes=[
            "FLUSHALL",
            "FT.DROPINDEX qbit_people",
            "SET k v",
            "DEL qbit:1",
            "HSET qbit:1 age 0",
            "EXPIRE qbit:1 1",
            "RENAME qbit:1 qbit:9",
            "EVAL \"return redis.call('DEL','qbit:1')\" 0",
        ],
        check=_redis_check,
        checks={
            "read_filtered": [
                Check(
                    'FT.SEARCH qbit_people "@age:[29 +inf]"',
                    ["alice", "bob"],
                    extract=_redis_names,
                )
            ],
            "ordering": [
                Check(
                    "FT.SEARCH qbit_people * SORTBY age DESC",
                    ["bob", "alice", "carol"],
                    ordered=True,
                    extract=_redis_names,
                )
            ],
            "pagination": [
                Check(
                    "FT.SEARCH qbit_people * SORTBY age ASC LIMIT 0 2",
                    ["carol", "alice"],
                    ordered=True,
                    extract=_redis_names,
                ),
                Check(
                    "FT.SEARCH qbit_people * SORTBY age ASC LIMIT 1 1",
                    ["alice"],
                    ordered=True,
                    extract=_redis_names,
                ),
            ],
            "value_safety": [
                Check(
                    f"HGET qbitspecial:{i} name",
                    [v],
                    extract=_redis_leaves,
                    subset=True,
                )
                for i, v in enumerate(SPECIAL_VALUES, 1)
            ],
        },
        extra_seed=_seed_redis_special,
        bad_queries=["FT.SEARCH qbit_no_such_index *", "FT.SEARCH qbit_people"],
        limitations={
            "spec_compile": Limitation(
                "Redis has no SQL layer: queries are native FT.SEARCH commands",
                probe=_redis_probe_sql,
            )
        },
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
            "MATCH (p:Person) REMOVE p.age",
            "MATCH (p:Person) DELETE p",
            "CREATE INDEX qbit_ix IF NOT EXISTS FOR (p:Person) ON (p.name)",
        ],
        check=_neo4j_check,
        checks={
            "read_filtered": [
                Check(
                    "MATCH (p:Person) WHERE p.age > 29 RETURN p.name AS name",
                    ["alice", "bob"],
                )
            ],
            "ordering": [
                Check(
                    "MATCH (p:Person) RETURN p.name AS name ORDER BY p.age DESC",
                    ["bob", "alice", "carol"],
                    ordered=True,
                )
            ],
            "pagination": [
                Check(
                    "MATCH (p:Person) RETURN p.name AS name ORDER BY p.age SKIP 1 LIMIT 1",
                    ["alice"],
                    ordered=True,
                ),
                Check(
                    "MATCH (p:Person) RETURN p.name AS name ORDER BY p.age LIMIT 2",
                    ["carol", "alice"],
                    ordered=True,
                ),
            ],
            "value_safety": [
                Check(
                    "MATCH (s:Special) WHERE s.name = "
                    f"{_cypher_lit(v)} RETURN s.name AS name",
                    [v],
                )
                for v in SPECIAL_VALUES
            ],
        },
        extra_seed=_seed_neo4j_special,
        bad_queries=["MATCH (n RETURN n", "MATCH (n:Person) RETURN nosuchfn(n)"],
        limitations={
            "spec_compile": Limitation("Neo4j speaks Cypher: no SQL QuerySpec compile path")
        },
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
            "ALTER TABLE qbit_people ADD x int",
            "CREATE TABLE qbit_new (id int PRIMARY KEY)",
        ],
        check=_cassandra_check,
        checks={
            "read_filtered": [
                Check(
                    "SELECT name FROM qbit_people WHERE age > 29 ALLOW FILTERING",
                    ["alice", "bob"],
                ),
                Check("SELECT name FROM qbit_people WHERE id = 3", ["carol"]),
            ],
            "pagination": [
                Check("SELECT name FROM qbit_people LIMIT 2", [], expect_count=2)
            ],
            "value_safety": [
                Check(f"SELECT name FROM qbit_special WHERE id = {i}", [v])
                for i, v in enumerate(SPECIAL_VALUES, 1)
            ],
        },
        extra_seed=_seed_cassandra_special,
        bad_queries=["SELECT name FROM qbit_no_such_table", "SELEC name FROM qbit_people"],
        limitations={
            "ordering": Limitation(
                "Cassandra only orders by clustering columns within a partition",
                probe=_cassandra_probe_order_by,
            ),
            "spec_compile": Limitation("CQL has no QuerySpec compile path here"),
        },
    ),
}
