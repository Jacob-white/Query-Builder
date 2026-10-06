"""
Tests for all NLQ providers (Mock, Gemini, OpenAI, Anthropic, Ollama) and registry.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from query_builder.nlq.models import NlqProviderError
from query_builder.nlq.providers import (
    AnthropicProvider,
    GeminiProvider,
    MockNlqProvider,
    NlqProvider,
    OllamaProvider,
    OpenAiProvider,
    _strip_markdown_code_blocks,
    get_nlq_provider,
    list_nlq_providers,
    register_nlq_provider,
)


def test_strip_markdown_code_blocks() -> None:
    raw1 = "```json\n{\"table\": \"users\"}\n```"
    assert _strip_markdown_code_blocks(raw1) == '{"table": "users"}'

    raw2 = "```\n{\"table\": \"orders\"}\n```"
    assert _strip_markdown_code_blocks(raw2) == '{"table": "orders"}'

    raw3 = '{"table": "items"}'
    assert _strip_markdown_code_blocks(raw3) == '{"table": "items"}'


def test_mock_nlq_provider_rich_intents() -> None:
    prov = MockNlqProvider()
    schema = {"tables": {"customers": {}, "orders": {}}}

    # 1. Matching table from schema + count
    ast, tokens = prov.generate_ast("count customers", schema=schema)
    assert ast["table"] == "customers"
    assert ast["columns"] == [{"column": "id", "agg": "COUNT", "alias": "total_count"}]
    assert tokens == 42

    # 2. Sum and Average
    ast_sum, _ = prov.generate_ast("sum orders")
    assert ast_sum["columns"] == [{"column": "amount", "agg": "SUM", "alias": "total_amount"}]

    ast_avg, _ = prov.generate_ast("average score in products")
    assert ast_avg["columns"] == [{"column": "score", "agg": "AVG", "alias": "avg_score"}]

    # 3. Specific columns + left join + filters + order by + limit + distinct + vector
    prompt = (
        "select name, email from users left join orders on user_id "
        "where status = active and amount > 50 and score < 100 and pending "
        "order by created_at desc limit 20 distinct vector search"
    )
    ast_rich, _ = prov.generate_ast(prompt)
    assert ast_rich["table"] == "users"
    assert ast_rich["columns"] == ["name", "email"]
    assert len(ast_rich["joins"]) == 1
    assert ast_rich["joins"][0]["type"] == "LEFT"
    assert ast_rich["joins"][0]["table"] == "orders"
    assert len(ast_rich["filters"]) >= 4
    assert ast_rich["order_by"] == [{"column": "created_at", "direction": "DESC"}]
    assert ast_rich["limit"] == 20
    assert ast_rich["distinct"] is True
    assert ast_rich["vector_search"] is not None

    # 4. Filter join "OR" and table regex fallback
    ast_or, _ = prov.generate_ast("find users where status = active or amount greater than 10")
    assert ast_or["filter_join"] == "OR"

    # 5. Explain query
    explain = prov.explain_query(ast_rich, dialect="postgres")
    assert "users" in explain["summary"]
    assert len(explain["steps"]) >= 4


def test_gemini_provider() -> None:
    prov = GeminiProvider(api_key=None)
    with pytest.raises(NlqProviderError, match="GEMINI_API_KEY not configured"):
        prov.generate_ast("test")
    with pytest.raises(NlqProviderError, match="GEMINI_API_KEY not configured"):
        prov.explain_query({"table": "users"})

    prov = GeminiProvider(api_key="test_key")

    # Success AST generation
    fake_resp = {
        "candidates": [{"content": {"parts": [{"text": '{"table": "accounts"}'}]}}],
        "usageMetadata": {"totalTokenCount": 99},
    }
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = io.BytesIO(json.dumps(fake_resp).encode("utf-8"))

    with patch("urllib.request.urlopen", return_value=mock_cm):
        ast, tokens = prov.generate_ast("Get accounts")
        assert ast == {"table": "accounts"}
        assert tokens == 99

    # Empty candidates error
    mock_empty = MagicMock()
    mock_empty.__enter__.return_value = io.BytesIO(json.dumps({"candidates": []}).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_empty):
        with pytest.raises(NlqProviderError, match="empty candidates"):
            prov.generate_ast("Get accounts")

    # Malformed JSON in response text
    mock_bad_json = MagicMock()
    mock_bad_json.__enter__.return_value = io.BytesIO(json.dumps({
        "candidates": [{"content": {"parts": [{"text": "not valid json"}]}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_bad_json):
        with pytest.raises(NlqProviderError, match="Failed to parse Gemini JSON output"):
            prov.generate_ast("Get accounts")

    # HTTPError
    err = urllib.error.HTTPError("http://test", 401, "Unauthorized", {}, io.BytesIO(b"bad auth"))  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(NlqProviderError, match="Gemini HTTP 401 error"):
            prov.generate_ast("Get accounts")

    # Explain query success & fail
    mock_explain = MagicMock()
    mock_explain.__enter__.return_value = io.BytesIO(json.dumps({
        "candidates": [{"content": {"parts": [{"text": '{"summary": "Explanation"}'}]}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain):
        exp = prov.explain_query({"table": "users"})
        assert exp["summary"] == "Explanation"

    mock_explain_bad = MagicMock()
    mock_explain_bad.__enter__.return_value = io.BytesIO(json.dumps({
        "candidates": [{"content": {"parts": [{"text": "not json"}]}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain_bad):
        with pytest.raises(NlqProviderError, match="Failed to parse Gemini explain JSON"):
            prov.explain_query({"table": "users"})


def test_openai_provider() -> None:
    prov = OpenAiProvider(api_key=None)
    with pytest.raises(NlqProviderError, match="OPENAI_API_KEY not configured"):
        prov.generate_ast("test")
    with pytest.raises(NlqProviderError, match="OPENAI_API_KEY not configured"):
        prov.explain_query({"table": "users"})

    prov = OpenAiProvider(api_key="test_key")

    # Success AST generation
    fake_resp = {
        "choices": [{"message": {"content": '{"table": "invoices"}'}}],
        "usage": {"total_tokens": 150},
    }
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = io.BytesIO(json.dumps(fake_resp).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_cm):
        ast, tokens = prov.generate_ast("Get invoices")
        assert ast == {"table": "invoices"}
        assert tokens == 150

    # No choices error
    mock_empty = MagicMock()
    mock_empty.__enter__.return_value = io.BytesIO(json.dumps({"choices": []}).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_empty):
        with pytest.raises(NlqProviderError, match="OpenAI returned no choices"):
            prov.generate_ast("Get invoices")

    # HTTPError
    err = urllib.error.HTTPError("http://test", 429, "Rate Limited", {}, io.BytesIO(b"rate limit"))  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(NlqProviderError, match="OpenAI HTTP 429 error"):
            prov.generate_ast("Get invoices")

    # Explain query success & fail
    mock_explain = MagicMock()
    mock_explain.__enter__.return_value = io.BytesIO(json.dumps({
        "choices": [{"message": {"content": '{"summary": "OpenAI summary"}'}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain):
        exp = prov.explain_query({"table": "invoices"})
        assert exp["summary"] == "OpenAI summary"

    mock_explain_bad = MagicMock()
    mock_explain_bad.__enter__.return_value = io.BytesIO(json.dumps({
        "choices": [{"message": {"content": "not json"}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain_bad):
        with pytest.raises(NlqProviderError, match="Failed to parse OpenAI explain JSON"):
            prov.explain_query({"table": "invoices"})


def test_anthropic_provider() -> None:
    prov = AnthropicProvider(api_key=None)
    with pytest.raises(NlqProviderError, match="ANTHROPIC_API_KEY not configured"):
        prov.generate_ast("test")
    with pytest.raises(NlqProviderError, match="ANTHROPIC_API_KEY not configured"):
        prov.explain_query({"table": "users"})

    prov = AnthropicProvider(api_key="test_key")

    fake_resp = {
        "content": [{"type": "text", "text": '{"table": "members"}'}],
        "usage": {"input_tokens": 50, "output_tokens": 25},
    }
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = io.BytesIO(json.dumps(fake_resp).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_cm):
        ast, tokens = prov.generate_ast("Get members")
        assert ast == {"table": "members"}
        assert tokens == 75

    # HTTPError
    err = urllib.error.HTTPError("http://test", 500, "Server Error", {}, io.BytesIO(b"anthropic error"))  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(NlqProviderError, match="Anthropic HTTP 500 error"):
            prov.generate_ast("Get members")

    # Explain query success & fail
    mock_explain = MagicMock()
    mock_explain.__enter__.return_value = io.BytesIO(json.dumps({
        "content": [{"type": "text", "text": '{"summary": "Claude summary"}'}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain):
        exp = prov.explain_query({"table": "members"})
        assert exp["summary"] == "Claude summary"

    mock_explain_bad = MagicMock()
    mock_explain_bad.__enter__.return_value = io.BytesIO(json.dumps({
        "content": [{"type": "text", "text": "not json"}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain_bad):
        with pytest.raises(NlqProviderError, match="Failed to parse Anthropic explain JSON"):
            prov.explain_query({"table": "members"})


def test_ollama_provider() -> None:
    prov = OllamaProvider()

    fake_resp = {
        "response": '{"table": "devices"}',
        "eval_count": 30,
        "prompt_eval_count": 70,
    }
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = io.BytesIO(json.dumps(fake_resp).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_cm):
        ast, tokens = prov.generate_ast("Get devices")
        assert ast == {"table": "devices"}
        assert tokens == 100

    # HTTPError
    err = urllib.error.HTTPError("http://test", 503, "Unavailable", {}, io.BytesIO(b"ollama down"))  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(NlqProviderError, match="Ollama HTTP 503 error"):
            prov.generate_ast("Get devices")

    # Explain query success & fail
    mock_explain = MagicMock()
    mock_explain.__enter__.return_value = io.BytesIO(json.dumps({
        "response": '{"summary": "Ollama summary"}'
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain):
        exp = prov.explain_query({"table": "devices"})
        assert exp["summary"] == "Ollama summary"

    mock_explain_bad = MagicMock()
    mock_explain_bad.__enter__.return_value = io.BytesIO(json.dumps({
        "response": "not json"
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_explain_bad):
        with pytest.raises(NlqProviderError, match="Failed to parse Ollama explain JSON"):
            prov.explain_query({"table": "devices"})


def test_provider_registry() -> None:
    assert "mock" in list_nlq_providers()
    assert "gemini" in list_nlq_providers()
    assert "openai" in list_nlq_providers()
    assert "anthropic" in list_nlq_providers()
    assert "ollama" in list_nlq_providers()

    p = get_nlq_provider("mock")
    assert isinstance(p, MockNlqProvider)

    with pytest.raises(NlqProviderError, match="Unknown NLQ provider 'invalid_prov'"):
        get_nlq_provider("invalid_prov")

    # Custom provider registration
    class CustomProvider(NlqProvider):
        name = "custom"

        def generate_ast(self, prompt: str, **kwargs: Any) -> tuple[dict[str, Any], int | None]:
            return {"table": "custom_tbl"}, 1

        def explain_query(self, query_dict: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            return {"summary": "custom"}

    register_nlq_provider("custom", CustomProvider)
    assert "custom" in list_nlq_providers()
    c_inst = get_nlq_provider("custom")
    assert isinstance(c_inst, CustomProvider)


def test_mock_nlq_provider_remaining_branches() -> None:
    prov = MockNlqProvider()
    schema = {"tables": {"inventory": {}}}

    # 1. No schema table matches prompt, no regex table match, but schema_tables has tables -> falls back to schema_tables[0]
    ast, _ = prov.generate_ast("show details", schema=schema)
    assert ast["table"] == "inventory"

    # 2. "select all from users" -> raw_cols_str == "all" -> columns fallback to ["*"]
    ast_all, _ = prov.generate_ast("select all from users")
    assert ast_all["columns"] == ["*"]

    # 3. status = active where eq_match.group(1) == "status"
    ast_status, _ = prov.generate_ast("select name from users where status = active")
    assert any(f["column"] == "status" for f in ast_status["filters"])

    # 4. Non-status eq filter (e.g. category = books) to hit line 159
    ast_cat, _ = prov.generate_ast("select id from products where category = books")
    assert any(f["column"] == "category" and f["value"] == "books" for f in ast_cat["filters"])

    # 5. Empty schema tables dict so loop at line 95 has empty iterable
    ast_empty, _ = prov.generate_ast("select name", schema={"tables": {}})
    assert ast_empty["table"] == "users"


def test_provider_network_and_malformed_json_exceptions() -> None:
    # 1. Gemini non-dict root object
    g_prov = GeminiProvider(api_key="test_key")
    mock_list_resp = MagicMock()
    mock_list_resp.__enter__.return_value = io.BytesIO(json.dumps({
        "candidates": [{"content": {"parts": [{"text": "[1, 2, 3]"}]}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_list_resp):
        with pytest.raises(NlqProviderError, match="Response root is not a JSON object"):
            g_prov.generate_ast("Get accounts")

    # 2. Gemini generic network error
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        with pytest.raises(NlqProviderError, match="Gemini request failed"):
            g_prov.generate_ast("Get accounts")

    # 3. OpenAI malformed JSON and generic network error
    o_prov = OpenAiProvider(api_key="test_key")
    mock_bad_openai = MagicMock()
    mock_bad_openai.__enter__.return_value = io.BytesIO(json.dumps({
        "choices": [{"message": {"content": "not json"}}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_bad_openai):
        with pytest.raises(NlqProviderError, match="Failed to parse OpenAI JSON output"):
            o_prov.generate_ast("Get invoices")

    with patch("urllib.request.urlopen", side_effect=OSError("network reset")):
        with pytest.raises(NlqProviderError, match="OpenAI request failed"):
            o_prov.generate_ast("Get invoices")

    # 4. Anthropic malformed JSON and generic network error
    a_prov = AnthropicProvider(api_key="test_key")
    mock_bad_anthropic = MagicMock()
    mock_bad_anthropic.__enter__.return_value = io.BytesIO(json.dumps({
        "content": [{"type": "text", "text": "not json"}]
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_bad_anthropic):
        with pytest.raises(NlqProviderError, match="Failed to parse Anthropic JSON output"):
            a_prov.generate_ast("Get members")

    with patch("urllib.request.urlopen", side_effect=OSError("ssl handshake error")):
        with pytest.raises(NlqProviderError, match="Anthropic request failed"):
            a_prov.generate_ast("Get members")

    # 5. Ollama malformed JSON and generic network error
    ol_prov = OllamaProvider()
    mock_bad_ollama = MagicMock()
    mock_bad_ollama.__enter__.return_value = io.BytesIO(json.dumps({
        "response": "not json"
    }).encode("utf-8"))
    with patch("urllib.request.urlopen", return_value=mock_bad_ollama):
        with pytest.raises(NlqProviderError, match="Failed to parse Ollama JSON output"):
            ol_prov.generate_ast("Get devices")

    with patch("urllib.request.urlopen", side_effect=OSError("timeout connecting to localhost")):
        with pytest.raises(NlqProviderError, match="Ollama request failed"):
            ol_prov.generate_ast("Get devices")


def test_mock_nlq_provider_multi_table_filter() -> None:
    prov = MockNlqProvider()
    # First table 'alpha' does not match, second table 'beta' matches
    schema = {"tables": {"alpha": {}, "beta": {}}}
    ast, _ = prov.generate_ast("select id from beta", schema=schema)
    assert ast["table"] == "beta"


def test_mock_nlq_provider_non_dict_raw_tables() -> None:
    prov = MockNlqProvider()
    # schema is not None, but tables is not a dict -> line 95 is False
    ast, _ = prov.generate_ast("select id from users", schema={"tables": "not_a_dict"})
    assert ast["table"] == "users"


def test_mock_nlq_provider_explain_without_order_by() -> None:
    prov = MockNlqProvider()
    query_dict = {
        "table": "users",
        "columns": ["id", "email"],
        "filters": [],
        "order_by": [],  # Empty order_by branch
        "limit": 10,
    }
    res = prov.explain_query(query_dict)
    assert res["summary"].startswith("Queries users")
    assert any("Limit query output to 10 rows." in step for step in res["steps"])


def test_nlq_provider_security_scheme_and_ssrf() -> None:
    # 1. Reject invalid URL scheme (e.g. file://, ftp://)
    o_prov = OpenAiProvider(api_key="sk-test", base_url="file:///etc/passwd")
    with pytest.raises(NlqProviderError, match="Forbidden URL scheme 'file'"):
        o_prov.generate_ast("test query")

    # 2. Reject cloud metadata SSRF on external providers
    g_prov = GeminiProvider(api_key="test_key")
    with pytest.raises(NlqProviderError, match="Security validation blocked network request"):
        g_prov._execute_http("http://169.254.169.254/latest/meta-data/", {})

    # 3. Reject cloud metadata SSRF on Ollama even though allow_private_networks is True
    ol_prov = OllamaProvider(base_url="http://169.254.169.254")
    with pytest.raises(NlqProviderError, match="Security validation blocked network request"):
        ol_prov.generate_ast("test query")

    # 4. Reject private network SSRF on AnthropicProvider
    a_prov = AnthropicProvider(api_key="test_key", base_url="http://192.168.1.100")
    with pytest.raises(NlqProviderError, match="Security validation blocked network request"):
        a_prov.generate_ast("test query")

