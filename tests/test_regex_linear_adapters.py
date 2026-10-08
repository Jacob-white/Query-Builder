"""Differential tests for the Prisma / Drizzle adapter regex rewrites.

The frozen ``OLD_*`` patterns are verbatim copies of the pre-rewrite regexes; the
tables hold values captured from them before the change.
"""

from __future__ import annotations

import random
import re
from typing import Any

import pytest

from query_builder.adapters import drizzle, prisma

OLD_RELATION = re.compile(
    r"@relation\([^)]*fields\s*:\s*\[([^\]]+)\][^)]*references\s*:\s*\[([^\]]+)\][^)]*\)"
)
OLD_ENUM = re.compile(r"enum\s+(\w+)\s*\{([^}]*)\}", re.MULTILINE)
OLD_MODEL = re.compile(r"model\s+(\w+)\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}", re.MULTILINE)
OLD_COLUMN_CALL = re.compile(r"(\w+)\s*\(\s*(?:['\"`]([^'\"`]*)['\"`])?")

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


RELATION_ATOMS = [
    "@relation(",
    "fields",
    ":",
    "[",
    "]",
    "(",
    ")",
    "references",
    " ",
    "a",
    "b,c",
    "fields:[a]",
    "references: [b]",
    "fields : [",
    "references : [",
    ")",
    "]]",
    "[]",
    "x",
    "\t",
    "@relation(fields: [a], references: [b])",
    '@relation(name: "x", ',
]


def test_random_relation_matches_original_regex() -> None:
    rng = random.Random(41)
    matched = 0
    for _ in range(6000):
        text = "".join(rng.choice(RELATION_ATOMS) for _ in range(rng.randint(1, 16)))
        expected = _groups(OLD_RELATION.search(text))
        assert prisma._match_relation(text) == expected, text
        matched += expected is not None
    assert matched > 500


BLOCK_ATOMS = [
    "model a {",
    "model b{",
    "enum e {",
    "enum",
    "model",
    "{",
    "}",
    "x",
    " ",
    "\n",
    "{x}",
    "a Int",
    "}}",
    "{{",
    "model  c  {",
    "xmodel y {",
]


def test_random_blocks_match_original_regexes() -> None:
    rng = random.Random(42)
    found = 0
    for _ in range(6000):
        text = "".join(rng.choice(BLOCK_ATOMS) for _ in range(rng.randint(1, 14)))
        models = OLD_MODEL.findall(text)
        assert prisma._find_blocks(text, prisma._MODEL_HEADER_RE) == models, text
        enums = OLD_ENUM.findall(text)
        assert prisma._find_blocks(text, prisma._ENUM_HEADER_RE) == enums, text
        found += bool(models or enums)
    assert found > 500


CALL_ATOMS = ["a", "bc", "_", "1", "(", ")", " ", "'", '"', "`", ".", "x(", "\n", "-"]


def test_random_column_call_matches_original_regex() -> None:
    rng = random.Random(43)
    found = 0
    for _ in range(6000):
        text = "".join(rng.choice(CALL_ATOMS) for _ in range(rng.randint(1, 14)))
        expected = _groups(OLD_COLUMN_CALL.search(text))
        assert _groups(drizzle._COLUMN_CALL_RE.search(text)) == expected, text
        found += expected is not None
    assert found > 500


@pytest.mark.parametrize("keyword", ["model", "enum"])
def test_blocks_stop_scanning_when_no_closing_brace(keyword: str) -> None:
    text = f"{keyword} a {{" * 30000
    header = prisma._MODEL_HEADER_RE if keyword == "model" else prisma._ENUM_HEADER_RE
    assert prisma._find_blocks(text, header) == []


# ---------------------------------------------------------------------------------
# Drizzle table headers, balanced calls, literal-then-[^X]+-then-X searches
# ---------------------------------------------------------------------------------
OLD_ASSIGNED_TABLE = re.compile(
    r"(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*(?:pgTable|mysqlTable|sqliteTable)\(\s*['\"`]([^'\"`]+)['\"`]"
)
OLD_TABLE_HEADER = re.compile(
    r"(?:(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*)?(?:pgTable|mysqlTable|sqliteTable)\s*\(\s*['\"`]([^'\"`]+)['\"`]"
)
OLD_ENUM_DECL = re.compile(
    r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:pgEnum|mysqlEnum|sqliteEnum)\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*\[([^\]]+)\]",
    re.MULTILINE,
)
OLD_DEFAULT = re.compile(r"\.default\(([^)]+)\)")
OLD_COLUMNS = re.compile(r"columns\s*:\s*\[([^\]]+)\]")
OLD_PRIMARY_KEY = re.compile(r"primaryKey\(([^)]+)\)")
OLD_PRISMA_ID = re.compile(r"@@id\(\s*\[([^\]]+)\]\s*\)")


def old_balanced_end(code: str, call_start_idx: int) -> int:
    """The original per-header parenthesis balancing loop (verbatim)."""
    depth = 0
    in_quote = None
    call_end_idx = -1
    i = call_start_idx
    while i < len(code):
        ch = code[i]
        if in_quote:
            if ch == in_quote and code[i - 1] != "\\":
                in_quote = None
        elif ch in ("'", '"', "`"):
            in_quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                call_end_idx = i
                break
        i += 1
    return call_end_idx


HEADER_ATOMS = [
    "const ",
    "export ",
    "export  const ",
    "x",
    "tbl",
    ":",
    " ",
    "=",
    "pgTable",
    "mysqlTable",
    "sqliteTable",
    "(",
    ")",
    "'x'",
    '"y"',
    "`z`",
    "'",
    '"',
    "`",
    "\\",
    ", ",
    "{",
    "}",
    "a: T",
    "\n",
    "const",
    "= pgTable(",
    "pgTable ( 'q'",
    " : Foo<Bar> = ",
    "exportconst ",
]


def test_random_table_headers_match_original_regexes() -> None:
    rng = random.Random(51)
    found = 0
    for _ in range(8000):
        text = "".join(rng.choice(HEADER_ATOMS) for _ in range(rng.randint(1, 22)))
        assigned = [(m.group(1), m.group(2)) for m in OLD_ASSIGNED_TABLE.finditer(text)]
        assert drizzle._find_assigned_tables(text) == assigned, text
        expected = [
            (m.start(), m.group(1), m.group(2)) for m in OLD_TABLE_HEADER.finditer(text)
        ]
        got = [
            (h.start, h.variable, h.table) for h in drizzle._find_table_headers(text)
        ]
        assert got == expected, text
        found += bool(expected)
    assert found > 1000


def test_random_balanced_call_ends_match_original_loop() -> None:
    rng = random.Random(52)
    atoms = ["(", ")", "'", '"', "`", "\\", "a", " ", "x(", "')", "'", "\n"]
    for _ in range(8000):
        text = "".join(rng.choice(atoms) for _ in range(rng.randint(1, 24)))
        starts = [i for i, ch in enumerate(text) if ch == "("]
        ends = drizzle._balanced_call_ends(text, starts)
        assert ends == {p: old_balanced_end(text, p) for p in starts}, text
    assert drizzle._balanced_call_ends("x", []) == {}


SEARCH_ATOMS = [
    ".default(",
    "columns",
    ":",
    "[",
    "]",
    "(",
    ")",
    "primaryKey(",
    " ",
    "a,b",
    "const x = pgEnum('e', [",
    "'v'",
    "@@id(",
    "\n",
    "x",
]


def test_random_truncated_searches_match_original_regexes() -> None:
    rng = random.Random(53)
    hits = 0
    for _ in range(8000):
        text = "".join(rng.choice(SEARCH_ATOMS) for _ in range(rng.randint(1, 14)))
        for old, close in (
            (OLD_DEFAULT, ")"),
            (OLD_PRIMARY_KEY, ")"),
            (OLD_COLUMNS, "]"),
        ):
            expected = _groups(old.search(text))
            assert _groups(old.search(drizzle._through_last(text, close))) == expected
            hits += expected is not None
        assert OLD_ENUM_DECL.findall(drizzle._through_last(text, "]")) == (
            OLD_ENUM_DECL.findall(text)
        )
        assert _groups(OLD_PRISMA_ID.search(prisma._through_last_list_close(text))) == (
            _groups(OLD_PRISMA_ID.search(text))
        )
    assert hits > 300
    assert drizzle._through_last("no close", ")") == ""
    assert prisma._through_last_list_close("no bracket") == ""


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
    "const a: T`pgTable ( 'q'\n)\\const, = pgTable(\"= pgTable(()exportconst , constpgTable ( 'q'\n\\'",
    "\"y\"const sqliteTable:pgTable ( 'q'const= pgTable(`z` {",
    "export const t: Foo<pgTable('q')> = pgTable('real', {})",
    "const a: pgTable('q') b = mysqlTable('r', {}) const c = pgTable('s'",
]


def test_annotation_spanning_a_table_keyword_wins_like_the_original() -> None:
    for text in SPANNING_ANNOTATION_CASES:
        expected = [
            (m.start(), m.group(1), m.group(2)) for m in OLD_TABLE_HEADER.finditer(text)
        ]
        got = [
            (h.start, h.variable, h.table) for h in drizzle._find_table_headers(text)
        ]
        assert got == expected, text
        assigned = [(m.group(1), m.group(2)) for m in OLD_ASSIGNED_TABLE.finditer(text)]
        assert drizzle._find_assigned_tables(text) == assigned, text
    # the first case really exercises a head that starts before the keyword it spans
    spanned = drizzle._find_table_headers(SPANNING_ANNOTATION_CASES[2])
    assert [(h.start, h.table) for h in spanned] == [(0, "real")]
