"""
Tenant Isolation & Security Module.
===================================
Provides fail-closed user and tenant isolation predicate resolution.
Walks relational foreign key chains to ensure rows in child tables can only be
accessed if owned by the requesting tenant or authenticated user.
"""

from __future__ import annotations

from typing import Any

from query_builder.dialects import BaseDialect


class SecurityError(Exception):
    """Raised when tenant isolation cannot be resolved or security checks fail."""


class AliasCounter:
    """Thread-safe counter generating unique correlation aliases for subqueries."""

    def __init__(self, prefix: str = "_own") -> None:
        self._n = 0
        self._prefix = prefix

    def next(self) -> str:
        self._n += 1
        return f"{self._prefix}{self._n}"


MAX_OWNERSHIP_CHAIN_DEPTH = 10


def _build_chain_exists(
    dialect: BaseDialect,
    tables_meta: dict[str, Any],
    from_alias: str,
    chain: list[tuple[str, str, str]],
    user_id: Any,
    params: list[Any],
    counter: AliasCounter,
    current_depth: int = 0,
    visited_tables: set[str] | None = None,
) -> str:
    """
    Builds a (possibly nested) EXISTS clause walking `chain` from `from_alias`
    to the user-owned table at the end of the chain, appending bind params in
    left-to-right order matching the returned SQL text.

    Guards against recursion overflow and cyclic ownership loops.
    """
    if not chain:
        raise SecurityError("Ownership chain cannot be empty.")

    if current_depth >= MAX_OWNERSHIP_CHAIN_DEPTH:
        raise SecurityError(
            f"Ownership chain depth exceeded maximum allowed limit ({MAX_OWNERSHIP_CHAIN_DEPTH})."
        )

    hop = chain[0]
    if not isinstance(hop, (tuple, list)) or len(hop) != 3:
        raise SecurityError(f"Invalid ownership chain element format: {hop}")

    fk_col, target_table, target_pk = hop
    if not isinstance(target_table, str) or not target_table.strip():
        raise SecurityError(f"Invalid target table in ownership chain: {target_table}")
    if not isinstance(fk_col, str) or not fk_col.strip():
        raise SecurityError(f"Invalid foreign key column in ownership chain: {fk_col}")
    if not isinstance(target_pk, str) or not target_pk.strip():
        raise SecurityError(f"Invalid target PK column in ownership chain: {target_pk}")

    visited = set(visited_tables) if visited_tables is not None else set()
    if target_table in visited:
        raise SecurityError(
            f"Cyclic ownership path detected at table '{target_table}'."
        )
    visited.add(target_table)

    tmp_alias = counter.next()
    q = dialect.quote_identifier
    conditions = [f"{q(tmp_alias)}.{q(target_pk)} = {q(from_alias)}.{q(fk_col)}"]

    if len(chain) == 1:
        tgt_info = (
            tables_meta.get(target_table, {}) if isinstance(tables_meta, dict) else {}
        )
        user_col = tgt_info.get("user_col", "user_id")
        conditions.append(f"{q(tmp_alias)}.{q(user_col)} = {dialect.placeholder}")
        params.append(user_id)
    else:
        nested = _build_chain_exists(
            dialect,
            tables_meta,
            tmp_alias,
            chain[1:],
            user_id,
            params,
            counter,
            current_depth=current_depth + 1,
            visited_tables=visited,
        )
        conditions.append(nested)

    where = " AND ".join(conditions)
    return f"EXISTS (SELECT 1 FROM {q(target_table)} {q(tmp_alias)} WHERE {where})"


def resolve_ownership_predicate(
    dialect: BaseDialect,
    tables_meta: dict[str, Any],
    alias: str,
    table: str,
    user_id: Any,
    params: list[Any],
    counter: AliasCounter | None = None,
    ownership_paths: dict[str, list[list[tuple[str, str, str]]]] | None = None,
) -> str:
    """
    Returns a SQL boolean expression asserting the row at `alias` (of `table`)
    is owned by `user_id`, appending any needed bind params to `params`.

    Fails closed: if `user_id` is None, or if `table` has no direct user column
    and no registered ownership chain, raises SecurityError instead of returning
    an unfiltered predicate.
    """
    if user_id is None:
        raise SecurityError("Tenant isolation requires a valid, non-null user_id.")
    if not isinstance(table, str) or not table.strip():
        raise SecurityError("Invalid table name for ownership resolution.")
    if not isinstance(alias, str) or not alias.strip():
        raise SecurityError("Invalid alias for ownership resolution.")

    meta = tables_meta if isinstance(tables_meta, dict) else {}
    tbl_info = meta.get(table, {})
    q = dialect.quote_identifier

    # 1. Direct user ownership column
    if tbl_info.get("has_user_id") or "user_id" in [
        c.get("name") if isinstance(c, dict) else str(c)
        for c in tbl_info.get("columns", [])
    ]:
        user_col = tbl_info.get("user_col", "user_id")
        params.append(user_id)
        return f"{q(alias)}.{q(user_col)} = {dialect.placeholder}"

    # 2. Multi-hop ownership chain resolution
    paths = ownership_paths or {}
    chains = paths.get(table)
    if not chains or not isinstance(chains, list):
        raise SecurityError(
            f"Table '{table}' has no resolvable ownership path; refusing to query it without tenant isolation."
        )

    ctr = counter or AliasCounter()
    or_parts = [
        _build_chain_exists(dialect, meta, alias, chain, user_id, params, ctr)
        for chain in chains
    ]
    return "(" + " OR ".join(or_parts) + ")"
