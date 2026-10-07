"""
Abstract Syntax Tree (AST) SQL Safety Validator.
=================================================
Performs deep AST parsing via sqlparse to strictly verify queries are read-only
SELECT/CTE operations, rejecting SQL injection, semicolon chaining, mutation keywords,
unauthorized schema access, and system/credential table references.
"""

from __future__ import annotations

import re
from typing import Any

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
    r"\bWAITFOR(?:\s+|\/\*.*?\*\/)+DELAY\b",
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

DEFAULT_RESTRICTED_SCHEMA_PATTERNS: list[str] = [
    r"(?:^|[^\w$])(?:[\"`\[]?)(PUBLIC|PG_CATALOG|INFORMATION_SCHEMA|MYSQL|PERFORMANCE_SCHEMA|SYS|MSDB|MASTER|SNOWFLAKE)(?:[\"`\]]?)\s*\.\s*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)",
]

MAX_SQL_LENGTH = 100_000
MAX_AST_TOKENS = 10_000


_IDENTIFIER_QUOTES: dict[str, str] = {'"': '"', "`": "`", "[": "]"}


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
        elif ch == ";" or (
            depth == 0
            and re.match(
                r"^(WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|UNION|INTERSECT|EXCEPT|WINDOW|FETCH|FOR)\b",
                sql[i:],
                re.IGNORECASE,
            )
        ):
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


def strip_sql_comments_and_literals(sql: str) -> str:
    """
    Strips single-line comments (-- ...), multiline comments (/* ... */),
    and single-quoted string literals (handling '' and \\' escapes).
    Replaces string literals with '' to preserve syntactical structure.
    """
    # 1. Strip single-line comments
    sql = re.sub(r"--[^\r\n]*", " ", sql)
    # 2. Strip multiline comments
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    # 3. Strip single-quoted string literals including escaped quotes
    sql = re.sub(r"'(?:''|\\[\s\S]|[^'\\])*'", "''", sql)
    return sql


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

    try:
        parsed = sqlparse.parse(clean)
    except Exception as exc:  # noqa: BLE001
        return {
            "valid": False,
            "ast_validated": False,
            "statement_type": "ERROR",
            "is_read_only": False,
            "violations": [f"Malformed SQL failed AST parsing: {exc}"],
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

    # Cleaned SQL stripped of comments and literals for robust pattern matching
    clean_stripped = strip_sql_comments_and_literals(clean)

    # Check for restricted system/security schema access
    schema_patterns = (
        restricted_schema_patterns
        if restricted_schema_patterns is not None
        else DEFAULT_RESTRICTED_SCHEMA_PATTERNS
    )
    for pattern in schema_patterns:
        for m in re.finditer(pattern, clean_stripped, re.IGNORECASE):
            if m.lastindex and m.lastindex >= 1:
                matched_schema = m.group(1).upper()
            else:
                matched_schema = (
                    m.group(0)
                    .rstrip(".")
                    .strip(' "`[]')
                    .split(".")[0]
                    .strip(' "`[]')
                    .upper()
                )
            if allowed_schemas:
                allowed_upper = {
                    s.upper().rstrip(".").strip(' "`[]') for s in allowed_schemas
                }
                if matched_schema in allowed_upper:
                    continue
            violations.append(
                "Access Denied: Queries may only target allowed analytical datasets."
            )
            break
        if any("analytical" in v.lower() for v in violations):
            break

    # Deep token inspection for mutation keywords
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

    tokens_list = list(stmt.flatten())
    if len(tokens_list) > max_ast_tokens:
        violations.append(
            f"Query AST token count ({len(tokens_list)}) exceeds safety threshold ({max_ast_tokens})."
        )

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
            elif val == "SET" and not re.search(
                r"\bSET\s+(?:TRANSACTION|LOCAL)\b", clean_stripped, re.IGNORECASE
            ):
                violations.append("Forbidden session modification keyword: 'SET'")

    # Check tables referenced in FROM and JOIN clauses
    table_pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+(?:\(\s*)*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)(?:\s*\.\s*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?))?",
        re.IGNORECASE,
    )
    for m in table_pattern.finditer(clean_stripped):
        p1 = m.group(1).upper()
        p2 = m.group(2).upper() if m.group(2) else None
        if p2:
            tbl_qualified = f"{p1}.{p2}"
            if tbl_qualified in effective_tables:
                violations.append(
                    f"Access Denied: Table '{tbl_qualified}' is restricted. Authentication, credentials, and session data cannot be queried."
                )
            elif p2 in effective_tables:
                violations.append(
                    f"Access Denied: Table '{p2}' is restricted. Authentication, credentials, and session data cannot be queried."
                )
        else:
            if p1 in effective_tables:
                violations.append(
                    f"Access Denied: Table '{p1}' is restricted. Authentication, credentials, and session data cannot be queried."
                )

    # Check comma-separated FROM tables
    from_clause_pattern = re.compile(
        r"\bFROM\s+([^;]+?)(?:\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|\bOFFSET\b|\bUNION\b|;|$)",
        re.IGNORECASE,
    )
    target_bodies: list[str] = []
    for fm in from_clause_pattern.finditer(clean_stripped):
        raw_body = fm.group(1)
        if raw_body.count("(") > raw_body.count(")"):
            body = _extract_from_body(
                clean_stripped,
                fm.start()
                + len(
                    re.match(
                        r"\bFROM\s+", clean_stripped[fm.start() :], re.IGNORECASE
                    ).group(0)
                ),
            )
        else:
            body = raw_body
        target_bodies.append(body)
        if re.search(r"\bFROM\s+", body, re.IGNORECASE):
            for sub_fm in from_clause_pattern.finditer(body):
                target_bodies.append(sub_fm.group(1))

    for from_body in target_bodies:
        if "," in from_body:
            for item in _split_from_items(from_body):
                tbl_m = re.match(
                    r"\s*(?:\(\s*)*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)(?:\s*\.\s*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?))?",
                    item,
                )
                if tbl_m:
                    cp1 = tbl_m.group(1).upper()
                    cp2 = tbl_m.group(2).upper() if tbl_m.group(2) else None
                    if cp2:
                        c_qual = f"{cp1}.{cp2}"
                        if c_qual in effective_tables:
                            violations.append(
                                f"Access Denied: Table '{c_qual}' is restricted. Authentication, credentials, and session data cannot be queried."
                            )
                        elif cp2 in effective_tables:
                            violations.append(
                                f"Access Denied: Table '{cp2}' is restricted. Authentication, credentials, and session data cannot be queried."
                            )
                    else:
                        if cp1 in effective_tables:
                            violations.append(
                                f"Access Denied: Table '{cp1}' is restricted. Authentication, credentials, and session data cannot be queried."
                            )

    # Check qualified table names like mysql.user, sys.objects, etc.
    for m in re.finditer(
        r"(?:^|[^\w$])(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)\s*\.\s*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)",
        clean_stripped,
    ):
        s_part, t_part = m.group(1).upper(), m.group(2).upper()
        qualified_tbl = f"{s_part}.{t_part}"
        if qualified_tbl in effective_tables:
            violations.append(
                f"Access Denied: Table '{qualified_tbl}' is restricted. Authentication, credentials, and session data cannot be queried."
            )

    # Regex safety fallback against obfuscated mutations
    clean_no_quoted_idents = re.sub(
        r'("[^"\\]*"|`[^`\\]*`|\[[^\]]*\])', ' "ident" ', clean_stripped
    )
    for pattern in FORBIDDEN_SQL_PATTERNS:
        match = re.search(pattern, clean_no_quoted_idents, re.IGNORECASE)
        if match:
            matched_kw = match.group(0).upper()
            if f"Forbidden mutation keyword: '{matched_kw}'" not in violations:
                violations.append(
                    f"Forbidden mutation pattern detected: '{matched_kw}'"
                )

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
