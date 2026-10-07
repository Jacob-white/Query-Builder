"""
High-Level Client API and Autonomous AI Agent for Query-Builder.
================================================================
Provides the `ask_ai(...)` 1-liner and the `QueryBuilderAiAgent` class for programs
and developers to integrate their AI seamlessly with Query-Builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from query_builder.ai.agent_tools import (
    execute_agent_tool_call,
    get_agent_tool_definitions,
)
from query_builder.ai.byo_provider import BringYourOwnAiProvider
from query_builder.ai.self_healing import SelfHealingQueryEngine
from query_builder.compiler import QueryCompiler
from query_builder.models import (
    FilterSpec,
    HavingSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
)
from query_builder.nlq.service import NlqService


@dataclass
class AiQueryResult:
    """The result returned from an AI query generation."""

    sql: str
    spec: dict[str, Any]
    query_spec: QuerySpec
    explanation: str
    confidence: float
    warnings: list[str] = field(default_factory=list)
    healing_notes: list[str] = field(default_factory=list)
    tokens_used: int | None = None
    dialect: str = "postgres"
    schema: dict[str, Any] | None = None

    def to_sql(self, dialect: str | None = None) -> str:
        """Re-compiles the query into another SQL dialect."""
        target_dialect = dialect or self.dialect
        compiler = QueryCompiler(self.spec, schema=self.schema, dialect=target_dialect)
        return compiler.compile()[0]

    def to_dict(self) -> dict[str, Any]:
        """Converts the result to a serializable dictionary."""
        return {
            "sql": self.sql,
            "spec": self.spec,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "healing_notes": self.healing_notes,
            "tokens_used": self.tokens_used,
            "dialect": self.dialect,
        }


def ask_ai(
    prompt: str,
    ai: Any = None,
    schema: dict[str, Any] | None = None,
    dialect: str = "postgres",
    auto_heal: bool = True,
    options: dict[str, Any] | None = None,
) -> AiQueryResult:
    """
    Translates a plain-English request into verified SQL and QuerySpec AST using any supplied AI.

    Parameters:
        prompt: User's query intent in plain English.
        ai: The external AI instance (OpenAI/Anthropic/Gemini/LangChain client or Python callable).
            If omitted, uses local mock or default configured provider.
        schema: Database schema definition dictionary.
        dialect: Target SQL dialect (e.g. 'postgres', 'snowflake', 'bigquery', 'mysql', 'sqlite', 'duckdb').
        auto_heal: Whether to run Dijkstra relational auto-joining and fuzzy column correction.
        options: Additional parameters (e.g. limit, model, temperature).
    """
    opts = options or {}
    provider_name = "byo" if ai is not None else "mock"

    byo_provider = BringYourOwnAiProvider(ai=ai) if ai is not None else None

    # Translate using NLQ service
    service = NlqService(default_provider=provider_name)
    if byo_provider is not None:
        service.translate = lambda req: _translate_with_byo(
            req, byo_provider, schema, dialect
        )  # type: ignore

    res = service.translate(
        {
            "prompt": prompt,
            "schema": schema,
            "provider": provider_name,
            "dialect": dialect,
            "options": opts,
        }
    )

    raw_spec = dict(res.spec)
    healing_notes: list[str] = []

    if auto_heal:
        healer = SelfHealingQueryEngine(schema=schema)
        raw_spec, healing_notes = healer.auto_heal(raw_spec, dialect=dialect)

    # Re-compile finalized healed SQL
    compiler = QueryCompiler(raw_spec, schema=schema, dialect=dialect)
    compiled_sql = compiler.compile()[0]

    # Re-build QuerySpec dataclass
    query_spec = QuerySpec(
        table=raw_spec["table"],
        columns=raw_spec.get("columns", ["*"]),
        joins=[JoinSpec(**j) for j in raw_spec.get("joins", [])],
        filters=[FilterSpec(**f) for f in raw_spec.get("filters", [])],
        filter_join=raw_spec.get("filter_join", "AND"),
        having=[HavingSpec(**h) for h in raw_spec.get("having", [])],
        order_by=[OrderBySpec(**o) for o in raw_spec.get("order_by", [])],
        limit=raw_spec.get("limit", 50),
        offset=raw_spec.get("offset"),
        distinct=raw_spec.get("distinct", False),
        vector_search=raw_spec.get("vector_search"),
        hybrid_search=raw_spec.get("hybrid_search"),
    )

    combined_warnings = list(res.warnings)
    if healing_notes:
        combined_warnings.extend(healing_notes)

    return AiQueryResult(
        sql=compiled_sql,
        spec=raw_spec,
        query_spec=query_spec,
        explanation=res.explanation,
        confidence=res.confidence,
        warnings=combined_warnings,
        healing_notes=healing_notes,
        tokens_used=res.tokens_used,
        dialect=dialect,
        schema=schema,
    )


def _translate_with_byo(
    req: Any,
    byo_provider: BringYourOwnAiProvider,
    schema: Any,
    dialect: str,
) -> Any:
    """Helper dispatching translation directly through BringYourOwnAiProvider."""
    prompt = req.get("prompt") if isinstance(req, dict) else req.prompt
    raw_ast, tokens = byo_provider.generate_ast(prompt, schema=schema, dialect=dialect)

    from query_builder.nlq.validator import NlqAstValidator

    validator = NlqAstValidator(schema=schema)
    validated_ast, warnings = validator.validate(raw_ast)

    explanation_data = byo_provider.explain_query(validated_ast, dialect=dialect)
    explanation = explanation_data.get(
        "explanation", explanation_data.get("summary", "Generated from user prompt.")
    )

    from query_builder.nlq.models import NlqResult

    return NlqResult(
        spec=validated_ast,
        query_spec=None,  # type: ignore
        confidence=1.0 - (len(warnings) * 0.1),
        explanation=explanation,
        provider="byo",
        model=str(byo_provider.model),
        tokens_used=tokens,
        warnings=warnings,
    )


class QueryBuilderAiAgent:
    """
    Autonomous AI agent wrapper enabling programs to generate, inspect, validate,
    and expose Query-Builder as an AI tool for external LLM loops.
    """

    def __init__(
        self,
        schema: dict[str, Any] | None = None,
        ai: Any = None,
        dialect: str = "postgres",
        auto_heal: bool = True,
    ) -> None:
        self.schema = schema or {}
        self.ai = ai
        self.dialect = dialect
        self.auto_heal = auto_heal

    def ask(self, prompt: str, dialect: str | None = None) -> AiQueryResult:
        """Asks the AI to build a query based on the given prompt."""
        return ask_ai(
            prompt=prompt,
            ai=self.ai,
            schema=self.schema,
            dialect=dialect or self.dialect,
            auto_heal=self.auto_heal,
        )

    def as_tool(self, format: str = "openai") -> list[dict[str, Any]]:
        """Returns standard tool definitions for this agent's schema and dialect."""
        return get_agent_tool_definitions(format=format, schema=self.schema)

    def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any] | str
    ) -> dict[str, Any]:
        """Handles an execution request for a tool call emitted by an LLM."""
        return execute_agent_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            schema=self.schema,
            dialect=self.dialect,
        )
