"""
Shared interpreter for the SQL-shaped text the compiler emits for vector stores.

Vector databases (Qdrant, Weaviate, Milvus, Pinecone, ...) have no SQL engine. The connector
compiles a ``QuerySpec`` (including ``vector_search``) with its dialect to a restricted
``SELECT`` and the cursor adapter must *interpret* that text against the vendor client. This
module parses that text into a small, explicit :class:`VectorQuery` (collection, projection,
AND-ed filter conditions, vector + metric, ordering, limit/offset) so each adapter only has to
translate the structure into its native call.

Anything the engine layer cannot honour is rejected with :class:`VectorQueryError` instead of
being silently ignored: a vector store that drops a ``WHERE`` clause returns wrong rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from query_builder.connectors.base import QueryExecutionError

DISTANCE_FUNCS = {
    "COSINE_DISTANCE": "cosine",
    "L2_DISTANCE": "euclidean",
    "INNER_PRODUCT": "dot",
}
_CMP = {"EQ": "=", "NEQ": "!=", "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<="}
_PLACEHOLDER = re.compile(r"%s")


class VectorQueryError(QueryExecutionError):
    """The SQL text uses a construct the vector store cannot execute faithfully."""


@dataclass
class Cond:
    column: str
    op: str  # = != > >= < <= in not_in is_null is_not_null
    value: Any = None


@dataclass
class VectorQuery:
    table: str
    count_only: bool = False
    #: (output name, source column | "*" | "_distance")
    columns: list[tuple[str, str]] = field(default_factory=list)
    conds: list[Cond] = field(default_factory=list)
    vector: list[float] | None = None
    metric: str | None = None
    vector_column: str | None = None
    #: from ``min_score``: keep only hits with distance <= this
    max_distance: float | None = None
    order_by: list[tuple[str, bool]] = field(default_factory=list)  # (name, desc)
    limit: int | None = None
    offset: int = 0

    @property
    def is_search(self) -> bool:
        return self.vector is not None

    def wanted_payload_fields(self) -> list[str] | None:
        """Payload fields to fetch; ``None`` means all."""
        if any(src == "*" for _, src in self.columns):
            return None
        names = {src for _, src in self.columns if src not in ("_distance",)}
        names |= {c.column for c in self.conds}
        names |= {n for n, _ in self.order_by if n != "_distance"}
        return sorted(names)


def vector_from_param(value: Any) -> list[float]:
    """The compiler binds the query vector as ``str([..])``; accept lists as well."""
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise VectorQueryError("vector parameter is not a JSON list") from exc
        if isinstance(parsed, list) and parsed:
            return [float(x) for x in parsed]
    raise VectorQueryError("vector parameter must be a non-empty list of numbers")


def distance_from_score(metric: str, score: float, engine_metric: str) -> float:
    """Convert an engine *score* into the pgvector-style distance the SQL promised.

    ``engine_metric`` is the metric the collection was built with; it must equal the
    requested ``metric`` (an index cannot be searched under another metric).
    """
    if metric != engine_metric:
        raise VectorQueryError(
            f"query asks for {metric} distance but the collection uses {engine_metric}"
        )
    if metric == "cosine":
        return 1.0 - float(score)
    if metric == "dot":
        return -float(score)
    return float(score)


def parse_vector_sql(sql: str, params: list[Any] | None = None) -> VectorQuery:
    import sqlglot
    from sqlglot import exp

    params = list(params or [])
    counter = iter(range(10_000))
    text = _PLACEHOLDER.sub(lambda _m: f":p{next(counter)}", sql.strip().rstrip(";"))
    text = text.replace("`", '"')
    try:
        tree = sqlglot.parse_one(text, read="postgres")
    except Exception as exc:  # noqa: BLE001 - sqlglot raises several error types
        raise VectorQueryError(f"cannot parse vector query: {exc}") from exc
    if not isinstance(tree, exp.Select):
        raise VectorQueryError("only SELECT is supported by vector stores")
    for forbidden in ("joins", "group", "having", "with", "with_", "distinct", "laterals"):
        if tree.args.get(forbidden):
            raise VectorQueryError(
                f"{forbidden.rstrip('_').upper()} is not supported by vector stores"
            )

    def value_of(node: Any) -> Any:
        if isinstance(node, exp.Placeholder):
            idx = int(str(node.this).lstrip("p"))
            if idx >= len(params):
                raise VectorQueryError("missing query parameter")
            return params[idx]
        if isinstance(node, exp.Literal):
            return (
                int(node.this)
                if not node.is_string and "." not in node.this
                else (float(node.this) if not node.is_string else node.this)
            )
        if isinstance(node, exp.Boolean):
            return bool(node.this)
        if isinstance(node, exp.Null):
            return None
        if isinstance(node, exp.Neg):
            return -value_of(node.this)
        raise VectorQueryError(f"unsupported value expression: {node.sql()}")

    def col_name(node: Any) -> str:
        if isinstance(node, exp.Column):
            return str(node.name)
        raise VectorQueryError(f"unsupported column expression: {node.sql()}")

    def dist_func(node: Any) -> str | None:
        return _distance_func(node)

    from_ = tree.args.get("from") or tree.args.get("from_")
    table = from_.this if from_ is not None else None
    if not isinstance(table, exp.Table):
        raise VectorQueryError("a single collection in FROM is required")
    vq = VectorQuery(table=str(table.name))

    distance_aliases: set[str] = set()
    for item in tree.expressions:
        inner = item.this if isinstance(item, exp.Alias) else item
        alias = item.alias if isinstance(item, exp.Alias) else None
        func = dist_func(inner)
        if isinstance(inner, exp.Star):
            vq.columns.append(("*", "*"))
        elif isinstance(inner, exp.Count):
            vq.count_only = True
        elif func is not None:
            vq.columns.append((alias or "_distance", "_distance"))
            distance_aliases.add(alias or "_distance")
            _set_vector(vq, func, value_of(_func_args(inner)[1]), _arg_col(inner))
        elif isinstance(inner, exp.Column):
            vq.columns.append((alias or inner.name, inner.name))
        else:
            raise VectorQueryError(f"unsupported projection: {inner.sql()}")

    where = tree.args.get("where")
    if where is not None:
        for leaf in _and_leaves(where.this):
            _read_condition(vq, leaf, value_of, col_name, dist_func)

    order = tree.args.get("order")
    if order is not None:
        for o in order.expressions:
            target = o.this
            if dist_func(target) is not None:
                name = "_distance"
                _set_vector(
                    vq,
                    dist_func(target) or "",
                    value_of(_func_args(target)[1]),
                    _arg_col(target),
                )
            elif isinstance(target, exp.Column):
                name = "_distance" if target.name in distance_aliases else target.name
            else:
                raise VectorQueryError(f"unsupported ORDER BY: {target.sql()}")
            vq.order_by.append((name, bool(o.args.get("desc"))))

    limit = tree.args.get("limit")
    if limit is not None:
        vq.limit = int(value_of(limit.expression))
    offset = tree.args.get("offset")
    if offset is not None:
        vq.offset = int(value_of(offset.expression))
    return vq


def _distance_func(node: Any) -> str | None:
    """sqlglot may parse COSINE_DISTANCE & co. as a typed node or as an anonymous function."""
    from sqlglot import exp

    if not isinstance(node, exp.Func):
        return None
    raw = node.name if isinstance(node, exp.Anonymous) else node.key
    norm = str(raw).upper().replace("_", "")
    for name in DISTANCE_FUNCS:
        if norm == name.replace("_", ""):
            return name
    return None


def _arg_col(node: Any) -> str | None:
    first = _func_args(node)[0]
    return str(first.name) if hasattr(first, "name") else None


def _func_args(node: Any) -> list[Any]:
    from sqlglot import exp

    if isinstance(node, exp.Anonymous):
        return list(node.expressions)
    return [node.this, node.args.get("expression")]


def _set_vector(
    vq: VectorQuery, func: str, raw: Any, column: str | None = None
) -> None:
    vec = vector_from_param(raw)
    metric = DISTANCE_FUNCS[func]
    if vq.vector is not None and (vq.vector != vec or vq.metric != metric):
        raise VectorQueryError("only one query vector per statement is supported")
    vq.vector, vq.metric = vec, metric
    vq.vector_column = column or vq.vector_column


def _and_leaves(node: Any) -> list[Any]:
    from sqlglot import exp

    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return _and_leaves(node.left) + _and_leaves(node.right)
    return [node]


def _read_condition(
    vq: VectorQuery, node: Any, value_of: Any, col_name: Any, dist_func: Any
) -> None:
    from sqlglot import exp

    # ``node`` is a leaf from ``_and_leaves``: never a Paren or And
    if isinstance(node, (exp.LT, exp.LTE)) and dist_func(node.left) is not None:
        _set_vector(
            vq,
            dist_func(node.left),
            value_of(_func_args(node.left)[1]),
            _arg_col(node.left),
        )
        vq.max_distance = float(value_of(node.right))
        return
    for cls_name, op in _CMP.items():
        if type(node).__name__ == cls_name:
            vq.conds.append(Cond(col_name(node.left), op, value_of(node.right)))
            return
    if isinstance(node, exp.In):
        vals = [value_of(v) for v in node.expressions]
        vq.conds.append(Cond(col_name(node.this), "in", vals))
        return
    if isinstance(node, exp.Is) and isinstance(node.expression, exp.Null):
        # newer sqlglot parses ``x IS NOT NULL`` as Is(negate=True), older as Not(Is(...))
        op = "is_not_null" if node.args.get("negate") else "is_null"
        vq.conds.append(Cond(col_name(node.this), op))
        return
    if isinstance(node, exp.Not):
        inner = node.this
        while isinstance(inner, exp.Paren):
            inner = inner.this
        if isinstance(inner, exp.In):
            vals = [value_of(v) for v in inner.expressions]
            vq.conds.append(Cond(col_name(inner.this), "not_in", vals))
            return
        if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
            vq.conds.append(Cond(col_name(inner.this), "is_not_null"))
            return
    raise VectorQueryError(
        f"unsupported WHERE condition for a vector store: {node.sql()}"
    )


def shape_rows(
    vq: VectorQuery, hits: list[dict[str, Any]]
) -> tuple[list[tuple[str]], list[list[Any]]]:
    """Build a DB-API ``description`` and rows from hit dicts (``id``, payload, ``_distance``)."""
    if vq.count_only:
        return [("count",)], [[len(hits)]]
    columns = list(vq.columns)
    if any(src == "*" for _, src in columns):
        names: list[str] = []
        for hit in hits:
            for key in hit:
                if key not in names:
                    names.append(key)
        columns = [(n, n) for n in names] or [("id", "id")]
    description = [(name,) for name, _ in columns]
    rows = [[hit.get(src) for _, src in columns] for hit in hits]
    return description, rows


def sort_hits(vq: VectorQuery, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Client-side ORDER BY for scans (``None`` sorts last in either direction)."""
    for name, desc in reversed(vq.order_by):
        present = [h for h in hits if h.get(name) is not None]
        missing = [h for h in hits if h.get(name) is None]
        present.sort(key=lambda h: h[name], reverse=desc)
        hits = present + missing
    return hits


def matches(conds: list[Cond], hit: dict[str, Any]) -> bool:
    """Evaluate AND-ed conditions client-side (used by engines without a native filter)."""
    for c in conds:
        v = hit.get(c.column)
        if c.op == "is_null":
            ok = v is None
        elif c.op == "is_not_null":
            ok = v is not None
        elif v is None:
            ok = c.op == "!="
        elif c.op == "=":
            ok = v == c.value
        elif c.op == "!=":
            ok = v != c.value
        elif c.op == "in":
            ok = v in c.value
        elif c.op == "not_in":
            ok = v not in c.value
        else:
            try:
                ok = {
                    ">": v > c.value,
                    ">=": v >= c.value,
                    "<": v < c.value,
                    "<=": v <= c.value,
                }[c.op]
            except TypeError:
                ok = False
        if not ok:
            return False
    return True


# ---------------------------------------------------------------- plan drivers
# An adapter expresses its logic once as a generator that yields ``(method, kwargs)`` calls to
# the vendor client and receives the results. The sync adapter drives it with direct calls,
# the async adapter awaits each call, so both classes share exactly one implementation.
Call = tuple[str, dict[str, Any]]


def _resolve(client: Any, dotted: Any) -> Any:
    if callable(dotted):  # a bound method of an object returned by an earlier call
        return dotted
    target = client
    for part in dotted.split("."):
        target = getattr(target, part)
    return target


def drive_sync(plan: Any, client: Any) -> Any:
    try:
        request = next(plan)
        while True:
            name, kwargs = request
            try:
                result = _resolve(client, name)(**kwargs)
            except Exception as exc:  # noqa: BLE001 - let the plan decide
                request = plan.throw(exc)
            else:
                request = plan.send(result)
    except StopIteration as done:
        return done.value


async def drive_async(plan: Any, client: Any) -> Any:
    import inspect

    try:
        request = next(plan)
        while True:
            name, kwargs = request
            try:
                result = _resolve(client, name)(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
                if hasattr(result, "__aiter__"):  # async generator: collect it
                    result = [item async for item in result]
            except Exception as exc:  # noqa: BLE001 - let the plan decide
                request = plan.throw(exc)
            else:
                request = plan.send(result)
    except StopIteration as done:
        return done.value


def infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "json"
    return "unknown"


def payload_columns(
    samples: list[dict[str, Any]], declared: dict[str, str] | None = None
) -> dict[str, str]:
    """Union of payload keys (declared schema first, then keys observed in samples)."""
    cols: dict[str, str] = dict(declared or {})
    for sample in samples:
        for key, value in sample.items():
            if value is None:
                cols.setdefault(key, "unknown")
            elif cols.get(key, "unknown") == "unknown":
                cols[key] = infer_type(value)
    return cols
