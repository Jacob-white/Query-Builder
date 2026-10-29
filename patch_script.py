import sys

with open("query_builder/join_solver.py", "r") as f:
    content = f.read()

helpers_code = """
def _get_table_columns(tables_meta: dict[str, Any], table_name: str) -> list[Any]:
    raw = tables_meta.get(table_name, {}) if isinstance(tables_meta, dict) else {}
    if hasattr(raw, "to_dict"):
        tbl_meta = raw.to_dict()
    elif isinstance(raw, dict):
        tbl_meta = raw
    elif hasattr(raw, "columns"):
        tbl_meta = {"columns": getattr(raw, "columns", [])}
    else:
        tbl_meta = {}
    return tbl_meta.get("columns", [])

def _check_explicit_fks(clean_left: str, clean_right: str, foreign_keys: list[Any]) -> dict[str, Any] | None:
    for fk in foreign_keys:
        if isinstance(fk, dict):
            fk_tbl = _clean_table_name(fk.get("table", ""))
            fk_foreign_tbl = _clean_table_name(fk.get("foreign_table", ""))
            col = fk.get("column", "")
            f_col = fk.get("foreign_column", "")
        elif hasattr(fk, "table"):
            fk_tbl = _clean_table_name(getattr(fk, "table", ""))
            fk_foreign_tbl = _clean_table_name(getattr(fk, "foreign_table", ""))
            col = getattr(fk, "column", "")
            f_col = getattr(fk, "foreign_column", "")
        else:
            continue

        # Direct: right -> left
        if fk_tbl == clean_right and fk_foreign_tbl == clean_left:
            return {
                "left_table": clean_left,
                "left_col": f_col,
                "right_table": clean_right,
                "right_col": col,
                "is_fk": True,
                "reason": "Schema foreign key constraint",
            }
        # Reverse: left -> right
        if fk_tbl == clean_left and fk_foreign_tbl == clean_right:
            return {
                "left_table": clean_left,
                "left_col": col,
                "right_table": clean_right,
                "right_col": f_col,
                "is_fk": True,
                "reason": "Schema foreign key constraint",
            }
    return None

def _check_relationships(clean_left: str, clean_right: str, relationships: list[Any]) -> dict[str, Any] | None:
    for rel in relationships:
        if isinstance(rel, dict):
            src_tbl = _clean_table_name(rel.get("source_table", ""))
            tgt_tbl = _clean_table_name(rel.get("target_table", ""))
            src_col = rel.get("source_column", "")
            tgt_col = rel.get("target_column", "")
        elif hasattr(rel, "source_table"):
            src_tbl = _clean_table_name(getattr(rel, "source_table", ""))
            tgt_tbl = _clean_table_name(getattr(rel, "target_table", ""))
            src_col = getattr(rel, "source_column", "")
            tgt_col = getattr(rel, "target_column", "")
        else:
            continue

        if src_tbl == clean_right and tgt_tbl == clean_left:
            return {
                "left_table": clean_left,
                "left_col": tgt_col,
                "right_table": clean_right,
                "right_col": src_col,
                "is_fk": True,
                "reason": "Schema foreign key constraint",
            }
        if src_tbl == clean_left and tgt_tbl == clean_right:
            return {
                "left_table": clean_left,
                "left_col": src_col,
                "right_table": clean_right,
                "right_col": tgt_col,
                "is_fk": True,
                "reason": "Schema foreign key constraint",
            }
    return None

def _check_canonical_match(clean_left: str, clean_right: str, left_col_names: set[str], right_col_names: set[str], effective_canon: Sequence[str]) -> dict[str, Any] | None:
    for col in effective_canon:
        if col in left_col_names and col in right_col_names:
            return {
                "left_table": clean_left,
                "left_col": col,
                "right_table": clean_right,
                "right_col": col,
                "is_fk": False,
                "reason": f"Canonical identifier match ({col})",
            }
    return None

def _singular_variants(tbl: str) -> list[str]:
    variants = [tbl]
    if tbl.endswith("ies") and len(tbl) > 3:
        variants.append(f"{tbl[:-3]}y")
    if tbl.endswith("es") and len(tbl) > 2:
        variants.append(tbl[:-2])
    if tbl.endswith("s") and len(tbl) > 1:
        variants.append(tbl[:-1])
    return variants

def _check_inferred_fks(clean_left: str, clean_right: str, left_col_names: set[str], right_col_names: set[str]) -> dict[str, Any] | None:
    for stem_left in _singular_variants(clean_left):
        right_fk_candidate = f"{stem_left}_id"
        if right_fk_candidate in right_col_names and "id" in left_col_names:
            return {
                "left_table": clean_left,
                "left_col": "id",
                "right_table": clean_right,
                "right_col": right_fk_candidate,
                "is_fk": True,
                "reason": f"Inferred foreign key ({clean_right}.{right_fk_candidate} -> {clean_left}.id)",
            }

    for stem_right in _singular_variants(clean_right):
        left_fk_candidate = f"{stem_right}_id"
        if left_fk_candidate in left_col_names and "id" in right_col_names:
            return {
                "left_table": clean_left,
                "left_col": left_fk_candidate,
                "right_table": clean_right,
                "right_col": "id",
                "is_fk": True,
                "reason": f"Inferred foreign key ({clean_left}.{left_fk_candidate} -> {clean_right}.id)",
            }
    return None

def _get_pk_fallback(clean_left: str, clean_right: str, left_cols: list[Any], right_cols: list[Any]) -> dict[str, Any]:
    left_pk = "id"
    for c in left_cols:
        if (isinstance(c, dict) and c.get("is_primary")) or getattr(
            c, "is_primary", False
        ):
            left_pk = (
                c.get("name", "id") if isinstance(c, dict) else getattr(c, "name", "id")
            )
            break

    right_pk = "id"
    for c in right_cols:
        if (isinstance(c, dict) and c.get("is_primary")) or getattr(
            c, "is_primary", False
        ):
            right_pk = (
                c.get("name", "id") if isinstance(c, dict) else getattr(c, "name", "id")
            )
            break

    return {
        "left_table": clean_left,
        "left_col": left_pk,
        "right_table": clean_right,
        "right_col": right_pk,
        "is_fk": False,
        "reason": "Primary key fallback",
    }
"""

replacement = """
def find_best_join_condition(
"""

idx = content.find("def find_best_join_condition(")
if idx != -1:
    content = content[:idx] + helpers_code + "\n\n" + content[idx:]
    with open("query_builder/join_solver.py", "w") as f:
        f.write(content)
