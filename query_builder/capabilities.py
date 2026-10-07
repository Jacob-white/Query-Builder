"""
Engine Capabilities & Feature Governance for Query Builder.
============================================================
Defines feature tiers (standard, advanced, disabled), engine capabilities registry,
presets, and validation exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class FeatureTier(str, Enum):
    """Classification tier for a query builder engine feature."""

    STANDARD = "standard"
    ADVANCED = "advanced"
    DISABLED = "disabled"


class DisabledFeatureError(ValueError):
    """
    Raised when a query spec attempts to compile or execute a feature that is
    explicitly disabled in the active EngineCapabilities.
    """

    def __init__(self, feature_name: str, message: Optional[str] = None):
        self.feature_name = feature_name
        self.message = (
            message
            or f"Feature '{feature_name}' is disabled in the active engine capabilities. "
            f"Enable '{feature_name}' in EngineCapabilities or select a capability preset that permits it."
        )
        super().__init__(self.message)


@dataclass
class EngineCapabilities:
    """
    Defines the availability and tier classification of features supported by
    the Query Builder engine.
    """

    projections: FeatureTier = FeatureTier.STANDARD
    filters: FeatureTier = FeatureTier.STANDARD
    sorts: FeatureTier = FeatureTier.STANDARD
    joins: FeatureTier = FeatureTier.STANDARD
    distinct_limit: FeatureTier = FeatureTier.STANDARD
    visual_chart: FeatureTier = FeatureTier.STANDARD
    ctes: FeatureTier = FeatureTier.ADVANCED
    window_functions: FeatureTier = FeatureTier.ADVANCED
    analytical_grouping: FeatureTier = FeatureTier.ADVANCED
    vector_search: FeatureTier = FeatureTier.ADVANCED
    raw_sql: FeatureTier = FeatureTier.ADVANCED
    query_plan: FeatureTier = FeatureTier.ADVANCED
    calculated_fields: FeatureTier = FeatureTier.ADVANCED
    schema_tools: FeatureTier = FeatureTier.ADVANCED
    custom_overrides: Dict[str, FeatureTier] = field(default_factory=dict)

    def get_tier(self, feature_name: str) -> FeatureTier:
        """Returns the FeatureTier for a given feature key."""
        if feature_name in self.custom_overrides:
            return self.custom_overrides[feature_name]
        return getattr(self, feature_name, FeatureTier.STANDARD)

    def is_enabled(self, feature_name: str) -> bool:
        """Checks if a feature is enabled (either standard or advanced)."""
        return self.get_tier(feature_name) != FeatureTier.DISABLED

    def is_advanced(self, feature_name: str) -> bool:
        """Checks if a feature is classified as advanced."""
        return self.get_tier(feature_name) == FeatureTier.ADVANCED

    def require_feature(self, feature_name: str) -> None:
        """
        Validates that a feature is enabled. Raises DisabledFeatureError if disabled.
        """
        if not self.is_enabled(feature_name):
            raise DisabledFeatureError(feature_name)

    def to_dict(self) -> Dict[str, str]:
        """Serializes capabilities to a dictionary of string values."""
        res: Dict[str, str] = {
            "projections": self.projections.value,
            "filters": self.filters.value,
            "sorts": self.sorts.value,
            "joins": self.joins.value,
            "distinct_limit": self.distinct_limit.value,
            "visual_chart": self.visual_chart.value,
            "ctes": self.ctes.value,
            "window_functions": self.window_functions.value,
            "analytical_grouping": self.analytical_grouping.value,
            "vector_search": self.vector_search.value,
            "raw_sql": self.raw_sql.value,
            "query_plan": self.query_plan.value,
            "calculated_fields": self.calculated_fields.value,
            "schema_tools": self.schema_tools.value,
        }
        for k, v in self.custom_overrides.items():
            res[k] = v.value if isinstance(v, FeatureTier) else str(v)
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EngineCapabilities:
        """Constructs an EngineCapabilities instance from a dictionary."""
        kwargs: Dict[str, Any] = {}
        overrides: Dict[str, FeatureTier] = {}

        def parse_tier(val: Any) -> FeatureTier:
            if isinstance(val, FeatureTier):
                return val
            if isinstance(val, bool):
                return FeatureTier.STANDARD if val else FeatureTier.DISABLED
            s = str(val).lower()
            if s in ("standard", "std"):
                return FeatureTier.STANDARD
            if s in ("advanced", "adv"):
                return FeatureTier.ADVANCED
            if s in ("disabled", "off", "false", "none"):
                return FeatureTier.DISABLED
            return FeatureTier.STANDARD

        known_fields = {
            "projections",
            "filters",
            "sorts",
            "joins",
            "distinct_limit",
            "visual_chart",
            "ctes",
            "window_functions",
            "analytical_grouping",
            "vector_search",
            "raw_sql",
            "query_plan",
            "calculated_fields",
            "schema_tools",
        }

        for k, v in data.items():
            if k in known_fields:
                kwargs[k] = parse_tier(v)
            elif k != "custom_overrides":
                overrides[k] = parse_tier(v)

        return cls(**kwargs, custom_overrides=overrides)

    @classmethod
    def default(cls) -> EngineCapabilities:
        """Default capabilities: standard core, advanced analytical/vector/pipeline features."""
        return cls()

    @classmethod
    def simple_only(cls) -> EngineCapabilities:
        """
        Disables all advanced features, enforcing simple/standard-only queries.
        """
        return cls(
            ctes=FeatureTier.DISABLED,
            window_functions=FeatureTier.DISABLED,
            analytical_grouping=FeatureTier.DISABLED,
            vector_search=FeatureTier.DISABLED,
            raw_sql=FeatureTier.DISABLED,
            query_plan=FeatureTier.DISABLED,
            calculated_fields=FeatureTier.DISABLED,
            schema_tools=FeatureTier.DISABLED,
        )

    @classmethod
    def power_user(cls) -> EngineCapabilities:
        """All features enabled as standard or advanced."""
        return cls()

    @classmethod
    def full(cls) -> EngineCapabilities:
        """All features enabled and elevated to standard tier."""
        return cls(
            ctes=FeatureTier.STANDARD,
            window_functions=FeatureTier.STANDARD,
            analytical_grouping=FeatureTier.STANDARD,
            vector_search=FeatureTier.STANDARD,
            raw_sql=FeatureTier.STANDARD,
            query_plan=FeatureTier.STANDARD,
            calculated_fields=FeatureTier.STANDARD,
            schema_tools=FeatureTier.STANDARD,
        )
