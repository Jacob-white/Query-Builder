import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useClientOlap } from "../src/hooks/useClientOlap";
import { resetClientOlapEngine } from "../src/drivers/duckdbDriver";
import type { DuckDBQueryResult } from "../src/types";

describe("useClientOlap Hook", () => {
  beforeEach(() => {
    resetClientOlapEngine();
  });

  it("initializes with ready state and empty tables", () => {
    const { result } = renderHook(() => useClientOlap());
    expect(result.current.engine.isReady).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(Object.keys(result.current.tables)).toHaveLength(0);
  });

  it("ingests CSV and updates tables and schemaSnapshot", async () => {
    const { result } = renderHook(() => useClientOlap());

    await act(async () => {
      await result.current.ingestCsv("products", "id,name,price\n1,Alpha,10.5\n2,Beta,20.0");
    });

    expect(result.current.tables["products"]).toBeDefined();
    expect(result.current.tables["products"].rowCount).toBe(2);
    expect(result.current.activeTable).toBe("products");
    expect(result.current.schemaSnapshot.tables["products"]).toBeDefined();
  });

  it("ingests JSON and caches backend query results", async () => {
    const { result } = renderHook(() => useClientOlap());

    await act(async () => {
      await result.current.ingestJson("users", [{ id: 10, role: "admin" }]);
      await result.current.cacheQueryResults("cached_stats", [{ count: 100 }]);
    });

    expect(result.current.tables["users"]).toBeDefined();
    expect(result.current.tables["cached_stats"]).toBeDefined();
    expect(result.current.tables["cached_stats"].sourceType).toBe("query_cache");
  });

  it("executes queries through hook", async () => {
    const { result } = renderHook(() => useClientOlap());

    await act(async () => {
      await result.current.ingestCsv("items", "id,val\n1,100\n2,200");
    });

    let qRes: DuckDBQueryResult | undefined;
    await act(async () => {
      qRes = await result.current.query("SELECT * FROM items WHERE val > 150;");
    });

    expect(qRes?.rowCount).toBe(1);
    expect(qRes?.rows[0].id).toBe(2);
  });

  it("handles dropTable, clear, and setActiveTable", async () => {
    const { result } = renderHook(() => useClientOlap());

    await act(async () => {
      await result.current.ingestCsv("t1", "id\n1");
      await result.current.ingestCsv("t2", "id\n2");
    });

    act(() => {
      result.current.setActiveTable("t1");
    });
    expect(result.current.activeTable).toBe("t1");

    await act(async () => {
      await result.current.dropTable("t1");
    });
    expect(result.current.tables["t1"]).toBeUndefined();

    await act(async () => {
      await result.current.clear();
    });
    expect(Object.keys(result.current.tables)).toHaveLength(0);
  });

  it("ingests local File object", async () => {
    const { result } = renderHook(() => useClientOlap());
    const file = new File(["id,num\n1,42"], "numbers.csv", { type: "text/csv" });

    await act(async () => {
      await result.current.ingestFile(file);
    });

    expect(result.current.tables["numbers"]).toBeDefined();
  });

  it("catches and sets error state on invalid input", async () => {
    const { result } = renderHook(() => useClientOlap());

    await act(async () => {
      try {
        await result.current.ingestCsv("bad", "");
      } catch {
        // Expected
      }
    });

    expect(result.current.error).not.toBeNull();
    expect(result.current.error?.message).toContain("empty");
  });
});
