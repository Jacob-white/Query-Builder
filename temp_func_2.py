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
    dialect: str | None = None,
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

    Two independent layers must BOTH accept the query (defense in depth): the legacy
    sqlparse/lexer layer and the sqlglot structural layer (``query_builder.sql_ast``).
    Violations are unioned; structural-layer messages carry the ``[sqlglot-ast] `` prefix
    and the result's ``violation_layers`` maps each layer to its messages.  ``dialect``
    (optional) selects the sqlglot dialect; unknown/None unions several interpretations.

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
