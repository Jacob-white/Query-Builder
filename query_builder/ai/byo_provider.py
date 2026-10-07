"""
Bring Your Own AI (BYO-AI) Provider Adapter.
============================================
Allows programs, agents, and applications to supply their own LLM client or callable
directly to Query-Builder without configuring separate API keys or external services.
Supports:
- Python Callables (sync and async functions)
- OpenAI client instances (`openai.OpenAI()`)
- Anthropic Claude client instances (`anthropic.Anthropic()`)
- Google Gemini client instances (`genai.Client()`)
- LangChain BaseChatModel / Runnable instances
- Custom AI adapter objects
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any

from query_builder.nlq.models import NlqProviderError
from query_builder.nlq.prompt import (
    build_explain_prompt,
    build_system_prompt,
    build_user_prompt,
    serialize_schema_for_prompt,
)
from query_builder.nlq.providers import (
    NlqProvider,
    _strip_markdown_code_blocks,
    register_nlq_provider,
)


class BringYourOwnAiProvider(NlqProvider):
    """
    Adapter that delegates natural language translation and query explanation
    to an arbitrary AI client, callable, or agent supplied by the host application.
    """

    name: str = "byo"

    def __init__(
        self,
        ai: Any = None,
        model: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, timeout=timeout, **kwargs)
        self.ai = ai or kwargs.get("client") or kwargs.get("handler")
        self.model = model or "byo-ai-custom"

    def set_ai(self, ai: Any) -> None:
        """Sets or replaces the underlying AI callable or client."""
        self.ai = ai

    def _call_ai_sync(
        self, prompt: str, system_prompt: str
    ) -> tuple[str | dict[str, Any], int | None]:
        """Dispatches prompt and system prompt to the user's AI client."""
        ai = self.ai
        if ai is None:
            raise NlqProviderError(
                "No AI instance or callable provided to BringYourOwnAiProvider. "
                "Supply an AI client, agent, or callable via ask_ai(..., ai=...) or BringYourOwnAiProvider(ai=...)."
            )

        tokens_used: int | None = None

        # 1. OpenAI Client: client.chat.completions.create(...)
        if (
            hasattr(ai, "chat")
            and hasattr(ai.chat, "completions")
            and callable(getattr(ai.chat.completions, "create", None))
        ):
            model_name = self.model if self.model != "byo-ai-custom" else "gpt-4o"
            res = ai.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            content = res.choices[0].message.content or "{}"
            if hasattr(res, "usage") and res.usage:
                tokens_used = getattr(res.usage, "total_tokens", None)
            return content, tokens_used

        # 2. Anthropic Client: client.messages.create(...)
        if hasattr(ai, "messages") and callable(getattr(ai.messages, "create", None)):
            model_name = (
                self.model
                if self.model != "byo-ai-custom"
                else "claude-3-5-sonnet-20241022"
            )
            res = ai.messages.create(
                model=model_name,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.0,
            )
            content = ""
            for block in res.content:
                if hasattr(block, "text"):
                    content += block.text
            if hasattr(res, "usage") and res.usage:
                tokens_used = getattr(res.usage, "input_tokens", 0) + getattr(
                    res.usage, "output_tokens", 0
                )
            return content, tokens_used

        # 3. Google Gemini Client: client.models.generate_content(...)
        if hasattr(ai, "models") and callable(
            getattr(ai.models, "generate_content", None)
        ):
            model_name = (
                self.model if self.model != "byo-ai-custom" else "gemini-1.5-flash"
            )
            full_prompt = f"{system_prompt}\n\nUser Request: {prompt}"
            res = ai.models.generate_content(
                model=model_name,
                contents=full_prompt,
            )
            content = getattr(res, "text", "{}")
            if hasattr(res, "usage_metadata") and res.usage_metadata:
                tokens_used = getattr(res.usage_metadata, "total_token_count", None)
            return content, tokens_used

        # 4. Gemini genai.GenerativeModel: model.generate_content(...)
        if hasattr(ai, "generate_content") and callable(
            getattr(ai, "generate_content", None)
        ):
            full_prompt = f"{system_prompt}\n\nUser Request: {prompt}"
            res = ai.generate_content(full_prompt)
            content = getattr(res, "text", "{}")
            return content, tokens_used

        # 5. LangChain BaseChatModel / Runnable: llm.invoke(...)
        if hasattr(ai, "invoke") and callable(getattr(ai, "invoke", None)):
            full_prompt = f"{system_prompt}\n\nUser Request: {prompt}"
            res = ai.invoke(full_prompt)
            content = getattr(res, "content", str(res))
            if hasattr(res, "response_metadata") and isinstance(
                res.response_metadata, dict
            ):
                usage = res.response_metadata.get("token_usage", {})
                tokens_used = usage.get("total_tokens")
            return content, tokens_used

        # 6. Custom Object with .generate() or .call()
        if hasattr(ai, "generate") and callable(getattr(ai, "generate", None)):
            res = ai.generate(prompt=prompt, system_prompt=system_prompt)
            return res, tokens_used
        if hasattr(ai, "call") and callable(getattr(ai, "call", None)):
            res = ai.call(prompt=prompt, system_prompt=system_prompt)
            return res, tokens_used

        # 7. Plain Callable: fn(prompt, system_prompt) or fn(prompt)
        if callable(ai):
            sig = inspect.signature(ai)
            param_count = len(sig.parameters)
            if param_count >= 2:
                resp = ai(prompt, system_prompt)
            else:
                resp = ai(f"{system_prompt}\n\nUser Request: {prompt}")

            if inspect.iscoroutine(resp):
                try:
                    resp = asyncio.run(resp)
                except RuntimeError:
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        resp = pool.submit(asyncio.run, resp).result()

            return resp, tokens_used

        raise NlqProviderError(
            f"Unsupported AI client type '{type(ai).__name__}'. "
            "BringYourOwnAiProvider supports callable functions, OpenAI, Anthropic, Gemini, LangChain, or objects with .generate()."
        )

    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        """Translates user natural language prompt into raw AST dictionary and tokens used."""
        schema_str = serialize_schema_for_prompt(schema)
        system_prompt = build_system_prompt(schema_str, dialect=dialect)
        user_prompt = build_user_prompt(prompt)

        resp, tokens_used = self._call_ai_sync(user_prompt, system_prompt)

        if isinstance(resp, dict):
            return resp, tokens_used

        if not isinstance(resp, str):
            resp = str(resp)

        clean = _strip_markdown_code_blocks(resp)

        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                return parsed, tokens_used
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed, tokens_used
            except json.JSONDecodeError as exc:
                raise NlqProviderError(
                    f"BYO-AI returned unparseable JSON: {clean[:200]}"
                ) from exc

        raise NlqProviderError(
            f"BYO-AI returned invalid non-JSON output: {clean[:200]}"
        )

    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Explains a visual query AST in plain, structured natural language."""
        explain_prompt = build_explain_prompt(query_dict, dialect=dialect)
        system_prompt = "You are a SQL and database expert. Explain the following QuerySpec query in plain, accessible English."

        try:
            resp, _ = self._call_ai_sync(explain_prompt, system_prompt)
            if isinstance(resp, dict):
                return resp
            clean = _strip_markdown_code_blocks(str(resp))
            return {"explanation": clean, "summary": clean}
        except Exception:
            tbl = query_dict.get("table", "unknown")
            cols = query_dict.get("columns", ["*"])
            return {
                "explanation": f"Queries table `{tbl}` selecting {len(cols)} columns.",
                "summary": f"Queries `{tbl}`.",
            }


# Register with NLQ Provider Registry
register_nlq_provider("byo", BringYourOwnAiProvider)
register_nlq_provider("custom", BringYourOwnAiProvider)
