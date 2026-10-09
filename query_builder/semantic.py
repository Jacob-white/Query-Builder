"""
Semantic Metrics & Modeling Layer Protocol.
===========================================
Provides declarative definition, validation, and expansion for reusable business
metrics, calculated virtual dimensions, and temporal grain aggregations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SemanticError(Exception):
    """Base exception for semantic model validation and expansion errors."""


SUPPORTED_AGGREGATIONS: set[str] = {
    "sum",
    "avg",
    "average",
    "count",
    "count_distinct",
    "min",
    "max",
    "custom",
}

SUPPORTED_TIME_GRAINS: set[str] = {
    "second",
    "minute",
    "hour",
    "day",
    "week",
    "month",
    "quarter",
    "year",
}

SUPPORTED_FORMATS: set[str] = {
    "currency",
    "percentage",
    "number",
    "decimal",
    "integer",
    "duration",
    "raw",
}


@dataclass
class MetricFilter:
    """Predicate condition scoped to an individual metric calculation."""

    field: str
    operator: str  # eq, neq, gt, gte, lt, lte, in, not_in, is_null, is_not_null
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricFilter:
        field_name = data.get("field") or data.get("column") or ""
        op = data.get("operator") or data.get("op") or "eq"
        val = data.get("value")
        if not field_name:
            raise SemanticError("MetricFilter requires a 'field' or 'column' name.")
        return cls(field=str(field_name), operator=str(op).lower(), value=val)


@dataclass
class MetricDefinition:
    """Specification of a reusable business metric or measure."""

    name: str
    title: str
    sql_expression: str
    aggregation: str = "sum"
    description: str | None = None
    filters: list[MetricFilter] = field(default_factory=list)
    format: str = "number"
    table: str | None = None

    def __post_init__(self) -> None:
        self.aggregation = self.aggregation.lower()
        if self.aggregation not in SUPPORTED_AGGREGATIONS:
            raise SemanticError(
                f"Unsupported metric aggregation '{self.aggregation}'. "
                f"Supported: {sorted(SUPPORTED_AGGREGATIONS)}"
            )
        self.format = self.format.lower()
        if self.format not in SUPPORTED_FORMATS:
            self.format = "number"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "sql_expression": self.sql_expression,
            "aggregation": self.aggregation,
            "filters": [f.to_dict() for f in self.filters],
            "format": self.format,
            "table": self.table,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricDefinition:
        name = data.get("name")
        if not name:
            raise SemanticError("Metric definition requires a 'name'.")
        title = data.get("title") or name.replace("_", " ").title()
        sql_expr = (
            data.get("sql_expression") or data.get("sql") or data.get("expression")
        )
        if not sql_expr:
            raise SemanticError(
                f"Metric '{name}' requires an 'sql_expression' or 'sql'."
            )

        filters_data = data.get("filters", [])
        filters = [MetricFilter.from_dict(f) for f in filters_data]

        return cls(
            name=str(name),
            title=str(title),
            description=data.get("description"),
            sql_expression=str(sql_expr),
            aggregation=str(data.get("aggregation") or data.get("type") or "sum"),
            filters=filters,
            format=str(data.get("format") or "number"),
            table=data.get("table"),
        )


@dataclass
class DimensionDefinition:
    """Specification of a calculated or virtual dimension."""

    name: str
    title: str
    sql_expression: str
    data_type: str = "string"
    description: str | None = None
    time_grains: list[str] = field(default_factory=list)
    table: str | None = None

    def __post_init__(self) -> None:
        valid_grains: list[str] = []
        for g in self.time_grains:
            g_low = g.lower()
            if g_low in SUPPORTED_TIME_GRAINS:
                valid_grains.append(g_low)
        self.time_grains = valid_grains

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "sql_expression": self.sql_expression,
            "data_type": self.data_type,
            "time_grains": self.time_grains,
            "table": self.table,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DimensionDefinition:
        name = data.get("name")
        if not name:
            raise SemanticError("Dimension definition requires a 'name'.")
        title = data.get("title") or name.replace("_", " ").title()
        sql_expr = (
            data.get("sql_expression") or data.get("sql") or data.get("expression")
        )
        if not sql_expr:
            raise SemanticError(
                f"Dimension '{name}' requires an 'sql_expression' or 'sql'."
            )

        return cls(
            name=str(name),
            title=str(title),
            description=data.get("description"),
            sql_expression=str(sql_expr),
            data_type=str(data.get("data_type") or data.get("type") or "string"),
            time_grains=list(data.get("time_grains") or []),
            table=data.get("table"),
        )


@dataclass
class SemanticModel:
    """Representation of an entity or table in the semantic modeling layer."""

    name: str
    table_name: str
    description: str | None = None
    dimensions: list[DimensionDefinition] = field(default_factory=list)
    metrics: list[MetricDefinition] = field(default_factory=list)
    primary_key: str | None = None
    default_time_dimension: str | None = None

    def get_metric(self, name: str) -> MetricDefinition | None:
        for m in self.metrics:
            if m.name == name:
                return m
        return None

    def get_dimension(self, name: str) -> DimensionDefinition | None:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table_name": self.table_name,
            "description": self.description,
            "primary_key": self.primary_key,
            "default_time_dimension": self.default_time_dimension,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "metrics": [m.to_dict() for m in self.metrics],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticModel:
        name = data.get("name") or data.get("model")
        if not name:
            raise SemanticError("SemanticModel requires a 'name' or 'model'.")
        table_name = data.get("table_name") or data.get("table") or name

        dims: list[DimensionDefinition] = []
        for d_item in data.get("dimensions", []):
            if isinstance(d_item, dict):
                dims.append(DimensionDefinition.from_dict(d_item))

        metrics: list[MetricDefinition] = []
        for m_item in data.get("metrics", []):
            if isinstance(m_item, dict):
                metrics.append(MetricDefinition.from_dict(m_item))

        return cls(
            name=str(name),
            table_name=str(table_name),
            description=data.get("description"),
            dimensions=dims,
            metrics=metrics,
            primary_key=data.get("primary_key") or data.get("pk"),
            default_time_dimension=data.get("default_time_dimension"),
        )


class SemanticRegistry:
    """Registry maintaining active semantic models, metrics, and dimensions."""

    def __init__(self) -> None:
        self._models: dict[str, SemanticModel] = {}
        self._metrics_by_name: dict[str, MetricDefinition] = {}

    def register_model(self, model: SemanticModel) -> None:
        self._models[model.name] = model
        for metric in model.metrics:
            if not metric.table:
                metric.table = model.table_name
            self._metrics_by_name[metric.name] = metric

    def get_model(self, name: str) -> SemanticModel | None:
        return self._models.get(name)

    def get_metric(self, name: str) -> MetricDefinition | None:
        return self._metrics_by_name.get(name)

    def list_models(self) -> list[SemanticModel]:
        return list(self._models.values())

    def list_metrics(self) -> list[MetricDefinition]:
        return list(self._metrics_by_name.values())

    def clear(self) -> None:
        self._models.clear()
        self._metrics_by_name.clear()


_GLOBAL_REGISTRY = SemanticRegistry()


def get_global_semantic_registry() -> SemanticRegistry:
    return _GLOBAL_REGISTRY


def reset_global_semantic_registry() -> None:
    _GLOBAL_REGISTRY.clear()


def parse_simple_yaml_or_json(content: str) -> dict[str, Any]:
    """
    Parses JSON directly or handles common dbt/Cube-style YAML subset
    without requiring third-party PyYAML if absent.
    """
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SemanticError(f"Invalid JSON in semantic definition: {exc}") from exc

    # Try importing PyYAML or PySyck if available
    try:
        import yaml

        parsed = yaml.safe_load(content)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"models": parsed}
        return {}
    except (ImportError, Exception):  # noqa: S110
        pass

    # Lightweight regex/indent parser for clean basic YAML documents
    result: dict[str, Any] = {"models": []}
    lines = content.splitlines()
    current_model: dict[str, Any] | None = None
    current_section: str | None = None
    current_item: dict[str, Any] | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line or line.strip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        stripped_line = line.strip()

        if stripped_line.startswith("models:"):
            current_section = "models"
            continue

        if stripped_line.startswith("- name:") and (
            current_section == "models" or indent <= 2
        ):
            val = stripped_line.split(":", 1)[1].strip().strip('"').strip("'")
            current_model = {"name": val, "dimensions": [], "metrics": []}
            result["models"].append(current_model)
            current_item = current_model
            continue

        if current_model is not None:
            if stripped_line.startswith(("table:", "table_name:")):
                current_model["table_name"] = (
                    stripped_line.split(":", 1)[1].strip().strip('"').strip("'")
                )
            elif stripped_line.startswith("description:"):
                current_model["description"] = (
                    stripped_line.split(":", 1)[1].strip().strip('"').strip("'")
                )
            elif stripped_line.startswith("metrics:"):
                current_section = "metrics"
                continue
            elif stripped_line.startswith("dimensions:"):
                current_section = "dimensions"
                continue
            elif stripped_line.startswith("- name:") and current_section in (
                "metrics",
                "dimensions",
            ):
                item_name = stripped_line.split(":", 1)[1].strip().strip('"').strip("'")
                current_item = {"name": item_name}
                current_model[current_section].append(current_item)
            elif ":" in stripped_line and current_item is not None:
                key, val = stripped_line.split(":", 1)
                clean_val = val.strip().strip('"').strip("'")
                current_item[key.strip()] = clean_val

    return result


def load_semantic_models_from_dict(data: dict[str, Any]) -> list[SemanticModel]:
    """Loads semantic models from an arbitrary dictionary structure."""
    models: list[SemanticModel] = []
    items = data.get("models") or data.get("semantic_models")
    if items is None and ("metrics" in data or "dimensions" in data):
        items = [data]
    elif items is None:
        items = []

    for item in items:
        if isinstance(item, dict):
            models.append(SemanticModel.from_dict(item))
    return models


def load_semantic_models_from_yaml(content_or_path: str | Path) -> list[SemanticModel]:
    """Loads semantic models from a YAML string or file path."""
    content: str
    if isinstance(content_or_path, Path) or (
        isinstance(content_or_path, str)
        and (
            Path(content_or_path).is_file()
            or content_or_path.endswith((".yml", ".yaml", ".json"))
        )
    ):
        p = Path(content_or_path)
        if not p.is_file():
            raise SemanticError(
                f"Semantic configuration file not found: {content_or_path}"
            )
        content = p.read_text(encoding="utf-8")
    else:
        content = str(content_or_path)

    parsed = parse_simple_yaml_or_json(content)
    return load_semantic_models_from_dict(parsed)


def _format_filter_sql(f: MetricFilter, dialect: str) -> str:
    """Formats a single metric filter condition into SQL."""
    field_expr = f.field
    op = f.operator.lower()
    val = f.value

    if op in ("eq", "=", "=="):
        if val is None:
            return f"{field_expr} IS NULL"
        val_str = f"'{val}'" if isinstance(val, str) else str(val)
        return f"{field_expr} = {val_str}"
    elif op in ("neq", "!=", "<>"):
        if val is None:
            return f"{field_expr} IS NOT NULL"
        val_str = f"'{val}'" if isinstance(val, str) else str(val)
        return f"{field_expr} <> {val_str}"
    elif op in ("gt", ">"):
        return f"{field_expr} > {val}"
    elif op in ("gte", ">="):
        return f"{field_expr} >= {val}"
    elif op in ("lt", "<"):
        return f"{field_expr} < {val}"
    elif op in ("lte", "<="):
        return f"{field_expr} <= {val}"
    elif op in ("in",):
        if isinstance(val, (list, tuple, set)):
            formatted = ", ".join(
                f"'{v}'" if isinstance(v, str) else str(v) for v in val
            )
            return f"{field_expr} IN ({formatted})"
        return f"{field_expr} IN ({val})"
    elif op in ("not_in", "not in"):
        if isinstance(val, (list, tuple, set)):
            formatted = ", ".join(
                f"'{v}'" if isinstance(v, str) else str(v) for v in val
            )
            return f"{field_expr} NOT IN ({formatted})"
        return f"{field_expr} NOT IN ({val})"
    elif op == "is_null":
        return f"{field_expr} IS NULL"
    elif op == "is_not_null":
        return f"{field_expr} IS NOT NULL"
    else:
        val_str = f"'{val}'" if isinstance(val, str) else str(val)
        return f"{field_expr} = {val_str}"


def expand_metric_sql(metric: MetricDefinition, dialect: str = "postgres") -> str:
    """
    Expands a declarative MetricDefinition into dialect-appropriate aggregated SQL.
    Supports filtered aggregates via FILTER (WHERE ...) for PostgreSQL/SQLite/DuckDB
    and CASE WHEN ... for MySQL/SQL Server/BigQuery.
    """
    expr = metric.sql_expression.strip()
    agg = metric.aggregation.lower()
    dialect_low = dialect.lower()

    filter_conditions = [_format_filter_sql(f, dialect_low) for f in metric.filters]
    combined_filter = " AND ".join(filter_conditions) if filter_conditions else None

    # Handle custom expressions
    if agg == "custom":
        if combined_filter:
            return f"CASE WHEN {combined_filter} THEN ({expr}) ELSE NULL END"
        return f"({expr})"

    # Dialects supporting standard FILTER (WHERE ...) clause
    filter_clause_dialects = {
        "postgres",
        "postgresql",
        "duckdb",
        "sqlite",
        "cockroach",
        "cockroachdb",
    }

    agg_func_map = {
        "sum": "SUM",
        "avg": "AVG",
        "average": "AVG",
        "min": "MIN",
        "max": "MAX",
        "count": "COUNT",
        "count_distinct": "COUNT(DISTINCT ",
    }

    if agg == "count_distinct":
        if combined_filter:
            if dialect_low in filter_clause_dialects:
                return f"COUNT(DISTINCT {expr}) FILTER (WHERE {combined_filter})"
            else:
                return f"COUNT(DISTINCT CASE WHEN {combined_filter} THEN {expr} ELSE NULL END)"
        return f"COUNT(DISTINCT {expr})"

    func_name = agg_func_map.get(agg, "SUM")

    if combined_filter:
        if dialect_low in filter_clause_dialects:
            return f"{func_name}({expr}) FILTER (WHERE {combined_filter})"
        else:
            return f"{func_name}(CASE WHEN {combined_filter} THEN {expr} ELSE NULL END)"

    return f"{func_name}({expr})"


def expand_time_grain_sql(
    column_or_expr: str, grain: str, dialect: str = "postgres"
) -> str:
    """
    Expands a temporal expression into the appropriate date/time truncation
    function for the specified database dialect.
    """
    g = grain.lower()
    if g not in SUPPORTED_TIME_GRAINS:
        raise SemanticError(
            f"Unsupported time grain '{grain}'. Supported: {sorted(SUPPORTED_TIME_GRAINS)}"
        )

    expr = column_or_expr.strip()
    d = dialect.lower()

    if d in ("postgres", "postgresql", "duckdb", "redshift", "snowflake"):
        return f"DATE_TRUNC('{g}', {expr})"
    elif d in ("bigquery",):
        return f"DATE_TRUNC({expr}, {g.upper()})"
    elif d in ("sqlite",):
        sqlite_format_map = {
            "second": "%Y-%m-%d %H:%M:%S",
            "minute": "%Y-%m-%d %H:%M:00",
            "hour": "%Y-%m-%d %H:00:00",
            "day": "%Y-%m-%d",
            "week": "%Y-%W",
            "month": "%Y-%m-01",
            "quarter": "%Y-m",  # simplified
            "year": "%Y-01-01",
        }
        fmt = sqlite_format_map.get(g, "%Y-%m-%d")
        return f"STRFTIME('{fmt}', {expr})"
    elif d in ("mysql", "mariadb"):
        mysql_format_map = {
            "second": "%Y-%m-%d %H:%i:%s",
            "minute": "%Y-%m-%d %H:%i:00",
            "hour": "%Y-%m-%d %H:00:00",
            "day": "%Y-%m-%d",
            "week": "%Y-%u",
            "month": "%Y-%m-01",
            "quarter": "%Y-%q",
            "year": "%Y-01-01",
        }
        fmt = mysql_format_map.get(g, "%Y-%m-%d")
        return f"DATE_FORMAT({expr}, '{fmt}')"
    elif d in ("mssql", "sqlserver"):
        return f"DATETRUNC({g}, {expr})"
    elif d in ("oracle",):
        oracle_map = {
            "day": "DD",
            "week": "IW",
            "month": "MM",
            "quarter": "Q",
            "year": "YYYY",
            "hour": "HH",
            "minute": "MI",
            "second": "SS",
        }
        fmt = oracle_map.get(g, "DD")
        return f"TRUNC({expr}, '{fmt}')"
    else:
        return f"DATE_TRUNC('{g}', {expr})"
