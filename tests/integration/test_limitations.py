"""
Declared limitations must prove themselves.

An engine owner can declare that an engine "legitimately lacks" a feature, and the dependent
live tests are then skipped. A skip can hide a real gap, so every limitation that carries a
``probe`` is attempted here through the NATIVE driver (never the connector under test); the
engine must REJECT it. If the engine ACCEPTS the probe the declaration is wrong and this test
FAILS, forcing the feature to be tested instead of skipped.

Limitations without a probe stay ``declared_unverified`` in the report and block the
``certified`` tier when they sit in a core category.
"""

from __future__ import annotations

import pytest

from tests.integration import conftest, limits
from tests.integration.engines import Engine, run_probe


@pytest.mark.qb_category("limitation_probe")
def test_declared_limitations_are_real(limitation_id: str, limitation_engine: Engine) -> None:
    name, feature = limitation_id.split("::", 1)
    lim = limits.lookup(name, feature)
    assert lim is not None and lim.probe is not None
    rejected, detail = run_probe(limitation_engine, lim)
    conftest._PROBES[(name, feature)] = rejected
    assert rejected, (
        f"{name}: declared limitation {feature!r} ({lim.reason}) is WRONG - {detail}. "
        "Remove the declaration and test the feature instead."
    )
