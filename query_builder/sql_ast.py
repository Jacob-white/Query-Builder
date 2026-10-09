"""
sqlglot-backed SQL analysis and allowlist policy.
==================================================

This module is the *structural* layer of the read-only SQL gatekeeper.  Where the
legacy layer in :mod:`query_builder.ast_validator` reasons about token streams, this
layer parses the statement into a real syntax tree (via ``sqlglot``) and evaluates an
allowlist policy on the tree:

* exactly one statement;
* the statement is a read-only query: ``SELECT`` / ``WITH ... SELECT`` / a set operation
  of those / a parenthesised query (never ``VALUES``, ``TABLE x``, DML, DDL, ``Command``
  or any node we do not recognise);
* no denied (SQL-executing / file-reading) function appears anywhere in the tree,
  including table-function positions;
* no *real* relation is a restricted table or lives in a restricted schema.  CTE aliases
  are resolved with proper scoping, so ``WITH auth_user AS (SELECT * FROM auth_user)``
  still reports the inner (real) table, and ``FROM auth_user AS harmless`` is still
  reported.

Failure policy (documented decision): **fail closed**.  When ``sqlglot`` cannot parse the
input under any candidate dialect -- or raises, or hits the recursion limit -- the
analysis reports ``parsed=False`` and the policy rejects the query.  There is
deliberately no "legacy proves it is safe" escape hatch: the only inputs such an
exception could cover (constant expressions such as ``SELECT 1``) are parsed by every
dialect anyway, so the exception would only ever widen the attack surface.

Dialect handling: a Query-Builder dialect name maps to one sqlglot dialect.  An unknown or
missing dialect is analysed under every dialect in :data:`FALLBACK_DIALECTS` and the
findings are UNIONed; the query is rejected if *any* interpretation that parses is
unsafe, and the analysis only counts as unparsable when *no* interpretation parses.

This is defence in depth, not a replacement for database-side read-only enforcement; see
``docs/THREAT_MODEL.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.dialects.dialect import Dialect as _SqlglotDialect
    from sqlglot.errors import SqlglotError
except ImportError:  # pragma: no cover - exercised only without the dependency
    sqlglot = None  # type: ignore[assignment]
    exp = None  # type: ignore[assignment]
    SqlglotError = Exception  # type: ignore[assignment,misc]
    _SqlglotDialect = None  # type: ignore[assignment,misc]

#: Interpretations tried (and UNIONed) when the dialect is unknown.  Maintainers may
#: mutate this tuple/list at start-up to widen or narrow coverage.
FALLBACK_DIALECTS: tuple[str, ...] = (
    "postgres",
    "mysql",
    "sqlite",
    "tsql",
    "duckdb",
    "bigquery",
    "snowflake",
    "clickhouse",
    "oracle",
)

#: Query-Builder dialect name -> sqlglot dialect name.  Names absent from the map (and
#: every non-SQL "dialect" such as the vector stores) use :data:`FALLBACK_DIALECTS`.
DIALECT_MAP: dict[str, str] = {
    # PostgreSQL wire family
    "postgres": "postgres",
    "postgresql": "postgres",
    "alloydb": "postgres",
    "neon": "postgres",
    "supabase": "postgres",
    "cockroach": "postgres",
    "cockroachdb": "postgres",
    "yugabyte": "postgres",
    "yugabytedb": "postgres",
    "timescale": "postgres",
    "timescaledb": "postgres",
    "crate": "postgres",
    "cratedb": "postgres",
    "questdb": "postgres",
    "redshift": "redshift",
    "materialize": "materialize",
    "mz": "materialize",
    "risingwave": "risingwave",
    "rw": "risingwave",
    # MySQL family
    "mysql": "mysql",
    "mariadb": "mysql",
    "tidb": "mysql",
    "oceanbase": "mysql",
    "singlestore": "singlestore",
    "memsql": "singlestore",
    "doris": "doris",
    "apache_doris": "doris",
    "pydoris": "doris",
    "starrocks": "starrocks",
    # Embedded
    "sqlite": "sqlite",
    "d1": "sqlite",
    "cloudflare_d1": "sqlite",
    "duckdb": "duckdb",
    # SQL Server family
    "mssql": "tsql",
    "sqlserver": "tsql",
    "sybase": "tsql",
    "ase": "tsql",
    "sap_ase": "tsql",
    # Cloud warehouses
    "bigquery": "bigquery",
    "spanner": "bigquery",
    "snowflake": "snowflake",
    "databricks": "databricks",
    "athena": "athena",
    "clickhouse": "clickhouse",
    "clickhouse_native": "clickhouse",
    "clickhouse_tcp": "clickhouse",
    "ch_native": "clickhouse",
    "chdb": "clickhouse",
    "oracle": "oracle",
    "teradata": "teradata",
    "exasol": "exasol",
    "dremio": "dremio",
    "drill": "drill",
    "apache_drill": "drill",
    "pydrill": "drill",
    "druid": "druid",
    "apache_druid": "druid",
    # Hive / Spark / Presto families
    "spark": "spark",
    "spark_sql": "spark",
    "sparksql": "spark",
    "pyspark": "spark",
    "kyuubi": "spark",
    "apache_kyuubi": "spark",
    "hive": "hive",
    "apache_hive": "hive",
    "pyhive": "hive",
    "impala": "hive",
    "apache_impala": "hive",
    "impyla": "hive",
    "trino": "trino",
    "presto": "presto",
    "prestodb": "presto",
}

#: Names reachable only through these keys are file paths / URLs rather than tables.
_FILE_LIKE_RE = re.compile(
    r"""(?:^[a-z][a-z0-9+.-]*://)            # URL scheme (s3://, https://, file://)
        |[/\\*?]                              # path separators / globs
        |\.(?:csv|tsv|parquet|json|jsonl|ndjson|db|sqlite3?|duckdb|txt|gz|zst|xlsx?|arrow|orc|avro)$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_WRITE_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterTable",
    "AlterColumn",
    "AlterRename",
    "TruncateTable",
    "Grant",
    "Revoke",
    "Copy",
    "LoadData",
    "Into",
    "Set",
    "SetItem",
    "Use",
    "Pragma",
    "Transaction",
    "Commit",
    "Rollback",
    "Attach",
    "Detach",
    "Command",
    "Execute",
    "ExecuteSql",
    "Declare",
    "Kill",
    "Lock",
    "LockingStatement",
    "Analyze",
    "Cache",
    "Uncache",
    "Refresh",
    "Export",
    "Install",
    "Put",
    "Comment",
    "Describe",
    "Show",
    "Summarize",
    "Return",
    "Semicolon",
)


def _node_types(names: Iterable[str]) -> tuple[type, ...]:
    if exp is None:  # pragma: no cover
        return ()
    return tuple(t for n in names if isinstance(t := getattr(exp, n, None), type))


_WRITE_TYPES = _node_types(_WRITE_NODE_NAMES)
_ROOT_QUERY_TYPES = _node_types(("Select", "SetOperation"))


@dataclass(frozen=True)
class TableRef:
    """A relation reference found in the tree."""

    catalog: str
    schema: str
    name: str
    #: True when the reference resolves to a CTE visible at that position.
    is_cte: bool = False
    #: True when the "table" is a table function (``FROM read_csv('x')``).
    is_function: bool = False

    @property
    def qualified(self) -> str:
        return ".".join(p for p in (self.catalog, self.schema, self.name) if p)


@dataclass(frozen=True)
class SqlAnalysis:
    """Structured result of :func:`analyze_sql`."""

    parsed: bool
    dialects_tried: tuple[str, ...] = ()
    dialects_parsed: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    statement_count: int = 0
    statement_types: tuple[str, ...] = ()
    tables: tuple[TableRef, ...] = ()
    functions: tuple[str, ...] = ()
    #: Qualifier prefixes of function calls (``dbms_xmlgen`` in ``dbms_xmlgen.getxml``).
    function_qualifiers: tuple[str, ...] = ()
    cte_names: tuple[str, ...] = ()
    recursive_cte: bool = False
    #: Names of node types that make the statement non read-only (DML, Command, ...).
    non_read_only_nodes: tuple[str, ...] = ()
    #: Per-dialect statement count, so a stacked statement under ANY dialect is visible.
    max_statement_count: int = 0
    unknown_root_types: tuple[str, ...] = ()
    #: Set when sqlglot itself is unavailable.
    unavailable: bool = False
    extra: dict[str, object] = field(default_factory=dict, compare=False, hash=False)

    @property
    def read_only(self) -> bool:
        """True only for exactly one statement that is a plain read-only query."""
        return (
            self.parsed
            and self.max_statement_count == 1
            and not self.non_read_only_nodes
            and not self.unknown_root_types
        )

    @property
    def real_tables(self) -> tuple[TableRef, ...]:
        return tuple(t for t in self.tables if not t.is_cte and not t.is_function)


def resolve_dialects(dialect: str | None) -> tuple[str, ...]:
    """Maps a Query-Builder dialect name to the sqlglot dialect(s) to try."""
    if dialect:
        mapped = DIALECT_MAP.get(dialect.strip().lower())
        if mapped and _dialect_available(mapped):
            return (mapped,)
        if dialect.strip().lower() in _sqlglot_dialect_names():
            return (dialect.strip().lower(),)
    return tuple(d for d in FALLBACK_DIALECTS if _dialect_available(d))


@lru_cache(maxsize=1)
def _sqlglot_dialect_names() -> frozenset[str]:
    if _SqlglotDialect is None:  # pragma: no cover
        return frozenset()
    try:
        from sqlglot.dialects import DIALECTS

        return frozenset(k.lower() for k in DIALECTS if k)
    except Exception:  # noqa: BLE001  # pragma: no cover
        return frozenset()


def _dialect_available(name: str) -> bool:
    return name in _sqlglot_dialect_names()


def _ident_name(node: object) -> str:
    if node is None:
        return ""
    if isinstance(node, exp.Identifier):
        return str(node.this) if node.this is not None else ""
    return str(getattr(node, "name", "") or "")


def _ident_quoted(node: object) -> bool:
    return bool(isinstance(node, exp.Identifier) and node.args.get("quoted"))


def _names_equal(a: object, b: object) -> bool:
    """Conservative CTE-name equality: case-insensitive only if both are unquoted."""
    na, nb = _ident_name(a), _ident_name(b)
    if _ident_quoted(a) or _ident_quoted(b):
        return na == nb
    return na.lower() == nb.lower()


def _with_of(node: object) -> object | None:
    w = node.args.get("with_") or node.args.get("with")  # type: ignore[attr-defined]
    return w if isinstance(w, exp.With) else None


def _resolves_to_cte(table: object) -> bool:
    """True if an unqualified table reference names a CTE visible at its position."""
    ident = table.args.get("this")  # type: ignore[attr-defined]
    if not isinstance(ident, exp.Identifier):
        return False
    if table.args.get("db") or table.args.get("catalog"):  # type: ignore[attr-defined]
        return False
    child = table
    node = table.parent  # type: ignore[attr-defined]
    while node is not None:
        if isinstance(node, exp.With):
            # `child` is the CTE whose definition contains the reference: only EARLIER
            # CTEs (and itself, for WITH RECURSIVE) are visible from inside it.
            recursive = bool(node.args.get("recursive"))
            for cte in node.expressions:
                if cte is child:
                    if recursive and _names_equal(
                        ident, cte.args.get("alias") and cte.args["alias"].this
                    ):
                        return True
                    break
                alias = cte.args.get("alias")
                if alias is not None and _names_equal(ident, alias.this):
                    return True
        else:
            w = _with_of(node)
            if w is not None and child is not w:
                for cte in w.expressions:
                    alias = cte.args.get("alias")
                    if alias is not None and _names_equal(ident, alias.this):
                        return True
        child = node
        node = node.parent
    return False


def _func_names(node: object) -> list[str]:
    names: list[str] = []
    if isinstance(node, exp.Anonymous):
        n = node.name
        if not n and isinstance(node.this, str):
            n = node.this
        names.append(str(n))
    else:
        try:
            names.extend(type(node).sql_names())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001, S110
            pass
        names.append(node.key)  # type: ignore[attr-defined]
        try:
            names.append(node.sql_name())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001, S110
            pass
    return [n.upper() for n in dict.fromkeys(names) if n]


def _qualifiers_of(node: object) -> list[str]:
    parent = node.parent  # type: ignore[attr-defined]
    quals: list[str] = []
    while isinstance(parent, exp.Dot):
        quals.extend(
            _ident_name(i).upper() for i in parent.this.find_all(exp.Identifier)
        )
        parent = parent.parent
    tbl = node.parent  # type: ignore[attr-defined]
    if isinstance(tbl, exp.Table):
        quals.extend(
            _ident_name(tbl.args.get(k)).upper()
            for k in ("db", "catalog")
            if tbl.args.get(k)
        )
    return [q for q in quals if q]


def _root_type(node: object) -> tuple[str, bool]:
    """Returns (type name, is_plain_read_only_query) for a root node."""
    inner = node
    while isinstance(inner, exp.Subquery):
        inner = inner.this
    name = type(inner).__name__.upper()
    return name, isinstance(inner, _ROOT_QUERY_TYPES)


# Bind-parameter placeholders emitted by the compiler for DB-API drivers.  Rewritten to
# the neutral `?` before parsing; quoted regions / comments are skipped.  Any mismatch
# with the real lexer can only leave a placeholder untouched (parse failure -> reject)
# or alter text inside a literal (harmless), never hide code.
_PLACEHOLDER_RE = re.compile(
    r"""(?P<skip>'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*"|`[^`]*`|--[^\r\n]*|/\*.*?\*/)"""
    r"""|(?P<ph>%\(\w+\)s|%s|\$\d+|\$[A-Za-z_]\w*(?!\w|\$))""",
    re.DOTALL,
)
# Cypher / Informix style pagination emitted by some dialects: `SKIP ? LIMIT ?`.
_SKIP_PAGINATION_RE = re.compile(
    r"""(?P<skip>'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*"|`[^`]*`|--[^\r\n]*|/\*.*?\*/)"""
    r"""|(?P<pg>\bSKIP\s+\?\s+(?:LIMIT|FIRST)\s+\?)""",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_placeholders(sql: str) -> str:
    if "%" in sql or "$" in sql:
        sql = _PLACEHOLDER_RE.sub(lambda m: m.group("skip") or "?", sql)
    if "?" in sql:
        sql = _SKIP_PAGINATION_RE.sub(
            lambda m: m.group("skip") or "LIMIT ? OFFSET ?", sql
        )
    return sql


def _analyze_one(sql: str, dialect: str | None) -> tuple[dict[str, object], str | None]:
    try:
        statements = sqlglot.parse(_normalize_placeholders(sql), read=dialect)
    except RecursionError:
        return {}, "recursion limit exceeded while parsing"
    except SqlglotError as exc:
        return (
            {},
            f"{type(exc).__name__}: {str(exc).splitlines()[0][:120] if str(exc) else ''}",
        )
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}"

    roots = [s for s in statements if s is not None]
    types: list[str] = []
    unknown_roots: list[str] = []
    bad: list[str] = []
    tables: list[TableRef] = []
    functions: list[str] = []
    qualifiers: list[str] = []
    cte_names: list[str] = []
    recursive = False

    try:
        for root in roots:
            tname, ok = _root_type(root)
            types.append(tname)
            if not ok:
                unknown_roots.append(tname)
            for node in root.walk():
                if isinstance(node, _WRITE_TYPES):
                    bad.append(type(node).__name__.upper())
                if isinstance(node, exp.With):
                    if node.args.get("recursive"):
                        recursive = True
                    for cte in node.expressions:
                        alias = cte.args.get("alias")
                        if alias is not None:
                            cte_names.append(_ident_name(alias.this))
                if isinstance(node, exp.Table):
                    this = node.args.get("this")
                    catalog = _ident_name(node.args.get("catalog"))
                    schema = _ident_name(node.args.get("db"))
                    if isinstance(this, exp.Func):
                        fnames = _func_names(this)
                        tables.append(
                            TableRef(
                                catalog,
                                schema,
                                fnames[0] if fnames else "",
                                is_function=True,
                            )
                        )
                    else:
                        tables.append(
                            TableRef(
                                catalog,
                                schema,
                                _ident_name(this),
                                is_cte=_resolves_to_cte(node),
                            )
                        )
                if isinstance(node, exp.Func):
                    functions.extend(_func_names(node))
                    qualifiers.extend(_qualifiers_of(node))
    except RecursionError:
        return {}, "recursion limit exceeded while walking the tree"

    return {
        "count": len(roots),
        "types": types,
        "unknown_roots": unknown_roots,
        "bad": bad,
        "tables": tables,
        "functions": functions,
        "qualifiers": qualifiers,
        "cte_names": cte_names,
        "recursive": recursive,
    }, None


@lru_cache(maxsize=512)
def _analyze_cached(sql: str, dialects: tuple[str, ...]) -> SqlAnalysis:
    if sqlglot is None:  # pragma: no cover
        return SqlAnalysis(
            parsed=False, unavailable=True, errors=("sqlglot is not installed",)
        )
    parsed_dialects: list[str] = []
    errors: list[str] = []
    types: list[str] = []
    unknown: list[str] = []
    bad: list[str] = []
    tables: list[TableRef] = []
    functions: list[str] = []
    quals: list[str] = []
    ctes: list[str] = []
    recursive = False
    max_count = 0
    count = 0
    for d in dialects:
        res, err = _analyze_one(sql, d)
        if err is not None:
            errors.append(f"{d}: {err}")
            continue
        parsed_dialects.append(d)
        count = max(count, int(res["count"]))  # type: ignore[call-overload]
        max_count = count
        types.extend(res["types"])  # type: ignore[arg-type]
        unknown.extend(res["unknown_roots"])  # type: ignore[arg-type]
        bad.extend(res["bad"])  # type: ignore[arg-type]
        tables.extend(res["tables"])  # type: ignore[arg-type]
        functions.extend(res["functions"])  # type: ignore[arg-type]
        quals.extend(res["qualifiers"])  # type: ignore[arg-type]
        ctes.extend(res["cte_names"])  # type: ignore[arg-type]
        recursive = recursive or bool(res["recursive"])

    def uniq(seq: Iterable[object]) -> tuple:
        return tuple(dict.fromkeys(seq))

    return SqlAnalysis(
        parsed=bool(parsed_dialects),
        dialects_tried=tuple(dialects),
        dialects_parsed=tuple(parsed_dialects),
        errors=tuple(errors),
        statement_count=count,
        max_statement_count=max_count,
        statement_types=uniq(types),
        tables=uniq(tables),
        functions=uniq(functions),
        function_qualifiers=uniq(quals),
        cte_names=uniq(ctes),
        recursive_cte=recursive,
        non_read_only_nodes=uniq(bad),
        unknown_root_types=uniq(unknown),
    )


def analyze_sql(sql: str, dialect: str | None = None) -> SqlAnalysis:
    """Parses ``sql`` with sqlglot and returns a structured, immutable analysis.

    ``dialect`` is a Query-Builder dialect name (``"postgres"``, ``"mysql"``, ...) or a
    sqlglot dialect name.  Unknown / ``None`` analyses the query under every dialect in
    :data:`FALLBACK_DIALECTS` and unions the findings.
    """
    return _analyze_cached(sql or "", resolve_dialects(dialect))


def _matches_restricted(ref: TableRef, restricted: set[str]) -> str | None:
    parts = [p.upper() for p in (ref.catalog, ref.schema, ref.name) if p]
    for a, b in zip(parts, parts[1:], strict=False):
        if f"{a}.{b}" in restricted:
            return f"{a}.{b}"
    if parts and parts[-1] in restricted:
        return parts[-1]
    return None


def evaluate_policy(
    analysis: SqlAnalysis,
    *,
    restricted_tables: set[str],
    schema_patterns: list[str],
    allowed_schemas_upper: set[str],
    denied_functions: frozenset[str] | set[str],
    denied_function_prefixes: tuple[str, ...],
    denied_keywords: set[str],
    allow_cte: bool = True,
    allow_recursive_cte: bool = False,
    clean_ident=lambda s: s.upper().strip('"[]`'),
) -> list[str]:
    """Applies the allowlist policy to an analysis; returns violation messages."""
    out: list[str] = []
    if analysis.unavailable:
        return ["sqlglot is not installed; the structural SQL layer is unavailable."]
    if not analysis.parsed:
        detail = "; ".join(analysis.errors[:3])
        return [
            "Query could not be parsed by the structural SQL layer "
            f"(failing closed){': ' + detail if detail else ''}."
        ]
    if analysis.max_statement_count != 1:
        out.append(
            f"Exactly one statement is required; the parser found {analysis.max_statement_count}."
        )
    for t in analysis.unknown_root_types:
        out.append(f"Statement type {t} is not a read-only query.")
    for n in analysis.non_read_only_nodes:
        out.append(f"Non read-only construct {n} is not permitted.")
    if analysis.cte_names and not allow_cte:
        out.append("Common Table Expressions (WITH) are not permitted.")
    if analysis.recursive_cte and not allow_recursive_cte:
        out.append(
            "Recursive Common Table Expressions (WITH RECURSIVE) are not permitted."
        )

    restricted_upper = {t.upper() for t in restricted_tables}
    for fn in analysis.functions:
        if (
            fn in denied_functions
            or fn in denied_keywords
            or fn.startswith(denied_function_prefixes)
        ):
            out.append(
                f"Function '{fn}' can execute arbitrary SQL or read external "
                "files/data and is not permitted."
            )
    for q in analysis.function_qualifiers:
        if q.startswith(denied_function_prefixes):
            out.append(f"Function package '{q}' is not permitted.")

    for ref in analysis.tables:
        if ref.is_cte:
            continue
        if ref.is_function:
            if (
                ref.name in denied_functions
                or ref.name in denied_keywords
                or ref.name.startswith(denied_function_prefixes)
            ):
                out.append(f"Table function '{ref.name}' is not permitted.")
        elif _FILE_LIKE_RE.search(ref.name):
            out.append(
                f"Relation '{ref.name}' looks like a file path or URL; file access is not permitted."
            )
        hit = _matches_restricted(ref, restricted_upper)
        if hit:
            out.append(f"Table '{hit}' is restricted.")
        rendered = (
            [".".join(p for p in (ref.schema, ref.name) if p)] if ref.schema else []
        )
        if ref.catalog:
            rendered.append(ref.qualified)
        denied_schema = False
        for text in rendered:
            for pattern in schema_patterns:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    matched = (
                        clean_ident(m.group(1))
                        if m.lastindex and m.lastindex >= 1
                        else clean_ident(m.group(0).split(".", 1)[0])
                    )
                    if allowed_schemas_upper and matched in allowed_schemas_upper:
                        continue
                    denied_schema = True
        if denied_schema:
            out.append(f"Relation '{ref.qualified}' is in a restricted system schema.")
    return list(dict.fromkeys(out))
