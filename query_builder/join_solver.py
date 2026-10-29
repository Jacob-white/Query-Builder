"""
Graph-Based Automatic Join Path & Condition Solver.
===================================================
Uses schema foreign key constraints, canonical entity heuristics, and Breadth-First Search
(BFS) to find optimal multi-hop join paths between database tables without requiring manual
FOREIGN KEY configuration from the user.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from query_builder.models import SchemaSnapshot

CANONICAL_ENTITY_COLUMNS: list[str] = [
    "user_id",
    "customer_id",
    "order_id",
    "account_id",
    "organization_id",
    "company_id",
    "project_id",
    "goal_id",
    "task_id",
    "session_id",
    "customer_master_id",
    "contact_master_id",
    "contact_id",
    "address_master_id",
    "address_id",
    "product_id",
    "category_id",
    "account_number",
    "registration_number",
]


MAX_JOIN_DEPTH = 10
MAX_BFS_ITERATIONS = 5000
MAX_ACTIVE_TABLES = 50
MAX_FOREIGN_KEYS = 5000


def _clean_table_name(tbl: Any) -> str:
    """Strips catalog and schema prefixes such as 'production.' or 'db.public.'."""
    if not tbl or not isinstance(tbl, str):
        return ""
    if "." in tbl:
        return tbl.rsplit(".", 1)[-1]
    return tbl


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


def _check_explicit_fks(
    clean_left: str, clean_right: str, foreign_keys: list[Any]
) -> dict[str, Any] | None:
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


def _check_relationships(
    clean_left: str, clean_right: str, relationships: list[Any]
) -> dict[str, Any] | None:
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


def _check_canonical_match(
    clean_left: str,
    clean_right: str,
    left_col_names: set[str],
    right_col_names: set[str],
    effective_canon: Sequence[str],
) -> dict[str, Any] | None:
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


def _check_inferred_fks(
    clean_left: str,
    clean_right: str,
    left_col_names: set[str],
    right_col_names: set[str],
) -> dict[str, Any] | None:
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


def _get_pk_fallback(
    clean_left: str, clean_right: str, left_cols: list[Any], right_cols: list[Any]
) -> dict[str, Any]:
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


def find_best_join_condition(
    left_table: str,
    right_table: str,
    schema_data: dict[str, Any] | SchemaSnapshot | None = None,
    canonical_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Determines the best join condition between two tables.
    Order of evaluation:
    1. Explicit foreign key constraint (direct or reverse).
    2. Shared canonical entity columns (e.g. firm_id, user_id, project_id).
    3. Direct entity name matching (e.g. table has '<other_table>_id').
    4. Primary key / fallback column match.
    """
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
    if canon_match := _check_canonical_match(
        clean_left, clean_right, left_col_names, right_col_names, effective_canon
    ):
        return canon_match

    # 3. Direct table named foreign key heuristics
    if inf_match := _check_inferred_fks(
        clean_left, clean_right, left_col_names, right_col_names
    ):
        return inf_match

    # 4. Primary key or fallback column
    return _get_pk_fallback(clean_left, clean_right, left_cols, right_cols)


def _get_safe_join_type(default_join_type: str) -> str:
    valid_join_types = {
        "LEFT JOIN",
        "INNER JOIN",
        "RIGHT JOIN",
        "FULL JOIN",
        "LEFT",
        "INNER",
        "RIGHT",
        "FULL",
    }
    if (
        not isinstance(default_join_type, str)
        or default_join_type.upper() not in valid_join_types
    ):
        return "LEFT JOIN"
    else:
        upper_jt = default_join_type.upper()
        return upper_jt if upper_jt.endswith("JOIN") else f"{upper_jt} JOIN"


def _extract_schema_metadata(
    schema_data: dict[str, Any] | SchemaSnapshot | None,
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    if hasattr(schema_data, "tables") and hasattr(schema_data, "foreign_keys"):
        tables_meta = getattr(schema_data, "tables", {})
        foreign_keys = getattr(schema_data, "foreign_keys", [])
        relationships = getattr(schema_data, "relationships", [])
    elif isinstance(schema_data, dict):
        tables_meta = schema_data.get("tables", {})
        foreign_keys = schema_data.get("foreign_keys", [])
        relationships = schema_data.get("relationships", [])
    else:
        tables_meta = {}
        foreign_keys = []
        relationships = []

    if not isinstance(tables_meta, dict):
        tables_meta = {}
    if not isinstance(foreign_keys, list):
        foreign_keys = []
    if not isinstance(relationships, list):
        relationships = []
    if len(foreign_keys) > MAX_FOREIGN_KEYS:
        foreign_keys = foreign_keys[:MAX_FOREIGN_KEYS]

    return tables_meta, foreign_keys, relationships


def _get_effective_canon(
    canonical_columns: Sequence[str] | None,
    schema_data: dict[str, Any] | SchemaSnapshot | None,
) -> Sequence[str]:
    effective_canon: Sequence[str] = CANONICAL_ENTITY_COLUMNS
    if canonical_columns:
        effective_canon = canonical_columns
    elif isinstance(schema_data, dict) and schema_data.get("canonical_columns"):
        effective_canon = schema_data["canonical_columns"]
    elif schema_data is not None and (
        canon_attr := getattr(schema_data, "canonical_columns", None)
    ):
        effective_canon = canon_attr
    return effective_canon


def _build_adjacency_graph(
    foreign_keys: list[Any],
    relationships: list[Any],
    tables_meta: dict[str, Any],
    effective_canon: Sequence[str],
) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {}

    def add_edge(u: str, v: str) -> None:
        u_list = adj.setdefault(u, [])
        if v not in u_list:
            u_list.append(v)
        v_list = adj.setdefault(v, [])
        if u not in v_list:
            v_list.append(u)

    for fk in foreign_keys:
        if isinstance(fk, dict):
            t1 = _clean_table_name(fk.get("table", ""))
            t2 = _clean_table_name(fk.get("foreign_table", ""))
        elif hasattr(fk, "table"):
            t1 = _clean_table_name(getattr(fk, "table", ""))
            t2 = _clean_table_name(getattr(fk, "foreign_table", ""))
        else:
            continue
        if t1 and t2:
            add_edge(t1, t2)

    for rel in relationships:
        if isinstance(rel, dict):
            t1 = _clean_table_name(rel.get("source_table", ""))
            t2 = _clean_table_name(rel.get("target_table", ""))
        elif hasattr(rel, "source_table"):
            t1 = _clean_table_name(getattr(rel, "source_table", ""))
            t2 = _clean_table_name(getattr(rel, "target_table", ""))
        else:
            continue
        if t1 and t2:
            add_edge(t1, t2)

    # Inferred entity bridges
    for tbl_name, raw_meta in tables_meta.items():
        if hasattr(raw_meta, "to_dict"):
            meta = raw_meta.to_dict()
        elif isinstance(raw_meta, dict):
            meta = raw_meta
        elif hasattr(raw_meta, "columns"):
            meta = {"columns": getattr(raw_meta, "columns", [])}
        else:
            continue
        clean_tbl = _clean_table_name(tbl_name)
        col_names = {
            c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
            for c in meta.get("columns", [])
        }
        candidate_cols = set(effective_canon) | {
            c for c in col_names if isinstance(c, str) and c.endswith("_id")
        }
        for entity_col in candidate_cols:
            if (
                entity_col in col_names
                and entity_col.endswith("_id")
                and len(entity_col) > 3
            ):
                base_entity = entity_col[:-3]
                candidates = [
                    base_entity,
                    f"{base_entity}s",
                    f"{base_entity}es",
                ]
                if base_entity.endswith("y") and len(base_entity) > 1:
                    candidates.append(f"{base_entity[:-1]}ies")
                for cand in candidates:
                    if cand != clean_tbl and cand in tables_meta:
                        add_edge(cand, clean_tbl)

    return adj


def _run_bfs_join_search(
    clean_active: list[str],
    clean_target: str,
    adj: dict[str, list[str]],
    schema_data: dict[str, Any] | SchemaSnapshot | None,
    effective_canon: Sequence[str],
    safe_join_type: str,
) -> list[dict[str, Any]] | None:
    queue: list[tuple[str, list[dict[str, Any]], int]] = []
    best_score: dict[str, int] = {}

    for start_table in clean_active:
        best_score[start_table] = 0
        queue.append((start_table, [], 0))

    iterations = 0
    while queue and iterations < MAX_BFS_ITERATIONS:
        iterations += 1
        min_idx = 0
        for idx in range(1, len(queue)):
            if queue[idx][2] < queue[min_idx][2]:
                min_idx = idx
        current, path, score = queue.pop(min_idx)
        if current == clean_target:
            return path

        if len(path) >= MAX_JOIN_DEPTH:
            continue

        for neighbor in adj.get(current, []):
            cond = find_best_join_condition(
                current,
                neighbor,
                schema_data,
                canonical_columns=effective_canon,
            )
            is_confirmed = cond.get("reason") == "Schema foreign key constraint"
            step_cost = 99 if is_confirmed else 100
            next_score = score + step_cost
            prev_best = best_score.get(neighbor)
            if prev_best is None or next_score < prev_best:
                best_score[neighbor] = next_score
                next_join = {
                    "type": safe_join_type,
                    "left_table": cond["left_table"],
                    "left_col": cond["left_col"],
                    "table": cond["right_table"],
                    "right_col": cond["right_col"],
                }
                queue.append((neighbor, path + [next_join], next_score))

    return None


def find_join_path(
    active_tables: list[str],
    target_table: str,
    schema_data: dict[str, Any] | SchemaSnapshot | None = None,
    default_join_type: str = "LEFT JOIN",
    canonical_columns: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Finds the shortest join path from any table in active_tables to target_table
    using Breadth-First Search (BFS) across foreign keys and canonical entity bridges.

    Protected against infinite loops, deep recursion, and large schema DoS.
    """
    clean_target = _clean_table_name(target_table)
    if not clean_target:
        return []

    if not isinstance(active_tables, (list, tuple, set)):
        return []

    safe_join_type = _get_safe_join_type(default_join_type)

    clean_active = [_clean_table_name(t) for t in active_tables if _clean_table_name(t)]

    if clean_target in clean_active or not clean_active:
        return []

    if len(clean_active) > MAX_ACTIVE_TABLES:
        clean_active = clean_active[:MAX_ACTIVE_TABLES]

    tables_meta, foreign_keys, relationships = _extract_schema_metadata(schema_data)
    effective_canon = _get_effective_canon(canonical_columns, schema_data)

    # Build adjacency graph (preserving insertion order via dict keys)
    adj = _build_adjacency_graph(
        foreign_keys, relationships, tables_meta, effective_canon
    )

    # BFS from active tables prioritizing confirmed FK/relationship edges over equal-length inferred bridges
    path = _run_bfs_join_search(
        clean_active,
        clean_target,
        adj,
        schema_data,
        effective_canon,
        safe_join_type,
    )

    if path is not None:
        return path

    # Fallback direct join from first active table
    fallback_start = clean_active[0]
    cond = find_best_join_condition(
        fallback_start,
        clean_target,
        schema_data,
        canonical_columns=effective_canon,
    )
    return [
        {
            "type": safe_join_type,
            "left_table": cond["left_table"],
            "left_col": cond["left_col"],
            "table": cond["right_table"],
            "right_col": cond["right_col"],
        }
    ]
