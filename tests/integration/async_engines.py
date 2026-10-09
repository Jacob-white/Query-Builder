"""
Async parity: engines that ship an async connector class are exercised through it
and must agree with the sync connector on the same live data.

``ASYNC`` is derived from the engine registry (``Engine.async_connector``), so a
new async class is picked up by registering its engine.
"""

from __future__ import annotations

from tests.integration import engines as eng

ASYNC: dict[str, eng.Engine] = {
    name: e for name, e in eng.ENGINES.items() if e.async_connector
}
