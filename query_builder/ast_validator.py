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

import sqlparse
from sqlparse.tokens import DDL, DML, Keyword

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


def _extract_cte_root_statement(stmt: sqlparse.sql.Statement) -> str:
    """Finds the root statement keyword (e.g. SELECT, DO, MERGE, DELETE) for a CTE."""
    found_with = False
    for tok in stmt.tokens:
        if tok.is_whitespace or tok.ttype in (
            sqlparse.tokens.Comment,
            sqlparse.tokens.Comment.Single,
            sqlparse.tokens.Comment.Multiline,
        ):
            continue
        v = tok.value.upper().strip('"[]`')
        if v == "WITH":
            found_with = True
            continue
        if found_with:
            if v == "RECURSIVE":
                continue
            if isinstance(tok, (sqlparse.sql.Identifier, sqlparse.sql.IdentifierList)):
                continue
            if tok.ttype in (
                sqlparse.tokens.Punctuation,
                sqlparse.tokens.Keyword.CTE,
            ) and v in (",", "AS"):
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

    # Check for restricted system/security schema access
    schema_patterns = (
        restricted_schema_patterns
        if restricted_schema_patterns is not None
        else DEFAULT_RESTRICTED_SCHEMA_PATTERNS
    )
    for pattern in schema_patterns:
        for m in re.finditer(pattern, clean, re.IGNORECASE):
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

    # Deep token inspection for mutation keywords and restricted auth/system tables
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
        val = tok.value.upper().strip('"[]`')
        if tok.ttype in (Keyword, DML, DDL) or val in effective_keywords:
            if val in effective_keywords:
                violations.append(f"Forbidden mutation keyword: '{val}'")
            elif val == "SET" and not re.search(
                r"\bSET\s+(?:TRANSACTION|LOCAL)\b", clean, re.IGNORECASE
            ):
                violations.append("Forbidden session modification keyword: 'SET'")

        # Restrict unauthorized tables
        if val in effective_tables:
            violations.append(
                f"Access Denied: Table '{val}' is restricted. Authentication, credentials, and session data cannot be queried."
            )

    # Check qualified table names like mysql.user, sys.objects, etc.
    for m in re.finditer(
        r"(?:^|[^\w$])(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)\s*\.\s*(?:[\"`\[]?)([a-zA-Z0-9_]+)(?:[\"`\]]?)",
        clean,
    ):
        s_part, t_part = m.group(1).upper(), m.group(2).upper()
        qualified_tbl = f"{s_part}.{t_part}"
        if qualified_tbl in effective_tables:
            violations.append(
                f"Access Denied: Table '{qualified_tbl}' is restricted. Authentication, credentials, and session data cannot be queried."
            )
        elif t_part in effective_tables:
            violations.append(
                f"Access Denied: Table '{t_part}' is restricted. Authentication, credentials, and session data cannot be queried."
            )

    # Regex safety fallback against obfuscated mutations (strip string literals to avoid false positives)
    clean_no_literals = re.sub(r"'(?:''|[^'])*'", "''", clean)
    for pattern in FORBIDDEN_SQL_PATTERNS:
        match = re.search(pattern, clean_no_literals, re.IGNORECASE)
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
