import { describe, it, expect } from "vitest";
import {
  withVectorSearch,
  createVectorQuery,
  isValidVectorSearch,
  type VectorSearchSpec,
  type QuerySpec,
} from "../src";

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
});
