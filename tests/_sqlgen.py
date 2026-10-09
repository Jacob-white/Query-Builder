"""Shared SQL generators, seeds and mutation operators for the differential/fuzz suites.

Not collected by pytest (leading underscore).  Everything here is *grammar-based*: a
composable hypothesis strategy that renders token lists joined by random separators
(whitespace and every comment style), so comments land in every position.

Profiles (``HYPOTHESIS_PROFILE``):

* default ("fast"): deterministic (``derandomize=True``), a few hundred examples per
  property, whole fuzz suite well under a minute.
* ``deep``: 10k+ examples per property, no deadline; run occasionally by maintainers:
  ``HYPOTHESIS_PROFILE=deep python -m pytest -m fuzz -q``.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

settings.register_profile(
    "fast",
    max_examples=int(os.environ.get("FUZZ_FAST_EXAMPLES", "250")),
    derandomize=True,
    deadline=None,
    database=None,
    suppress_health_check=list(HealthCheck),
)
settings.register_profile(
    "deep",
    max_examples=int(os.environ.get("FUZZ_DEEP_EXAMPLES", "12000")),
    derandomize=False,
    deadline=None,
    database=None,
    suppress_health_check=list(HealthCheck),
)
PROFILE = os.environ.get("HYPOTHESIS_PROFILE", "fast")
settings.load_profile(PROFILE)

# --------------------------------------------------------------------------------------
# Lexical building blocks
# --------------------------------------------------------------------------------------

SEPARATORS = st.sampled_from(
    [
        " ",
        " ",
        " ",
        "\n",
        "\t",
        "  ",
        "/**/",
        " /* c */ ",
        "/* -- */",
        "-- c\n",
        " --\n",
        "/* ' */",
        '/* " */',
        "/* ; */",
        "/* /* nested */ */",
        "\r\n",
        "/**/ /**/",
        "--\r\n",
    ]
)

RESTRICTED = "auth_user"
BENIGN_TABLES = ["orders", "customers", "t", "t1", "items", "café", "select", "order"]
COLUMNS = ["id", "name", "amount", "x", "a", "b", "created_at", "password"]


def _quote_styles(name: str) -> list[str]:
    return [
        name,
        name.upper(),
        name.capitalize(),
        f'"{name}"',
        f"`{name}`",
        f"[{name}]",
        f"'{name}'",
        f'"{name.upper()}"',
    ]


QUALIFIERS = ["main", "temp", "public", "pg_catalog", "db", ""]


@st.composite
def table_name(draw, restricted: bool | None = None):
    """A (possibly qualified, possibly quoted) table name token list."""
    if restricted is None:
        restricted = draw(st.booleans())
    base = RESTRICTED if restricted else draw(st.sampled_from(BENIGN_TABLES))
    rendered = draw(st.sampled_from(_quote_styles(base)))
    q = draw(st.sampled_from(QUALIFIERS))
    if q and draw(st.booleans()):
        qr = draw(
            st.sampled_from(_quote_styles(q)[:2] + [f'"{q}"', f"[{q}]", f"`{q}`"])
        )
        dot_sep = draw(st.sampled_from([".", " . ", "/**/./**/", "\n.\n"]))
        return [qr + dot_sep + rendered]
    return [rendered]


STRING_LITERALS = [
    "'a'",
    "'it''s'",
    "''",
    "'--'",
    "'/*'",
    "'*/'",
    "'; DROP TABLE x; --'",
    "'\\'",
    "'a\\'",
    "'\\' OR 1=1 --'",
    "x'41'",
    "'auth_user'",
    "'FROM auth_user'",
    "'$$'",
    "'$a$'",
    "'#'",
    "N'abc'",
    "E'x'",
    "'é'",
    '"dq"',
]
NUMBERS = ["0", "1", "42", "-1", "1.5", ".5", "1e3", "0x1F", "NULL", "TRUE", "FALSE"]


@st.composite
def literal(draw):
    return [draw(st.sampled_from(STRING_LITERALS + NUMBERS))]


# Function calls that are harmless / dangerous / table-valued, across engines.
SAFE_FUNCS = [
    "count",
    "max",
    "min",
    "sum",
    "abs",
    "length",
    "coalesce",
    "lower",
    "upper",
    "typeof",
]
DANGEROUS_FUNCS = [
    "load_extension",
    "readfile",
    "writefile",
    "pg_sleep",
    "sleep",
    "benchmark",
    "pg_read_file",
    "lo_import",
    "query_to_xml",
    "load_file",
    "dblink",
    "read_csv",
    "read_parquet",
    "fts3_tokenizer",
    "pragma_table_info",
    "pragma_database_list",
    "sqlite_compileoption_get",
    "randomblob",
    "zeroblob",
]


def render(draw, toks):
    """Joins tokens with drawn separators (every comment style in every position)."""
    out = []
    for i, t in enumerate(toks):
        if i:
            out.append(draw(SEPARATORS))
        out.append(t)
    return "".join(out)


def flat(parts):
    out: list[str] = []
    for p in parts:
        if isinstance(p, list):
            out.extend(flat(p))
        else:
            out.append(p)
    return out


@st.composite
def expression(draw, depth: int = 0):
    kind = draw(st.integers(0, 6 if depth < 2 else 2))
    if kind == 0:
        return [draw(st.sampled_from(COLUMNS))]
    if kind == 1:
        return draw(literal())
    if kind == 2:
        fn = draw(
            st.sampled_from(
                SAFE_FUNCS + (DANGEROUS_FUNCS if draw(st.booleans()) else [])
            )
        )
        return [fn, "(", *draw(literal()), ")"]
    if kind == 3:
        return ["(", *draw(select_core(depth + 1)), ")"]
    if kind == 4:
        return ["EXISTS", "(", *draw(select_core(depth + 1)), ")"]
    if kind == 5:
        return [
            *draw(expression(depth + 1)),
            draw(st.sampled_from(["+", "||", "=", "AND", "OR", "IN"])),
            *draw(expression(depth + 1)),
        ]
    return [
        draw(st.sampled_from(COLUMNS)),
        "IN",
        "(",
        *draw(select_core(depth + 1)),
        ")",
    ]


@st.composite
def source(draw, depth: int = 0):
    kind = draw(st.integers(0, 5 if depth < 2 else 1))
    if kind <= 1:
        toks = list(draw(table_name()))
        if draw(st.booleans()):
            toks += [
                draw(st.sampled_from(["", "AS"])),
                draw(st.sampled_from(["x", "auth_user", "o", '"auth_user"'])),
            ]
        return [t for t in toks if t]
    if kind == 2:
        return [
            "(",
            *draw(select_core(depth + 1)),
            ")",
            "AS",
            draw(st.sampled_from(["s", "auth_user", "q"])),
        ]
    if kind == 3:
        j = draw(
            st.sampled_from(
                [
                    "JOIN",
                    "LEFT JOIN",
                    "CROSS JOIN",
                    "NATURAL JOIN",
                    "INNER JOIN",
                    ",",
                    "STRAIGHT_JOIN",
                    "LEFT OUTER JOIN",
                ]
            )
        )
        left = draw(source(depth + 1))
        right = draw(source(depth + 1))
        on = (
            []
            if j in {",", "CROSS JOIN", "NATURAL JOIN", "STRAIGHT_JOIN"}
            else ["ON", "1", "=", "1"]
        )
        return [*left, j, *right, *on]
    if kind == 4:
        fn = draw(
            st.sampled_from(
                [
                    "json_each",
                    "json_tree",
                    "pragma_table_info",
                    "pragma_database_list",
                    "generate_series",
                    "read_csv",
                    "unnest",
                    "pg_read_file",
                    "sqlite_master",
                ]
            )
        )
        if fn == "sqlite_master":
            return [fn]
        return [fn, "(", *draw(literal()), ")"]
    return ["(", "VALUES", "(", *draw(literal()), ")", ")", "AS", "v"]


@st.composite
def select_core(draw, depth: int = 0):
    toks = ["SELECT"]
    if draw(st.booleans()):
        toks.append(draw(st.sampled_from(["DISTINCT", "ALL"])))
    ncols = draw(st.integers(1, 2))
    cols = []
    for _ in range(ncols):
        cols.append(draw(st.one_of(st.just(["*"]), expression(depth))))
    for i, c in enumerate(cols):
        if i:
            toks.append(",")
        toks += c
    toks += ["FROM", *draw(source(depth))]
    if draw(st.booleans()):
        toks += ["WHERE", *draw(expression(depth + 1))]
    if draw(st.integers(0, 4)) == 0:
        toks += ["ORDER", "BY", "1"]
    if draw(st.integers(0, 5)) == 0:
        toks += ["LIMIT", "10"]
    return toks


@st.composite
def query(draw, depth: int = 0):
    toks: list[str] = []
    if draw(st.integers(0, 3)) == 0:
        rec = draw(st.booleans())
        n = draw(st.integers(1, 2))
        toks += ["WITH"] + (["RECURSIVE"] if rec else [])
        for i in range(n):
            if i:
                toks.append(",")
            name = draw(
                st.sampled_from(["c1", "auth_user", "t", '"auth_user"', "orders"])
            )
            toks += [name, "AS", "(", *draw(select_core(depth + 1)), ")"]
    toks += draw(select_core(depth))
    for _ in range(draw(st.integers(0, 2)) if draw(st.integers(0, 3)) == 0 else 0):
        toks += [
            draw(st.sampled_from(["UNION", "UNION ALL", "INTERSECT", "EXCEPT"])),
            *draw(select_core(depth + 1)),
        ]
    return toks


DANGEROUS_STATEMENTS = [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "INSERT INTO orders VALUES (1)",
    "UPDATE orders SET id = 1",
    "CREATE TABLE z (a)",
    "ATTACH DATABASE ':memory:' AS z",
    "PRAGMA writable_schema=1",
    "VACUUM",
    "REPLACE INTO orders VALUES (1)",
    "ALTER TABLE orders ADD COLUMN q",
    "SELECT * FROM auth_user",
    "SELECT 1",
    "BEGIN",
    "COMMIT",
    "CREATE TRIGGER g AFTER INSERT ON orders BEGIN SELECT 1; END",
    "CREATE VIEW vv AS SELECT * FROM auth_user",
    "WITH x AS (SELECT 1) DELETE FROM orders",
    "SELECT load_extension('x')",
]


@st.composite
def script(draw):
    """A top-level input: a query, possibly followed by stacked statements."""
    q = draw(query())
    text = render(draw, q)
    if draw(st.integers(0, 3)) == 0:
        stacked = draw(
            st.lists(st.sampled_from(DANGEROUS_STATEMENTS), min_size=1, max_size=2)
        )
        glue = draw(
            st.sampled_from([";", " ; ", ";\n", "/**/;/**/", ";--c\n", "; /* c */ "])
        )
        text += glue + glue.join(stacked)
    return text


# --------------------------------------------------------------------------------------
# Seed corpus (every bypass fixed so far) and mutation
# --------------------------------------------------------------------------------------

SEEDS = [
    "SELECT '--' FROM auth_user",
    "SELECT '--', 1 FROM auth_user WHERE 1=1",
    "SELECT * FROM auth_user",
    "TABLE auth_user",
    "SELECT 1 UNION TABLE auth_user",
    "SELECT * FROM orders STRAIGHT_JOIN auth_user",
    "SELECT * FROM orders, auth_user",
    "SELECT * FROM (SELECT * FROM auth_user)",
    "SELECT * FROM main.auth_user",
    'SELECT * FROM "auth_user"',
    "SELECT * FROM [auth_user]",
    "SELECT * FROM `auth_user`",
    "SELECT * FROM 'auth_user'",
    "SELECT * FROM /* c */ auth_user",
    "SELECT * FROM -- c\n auth_user",
    "SELECT 'a\\' FROM auth_user -- '",
    "SELECT 'a\\'' FROM auth_user",
    "SELECT $$ FROM auth_user $$",
    "SELECT $a$ x $a$ FROM auth_user",
    "SELECT 1 /* /* */ */ FROM auth_user",
    "SELECT /*! 1 */ 1",
    "SELECT 1; DROP TABLE orders",
    "SELECT 1;DELETE FROM orders",
    "SELECT 1 ; /* c */ INSERT INTO orders VALUES (1)",
    "SELECT 1;\nATTACH DATABASE ':memory:' AS z",
    "SELECT 1; PRAGMA writable_schema=1",
    "SELECT 1 # c\n; DROP TABLE orders",
    "SELECT '\\'; DROP TABLE orders; --'",
    "SELECT '' ; DROP TABLE orders",
    "WITH auth_user AS (SELECT 1) SELECT * FROM auth_user",
    "WITH auth_user AS (SELECT * FROM auth_user) SELECT * FROM auth_user",
    "WITH RECURSIVE c AS (SELECT 1 UNION ALL SELECT * FROM auth_user) SELECT * FROM c",
    "WITH c AS (SELECT * FROM auth_user) SELECT * FROM c",
    "SELECT * FROM auth_user AS orders",
    "SELECT * FROM orders AS auth_user",
    "SELECT * FROM pragma_table_info('auth_user')",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM sqlite_schema",
    "SELECT load_extension('x')",
    "SELECT readfile('x')",
    "SELECT * FROM json_each('[1]') JOIN auth_user",
    "SELECT (SELECT password FROM auth_user)",
    "SELECT * FROM orders WHERE id IN (SELECT id FROM auth_user)",
    "SELECT EXISTS (SELECT 1 FROM auth_user)",
    "SELECT * FROM orders NATURAL JOIN auth_user",
    "SELECT * FROM orders CROSS JOIN auth_user",
    "SELECT * FROM orders LEFT JOIN auth_user ON 1=1",
    "SELECT * FROM orders UNION SELECT * FROM auth_user",
    "SELECT * FROM orders INTERSECT SELECT * FROM auth_user",
    "SELECT * FROM orders EXCEPT SELECT * FROM auth_user",
    "(SELECT * FROM auth_user)",
    "((SELECT * FROM auth_user))",
    "VALUES (1) UNION SELECT * FROM auth_user",
    "SELECT * FROM auth_user ",
    'SELECT * FROM main."auth_user"',
    "SELECT * FROM main . auth_user",
    "SELECT 1 INTO x FROM orders",
    "WITH x AS (SELECT 1) DELETE FROM orders",
    "REPLACE INTO orders VALUES (1)",
    "SELECT pg_sleep(1)",
    "SELECT * FROM read_csv('x')",
]

NASTY = [
    "'",
    '"',
    "`",
    "[",
    "]",
    "\\",
    "--",
    "/*",
    "*/",
    ";",
    "$$",
    "#",
    "(",
    ")",
    "\n",
    "\x0b",
    "\x0c",
    "/*!",
    " ",
    ";",
    "；",
    " ",
    ",",
    ".",
    "''",
    "\\'",
    "$a$",
    "-- \n",
    "/**/",
    "x'",
    "E'",
]


@st.composite
def mutated(draw):
    s = draw(st.sampled_from(SEEDS))
    for _ in range(draw(st.integers(1, 4))):
        op = draw(st.integers(0, 4))
        i = draw(st.integers(0, len(s)))
        if op == 0:
            s = s[:i] + draw(st.sampled_from(NASTY)) + s[i:]
        elif op == 1 and s:
            j = min(len(s), i + draw(st.integers(1, 3)))
            s = s[:i] + s[j:]
        elif op == 2 and s:
            j = min(len(s), i + draw(st.integers(1, 12)))
            s = s[:j] + s[i:j] + s[j:]
        elif op == 3:
            s = s[:i] + draw(SEPARATORS) + s[i:]
        else:
            s = s + draw(
                st.sampled_from(
                    [
                        "; DROP TABLE orders",
                        ";SELECT 1",
                        " ; INSERT INTO orders VALUES(1)",
                    ]
                )
            )
    return s


sql_inputs = st.one_of(script(), mutated(), st.sampled_from(SEEDS))


SOUP_VOCAB = (
    [
        "SELECT",
        "FROM",
        "WHERE",
        "JOIN",
        "UNION",
        "WITH",
        "AS",
        "TABLE",
        "VALUES",
        "ON",
        "ALL",
        "ONLY",
        "LATERAL",
        "INTO",
    ]
    + [
        "auth_user",
        "orders",
        "t",
        "x",
        "1",
        "*",
        ",",
        "(",
        ")",
        ";",
        ".",
        "main",
        "AUTH_USER",
        "sqlite_master",
    ]
    + NASTY
    + [
        "'a'",
        "'",
        '"auth_user"',
        "$$",
        "$a$",
        "E'",
        "\\",
        "-- x\n",
        "/* x */",
        "/*",
        "*/",
        "#\n",
    ]
)


@st.composite
def soup(draw):
    """Token soup: random vocabulary sequences; stresses lexer disagreements."""
    toks = draw(st.lists(st.sampled_from(SOUP_VOCAB), min_size=3, max_size=22))
    if draw(st.booleans()):
        toks = ["SELECT", "*", "FROM", *toks]
    return "".join(
        t if i == 0 else draw(st.sampled_from([" ", "", " ", "\n"])) + t
        for i, t in enumerate(toks)
    )


sql_inputs = st.one_of(script(), mutated(), soup(), st.sampled_from(SEEDS))
