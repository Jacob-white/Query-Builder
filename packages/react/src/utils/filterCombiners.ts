/**
 * Shared filter-combiner resolution.
 *
 * Every place that turns filters + a `filterJoin` into SQL or into a spec (compiler, specToState,
 * loadSpec) must go through these helpers so that the generated SQL, the emitted per-filter
 * `combiner`s and the aggregate `filter_join` can never disagree - and so that arbitrary strings
 * are never interpolated into SQL.
 */

export type FilterCombiner = "AND" | "OR";

/** Coerces any input to exactly `"AND"` or `"OR"` (case-insensitive, trimmed); otherwise `fallback`. */
export function normalizeCombiner(value: unknown, fallback: FilterCombiner = "AND"): FilterCombiner {
  if (typeof value === "string") {
    const upper = value.trim().toUpperCase();
    if (upper === "AND" || upper === "OR") return upper;
  }
  return fallback;
}

export interface ResolvedFilterCombiners {
  /** Effective, normalized combiner for each input filter (same order and length). */
  combiners: FilterCombiner[];
  /** Aggregate join: `"OR"` iff any effective combiner is OR, else `"AND"`. */
  filterJoin: FilterCombiner;
  /** True when any effective combiner is OR (every emitted filter must then carry a combiner). */
  hasOr: boolean;
}

/**
 * Resolves the effective combiner of each filter. A filter whose own `combiner` is missing or
 * invalid inherits the (normalized) `filterJoin`. Pass ONLY the filters that will actually be
 * emitted so the aggregate matches the emitted combiners.
 */
export function resolveFilterCombiners(
  filters: ReadonlyArray<{ combiner?: unknown }>,
  filterJoin?: unknown,
): ResolvedFilterCombiners {
  const fallback = normalizeCombiner(filterJoin, "AND");
  const combiners = filters.map((f) => normalizeCombiner(f?.combiner, fallback));
  const hasOr = filters.length > 0 ? combiners.includes("OR") : fallback === "OR";
  return { combiners, filterJoin: hasOr ? "OR" : "AND", hasOr };
}
