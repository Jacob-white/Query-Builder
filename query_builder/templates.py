"""
Query Template Persistence Store.
=================================
Manages reusable query templates with categorization, tenant isolation,
search filtering, and optional JSON disk persistence.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from query_builder.security import SecurityError


@dataclass
class QueryTemplate:
    """Stored declarative query template model."""

    id: str
    title: str
    spec: dict[str, Any]
    sql: str = ""
    description: str = ""
    category: str = "general"
    tenant_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Converts query template to dictionary."""
        return asdict(self)


class TemplateError(Exception):
    """Base exception for query template store operations."""


class TemplateNotFoundError(TemplateError):
    """Raised when requested template ID is not found."""


class TemplateValidationError(TemplateError):
    """Raised when template definition or specification is invalid."""


class TemplateStore:
    """Thread-safe query template store with optional disk persistence."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        self._templates: dict[str, QueryTemplate] = {}
        self._lock = threading.Lock()

        if self.storage_path and self.storage_path.exists():
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Loads serialized templates from disk storage."""
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for item in data.values():
                    if isinstance(item, dict):
                        tmpl = QueryTemplate(**item)
                        self._templates[tmpl.id] = tmpl
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        tmpl = QueryTemplate(**item)
                        self._templates[tmpl.id] = tmpl
        except (json.JSONDecodeError, OSError):
            pass

    def _save_to_disk(self) -> None:
        """Flushes in-memory templates to disk storage."""
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._templates.items()}
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def save(self, template: QueryTemplate | dict[str, Any]) -> QueryTemplate:
        """Saves or updates a query template."""
        if isinstance(template, QueryTemplate):
            data = template.to_dict()
        elif isinstance(template, dict):
            data = dict(template)
        else:
            raise TemplateValidationError(
                f"Unsupported template input type: {type(template).__name__}"
            )

        title = data.get("title")
        if not title or not isinstance(title, str) or not title.strip():
            raise TemplateValidationError("Template title is required.")

        spec = data.get("spec")
        if not isinstance(spec, dict) or not spec:
            raise TemplateValidationError(
                "Template specification must be a non-empty dictionary."
            )

        tmpl_id = str(data.get("id") or "").strip()
        if not tmpl_id:
            tmpl_id = uuid.uuid4().hex[:12]

        now_str = datetime.now(UTC).isoformat()

        with self._lock:
            existing = self._templates.get(tmpl_id)
            created_at = (
                existing.created_at
                if existing and existing.created_at
                else data.get("created_at") or now_str
            )

            saved = QueryTemplate(
                id=tmpl_id,
                title=title.strip(),
                spec=spec,
                sql=data.get("sql", ""),
                description=data.get("description", ""),
                category=data.get("category", "general"),
                tenant_id=data.get("tenant_id"),
                created_at=created_at,
                updated_at=now_str,
                is_default=bool(data.get("is_default", False)),
            )

            self._templates[tmpl_id] = saved
            if self.storage_path:
                self._save_to_disk()

            return saved

    def get(self, template_id: str) -> QueryTemplate | None:
        """Retrieves template by ID, or None if not found."""
        with self._lock:
            return self._templates.get(template_id)

    def list(
        self,
        tenant_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> list[QueryTemplate]:
        """Lists query templates matching optional tenant, category, and search criteria."""
        with self._lock:
            results: list[QueryTemplate] = []
            for tmpl in self._templates.values():
                # Tenant isolation: include tenant's templates and public (None) templates
                if (
                    tenant_id is not None
                    and tmpl.tenant_id is not None
                    and tmpl.tenant_id != tenant_id
                ):
                    continue
                if category is not None and tmpl.category != category:
                    continue
                if search is not None and search.strip():
                    term = search.strip().lower()
                    if (
                        term not in tmpl.title.lower()
                        and term not in tmpl.description.lower()
                    ):
                        continue
                results.append(tmpl)
            return results

    def delete(self, template_id: str, tenant_id: str | None = None) -> bool:
        """Deletes template by ID. Fails with SecurityError if tenant unauthorized."""
        with self._lock:
            tmpl = self._templates.get(template_id)
            if not tmpl:
                return False

            if (
                tenant_id is not None
                and tmpl.tenant_id is not None
                and tmpl.tenant_id != tenant_id
            ):
                raise SecurityError(
                    "Unauthorized: cannot delete template of another tenant."
                )

            del self._templates[template_id]
            if self.storage_path:
                self._save_to_disk()
            return True

    def clear(self) -> None:
        """Clears all templates from store and disk storage."""
        with self._lock:
            self._templates.clear()
            if self.storage_path:
                self._save_to_disk()
