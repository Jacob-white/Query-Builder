"""Golden-snapshot tests for the Prisma / Drizzle adapter regex rewrites.

Expected values (tables here, corpora in ``tests/fixtures/regex_golden_adapters.json``)
were captured from the original super-linear implementations before the rewrite; the
original code is intentionally not kept in the repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from query_builder.adapters import drizzle, prisma

CORPORA = json.loads(
    (Path(__file__).parent / "fixtures" / "regex_golden_adapters.json").read_text(
        encoding="utf-8"
    )
)


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))


REL_TABLE = [
    ("user User @relation(fields: [userId], references: [id])", ("userId", "id")),
    (
        'x @relation(name: "a", fields: [a, b] , references: [c, d], onDelete: Cascade)',
        ("a, b", "c, d"),
    ),
    ("@relation(fields: [a] references: [b]", None),
    ("@relation(fields: [] references: [b])", None),
    ("@relation(fields: [a], references: [])", None),
    ("@relation(references: [b], fields: [a])", None),
    ("@relation(fields: [a), references: [b])", None),
    ("@relation(fields: [a], x) references: [b])", None),
    ("@relation(fields:[a]) @relation(fields:[b], references:[c])", ("b", "c")),
    (
        "x @relation(fields: [a], references: [b], fields: [c], references: [d])",
        ("c", "d"),
    ),
    ("@relation(fields: [a]", None),
    ("no relation here", None),
]
ENUM_TABLE = [
    ("model User {\n id Int @id\n}", []),
    ("model A { x Json @default({}) } model B { y Int }", []),
    ("model A {\n b B[] @relation(fields: [x], references: [y])\n}\n}", []),
    ("model  A  {", []),
    ("model A { {x} {y} }", []),
    ("enum Role { ADMIN USER }", [("Role", " ADMIN USER ")]),
    ("enum R { A } model M { x R }", [("R", " A ")]),
    ("xmodel y {z}", []),
    ("model A { a } stray } model B { b }", []),
]
MODEL_TABLE = [
    ("model User {\n id Int @id\n}", [("User", "\n id Int @id\n")]),
    (
        "model A { x Json @default({}) } model B { y Int }",
        [("A", " x Json @default({"), ("B", " y Int ")],
    ),
    (
        "model A {\n b B[] @relation(fields: [x], references: [y])\n}\n}",
        [("A", "\n b B[] @relation(fields: [x], references: [y])\n")],
    ),
    ("model  A  {", []),
    ("model A { {x} {y} }", [("A", " {x")]),
    ("enum Role { ADMIN USER }", []),
    ("enum R { A } model M { x R }", [("M", " x R ")]),
    ("xmodel y {z}", [("y", "z")]),
    ("model A { a } stray } model B { b }", [("A", " a "), ("B", " b ")]),
]
CALL_TABLE = [
    ("serial('id').primaryKey()", ("serial", "id")),
    ("text('bio')", ("text", "bio")),
    ("varchar('name', { length: 255 })", ("varchar", "name")),
    ('integer("user_id").references(() => users.id)', ("integer", "user_id")),
    ("timestamp('created_at').defaultNow()", ("timestamp", "created_at")),
    ("boolean", None),
    ("  id ( ", ("id", None)),
    ("foo.bar(x)", ("bar", None)),
    ("a b c(d)", ("c", None)),
    ("1a(x)", ("1a", None)),
    ("abc  (  'x' )", ("abc", "x")),
]


def _groups(match: re.Match[str] | None) -> Any:
    return None if match is None else match.groups()


def test_relation_table() -> None:
    for text, expected in REL_TABLE:
        assert prisma._match_relation(text) == expected, text


def test_enum_and_model_tables() -> None:
    for text, expected in ENUM_TABLE:
        assert prisma._find_blocks(text, prisma._ENUM_HEADER_RE) == expected, text
    for text, expected in MODEL_TABLE:
        assert prisma._find_blocks(text, prisma._MODEL_HEADER_RE) == expected, text


def test_column_call_table() -> None:
    for text, expected in CALL_TABLE:
        assert _groups(drizzle._COLUMN_CALL_RE.search(text)) == expected, text


def test_golden_relation_directives() -> None:
    corpus = CORPORA["relation"]
    assert len(corpus) >= 300
    for text, expected in corpus:
        assert jsonable(prisma._match_relation(text)) == expected, text


def test_golden_prisma_blocks() -> None:
    corpus = CORPORA["blocks"]
    assert len(corpus) >= 300
    for text, expected in corpus:
        got = {
            "models": prisma._find_blocks(text, prisma._MODEL_HEADER_RE),
            "enums": prisma._find_blocks(text, prisma._ENUM_HEADER_RE),
        }
        assert jsonable(got) == expected, text


def test_golden_column_calls() -> None:
    corpus = CORPORA["column_call"]
    assert len(corpus) >= 300
    for text, expected in corpus:
        assert jsonable(_groups(drizzle._COLUMN_CALL_RE.search(text))) == expected, text


def test_golden_table_headers() -> None:
    corpus = CORPORA["headers"]
    assert len(corpus) >= 300
    for text, expected in corpus:
        got = {
            "assigned": [list(pair) for pair in drizzle._find_assigned_tables(text)],
            "headers": [
                [h.start, h.variable, h.table]
                for h in drizzle._find_table_headers(text)
            ],
        }
        assert got == expected, text


def test_golden_balanced_call_ends() -> None:
    corpus = CORPORA["balanced_ends"]
    assert len(corpus) >= 300
    for text, expected in corpus:
        starts = [i for i, ch in enumerate(text) if ch == "("]
        ends = drizzle._balanced_call_ends(text, starts)
        assert [ends[p] for p in starts] == expected, text
    assert drizzle._balanced_call_ends("x", []) == {}


def test_golden_truncated_searches() -> None:
    corpus = CORPORA["searches"]
    assert len(corpus) >= 300
    for text, expected in corpus:
        got = {
            "default": _groups(
                drizzle._DEFAULT_CALL_RE.search(drizzle._through_last(text, ")"))
            ),
            "primary_key": _groups(
                drizzle._PRIMARY_KEY_CALL_RE.search(drizzle._through_last(text, ")"))
            ),
            "columns": _groups(
                drizzle._COLUMNS_LIST_RE.search(drizzle._through_last(text, "]"))
            ),
            "enum": drizzle._ENUM_DECL_RE.findall(drizzle._through_last(text, "]")),
            "prisma_id": _groups(
                prisma._ID_LIST_RE.search(prisma._through_last_list_close(text))
            ),
        }
        assert jsonable(got) == expected, text
    assert drizzle._through_last("no close", ")") == ""
    assert prisma._through_last_list_close("no bracket") == ""


@pytest.mark.parametrize("keyword", ["model", "enum"])
def test_blocks_stop_scanning_when_no_closing_brace(keyword: str) -> None:
    text = f"{keyword} a {{" * 30000
    header = prisma._MODEL_HEADER_RE if keyword == "model" else prisma._ENUM_HEADER_RE
    assert prisma._find_blocks(text, header) == []


def test_drizzle_schema_with_annotations_and_nested_calls() -> None:
    source = """
export const roleEnum = pgEnum('role', ['admin', 'user']);
export const users: PgTableWithColumns<any> = pgTable('users', {
  id: serial('id').primaryKey(),
  role: roleEnum('role').default('user'),
});
export const orders = pgTable('orders', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id),
}, (t) => ({ pk: primaryKey({ columns: [t.id, t.userId] }) }));
"""
    tables = drizzle.from_drizzle(source)
    assert set(tables) == {"users", "orders"}
    assert tables["orders"].foreign_keys[0].foreign_table == "users"
    assert tables["users"].columns[1].default == "user"


SPANNING_ANNOTATION_CASES = [
    (
        "const a: T`pgTable ( 'q'\n"
        ")\\const, = pgTable(\"= pgTable(()exportconst , constpgTable ( 'q'\n"
        "\\'",
        [[0, "a", "= pgTable(()exportconst , constpgTable ( "]],
        [["a", "= pgTable(()exportconst , constpgTable ( "]],
    ),
    (
        "\"y\"const sqliteTable:pgTable ( 'q'const= pgTable(`z` {",
        [[3, "sqliteTable", "z"]],
        [["sqliteTable", "z"]],
    ),
    (
        "export const t: Foo<pgTable('q')> = pgTable('real', {})",
        [[0, "t", "real"]],
        [["t", "real"]],
    ),
    (
        "const a: pgTable('q') b = mysqlTable('r', {}) const c = pgTable('s'",
        [[0, "a", "r"], [46, "c", "s"]],
        [["a", "r"], ["c", "s"]],
    ),
]


def test_annotation_spanning_a_table_keyword_wins() -> None:
    for text, headers, assigned in SPANNING_ANNOTATION_CASES:
        got = [
            [h.start, h.variable, h.table] for h in drizzle._find_table_headers(text)
        ]
        assert got == headers, text
        assert [list(p) for p in drizzle._find_assigned_tables(text)] == assigned, text
    # the head starts before the keyword that its annotation spans
    assert SPANNING_ANNOTATION_CASES[2][1] == [[0, "t", "real"]]
