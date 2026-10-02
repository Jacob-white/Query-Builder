import pytest

from query_builder.join_solver import find_best_join_condition, find_join_path


@pytest.fixture
def sample_schema():
    return {
        "tables": {
            "customer_master": {
                "columns": [
                    {"name": "customer_master_id", "is_primary": True},
                    {"name": "legal_name"},
                    {"name": "registration_number"},
                ]
            },
            "contact_master": {
                "columns": [
                    {"name": "contact_master_id", "is_primary": True},
                    {"name": "first_name"},
                    {"name": "last_name"},
                ]
            },
            "customer_branch": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "customer_master_id"},
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
                "table": "customer_branch",
                "column": "customer_master_id",
                "foreign_table": "customer_master",
                "foreign_column": "customer_master_id",
            },
            {
                "table": "customer_branch",
                "column": "address_master_id",
                "foreign_table": "address_master",
                "foreign_column": "address_master_id",
            },
        ]
    }


def test_find_best_join_condition_fk_direct(sample_schema):
    cond = find_best_join_condition("customer_master", "customer_branch", sample_schema)
    assert cond["is_fk"] is True
    assert cond["left_table"] == "customer_master"
    assert cond["left_col"] == "customer_master_id"
    assert cond["right_table"] == "customer_branch"
    assert cond["right_col"] == "customer_master_id"


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
    # Join from customer_master to address_master through customer_branch
    path = find_join_path(["customer_master"], "address_master", sample_schema)
    assert len(path) == 2
    assert path[0]["table"] == "customer_branch"
    assert path[1]["table"] == "address_master"


def test_find_join_path_already_active(sample_schema):
    path = find_join_path(["customer_master"], "customer_master", sample_schema)
    assert path == []
