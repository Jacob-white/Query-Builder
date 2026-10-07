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


def apply_security_policy(
    spec: dict[str, Any] | QuerySpec,
    schema: dict[str, Any] | SchemaSnapshot | None = None,
    context: TenantContext | None = None,
    policy: SecurityPolicy | dict[str, Any] | Any | None = None,
) -> dict[str, Any]:
    """Validates and transforms query spec according to tenant context and security policy.

    Fails closed:
    - If tenant isolation is enforced and context/tenant_id is missing or empty.
    - If referenced tables are in restricted_tables or not in allowed_tables.
    - Automatically injects tenant_column filters and row_level_filters.
    - Redacts or masks columns matching column_masking or sensitive_column_patterns
      for non-privileged roles using configured masking_strategy.
    """
    if isinstance(spec, QuerySpec) or hasattr(spec, "__dataclass_fields__"):
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore
    elif isinstance(spec, dict):
        spec_dict = copy.deepcopy(spec)
    else:
        raise SecurityError(f"Unsupported spec type: {type(spec).__name__}")

    raw_table = spec_dict.get("table")
    if not raw_table or not isinstance(raw_table, str) or not raw_table.strip():
        raise SecurityError("Query specification missing required 'table'.")

    base_table = raw_table.strip()
    clean_base_table = base_table.split(".")[-1].lower()

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
            ) if hasattr(policy, "execution") else None,
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
    referenced_tables: list[str] = [base_table]
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

    # 3. Tenant isolation filter injection
    if active_policy.enforce_tenant_isolation and context and context.tenant_id:
        tenant_id_str = str(context.tenant_id).strip()

        # Check if base table filter exists
        has_base_tenant_filter = False
        for flt in filters:
            col = (
                flt.get("column")
                if isinstance(flt, dict)
                else getattr(flt, "column", None)
            )
            tbl_pfx = (
                flt.get("tablePrefix")
                if isinstance(flt, dict)
                else getattr(flt, "table_prefix", None)
            )
            if tbl_pfx is None and isinstance(flt, dict):
                tbl_pfx = flt.get("table")
            val = (
                flt.get("value")
                if isinstance(flt, dict)
                else getattr(flt, "value", None)
            )
            op = flt.get("op") if isinstance(flt, dict) else getattr(flt, "op", "eq")
            if (
                col == active_policy.tenant_column
                and op == "eq"
                and str(val) == tenant_id_str
                and (
                    tbl_pfx is None
                    or tbl_pfx == base_table
                    or tbl_pfx.split(".")[-1].lower() == clean_base_table
                )
            ):
                has_base_tenant_filter = True
                break

        if not has_base_tenant_filter:
            filters.insert(
                0,
                {
                    "column": active_policy.tenant_column,
                    "op": "eq",
                    "value": tenant_id_str,
                    "table": base_table,
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
                has_j_tenant_filter = False
                for flt in filters:
                    col = (
                        flt.get("column")
                        if isinstance(flt, dict)
                        else getattr(flt, "column", None)
                    )
                    tbl_pfx = (
                        flt.get("tablePrefix")
                        if isinstance(flt, dict)
                        else getattr(flt, "table_prefix", None)
                    )
                    if tbl_pfx is None and isinstance(flt, dict):
                        tbl_pfx = flt.get("table")
                    val = (
                        flt.get("value")
                        if isinstance(flt, dict)
                        else getattr(flt, "value", None)
                    )
                    op = (
                        flt.get("op")
                        if isinstance(flt, dict)
                        else getattr(flt, "op", "eq")
                    )
                    if (
                        col == active_policy.tenant_column
                        and op == "eq"
                        and str(val) == tenant_id_str
                        and (
                            tbl_pfx == j_tbl
                            or (tbl_pfx and tbl_pfx.split(".")[-1].lower() == clean_j)
                        )
                    ):
                        has_j_tenant_filter = True
                        break

                if not has_j_tenant_filter:
                    filters.append(
                        {
                            "column": active_policy.tenant_column,
                            "op": "eq",
                            "value": tenant_id_str,
                            "table": j_tbl,
                        }
                    )

    # 4. Row-Level Security (RLS) Filter Injection
    if active_policy.row_level_filters:
        for tbl in referenced_tables:
            clean_tbl = tbl.split(".")[-1].lower()
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
                filters.append(rule_copy)

    # 4.5. Column-Level Access Control (CLAC)
    col_perms = getattr(active_policy, "column_permissions", None)
    if col_perms:
        user_roles = set(r.lower() for r in (context.roles if context else []) if isinstance(r, str))
        for tbl in referenced_tables:
            clean_tbl = tbl.split(".")[-1].lower()
            perm = (
                col_perms.get(tbl)
                or col_perms.get(clean_tbl)
                or col_perms.get("*")
            )
            if perm:
                allowed_roles = set(r.lower() for r in perm.get("allowed_roles", []))
                restricted_cols = set(c.lower() for c in perm.get("restricted_columns", []))
                if restricted_cols and not (user_roles & allowed_roles):
                    for c in spec_dict.get("columns", []):
                        if isinstance(c, str):
                            col_name = c.split(".")[-1].lower()
                            col_tbl = c.split(".")[0].lower() if "." in c else clean_base_table
                        elif isinstance(c, dict):
                            col_name = str(c.get("column") or c.get("name", "")).lower()
                            col_tbl = str(c.get("table") or clean_base_table).split(".")[-1].lower()
                        else:
                            continue
                        if (col_tbl == clean_tbl or col_tbl == "*") and col_name in restricted_cols:
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
