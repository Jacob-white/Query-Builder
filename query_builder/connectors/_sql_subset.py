"""
A deliberately small SQL ``SELECT`` subset for engines that have NO SQL (Firestore,
Bigtable): single collection/table, projection, ``WHERE`` of AND-ed simple predicates,
``ORDER BY``, ``LIMIT``/``OFFSET`` and ``COUNT(*)``.

Anything outside the subset (joins, sub-queries, ``GROUP BY``, ``OR``, functions, DML ...)
raises :class:`UnsupportedQuery` instead of being approximated: a connector that silently
returned "the first ten documents" for a query it did not understand would hand callers
wrong data that looks right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from query_builder.connectors.base import QueryExecutionError

_PLACEHOLDER = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"|`([^`]*)`|(%s|\?)")


class UnsupportedQuery(QueryExecutionError):
    """The statement is outside the SQL subset this engine can run natively."""


@dataclass
class Predicate:
    column: str
    op: str  # = != < <= > >= in not-in is-null is-not-null prefix
    value: Any = None


@dataclass
class SubsetPlan:
    table: str
    columns: list[str] | None  # None = every column (``*``)
    out_names: list[str] = field(default_factory=list)  # output name per column
    predicates: list[Predicate] = field(default_factory=list)
    order_by: list[tuple[str, bool]] = field(
        default_factory=list
    )  # (column, descending)
    limit: int | None = None
    offset: int = 0
    count_star: bool = False
    count_alias: str = "count"


def _number_placeholders(sql: str) -> str:
    counter = iter(range(10**6))

    def sub(m: re.Match[str]) -> str:
        if m.group(2):
            return f":__p{next(counter)}"
        if m.group(1) is not None:  # `identifier` -> "identifier"
            return '"' + m.group(1) + '"'
        return m.group(0)

    return _PLACEHOLDER.sub(sub, sql)


def _literal(node: Any, params: list[Any]) -> Any:
    from sqlglot import exp

    if isinstance(node, exp.Paren):
        return _literal(node.this, params)
    if isinstance(node, exp.Neg):
        return -_literal(node.this, params)
    if isinstance(node, exp.Placeholder):
        name = str(node.this)
        if name.startswith("__p") and name[3:].isdigit():
            idx = int(name[3:])
            if idx >= len(params):
                raise UnsupportedQuery("missing value for a bind placeholder")
            return params[idx]
        raise UnsupportedQuery(f"named placeholder :{name} is not supported")
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Literal):
        if node.is_string:
            return str(node.this)
        text = str(node.this)
        return float(text) if any(c in text for c in ".eE") else int(text)
    raise UnsupportedQuery(f"unsupported value expression: {node.sql()}")


def _column(node: Any) -> str:
    from sqlglot import exp

    if isinstance(node, exp.Column):
        return str(node.name)
    raise UnsupportedQuery(f"expected a column, got: {node.sql()}")


_OPS = {"EQ": "=", "NEQ": "!=", "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<="}
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "=", "!=": "!="}


def _flatten_and(node: Any) -> list[Any]:
    from sqlglot import exp

    if isinstance(node, exp.Paren):
        return _flatten_and(node.this)
    if isinstance(node, exp.And):
        return _flatten_and(node.left) + _flatten_and(node.right)
    return [node]


def _predicate(node: Any, params: list[Any]) -> Predicate:
    from sqlglot import exp

    kind = type(node).__name__.upper()
    if kind in _OPS:
        op = _OPS[kind]
        if isinstance(node.left, exp.Column):
            return Predicate(_column(node.left), op, _literal(node.right, params))
        return Predicate(_column(node.right), _FLIP[op], _literal(node.left, params))
    if isinstance(node, exp.In):
        if node.args.get("query") is not None:
            raise UnsupportedQuery("IN (subquery) is not supported")
        return Predicate(
            _column(node.this), "in", [_literal(v, params) for v in node.expressions]
        )
    if isinstance(node, exp.Is):
        if isinstance(node.expression, exp.Null):
            return Predicate(_column(node.this), "is-null")
        raise UnsupportedQuery(f"unsupported IS predicate: {node.sql()}")
    if isinstance(node, exp.Not):
        inner = node.this
        if isinstance(inner, exp.Paren):
            inner = inner.this
        if isinstance(inner, exp.In) and inner.args.get("query") is None:
            return Predicate(
                _column(inner.this),
                "not-in",
                [_literal(v, params) for v in inner.expressions],
            )
        if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
            return Predicate(_column(inner.this), "is-not-null")
        raise UnsupportedQuery(f"unsupported NOT predicate: {node.sql()}")
    if isinstance(node, exp.Like):
        pattern = _literal(node.expression, params)
        if (
            isinstance(pattern, str)
            and pattern.endswith("%")
            and not re.search(r"[%_]", pattern[:-1])
        ):
            return Predicate(_column(node.this), "prefix", pattern[:-1])
        raise UnsupportedQuery("only LIKE 'prefix%' is supported")
    raise UnsupportedQuery(f"unsupported predicate: {node.sql()}")


def parse_select_subset(sql: str, params: list[Any] | None = None) -> SubsetPlan:
    """Parse ``sql`` into a :class:`SubsetPlan` or raise :class:`UnsupportedQuery`."""
    import sqlglot
    from sqlglot import exp

    params = list(params or [])
    try:
        tree = sqlglot.parse_one(_number_placeholders(sql.strip().rstrip(";")))
    except sqlglot.errors.SqlglotError as exc:
        raise UnsupportedQuery(f"cannot parse statement: {exc}") from exc
    if not isinstance(tree, exp.Select):
        raise UnsupportedQuery("only SELECT statements are supported")
    allowed = {"expressions", "from", "from_", "where", "order", "limit", "offset"}
    extra = {k for k, v in tree.args.items() if v and k not in allowed}
    if extra:
        raise UnsupportedQuery(f"unsupported clause: {', '.join(sorted(extra))}")
    source = tree.args.get("from") or tree.args.get("from_")
    table_node = source.this if source is not None else None
    if not isinstance(table_node, exp.Table) or table_node.args.get("joins"):
        raise UnsupportedQuery("exactly one collection/table is required in FROM")
    plan = SubsetPlan(table=str(table_node.name), columns=None)

    cols: list[str] = []
    outs: list[str] = []
    star = False
    for item in tree.expressions:
        inner = item.this if isinstance(item, exp.Alias) else item
        alias = item.alias if isinstance(item, exp.Alias) else None
        if isinstance(inner, exp.Star):
            star = True
        elif isinstance(inner, exp.Count) and isinstance(inner.this, exp.Star):
            plan.count_star = True
            plan.count_alias = alias or "count"
        elif isinstance(inner, exp.Column):
            if isinstance(inner.this, exp.Star):
                star = True
            else:
                cols.append(str(inner.name))
                outs.append(alias or str(inner.name))
        else:
            raise UnsupportedQuery(f"unsupported select expression: {inner.sql()}")
    if plan.count_star and (cols or star):
        raise UnsupportedQuery("COUNT(*) cannot be mixed with other columns")
    if not star and cols:
        plan.columns, plan.out_names = cols, outs

    where = tree.args.get("where")
    if where is not None:
        plan.predicates = [_predicate(n, params) for n in _flatten_and(where.this)]
    order = tree.args.get("order")
    if order is not None:
        for o in order.expressions:
            plan.order_by.append((_column(o.this), bool(o.args.get("desc"))))
    limit = tree.args.get("limit")
    if limit is not None:
        plan.limit = int(_literal(limit.expression, params))
    offset = tree.args.get("offset")
    if offset is not None:
        plan.offset = int(_literal(offset.expression, params))
    return plan
