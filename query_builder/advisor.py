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

    pk_by_table: dict[str, set[str]] = {}
    if schema_snapshot is not None:
        tables_meta = getattr(schema_snapshot, "tables", None) or (
            schema_snapshot.get("tables") if isinstance(schema_snapshot, dict) else None
        )
        if isinstance(tables_meta, dict):
            for t_name, t_meta in tables_meta.items():
                clean_t = str(t_name).split(".")[-1].lower()
                cols = (
                    t_meta.get("columns", [])
                    if isinstance(t_meta, dict)
                    else getattr(t_meta, "columns", [])
                )
                pks = {"id"}
                if isinstance(cols, list):
                    for c in cols:
                        is_pk = (
                            c.get("is_primary")
                            if isinstance(c, dict)
                            else getattr(c, "is_primary", False)
                        )
                        c_name = (
                            c.get("name")
                            if isinstance(c, dict)
                            else getattr(c, "name", None)
                        )
                        if is_pk and c_name:
                            pks.add(str(c_name).lower())
                pk_by_table[clean_t] = pks

    def _resolve_tbl(raw_prefix: str | None) -> str:
        if not raw_prefix:
            return clean_primary
        cleaned = str(raw_prefix).split(".")[-1]
        return alias_map.get(cleaned, cleaned)

    def _is_indexed_pk(tbl: str, col_name: str) -> bool:
        pks = pk_by_table.get(tbl.lower(), {"id"})
        return col_name.lower() in pks

    recommendations: list[dict[str, Any]] = []
    seen_indexes: set[tuple[str, tuple[str, ...]]] = set()

    # 1. Filters
    filters = spec_dict.get("filters", [])
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
        op = str(f_dict.get("op", "") or "")
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
        target_table = _resolve_tbl(prefix)
        dedup_key = (target_table.lower(), (col.lower(),))
        if not _is_indexed_pk(target_table, col) and dedup_key not in seen_indexes:
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

    # 2. Joins
    for j in joins:
        j_dict = (
            j.to_dict()
            if hasattr(j, "to_dict")
            else (dict(j) if isinstance(j, dict) else {})
        )
        raw_right_col = j_dict.get("right_col") or j_dict.get("rightCol")
        j_table = _resolve_tbl(j_dict.get("table", ""))
        if raw_right_col and j_table:
            right_col = str(raw_right_col).split(".")[-1]
            dedup_key = (j_table.lower(), (right_col.lower(),))
            if not _is_indexed_pk(j_table, right_col) and dedup_key not in seen_indexes:
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

    # 3. Composite index on (first_filter, first_order_by)
    order_by = spec_dict.get("order_by", [])
    if filters and order_by:
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
        f_col = (f0.get("column", "") or "").split(".")[-1]
        o_col = (o0.get("column", "") or "").split(".")[-1]
        if f_col and o_col and f_col != o_col and f0.get("op") != "RAW":
            comp_key: tuple[str, tuple[str, ...]] = (
                clean_primary.lower(),
                (f_col.lower(), o_col.lower()),
            )
            if comp_key not in seen_indexes:
                seen_indexes.add(comp_key)
                idx_name = f"idx_{clean_primary}_comp_{f_col.lower()}_{o_col.lower()}"
                recommendations.append(
                    {
                        "id": f"idx_comp_{clean_primary}_{f_col}_{o_col}",
                        "table": clean_primary,
                        "columns": [f_col, o_col],
                        "index_name": idx_name,
                        "ddl": f"CREATE INDEX {idx_name} ON {clean_primary} ({f_col}, {o_col});",
                        "rationale": f"Composite index satisfies both WHERE {f_col} and ORDER BY {o_col} avoiding file-sort.",
                        "estimated_impact": "medium",
                    }
                )

    return recommendations


def analyze_query_performance(
    spec: QuerySpec | dict[str, Any],
    sql: str,
    dialect: str = "postgres",
    table_stats: dict[str, dict[str, Any]] | None = None,
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
    recs = recommend_indexes(spec)
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
