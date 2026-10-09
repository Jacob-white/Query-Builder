import type { QuerySpec } from "../../src/types";

/**
 * Deliberately-incomplete QuerySpec: tests exercising the component's runtime
 * normalization of specs that omit fields (joins, filters, order_by, ...).
 * Unlike `makeSpec`, no defaults are filled in, so the runtime behaviour under
 * test is unchanged. The cast is intentional and local to this helper.
 */
export function partialSpec(spec: Partial<QuerySpec> & { table: string }): QuerySpec {
  return spec as QuerySpec;
}

/** Loose dictionary-style schema (`columns` keyed by name with `data_type`) as accepted by the AI/NLQ surface. */
export type SchemaDict = {
  tables: Record<
    string,
    {
      columns: Record<string, { data_type: string }>;
      foreign_keys?: { target_table: string; target_column: string; column: string }[];
    }
  >;
};
