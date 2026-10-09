import { describe, it, expect } from "vitest";
import {
  withVectorSearch,
  createVectorQuery,
  isValidVectorSearch,
  withHybridSearch,
  createHybridQuery,
  isValidHybridSearch,
  type VectorSearchSpec,
  type HybridSearchSpec,
  type QuerySpec,
} from "../src";
import { invalid } from "./helpers";

describe("Vector Search TypeScript SDK & Utilities", () => {
  it("attaches vector search spec via withVectorSearch", () => {
    const baseSpec: QuerySpec = {
      table: "documents",
      columns: ["id", "title"],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit: 50,
    };

    const vs: VectorSearchSpec = {
      vector: [0.1, 0.2, 0.3],
      top_k: 5,
      metric: "cosine",
    };

    const updated = withVectorSearch(baseSpec, vs);
    expect(updated.vector_search).toBeDefined();
    expect(updated.vector_search?.vector).toEqual([0.1, 0.2, 0.3]);
    expect(updated.vector_search?.column).toBe("embedding");
    expect(updated.vector_search?.top_k).toBe(5);
    expect(updated.vector_search?.include_distances).toBe(true);
  });

  it("creates a standalone vector similarity query via createVectorQuery", () => {
    const query = createVectorQuery("articles", {
      vector: [0.5, -0.5],
      metric: "euclidean",
      top_k: 8,
      min_score: 0.9,
    });

    expect(query.table).toBe("articles");
    expect(query.columns).toEqual(["*"]);
    expect(query.limit).toBe(8);
    expect(query.vector_search?.vector).toEqual([0.5, -0.5]);
    expect(query.vector_search?.metric).toBe("euclidean");
    expect(query.vector_search?.min_score).toBe(0.9);
  });

  it("allows overriding options in createVectorQuery", () => {
    const query = createVectorQuery(
      "products",
      {
        vector: [1.0, 2.0],
        top_k: 15,
      },
      {
        columns: ["id", "sku", "price"],
        limit: 20,
      }
    );

    expect(query.columns).toEqual(["id", "sku", "price"]);
    expect(query.limit).toBe(20);
    expect(query.vector_search?.top_k).toBe(15);
  });

  it("validates vector search specifications with isValidVectorSearch", () => {
    expect(isValidVectorSearch({ vector: [0.1, 0.2] })).toBe(true);
    expect(isValidVectorSearch({ vector: [] })).toBe(false);
    expect(isValidVectorSearch(null)).toBe(false);
    expect(isValidVectorSearch(undefined)).toBe(false);
    expect(isValidVectorSearch({ vector: [0.1, NaN] })).toBe(false);
    expect(
      isValidVectorSearch({ vector: ["bad" as unknown as number] })
    ).toBe(false);
  });

  it("attaches hybrid search spec via withHybridSearch", () => {
    const baseSpec: QuerySpec = {
      table: "knowledge_base",
      columns: ["id", "title"],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit: 25,
    };

    const hs = {
      vector: [0.3, -0.1, 0.9],
      query_text: "machine learning pipelines",
      text_columns: ["title", "abstract"],
      alpha: 0.7,
      fusion: "rrf" as const,
      rrf_k: 60,
    };

    const updated = withHybridSearch(baseSpec, hs);
    expect(updated.hybrid_search).toBeDefined();
    expect(updated.hybrid_search?.vector).toEqual([0.3, -0.1, 0.9]);
    expect(updated.hybrid_search?.query_text).toBe("machine learning pipelines");
    expect(updated.hybrid_search?.text_columns).toEqual(["title", "abstract"]);
    expect(updated.hybrid_search?.alpha).toBe(0.7);
    expect(updated.hybrid_search?.fusion).toBe("rrf");
    expect(updated.hybrid_search?.top_k).toBe(10);
  });

  it("creates a standalone hybrid search query via createHybridQuery", () => {
    const query = createHybridQuery("articles", {
      vector: [0.12, 0.34],
      query_text: "high performance database",
      text_columns: ["body"],
      top_k: 12,
    });

    expect(query.table).toBe("articles");
    expect(query.limit).toBe(12);
    expect(query.hybrid_search?.vector_column).toBe("embedding");
    expect(query.hybrid_search?.query_text).toBe("high performance database");
    expect(query.hybrid_search?.top_k).toBe(12);
  });

  it("validates hybrid search specs with isValidHybridSearch", () => {
    expect(
      isValidHybridSearch({
        vector: [0.1, 0.2],
        query_text: "valid search",
        text_columns: ["content"],
      })
    ).toBe(true);

    expect(
      isValidHybridSearch({
        vector: [],
        query_text: "valid",
        text_columns: ["content"],
      })
    ).toBe(false);

    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: "",
        text_columns: ["content"],
      })
    ).toBe(false);

    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: "valid",
        text_columns: [],
      })
    ).toBe(false);

    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: "valid",
        text_columns: ["content"],
        alpha: 1.5,
      })
    ).toBe(false);

    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: "valid",
        text_columns: ["content"],
        alpha: -0.2,
      })
    ).toBe(false);

    expect(isValidHybridSearch(null)).toBe(false);
    expect(isValidHybridSearch(undefined)).toBe(false);
    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: "   ",
        text_columns: ["content"],
      })
    ).toBe(false);
    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: invalid<string>(123),
        text_columns: ["content"],
      })
    ).toBe(false);
    expect(
      isValidHybridSearch({
        vector: [0.1],
        query_text: "valid",
        text_columns: invalid<string[]>("not-an-array"),
      })
    ).toBe(false);
  });

  it("handles createVectorQuery and createHybridQuery default fallback branches and comprehensive options", () => {
    // 1. Vector query with default top_k and comprehensive options
    const vQuery = createVectorQuery(
      "docs",
      { vector: [0.1, 0.2] }, // no top_k
      {
        joins: [{ table: "tags", type: "INNER", on: [{ left: "docs.id", right: "tags.doc_id" }] }],
        filters: [{ column: "archived", op: "=", value: false }],
        filter_join: "OR",
        order_by: [{ column: "created_at", direction: "DESC" }],
        distinct: true,
        limit: 100,
      }
    );
    expect(vQuery.limit).toBe(100);
    expect(vQuery.distinct).toBe(true);
    expect(vQuery.filter_join).toBe("OR");
    expect(vQuery.vector_search?.top_k).toBe(10);

    // 2. Hybrid query with default top_k and comprehensive options
    const hQuery = createHybridQuery(
      "docs",
      {
        vector: [0.1, 0.2],
        query_text: "hello",
        text_columns: ["title"],
      }, // no top_k
      {
        columns: ["id", "title"],
        joins: [{ table: "tags", type: "LEFT", on: [{ left: "docs.id", right: "tags.doc_id" }] }],
        filters: [{ column: "status", op: "=", value: "active" }],
        filter_join: "AND",
        order_by: [{ column: "id", direction: "ASC" }],
        distinct: true,
        limit: 50,
      }
    );
    expect(hQuery.limit).toBe(50);
    expect(hQuery.columns).toEqual(["id", "title"]);
    expect(hQuery.distinct).toBe(true);
    expect(hQuery.hybrid_search?.top_k).toBe(10);
  });
});

