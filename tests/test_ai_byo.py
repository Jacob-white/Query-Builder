"""
Tests for Bring Your Own AI (BYO-AI) & Agent Tool Calling framework.
====================================================================
Covers:
- Tool definition generators (OpenAI, Anthropic, Gemini, LangChain, MCP)
- Universal tool execution (build_query, validate_and_compile_query, get_schema_catalog, explain_query)
- BringYourOwnAiProvider (callables, async, OpenAI, Anthropic, Gemini, LangChain, custom)
- SelfHealingQueryEngine (Dijkstra auto-joins, fuzzy column repairs, repair prompts)
- ask_ai() 1-liner and QueryBuilderAiAgent
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from query_builder.ai import (
    AiQueryResult,
    BringYourOwnAiProvider,
    QueryBuilderAiAgent,
    SelfHealingQueryEngine,
    ask_ai,
    execute_agent_tool_call,
    get_agent_tool_definitions,
)
from query_builder.nlq.models import NlqProviderError


SAMPLE_SCHEMA = {
    "tables": {
        "users": {
            "columns": {
                "id": {"data_type": "INTEGER", "primary_key": True},
                "username": {"data_type": "VARCHAR"},
                "email": {"data_type": "VARCHAR"},
                "status": {"data_type": "VARCHAR"},
            },
            "foreign_keys": [],
        },
        "orders": {
            "columns": {
                "id": {"data_type": "INTEGER", "primary_key": True},
                "user_id": {"data_type": "INTEGER"},
                "amount": {"data_type": "DECIMAL"},
                "status": {"data_type": "VARCHAR"},
            },
            "foreign_keys": [
                {"column": "user_id", "target_table": "users", "target_column": "id"}
            ],
        },
    }
}


# ==========================================
# 1. Agent Tools Generation & Execution
# ==========================================


def test_agent_tool_definitions_formats():
    """Verifies tool generation across all 5 major AI formats."""
    # OpenAI
    openai_tools = get_agent_tool_definitions("openai")
    assert len(openai_tools) == 4
    assert openai_tools[0]["type"] == "function"
    assert "build_query" in openai_tools[0]["function"]["name"]

    # Anthropic
    anthropic_tools = get_agent_tool_definitions("anthropic")
    assert len(anthropic_tools) == 4
    assert "input_schema" in anthropic_tools[0]

    # Gemini
    gemini_tools = get_agent_tool_definitions("gemini")
    assert len(gemini_tools) == 4
    assert "parameters" in gemini_tools[0]

    # LangChain
    langchain_tools = get_agent_tool_definitions("langchain")
    assert len(langchain_tools) == 4
    assert "args_schema" in langchain_tools[0]

    # MCP
    mcp_tools = get_agent_tool_definitions("mcp")
    assert len(mcp_tools) == 4
    assert "inputSchema" in mcp_tools[0]

    # Invalid
    with pytest.raises(ValueError, match="Unsupported agent tool format"):
        get_agent_tool_definitions("unsupported_format")


def test_execute_agent_tool_build_query():
    """Tests build_query tool execution with valid and missing intent."""
    # Valid
    res = execute_agent_tool_call(
        "build_query",
        {
            "intent": "Show all users with status active",
            "dialect": "postgres",
            "limit": 10,
        },
        schema=SAMPLE_SCHEMA,
    )
    assert res["success"] is True
    assert "sql" in res
    assert "SELECT" in res["sql"].upper()
    assert res["spec"]["limit"] == 10

    # String arguments JSON
    res_str = execute_agent_tool_call(
        "build_query",
        json.dumps({"intent": "Show users"}),
        schema=SAMPLE_SCHEMA,
    )
    assert res_str["success"] is True

    # Missing intent
    err = execute_agent_tool_call("build_query", {}, schema=SAMPLE_SCHEMA)
    assert err["success"] is False
    assert "Missing required argument 'intent'" in err["error"]


def test_execute_agent_tool_validate_and_compile():
    """Tests validate_and_compile_query tool with spec, SQL, and error cases."""
    # With spec
    valid_spec = {
        "table": "users",
        "columns": ["id", "username"],
        "joins": [],
        "filters": [],
        "filter_join": "AND",
        "having": [],
        "order_by": [],
        "limit": 5,
        "offset": None,
        "distinct": False,
        "vector_search": None,
        "hybrid_search": None,
    }
    res = execute_agent_tool_call(
        "validate_and_compile_query",
        {"spec": valid_spec, "dialect": "postgres"},
        schema=SAMPLE_SCHEMA,
    )
    assert res["success"] is True
    assert res["valid"] is True
    assert "SELECT" in res["sql"]

    # With SQL string
    sql_res = execute_agent_tool_call(
        "validate_and_compile_query",
        {
            "sql": "SELECT id, username FROM users WHERE status = 'active';",
            "dialect": "postgres",
        },
        schema=SAMPLE_SCHEMA,
    )
    assert sql_res["success"] is True
    assert sql_res["valid"] is True

    # Missing both spec and sql
    missing_res = execute_agent_tool_call("validate_and_compile_query", {})
    assert missing_res["success"] is False
    assert "Either 'spec'" in missing_res["error"]

    # Unparseable SQL (valid SELECT token but missing FROM/projections)
    unparse_res = execute_agent_tool_call(
        "validate_and_compile_query", {"sql": "SELECT;"}
    )
    assert unparse_res["success"] is False
    assert "Failed to parse SQL" in unparse_res["error"]

    # Invalid spec compilation failure
    sec_spec = dict(valid_spec)
    sec_spec["table"] = "users; DROP TABLE users"
    sec_res = execute_agent_tool_call("validate_and_compile_query", {"spec": sec_spec})
    assert sec_res["success"] is False
    assert "validation failed" in sec_res["error"]

    # Security violation (mutation statement)
    drop_res = execute_agent_tool_call(
        "validate_and_compile_query", {"sql": "DROP TABLE users;"}
    )
    assert drop_res["success"] is False
    assert "Security validation failed" in drop_res["error"]


def test_execute_agent_tool_get_schema_catalog():
    """Tests get_schema_catalog in markdown and json formats, with table filtering."""
    # Markdown
    md_res = execute_agent_tool_call(
        "get_schema_catalog", {"format": "markdown"}, schema=SAMPLE_SCHEMA
    )
    assert md_res["success"] is True
    assert "users" in md_res["catalog"]

    # Filtered markdown
    filtered_md = execute_agent_tool_call(
        "get_schema_catalog",
        {"format": "markdown", "tables": ["orders"]},
        schema=SAMPLE_SCHEMA,
    )
    assert "orders" in filtered_md["catalog"]
    assert "- Table `users`:" not in filtered_md["catalog"]

    # JSON format
    json_res = execute_agent_tool_call(
        "get_schema_catalog", {"format": "json"}, schema=SAMPLE_SCHEMA
    )
    assert json_res["success"] is True
    assert "tables" in json_res["schema"]


def test_execute_agent_tool_explain_and_unknown():
    """Tests explain_query tool and unknown tool handling."""
    # Explain with spec
    spec = {
        "table": "users",
        "columns": ["id", {"column": "username", "alias": "name"}],
        "joins": [
            {
                "type": "LEFT JOIN",
                "table": "orders",
                "left_col": "id",
                "right_col": "user_id",
            }
        ],
        "filters": [{"column": "status", "op": "=", "value": "active"}],
        "filter_join": "AND",
        "limit": 25,
    }
    exp_res = execute_agent_tool_call("explain_query", {"spec": spec})
    assert exp_res["success"] is True
    assert "users" in exp_res["summary"]
    assert exp_res["joins_count"] == 1
    assert exp_res["filters_count"] == 1

    # Explain with SQL
    exp_sql = execute_agent_tool_call(
        "explain_query", {"sql": "SELECT id FROM users LIMIT 10;"}
    )
    assert exp_sql["success"] is True
    assert exp_sql["limit"] == 10

    # Explain with empty
    exp_err = execute_agent_tool_call("explain_query", {})
    assert exp_err["success"] is False

    # Unknown tool
    unknown = execute_agent_tool_call("non_existent_tool", {})
    assert unknown["success"] is False
    assert "Unknown tool" in unknown["error"]

    # Security & Input Validation Hardening
    # 1. Non-string tool name
    bad_name = execute_agent_tool_call(12345, {})  # type: ignore[arg-type]
    assert bad_name["success"] is False
    assert "Tool name must be a string" in bad_name["error"]

    # 2. Malformed JSON string
    bad_json = execute_agent_tool_call("build_query", "{ not valid json")
    assert bad_json["success"] is False
    assert "Invalid JSON arguments" in bad_json["error"]

    # 3. Invalid arguments type (not str and not dict)
    bad_type = execute_agent_tool_call("build_query", 999)  # type: ignore[arg-type]
    assert bad_type["success"] is False
    assert "Arguments must be a valid JSON string or dictionary" in bad_type["error"]

    # 4. Non-integer limit fallback
    fallback_lim = execute_agent_tool_call(
        "build_query", {"intent": "users", "limit": "not_an_int"}
    )
    assert fallback_lim["success"] is True
    assert fallback_lim["spec"]["limit"] == 50


# ==========================================
# 2. BringYourOwnAiProvider
# ==========================================


def test_byo_provider_missing_ai():
    """Checks that BringYourOwnAiProvider raises error if no AI client is set."""
    provider = BringYourOwnAiProvider()
    with pytest.raises(NlqProviderError, match="No AI instance or callable"):
        provider.generate_ast("Show users")


def test_byo_provider_callable_sync_and_async():
    """Tests sync callable (2-arg and 1-arg) and async coroutine."""

    # 2-arg sync callable
    def my_ai_2(prompt, system_prompt):
        return json.dumps(
            {
                "table": "users",
                "columns": ["id", "username"],
                "joins": [],
                "filters": [],
                "filter_join": "AND",
                "having": [],
                "order_by": [],
                "limit": 10,
                "offset": None,
                "distinct": False,
                "vector_search": None,
                "hybrid_search": None,
            }
        )

    provider = BringYourOwnAiProvider(ai=my_ai_2)
    ast, tokens = provider.generate_ast("Show users", schema=SAMPLE_SCHEMA)
    assert ast["table"] == "users"

    # 1-arg sync callable
    def my_ai_1(full_prompt):
        return {
            "table": "orders",
            "columns": ["id", "amount"],
            "joins": [],
            "filters": [],
            "filter_join": "AND",
            "having": [],
            "order_by": [],
            "limit": 20,
            "offset": None,
            "distinct": False,
            "vector_search": None,
            "hybrid_search": None,
        }

    provider.set_ai(my_ai_1)
    ast_dict, _ = provider.generate_ast("Show orders")
    assert ast_dict["table"] == "orders"

    # Async coroutine callable
    async def async_ai(prompt, system_prompt):
        return "```json\n" + json.dumps({"table": "users", "columns": ["*"]}) + "\n```"

    provider.set_ai(async_ai)
    ast_async, _ = provider.generate_ast("Show all")
    assert ast_async["table"] == "users"


def test_byo_provider_client_adapters():
    """Tests mock OpenAI, Anthropic, Gemini, LangChain, and custom objects."""
    # Mock OpenAI
    mock_openai = MagicMock(spec=["chat"])
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({"table": "users", "columns": ["id"]})
    mock_res = MagicMock()
    mock_res.choices = [mock_choice]
    mock_res.usage.total_tokens = 120
    mock_openai.chat = MagicMock()
    mock_openai.chat.completions.create.return_value = mock_res

    prov_openai = BringYourOwnAiProvider(ai=mock_openai)
    ast, tok = prov_openai.generate_ast("users")
    assert ast["table"] == "users"
    assert tok == 120

    # Mock Anthropic
    mock_anthropic = MagicMock(spec=["messages"])
    mock_block = MagicMock()
    mock_block.text = json.dumps({"table": "orders", "columns": ["id"]})
    mock_anth_res = MagicMock()
    mock_anth_res.content = [mock_block]
    mock_anth_res.usage.input_tokens = 40
    mock_anth_res.usage.output_tokens = 20
    mock_anthropic.messages.create.return_value = mock_anth_res

    prov_anthropic = BringYourOwnAiProvider(ai=mock_anthropic)
    ast_anth, tok_anth = prov_anthropic.generate_ast("orders")
    assert ast_anth["table"] == "orders"
    assert tok_anth == 60

    # Mock Gemini (google.genai client.models.generate_content)
    mock_gemini = MagicMock(spec=["models"])
    mock_gem_res = MagicMock()
    mock_gem_res.text = json.dumps({"table": "users", "columns": ["email"]})
    mock_gem_res.usage_metadata.total_token_count = 85
    mock_gemini.models.generate_content.return_value = mock_gem_res

    prov_gemini = BringYourOwnAiProvider(ai=mock_gemini)
    ast_gem, tok_gem = prov_gemini.generate_ast("users email")
    assert ast_gem["table"] == "users"
    assert tok_gem == 85

    # Mock Gemini genai.GenerativeModel (model.generate_content)
    mock_model = MagicMock(spec=["generate_content"])
    mock_model.generate_content.return_value = MagicMock(
        text=json.dumps({"table": "users"})
    )
    prov_model = BringYourOwnAiProvider(ai=mock_model)
    ast_m, _ = prov_model.generate_ast("users")
    assert ast_m["table"] == "users"

    # Mock LangChain BaseChatModel (llm.invoke)
    mock_langchain = MagicMock(spec=["invoke"])
    mock_lc_res = MagicMock()
    mock_lc_res.content = json.dumps({"table": "orders", "columns": ["amount"]})
    mock_lc_res.response_metadata = {"token_usage": {"total_tokens": 42}}
    mock_langchain.invoke.return_value = mock_lc_res

    prov_lc = BringYourOwnAiProvider(ai=mock_langchain)
    ast_lc, tok_lc = prov_lc.generate_ast("orders")
    assert ast_lc["table"] == "orders"
    assert tok_lc == 42

    # Custom object with .generate()
    class CustomAiObj:
        def generate(self, prompt, system_prompt):
            return json.dumps({"table": "custom_data", "columns": ["*"]})

    prov_custom = BringYourOwnAiProvider(ai=CustomAiObj())
    ast_c, _ = prov_custom.generate_ast("test")
    assert ast_c["table"] == "custom_data"

    # Custom object with .call()
    class CallObj:
        def call(self, prompt, system_prompt):
            return {"table": "call_data", "columns": ["id"]}

    prov_call = BringYourOwnAiProvider(ai=CallObj())
    ast_call, _ = prov_call.generate_ast("test")
    assert ast_call["table"] == "call_data"

    # Unsupported object
    prov_err = BringYourOwnAiProvider(ai=12345)
    with pytest.raises(NlqProviderError, match="Unsupported AI client type"):
        prov_err.generate_ast("test")


def test_byo_provider_json_parsing_and_explain():
    """Tests JSON extraction from embedded text and query explanation."""

    # AI returns conversational text containing JSON
    def conversational_ai(prompt, system_prompt):
        return 'Sure, here is your query:\n\n```json\n{"table": "users", "columns": ["id"]}\n```\nHope that helps!'

    prov = BringYourOwnAiProvider(ai=conversational_ai)
    ast, _ = prov.generate_ast("get users")
    assert ast["table"] == "users"

    # AI returns unparseable text
    def bad_ai(prompt, system_prompt):
        return "Sorry, I cannot help with this."

    prov_bad = BringYourOwnAiProvider(ai=bad_ai)
    with pytest.raises(NlqProviderError, match="invalid non-JSON"):
        prov_bad.generate_ast("users")

    # Malformed JSON inside braces
    def malformed_braces(prompt, system_prompt):
        return "{not valid json at all}"

    prov_malformed = BringYourOwnAiProvider(ai=malformed_braces)
    with pytest.raises(NlqProviderError, match="unparseable JSON"):
        prov_malformed.generate_ast("users")

    # Explain query success
    def explain_ai(prompt, system_prompt):
        return "This query retrieves all users."

    prov_exp = BringYourOwnAiProvider(ai=explain_ai)
    exp = prov_exp.explain_query({"table": "users", "columns": ["id"]})
    assert exp["explanation"] == "This query retrieves all users."

    # Explain query fallback on error
    def failing_ai(prompt, system_prompt):
        raise RuntimeError("AI offline")

    prov_fail = BringYourOwnAiProvider(ai=failing_ai)
    exp_fb = prov_fail.explain_query({"table": "users", "columns": ["id", "username"]})
    assert "users" in exp_fb["explanation"]


# ==========================================
# 3. SelfHealingQueryEngine
# ==========================================


def test_self_healing_table_inference():
    """Tests inferring primary table when omitted by the AI."""
    healer = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)

    # Inferred from projection users.id
    spec1 = {"table": "", "columns": ["users.id", "users.email"]}
    h1, notes1 = healer.auto_heal(spec1)
    assert h1["table"] == "users"
    assert any("Inferred primary table 'users'" in n for n in notes1)

    # Inferred from filter tablePrefix
    spec2 = {
        "table": "",
        "columns": ["id"],
        "filters": [{"tablePrefix": "orders", "column": "amount"}],
    }
    h2, notes2 = healer.auto_heal(spec2)
    assert h2["table"] == "orders"

    # Inferred from filter dotted column
    spec3 = {
        "table": "",
        "columns": ["id"],
        "filters": [{"column": "users.status", "op": "=", "value": "active"}],
    }
    h3, notes3 = healer.auto_heal(spec3)
    assert h3["table"] == "users"

    # Fallback to first schema table
    spec4 = {"table": "", "columns": ["id"]}
    h4, _ = healer.auto_heal(spec4)
    assert h4["table"] in ["users", "orders"]


def test_self_healing_auto_joins_and_fuzzy_columns():
    """Tests autonomous Dijkstra join synthesis and fuzzy column typo repair."""
    healer = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)

    # Projections reference orders.amount, but primary table is users with no joins!
    broken_spec = {
        "table": "users",
        "columns": ["id", "username", "orders.amount"],
        "joins": [],
        "filters": [{"column": "orders.status", "op": "=", "value": "paid"}],
    }

    healed, notes = healer.auto_heal(broken_spec)
    assert len(healed["joins"]) >= 1
    assert healed["joins"][0]["table"] == "orders"
    assert any("Autonomous join" in n for n in notes)

    # Fuzzy column typo repair: 'usernam' -> 'username', 'e-mail'
    typo_spec = {
        "table": "users",
        "columns": ["usernam", {"column": "users.usernam"}],
        "joins": [],
    }
    healed_typo, typo_notes = healer.auto_heal(typo_spec)
    assert healed_typo["columns"][0] == "username"
    assert healed_typo["columns"][1]["column"] == "users.username"
    assert any("Fuzzy column healed" in n for n in typo_notes)


def test_self_healing_repair_prompt():
    """Tests generating 1-shot repair prompt for external LLMs."""
    healer = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    prompt = healer.generate_repair_prompt(
        {"table": "unknown"},
        errors=["Table 'unknown' does not exist in schema.", "Column 'amt' invalid."],
        original_prompt="Show revenue",
    )
    assert "Table 'unknown' does not exist" in prompt
    assert "Show revenue" in prompt


# ==========================================
# 4. ask_ai() & QueryBuilderAiAgent
# ==========================================


def test_ask_ai_with_callable_and_mock():
    """Tests high-level ask_ai() function."""

    def mock_ai(prompt, system_prompt):
        return json.dumps(
            {
                "table": "users",
                "columns": ["id", "username"],
                "joins": [],
                "filters": [{"column": "status", "op": "=", "value": "active"}],
                "filter_join": "AND",
                "having": [],
                "order_by": [{"column": "id", "direction": "DESC"}],
                "limit": 10,
            }
        )

    result = ask_ai(
        "Find active users", ai=mock_ai, schema=SAMPLE_SCHEMA, dialect="postgres"
    )
    assert isinstance(result, AiQueryResult)
    assert "SELECT" in result.sql
    assert result.spec["table"] == "users"
    assert result.query_spec.table == "users"

    # Re-compile to snowflake
    sf_sql = result.to_sql("snowflake")
    assert "SELECT" in sf_sql

    # to_dict
    d = result.to_dict()
    assert d["dialect"] == "postgres"

    # Fallback with ai=None
    res_default = ask_ai("Show users", ai=None, schema=SAMPLE_SCHEMA)
    assert res_default.spec["table"] == "users"


def test_query_builder_ai_agent():
    """Tests QueryBuilderAiAgent class methods."""
    agent = QueryBuilderAiAgent(
        schema=SAMPLE_SCHEMA,
        dialect="postgres",
        auto_heal=True,
    )

    # Ask
    res = agent.ask("Show all users")
    assert res.spec["table"] == "users"

    # As tool
    tools = agent.as_tool("openai")
    assert len(tools) == 4

    # Handle tool call
    tool_res = agent.handle_tool_call("build_query", {"intent": "Show users"})
    assert tool_res["success"] is True


def test_ai_byo_comprehensive_edge_branches():
    """Covers remaining edge branches for 100% test coverage."""
    import asyncio

    # 1. Spec compiling to SQL with restricted security schema
    restricted_spec = {
        "table": "information_schema.tables",
        "columns": ["*"],
        "joins": [],
        "filters": [],
        "filter_join": "AND",
        "having": [],
        "order_by": [],
        "limit": 10,
    }
    sec_res = execute_agent_tool_call(
        "validate_and_compile_query", {"spec": restricted_spec}
    )
    assert sec_res["success"] is False
    assert "Security validation failed" in sec_res["error"]

    # 2. Async coroutine executed while an existing event loop is active
    async def async_worker():
        async def inner_coro(prompt, system_prompt):
            return json.dumps({"table": "users", "columns": ["id"]})

        prov = BringYourOwnAiProvider(ai=inner_coro)
        ast, _ = prov.generate_ast("users")
        assert ast["table"] == "users"

    asyncio.run(async_worker())

    # 3. AI returning dict directly in generate_ast and explain_query
    def dict_ai(prompt, system_prompt):
        return {"table": "users", "columns": ["email"]}

    prov_dict = BringYourOwnAiProvider(ai=dict_ai)
    ast_d, _ = prov_dict.generate_ast("users")
    assert ast_d["table"] == "users"
    exp_d = prov_dict.explain_query({"table": "users"})
    assert exp_d["table"] == "users"

    # 4. SelfHealing with empty spec and empty schema (hits default 'data' table)
    healer_empty = SelfHealingQueryEngine(schema={})
    empty_spec = {"table": "", "columns": []}
    h_empty, notes_empty = healer_empty.auto_heal(empty_spec)
    assert h_empty["table"] == "data"

    # 4b. SelfHealing with existing joins and fallback join synthesis
    from unittest.mock import patch

    disconnected_spec = {
        "table": "users",
        "joins": [{"table": "pre_joined_table"}],
        "columns": ["id"],
        "order_by": [
            {"tablePrefix": "unconnected_table", "column": "col1"},
            {"column": "another_table.col2"},
        ],
    }
    with patch("query_builder.ai.self_healing.find_join_path", return_value=[]):
        h_disc, notes_disc = healer_empty.auto_heal(disconnected_spec)
        assert len(h_disc["joins"]) >= 3
        assert any("Autonomous join synthesis" in n for n in notes_disc)

    # 4c. SelfHealing compiler exception branch
    healer_err = SelfHealingQueryEngine(schema={})
    h_err, notes_err = healer_err.auto_heal({"table": "bad; table", "columns": ["*"]})
    assert any("Compiler pre-check notice" in n for n in notes_err)

    # 5. Table metadata column parsing as list of dicts, strings, and non-dict/str
    custom_schema = {
        "tables": {
            "products": {
                "columns": [
                    {"name": "id"},
                    {"name": "price"},
                    "description",
                    123,  # non-dict, non-str
                ],
            },
            "non_dict_table": "invalid_meta",
            "bad_cols": {"columns": 12345},
        },
    }
    healer_meta = SelfHealingQueryEngine(schema=custom_schema)
    res_meta, _ = healer_meta.auto_heal(
        {
            "table": "products",
            "columns": ["prce", "descriptin"],
        }
    )
    assert res_meta["columns"][0] == "price"
    assert res_meta["columns"][1] == "description"

    # 5b. Non-dict table and non-list/dict columns
    healer_meta.auto_heal({"table": "non_dict_table", "columns": ["col"]})
    healer_meta.auto_heal({"table": "bad_cols", "columns": ["col"]})

    # 5c. Security sanitizer alert
    with patch(
        "query_builder.ai.self_healing.validate_sql_ast",
        return_value={"valid": False, "violations": ["Blocked"]},
    ):
        _, sec_notes = healer_meta.auto_heal({"table": "products", "columns": ["id"]})
        assert any("Security sanitizer alert" in n for n in sec_notes)

    # 5b. Non-string response in generate_ast
    class IntRespAi:
        def __call__(self, p, s):
            return 12345

    prov_int = BringYourOwnAiProvider(ai=IntRespAi())
    with pytest.raises(NlqProviderError, match="invalid non-JSON"):
        prov_int.generate_ast("users")

    # 6. ask_ai with auto_heal triggering healing_notes in combined_warnings
    def ai_needing_healing(prompt, system_prompt):
        return json.dumps(
            {
                "table": "users",
                "columns": ["usernam"],  # typo will be healed
                "joins": [],
            }
        )

    healed_result = ask_ai("users", ai=ai_needing_healing, schema=SAMPLE_SCHEMA)
    assert len(healed_result.healing_notes) > 0
    assert any("Fuzzy column healed" in w for w in healed_result.warnings)


def test_byo_ai_branch_coverage_completion():
    # 1. agent_tools: explain_query with no limit (covers 405->408)
    res_no_lim = execute_agent_tool_call(
        "explain_query", {"spec": {"table": "users", "columns": ["id"]}}
    )
    assert "Limits results" not in res_no_lim["summary"]

    # 2. byo_provider:
    # 2a. OpenAI response with no usage (covers 83->85)
    class OpenAiNoUsageClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    msg = MagicMock()
                    msg.content = '{"table": "users"}'
                    choice = MagicMock()
                    choice.message = msg
                    res = MagicMock(spec=["choices"])
                    res.choices = [choice]
                    return res

    prov_no_usage = BringYourOwnAiProvider(ai=OpenAiNoUsageClient())
    ast, tok = prov_no_usage.generate_ast("users")
    assert tok is None

    # 2b. Anthropic block with no text attribute & no usage (covers 99->98 and 101->103)
    class AnthropicNoUsageClient:
        class messages:
            @staticmethod
            def create(*args, **kwargs):
                block1 = MagicMock(spec=[])  # no 'text' attr
                block2 = MagicMock()
                block2.text = '{"table": "users"}'
                res = MagicMock(spec=["content"])
                res.content = [block1, block2]
                return res

    prov_anth = BringYourOwnAiProvider(ai=AnthropicNoUsageClient())
    ast_anth, tok_anth = prov_anth.generate_ast("users")
    assert tok_anth is None
    assert ast_anth["table"] == "users"

    # 2c. Gemini client with no usage_metadata (covers 114->116)
    class GeminiNoUsageClient:
        class models:
            @staticmethod
            def generate_content(*args, **kwargs):
                res = MagicMock(spec=["text"])
                res.text = '{"table": "users"}'
                return res

    prov_gem = BringYourOwnAiProvider(ai=GeminiNoUsageClient())
    ast_gem, tok_gem = prov_gem.generate_ast("users")
    assert tok_gem is None

    # 2d. LangChain runnable with no response_metadata (covers 130->133)
    class LangChainNoMetaClient:
        @staticmethod
        def invoke(*args, **kwargs):
            res = MagicMock(spec=["content"])
            res.content = '{"table": "users"}'
            return res

    prov_lc = BringYourOwnAiProvider(ai=LangChainNoMetaClient())
    ast_lc, tok_lc = prov_lc.generate_ast("users")
    assert tok_lc is None

    # 2e. JSON regex match that parses to a list (not a dict) (covers 200->207)
    prov_list = BringYourOwnAiProvider(
        ai=lambda p, s: "Here is the result: [1, 2, 3] end"
    )
    with pytest.raises(NlqProviderError, match="invalid non-JSON"):
        prov_list.generate_ast("users")

    # 3. client.py: ask_ai with auto_heal=False (covers 100->105)
    res_no_heal = ask_ai(
        "users",
        ai=lambda p, s: '{"table": "users", "columns": ["id"]}',
        auto_heal=False,
    )
    assert len(res_no_heal.healing_notes) == 0

    # 4. self_healing.py branches:
    # 4a. Filter without prefix and without dot (covers 72->65)
    healer = SelfHealingQueryEngine(schema=SAMPLE_SCHEMA)
    h_f, _ = healer.auto_heal(
        {
            "columns": ["*"],
            "filters": [{"column": "status", "op": "=", "value": "active"}],
        }
    )
    assert h_f["table"] == "users"

    # 4b. Table already in active_tables in joins loop (covers 91->89)
    h_dup_join, _ = healer.auto_heal(
        {
            "table": "users",
            "joins": [
                {
                    "table": "users",
                    "type": "LEFT JOIN",
                    "left_col": "id",
                    "right_col": "id",
                },
                {
                    "table": "users",
                    "type": "LEFT JOIN",
                    "left_col": "id",
                    "right_col": "id",
                },
            ],
        }
    )
    assert h_dup_join["table"] == "users"

    # 4c. Dijkstra path where join_step table is already in active_tables (covers 130->129)
    with patch(
        "query_builder.ai.self_healing.find_join_path",
        return_value=[
            {"table": "users", "type": "LEFT JOIN", "left_col": "id", "right_col": "id"}
        ],
    ):
        h_dup_path, _ = healer.auto_heal(
            {"table": "users", "columns": ["orders.amount"]}
        )
        assert h_dup_path["table"] == "users"

    # 4d. schema_tables is not a dict (covers 158->193)
    healer_no_dict = SelfHealingQueryEngine(schema=["not", "a", "dict"])
    h_nd, _ = healer_no_dict.auto_heal({"table": "users", "columns": ["id"]})
    assert h_nd["table"] == "users"

    # 4e. Dict column with raw_expression and dict column with typo but NO close match (covers 166->173, 168->173)
    h_col, _ = healer.auto_heal(
        {
            "table": "users",
            "columns": [
                {"column": "id", "raw_expression": "COUNT(id)"},
                {"column": "zzzzzz_unmatchable"},
            ],
        }
    )
    assert len(h_col["columns"]) == 2

    # 4f. String column with typo but NO close match (covers 182->188)
    h_str, _ = healer.auto_heal(
        {"table": "users", "columns": ["zzzzzz_unmatchable_string"]}
    )
    assert h_str["columns"][0] == "zzzzzz_unmatchable_string"

    # 4g. byo_provider: non-dict returned from regex json parse (covers 200->207)
    with patch(
        "json.loads", side_effect=[json.JSONDecodeError("err", "doc", 0), "non_dict"]
    ):
        prov_non_dict = BringYourOwnAiProvider(ai=lambda p, s: "{ some match }")
        with pytest.raises(NlqProviderError, match="invalid non-JSON"):
            prov_non_dict.generate_ast("users")

    # 4h. self_healing: schema['tables'] is not a dict (covers 158->193)
    healer_list_tables = SelfHealingQueryEngine(schema={"tables": ["users", "orders"]})
    h_lt, _ = healer_list_tables.auto_heal({"table": "users", "columns": ["id"]})
    assert h_lt["table"] == "users"
