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
    r"\bEXECUTE\b",
    r"\bCOPY\b",
    r"\bINTO\b",
    r"\bSET\b(?!\s+(?:TRANSACTION|LOCAL))",
]

RESTRICTED_MUTATION_KEYWORDS: set[str] = {
    "DELETE", "DROP", "UPDATE", "INSERT", "TRUNCATE", "ALTER",
    "GRANT", "REVOKE", "CREATE", "EXECUTE", "INTO", "COPY",
    "VACUUM", "REINDEX", "CLUSTER", "LOCK", "CALL"
}

RESTRICTED_SECURITY_TABLES: set[str] = {
    "AUTH_USER", "AUTH_GROUP", "AUTH_PERMISSION", "AUTH_USER_GROUPS", "AUTH_USER_USER_PERMISSIONS",
    "AUTHTOKEN_TOKEN", "DJANGO_SESSION", "DJANGO_ADMIN_LOG", "DJANGO_CONTENT_TYPE", "DJANGO_MIGRATIONS",
    "PG_SHADOW", "PG_AUTHID", "PG_USER", "PG_DATABASE", "PG_TABLES", "PG_STAT_ACTIVITY",
    "PG_ROLES", "PG_SETTINGS", "PG_CONFIG", "PASSWORDS", "CREDENTIALS",
    "CRM_CONNECTION", "CRM_FIELD_MAPPING", "DJANGO_CACHE_TABLE", "API_AUDITLOG", "USER_PROFILE",
}

DEFAULT_RESTRICTED_SCHEMA_PATTERNS: list[str] = [
    r"\bPUBLIC\.", r"\bPG_CATALOG\.", r"\bINFORMATION_SCHEMA\."
]


def validate_sql_ast(
    raw_sql: str,
    allowed_schemas: list[str] | None = None,
    restricted_tables: set[str] | None = None,
    restricted_keywords: set[str] | None = None,
    restricted_schema_patterns: list[str] | None = None,
    allow_cte: bool = True,
) -> dict[str, Any]:
    """
    Performs Abstract Syntax Tree (AST) validation using sqlparse.
    Verifies that:
    1. The SQL string is non-empty.
    2. Exactly one non-empty statement exists (rejecting semicolon query chaining/injection).
    3. The statement type is 'SELECT' (or CTE WITH where the root operation is SELECT).
    4. No AST tokens match restricted DDL/DML mutation keywords.
    5. No restricted security, credential, or administration tables are accessed.
    6. No restricted system/catalog schemas are queried without explicit authorization.

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

    parsed = sqlparse.parse(clean)
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
    violations: list[str] = []

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

    if not allow_cte and is_cte:
        violations.append("Common Table Expressions (WITH) are not permitted.")
    elif stmt_type != "SELECT" and not (is_cte and stmt_type in ("SELECT", "UNKNOWN")):
        detected_name = stmt_type if stmt_type else (first_val or "UNKNOWN")
        violations.append(
            f"Restricted statement type: {detected_name}. Only SELECT queries are permitted."
        )

    # Check for restricted system/security schema access
    schema_patterns = restricted_schema_patterns if restricted_schema_patterns is not None else DEFAULT_RESTRICTED_SCHEMA_PATTERNS
    for pattern in schema_patterns:
        if re.search(pattern, clean, re.IGNORECASE):
            # If allowed_schemas is explicitly provided, verify if this pattern is an exception
            if allowed_schemas:
                schema_allowed = False
                for allowed in allowed_schemas:
                    if re.search(rf"\b{allowed}\.", clean, re.IGNORECASE):
                        schema_allowed = True
                        break
                if schema_allowed:
                    continue
            violations.append(
                "Access Denied: Queries may only target allowed analytical datasets."
            )
            break

    # Deep token inspection for mutation keywords and restricted auth/system tables
    effective_keywords = restricted_keywords if restricted_keywords is not None else RESTRICTED_MUTATION_KEYWORDS
    effective_tables = restricted_tables if restricted_tables is not None else RESTRICTED_SECURITY_TABLES

    for tok in stmt.flatten():
        val = tok.value.upper().strip('"[]`')
        if tok.ttype in (Keyword, DML, DDL) or val in effective_keywords:
            if val in effective_keywords:
                violations.append(f"Forbidden mutation keyword: '{val}'")
            elif val == "SET" and not re.search(r"\bSET\s+(?:TRANSACTION|LOCAL)\b", clean, re.IGNORECASE):
                violations.append("Forbidden session modification keyword: 'SET'")

        # Restrict unauthorized tables
        if val in effective_tables:
            violations.append(
                f"Access Denied: Table '{val}' is restricted. Authentication, credentials, and session data cannot be queried."
            )

    # Regex safety fallback against obfuscated mutations
    for pattern in FORBIDDEN_SQL_PATTERNS:
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            matched_kw = match.group(0).upper()
            if f"Forbidden mutation keyword: '{matched_kw}'" not in violations:
                violations.append(f"Forbidden mutation pattern detected: '{matched_kw}'")

    unique_violations = list(dict.fromkeys(violations))
    is_valid = len(unique_violations) == 0
    detected_type = "SELECT" if (stmt_type == "SELECT" or is_cte) else (stmt_type or first_val or "UNKNOWN")

    risk = "NONE"
    if not is_valid:
        if any("MUTATION" in v.upper() or "KEYWORD" in v.upper() or "CHAINING" in v.upper() or "DENIED" in v.upper() for v in unique_violations):
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
        "message": "Query passed AST validation and read-only policy." if is_valid else unique_violations[0],
    }
