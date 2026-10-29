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

    legacy_violations = list(dict.fromkeys(violations))
    ast_violations = evaluate_policy(
        analyze_sql(clean, dialect),
        restricted_tables=effective_tables,
        schema_patterns=schema_patterns,
        allowed_schemas_upper=allowed_upper,
        denied_functions=_DENIED_FUNCTIONS,
        denied_function_prefixes=_DENIED_FUNCTION_PREFIXES,
        denied_keywords=effective_keywords,
        allow_cte=allow_cte,
        allow_recursive_cte=allow_recursive_cte,
        clean_ident=_clean_ident_part,
    )
    violations.extend(AST_LAYER_TAG + v for v in ast_violations)
    result = _finalize(violations, stmt_type, is_cte, cte_root, first_val)
    result["violation_layers"] = {
        "legacy": legacy_violations,
        "sqlglot_ast": [AST_LAYER_TAG + v for v in ast_violations],
    }
    return result


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
        elif q is not None and hasattr(q, "table"):
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
