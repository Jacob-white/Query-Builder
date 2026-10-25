"""
Universal Query Plan Explain and Optimization Advisory Engine.
==============================================================
Normalizes vendor-specific EXPLAIN outputs (PostgreSQL, SQLite, MySQL)
into unified QueryPlanNode trees with cost percentage calculation and
automated performance/indexing bottleneck recommendations.
Zero required external dependencies.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from query_builder.models import QuerySpec


@dataclass
class QueryPlanNode:
    """Standardized node in a query execution plan hierarchy."""

    node_type: str  # e.g., "Seq Scan", "Index Scan", "Hash Join", "Sort", "KNN Scan"
    table: str | None = None
    cost_estimate: float = 0.0
    actual_time_ms: float | None = None
    rows_estimated: int = 0
    rows_actual: int | None = None
    filter_predicate: str | None = None
    index_name: str | None = None
    cost_percentage: float = 0.0
    warnings: list[str] = field(default_factory=list)
    children: list[QueryPlanNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "table": self.table,
            "cost_estimate": self.cost_estimate,
            "actual_time_ms": self.actual_time_ms,
            "rows_estimated": self.rows_estimated,
            "rows_actual": self.rows_actual,
            "filter_predicate": self.filter_predicate,
            "index_name": self.index_name,
            "cost_percentage": round(self.cost_percentage, 2),
            "warnings": list(self.warnings),
            "children": [c.to_dict() for c in self.children],
        }


def _analyze_and_tag_warnings(node: QueryPlanNode, total_cost: float) -> None:
    """Recursively computes cost percentages and adds optimization warnings."""
    if total_cost > 0:
        node.cost_percentage = round((node.cost_estimate / total_cost) * 100.0, 2)
    else:
        node.cost_percentage = 0.0

    # Rule 1: High-cost sequential scan
    if "Seq Scan" in node.node_type and node.rows_estimated > 1000:
        node.warnings.append(
            f"Sequential table scan on '{node.table or 'table'}' with {node.rows_estimated:,} estimated rows. "
            f"Consider adding an index on relevant filter columns."
        )

    # Rule 2: Unindexed vector search scan
    if "KNN" in node.node_type and not node.index_name:
        node.warnings.append(
            f"Exact flat vector KNN scan on '{node.table or 'table'}'. "
            f"Create an HNSW or IVFFlat vector index to accelerate nearest neighbor retrieval."
        )

    # Rule 3: High cost node bottleneck
    if node.cost_percentage >= 40.0 and len(node.children) > 0:
        node.warnings.append(
            f"High resource bottleneck: operation consumes {node.cost_percentage}% of total query execution cost."
        )

    for child in node.children:
        _analyze_and_tag_warnings(child, total_cost)


def parse_postgres_plan(plan_dict: dict[str, Any]) -> QueryPlanNode:
    """Parses a PostgreSQL EXPLAIN (FORMAT JSON) plan dictionary."""
    plan = plan_dict.get("Plan", plan_dict)

    node_type = plan.get("Node Type", "Execution Node")
    table = plan.get("Relation Name")
    cost_estimate = float(plan.get("Total Cost", 0.0))
    actual_time = (
        float(plan.get("Actual Total Time", 0.0))
        if "Actual Total Time" in plan
        else None
    )
    rows_est = int(plan.get("Plan Rows", 0))
    rows_act = int(plan.get("Actual Rows", 0)) if "Actual Rows" in plan else None
    filter_pred = plan.get("Filter") or plan.get("Index Cond")
    index_name = plan.get("Index Name")

    children: list[QueryPlanNode] = []
    for subplan in plan.get("Plans", []):
        children.append(parse_postgres_plan(subplan))

    node = QueryPlanNode(
        node_type=node_type,
        table=table,
        cost_estimate=cost_estimate,
        actual_time_ms=actual_time,
        rows_estimated=rows_est,
        rows_actual=rows_act,
        filter_predicate=filter_pred,
        index_name=index_name,
        children=children,
    )
    return node


_MYSQL_INNER_KEYS = (
    "table",
    "nested_loop",
    "union_result",
    "duplicates_removal",
    "grouping_operation",
    "ordering_operation",
    "buffer_result",
)


def _parse_mysql_table_block(table_block: dict[str, Any]) -> QueryPlanNode:
    """Parses a MySQL EXPLAIN FORMAT=JSON table block."""
    table_name = table_block.get("table_name")
    access_type = str(table_block.get("access_type", "ALL")).upper()
    key = table_block.get("key")
    rows_est = int(
        table_block.get(
            "rows_examined_per_scan",
            table_block.get("rows_produced_per_join", table_block.get("rows", 0)),
        )
        or 0
    )
    cost_info = table_block.get("cost_info", {})
    raw_cost = (
        cost_info.get("read_cost")
        or cost_info.get("eval_cost")
        or cost_info.get("prefix_cost")
        or table_block.get("cost", 0.0)
    )
    try:
        cost_estimate = float(raw_cost)
    except (TypeError, ValueError):
        cost_estimate = float(max(rows_est, 1))
    if cost_estimate <= 0.0:
        cost_estimate = float(max(rows_est, 10))

    if access_type in ("ALL", "INDEX_MERGE") and not key:
        node_type = "Seq Scan"
    else:
        node_type = "Index Scan"

    children: list[QueryPlanNode] = []
    mat_sub = table_block.get("materialized_from_subquery")
    if isinstance(mat_sub, dict):
        children.append(parse_mysql_plan(mat_sub))

    attached_cond = table_block.get("attached_condition") or table_block.get("Extra")
    return QueryPlanNode(
        node_type=node_type,
        table=str(table_name) if table_name else None,
        cost_estimate=cost_estimate,
        rows_estimated=rows_est,
        filter_predicate=str(attached_cond) if attached_cond else None,
        index_name=str(key) if key else None,
        children=children,
    )


def _resolve_mysql_op_child(
    op_dict: dict[str, Any], current: QueryPlanNode | None
) -> QueryPlanNode:
    """Resolves the inner child plan node for a MySQL operation block."""
    if any(k in op_dict for k in _MYSQL_INNER_KEYS):
        return parse_mysql_plan({"query_block": op_dict})
    if current is not None:
        return current
    return QueryPlanNode(
        node_type="Execution Plan", cost_estimate=100.0, rows_estimated=50
    )


def parse_mysql_plan(raw_plan: dict[str, Any] | list[Any] | str) -> QueryPlanNode:
    """Parses MySQL EXPLAIN FORMAT=JSON or tabular EXPLAIN rows into a QueryPlanNode tree."""
    if isinstance(raw_plan, str):
        try:
            parsed = json.loads(raw_plan)
            if isinstance(parsed, (dict, list)):
                return parse_mysql_plan(parsed)
        except ValueError:
            pass
        return QueryPlanNode(
            node_type="Seq Scan",
            cost_estimate=100.0,
            rows_estimated=100,
            filter_predicate=raw_plan,
        )

    if isinstance(raw_plan, list):
        children: list[QueryPlanNode] = []
        total_cost = 0.0
        total_rows = 0
        for row in raw_plan:
            if not isinstance(row, dict):
                continue
            if "query_block" in row:
                return parse_mysql_plan(row)
            table_name = row.get("table") or row.get("table_name")
            access_type = str(
                row.get("type") or row.get("access_type") or "ALL"
            ).upper()
            key = row.get("key")
            rows_est = int(row.get("rows") or 0)
            extra = row.get("Extra") or row.get("filtered")
            node_type = (
                "Index Scan"
                if (key or access_type in ("REF", "EQ_REF", "RANGE", "CONST", "INDEX"))
                else "Seq Scan"
            )
            node_cost = float(max(rows_est, 10))
            total_cost += node_cost
            total_rows = max(total_rows, rows_est)
            children.append(
                QueryPlanNode(
                    node_type=node_type,
                    table=str(table_name) if table_name else None,
                    cost_estimate=node_cost,
                    rows_estimated=rows_est,
                    filter_predicate=str(extra) if extra else None,
                    index_name=str(key) if key else None,
                )
            )
        if len(children) == 1:
            return children[0]
        return QueryPlanNode(
            node_type="Nested Loop" if len(children) > 1 else "Execution Plan",
            cost_estimate=total_cost or 100.0,
            rows_estimated=total_rows or 50,
            children=children,
        )

    qb = raw_plan.get("query_block", raw_plan)
    if not isinstance(qb, dict):
        return QueryPlanNode(
            node_type="Execution Plan", cost_estimate=100.0, rows_estimated=50
        )

    cost_info = qb.get("cost_info", {})
    try:
        query_cost = float(cost_info.get("query_cost", 0.0))
    except (TypeError, ValueError):
        query_cost = 0.0

    current: QueryPlanNode | None = None
    union_res = qb.get("union_result")
    if isinstance(union_res, dict):
        specs = union_res.get("query_specifications", [])
        union_children = [
            parse_mysql_plan(s.get("query_block", s))
            for s in specs
            if isinstance(s, dict)
        ]
        sum_union_cost = sum(c.cost_estimate for c in union_children)
        sum_union_rows = sum(c.rows_estimated for c in union_children)
        current = QueryPlanNode(
            node_type="Union",
            table=str(union_res["table_name"]) if union_res.get("table_name") else None,
            cost_estimate=query_cost or sum_union_cost or 100.0,
            rows_estimated=sum_union_rows or 50,
            children=union_children,
        )

    if "table" in qb and isinstance(qb["table"], dict):
        current = _parse_mysql_table_block(qb["table"])

    nested_loop = qb.get("nested_loop")
    if isinstance(nested_loop, list) and nested_loop:
        loop_children: list[QueryPlanNode] = []
        for item in nested_loop:
            if (
                isinstance(item, dict)
                and "table" in item
                and isinstance(item["table"], dict)
            ):
                loop_children.append(_parse_mysql_table_block(item["table"]))
            elif isinstance(item, dict):
                loop_children.append(_parse_mysql_table_block(item))
        if len(loop_children) == 1:
            current = loop_children[0]
        elif loop_children:
            sum_cost = sum(c.cost_estimate for c in loop_children)
            current = QueryPlanNode(
                node_type="Nested Loop",
                cost_estimate=query_cost or sum_cost or 100.0,
                rows_estimated=max(
                    (c.rows_estimated for c in loop_children), default=50
                ),
                children=loop_children,
            )

    buffer_op = qb.get("buffer_result")
    if isinstance(buffer_op, dict):
        inner = _resolve_mysql_op_child(buffer_op, current)
        current = QueryPlanNode(
            node_type="Buffer Result",
            cost_estimate=query_cost or (inner.cost_estimate + 10.0),
            rows_estimated=inner.rows_estimated,
            children=[inner],
        )

    dup_op = qb.get("duplicates_removal")
    if isinstance(dup_op, dict):
        inner = _resolve_mysql_op_child(dup_op, current)
        current = QueryPlanNode(
            node_type="Unique",
            cost_estimate=query_cost or (inner.cost_estimate + 15.0),
            rows_estimated=inner.rows_estimated,
            children=[inner],
        )

    grouping_op = qb.get("grouping_operation")
    if isinstance(grouping_op, dict):
        inner = _resolve_mysql_op_child(grouping_op, current)
        current = QueryPlanNode(
            node_type="Group Aggregate",
            cost_estimate=query_cost or (inner.cost_estimate + 20.0),
            rows_estimated=inner.rows_estimated,
            children=[inner],
        )

    ordering_op = qb.get("ordering_operation")
    if isinstance(ordering_op, dict):
        inner = _resolve_mysql_op_child(ordering_op, current)
        current = QueryPlanNode(
            node_type="Sort",
            cost_estimate=query_cost or (inner.cost_estimate + 15.0),
            rows_estimated=inner.rows_estimated,
            children=[inner],
        )

    if current is None:
        current = QueryPlanNode(
            node_type="Execution Plan",
            cost_estimate=query_cost or 100.0,
            rows_estimated=50,
        )

    return current


def parse_sqlite_plan(raw_plan: list[Any] | dict[str, Any] | str) -> QueryPlanNode:
    """Parses SQLite EXPLAIN QUERY PLAN rows or strings into a QueryPlanNode tree."""
    lines: list[str] = []
    if isinstance(raw_plan, str):
        lines = [ln.strip() for ln in raw_plan.splitlines() if ln.strip()]
    elif isinstance(raw_plan, dict):
        detail = (
            raw_plan.get("detail") or raw_plan.get("notext") or raw_plan.get("plan")
        )
        if detail:
            lines = [str(detail)]
    elif isinstance(raw_plan, list):
        for item in raw_plan:
            if isinstance(item, dict):
                detail = item.get("detail") or item.get("notext") or item.get("plan")
                if detail:
                    lines.append(str(detail))
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                lines.append(str(item[3]))
            elif isinstance(item, str):
                lines.append(item)

    scan_nodes: list[QueryPlanNode] = []
    has_temp_sort = False
    has_temp_group = False

    for detail in lines:
        upper = detail.upper()
        if "USE TEMP B-TREE FOR ORDER BY" in upper:
            has_temp_sort = True
            continue
        if "USE TEMP B-TREE FOR GROUP BY" in upper:
            has_temp_group = True
            continue

        table_name: str | None = None
        index_name: str | None = None
        tokens = detail.split()
        for idx, tok in enumerate(tokens):
            if tok.upper() in ("TABLE", "SCAN", "SEARCH") and idx + 1 < len(tokens):
                candidate = tokens[idx + 1]
                if candidate.upper() != "TABLE":
                    table_name = candidate
                elif idx + 2 < len(tokens):
                    table_name = tokens[idx + 2]
                break
        if (
            "USING INDEX" in upper
            or "USING COVERING INDEX" in upper
            or "PRIMARY KEY" in upper
        ):
            node_type = "Index Scan"
            for idx, tok in enumerate(tokens):
                if tok.upper() == "INDEX" and idx + 1 < len(tokens):
                    index_name = tokens[idx + 1]
                    break
            if index_name is None and "PRIMARY KEY" in upper:
                index_name = "sqlite_autoindex_pk"
            scan_nodes.append(
                QueryPlanNode(
                    node_type=node_type,
                    table=table_name,
                    cost_estimate=25.0,
                    rows_estimated=100,
                    filter_predicate=detail,
                    index_name=index_name,
                )
            )
        else:
            scan_nodes.append(
                QueryPlanNode(
                    node_type="Seq Scan",
                    table=table_name,
                    cost_estimate=120.0,
                    rows_estimated=2000,
                    filter_predicate=detail,
                )
            )

    if not scan_nodes:
        return QueryPlanNode(
            node_type="Execution Plan",
            cost_estimate=100.0,
            rows_estimated=50,
            children=[
                QueryPlanNode(
                    node_type="Sqlite Driver Scan",
                    cost_estimate=100.0,
                    rows_estimated=50,
                )
            ],
        )

    if len(scan_nodes) == 1:
        root = scan_nodes[0]
    else:
        root = QueryPlanNode(
            node_type="Nested Loop",
            cost_estimate=sum(n.cost_estimate for n in scan_nodes),
            rows_estimated=max(n.rows_estimated for n in scan_nodes),
            children=scan_nodes,
        )

    if has_temp_group:
        root = QueryPlanNode(
            node_type="Group Aggregate",
            cost_estimate=root.cost_estimate + 30.0,
            rows_estimated=root.rows_estimated,
            filter_predicate="USE TEMP B-TREE FOR GROUP BY",
            children=[root],
        )
    if has_temp_sort:
        root = QueryPlanNode(
            node_type="Sort",
            cost_estimate=root.cost_estimate + 20.0,
            rows_estimated=root.rows_estimated,
            filter_predicate="USE TEMP B-TREE FOR ORDER BY",
            children=[root],
        )

    return root


def _extract_table_primary_keys(
    schema: dict[str, Any] | None, table_name: str
) -> list[str]:
    """Extracts ordered primary key column names for a given table from a schema snapshot."""
    if not schema or not isinstance(schema, dict):
        return []
    tables = schema.get("tables", schema)
    if not isinstance(tables, dict):
        return []
    table_meta = tables.get(table_name)
    if not isinstance(table_meta, dict):
        return []
    pks: list[str] = []
    explicit_pks = table_meta.get("primary_keys")
    if isinstance(explicit_pks, (list, tuple)):
        for pk in explicit_pks:
            if pk and str(pk) not in pks:
                pks.append(str(pk))
    columns = table_meta.get("columns", {})
    if isinstance(columns, dict):
        for col_name, col_meta in columns.items():
            if isinstance(col_meta, dict) and (
                col_meta.get("primary_key") or col_meta.get("is_primary")
            ):
                if str(col_name) not in pks:
                    pks.append(str(col_name))
    elif isinstance(columns, list):
        for col_meta in columns:
            if (
                isinstance(col_meta, dict)
                and (col_meta.get("primary_key") or col_meta.get("is_primary"))
                and col_meta.get("name")
            ):
                col_str = str(col_meta["name"])
                if col_str not in pks:
                    pks.append(col_str)
    return pks


def _match_pk_prefix(table_pks: list[str], candidate_cols: set[str]) -> str | None:
    """Returns matched PK suffix when candidate_cols covers at least the leading PK column."""
    if not table_pks or table_pks[0] not in candidate_cols:
        return None
    matched: list[str] = []
    for pk_col in table_pks:
        if pk_col in candidate_cols:
            matched.append(pk_col)
        else:
            break
    return "_".join(matched) if matched else None


def estimate_plan_from_spec(
    spec: dict[str, Any] | QuerySpec,
    schema: dict[str, Any] | None = None,
) -> QueryPlanNode:
    """Generates an estimated QueryPlanNode hierarchy from a QuerySpec without DB execution."""
    if isinstance(spec, QuerySpec) or hasattr(spec, "__dataclass_fields__"):
        spec_dict: dict[str, Any] = asdict(spec)  # type: ignore[arg-type]  # narrowed to a dataclass by the __dataclass_fields__ check
    elif isinstance(spec, dict):
        spec_dict = dict(spec)
    else:
        spec_dict = {}

    table_name = spec_dict.get("table", "unknown_table")
    raw_limit = spec_dict.get("limit")
    limit = int(raw_limit) if raw_limit is not None else 50
    filters = spec_dict.get("filters", [])
    joins = spec_dict.get("joins", [])
    vector_search = spec_dict.get("vector_search")
    hybrid_search = spec_dict.get("hybrid_search")

    # Base scan node
    base_rows = 10000
    base_cost = 150.0
    table_pks = _extract_table_primary_keys(schema, str(table_name))

    if hybrid_search:
        h_dict = (
            hybrid_search if isinstance(hybrid_search, dict) else asdict(hybrid_search)
        )
        vec_col = h_dict.get("vector_column", "embedding")
        text_cols = h_dict.get("text_columns", ["content"])
        knn_child = QueryPlanNode(
            node_type="Vector KNN Scan",
            table=table_name,
            cost_estimate=180.0,
            rows_estimated=100,
            filter_predicate=f"cosine_similarity({vec_col})",
        )
        text_child = QueryPlanNode(
            node_type="Full-Text Scan",
            table=table_name,
            cost_estimate=140.0,
            rows_estimated=200,
            filter_predicate=f"to_tsvector({', '.join(text_cols)})",
        )
        scan_node = QueryPlanNode(
            node_type="Hybrid Search Merge",
            table=table_name,
            cost_estimate=320.0,
            rows_estimated=min(limit, 100),
            children=[knn_child, text_child],
        )
    elif vector_search:
        v_dict = (
            vector_search if isinstance(vector_search, dict) else asdict(vector_search)
        )
        scan_node = QueryPlanNode(
            node_type="KNN Scan",
            table=table_name,
            cost_estimate=280.0,
            rows_estimated=min(limit, 100),
            filter_predicate=f"cosine_similarity({v_dict.get('column', 'embedding')})",
        )
    elif filters:
        filter_exprs = []
        filter_cols: set[str] = set()
        for f in filters:
            if isinstance(f, (list, tuple)) and len(f) >= 3:
                raw_col_str = str(f[0])
                filter_exprs.append(f"{f[0]} {f[1]} {f[2]}")
                if "." in raw_col_str:
                    prefix, col_raw = raw_col_str.split(".", 1)
                    if prefix == str(table_name):
                        filter_cols.add(col_raw)
                elif raw_col_str:
                    filter_cols.add(raw_col_str)
            elif isinstance(f, dict):
                raw_col_str = str(f.get("column") or "")
                f_table = f.get("table") or f.get("tablePrefix")
                f_op = f.get("op") or f.get("operator") or "="
                filter_exprs.append(f"{f.get('column')} {f_op} {f.get('value')}")
                if "." in raw_col_str:
                    prefix, col_raw = raw_col_str.split(".", 1)
                    if prefix == str(table_name):
                        filter_cols.add(col_raw)
                elif raw_col_str and (not f_table or str(f_table) == str(table_name)):
                    filter_cols.add(raw_col_str)
        matched_pk = _match_pk_prefix(table_pks, filter_cols)
        if matched_pk:
            scan_node = QueryPlanNode(
                node_type="Index Scan",
                table=table_name,
                cost_estimate=15.0,
                rows_estimated=10,
                filter_predicate=" AND ".join(filter_exprs) if filter_exprs else None,
                index_name=f"pk_{table_name}_{matched_pk}",
            )
        else:
            scan_node = QueryPlanNode(
                node_type="Seq Scan",
                table=table_name,
                cost_estimate=base_cost,
                rows_estimated=base_rows,
                filter_predicate=" AND ".join(filter_exprs) if filter_exprs else None,
            )
    else:
        scan_node = QueryPlanNode(
            node_type="Seq Scan",
            table=table_name,
            cost_estimate=base_cost,
            rows_estimated=base_rows,
        )

    current_node = scan_node

    # Joins
    for j in joins:
        j_dict = j if isinstance(j, dict) else getattr(j, "__dict__", {})
        j_table = j_dict.get("table", "joined_table")
        j_type = str(j_dict.get("type", "LEFT")).upper()
        j_on = j_dict.get("on", [])
        j_pks = _extract_table_primary_keys(schema, str(j_table))
        candidate_cols: list[Any] = []
        if isinstance(j_on, (list, tuple)):
            candidate_cols.extend(j_on)
        raw_rc = j_dict.get("right_col") or j_dict.get("rightCol")
        if raw_rc:
            candidate_cols.append(raw_rc)
        join_cols: set[str] = set()
        for side in candidate_cols:
            side_str = str(side)
            if "." in side_str:
                prefix, col_part = side_str.split(".", 1)
                if prefix == str(j_table):
                    join_cols.add(col_part)
            elif side_str:
                join_cols.add(side_str)
        join_pk_match = _match_pk_prefix(j_pks, join_cols)
        if join_pk_match:
            join_child = QueryPlanNode(
                node_type="Index Scan",
                table=j_table,
                cost_estimate=20.0,
                rows_estimated=100,
                index_name=f"pk_{j_table}_{join_pk_match}",
            )
            join_cost = current_node.cost_estimate + 35.0
        else:
            join_child = QueryPlanNode(
                node_type="Seq Scan",
                table=j_table,
                cost_estimate=80.0,
                rows_estimated=5000,
            )
            join_cost = current_node.cost_estimate + 120.0
        current_node = QueryPlanNode(
            node_type=f"{j_type} Join",
            cost_estimate=join_cost,
            rows_estimated=current_node.rows_estimated,
            children=[current_node, join_child],
        )

    # Sort & Limit top node
    top_cost = current_node.cost_estimate + 25.0
    root = QueryPlanNode(
        node_type="Limit",
        cost_estimate=top_cost,
        rows_estimated=limit,
        children=[
            QueryPlanNode(
                node_type="Sort",
                cost_estimate=top_cost - 5.0,
                rows_estimated=current_node.rows_estimated,
                children=[current_node],
            )
        ],
    )

    _analyze_and_tag_warnings(root, root.cost_estimate)
    return root


def normalize_explain_output(
    raw_output: Any, dialect: str = "postgres"
) -> QueryPlanNode:
    """Normalizes raw DB explain output or dict into a standard QueryPlanNode."""
    d = dialect.lower().strip()

    if (
        isinstance(raw_output, list)
        and len(raw_output) == 1
        and isinstance(raw_output[0], dict)
    ):
        first_row = raw_output[0]
        if "QUERY PLAN" in first_row:
            raw_output = first_row["QUERY PLAN"]
        elif "EXPLAIN" in first_row:
            raw_output = first_row["EXPLAIN"]
    elif isinstance(raw_output, dict):
        if "QUERY PLAN" in raw_output:
            raw_output = raw_output["QUERY PLAN"]
        elif "EXPLAIN" in raw_output:
            raw_output = raw_output["EXPLAIN"]

    if isinstance(raw_output, str) and d in ("postgres", "postgresql"):
        try:
            raw_output = json.loads(raw_output)
        except ValueError:
            pass

    if (
        isinstance(raw_output, list)
        and len(raw_output) > 0
        and isinstance(raw_output[0], dict)
        and "Plan" in raw_output[0]
    ):
        root = parse_postgres_plan(raw_output[0])
        _analyze_and_tag_warnings(root, root.cost_estimate)
        return root
    if isinstance(raw_output, dict) and "Plan" in raw_output:
        root = parse_postgres_plan(raw_output)
        _analyze_and_tag_warnings(root, root.cost_estimate)
        return root

    # MySQL EXPLAIN FORMAT=JSON or tabular rows
    if isinstance(raw_output, dict) and "query_block" in raw_output:
        root = parse_mysql_plan(raw_output)
        _analyze_and_tag_warnings(root, root.cost_estimate)
        return root
    if d in ("mysql", "mariadb") and (
        isinstance(raw_output, (dict, str))
        or (
            isinstance(raw_output, list)
            and len(raw_output) > 0
            and isinstance(raw_output[0], dict)
            and (
                "query_block" in raw_output[0]
                or "access_type" in raw_output[0]
                or "select_type" in raw_output[0]
                or "Extra" in raw_output[0]
            )
        )
    ):
        root = parse_mysql_plan(raw_output)
        _analyze_and_tag_warnings(root, root.cost_estimate)
        return root

    # SQLite EXPLAIN QUERY PLAN structured rows or tuple output
    if d in ("sqlite_eqp", "sqlite_structured") or (
        d in ("sqlite", "sqlite3")
        and (
            (
                isinstance(raw_output, dict)
                and ("detail" in raw_output or "explain" in raw_output)
            )
            or (
                isinstance(raw_output, list)
                and len(raw_output) > 0
                and (
                    isinstance(raw_output[0], tuple)
                    or (
                        isinstance(raw_output[0], dict)
                        and ("detail" in raw_output[0] or "explain" in raw_output[0])
                        and "notused" not in raw_output[0]
                    )
                )
            )
        )
    ):
        root = parse_sqlite_plan(raw_output)
        _analyze_and_tag_warnings(root, root.cost_estimate)
        return root

    # Fallback generic node tree
    root = QueryPlanNode(
        node_type="Execution Plan",
        cost_estimate=100.0,
        rows_estimated=50,
        children=[
            QueryPlanNode(
                node_type=f"{d.capitalize()} Driver Scan",
                cost_estimate=100.0,
                rows_estimated=50,
            )
        ],
    )
    _analyze_and_tag_warnings(root, root.cost_estimate)
    return root
