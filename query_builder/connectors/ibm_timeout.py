"""Statement timeout for the IBM CLI driver (``ibm_db`` / ``ibm_db_dbi``): Db2, Informix."""

from __future__ import annotations

import importlib
from typing import Any


def apply_prepared_query_timeout(cursor: Any, timeout_ms: int) -> None:
    """Make every statement run on ``cursor`` honour ``timeout_ms`` (whole seconds, min 1).

    The CLI query-timeout attribute is ignored on the connection and only takes effect on a
    prepared statement handle, so this cursor prepares each statement, sets the attribute on
    its handle and then executes the prepared statement.
    """
    seconds = max(int(timeout_ms // 1000), 1)
    try:
        ibm_db: Any = importlib.import_module("ibm_db")

        prepare = cursor.prepare
        run_prepared = cursor.execute
    except (ImportError, AttributeError):
        return

    def execute(operation: Any = None, parameters: Any = None) -> Any:
        prepare(operation)
        ibm_db.set_option(
            cursor.stmt_handler, {ibm_db.SQL_ATTR_QUERY_TIMEOUT: seconds}, 0
        )
        if parameters is None:
            return run_prepared()
        return run_prepared(None, parameters)

    cursor.execute = execute
