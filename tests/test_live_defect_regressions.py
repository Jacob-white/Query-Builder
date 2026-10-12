"""Regressions for defects found by live-engine testing (no services needed).

* RisingWave rejects ``SELECT DISTINCT ... ORDER BY <qualified column>`` and silently drops
  the rows whose partition key is NULL for an aggregate window without ORDER BY.
* pymongosql ignores the ``''`` quote escape and silently returns no rows.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from query_builder.compiler import QueryCompiler
from query_builder.connectors.mongodb import (
    MongoDBAtlasSQLConnector,
    bind_escaped_quote_literals,
)
from query_builder.dialects.registry import get_dialect

SCHEMA = {
    "tables": {
        "emp": {
            "columns": [
                {"name": "id", "is_primary": True},
                {"name": "dept_id"},
                {"name": "salary"},
            ],
            "has_user_id": False,
        }
    },
    "foreign_keys": [],
    "relationships": [],
}


def _sql(spec: dict[str, Any], dialect: str) -> str:
    return QueryCompiler(spec, schema=SCHEMA, dialect=get_dialect(dialect)).compile()[0]


DISTINCT = {
    "table": "emp",
    "columns": ["dept_id"],
    "distinct": True,
    "order_by": [{"column": "dept_id", "direction": "asc"}],
}


def test_risingwave_distinct_orders_by_select_alias() -> None:
    sql = _sql(DISTINCT, "risingwave")
    assert 'SELECT DISTINCT "t1"."dept_id" AS "dept_id"' in sql
    assert 'ORDER BY "dept_id" ASC' in sql


def test_risingwave_non_distinct_order_by_keeps_qualified_column() -> None:
    sql = _sql({**DISTINCT, "distinct": False}, "risingwave")
    assert 'ORDER BY "t1"."dept_id" ASC' in sql


def test_risingwave_distinct_order_by_unselected_column_is_untouched() -> None:
    spec = {**DISTINCT, "order_by": [{"column": "salary"}]}
    assert 'ORDER BY "t1"."salary" ASC' in _sql(spec, "risingwave")


def test_other_dialects_distinct_output_is_unchanged() -> None:
    assert 'ORDER BY "t1"."dept_id" ASC' in _sql(DISTINCT, "postgres")
    assert 'ORDER BY "t1"."dept_id" ASC' in _sql(DISTINCT, "cockroachdb")


def _window(wf: dict[str, Any]) -> dict[str, Any]:
    return {"table": "emp", "columns": ["id"], "window_functions": [wf]}


SUM_WINDOW = {
    "function": "SUM",
    "arguments": ["salary"],
    "partition_by": ["dept_id"],
    "alias": "t",
}
FULL = (
    'OVER (PARTITION BY "t1"."dept_id" ORDER BY "t1"."dept_id" '
    "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)"
)


def test_risingwave_partition_aggregate_window_keeps_null_partition_rows() -> None:
    assert FULL in _sql(_window(SUM_WINDOW), "risingwave")


@pytest.mark.parametrize(
    "wf",
    [
        {**SUM_WINDOW, "order_by": [{"column": "salary"}]},
        {**SUM_WINDOW, "frame": {"frame_type": "ROWS", "start": "UNBOUNDED PRECEDING"}},
        {**SUM_WINDOW, "partition_by": []},
        {
            "function": "ROW_NUMBER",
            "partition_by": ["dept_id"],
            "order_by": [{"column": "salary"}],
            "alias": "t",
        },
    ],
)
def test_risingwave_window_rewrite_only_for_bare_partition_aggregates(
    wf: dict[str, Any],
) -> None:
    assert FULL not in _sql(_window(wf), "risingwave")


def test_other_dialects_window_output_is_unchanged() -> None:
    sql = _sql(_window(SUM_WINDOW), "postgres")
    assert 'OVER (PARTITION BY "t1"."dept_id")' in sql


# ------------------------------------------------------------------ pymongosql quotes


@pytest.mark.parametrize(
    ("sql", "params", "want_sql", "want_params"),
    [
        (
            "SELECT name FROM c WHERE name = 'O''Brien'",
            None,
            "SELECT name FROM c WHERE name = ?",
            ["O'Brien"],
        ),
        (
            "SELECT a FROM c WHERE x = ? AND name = 'it''s' AND y = ?",
            [1, 2],
            "SELECT a FROM c WHERE x = ? AND name = ? AND y = ?",
            [1, "it's", 2],
        ),
        (
            "SELECT a FROM c WHERE n = 'a''b' OR m = 'c''''d'",
            [],
            "SELECT a FROM c WHERE n = ? OR m = ?",
            ["a'b", "c''d"],
        ),
        (  # only the quote-escaped literal is bound; plain literals stay literal
            "SELECT a FROM c WHERE n = 'plain' AND m = 'x''y'",
            None,
            "SELECT a FROM c WHERE n = 'plain' AND m = ?",
            ["x'y"],
        ),
        (  # a `?` or quote inside a double-quoted identifier is not a placeholder
            "SELECT \"we?ird\" FROM c WHERE m = 'x''y'",
            None,
            'SELECT "we?ird" FROM c WHERE m = ?',
            ["x'y"],
        ),
    ],
)
def test_escaped_quote_literals_become_bound_parameters(
    sql: str, params: Any, want_sql: str, want_params: list[Any]
) -> None:
    assert bind_escaped_quote_literals(sql, params) == (want_sql, want_params)


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        ("SELECT a FROM c WHERE n = 'plain'", None),  # no escape: untouched
        ("SELECT a FROM c WHERE n = 'x''y'", {"k": 1}),  # named params: untouched
        ("SELECT a FROM c WHERE n = 'x''y", None),  # unterminated: driver reports it
        ("SELECT \"a FROM c WHERE n = 'x''y'", None),  # unterminated identifier
    ],
)
def test_bind_escaped_quote_literals_leaves_other_sql_alone(
    sql: str, params: Any
) -> None:
    assert bind_escaped_quote_literals(sql, params) == (sql, params)


def test_mongodb_connector_executes_escaped_quote_query_with_bound_value() -> None:
    cur = MagicMock()
    cur.description = [("name",)]
    cur.fetchall.return_value = [("O'Brien",)]
    conn = MongoDBAtlasSQLConnector(database="d", cursor=cur)
    result = conn.execute(sql="SELECT name FROM people WHERE name = 'O''Brien'")
    cur.execute.assert_called_once_with(
        "SELECT name FROM people WHERE name = ?", ["O'Brien"]
    )
    assert result["rows"] == [{"name": "O'Brien"}]


# ----------------------------------------------- MongoDB: aliases / quoted identifiers
def _mongo_sql(spec: dict[str, Any]) -> str:
    return QueryCompiler(spec, dialect=get_dialect("mongodb")).compile()[0]


def test_mongodb_compiles_bare_identifiers_without_table_aliases() -> None:
    sql = _mongo_sql(
        {
            "table": "qbit_people",
            "columns": ["name", "age"],
            "order_by": [{"column": "age", "direction": "asc"}],
            "limit": 10,
        }
    )
    assert sql == (
        "SELECT name AS name, age AS age\nFROM qbit_people\nORDER BY age ASC\nLIMIT 10"
    )


def test_mongodb_star_and_filter_are_unqualified() -> None:
    sql = _mongo_sql(
        {
            "table": "qbit_people",
            "columns": ["*"],
            "filters": [{"column": "age", "op": "gt", "value": 25}],
        }
    )
    assert sql.startswith("SELECT *\nFROM qbit_people\nWHERE (age > ?)")
    assert '"' not in sql and "t1" not in sql


def test_mongodb_refuses_joins_it_cannot_alias() -> None:
    from query_builder.exceptions import CompilationError

    with pytest.raises(CompilationError, match="cannot compile joins"):
        _mongo_sql(
            {
                "table": "a",
                "columns": ["x"],
                "joins": [{"table": "b", "on": [{"left": "a.id", "right": "b.id"}]}],
            }
        )


def test_mongodb_unusual_alias_is_still_quoted_and_safe() -> None:
    dialect = get_dialect("mongodb")
    assert dialect.quote_alias("total") == "total"
    assert dialect.quote_alias('we"ird name') == '"we""ird name"'


def test_other_dialects_keep_table_aliases() -> None:
    sql = QueryCompiler(
        {"table": "p", "columns": ["name"]}, dialect=get_dialect("postgres")
    ).compile()[0]
    assert '"t1"."name"' in sql and 'FROM "p" "t1"' in sql


# ------------------------------------------- Bigtable: app profile is per table
def test_bigtable_binds_app_profile_to_tables_not_to_client_instance() -> None:
    """`Client.instance()` has no `app_profile_id` parameter (real signature mirrored here)."""
    from query_builder.connectors.bigtable import _open

    class _Instance:
        def __init__(self) -> None:
            self.tables: list[tuple[str, str | None]] = []

        def table(
            self,
            table_id: str,
            mutation_timeout: float | None = None,
            app_profile_id: str | None = None,
        ) -> str:
            self.tables.append((table_id, app_profile_id))
            return table_id

    class _Client:
        def __init__(self, project: str | None = None, admin: bool = False) -> None:
            self.made = _Instance()

        def instance(
            self,
            instance_id: str,
            display_name: str | None = None,
            instance_type: int | None = None,
            labels: dict[str, str] | None = None,
        ) -> _Instance:
            return self.made

    driver = MagicMock(Client=_Client)
    inst = _open(driver, "p", "i", "profile-1", False, {})
    inst.table("t")
    assert inst.tables == [("t", "profile-1")]
    plain = _open(driver, "p", "i", None, False, {})
    plain.table("t2")
    assert plain.tables[-1] == ("t2", None)


def test_bigtable_keeps_family_qualifier_as_one_column() -> None:
    """`cf.name` is a column family + qualifier, not table `cf` column `name`."""
    sql = QueryCompiler(
        {
            "table": "qbit_people",
            "columns": [{"column": "cf.name", "alias": "name"}],
            "filters": [{"column": "cf.age", "op": "gt", "value": 1}],
            "order_by": [{"column": "cf.age", "direction": "asc"}],
        },
        dialect=get_dialect("bigtable"),
    ).compile()[0]
    assert sql.startswith('SELECT "cf.name" AS "name"\nFROM "qbit_people"\n')
    assert 'WHERE ("cf.age" > %s)' in sql and 'ORDER BY "cf.age" ASC' in sql
    assert "t1" not in sql and "t2" not in sql


def test_presto_inlines_limit_and_offset_because_it_cannot_bind_them() -> None:
    """PrestoDB rejects `LIMIT ?` (mismatched input '?'); values are int-inlined."""
    presto = get_dialect("presto")
    assert presto.format_limit_offset(10, 20) == ("OFFSET 20 LIMIT 10", [])
    # OFFSET is off by default on PrestoDB, so a zero offset must not emit it.
    assert presto.format_limit_offset(10, 0) == ("LIMIT 10", [])
    sql, *rest = QueryCompiler(
        {"table": "qbit_employees", "columns": ["id"], "limit": 5},
        dialect=presto,
    ).compile()
    assert sql.rstrip().endswith("LIMIT 5")
    assert rest[0] == []


def test_presto_test_connection_survives_missing_version_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PrestoDB has no version(); a failed version lookup must not fail the test."""
    from query_builder.connectors.base import BaseConnector
    from query_builder.connectors.prestodb import PrestoDBConnector

    class _Cur:
        def __enter__(self) -> _Cur:
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def execute(self, sql: str) -> None:
            assert "version()" not in sql
            raise RuntimeError("boom")

    monkeypatch.setattr(BaseConnector, "test_connection", lambda self: {"ok": True})
    conn = PrestoDBConnector.__new__(PrestoDBConnector)
    monkeypatch.setattr(conn, "get_cursor", lambda: _Cur(), raising=False)
    assert conn.test_connection() == {"ok": True}


def test_vertica_escapes_like_wildcards_with_an_explicit_escape_clause() -> None:
    """A literal % or _ in a contains filter must not act as a wildcard."""
    sql, params, *_ = QueryCompiler(
        {
            "table": "qbit_employees",
            "columns": ["id"],
            "filters": [{"column": "name", "op": "contains", "value": "50%"}],
        },
        dialect=get_dialect("vertica"),
    ).compile()
    assert "ESCAPE '\\'" in sql
    assert params[0] == "%50\\%%"


def test_vertica_introspection_reads_v_catalog_not_information_schema() -> None:
    """Vertica has no information_schema; tables/columns/keys come from v_catalog."""
    from query_builder.connectors.introspection import introspect_vertica

    class _Cur:
        def __init__(self) -> None:
            self.seen: list[str] = []
            self._rows: list[tuple[Any, ...]] = []

        def execute(self, sql: str, params: Any = None) -> None:
            self.seen.append(sql)
            assert "information_schema" not in sql
            if "v_catalog.tables" in sql:
                self._rows = [("emp",), ("dept",)]
            elif "primary_keys" in sql:
                self._rows = [("emp", "id"), ("dept", "id")]
            elif "v_catalog.columns" in sql:
                self._rows = [
                    ("emp", "id", "int", False),
                    ("emp", "dept_id", "int", True),
                    ("dept", "id", "int", False),
                ]
            else:
                self._rows = [("emp", "dept_id", "dept", "id")]

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self._rows

    out = introspect_vertica(_Cur(), "public", filter_sensitive=False)
    emp = {c["name"]: c for c in out["tables"]["emp"]["columns"]}
    assert emp["id"]["is_primary"] is True and emp["id"]["is_nullable"] is False
    assert emp["dept_id"]["is_nullable"] is True
    assert out["foreign_keys"][0]["foreign_table"] == "dept"


def test_keyvalue_dsn_host_is_extracted_not_treated_as_a_hostname() -> None:
    """Db2/ODBC-style `KEY=value;` DSNs carry HOSTNAME/PORT; the whole string is not a host."""
    from query_builder.security import _parse_keyvalue_dsn

    dsn = "DATABASE=qbit;HOSTNAME=db2;PORT=50000;PROTOCOL=TCPIP;UID=u;PWD=p;"
    assert _parse_keyvalue_dsn(dsn) == ("db2", 50000)
    assert _parse_keyvalue_dsn("Driver={x};Server=tcp:h.example.com,1433") == (
        "h.example.com",
        1433,
    )
    assert _parse_keyvalue_dsn("localhost:5432") is None
    assert _parse_keyvalue_dsn("postgres://h/db") is None


def test_keyvalue_dsn_to_cloud_metadata_is_still_blocked() -> None:
    from query_builder.config import NetworkSecurityConfig
    from query_builder.connectors.base import SecurityError
    from query_builder.security import validate_network_target

    cfg = NetworkSecurityConfig(allow_private_networks=True, enforce_tls=False)
    with pytest.raises(SecurityError):
        validate_network_target(
            config={"dsn": "DATABASE=x;HOSTNAME=169.254.169.254;PORT=50000;"},
            network_config=cfg,
        )
    validate_network_target(
        config={"dsn": "DATABASE=x;HOSTNAME=127.0.0.1;PORT=50000;"},
        network_config=cfg,
    )


def test_db2_dialect_avoids_integer_average_and_declares_like_escape() -> None:
    """Db2 averages INTEGER columns with integer division and has no default LIKE escape."""
    sql, params, *_ = QueryCompiler(
        {
            "table": "qbit_employees",
            "columns": [{"column": "salary", "agg": "avg", "alias": "mean"}],
            "filters": [{"column": "name", "op": "contains", "value": "5_"}],
        },
        dialect=get_dialect("db2"),
    ).compile()
    assert 'AVG(CAST("t1"."salary" AS DOUBLE))' in sql
    assert "ESCAPE '\\'" in sql
    assert params[0] == "%5\\_%"


def test_db2_introspection_uses_primary_key_constraints_and_splits_fk_columns() -> None:
    """KEYCOLUSE lists FK columns too, and REFERENCES pads/joins column names."""
    from query_builder.connectors.introspection import introspect_db2

    class _Cur:
        def __init__(self) -> None:
            self.sql = ""
            self.rows: list[tuple[Any, ...]] = []

        def execute(self, sql: str, params: Any = None) -> None:
            self.sql = sql
            if "SYSCAT.TABLES" in sql:
                self.rows = [("EMP",), ("DEPT",)]
            elif "SYSCAT.COLUMNS" in sql:
                self.rows = [
                    ("EMP", "ID", "INTEGER", "N"),
                    ("EMP", "DEPT_ID", "INTEGER", "Y"),
                    ("DEPT", "ID", "INTEGER", "N"),
                ]
            elif "KEYCOLUSE" in sql:
                assert "TABCONST" in sql and "'P'" in sql
                self.rows = [("EMP", "ID"), ("DEPT", "ID")]
            else:
                self.rows = [
                    ("EMP", " DEPT_ID            ", "DEPT", " ID                 ")
                ]

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self.rows

    out = introspect_db2(_Cur(), "DB2INST1", filter_sensitive=False)
    assert out["foreign_keys"] == [
        {
            "table": "emp",
            "column": "dept_id",
            "foreign_table": "dept",
            "foreign_column": "id",
        }
    ]
    emp = {c["name"]: c for c in out["tables"]["emp"]["columns"]}
    assert emp["dept_id"]["is_primary"] is False and emp["id"]["is_primary"] is True


def test_db2_statement_timeout_is_set_on_the_prepared_statement() -> None:
    """The CLI query timeout only works per prepared statement, not per connection."""
    import sys
    import types

    from query_builder.connectors.db2 import DB2Connector

    calls: list[Any] = []
    fake = types.SimpleNamespace(
        SQL_ATTR_QUERY_TIMEOUT=0,
        set_option=lambda handle, opts, kind: calls.append((handle, opts, kind)),
    )

    class _Cur:
        stmt_handler = "stmt"

        def __init__(self) -> None:
            self.log: list[Any] = []

        def prepare(self, op: Any) -> None:
            self.log.append(("prepare", op))

        def execute(self, op: Any = None, params: Any = None) -> None:
            self.log.append(("execute", op, params))

    cur = _Cur()
    sys.modules["ibm_db"] = fake  # type: ignore[assignment]  # test double
    try:
        DB2Connector.__new__(DB2Connector).apply_statement_timeout(cur, 1500)
        cur.execute("SELECT 1", [1])
    finally:
        del sys.modules["ibm_db"]
    assert cur.log == [("prepare", "SELECT 1"), ("execute", None, [1])]
    assert calls == [("stmt", {0: 1}, 0)]


def test_informix_dialect_uses_qmark_inlined_pagination_and_typed_having() -> None:
    """ibm_db binds `?`; SKIP/FIRST is inlined; `SUM(x) > ?` needs a typed marker."""
    sql, params, *_ = QueryCompiler(
        {
            "table": "qbit_employees",
            "columns": [
                "dept_id",
                {"column": "salary", "agg": "sum", "alias": "total"},
            ],
            "having": [{"column": "salary", "agg": "sum", "op": "gt", "value": 150}],
            "filters": [{"column": "name", "op": "contains", "value": "5_"}],
            "limit": 5,
            "offset": 2,
        },
        dialect=get_dialect("informix"),
    ).compile()
    assert sql.startswith("SELECT SKIP 2 FIRST 5 ")
    assert 'HAVING SUM("t1"."salary") > CAST(? AS BIGINT)' in sql
    assert "ESCAPE '\\'" in sql
    assert params == ["%5\\_%", 150]


def test_validator_reads_informix_skip_first_before_distinct() -> None:
    """`SELECT SKIP n FIRST m DISTINCT ...` must parse (pagination moves to the end)."""
    from query_builder.sql_ast import _normalize_placeholders

    got = _normalize_placeholders(
        'SELECT SKIP 0 FIRST 50 DISTINCT "dept_id" FROM "t" ORDER BY "dept_id"',
        "informix",
    )
    assert got.endswith("LIMIT 50 OFFSET 0") and "SKIP" not in got
    quoted = "SELECT 'SKIP 1 FIRST 2' FROM t"
    assert _normalize_placeholders(quoted, "informix") == quoted


def test_informix_dsn_gets_delimident_unless_set_by_the_caller() -> None:
    """Without DELIMIDENT=y Informix reads "identifier" as a string (SQLCODE -201)."""
    from query_builder.connectors.informix import _with_delimident

    assert _with_delimident({"dsn": "DATABASE=a;HOSTNAME=h;"})["dsn"].endswith(
        "DELIMIDENT=y;"
    )
    assert _with_delimident({"dsn": "X=1;DELIMIDENT=n"})["dsn"] == "X=1;DELIMIDENT=n"
    assert _with_delimident({"host": "h"}) == {"host": "h"}


def test_jdbc_cursor_reports_aliases_not_underlying_column_names() -> None:
    """JayDeBeApi names columns via getColumnName (`name`), losing the `AS dept` alias."""
    from query_builder.connectors.jdbc_cursor import label_columns

    class _Meta:
        def getColumnCount(self) -> int:
            return 2

        def getColumnLabel(self, i: int) -> str:
            return ("id", "dept")[i - 1]

    class _Cur:
        __module__ = "jaydebeapi"  # only real JayDeBeApi cursors are wrapped
        _meta = _Meta()
        description = [("id", 4, None), ("name", 12, None)]

        def fetchall(self) -> list[Any]:
            return [(1, "Eng")]

    cur = label_columns(_Cur())
    assert [d[0] for d in cur.description] == ["id", "dept"]
    assert cur.description[1][1] == 12 and cur.fetchall() == [(1, "Eng")]
    plain = object()
    assert label_columns(plain) is plain  # non-JDBC cursors pass through untouched


def test_derby_averages_as_double_and_runs_semicolon_free_sql() -> None:
    sql, *_ = QueryCompiler(
        {"table": "t", "columns": [{"column": "salary", "agg": "avg", "alias": "m"}]},
        dialect=get_dialect("derby"),
    ).compile()
    assert 'AVG(CAST("t1"."salary" AS DOUBLE))' in sql

    import inspect

    import query_builder.connectors.derby as derby

    assert "SYSDUMMY1;" not in inspect.getsource(derby)  # Derby rejects a trailing ;


def test_derby_foreign_keys_only_use_jdbc_metadata_for_a_real_jdbc_cursor() -> None:
    from query_builder.connectors.introspection import _derby_jdbc_foreign_keys

    # a mock (or any non-JayDeBeApi cursor) must fall back to the SQL path, not loop
    assert _derby_jdbc_foreign_keys(MagicMock(), "APP", ["t"]) is None


def test_doris_has_no_ilike_and_declares_the_mysql_like_escape() -> None:
    """Doris has no ILIKE operator (ParseException); its sibling StarRocks already knew."""
    sql, params, *_ = QueryCompiler(
        {
            "table": "qbit_employees",
            "columns": ["id"],
            "filters": [{"column": "name", "op": "ilike", "value": "a%"}],
        },
        dialect=get_dialect("doris"),
    ).compile()
    assert "ILIKE" not in sql and "LOWER(`t1`.`name`) LIKE LOWER(%s)" in sql
    assert get_dialect("doris").escape_like("5%") == "5\\%"
