"""
Abstract Syntax Tree (AST) SQL Safety Validator.
=================================================
Performs deep AST parsing via sqlparse to strictly verify queries are read-only
SELECT/CTE operations, rejecting SQL injection, semicolon chaining, mutation keywords,
unauthorized schema access, and system/credential table references.
"""

from __future__ import annotations

import itertools
import logging
import re
from functools import lru_cache
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

try:
    import sqlparse
    from sqlparse.tokens import DDL, DML, Keyword
except ImportError:
    sqlparse = None  # type: ignore[assignment]
    DDL = DML = Keyword = None  # type: ignore[assignment]

FORBIDDEN_SQL_PATTERNS = [
    r"\bDROP\b",
    r"\bDELETE\b",
    r"\bUPDATE\b",
    r"\bINSERT\b",
    r"\bALTER\b",
    r"\bTRUNCATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bCREATE\b",
    r"\bEXEC(?:UTE)?\b",
    r"\bCOPY\b",
    r"\bINTO\b",
    r"\bMERGE\b",
    r"\bDO\b(?:\s+\$\$|\s+[0-9a-zA-Z_\(])",
    r"\bCALL\b",
    r"\bREPLACE\s+INTO\b",
    r"\bSET\b(?!\s+(?:TRANSACTION|LOCAL))",
    r"\bATTACH\b",
    r"\bDETACH\b",
    r"\bPRAGMA\b",
    r"\bLOAD_FILE\s*\(",
    r"\bINTO\s+(?:OUTFILE|DUMPFILE)\b",
    r"\b(?:XP_CMDSHELL|SP_EXECUTESQL|SP_MAKEWEBTASK)\b",
    r"\b(?:OPENROWSET|OPENDATASOURCE|OPENQUERY)\b",
    r"\b(?:PG_SLEEP|SLEEP|BENCHMARK)\s*\(",
    r"\bWAITFOR\s+DELAY\b",
    r"\bSHUTDOWN\b",
    r"/\*!",
]

RESTRICTED_MUTATION_KEYWORDS: set[str] = {
    "DELETE",
    "DROP",
    "UPDATE",
    "INSERT",
    "TRUNCATE",
    "ALTER",
    "GRANT",
    "REVOKE",
    "CREATE",
    "EXECUTE",
    "EXEC",
    "INTO",
    "COPY",
    "VACUUM",
    "REINDEX",
    "CLUSTER",
    "LOCK",
    "CALL",
    "MERGE",
    "DO",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "SHUTDOWN",
    "KILL",
    "LOAD_FILE",
    "OUTFILE",
    "DUMPFILE",
    "XP_CMDSHELL",
    "SP_EXECUTESQL",
    "OPENROWSET",
    "OPENDATASOURCE",
    "PG_SLEEP",
    "SLEEP",
    "BENCHMARK",
    "WAITFOR",
}

RESTRICTED_SECURITY_TABLES: set[str] = {
    "AUTH_USER",
    "AUTH_GROUP",
    "AUTH_PERMISSION",
    "AUTH_USER_GROUPS",
    "AUTH_USER_USER_PERMISSIONS",
    "AUTHTOKEN_TOKEN",
    "DJANGO_SESSION",
    "DJANGO_ADMIN_LOG",
    "DJANGO_CONTENT_TYPE",
    "DJANGO_MIGRATIONS",
    "PG_SHADOW",
    "PG_AUTHID",
    "PG_USER",
    "PG_DATABASE",
    "PG_TABLES",
    "PG_STAT_ACTIVITY",
    "PG_ROLES",
    "PG_SETTINGS",
    "PG_CONFIG",
    "PG_CLASS",
    "PG_PROC",
    "PG_TYPE",
    "PG_STATISTIC",
    "PG_STAT_STATEMENTS",
    "PASSWORDS",
    "CREDENTIALS",
    "CRM_CONNECTION",
    "CRM_FIELD_MAPPING",
    "DJANGO_CACHE_TABLE",
    "API_AUDITLOG",
    "USER_PROFILE",
    "SQLITE_MASTER",
    "SQLITE_SCHEMA",
    "SQLITE_TEMP_MASTER",
    "SQLITE_TEMP_SCHEMA",
    "SQLITE_SEQUENCE",
    "SQLITE_STAT1",
    "MYSQL.USER",
    "MYSQL.DB",
    "MYSQL.TABLES_PRIV",
    "MYSQL.COLUMNS_PRIV",
    "SYS.OBJECTS",
    "SYS.TABLES",
    "SYS.SCHEMAS",
    "SYS.DATABASE_PRINCIPALS",
    "SYS.SQL_LOGINS",
    "SYS.SYSLOGINS",
    "INFORMATION_SCHEMA.TABLES",
    "INFORMATION_SCHEMA.COLUMNS",
}

DEFAULT_RESTRICTED_SCHEMA_NAMES: set[str] = {
    "PUBLIC",
    "PG_CATALOG",
    "INFORMATION_SCHEMA",
    "MYSQL",
    "PERFORMANCE_SCHEMA",
    "SYS",
    "MSDB",
    "MASTER",
    "SNOWFLAKE",
}

# Unambiguous (no nested quantifiers over whitespace): every position has exactly one
# way to match, and the dot/space run is possessive, so matching is linear.
DEFAULT_RESTRICTED_SCHEMA_PATTERNS: list[str] = [
    r"(?<![\w$])[\"`\[]?(PUBLIC|PG_CATALOG|INFORMATION_SCHEMA|MYSQL|PERFORMANCE_SCHEMA|SYS|MSDB|MASTER|SNOWFLAKE)[\"`\]]?\s*\.[\s.]*+[\"`\[]?([a-zA-Z0-9_]+)[\"`\]]?",
]

MAX_SQL_LENGTH = 100_000
MAX_AST_TOKENS = 10_000
# sqlparse grouping is quadratic in the number of comment tokens (1000 comments ~0.3s,
# 4000 ~4s); no legitimate analytical query carries this many.
MAX_COMMENTS = 500

# Linear-time approximation of sqlparse's flattened token count.  Terminated quoted
# strings / identifiers and comments are one token, a word run is one token, and every
# other character (including each whitespace character, as sqlparse emits them) is one
# token.  Unterminated quotes / block comments are NOT one token for sqlparse (it emits
# one error token per character), so they are counted per character.
_ESTIMATE_TOKEN_RE = re.compile(
    r"""(?P<s>'(?:[^'\\]++|''|\\.?)*+(?:'|(?P<us>\Z)))"""
    r"""|(?P<d>"(?:[^"\\]++|""|\\.?)*+(?:"|(?P<ud>\Z)))"""
    r"|(?P<b>`[^`]*+(?:`|(?P<ub>\Z)))"
    r"|(?P<c>--[^\r\n]*+)"
    r"|(?P<m>/\*(?:(?!\*/).)*+(?:\*/|(?P<um>\Z)))"
    r"|\w++"
    r"|.",
    re.DOTALL,
)


def _estimate_token_count(sql: str, limit: int) -> tuple[int, int]:
    """Returns ``(estimated token count, number of comments)`` in one linear pass.

    Stops counting as soon as the estimate exceeds ``limit``.
    """
    tokens = comments = 0
    for m in _ESTIMATE_TOKEN_RE.finditer(sql):
        kind = m.lastgroup
        if kind is None:
            tokens += 1
            continue
        if kind == "c" or kind == "m":
            comments += 1
        if kind in ("c", "w") or m.groupdict().get("u" + kind) is None:
            tokens += 1
        else:
            tokens += len(m.group())
        if tokens > limit:
            break
    return tokens, comments


# `FROM` (not as a prefix of a longer identifier) plus optional ONLY/LATERAL modifiers.
_FROM_PREFIX_RE = r"\bFROM(?![\w$])\s*(?:(?:ONLY|LATERAL)\b\s*)*"

_IDENTIFIER_QUOTES: dict[str, str] = {'"': '"', "`": "`", "[": "]"}


def _clean_ident_part(p: str) -> str:
    """Strips all whitespace and quote/bracket characters from an identifier segment."""
    return p.strip().strip('"`[]').strip().upper()


# Keywords that end a FROM clause body.  Matched in place (``match(sql, i)``) rather than
# on a ``sql[i:]`` slice per character, which copied the rest of the text every time.
_FROM_BODY_END_RE = re.compile(
    r"(WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|UNION|INTERSECT|EXCEPT|WINDOW|FETCH|FOR)\b",
    re.IGNORECASE,
)


def _extract_from_body(sql: str, start_idx: int) -> str:
    """Extracts the body of a FROM clause starting at start_idx with balanced parentheses."""
    depth = 0
    i = start_idx
    length = len(sql)
    while i < length:
        ch = sql[i]
        if ch in _IDENTIFIER_QUOTES:
            quote_close = _IDENTIFIER_QUOTES[ch]
            j = i + 1
            while j < length and sql[j] != quote_close:
                j += 1
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
            else:
                break
        elif ch == ";" or (depth == 0 and _FROM_BODY_END_RE.match(sql, i)):
            break
        i += 1
    return sql[start_idx:i].strip()


def _split_from_items(from_body: str) -> list[str]:
    """Splits a FROM clause body on commas at parenthesis nesting level 0."""
    items: list[str] = []
    depth = 0
    start = 0
    i = 0
    length = len(from_body)
    while i < length:
        ch = from_body[i]
        if ch in _IDENTIFIER_QUOTES:
            quote_close = _IDENTIFIER_QUOTES[ch]
            j = i + 1
            while j < length and from_body[j] != quote_close:
                j += 1
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            items.append(from_body[start:i].strip())
            start = i + 1
        i += 1
    items.append(from_body[start:].strip())
    return items


class _LexMode(NamedTuple):
    """One lexical interpretation of the SQL text.

    The validator has no dialect parameter and dialects disagree about these rules, so the
    same text is lexed under every combination of the settings that could change what is
    code and what is literal/comment (see ``_lex_variants``).
    """

    backslash: bool = True  # backslash escapes inside '..' and ".." (MySQL, PG E'..')
    hash_comment: bool = False  # `#` starts a line comment (MySQL)
    dollar: bool = False  # $tag$ .. $tag$ dollar-quoted strings (PostgreSQL, DuckDB)
    bracket: bool = False  # [..] is a quoted identifier (SQL Server, SQLite)
    nested: bool = False  # /* .. /* .. */ .. */ nests (PostgreSQL)
    strict_dash: bool = (
        False  # `--` is a comment only when followed by whitespace (MySQL)
    )


# Opens of a dollar-quote tag: $$ or $tag$ (the tag may not start with a digit).
_DOLLAR_OPEN = r"(?<![\w$])\$(?:[^\W\d]\w*)?\$"
_BLOCK_DELIMS_RE = re.compile(r"/\*|\*/")


@lru_cache(maxsize=128)
def _lex_pattern(mode: _LexMode) -> re.Pattern[str]:
    """Builds the single left-to-right scanner for ``mode``.

    Every alternative uses possessive quantifiers / atomic structure so that each input
    position has exactly one way to match: scanning is linear (no ReDoS), and an
    unterminated literal/comment/identifier deliberately swallows the rest of the text.
    """
    if mode.backslash:
        string = r"(?P<str>'(?:[^'\\]++|''|\\.?)*+(?:'|(?P<ustr>\Z)))"
        dquote = r'(?P<dq>"(?:[^"\\]++|""|\\.?)*+(?:"|(?P<udq>\Z)))'
    else:
        string = r"(?P<str>'(?:[^']++|'')*+(?:'|(?P<ustr>\Z)))"
        dquote = r'(?P<dq>"(?:[^"]++|"")*+(?:"|(?P<udq>\Z)))'
    parts = [
        string,
        dquote,
        r"(?P<bt>`(?:[^`]++|``)*+(?:`|(?P<ubt>\Z)))",
        r"(?P<bc>/\*)",
    ]
    if mode.strict_dash:
        parts.append(r"(?P<lc>--(?=[\s\x00-\x1f]|\Z)[^\r\n]*+)")
    else:
        parts.append(r"(?P<lc>--[^\r\n]*+)")
    if mode.hash_comment:
        parts.append(r"(?P<hc>\#[^\r\n]*+)")
    if mode.bracket:
        # SQL Server / SQLite: anything up to `]` is an identifier.
        parts.append(r"(?P<br>\[(?:[^\]]++|\]\])*+(?:\]|(?P<ubr>\Z)))")
    else:
        # Other dialects: `[` is an array subscript / plain punctuation, so only a
        # simple bracketed word (no quotes, parens, `;`) is treated as an identifier;
        # anything richer stays visible as code (and its quotes are lexed normally).
        parts.append(r"""(?P<br>\[[^\]\[;'"`()]*+\])""")
    if mode.dollar:
        parts.append(f"(?P<dl>{_DOLLAR_OPEN})")
    return re.compile("|".join(parts), re.DOTALL)


def _skip_block_comment(sql: str, pos: int, nested: bool) -> tuple[int, bool]:
    """Returns ``(index just past the block comment whose body starts at pos, closed)``."""
    if not nested:
        close = sql.find("*/", pos)
        return (len(sql), False) if close < 0 else (close + 2, True)
    depth = 1
    for m in _BLOCK_DELIMS_RE.finditer(sql, pos):
        depth += 1 if m.group() == "/*" else -1
        if depth == 0:
            return m.end(), True
    return len(sql), False


class _Lexed(NamedTuple):
    """Result of lexing under one interpretation (see ``_lex``)."""

    stripped: str
    masked: str
    terminated: bool
    # For an unterminated interpretation: the (stripped, masked) text up to and including
    # the last code `;` before the dangling construct, i.e. the only part an engine could
    # execute (statements before the syntax error).  None when terminated.
    executable: tuple[str, str] | None


def _lex(sql: str, mode: _LexMode) -> _Lexed:
    """Single-pass lexer for one interpretation.

    Comments become a space and string / dollar-quoted literals become ``''``.
    ``stripped`` keeps quoted identifiers verbatim (needed for table-name checks);
    ``masked`` replaces them with ``"ident"`` so that nothing inside any quoting
    construct can be mistaken for code (used for keyword / ``;`` checks).

    When a string / identifier / dollar quote / block comment is still open at the end of
    the text the interpretation is a syntax error for the dialect it models.  Its
    ``stripped`` / ``masked`` then keep the unlexed remainder verbatim (fail-closed, used
    only if *every* interpretation is unterminated) and ``executable`` holds the part
    before the dangling construct that ends at its last ``;``.
    """
    search = _lex_pattern(mode).search
    total = len(sql)
    stripped: list[str] = []
    masked: list[str] = []
    last_semi: tuple[int, int] | None = None  # (part index, offset after the `;`)
    dangling_at = -1
    pos = 0
    while pos < total:
        m = search(sql, pos)
        if m is None:
            gap = sql[pos:]
            if ";" in gap:
                last_semi = (len(stripped), gap.rfind(";") + 1)
            stripped.append(gap)
            masked.append(gap)
            break
        if m.start() > pos:
            gap = sql[pos : m.start()]
            if ";" in gap:
                last_semi = (len(stripped), gap.rfind(";") + 1)
            stripped.append(gap)
            masked.append(gap)
        kind = m.lastgroup
        end = m.end()
        if kind == "str":
            if m.group("ustr") is not None:
                dangling_at = m.start()
                break
            stripped.append("''")
            masked.append("''")
        elif kind in ("dq", "bt", "br"):
            if m.groupdict().get("u" + kind) is not None:
                dangling_at = m.start()
                break
            stripped.append(m.group())
            masked.append(' "ident" ')
        elif kind == "dl":
            tag = m.group()
            close = sql.find(tag, end)
            if close < 0:
                dangling_at = m.start()
                break
            end = close + len(tag)
            stripped.append("''")
            masked.append("''")
        else:  # line / hash / block comments
            if kind == "bc":
                end, closed = _skip_block_comment(sql, end, mode.nested)
                if not closed:
                    dangling_at = m.start()
                    break
            stripped.append(" ")
            masked.append(" ")
        pos = end

    if dangling_at < 0:
        return _Lexed("".join(stripped), "".join(masked), True, None)

    executable: tuple[str, str] | None = None
    if last_semi is not None:
        idx, off = last_semi
        executable = (
            "".join(stripped[:idx]) + stripped[idx][:off],
            "".join(masked[:idx]) + masked[idx][:off],
        )
    rest = sql[dangling_at:]
    return _Lexed("".join(stripped) + rest, "".join(masked) + rest, False, executable)


def _lex_variants(sql: str) -> list[tuple[str, str]]:
    """Lexes ``sql`` under every dialect-dependent interpretation that could matter.

    Only the settings whose trigger characters occur in the text are varied, and
    interpretations that yield identical text are collapsed.  The caller validates every
    distinct result and takes the union of violations (fail-closed).

    An interpretation that leaves a quote or block comment open is a syntax error for the
    dialect it models, e.g. ``'it\\'s'`` where a backslash is an ordinary character leaves
    a dangling quote.  Such an engine can at most run the statements that precede the
    error, so only that executable prefix is validated for it (this keeps a literal like
    ``'it\\'s a drop'`` from being mistaken for code).  If every interpretation is
    unterminated, their full text is validated instead.
    """
    dims = (
        (True, False) if "\\" in sql else (True,),
        (True, False) if "#" in sql else (False,),
        (True, False) if "$" in sql else (False,),
        (True, False) if "[" in sql else (False,),
        (True, False) if sql.count("/*") > 1 else (False,),
        (True, False) if "--" in sql else (False,),
    )
    complete: dict[tuple[str, str], None] = {}
    prefixes: dict[tuple[str, str], None] = {}
    dangling: dict[tuple[str, str], None] = {}
    for combo in itertools.product(*dims):
        lexed = _lex(sql, _LexMode(*combo))
        if lexed.terminated:
            complete.setdefault((lexed.stripped, lexed.masked), None)
        else:
            dangling.setdefault((lexed.stripped, lexed.masked), None)
            if lexed.executable is not None and lexed.executable[1].strip(" ;\t\r\n"):
                prefixes.setdefault(lexed.executable, None)
    if complete:
        return list(complete) + [p for p in prefixes if p not in complete]
    return list(dangling)


def strip_sql_comments_and_literals(sql: str) -> str:
    """
    Strips comments (``--``, ``/* ... */``) and string literals (handling ``''`` and
    backslash escapes) in one left-to-right pass, replacing literals with ``''``.
    This is the default (MySQL-like backslash) interpretation; ``validate_sql_ast``
    additionally checks the other dialect interpretations.
    """
    return _lex(sql, _LexMode())[0]


# --------------------------------------------------------------------------------------
# Token based relation / function extraction (linear time, no whitespace-ambiguous regex)
# --------------------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r'(?P<q>"(?:[^"]++|"")*+(?:"|\Z)'
    r"|`(?:[^`]++|``)*+(?:`|\Z)"
    r"""|\[[^\]\[;'"`()]*+\])"""
    r"|(?P<w>[\w$]++)"
    r"|(?P<p>\S)"
)

# A token is (kind, value): kind 'w' word (value upper-cased), 'q' quoted identifier
# (value unquoted + upper-cased), 'p' single punctuation / other character.
_Token = tuple[str, str]

_RELATION_ANCHORS = frozenset(
    {"FROM", "JOIN", "APPLY", "STRAIGHT_JOIN", "TABLE", "LATERAL", "ONLY", "USING"}
)
_RELATION_MODIFIERS = frozenset({"ONLY", "LATERAL"})
_FROM_LIST_TERMINATORS = frozenset(
    {
        "WHERE",
        "GROUP",
        "ORDER",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "UNION",
        "INTERSECT",
        "EXCEPT",
        "WINDOW",
        "FETCH",
        "FOR",
        "QUALIFY",
        "RETURNING",
    }
)

# Functions that execute SQL passed as a string, or read arbitrary files / remote data.
# Their arguments are string literals (stripped before the table checks), so the *call*
# itself must be denied.  Matched against the final identifier before a `(`.
_DENIED_FUNCTIONS = frozenset(
    {
        # PostgreSQL
        "QUERY_TO_XML",
        "QUERY_TO_XMLSCHEMA",
        "QUERY_TO_XML_AND_XMLSCHEMA",
        "CURSOR_TO_XML",
        "CURSOR_TO_XMLSCHEMA",
        "TABLE_TO_XML",
        "TABLE_TO_XMLSCHEMA",
        "TABLE_TO_XML_AND_XMLSCHEMA",
        "SCHEMA_TO_XML",
        "SCHEMA_TO_XMLSCHEMA",
        "SCHEMA_TO_XML_AND_XMLSCHEMA",
        "DATABASE_TO_XML",
        "DATABASE_TO_XMLSCHEMA",
        "DATABASE_TO_XML_AND_XMLSCHEMA",
        "PG_READ_FILE",
        "PG_READ_BINARY_FILE",
        "PG_LS_DIR",
        "PG_STAT_FILE",
        "PG_EXECUTE_SERVER_PROGRAM",
        "SET_CONFIG",
        "PG_TERMINATE_BACKEND",
        "PG_CANCEL_BACKEND",
        "PG_RELOAD_CONF",
        # MySQL / MariaDB
        "LOAD_FILE",
        "EXTRACTVALUE",
        "UPDATEXML",
        "SYS_EXEC",
        "SYS_EVAL",
        # SQLite
        "LOAD_EXTENSION",
        "READFILE",
        "WRITEFILE",
        "FTS3_TOKENIZER",
        # SQL Server
        "OPENROWSET",
        "OPENQUERY",
        "OPENDATASOURCE",
        "OPENXML",
        "SP_EXECUTESQL",
        "SP_MAKEWEBTASK",
        # DuckDB
        "QUERY",
        "QUERY_TABLE",
        "SNIFF_CSV",
        # ClickHouse table functions
        "FILE",
        "URL",
        "S3",
        "S3CLUSTER",
        "REMOTE",
        "REMOTESECURE",
        "JDBC",
        "ODBC",
        "HDFS",
        "EXECUTABLE",
        "MYSQL",
        "POSTGRESQL",
        # Snowflake: resolves a table from a string
        "IDENTIFIER",
    }
)
_DENIED_FUNCTION_PREFIXES = (
    "DBLINK",
    "LO_",
    "LOREAD",
    "LOWRITE",
    "PG_LS_",
    "PG_READ_",
    "DBMS_",
    "UTL_",
    "XP_",
    "SP_OA",
    "READ_CSV",
    "READ_PARQUET",
    "READ_JSON",
    "READ_NDJSON",
    "READ_TEXT",
    "READ_BLOB",
    "PARQUET_",
    "SYSTEM$",
)


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        if kind == "w":
            tokens.append(("w", m.group().upper()))
        elif kind == "q":
            tokens.append(("q", _clean_ident_part(m.group())))
        else:
            tokens.append(("p", m.group()))
    return tokens


def _read_dotted_name(tokens: list[_Token], i: int) -> tuple[list[str], bool, int]:
    """Reads ``a.b..c`` starting at ``i`` -> (parts, saw_double_dot, next_index)."""
    parts = [tokens[i][1]]
    double_dot = False
    j = i + 1
    n = len(tokens)
    while j < n and tokens[j] == ("p", "."):
        k = j
        while k < n and tokens[k] == ("p", "."):
            k += 1
        if k >= n or tokens[k][0] == "p":
            break
        if k - j > 1:
            double_dot = True
        parts.append(tokens[k][1])
        j = k + 1
    return [p for p in parts if p], double_dot, j


def _restricted_name(
    parts: list[str], double_dot: bool, restricted: set[str], *, relation: bool
) -> str | None:
    """Returns the restricted table name matched by a dotted name, if any.

    ``relation`` is True when the name is known to be in a table position (FROM/JOIN/...),
    where the bare last part is enough; elsewhere a bare table is only a column/alias,
    so a restricted table needs schema qualification (3+ parts or a double dot).
    """
    if not parts:
        return None
    for a, b in zip(parts, parts[1:], strict=False):
        if f"{a}.{b}" in restricted:
            return f"{a}.{b}"
    base = parts[-1]
    if base in restricted and (relation or len(parts) >= 3 or double_dot):
        return base
    return None


_RESTRICTED_TABLE_MSG = (
    "Access Denied: Table '{}' is restricted. "
    "Authentication, credentials, and session data cannot be queried."
)


def _check_relations(
    tokens: list[_Token], restricted: set[str], violations: list[str]
) -> None:
    """Flags restricted tables in every relation position of the token stream.

    Relation positions: after FROM / JOIN / APPLY / STRAIGHT_JOIN / TABLE / LATERAL /
    ONLY / USING, and after each top-level comma of a FROM list.  Also flags dotted
    names anywhere (schema.table, db.schema.table, db..table).
    """
    n = len(tokens)

    def check_relation_at(j: int) -> None:
        while j < n and (
            tokens[j] == ("p", "(")
            or (tokens[j][0] == "w" and tokens[j][1] in _RELATION_MODIFIERS)
        ):
            j += 1
        if j < n and tokens[j][0] != "p":
            parts, dd, _ = _read_dotted_name(tokens, j)
            hit = _restricted_name(parts, dd, restricted, relation=True)
            if hit:
                violations.append(_RESTRICTED_TABLE_MSG.format(hit))

    depth = 0
    from_list: dict[int, bool] = {}
    for i, (kind, val) in enumerate(tokens):
        if kind == "p":
            if val == "(":
                depth += 1
            elif val == ")":
                from_list.pop(depth, None)
                depth = max(0, depth - 1)
            elif val == "," and from_list.get(depth):
                check_relation_at(i + 1)
            elif val == ";":
                from_list.clear()
            continue
        if kind != "w" or (i > 0 and tokens[i - 1] == ("p", ".")):
            continue
        if val in _RELATION_ANCHORS:
            if val == "USING" and i + 1 < n and tokens[i + 1] == ("p", "("):
                continue
            check_relation_at(i + 1)
            if val == "FROM":
                from_list[depth] = True
        elif val in _FROM_LIST_TERMINATORS:
            from_list[depth] = False

    # Dotted names anywhere (e.g. mysql.user, db.schema.auth_user, db..auth_user).
    i = 0
    while i < n:
        if tokens[i][0] != "p":
            parts, dd, nxt = _read_dotted_name(tokens, i)
            if len(parts) >= 2:
                hit = _restricted_name(parts, dd, restricted, relation=False)
                if hit:
                    violations.append(_RESTRICTED_TABLE_MSG.format(hit))
            i = nxt
        else:
            i += 1


def _check_denied_functions(tokens: list[_Token], violations: list[str]) -> None:
    for i in range(len(tokens) - 1):
        kind, val = tokens[i]
        if kind == "p" or tokens[i + 1] != ("p", "("):
            continue
        # Check the function name and every qualifier before it (dbms_xmlgen.getxml(...),
        # pg_catalog.pg_read_file(...)): either part may be the dangerous one.
        names = [val]
        j = i - 1
        while j >= 1 and tokens[j] == ("p", ".") and tokens[j - 1][0] != "p":
            names.append(tokens[j - 1][1])
            j -= 2
        for pos, name in enumerate(names):
            # Only the final name is matched against the exact-name list; qualifiers
            # (schemas / packages) are matched by prefix only, so an alias such as
            # `url` or `file` is not mistaken for a table function.
            if name.startswith(_DENIED_FUNCTION_PREFIXES) or (
                pos == 0 and name in _DENIED_FUNCTIONS
            ):
                violations.append(
                    f"Access Denied: Function '{name}' can execute arbitrary SQL or read "
                    "external files/data and is not permitted."
                )


def _extract_cte_root_statement(stmt: sqlparse.sql.Statement) -> str:
    """Finds the root statement keyword (e.g. SELECT, DO, MERGE, DELETE) for a CTE."""
    found_with = False
    in_cte_def = False
    tokens = [
        t
        for t in stmt.tokens
        if not t.is_whitespace
        and t.ttype
        not in (
            sqlparse.tokens.Comment,
            sqlparse.tokens.Comment.Single,
            sqlparse.tokens.Comment.Multiline,
        )
    ]
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        v = tok.value.upper().strip('"[]`')
        if v == "WITH":
            found_with = True
            idx += 1
            continue
        if found_with:
            if v == "RECURSIVE":
                idx += 1
                continue
            if isinstance(tok, (sqlparse.sql.Identifier, sqlparse.sql.IdentifierList)):
                idx += 1
                continue
            if tok.ttype in (
                sqlparse.tokens.Punctuation,
                sqlparse.tokens.Keyword.CTE,
            ) and v in (",", "AS"):
                in_cte_def = True
                idx += 1
                continue
            if in_cte_def and isinstance(tok, sqlparse.sql.Parenthesis):
                in_cte_def = False
                idx += 1
                continue
            if isinstance(tok, sqlparse.sql.Parenthesis):
                inner = [
                    it.value.upper().strip('"[]`')
                    for it in tok.tokens
                    if not it.is_whitespace
                    and it.ttype
                    not in (
                        sqlparse.tokens.Comment,
                        sqlparse.tokens.Comment.Single,
                        sqlparse.tokens.Comment.Multiline,
                    )
                    and it.value not in ("(", ")")
                ]
                return inner[0] if inner else "UNKNOWN"
            return v
        idx += 1
    return "UNKNOWN"


def _check_variant(
    stripped: str,
    masked: str,
    violations: list[str],
    *,
    effective_keywords: set[str],
    effective_tables: set[str],
    schema_patterns: list[str],
    allowed_upper: set[str],
) -> None:
    """Runs every text-based check on one lexical interpretation of the query."""
    # Restricted system/security schemas
    schema_denied = False
    for pattern in schema_patterns:
        for m in re.finditer(pattern, stripped, re.IGNORECASE):
            if m.lastindex and m.lastindex >= 1:
                matched_schema = _clean_ident_part(m.group(1))
            else:
                matched_schema = _clean_ident_part(m.group(0).split(".", 1)[0])
            if allowed_upper and matched_schema in allowed_upper:
                continue
            schema_denied = True
            break
        if schema_denied:
            break
    if schema_denied:
        violations.append(
            "Access Denied: Queries may only target allowed analytical datasets."
        )

    tokens = _tokenize(stripped)
    for kind, val in tokens:
        if kind == "w" and val in effective_keywords:
            violations.append(f"Forbidden mutation keyword: '{val}'")
    _check_relations(tokens, effective_tables, violations)
    _check_denied_functions(tokens, violations)

    # Regex safety fallback against obfuscated mutations (quoted identifiers masked)
    for pattern in FORBIDDEN_SQL_PATTERNS:
        match = re.search(pattern, masked, re.IGNORECASE)
        if match:
            matched_kw = " ".join(match.group(0).upper().split())
            if f"Forbidden mutation keyword: '{matched_kw}'" not in violations:
                violations.append(
                    f"Forbidden mutation pattern detected: '{matched_kw}'"
                )


def _finalize(
    violations: list[str],
    stmt_type: str,
    is_cte: bool,
    cte_root: str,
    first_val: str,
) -> dict[str, Any]:
    unique_violations = list(dict.fromkeys(violations))
    is_valid = len(unique_violations) == 0
    detected_type = (
        "SELECT"
        if (stmt_type == "SELECT" or (is_cte and cte_root == "SELECT"))
        else (stmt_type or first_val or "UNKNOWN")
    )

    risk = "NONE"
    if not is_valid:
        if any(
            "MUTATION" in v.upper()
            or "KEYWORD" in v.upper()
            or "CHAINING" in v.upper()
            or "DENIED" in v.upper()
            or "SEPARATOR" in v.upper()
            or "COMMENT" in v.upper()
            or "NULL BYTE" in v.upper()
            for v in unique_violations
        ):
            risk = "CRITICAL"
        else:
            risk = "HIGH"

    return {
        "valid": is_valid,
        "ast_validated": True,
        "statement_type": detected_type,
        "is_read_only": is_valid,
        "violations": unique_violations,
        "injection_risk": risk,
        "message": "Query passed AST validation and read-only policy."
        if is_valid
        else unique_violations[0],
    }


def validate_sql_ast(
    raw_sql: str,
    allowed_schemas: list[str] | None = None,
    restricted_tables: set[str] | None = None,
    restricted_keywords: set[str] | None = None,
    restricted_schema_patterns: list[str] | None = None,
    allow_cte: bool = True,
    allow_recursive_cte: bool = False,
    max_sql_length: int = MAX_SQL_LENGTH,
    max_ast_tokens: int = MAX_AST_TOKENS,
) -> dict[str, Any]:
    """
    Performs Abstract Syntax Tree (AST) validation using sqlparse.
    Verifies that:
    1. The SQL string is non-empty and within length bounds.
    2. No null bytes, disallowed control characters, or executable comment tricks are present.
    3. Exactly one non-empty statement exists (rejecting semicolon query chaining/injection).
    4. The statement type is 'SELECT' (or safe CTE WITH where the root operation is SELECT).
    5. No AST tokens match restricted DDL/DML mutation keywords or injection functions.
    6. No restricted security, credential, or administration tables are accessed.
    7. No restricted system/catalog schemas are queried without explicit authorization.

    Returns a dictionary detailing validation status, detected statement type, violations, and injection risk.
    """
    clean = (raw_sql or "").strip()
    if not clean:
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "NONE",
            "is_read_only": True,
            "violations": ["Query string is empty."],
            "injection_risk": "NONE",
            "message": "No query provided.",
        }

    if len(clean) > max_sql_length:
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "NONE",
            "is_read_only": False,
            "violations": [
                f"Query length ({len(clean)}) exceeds maximum allowed length ({max_sql_length})."
            ],
            "injection_risk": "HIGH",
            "message": "Query length exceeds maximum allowed limit.",
        }

    if "\x00" in clean:
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "NONE",
            "is_read_only": False,
            "violations": ["Null byte detected in query string."],
            "injection_risk": "CRITICAL",
            "message": "Null byte injection blocked.",
        }

    violations: list[str] = []

    if re.search(r"[\uff1b\u037e\u2044]", clean):
        violations.append("Obfuscated statement separator detected.")

    if any(ord(c) < 32 and c not in ("\t", "\n", "\r") for c in clean):
        violations.append("Disallowed control character detected in query string.")

    if "/*!" in clean:
        violations.append("Forbidden executable comment syntax ('/*!... */') detected.")

    if sqlparse is None:
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "UNKNOWN",
            "is_read_only": False,
            "violations": [
                "sqlparse is not installed. Install with 'pip install sqlparse' to enable AST validation."
            ],
            "injection_risk": "HIGH",
            "message": "AST validation unavailable: sqlparse package not found.",
        }

    # sqlparse's grouping is super-linear in the token count, so bound the work BEFORE
    # parsing with a cheap linear estimate (never rejects less than the exact check below).
    estimated_tokens, comment_count = _estimate_token_count(clean, max_ast_tokens)
    if estimated_tokens > max_ast_tokens:
        violations.append(
            f"Query AST token count ({estimated_tokens}) exceeds safety threshold ({max_ast_tokens})."
        )
        return _finalize(violations, "UNKNOWN", False, "", "")
    if comment_count > MAX_COMMENTS:
        violations.append(
            f"Query contains too many comments (more than {MAX_COMMENTS}); "
            "comment-heavy input is rejected to bound parsing cost."
        )
        return _finalize(violations, "UNKNOWN", False, "", "")

    try:
        parsed = sqlparse.parse(clean)
    except Exception:  # noqa: BLE001
        # The result is returned to API clients, so it must not carry parser internals; the
        # exception is available to operators through debug logging.
        logger.debug("sqlparse failed to parse validated SQL", exc_info=True)
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "ERROR",
            "is_read_only": False,
            "violations": ["Malformed SQL failed AST parsing."],
            "injection_risk": "CRITICAL",
            "message": "Query failed AST parsing.",
        }

    statements = [s for s in parsed if s.value.strip().strip(";")]
    if len(statements) == 0:
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "NONE",
            "is_read_only": True,
            "violations": ["Query contains no executable statements."],
            "injection_risk": "NONE",
            "message": "No query provided.",
        }

    if len(statements) > 1:
        return {
            "valid": False,
            "ast_validated": True,
            "statement_type": "MULTI_STATEMENT",
            "is_read_only": False,
            "violations": [
                "Multiple statements detected. Semicolon query chaining is not permitted."
            ],
            "injection_risk": "CRITICAL",
            "message": "Multiple statements detected. Query chaining is blocked.",
        }

    stmt = statements[0]
    stmt_type = stmt.get_type()

    # Find the first non-comment, non-whitespace token
    first_token = None
    for tok in stmt.tokens:
        if not tok.is_whitespace and tok.ttype not in (
            sqlparse.tokens.Comment,
            sqlparse.tokens.Comment.Single,
            sqlparse.tokens.Comment.Multiline,
        ):
            first_token = tok
            break

    first_val = first_token.value.upper() if first_token else ""
    is_cte = first_val == "WITH"
    cte_root = _extract_cte_root_statement(stmt) if is_cte else ""

    # Support parenthesized queries like ((SELECT 1))
    if stmt_type == "UNKNOWN" and clean.startswith("("):
        for tok in stmt.flatten():
            if (
                not tok.is_whitespace
                and tok.ttype
                not in (
                    sqlparse.tokens.Comment,
                    sqlparse.tokens.Comment.Single,
                    sqlparse.tokens.Comment.Multiline,
                )
                and tok.value not in ("(", ")")
            ):
                inner_val = tok.value.upper().strip('"[]`')
                if inner_val == "SELECT":
                    stmt_type = "SELECT"
                elif (
                    tok.ttype in (Keyword, DML, DDL)
                    or inner_val in RESTRICTED_MUTATION_KEYWORDS
                ):
                    stmt_type = inner_val
                break

    if is_cte:
        if not allow_cte:
            violations.append("Common Table Expressions (WITH) are not permitted.")
        elif not allow_recursive_cte and re.search(
            r"\bRECURSIVE\b", clean, re.IGNORECASE
        ):
            violations.append(
                "Recursive Common Table Expressions (WITH RECURSIVE) are not permitted."
            )
        elif cte_root != "SELECT":
            violations.append(
                f"Restricted statement type: {cte_root}. Only SELECT queries are permitted."
            )
            stmt_type = cte_root
        else:
            stmt_type = "SELECT"
    elif stmt_type != "SELECT":
        detected_name = stmt_type if stmt_type else (first_val or "UNKNOWN")
        violations.append(
            f"Restricted statement type: {detected_name}. Only SELECT queries are permitted."
        )

    effective_keywords = (
        restricted_keywords
        if restricted_keywords is not None
        else RESTRICTED_MUTATION_KEYWORDS
    )
    effective_tables = (
        restricted_tables
        if restricted_tables is not None
        else RESTRICTED_SECURITY_TABLES
    )
    schema_patterns = (
        restricted_schema_patterns
        if restricted_schema_patterns is not None
        else DEFAULT_RESTRICTED_SCHEMA_PATTERNS
    )
    allowed_upper = (
        {_clean_ident_part(s.rstrip(".")) for s in allowed_schemas}
        if allowed_schemas
        else set()
    )

    tokens_list = list(stmt.flatten())
    if len(tokens_list) > max_ast_tokens:
        # Early return: do not spend more CPU on an input that is already rejected.
        violations.append(
            f"Query AST token count ({len(tokens_list)}) exceeds safety threshold ({max_ast_tokens})."
        )
        return _finalize(violations, stmt_type, is_cte, cte_root, first_val)

    # Lex ONCE per dialect interpretation (backslash escapes, `#` comments, dollar
    # quoting, [bracket] identifiers, nested comments, MySQL `--` rule) and validate
    # every distinct interpretation; the union of violations is reported (fail-closed).
    variants = _lex_variants(clean)
    for _stripped, masked in variants:
        # A `;` that is code (not inside any literal/comment/quoted identifier) under ANY
        # interpretation, followed by more code, is a stacked statement.
        if len([seg for seg in masked.split(";") if seg.strip()]) > 1:
            violations.append(
                "Multiple statements detected. Semicolon query chaining is not permitted."
            )
            break

    set_scope_ok = all(
        re.search(r"\bSET\s+(?:TRANSACTION|LOCAL)\b", stripped, re.IGNORECASE)
        for stripped, _masked in variants
    )

    # Deep token inspection for mutation keywords (sqlparse's own lexing of the raw text)
    for tok in tokens_list:
        if tok.is_whitespace or tok.ttype in (
            sqlparse.tokens.Comment,
            sqlparse.tokens.Comment.Single,
            sqlparse.tokens.Comment.Multiline,
        ):
            continue
        if tok.ttype in (
            sqlparse.tokens.Literal.String,
            sqlparse.tokens.Literal.String.Single,
            sqlparse.tokens.String.Single,
        ):
            continue

        raw_val = tok.value.strip()
        is_quoted = (
            (raw_val.startswith('"') and raw_val.endswith('"'))
            or (raw_val.startswith("`") and raw_val.endswith("`"))
            or (raw_val.startswith("[") and raw_val.endswith("]"))
        )
        val = raw_val.upper().strip('"[]`')

        if not is_quoted and (
            tok.ttype in (Keyword, DML, DDL) or val in effective_keywords
        ):
            if val in effective_keywords:
                violations.append(f"Forbidden mutation keyword: '{val}'")
            elif val == "SET" and not set_scope_ok:
                violations.append("Forbidden session modification keyword: 'SET'")

    for stripped, masked in variants:
        _check_variant(
            stripped,
            masked,
            violations,
            effective_keywords=effective_keywords,
            effective_tables=effective_tables,
            schema_patterns=schema_patterns,
            allowed_upper=allowed_upper,
        )

    return _finalize(violations, stmt_type, is_cte, cte_root, first_val)


SUPPORTED_WINDOW_FUNCTIONS: set[str] = {
    "ROW_NUMBER",
    "RANK",
    "DENSE_RANK",
    "PERCENT_RANK",
    "CUME_DIST",
    "NTILE",
    "LEAD",
    "LAG",
    "FIRST_VALUE",
    "LAST_VALUE",
    "NTH_VALUE",
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
}


def validate_cte_dag(ctes: list[Any]) -> dict[str, Any]:
    """
    Validates a collection of CTE specifications for DAG structure:
    1. Valid identifier names and uniqueness.
    2. Identifies dependencies between CTEs.
    3. Detects circular dependencies (cycles).
    4. Ensures self-referencing CTEs are explicitly marked recursive=True.
    5. Computes a valid topological execution order.
    """
    violations: list[str] = []
    cycles: list[list[str]] = []
    topological_order: list[str] = []

    if not ctes:
        return {
            "valid": True,
            "cycles": cycles,
            "violations": violations,
            "topological_order": topological_order,
        }

    cte_names: set[str] = set()
    graph: dict[str, list[str]] = {}
    recursive_map: dict[str, bool] = {}

    for cte in ctes:
        name = getattr(cte, "name", None) or (
            cte.get("name") if isinstance(cte, dict) else None
        )
        if not name or not isinstance(name, str):
            violations.append("CTE specification is missing a valid 'name'.")
            continue
        clean_name = name.strip()
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", clean_name):
            violations.append(f"Invalid CTE identifier name: '{name}'.")

        if clean_name.lower() in {n.lower() for n in cte_names}:
            violations.append(f"Duplicate CTE name detected: '{name}'.")
        cte_names.add(clean_name)

        is_recursive = bool(
            getattr(cte, "recursive", False)
            or (cte.get("recursive") if isinstance(cte, dict) else False)
        )
        recursive_map[clean_name] = is_recursive

        # Extract dependencies from query table and joins
        q = getattr(cte, "query", None) or (
            cte.get("query") if isinstance(cte, dict) else {}
        )
        deps: list[str] = []
        if isinstance(q, dict):
            base_tbl = q.get("table")
            if isinstance(base_tbl, str):
                deps.append(base_tbl)
            for j in q.get("joins", []):
                if isinstance(j, dict) and "table" in j:
                    deps.append(j["table"])
                elif hasattr(j, "table"):
                    deps.append(j.table)
        elif hasattr(q, "table"):
            deps.append(q.table)
            for j in getattr(q, "joins", []):
                if hasattr(j, "table"):
                    deps.append(j.table)
                elif isinstance(j, dict) and "table" in j:
                    deps.append(j["table"])

        graph[clean_name] = deps

    if violations:
        return {
            "valid": False,
            "cycles": cycles,
            "violations": violations,
            "topological_order": topological_order,
        }

    # Check for self-referencing CTEs without recursive=True
    for cte_name, deps in graph.items():
        if cte_name in deps and not recursive_map.get(cte_name, False):
            violations.append(
                f"Self-referencing CTE '{cte_name}' must be marked as recursive."
            )

    # Filter dependencies to only internal CTEs
    internal_graph: dict[str, list[str]] = {
        name: [d for d in deps if d in cte_names and d != name]
        for name, deps in graph.items()
    }

    # Detect cycles via 3-color DFS
    state: dict[str, int] = {name: 0 for name in cte_names}
    path: list[str] = []

    def dfs(node: str) -> None:
        state[node] = 1
        path.append(node)
        for neighbor in internal_graph.get(node, []):
            if state[neighbor] == 1:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
                violations.append(
                    f"Circular dependency detected in CTEs: {' -> '.join(cycle)}"
                )
            elif state[neighbor] == 0:
                dfs(neighbor)
        path.pop()
        state[node] = 2
        topological_order.append(node)

    for node in cte_names:
        if state[node] == 0:
            dfs(node)

    is_valid = len(violations) == 0
    return {
        "valid": is_valid,
        "cycles": cycles,
        "violations": violations,
        "topological_order": topological_order if is_valid else [],
    }


def validate_window_function_spec(spec: Any) -> dict[str, Any]:
    """
    Validates a window function specification:
    1. Function name is recognized and valid.
    2. Window frame type is ROWS, RANGE, or GROUPS.
    3. Window frame boundaries are semantically valid.
    """
    violations: list[str] = []
    func = getattr(spec, "function", None) or (
        spec.get("function") if isinstance(spec, dict) else None
    )
    if not func or not isinstance(func, str):
        return {
            "valid": False,
            "violations": ["Window function is missing a valid 'function' name."],
        }

    clean_func = func.upper().strip()
    if clean_func not in SUPPORTED_WINDOW_FUNCTIONS:
        violations.append(f"Unsupported window function: '{func}'.")

    frame = getattr(spec, "frame", None) or (
        spec.get("frame") if isinstance(spec, dict) else None
    )
    if frame:
        ftype = (
            (
                getattr(frame, "frame_type", None)
                or (frame.get("frame_type") if isinstance(frame, dict) else "ROWS")
                or "ROWS"
            )
            .upper()
            .strip()
        )
        if ftype not in {"ROWS", "RANGE", "GROUPS"}:
            violations.append(
                f"Invalid frame_type '{ftype}'. Must be ROWS, RANGE, or GROUPS."
            )

        start = (
            (
                getattr(frame, "start", None)
                or (
                    frame.get("start")
                    if isinstance(frame, dict)
                    else "UNBOUNDED PRECEDING"
                )
                or "UNBOUNDED PRECEDING"
            )
            .upper()
            .strip()
        )
        end = getattr(frame, "end", None) or (
            frame.get("end") if isinstance(frame, dict) else None
        )
        if end:
            end = str(end).upper().strip()

        if "UNBOUNDED FOLLOWING" in start:
            violations.append("Window frame start cannot be UNBOUNDED FOLLOWING.")
        if end and "UNBOUNDED PRECEDING" in end:
            violations.append("Window frame end cannot be UNBOUNDED PRECEDING.")
        if (
            "FOLLOWING" in start
            and end
            and ("PRECEDING" in end or end == "CURRENT ROW")
        ):
            violations.append(
                "Window frame start FOLLOWING cannot precede end PRECEDING or CURRENT ROW."
            )
        if start == "CURRENT ROW" and end and "PRECEDING" in end:
            violations.append(
                "Window frame start CURRENT ROW cannot precede end PRECEDING."
            )

    return {
        "valid": len(violations) == 0,
        "violations": violations,
    }
