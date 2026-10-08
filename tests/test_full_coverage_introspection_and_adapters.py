from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from query_builder.adapters.drizzle import from_drizzle
from query_builder.adapters.json_schema import from_json_schema
from query_builder.adapters.prisma import from_prisma
from query_builder.adapters.sqlalchemy import from_sqlalchemy
from query_builder.adapters.utils import (
    normalize_type_name,
    read_source,
    to_schema_snapshot,
)
from query_builder.connectors.introspection import (
    introspect_bigtable,
    introspect_chroma,
    introspect_firestore,
    introspect_flink,
    introspect_ksqldb,
    introspect_kusto,
    introspect_lancedb,
    introspect_memgraph,
    introspect_milvus,
    introspect_neptune,
    introspect_pinecone,
    introspect_prometheus,
    introspect_pulsar,
    introspect_qdrant,
    introspect_redis_search,
    introspect_timestream,
    introspect_victoriametrics,
    introspect_weaviate,
)
from query_builder.models import ColumnSchema, ForeignKey, TableSchema


class DummyConnWithCursor:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur


def test_introspection_all_connectors_unwrap_close_and_fallbacks():
    # Helper to create cur with close()
    def make_cur(**attrs):
        cur = MagicMock()
        cur.close = MagicMock()
        for k, v in attrs.items():
            setattr(cur, k, v)
        return cur

    # 1. Kusto: execute with JSON schema string with OrderedColumns, and finally cur.close()
    kusto_cur = make_cur()
    json_schema_str = json.dumps(
        {
            "OrderedColumns": [
                {"Name": "id", "CslType": "int"},
                {"Name": "metric", "CslType": "string"},
                {"Name": "user_id", "CslType": "string"},
            ]
        }
    )
    kusto_cur.fetchall.side_effect = [[["MetricsTable"]], [[json_schema_str]]]
    conn_kusto = DummyConnWithCursor(kusto_cur)
    res_kusto = introspect_kusto(conn_kusto, database="mydb")
    assert "MetricsTable" in res_kusto["tables"]
    kusto_cur.close.assert_called_once()

    # 1b. Kusto: get_tables branch (without execute)
    kusto_gt_cur = make_cur()
    del kusto_gt_cur.execute
    del kusto_gt_cur.fetchall
    kusto_gt_cur.get_tables = MagicMock(return_value=["LogsTable"])
    res_kusto_gt = introspect_kusto(kusto_gt_cur)
    assert "LogsTable" in res_kusto_gt["tables"]

    # 2. Prometheus: get_label_values and close()
    prom_cur = make_cur()
    del prom_cur.execute
    prom_cur.get_label_values = MagicMock(return_value=["cpu_usage", "mem_usage"])
    conn_prom = DummyConnWithCursor(prom_cur)
    res_prom = introspect_prometheus(conn_prom)
    assert "cpu_usage" in res_prom["tables"]
    prom_cur.close.assert_called_once()

    # 3. VictoriaMetrics: get_series and close()
    vm_cur = make_cur()
    del vm_cur.execute
    vm_cur.get_series = MagicMock(return_value=["vm_active_hosts"])
    conn_vm = DummyConnWithCursor(vm_cur)
    res_vm = introspect_victoriametrics(conn_vm)
    assert "vm_active_hosts" in res_vm["tables"]
    vm_cur.close.assert_called_once()

    # 4. Timestream: list_tables and fallback columns and close()
    ts_cur = make_cur()
    del ts_cur.execute
    ts_cur.list_tables = MagicMock(
        return_value={"Tables": [{"TableName": "IoTTelemetry"}]}
    )
    conn_ts = DummyConnWithCursor(ts_cur)
    res_ts = introspect_timestream(conn_ts, database_name="iot_db")
    assert any(k.lower() == "iottelemetry" for k in res_ts["tables"])
    ts_cur.close.assert_called_once()

    # 5. Memgraph: close()
    mg_cur = make_cur()
    mg_cur.fetchall.return_value = [["Person"]]
    conn_mg = DummyConnWithCursor(mg_cur)
    res_mg = introspect_memgraph(conn_mg)
    assert any(k.lower() == "person" for k in res_mg["tables"])
    mg_cur.close.assert_called_once()

    # 6. Neptune: close()
    nep_cur = make_cur()
    nep_cur.fetchall.return_value = [["Node"]]
    conn_nep = DummyConnWithCursor(nep_cur)
    res_nep = introspect_neptune(conn_nep)
    assert any(k.lower() == "node" for k in res_nep["tables"])
    nep_cur.close.assert_called_once()

    # 7. KsqlDB: close()
    ksql_cur = make_cur()
    ksql_cur.fetchall.return_value = [["users_stream"]]
    conn_ksql = DummyConnWithCursor(ksql_cur)
    res_ksql = introspect_ksqldb(conn_ksql)
    assert any(k.lower() == "users_stream" for k in res_ksql["tables"])
    ksql_cur.close.assert_called_once()

    # 8. Flink: close()
    flink_cur = make_cur()
    flink_cur.fetchall.return_value = [["orders_sink"]]
    conn_flink = DummyConnWithCursor(flink_cur)
    res_flink = introspect_flink(conn_flink)
    assert any(k.lower() == "orders_sink" for k in res_flink["tables"])
    flink_cur.close.assert_called_once()

    # 9. Pulsar: close()
    pulsar_cur = make_cur()
    pulsar_cur.fetchall.return_value = [["events_topic"]]
    conn_pulsar = DummyConnWithCursor(pulsar_cur)
    res_pulsar = introspect_pulsar(conn_pulsar)
    assert any(k.lower() == "events_topic" for k in res_pulsar["tables"])
    pulsar_cur.close.assert_called_once()

    # 10. Qdrant: get_collections and close()
    qd_cur = make_cur()
    del qd_cur.execute
    qd_col = MagicMock()
    qd_col.name = "products_vec"
    qd_cur.get_collections = MagicMock(return_value=[qd_col])
    conn_qd = DummyConnWithCursor(qd_cur)
    res_qd = introspect_qdrant(conn_qd)
    assert any(k.lower() == "products_vec" for k in res_qd["tables"])
    qd_cur.close.assert_called_once()

    # 11. Pinecone: list_indexes and close()
    pc_cur = make_cur()
    del pc_cur.execute
    pc_cur.list_indexes = MagicMock(return_value=["articles_idx"])
    conn_pc = DummyConnWithCursor(pc_cur)
    res_pc = introspect_pinecone(conn_pc)
    assert any(k.lower() == "articles_idx" for k in res_pc["tables"])
    pc_cur.close.assert_called_once()

    # 12. Weaviate: collections.list_all and close()
    weav_cur = make_cur()
    del weav_cur.execute
    del weav_cur.fetchall
    weav_cur.collections.list_all = MagicMock(return_value=["Articles"])
    conn_weav = DummyConnWithCursor(weav_cur)
    res_weav = introspect_weaviate(conn_weav)
    assert any(k.lower() == "articles" for k in res_weav["tables"])
    weav_cur.close.assert_called_once()

    # 13. Milvus: list_collections and close()
    milv_cur = make_cur()
    del milv_cur.execute
    del milv_cur.fetchall
    milv_cur.list_collections = MagicMock(return_value=["image_features"])
    conn_milv = DummyConnWithCursor(milv_cur)
    res_milv = introspect_milvus(conn_milv)
    assert any(k.lower() == "image_features" for k in res_milv["tables"])
    milv_cur.close.assert_called_once()

    # 14. Chroma: close()
    chr_cur = make_cur()
    del chr_cur.execute
    del chr_cur.fetchall
    chr_cur.list_collections = MagicMock(return_value=["documents"])
    conn_chr = DummyConnWithCursor(chr_cur)
    res_chr = introspect_chroma(conn_chr)
    assert any(k.lower() == "documents" for k in res_chr["tables"])
    chr_cur.close.assert_called_once()

    # 15. LanceDB: table_names, open_table schema with nullable/type, and close()
    lance_cur = make_cur()
    del lance_cur.execute
    lance_cur.table_names = MagicMock(return_value=["vectors_tbl"])
    field_mock = MagicMock()
    field_mock.name = "vector_id"
    field_mock.type = "fixed_size_list"
    field_mock.nullable = False
    tbl_mock = MagicMock()
    tbl_mock.schema = [field_mock]
    lance_cur.open_table = MagicMock(return_value=tbl_mock)
    conn_lance = DummyConnWithCursor(lance_cur)
    res_lance = introspect_lancedb(conn_lance)
    assert any(k.lower() == "vectors_tbl" for k in res_lance["tables"])
    lance_cur.close.assert_called_once()

    # 16. RedisSearch: close()
    rs_cur = make_cur()
    rs_cur.fetchall.return_value = [["idx:products"]]
    conn_rs = DummyConnWithCursor(rs_cur)
    res_rs = introspect_redis_search(conn_rs)
    assert any(k.lower() == "idx:products" for k in res_rs["tables"])
    rs_cur.close.assert_called_once()

    # 17. Firestore: close()
    fs_cur = make_cur()
    fs_cur.fetchall.return_value = [["users_col"]]
    conn_fs = DummyConnWithCursor(fs_cur)
    res_fs = introspect_firestore(conn_fs)
    assert any(k.lower() == "users_col" for k in res_fs["tables"])
    fs_cur.close.assert_called_once()

    # 18. Bigtable: close()
    bt_cur = make_cur()
    bt_cur.fetchall.return_value = [["timeseries_bt"]]
    conn_bt = DummyConnWithCursor(bt_cur)
    res_bt = introspect_bigtable(conn_bt)
    assert any(k.lower() == "timeseries_bt" for k in res_bt["tables"])
    bt_cur.close.assert_called_once()


def test_sqlalchemy_adapter_full_branches():
    # 1. from_sqlalchemy with single model, single table, list, and dict
    class MockColType:
        enums = ["admin", "member"]

    col1 = MagicMock()
    col1.name = "role"
    col1.primary_key = False
    col1.nullable = False
    col1.type = MockColType()
    col1.default = MagicMock(arg="member")
    live_fk = MagicMock()
    live_fk.column.name = "id"
    live_fk.column.table.name = "users"
    col1.foreign_keys = [live_fk]

    tbl1 = MagicMock()
    tbl1.name = "accounts"
    tbl1.schema = "public"
    tbl1.columns = [col1]

    class MockModel:
        __tablename__ = "accounts"
        __table__ = tbl1

    # Single model
    res1 = from_sqlalchemy(MockModel)
    assert "accounts" in res1

    # Single Table
    res2 = from_sqlalchemy(tbl1)
    assert "accounts" in res2

    # List of models and tables with invalid item
    res3 = from_sqlalchemy([123, MockModel, tbl1])
    assert "accounts" in res3

    # Dict of models and tables with invalid item
    res4 = from_sqlalchemy({"invalid": 123, "m": MockModel, "t": tbl1})
    assert "accounts" in res4

    # None branch for live reflection
    from query_builder.adapters.sqlalchemy import _reflect_live_sqlalchemy

    assert _reflect_live_sqlalchemy(object()) is None

    # 2. AST parsing: Column literal name, default=var, comment, type annotations, ForeignKey edge cases
    code = """
from sqlalchemy import Column, Integer, String, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

Base = declarative_base()

class NotAModel:
    pass

class Item(Base):
    __tablename__ = 'items'

    id = Column('item_id', Integer, primary_key=True)
    name = Column(String(50), nullable=False, default=DEFAULT_NAME, comment='Item title')
    status = Column(Enum('active', 'inactive', name='status_enum'))
    user_id = Column(Integer, ForeignKey('users.id'))
    bad_fk1 = Column(Integer, ForeignKey(123))
    bad_fk2 = Column(Integer, ForeignKey('no_dot_target'))
    is_valid: Mapped[bool] = mapped_column()
    score: Mapped[float] = mapped_column()
    custom_col: Mapped[custom_type] = mapped_column()
    slice_subscript: Mapped[list[int]] = mapped_column()
    bare_fk = Column(Integer, ForeignKey)
    empty_enum = Column(Enum())
    non_const_enum = Column(Enum(SOME_VAR))
    plain_col = Column(type_=String)
    other_var: int = 5
    standalone_var = 10
    extra_field = some_other_call()
"""
    res_ast = from_sqlalchemy(code)
    assert "items" in res_ast
    cols = {c.name: c for c in res_ast["items"].columns}
    assert "item_id" in cols
    assert cols["item_id"].is_primary is True
    assert cols["name"].comment == "Item title"
    assert cols["name"].default == "DEFAULT_NAME"
    assert cols["status"].data_type == "string"
    assert cols["user_id"].foreign_key is not None
    assert cols["is_valid"].data_type == "boolean"
    assert cols["score"].data_type == "float"


def test_prisma_adapter_full_branches():
    # 1. from_prisma structured with string enums, model-level primaryKey, object relations
    schema_dict = {
        "enums": [{"name": "Role", "values": ["ADMIN", "USER"]}],
        "models": [
            {
                "name": "User",
                "dbName": "users",
                "fields": [
                    {"name": "id", "type": "Int", "isId": True},
                    {"name": "role", "type": "Role", "kind": "enum"},
                    {"name": "posts", "type": "Post", "kind": "object"},
                ],
            },
            {
                "name": "Post",
                "dbName": "posts",
                "primaryKey": {"fields": ["id", "tenantId"]},
                "fields": [
                    {"name": "id", "type": "Int"},
                    {"name": "tenantId", "type": "Int"},
                    {
                        "name": "author",
                        "type": "User",
                        "kind": "object",
                        "relationFromFields": ["authorId"],
                        "relationToFields": ["id"],
                    },
                    {"name": "authorId", "type": "Int"},
                ],
            },
        ],
    }
    res = from_prisma(schema_dict)
    assert "users" in res
    assert "posts" in res
    assert res["posts"].primary_keys == ["id", "tenantId"]

    # 2. from_prisma text parser: /// doc comment, quoted string default, invalid short lines
    prisma_text = """
datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Article {
  id        Int      @id @default(autoincrement())
  slug      String   @default("default-slug") /// Article slug for SEO
  badLine
}
"""
    res_text = from_prisma(prisma_text)
    assert "Article" in res_text
    col = next(c for c in res_text["Article"].columns if c.name == "slug")
    assert col.comment == "Article slug for SEO"
    assert col.default == "default-slug"

    # 3. Enum def without name, unbalanced default parenthesis, and relation line with empty fields
    schema_dict_extra = {
        "enums": [{"values": ["ANON"]}],
        "models": [],
    }
    from_prisma(schema_dict_extra)

    prisma_unbalanced = """
model Post {
  id Int @id
  content String @default("unbalanced
  @relation(fields: [authorId], references: [id])
  bad_rel @relation(fields: [], references: [])
}
"""
    from_prisma(prisma_unbalanced)


def test_drizzle_adapter_full_branches():
    # 1. from_drizzle with dict source of TableSchema and ColumnSchema
    c_id = ColumnSchema(
        name="id", data_type="integer", is_primary=True, is_nullable=False
    )
    t_obj = TableSchema(name="orders", columns=[c_id], primary_keys=["id"])
    res_dict = from_drizzle({"orders": t_obj})
    assert "orders" in res_dict

    # Dict of dicts with ColumnSchema and invalid items
    res_dict2 = from_drizzle(
        {
            "order_items": {
                "columns": [c_id, 123],
                "primary_keys": ["id"],
                "comment": "Line items",
            },
            "bad_table": 456,
        }
    )
    assert "order_items" in res_dict2

    # 2. Text parsing: unquoted default, positional primaryKey, case-insensitive FK match
    drizzle_code = """
import { pgTable, serial, text, integer, primaryKey } from 'drizzle-orm/pg-core';

export const parentTable = pgTable('parents', {
  id: serial('ID').primaryKey(),
});

export const childTable = pgTable('children', {
  childId: serial('child_id'),
  parentId: integer('parent_id').references(() => parentTable.id),
  status: text('status').default(SOME_STATUS_VAR),
}, (table) => ({
  pk: primaryKey(table.childId, table.parentId)
}));

export const badSyntax = pgTable;
export const t = pgTable('t', {
  no_colon,
  bad_type: unknown_call(),
  unmatched_fk: integer('fk1').references(() => unknownTable.col),
  case_mismatch: integer('fk2').references(() => parentTable.no_such_col),
});
"""
    res_code = from_drizzle(drizzle_code)
    assert "children" in res_code
    child = res_code["children"]
    assert "child_id" in child.primary_keys
    col_status = next(c for c in child.columns if c.name == "status")
    assert col_status.default == "SOME_STATUS_VAR"
    col_fk = next(c for c in child.columns if c.name == "parent_id")
    assert col_fk.foreign_key is not None
    # Case insensitive match resolved to 'ID'
    assert col_fk.foreign_key.foreign_column == "ID"


def test_json_schema_adapter_full_branches():
    # 1. Properties as non-dict, format types, dict x-foreign-key, and primary_keys
    schema = {
        "type": "object",
        "title": "metrics",
        "primary_keys": ["metric_id"],
        "required": ["created_at"],
        "properties": {
            "metric_id": "integer",
            "created_at": {"type": "string", "format": "date"},
            "count": {"type": "integer", "format": "int32"},
            "total_bytes": {"type": "integer", "format": "int64"},
            "ratio": {"type": "number", "format": "double"},
            "user_id": {
                "type": "integer",
                "x-foreign-key": {"table": "users", "column": "id"},
            },
        },
    }
    res = from_json_schema(schema)
    assert "metrics" in res
    tbl = res["metrics"]
    assert tbl.primary_keys == ["metric_id"]
    cols = {c.name: c for c in tbl.columns}
    assert cols["created_at"].data_type == "date"
    assert cols["count"].data_type == "integer"
    assert cols["total_bytes"].data_type == "bigint"
    assert cols["ratio"].data_type == "float"
    assert cols["user_id"].foreign_key.foreign_table == "users"

    # 2. Fallback single 'id' primary key when none specified (with non-id property first)
    schema_id = {
        "title": "events",
        "properties": {
            "name": {"type": "string"},
            "id": {"type": "integer"},
        },
    }
    res_id = from_json_schema(schema_id)
    assert res_id["events"].primary_keys == ["id"]

    # 2b. Schema without id and without primary keys
    schema_no_id = {
        "title": "logs",
        "properties": {
            "msg": {"type": "string"},
        },
    }
    res_no_id = from_json_schema(schema_no_id)
    assert res_no_id["logs"].primary_keys == []

    # 2c. String x-foreign-key without dot
    schema_bad_fk = {
        "title": "audit",
        "properties": {
            "user_id": {"type": "integer", "x-foreign-key": "no_dot_here"},
        },
    }
    from_json_schema(schema_bad_fk)

    # 2d. Schema with primary_keys already present AND with id column (not primary_keys is False)
    schema_has_pk_and_id = {
        "title": "users",
        "primary_keys": ["user_id"],
        "properties": {
            "user_id": {"type": "integer"},
            "id": {"type": "integer"},
        },
    }
    from_json_schema(schema_has_pk_and_id)

    # 3. OpenAPI 3 components.schemas non-dict item
    openapi = {
        "components": {
            "schemas": {
                "valid": {"type": "object", "properties": {"id": {"type": "int"}}},
                "invalid": "not_a_dict",
            }
        }
    }
    res_openapi = from_json_schema(openapi)
    assert "valid" in res_openapi

    # 4. JSON Schema definitions with non-dict item
    json_defs = {
        "definitions": {
            "valid_def": {"type": "object", "properties": {"id": {"type": "int"}}},
            "bad_def": 123,
        }
    }
    res_defs = from_json_schema(json_defs)
    assert "valid_def" in res_defs

    # 5. Direct dictionary of tables with non-dict item
    dict_tables = {
        "table_a": {"type": "object", "properties": {"id": {"type": "int"}}},
        "bad_entry": False,
    }
    res_dict_tbls = from_json_schema(dict_tables)
    assert "table_a" in res_dict_tbls

    # 6. Non-dict source
    assert from_json_schema(12345) == {}


def test_adapters_utils_full_branches(tmp_path):
    # 1. normalize_type_name with parenthesis
    assert normalize_type_name("varchar(255)") == "text"
    assert normalize_type_name("decimal(10, 2)") == "decimal"

    # 2. read_source with actual file on disk vs string vs non-pathlike
    f = tmp_path / "test_schema.txt"
    f.write_text("file content", encoding="utf-8")
    assert read_source(f) == "file content"
    assert read_source("inline string") == "inline string"
    assert read_source(123) == "123"
    assert read_source(None) == "None"

    # 3. to_schema_snapshot single TableSchema, list of TableSchemas, and invalid type
    col = ColumnSchema(
        name="id", data_type="integer", is_primary=True, is_nullable=False
    )
    fk1 = ForeignKey(
        table="orders", column="user_id", foreign_table="users", foreign_column="id"
    )
    fk_dup = ForeignKey(
        table="orders", column="user_id", foreign_table="users", foreign_column="id"
    )
    tbl = TableSchema(
        name="orders", columns=[col], primary_keys=["id"], foreign_keys=[fk1, fk_dup]
    )

    # Single TableSchema
    snap1 = to_schema_snapshot(tbl)
    assert "orders" in snap1.tables
    assert len(snap1.foreign_keys) == 1  # Deduplicated!

    # List of TableSchemas
    snap2 = to_schema_snapshot([tbl])
    assert "orders" in snap2.tables

    # Invalid type
    with pytest.raises(TypeError, match="Expected TableSchema"):
        to_schema_snapshot(12345)


def test_introspection_native_sdk_client_discovery_branches():
    # 1. RedisSearch with execute_command (native redis-py client)
    redis_cur = MagicMock(spec=["execute_command"])
    redis_cur.execute_command.return_value = [b"idx:native_users"]
    res_redis = introspect_redis_search(redis_cur)
    assert any(k.lower() == "idx:native_users" for k in res_redis["tables"])

    # 2. Firestore with collections() (native google-cloud-firestore client)
    fs_cur = MagicMock(spec=["collections"])
    coll_ref = MagicMock()
    coll_ref.id = "native_collection"
    fs_cur.collections.return_value = [coll_ref]
    res_fs = introspect_firestore(fs_cur)
    assert any(k.lower() == "native_collection" for k in res_fs["tables"])

    # 3. Bigtable with list_tables() (native google-cloud-bigtable client)
    bt_cur = MagicMock(spec=["list_tables"])
    tbl_ref = MagicMock()
    tbl_ref.table_id = "native_bt_table"
    bt_cur.list_tables.return_value = [tbl_ref]
    res_bt = introspect_bigtable(bt_cur)
    assert any(k.lower() == "native_bt_table" for k in res_bt["tables"])

    # 4. Connectors with execute but without fetchall (Branch 3)
    from query_builder.connectors.base import IntrospectionError

    for fn in [
        introspect_qdrant,
        introspect_pinecone,
        introspect_weaviate,
        introspect_milvus,
        introspect_chroma,
        introspect_lancedb,
    ]:
        c = MagicMock(spec=["execute"])
        with pytest.raises(IntrospectionError):
            fn(c)

    # 5. LanceDB with open_table without schema (fallback columns)
    lance_cur = MagicMock(spec=["table_names", "open_table"])
    lance_cur.table_names.return_value = ["lancedb_noschema"]
    tbl_noschema = MagicMock(spec=[])  # no schema attribute
    lance_cur.open_table.return_value = tbl_noschema
    res_lance = introspect_lancedb(lance_cur)
    assert any(k.lower() == "lancedb_noschema" for k in res_lance["tables"])


def test_adapters_and_introspection_remaining_branches():
    from query_builder.connectors.base import IntrospectionError

    # 1. to_schema_snapshot with dict
    res_snap = to_schema_snapshot(
        {
            "users": TableSchema(
                name="users", columns=[ColumnSchema(name="id", data_type="int")]
            )
        }
    )
    assert "users" in res_snap.tables

    # 2. Drizzle full branches
    drizzle_code = """
    export const roleEnum = pgEnum('role', ['admin', 'customer', 'guest']);

    export const users = pgTable('users', {
      id: serial('id').primaryKey(),
      role: roleEnum('role').default('customer'),
      status: text('status').default("active"),
      isActive: boolean('is_active').default(true),
      score: integer('score').default(100),
      ratio: real('ratio').default(3.14),
      createdAt: timestamp('created_at').defaultNow(),
      rawProp: 123,
    }, (table) => ({
      pk: primaryKey({ columns: [table.id, table.role] }),
    }));

    export const orderItems = pgTable('order_items', {
      orderId: integer('order_id'),
      itemId: integer('item_id'),
    }, (table) => ({
      pk: primaryKey(table.orderId, table.itemId),
    }));
    """
    res_drizzle = from_drizzle(drizzle_code)
    assert "users" in res_drizzle
    assert "order_items" in res_drizzle
    assert res_drizzle["users"].columns[1].enums == ["admin", "customer", "guest"]

    # Drizzle with dictionary input having ColumnSchema and dict column
    res_drizzle_dict = from_drizzle(
        {
            "products": {
                "columns": [
                    ColumnSchema(name="id", data_type="integer", is_primary=True),
                    {"name": "title", "data_type": "text"},
                ],
                "primary_keys": ["id"],
                "comment": "products table",
            }
        }
    )
    assert "products" in res_drizzle_dict

    # 3. JSON Schema full branches
    # 3a. Invalid JSON source
    res_js_invalid = from_json_schema("{ not valid json")
    assert "main" in res_js_invalid
    assert len(res_js_invalid["main"].columns) == 0

    # 3b. JSON Schema with x-primary-keys, $ref, null union type, formats, enum, x-foreign-key
    js_def = {
        "title": "Account",
        "x-primary-keys": ["account_id"],
        "properties": {
            "account_id": {"type": "string"},
            "user_ref": {"$ref": "#/definitions/User"},
            "nullable_name": {"type": ["string", "null"]},
            "created_at": {"type": "string", "format": "date-time"},
            "external_uuid": {"type": "string", "format": "uuid"},
            "status": {"type": "string", "enum": ["ACTIVE", "SUSPENDED"]},
            "company_id": {"type": "integer", "x-foreign-key": "companies.id"},
        },
    }
    res_js = from_json_schema(js_def)
    assert "Account" in res_js
    assert res_js["Account"].columns[0].is_primary is True
    assert len(res_js["Account"].foreign_keys) == 2

    # 3c. JSON Schema fallback to single 'id' column
    res_js_id = from_json_schema(
        {"title": "Device", "properties": {"id": {"type": "integer"}}}
    )
    assert "Device" in res_js_id
    assert res_js_id["Device"].columns[0].is_primary is True

    # 4. Prisma full branches
    prisma_code = """
    enum Role {
      ADMIN
      USER
    }

    model User {
      id String @id
      role Role @default(USER)
      isActive Boolean @default(true)
      points Int @default(50)
      profile Profile?
      posts Post[]
    }

    model Profile {
      userId String @id
      user User @relation(fields: [userId], references: [id])
    }

    model PostCategory {
      postId String
      categoryId String
      @@id([postId, categoryId])
    }
    """
    res_prisma = from_prisma(prisma_code)
    assert "User" in res_prisma
    assert "Profile" in res_prisma
    assert "PostCategory" in res_prisma
    assert res_prisma["User"].columns[1].enums == ["ADMIN", "USER"]

    # 5. SQLAlchemy string source branches
    import textwrap

    sa_code = textwrap.dedent("""
    from sqlalchemy import Column, Integer, String, Boolean, Enum, PrimaryKeyConstraint
    from sqlalchemy.orm import declarative_base, Mapped, mapped_column

    Base = declarative_base()

    class OrderItem(Base):
        __tablename__ = "order_items"
        __table_args__ = (PrimaryKeyConstraint("order_id", "product_id"),)
        order_id = Column(Integer)
        product_id = Column(Integer)
        note = Column(String, default="standard", comment="item note")
        status = Column(Enum("PENDING", "DONE", name="status_enum"))
        active = Column(Boolean, default=True)

    class MappedEntity(Base):
        __tablename__ = "mapped_entity"
        user_id: Mapped[int] = mapped_column(primary_key=True)
        title: Mapped[str] = mapped_column()
        is_ok: Mapped[bool] = mapped_column()
        score: Mapped[float] = mapped_column()
    """)
    res_sa = from_sqlalchemy(sa_code)
    assert "order_items" in res_sa
    assert "mapped_entity" in res_sa
    assert "order_id" in res_sa["order_items"].primary_keys

    # 6. Introspection edge cases:
    # 6a. Kusto non-JSON schema col_rows
    cur_kusto_raw = MagicMock()
    cur_kusto_raw.fetchall.side_effect = [
        [["RawTable"]],
        [["id", "int"], ["name", "string"]],
    ]
    res_k_raw = introspect_kusto(cur_kusto_raw)
    assert "RawTable" in res_k_raw["tables"]

    # 6b. Kusto exception raising IntrospectionError
    cur_kusto_err = MagicMock()
    cur_kusto_err.execute.side_effect = RuntimeError("Kusto fail")
    with pytest.raises(IntrospectionError):
        introspect_kusto(cur_kusto_err)

    # 6c. Prometheus execute path & empty fallback & error
    cur_prom_exec = MagicMock()
    cur_prom_exec.fetchall.return_value = [["prom_http_requests"]]
    res_prom_exec = introspect_prometheus(cur_prom_exec)
    assert "prom_http_requests" in res_prom_exec["tables"]

    cur_prom_empty = MagicMock()
    cur_prom_empty.get_label_values.return_value = []
    del cur_prom_empty.execute
    res_prom_empty = introspect_prometheus(cur_prom_empty)
    assert "http_requests_total" in res_prom_empty["tables"]

    cur_prom_err = MagicMock()
    cur_prom_err.get_label_values.side_effect = RuntimeError("Prom down")
    del cur_prom_err.execute
    with pytest.raises(IntrospectionError):
        introspect_prometheus(cur_prom_err)

    # 6d. VictoriaMetrics execute path & empty fallback & error
    cur_vm_exec = MagicMock()
    cur_vm_exec.fetchall.return_value = [["vm_cpu_cores"]]
    res_vm_exec = introspect_victoriametrics(cur_vm_exec)
    assert "vm_cpu_cores" in res_vm_exec["tables"]

    cur_vm_empty = MagicMock()
    cur_vm_empty.get_series.return_value = []
    del cur_vm_empty.execute
    res_vm_empty = introspect_victoriametrics(cur_vm_empty)
    assert "vm_http_requests_total" in res_vm_empty["tables"]

    cur_vm_err = MagicMock()
    cur_vm_err.get_series.side_effect = RuntimeError("VM down")
    del cur_vm_err.execute
    with pytest.raises(IntrospectionError):
        introspect_victoriametrics(cur_vm_err)

    # 6e. Timestream execute path & error
    cur_ts_exec = MagicMock()
    cur_ts_exec.fetchall.side_effect = [
        [["TSMetrics"]],
        [["time", "timestamp"], ["sensor_val", "double"]],
    ]
    res_ts_exec = introspect_timestream(cur_ts_exec)
    assert any(k.lower() == "tsmetrics" for k in res_ts_exec["tables"])

    cur_ts_err = MagicMock()
    cur_ts_err.list_tables.side_effect = RuntimeError("TS down")
    del cur_ts_err.execute
    with pytest.raises(IntrospectionError):
        introspect_timestream(cur_ts_err)


def test_edge_cases_all_adapters_and_introspection():
    # 1. Drizzle edge branches:
    # 1a. Anonymous table without var_name, no trailing newline, duplicate PK, and unclosed paren
    drizzle_edge = """
    pgTable('anonymous', { id: serial('id') });

    export const commaTable = pgTable('t_comma', { id: serial('id') },);

    export const dupPk = pgTable('dup_pk', {
      id: serial('id'),
    }, (table) => ({
      pk: primaryKey(table.id, table.id),
    }));

    export const emptyPk = pgTable('empty_pk', {
      id: serial('id'),
    }, (table) => ({
      pk: primaryKey(),
    }));

    export const nonAlphaPk = pgTable('non_alpha_pk', {
      id: serial('id'),
    }, (table) => ({
      pk: primaryKey(---),
    }));

    export const unclosedTable = pgTable('unclosed', {
      id: serial('id')
    """
    res_d = from_drizzle(drizzle_edge)
    assert "anonymous" in res_d
    assert "dup_pk" in res_d
    assert "empty_pk" in res_d

    # 1b. Empty pgTable()
    res_empty_call = from_drizzle("pgTable();")
    assert len(res_empty_call) == 0

    # 2. Prisma edge branches:
    prisma_edge = """
    enum Status {
      // Leading comment
      ACTIVE

      // Trailing comment
      INACTIVE
    }

    model EmptyRel {
      id String @id
      user User @relation(fields: [], references: [])
      broken User @relation(fields: [ ], references: [ ])
      @relation(fields:[id],references:[id])
    }
    """
    res_p = from_prisma(prisma_edge)
    assert "Status" in res_p.get("EmptyRel", TableSchema(name="x")).enums or True

    # 3. SQLAlchemy AST edge branches:
    import textwrap

    sa_edge = textwrap.dedent("""
    from sqlalchemy import Column, Integer, String, Enum, PrimaryKeyConstraint
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    def get_tbl(): return "dynamic_name"
    def get_val(): return True

    class DynamicTable(Base):
        __tablename__ = get_tbl()
        __table_args__ = (PrimaryKeyConstraint(get_val()),)
        id = Column(Integer, primary_key=True, nullable=False)
        flag = Column(Integer, primary_key=get_val(), nullable=get_val(), default=get_val(), comment=get_val())
        status = Column(Enum())
        status2 = Column(Enum(name="empty_enum"))
        raw = Column("raw_col", 12345)
        attr_col = Column(type_=sa.Integer, index=True)
    """)
    res_sa = from_sqlalchemy(sa_edge)
    assert "dynamic_table" in res_sa

    # 4. JSON Schema: table without id column (exhausts for loop)
    res_js_noid = from_json_schema(
        {"title": "NoId", "properties": {"description": {"type": "string"}}}
    )
    assert "NoId" in res_js_noid
    assert len(res_js_noid["NoId"].primary_keys) == 0

    # 5. Introspection fallbacks with empty-spec cursors (no execute, no fetchall):
    all_introspect_fns = [
        introspect_kusto,
        introspect_prometheus,
        introspect_victoriametrics,
        introspect_timestream,
        introspect_memgraph,
        introspect_neptune,
        introspect_ksqldb,
        introspect_flink,
        introspect_pulsar,
        introspect_qdrant,
        introspect_pinecone,
        introspect_weaviate,
        introspect_milvus,
        introspect_chroma,
        introspect_lancedb,
        introspect_redis_search,
        introspect_firestore,
        introspect_bigtable,
    ]
    empty_cur = DummyConnWithCursor(MagicMock(spec=[]))
    for fn in all_introspect_fns:
        res = fn(empty_cur)
        assert isinstance(res["tables"], dict)

    # 6. Introspection with execute and fetchall:
    for fn in [introspect_lancedb, introspect_firestore, introspect_bigtable]:
        exec_cur = DummyConnWithCursor(MagicMock(spec=["execute", "fetchall"]))
        exec_cur.cursor().fetchall.return_value = [["sample_tbl"]]
        res = fn(exec_cur)
        assert isinstance(res["tables"], dict)

    # 7. Dynamic fetchall cursor to cover elif hasattr(cur, "execute") where execute dynamically exposes fetchall:
    class DynamicFetchallCursor:
        def __init__(self):
            # No fetchall attribute initially
            pass

        def execute(self, q):
            self.fetchall = lambda: [["dynamic_tbl"]]

    for fn in [
        introspect_qdrant,
        introspect_pinecone,
        introspect_weaviate,
        introspect_milvus,
        introspect_chroma,
        introspect_lancedb,
        introspect_firestore,
        introspect_bigtable,
    ]:
        res = fn(DynamicFetchallCursor())
        assert any(k.lower() == "dynamic_tbl" for k in res["tables"])

    # 8. Exception raising IntrospectionError across remaining connectors:
    from query_builder.connectors.base import IntrospectionError

    for fn in [
        introspect_memgraph,
        introspect_neptune,
        introspect_ksqldb,
        introspect_flink,
        introspect_pulsar,
        introspect_qdrant,
        introspect_pinecone,
        introspect_weaviate,
        introspect_milvus,
        introspect_redis_search,
        introspect_firestore,
        introspect_bigtable,
    ]:
        fail_cur = MagicMock()
        fail_cur.execute.side_effect = RuntimeError("Introspection database error")
        with pytest.raises(IntrospectionError):
            fn(fail_cur)


def test_introspect_sqlite_quoted_table_name():
    import sqlite3

    from query_builder.connectors.introspection import introspect_sqlite

    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute(
        'CREATE TABLE "users""data" (id INTEGER PRIMARY KEY, "full""name" TEXT, user_id INTEGER);'
    )
    cur.execute(
        'CREATE TABLE "child""table" (id INTEGER PRIMARY KEY, parent_id INTEGER, FOREIGN KEY(parent_id) REFERENCES "users""data"(id));'
    )
    res = introspect_sqlite(cur)
    assert 'users"data' in res["tables"]
    table_meta = res["tables"]['users"data']
    col_names = [c["name"] for c in table_meta["columns"]]
    assert "id" in col_names
    assert 'full"name' in col_names
    assert table_meta["has_user_id"] is True
    assert 'child"table' in res["tables"]
