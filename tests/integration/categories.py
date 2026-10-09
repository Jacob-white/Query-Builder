"""
Check categories for the live suite.

Every live test result is attributed to ONE named category so the report can say
*what* was tested, not just how many tests passed. ``certified`` (see
``query_builder/connectors/status.py``) needs every applicable CORE category of the
engine's family to be covered; skips must prove themselves (``Limitation`` probes in
``engines.py``).

How a test gets its category (first match wins, see :func:`category_of`):

1. ``@pytest.mark.qb_category("name")`` on the test function;
2. for the parametrized query battery, ``Case.category`` (derived from the case in
   :func:`case_category`).

A test without a category is reported under ``uncategorized`` (never core).
"""

from __future__ import annotations

import re
from typing import Any

from query_builder.connectors.status import NATIVE_CORE, SQL_CORE

#: SQL family core: what a SQL engine must demonstrate to be ``certified``.
SQL_CORE_CATEGORIES: tuple[str, ...] = SQL_CORE
#: NATIVE family core: non-SQL engines (document, key-value, search, graph, wide-column,
#: vector, ...). ``async_parity`` only applies when the engine has an async class.
NATIVE_CORE_CATEGORIES: tuple[str, ...] = NATIVE_CORE

#: Valid non-core categories (reported, never required).
EXTRA_CATEGORIES: tuple[str, ...] = (
    "window",  # window functions: legitimately absent in many engines
    "secrets",  # wrong password never leaks
    "spec_compile",  # QuerySpec -> native query (only engines with a compiler path)
    "limitation_probe",  # test_declared_limitations_are_real
    "registry",  # harness sanity checks
    "uncategorized",
)
ALL_CATEGORIES: frozenset[str] = frozenset(
    SQL_CORE_CATEGORIES + NATIVE_CORE_CATEGORIES + EXTRA_CATEGORIES
)

#: case ids (query battery) that exercise pagination rather than ordering.
_PAGINATION_IDS = {"order-desc-limit-offset", "offset-past-end", "limit-zero-one"}


def case_category(group: str, case_id: str, requires: tuple[str, ...] = ()) -> str:
    """Category of one declarative query case (``tests/integration/cases.py``)."""
    if case_id in _PAGINATION_IDS:
        return "pagination"
    if "in_subquery" in requires or "subquery" in case_id:
        return "subquery_cte"
    if case_id == "aggregate-null-handling":
        return "null_handling"
    return {
        "select": "read_projection",
        "filter": "filters",
        "order": "ordering",
        "aggregate": "aggregates",
        "distinct": "aggregates",
        "join": "joins",
        "cte": "subquery_cte",
        "window": "window",
        "binding": "parameter_safety",
        "quoting": "identifier_quoting",
        "null": "null_handling",
    }.get(group, "uncategorized")


def core_for(family_kind: str, has_async: bool) -> list[str]:
    """Core categories that apply to an engine (``async_parity`` only with an async class)."""
    core = SQL_CORE_CATEGORIES if family_kind == "sql" else NATIVE_CORE_CATEGORIES
    return [c for c in core if c != "async_parity" or has_async]


def category_of(item: Any) -> str:
    """Category of a collected pytest item."""
    marker = item.get_closest_marker("qb_category")
    if marker is not None:
        return str(marker.args[0])
    callspec = getattr(item, "callspec", None)
    if callspec is not None:
        case = callspec.params.get("case")
        category = getattr(case, "category", "")
        if category:
            return str(category)
    return "uncategorized"


# ---------------------------------------------------------------- skip classes
LIMITATION_TAG = "[limitation:"
ENVIRONMENT_TAG = "[environment]"
_ENV_PATTERNS = re.compile(
    r"not reachable|driver (?:not installed|unusable)|not installed|is installed but"
    r"|set QB_IT_|unavailable|cannot be imported|required but",
    re.IGNORECASE,
)


def limitation_reason(engine: str, feature: str, reason: str) -> str:
    """Skip message for a declared limitation; :func:`classify_skip` parses it back."""
    return f"{LIMITATION_TAG}{feature}] {engine}: {feature} unsupported - {reason}"


def environment_reason(reason: str) -> str:
    return f"{ENVIRONMENT_TAG} {reason}"


def classify_skip(reason: str) -> tuple[str, str | None]:
    """``(kind, feature)``: kind is ``limitation`` | ``environment`` | ``other``."""
    if reason.startswith(LIMITATION_TAG):
        feature = reason[len(LIMITATION_TAG) :].split("]", 1)[0]
        return "limitation", feature
    if reason.startswith(ENVIRONMENT_TAG) or _ENV_PATTERNS.search(reason):
        return "environment", None
    return "other", None


def empty_category() -> dict[str, Any]:
    return {
        "passed": 0,
        "failed": 0,
        "xfailed": 0,
        "skipped": {
            "verified_limitation": 0,
            "declared_unverified": 0,
            "environment": 0,
        },
    }
