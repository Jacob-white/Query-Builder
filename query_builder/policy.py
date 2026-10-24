"""
Multi-Tenant Security & Fail-Closed RLS Policy Engine.
======================================================
Enforces role-based access control (RBAC), attribute-based access control (ABAC),
table allow/denylists, column masking, regex-based sensitive column detection,
dynamic masking strategies ('redact', 'hash', 'partial'), and automatic fail-closed
row-level tenant filter injection into query specifications.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from query_builder.models import QuerySpec, SchemaSnapshot
from query_builder.security import SecurityError


@dataclass
class TenantContext:
    """Authentication and tenant context for query execution."""

    tenant_id: str
    user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class TablePolicy:
    """Table-level access policy declaring allowed and restricted tables."""

    allowed_tables: list[str] | None = None
    restricted_tables: list[str] = field(default_factory=list)


@dataclass
class ColumnPolicy:
    """Role-based Column-Level Access Control (CLAC) policy specification."""

    allowed_roles: list[str] = field(default_factory=list)
    restricted_columns: list[str] = field(default_factory=list)


@dataclass
class RowPolicy:
    """Row-level security (RLS) predicate specification."""

    filters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SecurityPolicy:
    """Security policy configuration for multi-tenant isolation and row-level access control."""

    allowed_tables: list[str] | None = None
    restricted_tables: list[str] = field(default_factory=list)
    tenant_column: str = "tenant_id"
    enforce_tenant_isolation: bool = True
    row_level_filters: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    column_masking: dict[str, list[str]] = field(default_factory=dict)
    sensitive_column_patterns: list[str] = field(default_factory=list)
    masking_strategy: str = "redact"
    max_complexity_score: int | None = None
    column_permissions: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    table_policy: TablePolicy | None = None
    column_policies: dict[str, ColumnPolicy | dict[str, Any]] | None = None
    row_policies: dict[str, RowPolicy | list[dict[str, Any]]] | None = None

    def __post_init__(self) -> None:
        if self.table_policy is not None:
            if self.table_policy.allowed_tables is not None:
                self.allowed_tables = list(self.table_policy.allowed_tables)
            if self.table_policy.restricted_tables:
                self.restricted_tables = list(self.table_policy.restricted_tables)
        if self.column_policies is not None:
            for table_name, col_policy in self.column_policies.items():
                if isinstance(col_policy, ColumnPolicy):
                    self.column_permissions[table_name] = {
                        "allowed_roles": list(col_policy.allowed_roles),
                        "restricted_columns": list(col_policy.restricted_columns),
                    }
                elif isinstance(col_policy, dict):
                    self.column_permissions[table_name] = col_policy
        if self.row_policies is not None:
            for table_name, row_policy in self.row_policies.items():
                if isinstance(row_policy, RowPolicy):
                    self.row_level_filters[table_name] = [
                        f.to_dict() if hasattr(f, "to_dict") else dict(f)
                        for f in row_policy.filters
                    ]
                elif isinstance(row_policy, list):
                    self.row_level_filters[table_name] = row_policy


SecurityGovernor = SecurityPolicy


_ENFORCE_KEYS = ("_enforced", "enforced")


def _drop_equivalent(
    filters: list[Any],
    column: str,
    value: str,
    table: str,
    allow_unprefixed: bool = True,
) -> None:
    """Remove plain client ``column = value`` filters on ``table`` (no paren flags).

    The enforced predicate injected right after supersedes them, so the client
    cannot rely on its own copy (which it could OR away).
    """
    clean = table.split(".")[-1].lower()
    keep: list[Any] = []
    for flt in filters:
        fd = (
            flt
            if isinstance(flt, dict)
            else dict(vars(flt))
            if hasattr(flt, "__dict__")
            else None
        )
        if fd is not None:
            pfx = fd.get("tablePrefix") or fd.get("table_prefix") or fd.get("table")
            same = (
                fd.get("column") == column
                and str(fd.get("op", "eq")) == "eq"
                and str(fd.get("value")) == value
                and (
                    (pfx is None and allow_unprefixed)
                    or (pfx is not None and str(pfx).split(".")[-1].lower() == clean)
                )
                and not fd.get("parenOpen")
                and not fd.get("parenClose")
            )
            if same:
                continue
        keep.append(flt)
    filters[:] = keep


def _extract_columns_from_expression(
    expr: str, default_table: str
) -> list[tuple[str, str]]:
    """Extracts (table_name, column_name) pairs referenced in a SQL expression."""
    cols: list[tuple[str, str]] = []
    clean_def_tbl = default_table.split(".")[-1].lower() if default_table else ""
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(f"SELECT {expr} FROM {clean_def_tbl or 't'}")
        for col_node in tree.find_all(exp.Column):
            t = (col_node.table or clean_def_tbl).lower()
            cols.append((t, col_node.name.lower()))
    except Exception:  # noqa: BLE001, S110
        pass
    return cols


def _is_column_masked(
    table: str | None,
    column: str,
    base_table: str,
    active_policy: SecurityPolicy,
    compiled_patterns: list[re.Pattern[str]],
    alias_map: Mapping[str, str] | None = None,
    referenced_tables: Sequence[str] | None = None,
) -> bool:
    """Checks whether a table.column combination is subject to masking."""
    if "." in column:
        parts = column.split(".")
        tbl_part: str | None = parts[-2] if len(parts) > 1 else parts[0]
        col_part = parts[-1]
    else:
        tbl_part = table
        col_part = column

    if compiled_patterns and col_part != "*":
        if any(p.search(col_part) for p in compiled_patterns):
            return True

    if not active_policy.column_masking:
        return False

    def _resolve(t: str) -> str:
        cleaned = t.strip().lower().split(".")[-1]
        return alias_map.get(cleaned, t.strip()) if alias_map else t.strip()

    if tbl_part:
        resolved_tbl = _resolve(tbl_part)
        clean_tbl = tbl_part.split(".")[-1].lower()
        clean_resolved = resolved_tbl.split(".")[-1].lower()
        tbl_variants = {
            str(tbl_part),
            str(tbl_part).lower(),
            clean_tbl,
            resolved_tbl,
            resolved_tbl.lower(),
            clean_resolved,
            "*",
        }
        for k, v in active_policy.column_masking.items():
            clean_k = k.split(".")[-1].lower()
            if (
                k in tbl_variants
                or k.lower() in tbl_variants
                or clean_k in tbl_variants
            ):
                if (
                    col_part in v
                    or col_part.lower() in [m.lower() for m in v]
                    or column in v
                    or column.lower() in [m.lower() for m in v]
                ):
                    return True
        return False
    else:
        candidate_tables: list[str] = (
            list(referenced_tables)
            if referenced_tables
            else ([base_table] if base_table else ["*"])
        )
        for cand in candidate_tables:
            resolved_cand = _resolve(cand)
            clean_cand = resolved_cand.split(".")[-1].lower()
            tbl_variants = {
                cand,
                cand.lower(),
                clean_cand,
                resolved_cand,
                resolved_cand.lower(),
                "*",
            }
            for k, v in active_policy.column_masking.items():
                clean_k = k.split(".")[-1].lower()
                if (
                    k in tbl_variants
                    or k.lower() in tbl_variants
                    or clean_k in tbl_variants
                ):
                    if col_part in v or col_part.lower() in [m.lower() for m in v]:
                        return True
        return False


def apply_security_policy(
    spec: dict[str, Any] | QuerySpec,
    schema: dict[str, Any] | SchemaSnapshot | None = None,
    context: TenantContext | None = None,
    policy: SecurityPolicy | dict[str, Any] | Any | None = None,
    defined_ctes: set[str] | None = None,
) -> dict[str, Any]:
    """Validates and transforms query spec according to tenant context and security policy.

    Fails closed:
    - If tenant isolation is enforced and context/tenant_id is missing or empty.
    - If referenced tables are in restricted_tables or not in allowed_tables.
    - Automatically injects tenant_column filters and row_level_filters.
    - Redacts or masks columns matching column_masking or sensitive_column_patterns
      for non-privileged roles using configured masking_strategy.
    - Recursively inspects and transforms CTEs, set operations, filter subqueries,
      and derived tables.
    """
    if isinstance(spec, QuerySpec) or hasattr(spec, "__dataclass_fields__"):
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore[arg-type]  # narrowed to a dataclass by the __dataclass_fields__ check
    elif isinstance(spec, dict):
        spec_dict = copy.deepcopy(spec)
    else:
        raise SecurityError(f"Unsupported spec type: {type(spec).__name__}")

    raw_table = spec_dict.get("table")
    if not raw_table:
        raise SecurityError("Query specification missing required 'table'.")

    if policy is None:
        active_policy = SecurityPolicy()
    elif isinstance(policy, SecurityPolicy):
        active_policy = policy
    elif isinstance(policy, dict):
        active_policy = SecurityPolicy(**policy)
    elif hasattr(policy, "privacy") and hasattr(
        policy.privacy, "sensitive_column_patterns"
    ):
        # SecurityConfig instance
        active_policy = SecurityPolicy(
            tenant_column=policy.privacy.tenant_column,
            enforce_tenant_isolation=policy.privacy.enforce_tenant_isolation,
            sensitive_column_patterns=policy.privacy.sensitive_column_patterns,
            masking_strategy=policy.privacy.masking_strategy,
            max_complexity_score=getattr(
                policy.execution,
                "max_complexity_score",
                getattr(policy.execution, "max_ast_complexity", None),
            )
            if hasattr(policy, "execution")
            else None,
        )
    elif hasattr(policy, "sensitive_column_patterns") and hasattr(
        policy, "tenant_column"
    ):
        # PrivacySecurityConfig instance
        active_policy = SecurityPolicy(
            allowed_tables=getattr(policy, "allowed_tables", None),
            restricted_tables=getattr(policy, "restricted_tables", []),
            tenant_column=policy.tenant_column,
            enforce_tenant_isolation=policy.enforce_tenant_isolation,
            row_level_filters=getattr(policy, "row_level_filters", {}),
            column_masking=getattr(policy, "column_masking", {}),
            sensitive_column_patterns=policy.sensitive_column_patterns,
            masking_strategy=getattr(policy, "masking_strategy", "redact"),
            max_complexity_score=getattr(policy, "max_complexity_score", None),
            column_permissions=getattr(policy, "column_permissions", {}),
        )
    else:
        active_policy = policy

    if defined_ctes is None:
        active_defined_ctes: set[str] = set()
    else:
        active_defined_ctes = set(defined_ctes)

    # Recursively apply security policy to CTEs
    ctes = spec_dict.get("ctes")
    if ctes and isinstance(ctes, list):
        for cte in ctes:
            c_name = (
                cte.get("name") if isinstance(cte, dict) else getattr(cte, "name", None)
            )
            if c_name and isinstance(c_name, str):
                active_defined_ctes.add(c_name.strip().lower())
        for cte in ctes:
            c_query = (
                cte.get("query")
                if isinstance(cte, dict)
                else getattr(cte, "query", None)
            )
            if c_query:
                transformed_query = apply_security_policy(
                    c_query,
                    schema=schema,
                    context=context,
                    policy=active_policy,
                    defined_ctes=active_defined_ctes,
                )
                if isinstance(cte, dict):
                    cte["query"] = transformed_query
                elif hasattr(cte, "query"):
                    cte.query = transformed_query

    # Recursively apply security policy to set operations
    set_ops = spec_dict.get("set_operations")
    if set_ops and isinstance(set_ops, list):
        for so in set_ops:
            so_query = (
                so.get("query") if isinstance(so, dict) else getattr(so, "query", None)
            )
            if so_query:
                transformed_so = apply_security_policy(
                    so_query,
                    schema=schema,
                    context=context,
                    policy=active_policy,
                    defined_ctes=active_defined_ctes,
                )
                if isinstance(so, dict):
                    so["query"] = transformed_so
                elif hasattr(so, "query"):
                    so.query = transformed_so

    # Recursively apply security policy to filter subqueries
    for flt in spec_dict.get("filters", []):
        if isinstance(flt, dict):
            subq = flt.get("subquery")
            if subq:
                flt["subquery"] = apply_security_policy(
                    subq,
                    schema=schema,
                    context=context,
                    policy=active_policy,
                    defined_ctes=active_defined_ctes,
                )
            elif isinstance(flt.get("value"), dict) and "table" in flt["value"]:
                flt["value"] = apply_security_policy(
                    flt["value"],
                    schema=schema,
                    context=context,
                    policy=active_policy,
                    defined_ctes=active_defined_ctes,
                )

    if isinstance(raw_table, dict) or hasattr(raw_table, "__dataclass_fields__"):
        spec_dict["table"] = apply_security_policy(
            raw_table,
            schema=schema,
            context=context,
            policy=active_policy,
            defined_ctes=active_defined_ctes,
        )
        base_table = "subquery"
        clean_base_table = "subquery"
        referenced_tables = []
    elif isinstance(raw_table, str) and raw_table.strip():
        base_table = raw_table.strip()
        clean_base_table = base_table.split(".")[-1].lower()
        referenced_tables = [base_table]
    else:
        raise SecurityError("Query specification missing required 'table'.")

    # 0. Pre-execution Complexity Quota Governor
    max_complexity = getattr(active_policy, "max_complexity_score", None)
    if max_complexity is not None:
        from query_builder.security import calculate_ast_complexity

        score = calculate_ast_complexity(spec_dict)
        if score > max_complexity:
            raise SecurityError(
                f"Query complexity score ({score}) exceeds authorized quota ceiling ({max_complexity})."
            )

    # 1. Fail-closed tenant context verification
    if active_policy.enforce_tenant_isolation:
        if context is None:
            raise SecurityError(
                "Tenant isolation enforced but no TenantContext provided."
            )
        if not context.tenant_id or not str(context.tenant_id).strip():
            raise SecurityError(
                "Tenant isolation enforced but tenant_id is missing or empty."
            )

    # 2. Table authorization (base table + joined tables)
    for join in spec_dict.get("joins", []):
        j_tbl = (
            join.get("table")
            if isinstance(join, dict)
            else getattr(join, "table", None)
        )
        if j_tbl and isinstance(j_tbl, str):
            referenced_tables.append(j_tbl.strip())

    alias_map: dict[str, str] = {}
    base_alias = (
        spec_dict.get("alias")
        if isinstance(spec_dict, dict)
        else getattr(spec_dict, "alias", None)
    )
    if base_alias and isinstance(base_alias, str) and base_table:
        alias_map[base_alias.strip().lower()] = base_table
        alias_map[base_alias.strip().split(".")[-1].lower()] = base_table

    for join in spec_dict.get("joins", []):
        j_tbl = (
            join.get("table")
            if isinstance(join, dict)
            else getattr(join, "table", None)
        )
        j_alias = (
            join.get("alias")
            if isinstance(join, dict)
            else getattr(join, "alias", None)
        )
        if j_alias and isinstance(j_alias, str) and j_tbl and isinstance(j_tbl, str):
            alias_map[j_alias.strip().lower()] = j_tbl.strip()
            alias_map[j_alias.strip().split(".")[-1].lower()] = j_tbl.strip()

    def _resolve_table(t: str | None) -> str | None:
        if not t:
            return None
        cleaned = str(t).strip().lower().split(".")[-1]
        return alias_map.get(cleaned, str(t).strip())

    for tbl in referenced_tables:
        clean_tbl = tbl.split(".")[-1].lower()
        if clean_tbl in active_defined_ctes:
            continue
        if active_policy.restricted_tables:
            for r in active_policy.restricted_tables:
                if clean_tbl == r.split(".")[-1].lower():
                    raise SecurityError(
                        f"Access to restricted table '{tbl}' is forbidden."
                    )
        if active_policy.allowed_tables is not None:
            allowed_clean = {
                a.split(".")[-1].lower() for a in active_policy.allowed_tables
            }
            if clean_tbl not in allowed_clean:
                raise SecurityError(
                    f"Access to table '{tbl}' is forbidden by allowed_tables policy."
                )

    filters = spec_dict.setdefault("filters", [])

    # Client-supplied filters can never carry the internal enforcement marker.
    # Only predicates injected below are flagged ``_enforced`` (AND-ed by the
    # compiler outside the client's filter group).
    for i, flt in enumerate(filters):
        if isinstance(flt, dict):
            if "_enforced" in flt or "enforced" in flt:
                flt = {k: v for k, v in flt.items() if k not in _ENFORCE_KEYS}
                filters[i] = flt
        elif any(hasattr(flt, k) for k in _ENFORCE_KEYS):
            for k in _ENFORCE_KEYS:
                if hasattr(flt, k):
                    try:
                        delattr(flt, k)
                    except AttributeError:
                        pass

    # 3. Tenant isolation filter injection
    if active_policy.enforce_tenant_isolation and context and context.tenant_id:
        tenant_id_str = str(context.tenant_id).strip()

        # Always inject an enforced predicate on base table if not a derived subquery
        if base_table != "subquery":
            _drop_equivalent(
                filters, active_policy.tenant_column, tenant_id_str, base_table
            )
            filters.insert(
                0,
                {
                    "column": active_policy.tenant_column,
                    "op": "eq",
                    "value": tenant_id_str,
                    "table": base_table,
                    "_enforced": True,
                },
            )

        # Check join tables
        for join in spec_dict.get("joins", []):
            j_tbl = (
                join.get("table")
                if isinstance(join, dict)
                else getattr(join, "table", None)
            )
            if not j_tbl or not isinstance(j_tbl, str):
                continue
            clean_j = j_tbl.strip().split(".")[-1].lower()

            has_col = True
            if schema is not None:
                tables_map = getattr(schema, "tables", None) or (
                    schema.get("tables") if isinstance(schema, dict) else None
                )
                if tables_map and isinstance(tables_map, dict):
                    tbl_info = tables_map.get(j_tbl) or tables_map.get(clean_j)
                    if tbl_info is not None:
                        cols = (
                            tbl_info.get("columns", [])
                            if isinstance(tbl_info, dict)
                            else getattr(tbl_info, "columns", [])
                        )
                        col_names = [
                            c.name
                            if hasattr(c, "name")
                            else (c.get("name") if isinstance(c, dict) else str(c))
                            for c in cols
                        ]
                        if active_policy.tenant_column not in col_names:
                            has_col = False

            if has_col:
                _drop_equivalent(
                    filters, active_policy.tenant_column, tenant_id_str, j_tbl
                )
                filters.append(
                    {
                        "column": active_policy.tenant_column,
                        "op": "eq",
                        "value": tenant_id_str,
                        "table": j_tbl,
                        "_enforced": True,
                    }
                )

    def _schema_columns_for_table(tbl_name: str) -> list[str]:
        if schema is None:
            return []
        tables_map = getattr(schema, "tables", None) or (
            schema.get("tables") if isinstance(schema, dict) else None
        )
        if not tables_map or not isinstance(tables_map, dict):
            return []
        clean_t = tbl_name.split(".")[-1].lower()
        tbl_info = tables_map.get(tbl_name) or tables_map.get(clean_t)
        if tbl_info is None:
            for k, v in tables_map.items():
                if str(k).split(".")[-1].lower() == clean_t:
                    tbl_info = v
                    break
        if tbl_info is None:
            return []
        raw_cols = (
            tbl_info.get("columns", [])
            if isinstance(tbl_info, dict)
            else getattr(tbl_info, "columns", [])
        )
        if isinstance(raw_cols, dict):
            return [str(k) for k in raw_cols]
        return [
            str(
                c.name
                if hasattr(c, "name")
                else (c.get("name") if isinstance(c, dict) else c)
            )
            for c in raw_cols
        ]

    # 4. Row-Level Security (RLS) Filter Injection
    if active_policy.row_level_filters:
        for tbl in referenced_tables:
            clean_tbl = tbl.split(".")[-1].lower()
            if clean_tbl in active_defined_ctes:
                continue
            rules = (
                active_policy.row_level_filters.get(tbl)
                or active_policy.row_level_filters.get(clean_tbl)
                or active_policy.row_level_filters.get("*")
                or []
            )
            for rule in rules:
                rule_copy = dict(rule)
                raw_val = rule_copy.get("value")
                if raw_val == "$user_id":
                    rule_copy["value"] = context.user_id if context else None
                elif raw_val == "$tenant_id":
                    rule_copy["value"] = context.tenant_id if context else None
                elif isinstance(raw_val, str) and raw_val.startswith("$attr."):
                    attr_name = raw_val[len("$attr.") :]
                    rule_copy["value"] = (
                        context.attributes.get(attr_name)
                        if context and context.attributes
                        else None
                    )
                if (
                    "table" not in rule_copy
                    and "tablePrefix" not in rule_copy
                    and "table_prefix" not in rule_copy
                ):
                    rule_copy["table"] = tbl
                rule_copy.pop("enforced", None)
                rule_copy.pop("combiner", None)
                rule_copy["_enforced"] = True

                col_name = rule_copy.get("column")
                if schema is not None and col_name:
                    c_names = _schema_columns_for_table(tbl)
                    if c_names and col_name not in c_names:
                        continue

                filters.append(rule_copy)

    # 4.5. Column-Level Access Control (CLAC)
    col_perms = getattr(active_policy, "column_permissions", None)
    if col_perms:
        user_roles = {
            r.lower() for r in (context.roles if context else []) if isinstance(r, str)
        }
        for tbl in referenced_tables:
            clean_tbl = tbl.split(".")[-1].lower()
            perm = col_perms.get(tbl) or col_perms.get(clean_tbl) or col_perms.get("*")
            if perm:
                allowed_roles = {r.lower() for r in perm.get("allowed_roles", [])}
                restricted_cols = {
                    c.lower() for c in perm.get("restricted_columns", [])
                }
                if restricted_cols and not (user_roles & allowed_roles):
                    if not spec_dict.get("columns"):
                        schema_cols = _schema_columns_for_table(tbl)
                        if schema_cols:
                            spec_dict["columns"] = [
                                c
                                for c in schema_cols
                                if c.lower() not in restricted_cols
                            ]

                    def _check_clac_restricted(
                        raw_tbl: str | None,
                        col_raw: str,
                        *,
                        _clean_tbl: str = clean_tbl,
                        _restricted_cols: set[str] = restricted_cols,
                        _orig_tbl: str = tbl,
                        _allowed_roles: set[str] = allowed_roles,
                    ) -> None:
                        col_lower = col_raw.split(".")[-1].lower()
                        parts = col_raw.split(".")
                        tbl_candidate = parts[-2] if len(parts) > 1 else raw_tbl
                        resolved = _resolve_table(tbl_candidate)
                        clean_col_tbl = (
                            resolved.split(".")[-1].lower() if resolved else None
                        )
                        if (
                            clean_col_tbl is None
                            or clean_col_tbl == _clean_tbl
                            or clean_col_tbl == "*"
                        ) and (col_lower in _restricted_cols or col_lower == "*"):
                            target_col = (
                                sorted(_restricted_cols)[0]
                                if col_lower == "*"
                                else col_lower
                            )
                            raise SecurityError(
                                f"Access to restricted column '{target_col}' on table '{_orig_tbl}' requires roles: {sorted(_allowed_roles)}."
                            )

                    for c in spec_dict.get("columns", []):
                        if isinstance(c, str):
                            _check_clac_restricted(None, c)
                        elif isinstance(c, dict):
                            expr = c.get("expression") or c.get("raw_expression")
                            if expr and isinstance(expr, str):
                                expr_cols = _extract_columns_from_expression(
                                    expr, clean_base_table
                                )
                                for e_tbl, e_col in expr_cols:
                                    _check_clac_restricted(e_tbl, e_col)
                            c_name = str(c.get("column") or c.get("name", ""))
                            if c_name:
                                c_t = (
                                    c.get("table")
                                    or c.get("tablePrefix")
                                    or c.get("table_prefix")
                                )
                                _check_clac_restricted(c_t, c_name)

                    def _check_filter_clac(flt: Any) -> None:
                        fd = dict(flt.__dict__) if hasattr(flt, "__dict__") else flt
                        if not isinstance(fd, dict):
                            return
                        sub_flts = fd.get("filters")
                        if isinstance(sub_flts, list):
                            for sf in sub_flts:
                                _check_filter_clac(sf)
                        expr = fd.get("expression") or fd.get("raw_expression")
                        if expr and isinstance(expr, str):
                            for e_tbl, e_col in _extract_columns_from_expression(
                                expr, clean_base_table
                            ):
                                _check_clac_restricted(e_tbl, e_col)
                        c_col = fd.get("column") or fd.get("field")
                        if c_col and isinstance(c_col, str):
                            c_t = (
                                fd.get("table")
                                or fd.get("tablePrefix")
                                or fd.get("table_prefix")
                            )
                            _check_clac_restricted(c_t, c_col)

                    for f in spec_dict.get("filters", []):
                        _check_filter_clac(f)

                    for h in spec_dict.get("having", []):
                        _check_filter_clac(h)

                    for ob in spec_dict.get("order_by", []):
                        if isinstance(ob, str):
                            _check_clac_restricted(None, ob.split()[0])
                        else:
                            _check_filter_clac(ob)

    # 5. Column Masking
    if active_policy.column_masking or active_policy.sensitive_column_patterns:
        is_admin = bool(
            context
            and any(r.lower() == "admin" for r in context.roles if isinstance(r, str))
        )
        if not is_admin:
            cols = list(spec_dict.get("columns", []))
            compiled_patterns = [
                re.compile(p) for p in active_policy.sensitive_column_patterns
            ]
            # Expand empty or wildcard columns when schema is provided and table has masked columns
            if not cols and base_table != "subquery":
                schema_cols = _schema_columns_for_table(base_table)
                if schema_cols and any(
                    _is_column_masked(
                        base_table,
                        sc,
                        base_table,
                        active_policy,
                        compiled_patterns,
                        alias_map=alias_map,
                        referenced_tables=referenced_tables,
                    )
                    for sc in schema_cols
                ):
                    cols = list(schema_cols)
            elif any(
                (isinstance(c, str) and c.split(".")[-1] == "*")
                or (
                    isinstance(c, dict)
                    and str(c.get("column") or c.get("name", "")).split(".")[-1] == "*"
                )
                for c in cols
            ):
                expanded_cols: list[Any] = []
                for c in cols:
                    is_star = (isinstance(c, str) and c.split(".")[-1] == "*") or (
                        isinstance(c, dict)
                        and str(c.get("column") or c.get("name", "")).split(".")[-1]
                        == "*"
                    )
                    if is_star:
                        star_tbl = (
                            c.split(".")[-2]
                            if isinstance(c, str) and "." in c
                            else (
                                (
                                    c.get("table")
                                    or c.get("tablePrefix")
                                    or c.get("table_prefix")
                                )
                                if isinstance(c, dict)
                                else None
                            )
                        )
                        resolved_star_tbl = _resolve_table(star_tbl) or base_table
                        schema_cols = _schema_columns_for_table(resolved_star_tbl)
                        if schema_cols:
                            expanded_cols.extend(schema_cols)
                        else:
                            expanded_cols.append(c)
                    else:
                        expanded_cols.append(c)
                cols = expanded_cols

            new_cols: list[Any] = []
            for c in cols:
                if isinstance(c, str):
                    parts = c.split(".")
                    c_tbl = parts[-2] if len(parts) > 1 else None
                    c_name = parts[-1]
                    if _is_column_masked(
                        c_tbl,
                        c_name,
                        base_table,
                        active_policy,
                        compiled_patterns,
                        alias_map=alias_map,
                        referenced_tables=referenced_tables,
                    ):
                        col_entry: dict[str, Any] = {
                            "column": c_name,
                            "alias": f"{c_name}_masked",
                            "masked": True,
                        }
                        if active_policy.masking_strategy != "redact":
                            col_entry["masking_strategy"] = (
                                active_policy.masking_strategy
                            )
                        new_cols.append(col_entry)
                    else:
                        new_cols.append(c)
                elif isinstance(c, dict):
                    expr = c.get("expression") or c.get("raw_expression")
                    if expr and isinstance(expr, str):
                        expr_cols = _extract_columns_from_expression(expr, base_table)
                        for e_tbl, e_col in expr_cols:
                            if _is_column_masked(
                                e_tbl,
                                e_col,
                                base_table,
                                active_policy,
                                compiled_patterns,
                                alias_map=alias_map,
                                referenced_tables=referenced_tables,
                            ):
                                raise SecurityError(
                                    f"Access to masked column '{e_col}' in expression is forbidden."
                                )
                    c_name = c.get("column") or c.get("name", "")
                    c_tbl = (
                        c.get("table") or c.get("tablePrefix") or c.get("table_prefix")
                    )
                    if c_name and _is_column_masked(
                        c_tbl,
                        str(c_name),
                        base_table,
                        active_policy,
                        compiled_patterns,
                        alias_map=alias_map,
                        referenced_tables=referenced_tables,
                    ):
                        c_copy = dict(c)
                        c_copy["alias"] = c.get("alias") or f"{c_name}_masked"
                        c_copy["masked"] = True
                        if active_policy.masking_strategy != "redact":
                            c_copy["masking_strategy"] = active_policy.masking_strategy
                        new_cols.append(c_copy)
                    else:
                        new_cols.append(c)
                else:
                    new_cols.append(c)
            spec_dict["columns"] = new_cols

            def _check_filter_masks(flt: Any) -> None:
                flt_dict = dict(flt.__dict__) if hasattr(flt, "__dict__") else flt
                if not isinstance(flt_dict, dict):
                    return

                sub_filters = flt_dict.get("filters")
                if isinstance(sub_filters, list):
                    for sf in sub_filters:
                        _check_filter_masks(sf)

                subq = flt_dict.get("subquery") or (
                    flt_dict.get("value")
                    if isinstance(flt_dict.get("value"), dict)
                    else None
                )
                if isinstance(subq, dict):
                    subq_cols = subq.get("columns", [])
                    subq_tbl = str(subq.get("table") or base_table)
                    for sc in subq_cols:
                        c_name = (
                            sc.get("column")
                            if isinstance(sc, dict)
                            else (sc if isinstance(sc, str) else None)
                        )
                        if (isinstance(sc, dict) and sc.get("masked")) or (
                            c_name
                            and _is_column_masked(
                                subq_tbl,
                                str(c_name),
                                subq_tbl,
                                active_policy,
                                compiled_patterns,
                                alias_map=alias_map,
                                referenced_tables=referenced_tables,
                            )
                        ):
                            raise SecurityError(
                                f"Filtering or sorting on masked column '{c_name or 'column'}' is forbidden."
                            )

                expr = flt_dict.get("expression") or flt_dict.get("raw_expression")
                if expr and isinstance(expr, str):
                    expr_cols = _extract_columns_from_expression(expr, base_table)
                    for e_tbl, e_col in expr_cols:
                        if _is_column_masked(
                            e_tbl,
                            e_col,
                            base_table,
                            active_policy,
                            compiled_patterns,
                            alias_map=alias_map,
                            referenced_tables=referenced_tables,
                        ):
                            raise SecurityError(
                                f"Filtering or sorting on masked column '{e_col}' is forbidden."
                            )

                col = flt_dict.get("column") or flt_dict.get("field")
                if col and isinstance(col, str):
                    col_tbl = (
                        flt_dict.get("table")
                        or flt_dict.get("tablePrefix")
                        or flt_dict.get("table_prefix")
                    )
                    if _is_column_masked(
                        col_tbl,
                        col,
                        base_table,
                        active_policy,
                        compiled_patterns,
                        alias_map=alias_map,
                        referenced_tables=referenced_tables,
                    ):
                        raise SecurityError(
                            f"Filtering or sorting on masked column '{col}' is forbidden."
                        )

            for f in spec_dict.get("filters", []):
                _check_filter_masks(f)

            for h in spec_dict.get("having", []):
                h_dict = dict(h.__dict__) if hasattr(h, "__dict__") else h
                if isinstance(h_dict, dict):
                    expr = h_dict.get("expression") or h_dict.get("raw_expression")
                    if expr and isinstance(expr, str):
                        expr_cols = _extract_columns_from_expression(expr, base_table)
                        for e_tbl, e_col in expr_cols:
                            if _is_column_masked(
                                e_tbl,
                                e_col,
                                base_table,
                                active_policy,
                                compiled_patterns,
                                alias_map=alias_map,
                                referenced_tables=referenced_tables,
                            ):
                                raise SecurityError(
                                    f"Filtering or sorting on masked column '{e_col}' is forbidden."
                                )
                    col = h_dict.get("column") or h_dict.get("field")
                    if col and isinstance(col, str):
                        h_tbl = (
                            h_dict.get("table")
                            or h_dict.get("tablePrefix")
                            or h_dict.get("table_prefix")
                        )
                        if _is_column_masked(
                            h_tbl,
                            col,
                            base_table,
                            active_policy,
                            compiled_patterns,
                            alias_map=alias_map,
                            referenced_tables=referenced_tables,
                        ):
                            raise SecurityError(
                                f"Filtering or sorting on masked column '{col}' is forbidden."
                            )

            for ob in spec_dict.get("order_by", []):
                if isinstance(ob, str):
                    ob_col = ob.split()[0]
                    if _is_column_masked(
                        None,
                        ob_col,
                        base_table,
                        active_policy,
                        compiled_patterns,
                        alias_map=alias_map,
                        referenced_tables=referenced_tables,
                    ):
                        raise SecurityError(
                            f"Filtering or sorting on masked column '{ob_col}' is forbidden."
                        )
                else:
                    ob_dict = dict(ob.__dict__) if hasattr(ob, "__dict__") else ob
                    if isinstance(ob_dict, dict):
                        expr = ob_dict.get("expression") or ob_dict.get(
                            "raw_expression"
                        )
                        if expr and isinstance(expr, str):
                            expr_cols = _extract_columns_from_expression(
                                expr, base_table
                            )
                            for e_tbl, e_col in expr_cols:
                                if _is_column_masked(
                                    e_tbl,
                                    e_col,
                                    base_table,
                                    active_policy,
                                    compiled_patterns,
                                    alias_map=alias_map,
                                    referenced_tables=referenced_tables,
                                ):
                                    raise SecurityError(
                                        f"Filtering or sorting on masked column '{e_col}' is forbidden."
                                    )
                        col = ob_dict.get("column") or ob_dict.get("field")
                        if col and isinstance(col, str):
                            ob_tbl = (
                                ob_dict.get("table")
                                or ob_dict.get("tablePrefix")
                                or ob_dict.get("table_prefix")
                            )
                            if _is_column_masked(
                                ob_tbl,
                                col,
                                base_table,
                                active_policy,
                                compiled_patterns,
                                alias_map=alias_map,
                                referenced_tables=referenced_tables,
                            ):
                                raise SecurityError(
                                    f"Filtering or sorting on masked column '{col}' is forbidden."
                                )

    return spec_dict
