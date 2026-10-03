"""
Tests for Query Template Persistence Store.
===========================================
Verifies template CRUD, search, categorization, multi-tenant isolation,
disk persistence, validation errors, and cross-tenant security invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from query_builder.security import SecurityError
from query_builder.templates import (
    QueryTemplate,
    TemplateStore,
    TemplateValidationError,
)


def test_template_save_and_get():
    store = TemplateStore()
    tmpl = store.save(
        {
            "title": "Monthly Active Users",
            "spec": {"table": "users", "columns": ["id"]},
            "category": "analytics",
        }
    )
    assert tmpl.id is not None
    assert tmpl.title == "Monthly Active Users"
    assert tmpl.created_at != ""
    assert tmpl.updated_at != ""

    fetched = store.get(tmpl.id)
    assert fetched is not None
    assert fetched.id == tmpl.id
    assert fetched.title == tmpl.title


def test_template_update_existing():
    store = TemplateStore()
    tmpl = store.save(
        {
            "id": "t100",
            "title": "Initial Title",
            "spec": {"table": "orders"},
        }
    )
    initial_created = tmpl.created_at

    # Update title
    updated = store.save(
        {
            "id": "t100",
            "title": "Updated Title",
            "spec": {"table": "orders", "limit": 10},
        }
    )
    assert updated.id == "t100"
    assert updated.title == "Updated Title"
    assert updated.created_at == initial_created
    assert updated.spec["limit"] == 10


def test_template_save_query_template_object():
    store = TemplateStore()
    obj = QueryTemplate(
        id="obj_1",
        title="From Object",
        spec={"table": "items"},
    )
    saved = store.save(obj)
    assert saved.id == "obj_1"
    assert saved.title == "From Object"


def test_template_validation_missing_title():
    store = TemplateStore()
    with pytest.raises(TemplateValidationError, match="title is required"):
        store.save({"title": "", "spec": {"table": "t"}})

    with pytest.raises(TemplateValidationError, match="title is required"):
        store.save({"spec": {"table": "t"}})


def test_template_validation_missing_spec():
    store = TemplateStore()
    with pytest.raises(TemplateValidationError, match="specification must be"):
        store.save({"title": "Valid", "spec": {}})

    with pytest.raises(TemplateValidationError, match="specification must be"):
        store.save({"title": "Valid", "spec": "not_a_dict"})


def test_template_validation_invalid_type():
    store = TemplateStore()
    with pytest.raises(TemplateValidationError, match="Unsupported template"):
        store.save("invalid_string")  # type: ignore


def test_template_list_filters():
    store = TemplateStore()
    store.save(
        {
            "id": "t1",
            "title": "Finance Summary",
            "spec": {"table": "f"},
            "category": "finance",
            "tenant_id": "orgA",
            "description": "Quarterly balance",
        }
    )
    store.save(
        {
            "id": "t2",
            "title": "Marketing Clicks",
            "spec": {"table": "m"},
            "category": "marketing",
            "tenant_id": "orgB",
            "description": "Ad performance",
        }
    )
    store.save(
        {
            "id": "t3",
            "title": "Public Metrics",
            "spec": {"table": "p"},
            "category": "general",
            "tenant_id": None,  # Public template
        }
    )

    # Filter by tenant
    res_a = store.list(tenant_id="orgA")
    ids_a = {t.id for t in res_a}
    assert "t1" in ids_a
    assert "t3" in ids_a  # public included
    assert "t2" not in ids_a

    # Filter by category
    res_cat = store.list(category="marketing")
    assert len(res_cat) == 1
    assert res_cat[0].id == "t2"

    # Search filter
    res_search = store.list(search="Quarterly")
    assert len(res_search) == 1
    assert res_search[0].id == "t1"

    # Non-matching search
    assert store.list(search="nonexistent_keyword") == []


def test_template_delete_success():
    store = TemplateStore()
    tmpl = store.save({"title": "To Delete", "spec": {"table": "t"}})
    assert store.delete(tmpl.id) is True
    assert store.get(tmpl.id) is None


def test_template_delete_not_found():
    store = TemplateStore()
    assert store.delete("missing_id") is False


def test_template_delete_cross_tenant_forbidden():
    store = TemplateStore()
    tmpl = store.save(
        {"title": "Tenant Locked", "spec": {"table": "t"}, "tenant_id": "orgA"}
    )
    with pytest.raises(SecurityError, match="cannot delete template of another"):
        store.delete(tmpl.id, tenant_id="orgB")


def test_template_disk_persistence(tmp_path: Path):
    file_path = tmp_path / "templates.json"
    store1 = TemplateStore(storage_path=file_path)
    store1.save(
        {
            "id": "disk_1",
            "title": "Persisted Query",
            "spec": {"table": "items"},
        }
    )
    assert file_path.exists()

    # Load from new store instance
    store2 = TemplateStore(storage_path=file_path)
    loaded = store2.get("disk_1")
    assert loaded is not None
    assert loaded.title == "Persisted Query"

    # Clear also updates disk
    store2.clear()
    assert len(store2.list()) == 0
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {}


def test_template_load_from_disk_list_format(tmp_path: Path):
    file_path = tmp_path / "list_templates.json"
    raw_list = [
        {"id": "l1", "title": "From List", "spec": {"table": "x"}},
        "not_a_dict",
    ]
    file_path.write_text(json.dumps(raw_list))

    store = TemplateStore(storage_path=file_path)
    assert store.get("l1") is not None


def test_template_load_from_disk_dict_with_non_dict_values(tmp_path: Path):
    file_path = tmp_path / "dict_templates.json"
    raw_dict = {
        "valid": {"id": "v1", "title": "Valid", "spec": {"table": "x"}},
        "invalid": "scalar_value",
    }
    file_path.write_text(json.dumps(raw_dict))

    store = TemplateStore(storage_path=file_path)
    assert store.get("v1") is not None


def test_template_load_and_save_no_storage_path():
    store = TemplateStore(storage_path=None)
    store._load_from_disk()
    store._save_to_disk()
    store.save({"title": "In Memory", "spec": {"table": "m"}})
    store.clear()
    assert len(store.list()) == 0


def test_template_delete_with_storage_path(tmp_path: Path):
    file_path = tmp_path / "del.json"
    store = TemplateStore(storage_path=file_path)
    tmpl = store.save({"id": "d1", "title": "Delete Me", "spec": {"table": "t"}})
    assert store.delete(tmpl.id) is True
    assert store.get(tmpl.id) is None
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {}


def test_template_load_from_disk_corrupt_file(tmp_path: Path):
    file_path = tmp_path / "corrupt.json"
    file_path.write_text("not_valid_json{")
    store = TemplateStore(storage_path=file_path)
    assert len(store.list()) == 0


def test_template_load_from_disk_scalar_json(tmp_path: Path):
    file_path = tmp_path / "scalar.json"
    file_path.write_text("12345")
    store = TemplateStore(storage_path=file_path)
    assert len(store.list()) == 0
