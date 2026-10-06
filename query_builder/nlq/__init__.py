"""
Natural Language to Visual Query (NLQ) Engine for Query-Builder.
================================================================
Provides schema-grounded translation of plain English into QuerySpec ASTs,
multi-provider support (Gemini, OpenAI, Anthropic, Ollama, Mock), and bidirectional
natural language query explanation.
"""

from __future__ import annotations

from query_builder.nlq.models import (
    NlqError,
    NlqExplainResult,
    NlqProviderError,
    NlqResult,
    NlqTranslateRequest,
    NlqValidationError,
)
from query_builder.nlq.prompt import (
    build_explain_prompt,
    build_system_prompt,
    build_user_prompt,
    get_few_shot_exemplars,
    serialize_schema_for_prompt,
)
from query_builder.nlq.providers import (
    AnthropicProvider,
    GeminiProvider,
    MockNlqProvider,
    NlqProvider,
    OllamaProvider,
    OpenAiProvider,
    get_nlq_provider,
    list_nlq_providers,
    register_nlq_provider,
)
from query_builder.nlq.service import NlqService
from query_builder.nlq.validator import NlqAstValidator

__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "MockNlqProvider",
    "NlqAstValidator",
    "NlqError",
    "NlqExplainResult",
    "NlqProvider",
    "NlqProviderError",
    "NlqResult",
    "NlqService",
    "NlqTranslateRequest",
    "NlqValidationError",
    "OllamaProvider",
    "OpenAiProvider",
    "build_explain_prompt",
    "build_system_prompt",
    "build_user_prompt",
    "get_few_shot_exemplars",
    "get_nlq_provider",
    "list_nlq_providers",
    "register_nlq_provider",
    "serialize_schema_for_prompt",
]
