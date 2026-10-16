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
from query_builder.nlq.models import NlqResult, NlqTranslateRequest
from query_builder.nlq.service import NlqService, query_spec_from_validated_ast


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
    max_retries: int = 1,
    semantic_model: Any = None,
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
        max_retries: Number of automatic correction turns if compilation or AST validation fails.
        semantic_model: Optional SemanticModel, SemanticRegistry, or dict to ground metrics and dimensions.
    """
    opts = dict(options or {})
    provider_name = "byo" if ai is not None else "mock"

    byo_provider = BringYourOwnAiProvider(ai=ai) if ai is not None else None

    # Translate using NLQ service
    service: NlqService
    if byo_provider is not None:
        byo = byo_provider

        class _ByoNlqService(NlqService):
            def translate(
                self, request: NlqTranslateRequest | dict[str, Any]
            ) -> NlqResult:
                return _translate_with_byo(request, byo, schema, dialect)

        service = _ByoNlqService(default_provider=provider_name)
    else:
        service = NlqService(default_provider=provider_name)

    current_prompt = prompt
    retries_left = max(0, max_retries)
    healer = SelfHealingQueryEngine(schema=schema) if auto_heal else None
    last_exc: Exception | None = None
    last_raw_spec: dict[str, Any] = {}

    while True:
        try:
            res = service.translate(
                {
                    "prompt": current_prompt,
                    "schema": schema,
                    "provider": provider_name,
                    "dialect": dialect,
                    "options": opts,
                    "semantic_model": semantic_model,
                }
            )

            raw_spec = dict(res.spec)
            last_raw_spec = raw_spec
            healing_notes: list[str] = []

            if healer is not None:
                raw_spec, healing_notes = healer.auto_heal(raw_spec, dialect=dialect)
                last_raw_spec = raw_spec

            # Re-compile finalized healed SQL
            compiler = QueryCompiler(raw_spec, schema=schema, dialect=dialect)
            compiled_sql, *_ = compiler.compile()

            # Security AST validation check
            from query_builder.ast_validator import validate_sql_ast

            ast_res = validate_sql_ast(compiled_sql)
            if not ast_res.get("valid") or not ast_res.get("is_read_only"):
                violations = ast_res.get(
                    "violations", ["AST validation failed: Non-read-only query."]
                )
                if retries_left > 0 and healer is not None:
                    retries_left -= 1
                    current_prompt = healer.generate_repair_prompt(
                        broken_spec=raw_spec,
                        errors=violations,
                        original_prompt=prompt,
                    )
                    continue
                else:
                    healing_notes.append(
                        f"Security sanitizer alert: {'; '.join(violations)}"
                    )

            # Re-build QuerySpec dataclass
            query_spec = QuerySpec(
                table=raw_spec["table"],
                columns=raw_spec.get("columns", ["*"]),
                joins=[
                    JoinSpec(**j) if isinstance(j, dict) else j
                    for j in raw_spec.get("joins", [])
                ],
                filters=[
                    FilterSpec(**f) if isinstance(f, dict) else f
                    for f in raw_spec.get("filters", [])
                ],
                filter_join=raw_spec.get("filter_join", "AND"),
                having=[
                    HavingSpec(**h) if isinstance(h, dict) else h
                    for h in raw_spec.get("having", [])
                ],
                order_by=[
                    OrderBySpec(**o) if isinstance(o, dict) else o
                    for o in raw_spec.get("order_by", [])
                ],
                limit=raw_spec.get("limit", 50),
                offset=raw_spec.get("offset", 0),
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
        except Exception as exc:
            last_exc = exc
            if retries_left > 0 and healer is not None:
                retries_left -= 1
                current_prompt = healer.generate_repair_prompt(
                    broken_spec=last_raw_spec,
                    errors=[str(exc)],
                    original_prompt=prompt,
                )
                continue
            raise last_exc from exc


def _translate_with_byo(
    req: NlqTranslateRequest | dict[str, Any],
    byo_provider: BringYourOwnAiProvider,
    schema: Any,
    dialect: str,
) -> NlqResult:
    """Helper dispatching translation directly through BringYourOwnAiProvider."""
    prompt: str = req.get("prompt", "") if isinstance(req, dict) else req.prompt
    semantic_model = (
        req.get("semantic_model")
        if isinstance(req, dict)
        else getattr(req, "semantic_model", None)
    )
    raw_ast, tokens = byo_provider.generate_ast(
        prompt,
        schema=schema,
        dialect=dialect,
        semantic_model=semantic_model,
    )

    working_ast = raw_ast
    if semantic_model is not None:
        from query_builder.semantic import expand_metrics_and_dimensions

        working_ast = expand_metrics_and_dimensions(
            working_ast, semantic_model, dialect=dialect
        )

    from query_builder.nlq.validator import NlqAstValidator

    validator = NlqAstValidator(schema=schema)
    validated_ast, warnings = validator.validate(working_ast)

    explanation_data = byo_provider.explain_query(validated_ast, dialect=dialect)
    explanation = explanation_data.get(
        "explanation", explanation_data.get("summary", "Generated from user prompt.")
    )

    return NlqResult(
        spec=validated_ast,
        query_spec=query_spec_from_validated_ast(validated_ast),
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
        semantic_model: Any = None,
    ) -> None:
        self.schema = schema or {}
        self.ai = ai
        self.dialect = dialect
        self.auto_heal = auto_heal
        self.semantic_model = semantic_model

    def ask(
        self,
        prompt: str,
        dialect: str | None = None,
        max_retries: int = 1,
        semantic_model: Any = None,
    ) -> AiQueryResult:
        """Asks the AI to build a query based on the given prompt."""
        active_semantic = (
            semantic_model if semantic_model is not None else self.semantic_model
        )
        return ask_ai(
            prompt=prompt,
            ai=self.ai,
            schema=self.schema,
            dialect=dialect or self.dialect,
            auto_heal=self.auto_heal,
            max_retries=max_retries,
            semantic_model=active_semantic,
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
