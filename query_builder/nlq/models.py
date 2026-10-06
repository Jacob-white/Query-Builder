"""
Data models and error types for Natural Language to Visual Query (NLQ) engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from query_builder.models import QuerySpec


class NlqError(Exception):
    """Base exception for all NLQ translation and explanation operations."""


class NlqValidationError(NlqError):
    """Raised when generated AST fails schema validation or grounding."""


class NlqProviderError(NlqError):
    """Raised when an LLM provider encounters an API, network, or decoding error."""


@dataclass
class NlqResult:
    """Structured result returned by NLQ translation."""

    spec: dict[str, Any]
    query_spec: QuerySpec
    confidence: float
    explanation: str
    provider: str
    model: str
    tokens_used: int | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "provider": self.provider,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "warnings": list(self.warnings),
        }


@dataclass
class NlqExplainResult:
    """Structured result explaining a visual query in natural language."""

    summary: str
    explanation: str
    steps: list[str]
    provider: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "explanation": self.explanation,
            "steps": list(self.steps),
            "provider": self.provider,
        }


@dataclass
class NlqTranslateRequest:
    """Request configuration for natural language translation."""

    prompt: str
    schema: dict[str, Any] | None = None
    provider: str = "mock"
    dialect: str = "postgres"
    api_key: str | None = None
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    options: dict[str, Any] = field(default_factory=dict)
