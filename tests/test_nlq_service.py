"""
Tests for NlqService facade and translation workflows.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from query_builder.models import QuerySpec
from query_builder.nlq.models import NlqTranslateRequest
from query_builder.nlq.service import NlqService


def test_nlq_service_translate_dict_request() -> None:
    svc = NlqService(default_provider="mock")
    schema = {
        "tables": {
            "users": {
                "columns": {
                    "id": {"data_type": "INT"},
                    "name": {"data_type": "TEXT"},
                    "status": {"data_type": "TEXT"},
                }
            }
        }
    }

    req_dict = {
        "prompt": "Find all active users",
        "schema": schema,
        "provider": "mock",
        "dialect": "postgres",
    }
    result = svc.translate(req_dict)
    assert result.spec["table"] == "users"
    assert result.confidence == 1.0
    assert result.provider == "mock"
    assert isinstance(result.query_spec, QuerySpec)
    assert len(result.warnings) == 0
    assert "users" in result.explanation


def test_nlq_service_translate_dataclass_request_with_warnings() -> None:
    svc = NlqService(default_provider="mock")
    schema = {"tables": {"orders": {}}}

    # Prompt targets non_existent_table which is not in schema -> produces warning
    req = NlqTranslateRequest(
        prompt="Find items from non_existent_table",
        schema=schema,
        provider="mock",
    )
    result = svc.translate(req)
    assert len(result.warnings) > 0
    assert result.confidence < 1.0


def test_nlq_service_explain() -> None:
    svc = NlqService(default_provider="mock")

    # 1. From dict
    exp1 = svc.explain({"table": "orders", "limit": 10})
    assert "orders" in exp1.summary
    assert len(exp1.steps) > 0
    assert exp1.provider == "mock"

    # 2. From QuerySpec instance
    qs = QuerySpec(table="customers", columns=["id", "name"])
    exp2 = svc.explain(qs)
    assert "customers" in exp2.summary

    # 3. From invalid object
    exp3 = svc.explain("not a valid query spec")  # type: ignore[arg-type]
    assert "unknown" in exp3.summary


def test_nlq_service_list_available_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = NlqService()

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    providers = svc.list_available_providers()
    prov_map = {p["name"]: p for p in providers}

    assert prov_map["mock"]["configured"] is True
    assert prov_map["ollama"]["configured"] is True
    assert prov_map["gemini"]["configured"] is False
    assert prov_map["openai"]["configured"] is True


def test_nlq_service_explain_empty_steps() -> None:
    svc = NlqService()
    with patch(
        "query_builder.nlq.providers.MockNlqProvider.explain_query",
        return_value={"summary": "sum", "explanation": "exp", "steps": []},
    ):
        res = svc.explain({"table": "users"})
        assert res.steps == ["exp"]
