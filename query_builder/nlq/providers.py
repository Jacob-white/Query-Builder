"""
Multi-provider LLM integrations (Gemini, OpenAI, Anthropic, Ollama, and Mock) for NLQ.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from query_builder.nlq.models import NlqProviderError
from query_builder.nlq.prompt import (
    build_explain_prompt,
    build_system_prompt,
    build_user_prompt,
    serialize_schema_for_prompt,
)


def _strip_markdown_code_blocks(text: str) -> str:
    """Strips markdown code block wrappers (e.g. ```json ... ```) from model output."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z0-9]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    return clean.strip()


# ``(?<![a-zA-Z0-9_])`` restricts the unanchored search to word starts.  The leftmost
# match of the former pattern always started at the first character of a word anyway
# (extending a match to the left keeps its tail), but trying every position inside a
# long word was quadratic.
_GT_FILTER_RE = re.compile(
    r"(?<![a-zA-Z0-9_])([a-zA-Z0-9_]+)\s*(?:>|greater than|more than)\s*([0-9]+)"
)
_LT_FILTER_RE = re.compile(
    r"(?<![a-zA-Z0-9_])([a-zA-Z0-9_]+)\s*(?:<|less than)\s*([0-9]+)"
)
_EQ_FILTER_RE = re.compile(
    r"(?<![a-zA-Z0-9_])([a-zA-Z0-9_]+)\s*(?:=|equals)\s*['\"]?([a-zA-Z0-9_-]+)['\"]?"
)

_COLUMN_PHRASE_KEYWORD_RE = re.compile(r"\b(?:show|select|find|get)(?=\s)")
_WHITESPACE_RUN_RE = re.compile(r"\s+")
_COLUMN_CHARS_RUN_RE = re.compile(r"[a-zA-Z0-9_,\s]*")
_COLUMN_PHRASE_TERMINATORS = ("from", "where", "order", "limit", "sorted")


def _match_column_phrase(text: str) -> str | None:
    r"""Returns the stripped column phrase of ``show|select|find|get <cols> from|...``.

    Linear-time equivalent of ``re.search(r"\b(?:show|select|find|get)\s+
    ([a-zA-Z0-9_,\s]+?)\s+(?:from|where|order|limit|sorted|$)", text)`` (group 1,
    stripped; ``None`` when there is no match).  The lazy group may itself contain
    whitespace, which made the regex cubic on long whitespace runs and quadratic on
    repeated keywords.

    Whether the whitespace run before a terminator (or the end of the text) is
    followed by one depends on the run alone, so the lazy group ends at the first such
    run inside the maximal run of allowed characters.  When the group cannot start at
    the first non-space character the regex falls back to a one-character whitespace
    group, which needs a whitespace run of at least three characters.
    """
    length = len(text)
    # Maximal run ``[region_start, region_end)`` of allowed characters seen so far.
    region_start = region_end = 0
    failed_end = -1
    for keyword in _COLUMN_PHRASE_KEYWORD_RE.finditer(text):
        after_keyword = keyword.end()
        group_start = _run_end(_WHITESPACE_RUN_RE, text, after_keyword)
        if not region_start <= after_keyword < region_end:
            region_start = after_keyword
            region_end = _run_end(_COLUMN_CHARS_RUN_RE, text, after_keyword)
        if failed_end <= group_start < region_end:
            for run in _WHITESPACE_RUN_RE.finditer(text, group_start, region_end):
                run_end = run.end()
                if run_end == length or text.startswith(
                    _COLUMN_PHRASE_TERMINATORS, run_end
                ):
                    return text[group_start : run.start()].strip()
            failed_end = region_end
        if group_start - after_keyword >= 3 and (
            group_start == length
            or text.startswith(_COLUMN_PHRASE_TERMINATORS, group_start)
        ):
            return ""
    return None


def _run_end(pattern: re.Pattern[str], text: str, pos: int) -> int:
    match = pattern.match(text, pos)
    return match.end() if match else pos


class NlqProvider(ABC):
    """Abstract base class for all LLM providers translating natural language to QuerySpec."""

    name: str = "base"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.extra_kwargs = kwargs

    def _root_url(self) -> str:
        """The configured base URL without a trailing slash ('' when unset)."""
        return (self.base_url or "").rstrip("/")

    def _safe_execute_http_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        allow_private_networks: bool = False,
    ) -> bytes:
        """
        Safely executes an outbound HTTP request for NLQ providers.
        Strictly enforces:
        1. Only permitted URL schemes ('http', 'https').
        2. Network egress validation via validate_network_target to block SSRF
           (cloud metadata 169.254.169.254, internal private subnets when disabled).
        """
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise NlqProviderError(
                f"Forbidden URL scheme '{scheme}'. Only 'http' and 'https' are allowed."
            )

        from query_builder.config import NetworkSecurityConfig
        from query_builder.exceptions import SecurityError
        from query_builder.security import validate_network_target

        try:
            validate_network_target(
                url=url,
                network_config=NetworkSecurityConfig(
                    allow_private_networks=allow_private_networks,
                    enforce_tls=not allow_private_networks,
                ),
            )
        except SecurityError as sec_err:
            raise NlqProviderError(
                f"Security validation blocked network request: {sec_err}"
            ) from sec_err

        req = urllib.request.Request(  # noqa: S310
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        # Scheme and network target are validated above; urlopen is restricted to http/https and non-metadata egress targets.
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return resp.read()

    @abstractmethod
    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        """Translates user natural language prompt into raw AST dictionary and tokens used."""

    @abstractmethod
    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Explains a visual query AST in plain, structured natural language."""


class MockNlqProvider(NlqProvider):
    """Hermetic, offline rule-and-intent based NLQ provider for testing and deterministic fallbacks."""

    name: str = "mock"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.model = self.model or "mock-rule-v1"

    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        lower_prompt = prompt.lower().strip()

        # Resolve primary table
        table = "users"
        schema_tables: list[str] = []
        if schema:
            raw_t = schema.get("tables", schema)
            if isinstance(raw_t, dict):
                schema_tables = list(raw_t.keys())

        # Match table from prompt against schema
        for st in schema_tables:
            if st.lower() in lower_prompt:
                table = st
                break
        else:
            tbl_match = re.search(
                r"\b(?:from|in|table)\s+([a-zA-Z0-9_]+)", lower_prompt
            )
            if tbl_match:
                table = tbl_match.group(1)
            elif schema_tables:
                table = schema_tables[0]

        # Columns
        columns: list[str | dict[str, Any]] = []
        if "count" in lower_prompt:
            columns.append({"column": "id", "agg": "COUNT", "alias": "total_count"})
        elif "sum" in lower_prompt:
            columns.append({"column": "amount", "agg": "SUM", "alias": "total_amount"})
        elif "average" in lower_prompt or "avg" in lower_prompt:
            columns.append({"column": "score", "agg": "AVG", "alias": "avg_score"})
        else:
            raw_cols_str = _match_column_phrase(lower_prompt)
            if raw_cols_str is not None:
                if raw_cols_str and raw_cols_str != "all":
                    extracted = [
                        c.strip() for c in raw_cols_str.split(",") if c.strip()
                    ]
                    columns.extend(extracted)
            if not columns:
                columns = ["*"]

        # Joins
        joins: list[dict[str, Any]] = []
        join_match = re.search(
            r"\b(?:joined\s+with|join)\s+([a-zA-Z0-9_]+)(?:\s+on\s+([a-zA-Z0-9_]+))?",
            lower_prompt,
        )
        if join_match:
            j_table = join_match.group(1)
            j_col = join_match.group(2) or "id"
            joins.append(
                {
                    "table": j_table,
                    "type": "LEFT" if "left join" in lower_prompt else "INNER",
                    "left_table": table,
                    "left_col": f"{j_table}_id",
                    "right_col": j_col,
                }
            )

        # Filters
        filters: list[dict[str, Any]] = []
        if "active" in lower_prompt:
            filters.append({"column": "status", "op": "=", "value": "active"})
        if "pending" in lower_prompt:
            filters.append({"column": "status", "op": "=", "value": "pending"})
        gt_match = _GT_FILTER_RE.search(lower_prompt)
        if gt_match:
            filters.append(
                {
                    "column": gt_match.group(1),
                    "op": ">",
                    "value": int(gt_match.group(2)),
                }
            )
        lt_match = _LT_FILTER_RE.search(lower_prompt)
        if lt_match:
            filters.append(
                {
                    "column": lt_match.group(1),
                    "op": "<",
                    "value": int(lt_match.group(2)),
                }
            )
        eq_match = _EQ_FILTER_RE.search(lower_prompt)
        if eq_match and eq_match.group(1) not in {"status"}:
            filters.append(
                {"column": eq_match.group(1), "op": "=", "value": eq_match.group(2)}
            )

        # Order By
        order_by: list[dict[str, Any]] = []
        order_match = re.search(
            r"\b(?:order\s+by|sorted\s+by|sort\s+by)\s+([a-zA-Z0-9_]+)(?:\s+(asc|desc|ascending|descending))?",
            lower_prompt,
        )
        if order_match:
            ob_col = order_match.group(1)
            direction = (
                "DESC"
                if order_match.group(2) in ("desc", "descending")
                or "descending" in lower_prompt
                else "ASC"
            )
            order_by.append({"column": ob_col, "direction": direction})

        # Limit
        limit = 50
        limit_match = re.search(r"\b(?:limit|top)\s+([0-9]+)", lower_prompt)
        if limit_match:
            limit = int(limit_match.group(1))

        # Distinct
        distinct = "distinct" in lower_prompt or "unique" in lower_prompt

        # Vector search
        vector_search = None
        if "vector" in lower_prompt or "similar" in lower_prompt:
            vector_search = {
                "column": "embedding",
                "vector": [0.1, 0.2, 0.3],
                "top_k": 10,
                "metric": "cosine",
            }

        ast: dict[str, Any] = {
            "table": table,
            "columns": columns,
            "joins": joins,
            "filters": filters,
            "filter_join": "OR" if " or " in lower_prompt else "AND",
            "having": [],
            "order_by": order_by,
            "limit": limit,
            "offset": 0,
            "distinct": distinct,
            "vector_search": vector_search,
            "hybrid_search": None,
        }
        return ast, 42

    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        table = query_dict.get("table", "unknown_table")
        cols = query_dict.get("columns", ["*"])
        joins = query_dict.get("joins", [])
        filters = query_dict.get("filters", [])
        order_by = query_dict.get("order_by", [])
        limit = query_dict.get("limit", 50)

        steps: list[str] = [f"Select records from base table '{table}'."]
        for j in joins:
            steps.append(
                f"Join with table '{j.get('table')}' on {j.get('left_col')} = {j.get('right_col')}."
            )
        for f in filters:
            steps.append(
                f"Filter records where '{f.get('column')}' {f.get('op')} {f.get('value')}."
            )
        if order_by:
            ob_strs = [
                f"{o.get('column')} {o.get('direction', 'ASC')}" for o in order_by
            ]
            steps.append(f"Sort results by {', '.join(ob_strs)}.")
        steps.append(f"Limit query output to {limit} rows.")

        summary = f"Queries {table} projecting {len(cols)} columns with {len(filters)} filters."
        explanation = (
            f"This query targets the '{table}' dataset in {dialect} SQL dialect. "
            + " ".join(steps)
        )
        return {
            "summary": summary,
            "explanation": explanation,
            "steps": steps,
        }


class GeminiProvider(NlqProvider):
    """Google Gemini API provider using structured JSON output."""

    name: str = "gemini"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = self.api_key or os.getenv("GEMINI_API_KEY")
        self.model = self.model or "gemini-2.5-flash"

    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        if not self.api_key:
            raise NlqProviderError("GEMINI_API_KEY not configured for GeminiProvider.")

        schema_str = serialize_schema_for_prompt(schema)
        sys_prompt = build_system_prompt(schema_str, dialect=dialect)
        user_prompt = build_user_prompt(prompt)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": sys_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        }

        data, tokens = self._execute_http(url, payload)
        clean_text = _strip_markdown_code_blocks(data)
        try:
            ast = json.loads(clean_text)
            if not isinstance(ast, dict):
                raise ValueError("Response root is not a JSON object")
            return ast, tokens
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse Gemini JSON output: {exc}. Response text: {clean_text[:200]}"
            ) from exc

    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise NlqProviderError("GEMINI_API_KEY not configured for GeminiProvider.")

        prompt = build_explain_prompt(query_dict, dialect=dialect)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        }
        data, _ = self._execute_http(url, payload)
        clean_text = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean_text)
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse Gemini explain JSON: {exc}"
            ) from exc

    def _execute_http(
        self, url: str, payload: dict[str, Any]
    ) -> tuple[str, int | None]:
        headers = {"Content-Type": "application/json"}
        try:
            raw_bytes = self._safe_execute_http_request(
                url, payload, headers, allow_private_networks=False
            )
            raw = raw_bytes.decode("utf-8")
            res = json.loads(raw)
            candidates = res.get("candidates", [])
            if not candidates:
                raise NlqProviderError("Gemini returned empty candidates list.")
            text = (
                candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            )
            usage = res.get("usageMetadata", {})
            tokens = usage.get("totalTokenCount")
            return text, tokens
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise NlqProviderError(f"Gemini HTTP {exc.code} error: {err_body}") from exc
        except NlqProviderError:
            raise
        except Exception as exc:
            raise NlqProviderError(f"Gemini request failed: {exc}") from exc


class OpenAiProvider(NlqProvider):
    """OpenAI API provider for models like gpt-4o and gpt-4o-mini."""

    name: str = "openai"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        self.model = self.model or "gpt-4o-mini"
        self.base_url = self.base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )

    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        if not self.api_key:
            raise NlqProviderError("OPENAI_API_KEY not configured for OpenAiProvider.")

        schema_str = serialize_schema_for_prompt(schema)
        sys_prompt = build_system_prompt(schema_str, dialect=dialect)
        user_prompt = build_user_prompt(prompt)

        url = f"{self._root_url()}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        data, tokens = self._execute_http(url, payload)
        clean = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean), tokens
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse OpenAI JSON output: {exc}"
            ) from exc

    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise NlqProviderError("OPENAI_API_KEY not configured for OpenAiProvider.")

        prompt = build_explain_prompt(query_dict, dialect=dialect)
        url = f"{self._root_url()}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You explain SQL and AST queries."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        data, _ = self._execute_http(url, payload)
        clean = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean)
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse OpenAI explain JSON: {exc}"
            ) from exc

    def _execute_http(
        self, url: str, payload: dict[str, Any]
    ) -> tuple[str, int | None]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            raw_bytes = self._safe_execute_http_request(
                url, payload, headers, allow_private_networks=False
            )
            raw = raw_bytes.decode("utf-8")
            res = json.loads(raw)
            choices = res.get("choices", [])
            if not choices:
                raise NlqProviderError("OpenAI returned no choices.")
            content = choices[0].get("message", {}).get("content", "{}")
            tokens = res.get("usage", {}).get("total_tokens")
            return content, tokens
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise NlqProviderError(f"OpenAI HTTP {exc.code} error: {err_body}") from exc
        except NlqProviderError:
            raise
        except Exception as exc:
            raise NlqProviderError(f"OpenAI request failed: {exc}") from exc


class AnthropicProvider(NlqProvider):
    """Anthropic Claude API provider."""

    name: str = "anthropic"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = self.model or "claude-3-5-sonnet-20241022"
        self.base_url = self.base_url or "https://api.anthropic.com/v1"

    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        if not self.api_key:
            raise NlqProviderError(
                "ANTHROPIC_API_KEY not configured for AnthropicProvider."
            )

        schema_str = serialize_schema_for_prompt(schema)
        sys_prompt = build_system_prompt(schema_str, dialect=dialect)
        user_prompt = build_user_prompt(prompt)

        url = f"{self._root_url()}/messages"
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": 0.0,
        }

        data, tokens = self._execute_http(url, payload)
        clean = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean), tokens
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse Anthropic JSON output: {exc}"
            ) from exc

    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise NlqProviderError(
                "ANTHROPIC_API_KEY not configured for AnthropicProvider."
            )

        prompt = build_explain_prompt(query_dict, dialect=dialect)
        url = f"{self._root_url()}/messages"
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": "You explain SQL and AST queries. Output only structured JSON.",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        data, _ = self._execute_http(url, payload)
        clean = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean)
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse Anthropic explain JSON: {exc}"
            ) from exc

    def _execute_http(
        self, url: str, payload: dict[str, Any]
    ) -> tuple[str, int | None]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        try:
            raw_bytes = self._safe_execute_http_request(
                url, payload, headers, allow_private_networks=False
            )
            raw = raw_bytes.decode("utf-8")
            res = json.loads(raw)
            content_blocks = res.get("content", [])
            text = "".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            )
            usage = res.get("usage", {})
            tokens = (
                usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            ) or None
            return text, tokens
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise NlqProviderError(
                f"Anthropic HTTP {exc.code} error: {err_body}"
            ) from exc
        except NlqProviderError:
            raise
        except Exception as exc:
            raise NlqProviderError(f"Anthropic request failed: {exc}") from exc


class OllamaProvider(NlqProvider):
    """Local Ollama instance provider with zero external dependencies."""

    name: str = "ollama"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.model = self.model or "llama3.2"
        self.base_url = self.base_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )

    def generate_ast(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> tuple[dict[str, Any], int | None]:
        schema_str = serialize_schema_for_prompt(schema)
        sys_prompt = build_system_prompt(schema_str, dialect=dialect)
        user_prompt = build_user_prompt(prompt)

        url = f"{self._root_url()}/api/generate"
        payload = {
            "model": self.model,
            "system": sys_prompt,
            "prompt": user_prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
        }

        data, tokens = self._execute_http(url, payload)
        clean = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean), tokens
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse Ollama JSON output: {exc}"
            ) from exc

    def explain_query(
        self,
        query_dict: dict[str, Any],
        dialect: str = "postgres",
        **kwargs: Any,
    ) -> dict[str, Any]:
        prompt = build_explain_prompt(query_dict, dialect=dialect)
        url = f"{self._root_url()}/api/generate"
        payload = {
            "model": self.model,
            "system": "You explain SQL and AST queries. Output only structured JSON.",
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
        }
        data, _ = self._execute_http(url, payload)
        clean = _strip_markdown_code_blocks(data)
        try:
            return json.loads(clean)
        except Exception as exc:
            raise NlqProviderError(
                f"Failed to parse Ollama explain JSON: {exc}"
            ) from exc

    def _execute_http(
        self, url: str, payload: dict[str, Any]
    ) -> tuple[str, int | None]:
        headers = {"Content-Type": "application/json"}
        try:
            raw_bytes = self._safe_execute_http_request(
                url, payload, headers, allow_private_networks=True
            )
            raw = raw_bytes.decode("utf-8")
            res = json.loads(raw)
            response_text = res.get("response", "{}")
            eval_count = res.get("eval_count")
            prompt_eval_count = res.get("prompt_eval_count")
            tokens = (
                (eval_count + prompt_eval_count)
                if (eval_count and prompt_eval_count)
                else eval_count
            )
            return response_text, tokens
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise NlqProviderError(f"Ollama HTTP {exc.code} error: {err_body}") from exc
        except NlqProviderError:
            raise
        except Exception as exc:
            raise NlqProviderError(f"Ollama request failed: {exc}") from exc


# Provider Registry
PROVIDER_REGISTRY: dict[str, type[NlqProvider]] = {
    "mock": MockNlqProvider,
    "gemini": GeminiProvider,
    "openai": OpenAiProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def register_nlq_provider(name: str, provider_cls: type[NlqProvider]) -> None:
    """Registers a new NLQ provider implementation."""
    PROVIDER_REGISTRY[name.lower()] = provider_cls


def get_nlq_provider(name: str = "mock", **kwargs: Any) -> NlqProvider:
    """Factory creating an instance of the requested NLQ provider."""
    key = name.lower()
    if key not in PROVIDER_REGISTRY:
        raise NlqProviderError(
            f"Unknown NLQ provider '{name}'. Available: {list(PROVIDER_REGISTRY.keys())}"
        )
    return PROVIDER_REGISTRY[key](**kwargs)


def list_nlq_providers() -> list[str]:
    """Returns the names of all registered NLQ providers."""
    return list(PROVIDER_REGISTRY.keys())
