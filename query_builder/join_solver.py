"""
Graph-Based Automatic Join Path & Condition Solver.
===================================================
Uses schema foreign key constraints, canonical entity heuristics, and Breadth-First Search
(BFS) to find optimal multi-hop join paths between database tables without requiring manual
FOREIGN KEY configuration from the user.
"""

from __future__ import annotations

from collections import deque
from typing import Any

CANONICAL_ENTITY_COLUMNS: list[str] = [
    "user_id",
    "project_id",
    "goal_id",
    "task_id",
    "session_id",
    "habbit_id",
    "firm_master_id",
    "firm_id",
    "contact_master_id",
    "contact_id",
    "address_master_id",
    "address_id",
    "product_id",
    "custodian_id",
    "crd_number",
    "sec_number",
    "cik",
]


def _clean_table_name(tbl: str) -> str:
    """Strips schema prefixes such as 'production.' or 'public.'."""
    if "." in tbl:
        return tbl.split(".", 1)[1]
    return tbl


def find_best_join_condition(
    left_table: str,
    right_table: str,
    schema_data: dict[str, Any] | None = None,
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

    tables_meta = schema_data.get("tables", {}) if schema_data else {}
    foreign_keys = schema_data.get("foreign_keys", []) if schema_data else []

    left_tbl_meta = tables_meta.get(clean_left, {})
    right_tbl_meta = tables_meta.get(clean_right, {})

    left_cols = left_tbl_meta.get("columns", [])
    right_cols = right_tbl_meta.get("columns", [])

    left_col_names = {c["name"] if isinstance(c, dict) else str(c) for c in left_cols}
    right_col_names = {c["name"] if isinstance(c, dict) else str(c) for c in right_cols}

    # 1. Explicit FK match
    for fk in foreign_keys:
        fk_tbl = _clean_table_name(fk.get("table", ""))
        fk_foreign_tbl = _clean_table_name(fk.get("foreign_table", ""))
        col = fk.get("column", "")
        f_col = fk.get("foreign_column", "")

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

    # 2. Canonical entity ID matches
    for col in CANONICAL_ENTITY_COLUMNS:
        if col in left_col_names and col in right_col_names:
            return {
                "left_table": clean_left,
                "left_col": col,
                "right_table": clean_right,
                "right_col": col,
                "is_fk": False,
                "reason": f"Canonical identifier match ({col})",
            }

    # 3. Direct table named foreign key heuristics (e.g. left='user', right has 'user_id')
    right_fk_candidate = f"{clean_left}_id"
    if right_fk_candidate in right_col_names and "id" in left_col_names:
        return {
            "left_table": clean_left,
            "left_col": "id",
            "right_table": clean_right,
            "right_col": right_fk_candidate,
            "is_fk": True,
            "reason": f"Inferred foreign key ({clean_right}.{right_fk_candidate} -> {clean_left}.id)",
        }

    left_fk_candidate = f"{clean_right}_id"
    if left_fk_candidate in left_col_names and "id" in right_col_names:
        return {
            "left_table": clean_left,
            "left_col": left_fk_candidate,
            "right_table": clean_right,
            "right_col": "id",
            "is_fk": True,
            "reason": f"Inferred foreign key ({clean_left}.{left_fk_candidate} -> {clean_right}.id)",
        }

    # 4. Primary key or fallback column
    left_pk = "id"
    for c in left_cols:
        if isinstance(c, dict) and c.get("is_primary"):
            left_pk = c.get("name", "id")
            break

    right_pk = "id"
    for c in right_cols:
        if isinstance(c, dict) and c.get("is_primary"):
            right_pk = c.get("name", "id")
            break

    return {
        "left_table": clean_left,
        "left_col": left_pk,
        "right_table": clean_right,
        "right_col": right_pk,
        "is_fk": False,
        "reason": "Primary key fallback",
    }


def find_join_path(
    active_tables: list[str],
    target_table: str,
    schema_data: dict[str, Any] | None = None,
    default_join_type: str = "LEFT JOIN",
) -> list[dict[str, Any]]:
    """
    Finds the shortest join path from any table in active_tables to target_table
    using Breadth-First Search (BFS) across foreign keys and canonical entity bridges.
    """
    clean_target = _clean_table_name(target_table)
    clean_active = [_clean_table_name(t) for t in active_tables]

    if clean_target in clean_active:
        return []

    if not clean_active:
        return []

    tables_meta = schema_data.get("tables", {}) if schema_data else {}
    foreign_keys = schema_data.get("foreign_keys", []) if schema_data else []

    # Build adjacency graph
    adj: dict[str, set[str]] = {}

    def add_edge(u: str, v: str) -> None:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)

    for fk in foreign_keys:
        t1 = _clean_table_name(fk.get("table", ""))
        t2 = _clean_table_name(fk.get("foreign_table", ""))
        if t1 and t2:
            add_edge(t1, t2)

    # Inferred entity bridges
    for tbl_name, meta in tables_meta.items():
        clean_tbl = _clean_table_name(tbl_name)
        col_names = {
            c["name"] if isinstance(c, dict) else str(c)
            for c in meta.get("columns", [])
        }
        for entity_col in CANONICAL_ENTITY_COLUMNS:
            if entity_col in col_names and entity_col.endswith("_id"):
                base_entity = entity_col[:-3]
                if base_entity in tables_meta:
                    add_edge(base_entity, clean_tbl)

    # BFS from active tables
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque()
    visited: set[str] = set(clean_active)

    for start_table in clean_active:
        queue.append((start_table, []))

    while queue:
        current, path = queue.popleft()
        if current == clean_target:
            return path

        for neighbor in adj.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                cond = find_best_join_condition(current, neighbor, schema_data)
                next_join = {
                    "type": default_join_type,
                    "left_table": cond["left_table"],
                    "left_col": cond["left_col"],
                    "table": cond["right_table"],
                    "right_col": cond["right_col"],
                }
                queue.append((neighbor, path + [next_join]))

    # Fallback direct join from first active table
    fallback_start = clean_active[0]
    cond = find_best_join_condition(fallback_start, clean_target, schema_data)
    return [
        {
            "type": default_join_type,
            "left_table": cond["left_table"],
            "left_col": cond["left_col"],
            "table": cond["right_table"],
            "right_col": cond["right_col"],
        }
    ]
