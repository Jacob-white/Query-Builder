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
    if not primary_table:
        return []

    recommendations: list[dict[str, Any]] = []
    existing_indexes = {"id"}

    # 1. Filters
    filters = spec_dict.get("filters", [])
    for f in filters:
        f_dict = f.to_dict() if hasattr(f, "to_dict") else dict(f)
        col = f_dict.get("column", "")
        op = f_dict.get("op", "")
        if not col or col == "*" or op == "RAW":
            continue

        target_table = f_dict.get("table_prefix") or primary_table
        if col.lower() not in existing_indexes:
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
    joins = spec_dict.get("joins", [])
    for j in joins:
        j_dict = j.to_dict() if hasattr(j, "to_dict") else dict(j)
        right_col = j_dict.get("right_col")
        j_table = j_dict.get("table", "")
        if right_col and right_col.lower() not in existing_indexes:
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
        f0 = (
            filters[0].to_dict() if hasattr(filters[0], "to_dict") else dict(filters[0])
        )
        o0 = (
            order_by[0].to_dict()
            if hasattr(order_by[0], "to_dict")
            else dict(order_by[0])
        )
        f_col = f0.get("column", "")
        o_col = o0.get("column", "")
        if f_col and o_col and f_col != o_col and f0.get("op") != "RAW":
            idx_name = f"idx_{primary_table}_comp_{f_col}_{o_col}"
            recommendations.append(
                {
                    "id": f"idx_comp_{primary_table}_{f_col}_{o_col}",
                    "table": primary_table,
                    "columns": [f_col, o_col],
                    "index_name": idx_name,
                    "ddl": f"CREATE INDEX {idx_name} ON {primary_table} ({f_col}, {o_col});",
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
