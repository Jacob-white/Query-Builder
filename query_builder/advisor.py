"""
Performance Advisor & Cloud Cost Estimation Engine.
===================================================
Provides backend pre-execution cloud cost calculation (BigQuery, Snowflake),
1-click index recommendations, and query performance hotspot detection.
"""

from __future__ import annotations

import re
from typing import Any

from query_builder.models import QuerySpec, SchemaSnapshot

# Pricing Constants
BIGQUERY_PER_TB_DOLLARS = 6.25
MIN_BIGQUERY_SCAN_BYTES = 10 * 1024 * 1024
ESTIMATED_ROW_BYTE_SIZE = 128


def estimate_cloud_cost(
    sql: str,
    dialect: str = "postgres",
    table_stats: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Estimates byte volume scanned and cloud warehouse dollar cost before execution."""
    clean = sql.lower()

    # Find referenced table names
    from_matches = re.finditer(
        r"\b(?:from|join)\s+([a-zA-Z0-9_\".`\[\]]+)", clean, re.IGNORECASE
    )
    tables: list[str] = []
    for m in from_matches:
        raw = re.sub(r'["\'`\[\]]', "", m.group(1))
        parts = raw.split(".")
        tables.append(parts[-1])

    total_bytes = 0
    for tbl in tables:
        if table_stats and tbl in table_stats and table_stats[tbl].get("byte_size"):
            total_bytes += int(table_stats[tbl]["byte_size"])
        elif table_stats and tbl in table_stats and table_stats[tbl].get("row_count"):
            total_bytes += int(table_stats[tbl]["row_count"]) * ESTIMATED_ROW_BYTE_SIZE
        else:
            total_bytes += 25 * 1024 * 1024  # 25 MB heuristic default

    d = dialect.lower()
    is_bigquery = d == "bigquery"
    is_snowflake = d == "snowflake"

    dollar_cost = 0.0
    credits_estimated: float | None = None
    pricing_tier = "Zero-Cost Local / Provisioned Instance"

    if is_bigquery:
        billed_bytes = max(MIN_BIGQUERY_SCAN_BYTES, total_bytes)
        tb_scanned = billed_bytes / (1024 * 1024 * 1024 * 1024)
        dollar_cost = round(tb_scanned * BIGQUERY_PER_TB_DOLLARS, 5)
        pricing_tier = "BigQuery On-Demand ($6.25/TB)"
    elif is_snowflake:
        seconds_est = max(1, min(60, int(total_bytes / (50 * 1024 * 1024))))
        credits_estimated = round((seconds_est / 3600.0) * 1.0, 4)
        dollar_cost = round(credits_estimated * 3.0, 4)
        pricing_tier = "Snowflake X-Small (1 Credit/Hr)"

    return {
        "bytes_scanned_estimated": total_bytes,
        "dollar_cost_estimated": dollar_cost,
        "credits_estimated": credits_estimated,
        "pricing_tier": pricing_tier,
        "is_cached": False,
    }


def _build_alias_map(spec_dict: dict[str, Any], clean_primary: str) -> dict[str, str]:
    alias_map: dict[str, str] = {"t1": clean_primary}
    if spec_dict.get("alias"):
        alias_map[str(spec_dict["alias"]).split(".")[-1]] = clean_primary

    joins = spec_dict.get("joins", [])
    for idx, j in enumerate(joins, start=2):
        j_dict = (
            j.to_dict()
            if hasattr(j, "to_dict")
            else (dict(j) if isinstance(j, dict) else {})
        )
        j_tbl = str(j_dict.get("table", "") or "").split(".")[-1]
        if j_tbl:
            alias_map[f"t{idx}"] = j_tbl
            if j_dict.get("alias"):
                alias_map[str(j_dict["alias"]).split(".")[-1]] = j_tbl
    return alias_map


def _extract_primary_keys(
    schema_snapshot: SchemaSnapshot | dict[str, Any] | None,
) -> dict[str, list[str]]:
    pk_by_table: dict[str, list[str]] = {}
    if schema_snapshot is None:
        return pk_by_table

    tables_meta = getattr(schema_snapshot, "tables", None) or (
        schema_snapshot.get("tables", schema_snapshot)
        if isinstance(schema_snapshot, dict)
        else None
    )
    if not isinstance(tables_meta, dict):
        return pk_by_table

    for t_name, t_meta in tables_meta.items():
        if not isinstance(t_meta, dict) and not hasattr(t_meta, "columns"):
            continue
        clean_t = str(t_name).split(".")[-1].lower()
        cols = (
            t_meta.get("columns", [])
            if isinstance(t_meta, dict)
            else getattr(t_meta, "columns", [])
        )
        pks: list[str] = []
        explicit_pks = (
            t_meta.get("primary_keys")
            if isinstance(t_meta, dict)
            else getattr(t_meta, "primary_keys", None)
        )
        if isinstance(explicit_pks, (list, tuple)):
            for pk in explicit_pks:
                if pk and str(pk).lower() not in pks:
                    pks.append(str(pk).lower())
        id_explicitly_non_pk = False
        if isinstance(cols, dict):
            for c_name, c_meta in cols.items():
                is_pk = (
                    c_meta.get("is_primary") or c_meta.get("primary_key")
                    if isinstance(c_meta, dict)
                    else getattr(c_meta, "is_primary", False)
                    or getattr(c_meta, "primary_key", False)
                )
                if is_pk and c_name:
                    c_lower = str(c_name).lower()
                    if c_lower not in pks:
                        pks.append(c_lower)
                elif str(c_name).lower() == "id" and isinstance(c_meta, dict):
                    if (
                        c_meta.get("is_primary") is False
                        or c_meta.get("primary_key") is False
                    ):
                        id_explicitly_non_pk = True
        elif isinstance(cols, list):
            for c in cols:
                is_pk = (
                    (c.get("is_primary") or c.get("primary_key"))
                    if isinstance(c, dict)
                    else (
                        getattr(c, "is_primary", False)
                        or getattr(c, "primary_key", False)
                    )
                )
                c_name = (
                    c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
                )
                if is_pk and c_name:
                    c_lower = str(c_name).lower()
                    if c_lower not in pks:
                        pks.append(c_lower)
                elif c_name and str(c_name).lower() == "id" and isinstance(c, dict):
                    if c.get("is_primary") is False or c.get("primary_key") is False:
                        id_explicitly_non_pk = True
        if not pks and not id_explicitly_non_pk:
            pks.append("id")
        pk_by_table[clean_t] = pks

    return pk_by_table


def _resolve_tbl(
    raw_prefix: str | None, clean_primary: str, alias_map: dict[str, str]
) -> str:
    if not raw_prefix:
        return clean_primary
    cleaned = str(raw_prefix).split(".")[-1]
    return alias_map.get(cleaned, cleaned)


def _covered_pk_cols(
    tbl: str, active_cols: set[str], pk_by_table: dict[str, list[str]]
) -> set[str]:
    pks = pk_by_table.get(tbl.lower(), ["id"])
    covered: set[str] = set()
    for pk_col in pks:
        if pk_col in active_cols:
            covered.add(pk_col)
        else:
            break
    return covered


def _recommend_for_filters(
    filters: list[Any],
    clean_primary: str,
    alias_map: dict[str, str],
    pk_by_table: dict[str, list[str]],
    seen_indexes: set[tuple[str, tuple[str, ...]]],
    recommendations: list[dict[str, Any]],
) -> dict[str, set[str]]:
    parsed_filters: list[tuple[str, str, str]] = []
    filter_cols_by_table: dict[str, set[str]] = {}

    for f in filters:
        if hasattr(f, "to_dict"):
            f_dict = f.to_dict()
        elif isinstance(f, dict):
            f_dict = dict(f)
        elif isinstance(f, (list, tuple)) and len(f) >= 2:
            f_dict = {"column": f[0], "op": f[1]}
        else:
            continue
        raw_col = str(f_dict.get("column", "") or "")
        op = str(f_dict.get("op") or f_dict.get("operator") or "")
        if not raw_col or raw_col == "*" or op == "RAW":
            continue

        col_parts = raw_col.split(".")
        col = col_parts[-1]
        prefix = (
            f_dict.get("table_prefix")
            or f_dict.get("tablePrefix")
            or f_dict.get("table")
            or (col_parts[-2] if len(col_parts) > 1 else None)
        )
        target_table = _resolve_tbl(prefix, clean_primary, alias_map)
        parsed_filters.append((target_table, col, op))
        filter_cols_by_table.setdefault(target_table.lower(), set()).add(col.lower())

    for target_table, col, op in parsed_filters:
        covered_pks = _covered_pk_cols(
            target_table,
            filter_cols_by_table.get(target_table.lower(), set()),
            pk_by_table,
        )
        dedup_key = (target_table.lower(), (col.lower(),))
        if col.lower() not in covered_pks and dedup_key not in seen_indexes:
            seen_indexes.add(dedup_key)
            idx_name = f"idx_{target_table}_{col.lower()}"
            recommendations.append(
                {
                    "id": f"idx_rec_{target_table}_{col}",
                    "table": target_table,
                    "columns": [col],
                    "index_name": idx_name,
                    "ddl": f"CREATE INDEX {idx_name} ON {target_table} ({col});",
                    "rationale": f"Accelerates filter condition ({col} {op} ...) from sequential table scan to B-Tree index scan.",
                    "estimated_impact": "high",
                }
            )

    return filter_cols_by_table


def _recommend_for_joins(
    joins: list[Any],
    primary_table: str,
    clean_primary: str,
    alias_map: dict[str, str],
    pk_by_table: dict[str, list[str]],
    filter_cols_by_table: dict[str, set[str]],
    seen_indexes: set[tuple[str, tuple[str, ...]]],
    recommendations: list[dict[str, Any]],
) -> None:
    for j in joins:
        j_dict = (
            j.to_dict()
            if hasattr(j, "to_dict")
            else (dict(j) if isinstance(j, dict) else {})
        )
        on_pair = j_dict.get("on")
        raw_right_col = (
            j_dict.get("right_col")
            or j_dict.get("rightCol")
            or (
                on_pair[1]
                if isinstance(on_pair, (list, tuple)) and len(on_pair) >= 2
                else None
            )
        )
        j_table = _resolve_tbl(j_dict.get("table", ""), clean_primary, alias_map)
        if raw_right_col and j_table:
            right_col = str(raw_right_col).split(".")[-1]
            active_join_cols = {right_col.lower()} | filter_cols_by_table.get(
                j_table.lower(), set()
            )
            covered_join_pks = _covered_pk_cols(j_table, active_join_cols, pk_by_table)
            dedup_key = (j_table.lower(), (right_col.lower(),))
            if (
                right_col.lower() not in covered_join_pks
                and dedup_key not in seen_indexes
            ):
                seen_indexes.add(dedup_key)
                idx_name = f"idx_{j_table}_{right_col.lower()}"
                recommendations.append(
                    {
                        "id": f"idx_join_{j_table}_{right_col}",
                        "table": j_table,
                        "columns": [right_col],
                        "index_name": idx_name,
                        "ddl": f"CREATE INDEX {idx_name} ON {j_table} ({right_col});",
                        "rationale": f"Improves JOIN performance on foreign key between {primary_table} and {j_table}.",
                        "estimated_impact": "high",
                    }
                )


def _recommend_composite(
    filters: list[Any],
    order_by: list[Any],
    clean_primary: str,
    alias_map: dict[str, str],
    seen_indexes: set[tuple[str, tuple[str, ...]]],
    recommendations: list[dict[str, Any]],
) -> None:
    if not filters or not order_by:
        return

    first_f = filters[0]
    f0 = (
        first_f.to_dict()
        if hasattr(first_f, "to_dict")
        else (
            dict(first_f)
            if isinstance(first_f, dict)
            else (
                {"column": first_f[0], "op": first_f[1]}
                if isinstance(first_f, (list, tuple)) and len(first_f) >= 2
                else {}
            )
        )
    )
    first_o = order_by[0]
    if hasattr(first_o, "to_dict"):
        o0 = first_o.to_dict()
    elif isinstance(first_o, dict):
        o0 = dict(first_o)
    elif isinstance(first_o, str):
        o0 = {"column": first_o.strip().split()[0]}
    else:
        o0 = {}
    raw_f_col = str(f0.get("column", "") or "")
    f_parts = raw_f_col.split(".")
    f_col = f_parts[-1]
    f_prefix = (
        f0.get("table_prefix")
        or f0.get("tablePrefix")
        or f0.get("table")
        or (f_parts[-2] if len(f_parts) > 1 else None)
    )
    f_table = _resolve_tbl(f_prefix, clean_primary, alias_map)

    raw_o_col = str(o0.get("column", "") or "")
    o_parts = raw_o_col.split(".")
    o_col = o_parts[-1]
    o_prefix = (
        o0.get("table_prefix")
        or o0.get("tablePrefix")
        or o0.get("table")
        or (o_parts[-2] if len(o_parts) > 1 else None)
    )
    o_table = _resolve_tbl(o_prefix, clean_primary, alias_map)

    if (
        f_col
        and o_col
        and f_col != o_col
        and f0.get("op") != "RAW"
        and f_table.lower() == o_table.lower()
    ):
        comp_key: tuple[str, tuple[str, ...]] = (
            f_table.lower(),
            (f_col.lower(), o_col.lower()),
        )
        if comp_key not in seen_indexes:
            seen_indexes.add(comp_key)
            idx_name = f"idx_{f_table}_comp_{f_col.lower()}_{o_col.lower()}"
            recommendations.append(
                {
                    "id": f"idx_comp_{f_table}_{f_col}_{o_col}",
                    "table": f_table,
                    "columns": [f_col, o_col],
                    "index_name": idx_name,
                    "ddl": f"CREATE INDEX {idx_name} ON {f_table} ({f_col}, {o_col});",
                    "rationale": f"Composite index satisfies both WHERE {f_col} and ORDER BY {o_col} avoiding file-sort.",
                    "estimated_impact": "medium",
                }
            )


def recommend_indexes(
    spec: QuerySpec | dict[str, Any],
    schema_snapshot: SchemaSnapshot | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Recommends database indexes based on QuerySpec filters, joins, and order_by."""
    spec_dict = spec.to_dict() if hasattr(spec, "to_dict") else dict(spec)
    primary_table = spec_dict.get("table", "")
    if not primary_table or not isinstance(primary_table, str):
        return []

    clean_primary = primary_table.split(".")[-1]
    alias_map = _build_alias_map(spec_dict, clean_primary)
    pk_by_table = _extract_primary_keys(schema_snapshot)

    recommendations: list[dict[str, Any]] = []
    seen_indexes: set[tuple[str, tuple[str, ...]]] = set()

    # 1. Filters
    filters = spec_dict.get("filters", [])
    filter_cols_by_table = _recommend_for_filters(
        filters,
        clean_primary,
        alias_map,
        pk_by_table,
        seen_indexes,
        recommendations,
    )

    # 2. Joins
    joins = spec_dict.get("joins", [])
    _recommend_for_joins(
        joins,
        primary_table,
        clean_primary,
        alias_map,
        pk_by_table,
        filter_cols_by_table,
        seen_indexes,
        recommendations,
    )

    # 3. Composite index on (first_filter, first_order_by)
    order_by = spec_dict.get("order_by", [])
    _recommend_composite(
        filters,
        order_by,
        clean_primary,
        alias_map,
        seen_indexes,
        recommendations,
    )

    return recommendations


def analyze_query_performance(
    spec: QuerySpec | dict[str, Any],
    sql: str,
    dialect: str = "postgres",
    table_stats: dict[str, dict[str, Any]] | None = None,
    schema_snapshot: Any = None,
) -> list[dict[str, Any]]:
    """Analyzes query and produces complete performance and cloud cost insights."""
    spec_dict = spec.to_dict() if hasattr(spec, "to_dict") else dict(spec)
    insights: list[dict[str, Any]] = []

    # 1. Cost estimate
    cost = estimate_cloud_cost(sql, dialect, table_stats)
    insights.append(
        {
            "type": "cost",
            "severity": "warning" if cost["dollar_cost_estimated"] > 0.05 else "info",
            "title": f"Estimated Cost: ${cost['dollar_cost_estimated']:.4f}",
            "message": f"Estimated scan volume: ~{cost['bytes_scanned_estimated'] / (1024 * 1024):.1f} MB using {cost['pricing_tier']}.",
            "cost_estimate": cost,
        }
    )

    # 2. Unbounded Scan Warning
    cols = spec_dict.get("columns", [])
    has_wildcard = "*" in cols or bool(re.search(r"select\s+\*", sql, re.IGNORECASE))
    limit = spec_dict.get("limit")
    has_no_limit = (
        limit is None
        or limit <= 0
        or not bool(re.search(r"\blimit\s+\d+", sql, re.IGNORECASE))
    )

    if has_wildcard and has_no_limit:
        insights.append(
            {
                "type": "warning",
                "severity": "warning",
                "title": "Unbounded Table Scan Detected",
                "message": "Query selects all columns ('SELECT *') without an explicit LIMIT clause. Adding a LIMIT or projecting specific columns saves I/O.",
            }
        )

    # 3. Missing Filter Warning
    filters = spec_dict.get("filters", [])
    if not filters:
        insights.append(
            {
                "type": "optimization",
                "severity": "info",
                "title": "Full Table Scan",
                "message": f"Query on table '{spec_dict.get('table')}' has no WHERE filter predicates.",
            }
        )

    # 4. Index recommendations
    recs = recommend_indexes(spec, schema_snapshot=schema_snapshot)
    for rec in recs:
        insights.append(
            {
                "type": "index",
                "severity": "warning" if rec["estimated_impact"] == "high" else "info",
                "title": f"Recommended Index: {rec['index_name']}",
                "message": rec["rationale"],
                "recommendation": rec,
            }
        )

    return insights
