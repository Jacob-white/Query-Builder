"""
Unified NLQ Service coordinating LLM providers, schema grounding, and validation.
"""

from __future__ import annotations

import os
from typing import Any

from query_builder.models import (
    FilterSpec,
    HavingSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
)
from query_builder.nlq.models import (
    NlqExplainResult,
    NlqResult,
    NlqTranslateRequest,
)
from query_builder.nlq.providers import (
    get_nlq_provider,
    list_nlq_providers,
)
from query_builder.nlq.validator import NlqAstValidator


def query_spec_from_validated_ast(validated_ast: dict[str, Any]) -> QuerySpec:
    """Builds a QuerySpec dataclass from a fully-normalized `NlqAstValidator` result."""
    return QuerySpec(
        table=validated_ast["table"],
        columns=validated_ast["columns"],
        joins=[
            JoinSpec(**j) if isinstance(j, dict) else j for j in validated_ast["joins"]
        ],
        filters=[
            FilterSpec(**f) if isinstance(f, dict) else f
            for f in validated_ast["filters"]
        ],
        filter_join=validated_ast["filter_join"],
        having=[
            HavingSpec(**h) if isinstance(h, dict) else h
            for h in validated_ast["having"]
        ],
        order_by=[
            OrderBySpec(**o) if isinstance(o, dict) else o
            for o in validated_ast["order_by"]
        ],
        limit=validated_ast["limit"],
        offset=validated_ast["offset"],
        distinct=validated_ast["distinct"],
        vector_search=validated_ast.get("vector_search"),
        hybrid_search=validated_ast.get("hybrid_search"),
        metrics=validated_ast.get("metrics", []),
        semantic_model=validated_ast.get("semantic_model"),
        semantic_models=validated_ast.get("semantic_models", []),
        ctes=validated_ast.get("ctes", []),
        window_functions=validated_ast.get("window_functions", []),
        set_operations=validated_ast.get("set_operations", []),
    )


class NlqService:
    """Service facade managing natural language to QuerySpec translation and explanation."""

    def __init__(self, default_provider: str = "mock") -> None:
        self.default_provider = default_provider

    def translate(
        self,
        request: NlqTranslateRequest | dict[str, Any],
    ) -> NlqResult:
        """Translates natural language into a schema-grounded and validated QuerySpec AST."""
        if isinstance(request, dict):
            req = NlqTranslateRequest(
                prompt=request.get("prompt", ""),
                schema=request.get("schema"),
                provider=request.get("provider") or self.default_provider,
                dialect=request.get("dialect") or "postgres",
                api_key=request.get("api_key"),
                model=request.get("model"),
                temperature=float(request.get("temperature", 0.0)),
                max_tokens=int(request.get("max_tokens", 1024)),
                options=request.get("options", {}),
                semantic_model=request.get("semantic_model"),
                current_spec=request.get("current_spec") or request.get("currentSpec"),
                history=request.get("history"),
            )
        else:
            req = request

        provider = get_nlq_provider(
            req.provider,
            api_key=req.api_key,
            model=req.model,
            **req.options,
        )

        raw_ast, tokens_used = provider.generate_ast(
            prompt=req.prompt,
            schema=req.schema,
            dialect=req.dialect,
            semantic_model=req.semantic_model,
            current_spec=req.current_spec,
            history=req.history,
        )

        working_ast = raw_ast
        if req.semantic_model is not None:
            from query_builder.semantic import expand_metrics_and_dimensions

            working_ast = expand_metrics_and_dimensions(
                working_ast, req.semantic_model, dialect=req.dialect
            )

        validator = NlqAstValidator(schema=req.schema)
        validated_ast, warnings = validator.validate(working_ast)

        query_spec = query_spec_from_validated_ast(validated_ast)

        # Confidence calculation
        confidence = 1.0 - (len(warnings) * 0.15)
        confidence = max(0.2, min(1.0, round(confidence, 2)))

        # Natural language explanation (use inline explanation from AST when provided by LLM to avoid a second network roundtrip)
        inline_explanation = (
            raw_ast.get("explanation") if isinstance(raw_ast, dict) else None
        )
        if isinstance(inline_explanation, str) and inline_explanation.strip():
            explanation_text = inline_explanation.strip()
        else:
            explanation_data = provider.explain_query(
                validated_ast, dialect=req.dialect
            )
            explanation_text = explanation_data.get(
                "explanation",
                explanation_data.get("summary", "Generated from user prompt."),
            )

        raw_follow_ups = (
            raw_ast.get("follow_ups") if isinstance(raw_ast, dict) else None
        )
        follow_ups: list[str] = (
            [str(f).strip() for f in raw_follow_ups if str(f).strip()][:4]
            if isinstance(raw_follow_ups, list)
            else []
        )

        return NlqResult(
            spec=validated_ast,
            query_spec=query_spec,
            confidence=confidence,
            explanation=explanation_text,
            provider=provider.name,
            model=str(provider.model),
            tokens_used=tokens_used,
            warnings=warnings,
            follow_ups=follow_ups,
        )

    def explain(
        self,
        query: dict[str, Any] | QuerySpec,
        dialect: str = "postgres",
        provider: str = "mock",
        api_key: str | None = None,
        model: str | None = None,
        **options: Any,
    ) -> NlqExplainResult:
        """Explains an existing visual QuerySpec in structured natural language."""
        if hasattr(query, "to_dict"):
            query_dict = query.to_dict()
        elif isinstance(query, dict):
            query_dict = query
        else:
            query_dict = {"table": "unknown"}

        prov = get_nlq_provider(provider, api_key=api_key, model=model, **options)
        res = prov.explain_query(query_dict, dialect=dialect)

        summary = res.get("summary", "Query summary")
        explanation = res.get("explanation", summary)
        steps = res.get("steps", [])
        if not steps and explanation:
            steps = [explanation]

        return NlqExplainResult(
            summary=summary,
            explanation=explanation,
            steps=steps,
            provider=prov.name,
        )

    def list_available_providers(self) -> list[dict[str, Any]]:
        """Lists registered providers and their runtime configuration status."""
        result: list[dict[str, Any]] = []
        for name in list_nlq_providers():
            env_var = {
                "gemini": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
            }.get(name)
            is_configured = (
                True
                if name in {"mock", "ollama"}
                else bool(env_var and os.getenv(env_var))
            )
            result.append(
                {
                    "name": name,
                    "configured": is_configured,
                    "is_local": name in {"mock", "ollama"},
                }
            )
        return result
