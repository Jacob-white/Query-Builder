"""JDBC-over-JayDeBeApi cursor helpers shared by the H2 and Derby connectors."""

from __future__ import annotations

from typing import Any


class _LabelledCursor:
    """Cursor proxy whose ``description`` names columns by their JDBC *label*.

    JayDeBeApi builds ``description`` from ``ResultSetMetaData.getColumnName``, which for H2
    is the underlying column (``name``) rather than the ``AS`` alias (``dept``), so every
    aliased column came back under the wrong key. ``getColumnLabel`` is the alias.
    """

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    @property
    def description(self) -> Any:
        description = self._cursor.description
        meta = getattr(self._cursor, "_meta", None)
        if not description or meta is None:
            return description
        labels = [
            str(meta.getColumnLabel(i))
            for i in range(1, int(meta.getColumnCount()) + 1)
        ]
        if len(labels) != len(description):
            return description
        return [
            (label, *col[1:]) for label, col in zip(labels, description, strict=True)
        ]


def label_columns(cursor: Any) -> Any:
    """Wrap a JayDeBeApi cursor so column names are JDBC labels; others pass through."""
    is_jaydebeapi = type(cursor).__module__.startswith("jaydebeapi")
    return (
        _LabelledCursor(cursor)
        if is_jaydebeapi and hasattr(cursor, "_meta")
        else cursor
    )
