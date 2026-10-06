"""
Bring Your Own AI (BYO-AI) & Agentic Tool Calling Framework.
============================================================
Exposes tool definitions, universal execution adapters, self-healing query engines,
and client interfaces for external programs, LLMs, and agentic pipelines.
"""

from __future__ import annotations

from query_builder.ai.agent_tools import (
    execute_agent_tool_call,
    get_agent_tool_definitions,
)
from query_builder.ai.byo_provider import BringYourOwnAiProvider
from query_builder.ai.client import AiQueryResult, QueryBuilderAiAgent, ask_ai
from query_builder.ai.self_healing import SelfHealingQueryEngine

__all__ = [
    "AiQueryResult",
    "BringYourOwnAiProvider",
    "QueryBuilderAiAgent",
    "SelfHealingQueryEngine",
    "ask_ai",
    "execute_agent_tool_call",
    "get_agent_tool_definitions",
]
