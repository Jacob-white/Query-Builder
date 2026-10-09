"""
Transaction hygiene shared by DB-API connectors that run in a transaction.

PostgreSQL (and its wire-compatible engines) refuses every further statement on
a connection whose transaction hit an error ("current transaction is aborted"),
so one failed query would poison the connector until it is reconnected.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any


class RollbackOnErrorMixin:
    """Roll the connection back when a statement run through get_cursor() fails."""

    _connection: Any

    @contextlib.contextmanager
    def get_cursor(self) -> Iterator[Any]:
        with super().get_cursor() as cur:  # type: ignore[misc]
            try:
                yield cur
            except Exception:
                rollback = getattr(self._connection, "rollback", None)
                if callable(rollback):
                    with contextlib.suppress(Exception):
                        rollback()
                raise
