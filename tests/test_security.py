import pytest

from query_builder.dialects import get_dialect
from query_builder.security import SecurityError, resolve_ownership_predicate


def test_resolve_ownership_direct_user_id():
    dialect = get_dialect("postgres")
    tables_meta = {
        "projects": {
            "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "title"}],
            "has_user_id": True,
            "user_col": "user_id",
        }
    }
    params = []
    predicate = resolve_ownership_predicate(
        dialect, tables_meta, "t1", "projects", 42, params
    )
    assert predicate == '"t1"."user_id" = %s'
    assert params == [42]


def test_resolve_ownership_multi_hop_chain():
    dialect = get_dialect("postgres")
    tables_meta = {
        "projects": {
            "columns": [{"name": "id"}, {"name": "user_id"}],
            "has_user_id": True,
            "user_col": "user_id",
        },
        "tasks": {
            "columns": [{"name": "id"}, {"name": "project_id"}],
            "has_user_id": False,
        },
        "evidence": {
            "columns": [{"name": "id"}, {"name": "task_id"}],
            "has_user_id": False,
        },
    }
    ownership_paths = {
        "tasks": [[("project_id", "projects", "id")]],
        "evidence": [[("task_id", "tasks", "id"), ("project_id", "projects", "id")]],
    }
    params = []
    predicate = resolve_ownership_predicate(
        dialect,
        tables_meta,
        "t1",
        "evidence",
        42,
        params,
        ownership_paths=ownership_paths,
    )
    assert "EXISTS" in predicate
    assert '"tasks"' in predicate
    assert '"projects"' in predicate
    assert params == [42]


def test_resolve_ownership_fails_closed_when_unresolvable():
    dialect = get_dialect("postgres")
    tables_meta = {
        "orphaned_table": {
            "columns": [{"name": "id"}, {"name": "val"}],
            "has_user_id": False,
        }
    }
    params = []
    with pytest.raises(SecurityError) as exc:
        resolve_ownership_predicate(
            dialect, tables_meta, "t1", "orphaned_table", 42, params
        )
    assert "refusing to query it without tenant isolation" in str(exc.value)
