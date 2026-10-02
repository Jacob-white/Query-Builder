import pytest

from query_builder.join_solver import find_best_join_condition, find_join_path


@pytest.fixture
def sample_schema():
    return {
        "tables": {
            "firm_master": {
                "columns": [
                    {"name": "firm_master_id", "is_primary": True},
                    {"name": "legal_name"},
                    {"name": "crd_number"},
                ]
            },
            "contact_master": {
                "columns": [
                    {"name": "contact_master_id", "is_primary": True},
                    {"name": "first_name"},
                    {"name": "last_name"},
                ]
            },
            "firm_branch": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "firm_master_id"},
                    {"name": "address_master_id"},
                    {"name": "branch_name"},
                ]
            },
            "address_master": {
                "columns": [
                    {"name": "address_master_id", "is_primary": True},
                    {"name": "city"},
                    {"name": "state"},
                ]
            }
        },
        "foreign_keys": [
            {
                "table": "firm_branch",
                "column": "firm_master_id",
                "foreign_table": "firm_master",
                "foreign_column": "firm_master_id",
            },
            {
                "table": "firm_branch",
                "column": "address_master_id",
                "foreign_table": "address_master",
                "foreign_column": "address_master_id",
            },
        ]
    }


def test_find_best_join_condition_fk_direct(sample_schema):
    cond = find_best_join_condition("firm_master", "firm_branch", sample_schema)
    assert cond["is_fk"] is True
    assert cond["left_table"] == "firm_master"
    assert cond["left_col"] == "firm_master_id"
    assert cond["right_table"] == "firm_branch"
    assert cond["right_col"] == "firm_master_id"


def test_find_best_join_condition_canonical_match():
    schema = {
        "tables": {
            "users": {"columns": [{"name": "user_id"}, {"name": "email"}]},
            "orders": {"columns": [{"name": "user_id"}, {"name": "amount"}]},
        }
    }
    cond = find_best_join_condition("users", "orders", schema)
    assert cond["left_col"] == "user_id"
    assert cond["right_col"] == "user_id"


def test_find_join_path_bfs_multi_hop(sample_schema):
    # Join from firm_master to address_master through firm_branch
    path = find_join_path(["firm_master"], "address_master", sample_schema)
    assert len(path) == 2
    assert path[0]["table"] == "firm_branch"
    assert path[1]["table"] == "address_master"


def test_find_join_path_already_active(sample_schema):
    path = find_join_path(["firm_master"], "firm_master", sample_schema)
    assert path == []
