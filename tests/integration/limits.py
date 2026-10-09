"""
Registry of declared limitations across SQL engines (``Engine.unsupported``) and native
smoke engines (``Smoke.limitations``), plus the lookup the report uses to classify skips.

A limitation WITH a probe can be verified live (``test_declared_limitations_are_real``);
one without is ``declared_unverified``.
"""

from __future__ import annotations

from tests.integration import engines as eng
from tests.integration import smoke
from tests.integration.engines import Limitation, as_limitation


def lookup(engine: str, feature: str) -> Limitation | None:
    """The limitation ``engine`` declares for ``feature`` (SQL table first, then smoke)."""
    e = eng.ENGINES.get(engine)
    if e is not None:
        found = e.limitation(feature)
        if found is not None:
            return found
    sm = smoke.SMOKE.get(engine)
    if sm is not None and feature in sm.limitations:
        return as_limitation(sm.limitations[feature])
    return None


def all_declared() -> dict[tuple[str, str], Limitation]:
    """Every declared ``(engine, feature) -> Limitation``."""
    out: dict[tuple[str, str], Limitation] = {}
    for name, e in eng.ENGINES.items():
        for feature in e.unsupported:
            lim = e.limitation(feature)
            assert lim is not None
            out[(name, feature)] = lim
    for name, sm in smoke.SMOKE.items():
        for feature, value in sm.limitations.items():
            out[(name, feature)] = as_limitation(value)
    return out


def probe_ids() -> list[str]:
    """``engine::feature`` ids of the limitations that carry a probe."""
    return [
        f"{name}::{feature}"
        for (name, feature), lim in sorted(all_declared().items())
        if lim.probe is not None
    ]
