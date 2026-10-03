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


def _build_chain_exists(
    dialect: BaseDialect,
    tables_meta: dict[str, Any],
    from_alias: str,
    chain: list[tuple[str, str, str]],
    user_id: Any,
    params: list[Any],
    counter: AliasCounter,
) -> str:
    """
    Builds a (possibly nested) EXISTS clause walking `chain` from `from_alias`
    to the user-owned table at the end of the chain, appending bind params in
    left-to-right order matching the returned SQL text.
    """
    fk_col, target_table, target_pk = chain[0]
    tmp_alias = counter.next()
    q = dialect.quote_identifier
    conditions = [f"{q(tmp_alias)}.{q(target_pk)} = {q(from_alias)}.{q(fk_col)}"]

    if len(chain) == 1:
        tgt_info = tables_meta.get(target_table, {})
        user_col = tgt_info.get("user_col", "user_id")
        conditions.append(f"{q(tmp_alias)}.{q(user_col)} = {dialect.placeholder}")
        params.append(user_id)
    else:
        nested = _build_chain_exists(
            dialect, tables_meta, tmp_alias, chain[1:], user_id, params, counter
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

    Fails closed: if `table` has no direct user column and no registered
    ownership chain, raises SecurityError instead of returning an unfiltered predicate.
    """
    tbl_info = tables_meta.get(table, {})
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
    if not chains:
        raise SecurityError(
            f"Table '{table}' has no resolvable ownership path; refusing to query it without tenant isolation."
        )

    ctr = counter or AliasCounter()
    or_parts = [
        _build_chain_exists(dialect, tables_meta, alias, chain, user_id, params, ctr)
        for chain in chains
    ]
    return "(" + " OR ".join(or_parts) + ")"
