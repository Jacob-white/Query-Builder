"""
Client-side read-only guard for NATIVE (non-SQL) query languages.

The generic mutation check in :mod:`query_builder.middleware` is SQL-shaped: it knows
``INSERT/UPDATE/DELETE/CREATE/...`` but not AQL's ``REMOVE``/``REPLACE``/``UPSERT``,
Cypher's ``SET``/``MERGE``/``REMOVE``, SurrealQL's ``RELATE``/``DEFINE`` or SQL++'s ``MERGE``.
Live runs against real engines showed those statements sailing through whenever the AST
validator was off.  Connectors for such engines call :func:`assert_read_only` from their
cursor adapter, so the guard sits below every execution path (spec, raw SQL, introspection).

The guard is an ALLOW-LIST on the leading keyword plus a DENY-LIST of mutating keywords
anywhere outside string literals, quoted identifiers and comments (keywords used as property
names, i.e. ``x.set`` or ``{set: 1}``, are ignored).  It is defence in depth, not a parser:
where the engine can refuse writes itself (a READ access mode, a read-only transaction) the
connector should do that as well.
"""

from __future__ import annotations

import re

from query_builder.exceptions import SecurityError

_COMMENT_OR_LITERAL = re.compile(
    r"""
    /\*.*?\*/                 # block comment
  | //[^\n]*                  # line comment (AQL, Cypher, SurrealQL)
  | --[^\n]*                  # line comment (SQL, CQL, SurrealQL, SQL++)
  | \#[^\n]*                  # line comment (SurrealQL)
  | '(?:[^'\\]|\\.|'')*'      # single-quoted string
  | "(?:[^"\\]|\\.)*"         # double-quoted string / identifier
  | `(?:[^`\\]|\\.)*`         # backticked identifier
  | ´(?:[^´\\]|\\.)*´         # AQL forward ticks
    """,
    re.DOTALL | re.VERBOSE,
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")

_RULES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "aql": (
        # SELECT is not AQL; it is allowed through so the ENGINE reports the syntax error
        frozenset({"FOR", "RETURN", "LET", "WITH", "SELECT"}),
        frozenset({"INSERT", "UPDATE", "REPLACE", "REMOVE", "UPSERT"}),
    ),
    "surrealql": (
        frozenset({"SELECT", "RETURN", "INFO", "LET"}),
        frozenset(
            {
                "CREATE",
                "UPDATE",
                "UPSERT",
                "DELETE",
                "INSERT",
                "RELATE",
                "DEFINE",
                "REMOVE",
                "ALTER",
                "KILL",
                "SLEEP",
                "USE",
                "THROW",
            }
        ),
    ),
    "cypher": (
        frozenset(
            {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN", "SHOW", "EXPLAIN", "PROFILE", "CALL"}
        ),
        frozenset(
            {
                "CREATE",
                "MERGE",
                "SET",
                "DELETE",
                "DETACH",
                "REMOVE",
                "DROP",
                "FOREACH",
                "LOAD",
                "ALTER",
                "GRANT",
                "REVOKE",
                "DENY",
                "TERMINATE",
                "FREE",
                "STORAGE",
                "ANALYZE",
                "RECOVER",
                "SNAPSHOT",
                "LOCK",
                "UNLOCK",
                "ISOLATION",
                "USE",
            }
        ),
    ),
    "cql": (
        frozenset({"SELECT", "DESCRIBE", "DESC"}),
        frozenset(
            {
                "INSERT",
                "UPDATE",
                "DELETE",
                "DROP",
                "ALTER",
                "CREATE",
                "TRUNCATE",
                "GRANT",
                "REVOKE",
                "BATCH",
                "APPLY",
                "USE",
            }
        ),
    ),
    "n1ql": (
        frozenset({"SELECT", "INFER", "WITH", "EXPLAIN", "ADVISE"}),
        frozenset(
            {
                "INSERT",
                "UPSERT",
                "UPDATE",
                "DELETE",
                "MERGE",
                "CREATE",
                "DROP",
                "ALTER",
                "GRANT",
                "REVOKE",
                "BUILD",
                "EXECUTE",
                "PREPARE",
                "UPDATE",
            }
        ),
    ),
}

#: Cypher procedures that only read (Neo4j ``db.*``/``dbms.*`` metadata, Memgraph
#: ``mg.procedures``/``mg.functions`` and ``schema.*``).  Any other ``CALL`` is refused.
_SAFE_CALL = re.compile(
    r"^\s*CALL\s+(?:db\.|dbms\.components|dbms\.procedures|schema\.|mg\.procedures|mg\.functions)",
    re.IGNORECASE,
)
_SURREAL_HTTP = re.compile(r"\bhttp::", re.IGNORECASE)


def _blank(match: re.Match[str]) -> str:
    return " "


def strip_literals(statement: str) -> str:
    """Statement with comments, string literals and quoted identifiers blanked out."""
    return _COMMENT_OR_LITERAL.sub(_blank, statement)


def find_mutation(statement: str, language: str) -> str | None:
    """Return the offending keyword/reason when ``statement`` is not provably read-only."""
    allowed, denied = _RULES[language]
    text = strip_literals(statement).strip().rstrip(";").strip()
    if not text:
        return None
    words = [(m.group(0).upper(), m.start(), m.end()) for m in _WORD.finditer(text)]
    if not words:
        return None
    first = words[0][0]
    if first not in allowed:
        return f"statement starts with {first!r}"
    if language == "cypher" and first == "CALL" and not _SAFE_CALL.match(text):
        return "CALL of a procedure that is not known to be read-only"
    if language == "surrealql" and _SURREAL_HTTP.search(text):
        return "http:: function"
    for word, start, end in words:
        if word not in denied:
            continue
        before = text[:start].rstrip()
        after = text[end:].lstrip()
        if before.endswith("."):  # property access: p.update
            continue
        if after.startswith(":") and not after.startswith("::"):  # object key {set: 1}
            continue
        return word
    return None


def assert_read_only(statement: str, language: str, engine: str) -> None:
    """Raise :class:`SecurityError` unless ``statement`` is provably read-only."""
    reason = find_mutation(statement, language)
    if reason is not None:
        raise SecurityError(
            f"Read-only session violation ({engine}): {reason} in '{statement[:60]}'."
        )
