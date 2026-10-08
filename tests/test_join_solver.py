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
            },
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
        ],
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


def test_find_best_join_condition_reverse_fk(sample_schema):
    # Test reverse direction
    cond = find_best_join_condition("customer_branch", "customer_master", sample_schema)
    assert cond["is_fk"] is True
    assert cond["left_col"] == "customer_master_id"
    assert cond["right_col"] == "customer_master_id"


def test_find_best_join_condition_inferred_named_fk():
    schema = {
        "tables": {
            "author": {
                "columns": [{"name": "id", "is_primary": True}, {"name": "name"}]
            },
            "book": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "author_id"},
                    {"name": "title"},
                ]
            },
        }
    }
    # Direct
    cond = find_best_join_condition("author", "book", schema)
    assert cond["is_fk"] is True
    assert cond["left_col"] == "id"
    assert cond["right_col"] == "author_id"

    # Reverse
    cond_rev = find_best_join_condition("book", "author", schema)
    assert cond_rev["is_fk"] is True
    assert cond_rev["left_col"] == "author_id"
    assert cond_rev["right_col"] == "id"


def test_find_best_join_condition_pk_fallback():
    schema = {
        "tables": {
            "alpha": {
                "columns": [{"name": "uuid", "is_primary": True}, {"name": "content"}]
            },
            "beta": {
                "columns": [{"name": "beta_pk", "is_primary": True}, {"name": "data"}]
            },
        }
    }
    cond = find_best_join_condition("alpha", "beta", schema)
    assert cond["is_fk"] is False
    assert cond["left_col"] == "uuid"
    assert cond["right_col"] == "beta_pk"


def test_find_join_path_empty_active():
    assert find_join_path([], "target") == []


def test_find_join_path_disconnected_fallback():
    schema = {
        "tables": {
            "island_a": {"columns": [{"name": "id", "is_primary": True}]},
            "island_b": {"columns": [{"name": "id", "is_primary": True}]},
        }
    }
    path = find_join_path(["island_a"], "island_b", schema)
    assert len(path) == 1
    assert path[0]["left_table"] == "island_a"
    assert path[0]["table"] == "island_b"


def test_find_join_path_already_active(sample_schema):
    path = find_join_path(["customer_master"], "customer_master", sample_schema)
    assert path == []


def test_clean_table_name_multipart():
    from query_builder.join_solver import _clean_table_name

    assert _clean_table_name("analytics.public.orders") == "orders"
    assert _clean_table_name("cluster.db.schema.users") == "users"
    assert _clean_table_name("production.customer_master") == "customer_master"
    assert _clean_table_name("customer_master") == "customer_master"
    assert _clean_table_name("") == ""
    assert _clean_table_name(None) == ""


def test_find_best_join_condition_multipart_schema(sample_schema):
    cond = find_best_join_condition(
        "analytics.public.customer_master", "db.public.customer_branch", sample_schema
    )
    assert cond["is_fk"] is True
    assert cond["left_table"] == "customer_master"
    assert cond["left_col"] == "customer_master_id"
    assert cond["right_col"] == "customer_master_id"
