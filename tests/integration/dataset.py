"""
The standard schema + data every SQL engine is seeded with (via the engine's
NATIVE driver, never through the connector under test) and the DDL dialect
differences needed to do so.

All objects use the ``qbit_`` prefix so the suite never touches a user's own
tables when pointed at a shared database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEPARTMENTS = [
    (1, "Engineering"),
    (2, "Sales"),
    (3, "Marketing"),
    (4, "Empty"),
]

#: id, name, dept_id, salary, age, email
EMPLOYEES: list[tuple[Any, ...]] = [
    (1, "Alice", 1, 120, 30, "alice@example.com"),
    (2, "Bob", 1, 100, 45, None),
    (3, "Carol", 2, 90, 28, "carol@example.com"),
    (4, "Dave", 2, 80, 52, None),
    (5, "Eve", 3, 70, 39, "eve@example.com"),
    (6, "Frank", None, 60, 23, None),
    (7, "O'Brien", 1, 110, 41, "ob@example.com"),
    (8, "Zoë Ünï", 3, 75, 35, "zoe@example.com"),
]

#: id, select, group, order, MixedCase, unicode column
RESERVED = [
    (1, 10, "g1", 3, "Mc1", "u1"),
    (2, 20, "g2", 2, "Mc2", "u2"),
    (3, 30, "g1", 1, "Mc3", "u3"),
]

UNICODE_COL = "ünï_çol"

T_DEPT = "qbit_departments"
T_EMP = "qbit_employees"
T_RES = "qbit_reserved"
T_MIXED = "QbitMixedCase"


@dataclass(frozen=True)
class Ddl:
    """Per-family DDL fragments."""

    int_t: str = "INTEGER"
    str_t: str = "VARCHAR(100)"
    nint_t: str = "INTEGER"  # nullable int
    nstr_t: str = "VARCHAR(100)"  # nullable string
    quote: str = '"'
    nprefix: str = ""  # N'' prefix for unicode literals (SQL Server)
    pk: bool = True
    fk: bool = True
    table_suffix: str = ""  # e.g. ENGINE = MergeTree ORDER BY id
    not_null: str = " NOT NULL"
    drop: str = "DROP TABLE IF EXISTS {t}"
    pk_inline: bool = True  # PRIMARY KEY (id) clause inside CREATE


FAMILIES: dict[str, Ddl] = {
    "pg": Ddl(),
    "sqlite": Ddl(),
    "duckdb": Ddl(),
    "mysql": Ddl(quote="`"),
    "mssql": Ddl(
        int_t="INT",
        nint_t="INT",
        str_t="NVARCHAR(100)",
        nstr_t="NVARCHAR(100)",
        nprefix="N",
    ),
    "clickhouse": Ddl(
        int_t="Int32",
        nint_t="Nullable(Int32)",
        str_t="String",
        nstr_t="Nullable(String)",
        pk=False,
        fk=False,
        not_null="",
        table_suffix=" ENGINE = MergeTree ORDER BY id",
    ),
    "questdb": Ddl(
        int_t="INT",
        nint_t="INT",
        str_t="STRING",
        nstr_t="STRING",
        pk=False,
        fk=False,
        not_null="",
    ),
    "trino": Ddl(
        int_t="INTEGER", str_t="VARCHAR", nstr_t="VARCHAR", pk=False, fk=False
    ),
}


def _lit(value: Any, d: Ddl) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"{d.nprefix}'{text}'"


def _q(name: str, d: Ddl) -> str:
    return f"{d.quote}{name}{d.quote}"


def schema_statements(family: str) -> list[str]:
    """DROP/CREATE/INSERT statements that build the standard dataset."""
    d = FAMILIES[family]
    q = lambda n: _q(n, d)  # noqa: E731
    pk = ",\n  PRIMARY KEY (id)" if d.pk else ""
    stmts: list[str] = []
    for t in (T_EMP, T_RES, T_MIXED, T_DEPT):
        stmts.append(d.drop.format(t=q(t)))

    stmts.append(
        f"CREATE TABLE {q(T_DEPT)} (\n  id {d.int_t}{d.not_null},\n"
        f"  name {d.str_t}{d.not_null}{pk}\n){d.table_suffix}"
    )
    fk = (
        f",\n  FOREIGN KEY (dept_id) REFERENCES {q(T_DEPT)} (id)"
        if d.fk and d.pk
        else ""
    )
    stmts.append(
        f"CREATE TABLE {q(T_EMP)} (\n  id {d.int_t}{d.not_null},\n"
        f"  name {d.str_t}{d.not_null},\n  dept_id {d.nint_t},\n"
        f"  salary {d.int_t}{d.not_null},\n  age {d.int_t}{d.not_null},\n"
        f"  email {d.nstr_t}{pk}{fk}\n){d.table_suffix}"
    )
    stmts.append(
        f"CREATE TABLE {q(T_RES)} (\n  id {d.int_t}{d.not_null},\n"
        f"  {q('select')} {d.int_t}{d.not_null},\n"
        f"  {q('group')} {d.str_t}{d.not_null},\n"
        f"  {q('order')} {d.int_t}{d.not_null},\n"
        f"  {q('MixedCase')} {d.str_t}{d.not_null},\n"
        f"  {q(UNICODE_COL)} {d.str_t}{d.not_null}{pk}\n){d.table_suffix}"
    )
    stmts.append(
        f"CREATE TABLE {q(T_MIXED)} (\n  id {d.int_t}{d.not_null},\n"
        f"  val {d.str_t}{d.not_null}{pk}\n){d.table_suffix}"
    )
    for row in DEPARTMENTS:
        stmts.append(
            f"INSERT INTO {q(T_DEPT)} (id, name) VALUES "
            f"({_lit(row[0], d)}, {_lit(row[1], d)})"
        )
    for row in EMPLOYEES:
        vals = ", ".join(_lit(v, d) for v in row)
        stmts.append(
            f"INSERT INTO {q(T_EMP)} (id, name, dept_id, salary, age, email) "
            f"VALUES ({vals})"
        )
    cols = ", ".join(
        q(c) for c in ("id", "select", "group", "order", "MixedCase", UNICODE_COL)
    )
    for row in RESERVED:
        vals = ", ".join(_lit(v, d) for v in row)
        stmts.append(f"INSERT INTO {q(T_RES)} ({cols}) VALUES ({vals})")
    stmts.append(f"INSERT INTO {q(T_MIXED)} (id, val) VALUES (1, {_lit('mixed', d)})")
    return stmts


def drop_statements(family: str) -> list[str]:
    d = FAMILIES[family]
    return [d.drop.format(t=_q(t, d)) for t in (T_EMP, T_RES, T_MIXED, T_DEPT)]
