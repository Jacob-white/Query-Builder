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
                    tables_map = getattr(schema, "tables", None) or (
                        schema.get("tables") if isinstance(schema, dict) else None
                    )
                    if tables_map and isinstance(tables_map, dict):
                        tbl_info = tables_map.get(tbl) or tables_map.get(clean_tbl)
                        if tbl_info is not None:
                            t_cols = (
                                tbl_info.get("columns", [])
                                if isinstance(tbl_info, dict)
                                else getattr(tbl_info, "columns", [])
                            )
                            c_names = [
                                c.name
                                if hasattr(c, "name")
                                else (c.get("name") if isinstance(c, dict) else str(c))
                                for c in t_cols
                            ]
                            if col_name not in c_names:
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
                    for c in spec_dict.get("columns", []):
                        if isinstance(c, str):
                            col_name = c.split(".")[-1].lower()
                            col_tbl = (
                                c.split(".")[0].lower()
                                if "." in c
                                else clean_base_table
                            )
                            if (
                                col_tbl == clean_tbl or col_tbl == "*"
                            ) and col_name in restricted_cols:
                                raise SecurityError(
                                    f"Access to restricted column '{col_name}' on table '{tbl}' requires roles: {sorted(allowed_roles)}."
                                )
                        elif isinstance(c, dict):
                            expr = c.get("expression") or c.get("raw_expression")
                            if expr and isinstance(expr, str):
                                expr_cols = _extract_columns_from_expression(
                                    expr, clean_base_table
                                )
                                for e_tbl, e_col in expr_cols:
                                    if (
                                        e_tbl == clean_tbl or e_tbl == "*" or not e_tbl
                                    ) and e_col in restricted_cols:
                                        raise SecurityError(
                                            f"Access to restricted column '{e_col}' on table '{tbl}' via expression requires roles: {sorted(allowed_roles)}."
                                        )
                            col_name = str(c.get("column") or c.get("name", "")).lower()
                            if not col_name:
                                continue
                            col_tbl = (
                                str(c.get("table") or clean_base_table)
                                .split(".")[-1]
                                .lower()
                            )
                            if (
                                col_tbl == clean_tbl or col_tbl == "*"
                            ) and col_name in restricted_cols:
                                raise SecurityError(
                                    f"Access to restricted column '{col_name}' on table '{tbl}' requires roles: {sorted(allowed_roles)}."
                                )

    # 5. Column Masking
    if active_policy.column_masking or active_policy.sensitive_column_patterns:
        is_admin = bool(
            context
            and any(r.lower() == "admin" for r in context.roles if isinstance(r, str))
        )
        if not is_admin:
            cols = spec_dict.get("columns", [])
            new_cols: list[Any] = []
            compiled_patterns = [
                re.compile(p) for p in active_policy.sensitive_column_patterns
            ]
            for c in cols:
                if isinstance(c, str):
                    parts = c.split(".")
                    c_tbl = parts[0] if len(parts) > 1 else base_table
                    c_name = parts[-1]
                    masked_list = (
                        active_policy.column_masking.get(c_tbl)
                        or active_policy.column_masking.get(c_tbl.lower())
                        or active_policy.column_masking.get(
                            c_tbl.split(".")[-1].lower()
                        )
                        or active_policy.column_masking.get("*", [])
                    )
                    is_masked = c_name in masked_list or c in masked_list
                    if not is_masked and compiled_patterns:
                        is_masked = any(p.search(c_name) for p in compiled_patterns)
                    if is_masked:
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
                            e_masked_list = (
                                active_policy.column_masking.get(e_tbl)
                                or active_policy.column_masking.get(str(e_tbl).lower())
                                or active_policy.column_masking.get(
                                    str(e_tbl).split(".")[-1].lower()
                                )
                                or active_policy.column_masking.get("*", [])
                            )
                            is_e_masked = e_col in e_masked_list or e_col.lower() in [
                                m.lower() for m in e_masked_list
                            ]
                            if not is_e_masked and compiled_patterns:
                                is_e_masked = any(
                                    p.search(e_col) for p in compiled_patterns
                                )
                            if is_e_masked:
                                raise SecurityError(
                                    f"Access to masked column '{e_col}' in expression is forbidden."
                                )
                    c_name = c.get("column") or c.get("name", "")
                    c_tbl = (
                        c.get("table")
                        or c.get("tablePrefix")
                        or c.get("table_prefix")
                        or base_table
                    )
                    masked_list = (
                        active_policy.column_masking.get(c_tbl)
                        or active_policy.column_masking.get(str(c_tbl).lower())
                        or active_policy.column_masking.get(
                            str(c_tbl).split(".")[-1].lower()
                        )
                        or active_policy.column_masking.get("*", [])
                    )
                    is_masked = c_name in masked_list
                    if not is_masked and compiled_patterns:
                        is_masked = any(
                            p.search(str(c_name)) for p in compiled_patterns
                        )
                    if is_masked:
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

    return spec_dict
