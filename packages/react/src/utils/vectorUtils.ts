import type { QuerySpec, VectorSearchSpec, HybridSearchSpec, DatabaseSchemaDefinition } from "../types";

/**
 * Attaches or updates a vector search specification on an existing QuerySpec.
 */
export function withVectorSearch<Schema = DatabaseSchemaDefinition>(
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

/**
 * Attaches or updates a hybrid search specification on an existing QuerySpec.
 */
export function withHybridSearch<Schema = DatabaseSchemaDefinition>(
  spec: QuerySpec<Schema>,
  hybridSearch: HybridSearchSpec
): QuerySpec<Schema> {
  return {
    ...spec,
    hybrid_search: {
      vector_column: "embedding",
      alpha: 0.5,
      fusion: "rrf",
      rrf_k: 60,
      top_k: 10,
      metric: "cosine",
      include_scores: true,
      ...hybridSearch,
    },
  };
}

/**
 * Creates a standalone hybrid search QuerySpec combining dense vector & sparse text search.
 */
export function createHybridQuery(
  table: string,
  hybridSearch: HybridSearchSpec,
  options?: Partial<Omit<QuerySpec, "table" | "hybrid_search">>
): QuerySpec {
  const topK = hybridSearch.top_k ?? 10;
  return {
    table,
    columns: options?.columns ?? ["*"],
    joins: options?.joins ?? [],
    filters: options?.filters ?? [],
    filter_join: options?.filter_join ?? "AND",
    order_by: options?.order_by ?? [],
    distinct: options?.distinct ?? false,
    limit: options?.limit ?? topK,
    hybrid_search: {
      vector_column: "embedding",
      alpha: 0.5,
      fusion: "rrf",
      rrf_k: 60,
      top_k: topK,
      metric: "cosine",
      include_scores: true,
      ...hybridSearch,
    },
    ...options,
  };
}

/**
 * Validates whether a hybrid search spec is properly configured with vectors and text.
 */
export function isValidHybridSearch(
  hs: HybridSearchSpec | null | undefined
): boolean {
  if (!hs) return false;
  if (!isValidVectorSearch({ vector: hs.vector })) return false;
  if (typeof hs.query_text !== "string" || hs.query_text.trim().length === 0) return false;
  if (!Array.isArray(hs.text_columns) || hs.text_columns.length === 0) return false;
  if (hs.alpha !== undefined && (hs.alpha < 0 || hs.alpha > 1)) return false;
  return true;
}

