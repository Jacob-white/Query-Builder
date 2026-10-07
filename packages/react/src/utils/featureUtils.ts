/**
 * Feature Flags & Capabilities Evaluation Utilities.
 * ==================================================
 * Resolves feature tiers (standard, advanced, disabled), handles presets,
 * evaluates UI visibility, and detects active advanced clauses in query state.
 */

import type {
  FeatureKey,
  FeatureTier,
  FeatureConfig,
  FeaturePreset,
  ResolvedFeatureMap,
} from "../types";

export const ALL_FEATURE_KEYS: FeatureKey[] = [
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
];

export const DEFAULT_FEATURE_CONFIG: ResolvedFeatureMap = {
  projections: "standard",
  filters: "standard",
  sorts: "standard",
  joins: "standard",
  distinct_limit: "standard",
  visual_chart: "standard",
  ctes: "advanced",
  window_functions: "advanced",
  analytical_grouping: "advanced",
  vector_search: "advanced",
  raw_sql: "advanced",
  query_plan: "advanced",
  calculated_fields: "advanced",
  schema_tools: "advanced",
};

export const FEATURE_PRESETS: Record<FeaturePreset, ResolvedFeatureMap> = {
  simple: {
    projections: "standard",
    filters: "standard",
    sorts: "standard",
    joins: "standard",
    distinct_limit: "standard",
    visual_chart: "standard",
    ctes: "disabled",
    window_functions: "disabled",
    analytical_grouping: "disabled",
    vector_search: "disabled",
    raw_sql: "disabled",
    query_plan: "disabled",
    calculated_fields: "disabled",
    schema_tools: "disabled",
  },
  standard: {
    ...DEFAULT_FEATURE_CONFIG,
  },
  power_user: {
    ...DEFAULT_FEATURE_CONFIG,
  },
  all: {
    projections: "standard",
    filters: "standard",
    sorts: "standard",
    joins: "standard",
    distinct_limit: "standard",
    visual_chart: "standard",
    ctes: "standard",
    window_functions: "standard",
    analytical_grouping: "standard",
    vector_search: "standard",
    raw_sql: "standard",
    query_plan: "standard",
    calculated_fields: "standard",
    schema_tools: "standard",
  },
};

/**
 * Normalizes a boolean or string tier into a canonical FeatureTier.
 */
export function normalizeTier(val: FeatureTier | boolean | string | undefined): FeatureTier {
  if (val === true) return "standard";
  if (val === false) return "disabled";
  if (typeof val === "string") {
    const s = val.toLowerCase();
    if (s === "standard" || s === "std") return "standard";
    if (s === "advanced" || s === "adv") return "advanced";
    if (s === "disabled" || s === "off" || s === "none") return "disabled";
  }
  return "standard";
}

/**
 * Resolves a unified feature map by combining base presets, server capabilities,
 * and user-supplied prop overrides.
 */
export function resolveFeatureConfig(
  features?: FeatureConfig,
  preset?: FeaturePreset,
  serverCapabilities?: Record<string, string> | null,
): ResolvedFeatureMap {
  const basePreset = preset ? FEATURE_PRESETS[preset] || DEFAULT_FEATURE_CONFIG : DEFAULT_FEATURE_CONFIG;
  const resolved: ResolvedFeatureMap = { ...basePreset };

  // Overlay server capabilities if introspected
  if (serverCapabilities && typeof serverCapabilities === "object") {
    for (const key of ALL_FEATURE_KEYS) {
      if (key in serverCapabilities) {
        resolved[key] = normalizeTier(serverCapabilities[key]);
      }
    }
  }

  // Overlay explicit props
  if (features && typeof features === "object") {
    for (const key of ALL_FEATURE_KEYS) {
      if (key in features) {
        resolved[key] = normalizeTier(features[key]);
      }
    }
  }

  return resolved;
}

/**
 * Determines whether a given feature should be visible in the UI.
 */
export function isFeatureVisible(
  feature: FeatureKey,
  resolvedFeatures: ResolvedFeatureMap,
  isAdvancedMode: boolean,
): boolean {
  const tier = resolvedFeatures[feature] || "standard";
  if (tier === "disabled") return false;
  if (tier === "standard") return true;
  if (tier === "advanced") return Boolean(isAdvancedMode);
  return true;
}

export interface ActiveAdvancedClause {
  key: FeatureKey;
  label: string;
}

/**
 * Inspects the current visual query state and identifies any active clauses
 * that are classified as "advanced" features.
 */
export function detectActiveAdvancedClauses(
  state: {
    ctes?: any[];
    windowFunctions?: any[];
    vectorSearch?: any;
    hybridSearch?: any;
    selectedColumns?: Record<string, any>;
    rollup?: any;
    cube?: any;
    groupingSets?: any;
    pivot?: any;
  },
  resolvedFeatures: ResolvedFeatureMap,
): ActiveAdvancedClause[] {
  const active: ActiveAdvancedClause[] = [];

  if (state.ctes && state.ctes.length > 0 && resolvedFeatures.ctes === "advanced") {
    active.push({ key: "ctes", label: `CTE Pipeline (${state.ctes.length})` });
  }

  if (
    state.windowFunctions &&
    state.windowFunctions.length > 0 &&
    resolvedFeatures.window_functions === "advanced"
  ) {
    active.push({
      key: "window_functions",
      label: `Window Functions (${state.windowFunctions.length})`,
    });
  }

  if (
    (state.vectorSearch || state.hybridSearch) &&
    resolvedFeatures.vector_search === "advanced"
  ) {
    active.push({ key: "vector_search", label: "Vector / Hybrid Search" });
  }

  if (
    (state.rollup || state.cube || state.groupingSets || state.pivot) &&
    resolvedFeatures.analytical_grouping === "advanced"
  ) {
    active.push({ key: "analytical_grouping", label: "Analytical Grouping" });
  }

  if (state.selectedColumns && resolvedFeatures.calculated_fields === "advanced") {
    const hasCalculated = Object.values(state.selectedColumns).some(
      (c) => c && (Boolean(c.rawExpression) || Boolean((c as any).expression)),
    );
    if (hasCalculated) {
      active.push({ key: "calculated_fields", label: "Calculated Expressions" });
    }
  }

  return active;
}
