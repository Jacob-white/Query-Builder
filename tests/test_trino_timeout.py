"""Trino applies the statement timeout through its session property."""

from unittest.mock import MagicMock

from query_builder.connectors.trino import TrinoConnector


def test_trino_statement_timeout_sets_session_property():
    cur = MagicMock()
    TrinoConnector(connection=MagicMock()).apply_statement_timeout(cur, 2500)
    cur.execute.assert_called_once_with(
        "SET SESSION query_max_execution_time = '2500ms'"
    )
    cur.fetchall.assert_called_once()
