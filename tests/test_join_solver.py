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


def test_join_solver_custom_canonical_columns():
    from query_builder.models import SchemaSnapshot, TableMeta

    schema_dict = {
        "tables": {
            "orders": {"columns": [{"name": "org_uuid"}, {"name": "amount"}]},
            "invoices": {"columns": [{"name": "org_uuid"}, {"name": "total"}]},
        },
        "canonical_columns": ["org_uuid"],
    }
    # 1. Via dict canonical_columns
    cond1 = find_best_join_condition("orders", "invoices", schema_dict)
    assert cond1["left_col"] == "org_uuid"
    assert cond1["right_col"] == "org_uuid"
    assert cond1["is_fk"] is False
    path1 = find_join_path(["orders"], "invoices", schema_dict)
    assert len(path1) == 1
    assert path1[0]["left_col"] == "org_uuid"
    assert path1[0]["right_col"] == "org_uuid"

    raw_schema = {
        "tables": {
            "orders": {"columns": [{"name": "org_uuid"}, {"name": "amount"}]},
            "invoices": {"columns": [{"name": "org_uuid"}, {"name": "total"}]},
        },
    }
    cond2 = find_best_join_condition(
        "orders", "invoices", raw_schema, canonical_columns=["org_uuid"]
    )
    assert cond2["left_col"] == "org_uuid"
    path2 = find_join_path(
        ["orders"], "invoices", raw_schema, canonical_columns=["org_uuid"]
    )
    assert len(path2) == 1
    assert path2[0]["left_col"] == "org_uuid"

    # 3. Via SchemaSnapshot.canonical_columns
    snapshot = SchemaSnapshot(
        tables={
            "orders": TableMeta(
                name="orders", columns=[{"name": "org_uuid"}, {"name": "amount"}]
            ),
            "invoices": TableMeta(
                name="invoices", columns=[{"name": "org_uuid"}, {"name": "total"}]
            ),
        },
        canonical_columns=["org_uuid"],
    )
    cond3 = find_best_join_condition("orders", "invoices", snapshot)
    assert cond3["left_col"] == "org_uuid"
    path3 = find_join_path(["orders"], "invoices", snapshot)
    assert len(path3) == 1


def test_join_solver_plural_entity_bridges_and_relationships():
    schema = {
        "tables": {
            "users": {"columns": [{"name": "id", "is_primary": True}]},
            "orders": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "user_id"},
                ]
            },
            "order_items": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "order_id"},
                    {"name": "product_id"},
                ]
            },
            "products": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "category_id"},
                ]
            },
            "categories": {"columns": [{"name": "id", "is_primary": True}]},
        },
        "relationships": [
            {
                "source_table": "products",
                "source_column": "category_id",
                "target_table": "categories",
                "target_column": "id",
            }
        ],
    }
    path = find_join_path(["users"], "categories", schema)
    assert [step["table"] for step in path] == [
        "orders",
        "order_items",
        "products",
        "categories",
    ]

    # Direct & reverse find_best_join_condition via relationships
    cond_rel = find_best_join_condition("products", "categories", schema)
    assert cond_rel["is_fk"] is True
    assert cond_rel["left_col"] == "category_id"
    assert cond_rel["right_col"] == "id"

    cond_rel_rev = find_best_join_condition("categories", "products", schema)
    assert cond_rel_rev["is_fk"] is True
    assert cond_rel_rev["left_col"] == "id"
    assert cond_rel_rev["right_col"] == "category_id"


def test_find_join_path_prioritizes_confirmed_fk_over_inferred():
    schema = {
        "tables": {
            "a": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "b_inferred_id"},
                    {"name": "b_confirmed_id"},
                ]
            },
            "b_inferred": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "c_id"},
                ]
            },
            "b_confirmed": {
                "columns": [
                    {"name": "id", "is_primary": True},
                    {"name": "c_id"},
                ]
            },
            "c": {"columns": [{"name": "id", "is_primary": True}]},
        },
        "foreign_keys": [
            {
                "table": "a",
                "column": "b_confirmed_id",
                "foreign_table": "b_confirmed",
                "foreign_column": "id",
            },
            {
                "table": "b_confirmed",
                "column": "c_id",
                "foreign_table": "c",
                "foreign_column": "id",
            },
        ],
    }
    path = find_join_path(["a"], "c", schema)
    assert [step["table"] for step in path] == ["b_confirmed", "c"]


def test_build_adjacency_graph_add_edge():
    from query_builder.join_solver import _build_adjacency_graph

    foreign_keys = [
        {"table": "a", "foreign_table": "b"},
        {"table": "b", "foreign_table": "c"},
        # Duplicate edge to test that it is not added multiple times
        {"table": "a", "foreign_table": "b"},
    ]

    adj = _build_adjacency_graph(foreign_keys, [], {}, [])

    # Check that bidirectional edges are properly created
    assert "b" in adj["a"]
    assert "a" in adj["b"]
    assert "c" in adj["b"]
    assert "b" in adj["c"]

    # Check that duplicates are prevented
    assert adj["a"].count("b") == 1
    assert adj["b"].count("a") == 1
