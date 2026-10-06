import type { QuerySpec, VectorSearchSpec } from "../types";

/**
 * Attaches or updates a vector search specification on an existing QuerySpec.
 */
export function withVectorSearch<Schema = any>(
  spec: QuerySpec<Schema>,
  vectorSearch: VectorSearchSpec
): QuerySpec<Schema> {
  return {
    ...spec,
    vector_search: {
      column: "embedding",
      top_k: 10,
      metric: "cosine",
      include_distances: true,
      ...vectorSearch,
    },
  };
}

/**
 * Creates a standalone vector similarity QuerySpec for nearest-neighbor queries.
 */
export function createVectorQuery(
  table: string,
  vectorSearch: VectorSearchSpec,
  options?: Partial<Omit<QuerySpec, "table" | "vector_search">>
): QuerySpec {
  const topK = vectorSearch.top_k ?? 10;
  return {
    table,
    columns: options?.columns ?? ["*"],
    joins: options?.joins ?? [],
    filters: options?.filters ?? [],
    filter_join: options?.filter_join ?? "AND",
    order_by: options?.order_by ?? [],
    distinct: options?.distinct ?? false,
    limit: options?.limit ?? topK,
    vector_search: {
      column: "embedding",
      top_k: topK,
      metric: "cosine",
      include_distances: true,
      ...vectorSearch,
    },
    ...options,
  };
}

/**
 * Validates whether a vector search spec contains a non-empty numeric vector.
 */
export function isValidVectorSearch(
  vs: VectorSearchSpec | null | undefined
): boolean {
  if (!vs || !Array.isArray(vs.vector) || vs.vector.length === 0) {
    return false;
  }
  return vs.vector.every((num) => typeof num === "number" && !isNaN(num));
}
