import sys

with open("query_builder/join_solver.py", "r") as f:
    content = f.read()

find_best_start = content.find("def find_best_join_condition(")
find_best_end = content.find("def _get_safe_join_type(", find_best_start)

find_best_new = """def find_best_join_condition(
    left_table: str,
    right_table: str,
    schema_data: dict[str, Any] | SchemaSnapshot | None = None,
    canonical_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    \"\"\"
    Determines the best join condition between two tables.
    Order of evaluation:
    1. Explicit foreign key constraint (direct or reverse).
    2. Shared canonical entity columns (e.g. firm_id, user_id, project_id).
    3. Direct entity name matching (e.g. table has '<other_table>_id').
    4. Primary key / fallback column match.
    \"\"\"
    clean_left = _clean_table_name(left_table)
    clean_right = _clean_table_name(right_table)
    if not clean_left or not clean_right:
        return {
            "left_table": clean_left or "t1",
            "left_col": "id",
            "right_table": clean_right or "t2",
            "right_col": "id",
            "is_fk": False,
            "reason": "Fallback condition for empty/invalid table name",
        }

    tables_meta, foreign_keys, relationships = _extract_schema_metadata(schema_data)

    left_cols = _get_table_columns(tables_meta, clean_left)
    right_cols = _get_table_columns(tables_meta, clean_right)

    left_col_names = {
        c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
        for c in left_cols
    }
    right_col_names = {
        c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
        for c in right_cols
    }

    # 1. Explicit FK match
    if fk_match := _check_explicit_fks(clean_left, clean_right, foreign_keys):
        return fk_match

    # 1b. Explicit relationship match
    if rel_match := _check_relationships(clean_left, clean_right, relationships):
        return rel_match

    effective_canon = _get_effective_canon(canonical_columns, schema_data)

    # 2. Canonical entity ID matches
    if canon_match := _check_canonical_match(clean_left, clean_right, left_col_names, right_col_names, effective_canon):
        return canon_match

    # 3. Direct table named foreign key heuristics
    if inf_match := _check_inferred_fks(clean_left, clean_right, left_col_names, right_col_names):
        return inf_match

    # 4. Primary key or fallback column
    return _get_pk_fallback(clean_left, clean_right, left_cols, right_cols)


"""

content = content[:find_best_start] + find_best_new + content[find_best_end:]

with open("query_builder/join_solver.py", "w") as f:
    f.write(content)
