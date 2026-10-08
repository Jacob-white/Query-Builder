"""
Graph-Based Automatic Join Path & Condition Solver.
===================================================
Uses schema foreign key constraints, canonical entity heuristics, and Breadth-First Search
(BFS) to find optimal multi-hop join paths between database tables without requiring manual
FOREIGN KEY configuration from the user.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from query_builder.models import SchemaSnapshot

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


def find_best_join_condition(
    left_table: str,
    right_table: str,
    schema_data: dict[str, Any] | SchemaSnapshot | None = None,
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

    if hasattr(schema_data, "tables") and hasattr(schema_data, "foreign_keys"):
        tables_meta = getattr(schema_data, "tables", {})
        foreign_keys = getattr(schema_data, "foreign_keys", [])
    elif isinstance(schema_data, dict):
        tables_meta = schema_data.get("tables", {})
        foreign_keys = schema_data.get("foreign_keys", [])
    else:
        tables_meta = {}
        foreign_keys = []

    if not isinstance(tables_meta, dict):
        tables_meta = {}
    if not isinstance(foreign_keys, list):
        foreign_keys = []

    raw_left = tables_meta.get(clean_left, {}) if isinstance(tables_meta, dict) else {}
    if hasattr(raw_left, "to_dict"):
        left_tbl_meta = raw_left.to_dict()
    elif isinstance(raw_left, dict):
        left_tbl_meta = raw_left
    else:
        left_tbl_meta = {}

    raw_right = (
        tables_meta.get(clean_right, {}) if isinstance(tables_meta, dict) else {}
    )
    if hasattr(raw_right, "to_dict"):
        right_tbl_meta = raw_right.to_dict()
    elif isinstance(raw_right, dict):
        right_tbl_meta = raw_right
    else:
        right_tbl_meta = {}

    left_cols = left_tbl_meta.get("columns", [])
    right_cols = right_tbl_meta.get("columns", [])

    left_col_names = {
        c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
        for c in left_cols
    }
    right_col_names = {
        c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
        for c in right_cols
    }

    # 1. Explicit FK match
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
    schema_data: dict[str, Any] | SchemaSnapshot | None = None,
    default_join_type: str = "LEFT JOIN",
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
        safe_join_type = "LEFT JOIN"
    else:
        upper_jt = default_join_type.upper()
        safe_join_type = upper_jt if upper_jt.endswith("JOIN") else f"{upper_jt} JOIN"

    clean_active = [_clean_table_name(t) for t in active_tables if _clean_table_name(t)]

    if clean_target in clean_active or not clean_active:
        return []

    if len(clean_active) > MAX_ACTIVE_TABLES:
        clean_active = clean_active[:MAX_ACTIVE_TABLES]

    if hasattr(schema_data, "tables") and hasattr(schema_data, "foreign_keys"):
        tables_meta = getattr(schema_data, "tables", {})
        foreign_keys = getattr(schema_data, "foreign_keys", [])
    elif isinstance(schema_data, dict):
        tables_meta = schema_data.get("tables", {})
        foreign_keys = schema_data.get("foreign_keys", [])
    else:
        tables_meta = {}
        foreign_keys = []

    if not isinstance(tables_meta, dict):
        tables_meta = {}
    if not isinstance(foreign_keys, list):
        foreign_keys = []
    if len(foreign_keys) > MAX_FOREIGN_KEYS:
        foreign_keys = foreign_keys[:MAX_FOREIGN_KEYS]

    # Build adjacency graph
    adj: dict[str, set[str]] = {}

    def add_edge(u: str, v: str) -> None:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)

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

    # Inferred entity bridges
    for tbl_name, raw_meta in tables_meta.items():
        if hasattr(raw_meta, "to_dict"):
            meta = raw_meta.to_dict()
        elif isinstance(raw_meta, dict):
            meta = raw_meta
        else:
            continue
        clean_tbl = _clean_table_name(tbl_name)
        col_names = {
            c["name"] if isinstance(c, dict) else getattr(c, "name", str(c))
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

    iterations = 0
    while queue and iterations < MAX_BFS_ITERATIONS:
        iterations += 1
        current, path = queue.popleft()
        if current == clean_target:
            return path

        if len(path) >= MAX_JOIN_DEPTH:
            continue

        for neighbor in adj.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                cond = find_best_join_condition(current, neighbor, schema_data)
                next_join = {
                    "type": safe_join_type,
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
            "type": safe_join_type,
            "left_table": cond["left_table"],
            "left_col": cond["left_col"],
            "table": cond["right_table"],
            "right_col": cond["right_col"],
        }
    ]
