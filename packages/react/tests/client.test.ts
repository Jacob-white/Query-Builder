import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createQueryBuilderClient,
  createQuery,
  QueryBuilderApiError,
  FluentQuery,
} from "../src/client/index";
import type { QuerySpec, SchemaSnapshot, QueryResultData } from "../src/types";
import { makeSpec } from "./helpers";

describe("QueryBuilderClient", () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("normalizes trailing slashes in baseUrl and sets default timeout", () => {
    const client = createQueryBuilderClient({
      baseUrl: "https://api.example.com/qb///",
      fetchFn: mockFetch,
    });
    expect(client).toBeDefined();
    expect(typeof client.getSchema).toBe("function");
    expect(typeof client.compile).toBe("function");
    expect(typeof client.validate).toBe("function");
    expect(typeof client.execute).toBe("function");
    expect(typeof client.export).toBe("function");
    expect(typeof client.query).toBe("function");
  });

  it("throws if globalThis.fetch is missing and fetchFn is not supplied", () => {
    const originalFetch = globalThis.fetch;
    try {
      Reflect.set(globalThis, "fetch", undefined);
      expect(() => createQueryBuilderClient({ baseUrl: "/api" })).toThrow(
        /globalThis\.fetch is not defined/,
      );
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("applies static headers and dynamic headers function", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tables: {} }),
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      headers: async () => ({ "X-Custom-Tenant": "tenant_123" }),
      fetchFn: mockFetch,
    });

    await client.getSchema();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/qb/schema");
    expect(init.headers["X-Custom-Tenant"]).toBe("tenant_123");
  });

  it("applies token with Bearer prefix if not already present", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tables: {} }),
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      token: "secret_token_abc",
      fetchFn: mockFetch,
    });

    await client.getSchema();

    const [, init] = mockFetch.mock.calls[0];
    expect(init.headers["Authorization"]).toBe("Bearer secret_token_abc");
  });

  it("preserves custom authorization header if already contains a scheme", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tables: {} }),
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      token: () => "Token my_custom_django_token",
      fetchFn: mockFetch,
    });

    await client.getSchema();

    const [, init] = mockFetch.mock.calls[0];
    expect(init.headers["Authorization"]).toBe("Token my_custom_django_token");
  });

  it("throws QueryBuilderApiError with HTTP status and parsed body on failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({ error: "Tenant quota exceeded", code: "QUOTA_EXCEEDED" }),
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      fetchFn: mockFetch,
    });

    const spec: QuerySpec = makeSpec({ table: "users", columns: ["id"] });

    await expect(client.execute(spec)).rejects.toThrow(QueryBuilderApiError);
    try {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        json: async () => ({ error: "Tenant quota exceeded", code: "QUOTA_EXCEEDED" }),
      });
      await client.execute(spec);
    } catch (err) {
      expect(err instanceof QueryBuilderApiError).toBe(true);
      const apiErr = err as QueryBuilderApiError;
      expect(apiErr.status).toBe(403);
      expect(apiErr.statusText).toBe("Forbidden");
      expect((apiErr.data as { code: string }).code).toBe("QUOTA_EXCEEDED");
      expect(apiErr.message).toContain("403: Forbidden");
    }
  });

  it("handles non-JSON error response from backend gracefully", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: async () => {
        throw new Error("Invalid JSON");
      },
      text: async () => "<html>502 Bad Gateway</html>",
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      fetchFn: mockFetch,
    });

    await expect(client.getSchema()).rejects.toThrow(QueryBuilderApiError);
  });

  it("aborts requests using caller signal", async () => {
    const controller = new AbortController();
    mockFetch.mockImplementationOnce((_url, init) => {
      return new Promise((_, reject) => {
        if (init.signal) {
          init.signal.addEventListener("abort", () => {
            const err = new Error("This operation was aborted");
            err.name = "AbortError";
            reject(err);
          });
        }
      });
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      fetchFn: mockFetch,
    });

    setTimeout(() => controller.abort(), 10);

    await expect(client.getSchema({ signal: controller.signal })).rejects.toThrow();
  });

  it("times out requests that exceed timeoutMs", async () => {
    mockFetch.mockImplementationOnce((_url, init) => {
      return new Promise((_, reject) => {
        if (init.signal) {
          init.signal.addEventListener("abort", () => {
            const err = new Error("Request timed out");
            err.name = "AbortError";
            reject(err);
          });
        }
      });
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      timeoutMs: 20,
      fetchFn: mockFetch,
    });

    await expect(client.getSchema()).rejects.toThrow(/timed out|aborted/i);
  });

  it("calls getSchema, compile, validate, execute, and export endpoints with proper methods and bodies", async () => {
    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      fetchFn: mockFetch,
    });

    // 1. getSchema
    const mockSchema: SchemaSnapshot = { tables: { users: { name: "users", columns: [] } } };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockSchema });
    const schema = await client.getSchema();
    expect(schema).toEqual(mockSchema);
    expect(mockFetch.mock.calls[0][0]).toBe("/api/qb/schema");
    expect(mockFetch.mock.calls[0][1].method).toBe("GET");

    // 2. compile
    const mockSpec: QuerySpec = makeSpec({ table: "users", columns: ["id", "email"] });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sql: 'SELECT id, email FROM "users"', params: [] }),
    });
    const compileRes = await client.compile(mockSpec, "postgres");
    expect(compileRes.sql).toContain("SELECT");
    expect(mockFetch.mock.calls[1][0]).toBe("/api/qb/compile");
    expect(mockFetch.mock.calls[1][1].method).toBe("POST");
    expect(JSON.parse(mockFetch.mock.calls[1][1].body)).toEqual({
      spec: mockSpec,
      dialect: "postgres",
    });

    // 3. validate
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ valid: true, is_read_only: true, tables: ["users"] }),
    });
    const valRes = await client.validate("SELECT * FROM users");
    expect(valRes.valid).toBe(true);
    expect(mockFetch.mock.calls[2][0]).toBe("/api/qb/validate");
    expect(mockFetch.mock.calls[2][1].method).toBe("POST");

    // 4. execute with spec
    const mockResult: QueryResultData = {
      columns: ["id"],
      rows: [{ id: 1 }],
      count: 1,
      latency_ms: 12,
    };
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockResult });
    const execRes = await client.execute(mockSpec);
    expect(execRes.rows).toHaveLength(1);
    expect(mockFetch.mock.calls[3][0]).toBe("/api/qb/execute");
    expect(mockFetch.mock.calls[3][1].method).toBe("POST");

    // 5. execute with raw sql
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockResult });
    await client.execute({ sql: "SELECT 1", params: [42] });
    expect(JSON.parse(mockFetch.mock.calls[4][1].body)).toEqual({
      sql: "SELECT 1",
      params: [42],
    });

    // 6. export
    const blobContent = "id,name\n1,Alice";
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob([blobContent], { type: "text/csv" }),
    });
    const blob = await client.export(mockSpec, "csv");
    expect(blob).toBeInstanceOf(Blob);
    expect(mockFetch.mock.calls[5][0]).toBe("/api/qb/export");
    expect(JSON.parse(mockFetch.mock.calls[5][1].body)).toEqual({
      spec: mockSpec,
      format: "csv",
    });
  });
});

describe("FluentQuery Builder", () => {
  it("constructs complex queries fluently and serializes to QuerySpec", () => {
    const q = createQuery("users")
      .select(["id", "name", { column: "orders.amount", agg: "SUM", alias: "total_revenue" }])
      .join("orders", "id", "=", "user_id", "INNER JOIN")
      .where("users.status", "=", "ACTIVE")
      .where("orders.amount", ">", 100)
      .groupBy(["id", "name"])
      .having("total_revenue", ">", 500)
      .orderBy("total_revenue", "DESC")
      .limit(10)
      .offset(20)
      .distinct(true);

    const spec = q.toSpec();

    expect(spec.table).toBe("users");
    expect(spec.columns).toHaveLength(3);
    expect(spec.joins).toHaveLength(1);
    expect(spec.joins?.[0].table).toBe("orders");
    expect(spec.joins?.[0].type).toBe("INNER JOIN");
    expect(spec.filters).toHaveLength(2);
    expect(spec.filters?.[0]).toEqual({ column: "users.status", op: "=", value: "ACTIVE" });
    expect(spec.group_by).toEqual(["id", "name"]);
    expect(spec.having).toHaveLength(1);
    expect(spec.order_by).toEqual([{ column: "total_revenue", direction: "DESC" }]);
    expect(spec.limit).toBe(10);
    expect(spec.offset).toBe(20);
    expect(spec.distinct).toBe(true);
  });

  it("supports client.query() fluent initiation and .execute(client) chaining", async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        columns: [{ name: "id", type: "integer" }],
        rows: [{ id: 1 }],
        totalRows: 1,
        executionTimeMs: 5,
      }),
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      fetchFn: mockFetch,
    });

    const res = await client
      .query("products")
      .select(["id", "title"])
      .where("in_stock", "=", true)
      .limit(5)
      .execute(); // Works without passing client explicitly

    expect(res.rows).toEqual([{ id: 1 }]);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/qb/execute");
    const body = JSON.parse(init.body);
    expect(body.spec.table).toBe("products");
    expect(body.spec.limit).toBe(5);
  });

  it("cleans up abort event listener from AbortSignal after request completes", async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tables: {} }),
    });

    const client = createQueryBuilderClient({
      baseUrl: "/api/qb",
      fetchFn: mockFetch,
    });

    const controller = new AbortController();
    const addEventListenerSpy = vi.spyOn(controller.signal, "addEventListener");
    const removeEventListenerSpy = vi.spyOn(controller.signal, "removeEventListener");

    await client.getSchema({ signal: controller.signal });

    expect(addEventListenerSpy).toHaveBeenCalledWith("abort", expect.any(Function));
    expect(removeEventListenerSpy).toHaveBeenCalledWith("abort", expect.any(Function));
  });
});
