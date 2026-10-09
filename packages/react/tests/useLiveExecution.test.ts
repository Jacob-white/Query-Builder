import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useLiveExecution, type LiveExecutionResult } from "../src/hooks/useLiveExecution";

describe("useLiveExecution hook", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("initializes with default states", () => {
    const { result } = renderHook(() => useLiveExecution());

    expect(result.current.isExecuting).toBe(false);
    expect(result.current.executionTimeMs).toBeNull();
    expect(result.current.results).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.connectionStatus).toBe("idle");
    expect(result.current.connectionLatencyMs).toBeNull();
    expect(result.current.activeExecutionId).toBeNull();
  });

  it("initializes with initialResults when provided", () => {
    const initial: LiveExecutionResult = {
      columns: ["id", "val"],
      rows: [{ id: 1, val: "A" }],
      rowCount: 1,
      executionTimeMs: 42,
    };
    const { result } = renderHook(() =>
      useLiveExecution({ initialResults: initial })
    );

    expect(result.current.results).toEqual(initial);
    expect(result.current.executionTimeMs).toBe(42);
  });

  it("executes raw SQL query successfully", async () => {
    const onSuccess = vi.fn();
    const mockResponse = {
      columns: ["id", "name"],
      rows: [
        { id: 1, name: "Alice" },
        { id: 2, name: "Bob" },
      ],
      count: 2,
      execution_id: "exec_custom_123",
      duration_ms: 18,
      dialect: "sqlite",
      truncated: false,
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        apiUrl: "/custom/api",
        connectionId: "main_db",
        dialect: "sqlite",
        fetchFn: mockFetch as unknown as typeof fetch,
        onSuccess,
      })
    );

    let execResult = null as LiveExecutionResult | null;
    await act(async () => {
      execResult = await result.current.executeQuery("SELECT * FROM users", {
        limit: 10,
        params: ["active"],
      });
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/custom/api/query/execute",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: expect.stringContaining('"sql":"SELECT * FROM users"'),
      })
    );

    expect(execResult).not.toBeNull();
    expect(execResult?.rowCount).toBe(2);
    expect(execResult?.columns).toEqual(["id", "name"]);
    expect(execResult?.executionTimeMs).toBe(18);
    expect(result.current.isExecuting).toBe(false);
    expect(result.current.activeExecutionId).toBeNull();
    expect(onSuccess).toHaveBeenCalledWith(execResult);
  });

  it("executes structured QuerySpec object and infers columns from rows if columns omitted", async () => {
    const mockResponse = {
      rows: [{ colA: 100, colB: "hello" }],
      // columns intentionally omitted
      execution_id: "exec_query_spec",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockResponse,
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let execResult = null as LiveExecutionResult | null;
    await act(async () => {
      execResult = await result.current.executeQuery({
        table: "orders",
        columns: ["colA", "colB"],
      });
    });

    expect(execResult?.columns).toEqual(["colA", "colB"]);
    expect(execResult?.rowCount).toBe(1);
  });

  it("handles empty rows and null data gracefully", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => null,
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let execResult = null as LiveExecutionResult | null;
    await act(async () => {
      execResult = await result.current.executeQuery("SELECT 1 WHERE 1=0");
    });

    expect(execResult?.columns).toEqual([]);
    expect(execResult?.rows).toEqual([]);
    expect(execResult?.rowCount).toBe(0);
  });

  it("aborts active execution if a new query is triggered while running", async () => {
    let callCount = 0;
    const mockFetch = vi.fn().mockImplementation(() => {
      callCount++;
      return new Promise((resolve) => {
        setTimeout(() => {
          resolve({
            ok: true,
            status: 200,
            json: async () => ({
              columns: ["id"],
              rows: [{ id: callCount }],
              count: 1,
            }),
          });
        }, 50);
      });
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    act(() => {
      void result.current.executeQuery("SELECT 1");
    });
    expect(result.current.isExecuting).toBe(true);

    let secondResult = null as LiveExecutionResult | null;
    await act(async () => {
      secondResult = await result.current.executeQuery("SELECT 2");
    });

    expect(secondResult?.rows).toEqual([{ id: 2 }]);
  });

  it("handles HTTP error with structured error.message", async () => {
    const onError = vi.fn();
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({
        error: { message: "Syntax error in SQL near FROM" },
      }),
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
        onError,
      })
    );

    let res = null as LiveExecutionResult | null;
    await act(async () => {
      res = await result.current.executeQuery("INVALID SQL");
    });

    expect(res).toBeNull();
    expect(result.current.error).toBe("Syntax error in SQL near FROM");
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: "Syntax error in SQL near FROM" })
    );
  });

  it("handles HTTP error with top-level message", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        message: "Forbidden access to database",
      }),
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    await act(async () => {
      await result.current.executeQuery("SELECT 1");
    });

    expect(result.current.error).toBe("Forbidden access to database");
  });

  it("handles HTTP error with non-JSON response", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("Invalid JSON");
      },
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    await act(async () => {
      await result.current.executeQuery("SELECT 1");
    });

    expect(result.current.error).toBe("Query execution failed with status 502");
  });

  it("handles unexpected network throw", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error("Network connection dropped"));

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    await act(async () => {
      await result.current.executeQuery("SELECT 1");
    });

    expect(result.current.error).toBe("Network connection dropped");
  });

  it("handles non-Error thrown object", async () => {
    const mockFetch = vi.fn().mockRejectedValue("String error thrown");

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    await act(async () => {
      await result.current.executeQuery("SELECT 1");
    });

    expect(result.current.error).toBe("An unknown execution error occurred.");
  });

  it("cancels execution successfully when query is running", async () => {
    let cancelCalled = false;
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/connections/cancel")) {
        cancelCalled = true;
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ cancelled: true }),
        });
      }
      return new Promise((resolve) => {
        setTimeout(() => {
          resolve({
            ok: true,
            status: 200,
            json: async () => ({ columns: [], rows: [] }),
          });
        }, 100);
      });
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    act(() => {
      void result.current.executeQuery("SELECT pg_sleep(10)");
    });

    expect(result.current.isExecuting).toBe(true);

    let cancelled = false;
    await act(async () => {
      cancelled = await result.current.cancelExecution();
    });

    expect(cancelled).toBe(true);
    expect(cancelCalled).toBe(true);
    expect(result.current.isExecuting).toBe(false);
    expect(result.current.activeExecutionId).toBeNull();
  });

  it("handles cancel execution when cancel endpoint fails", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/connections/cancel")) {
        return Promise.reject(new Error("Cancel endpoint unreachable"));
      }
      return new Promise(() => {}); // never resolves
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    act(() => {
      void result.current.executeQuery("SELECT 1");
    });

    let cancelled = false;
    await act(async () => {
      cancelled = await result.current.cancelExecution();
    });

    expect(cancelled).toBe(true);
    expect(result.current.isExecuting).toBe(false);
  });

  it("cancels when no active execution exists returns false", async () => {
    const { result } = renderHook(() => useLiveExecution());

    let cancelled = false;
    await act(async () => {
      cancelled = await result.current.cancelExecution();
    });

    expect(cancelled).toBe(false);
  });

  it("tests connection successfully", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        healthy: true,
        dialect: "sqlite",
        latency_ms: 12,
      }),
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        connectionId: "test_db",
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let success = false;
    await act(async () => {
      success = await result.current.testConnection();
    });

    expect(success).toBe(true);
    expect(result.current.connectionStatus).toBe("connected");
    expect(result.current.connectionLatencyMs).toBe(12);
  });

  it("tests connection with targetConnId override and calculates fallback latency", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        healthy: true,
        dialect: "postgres",
        // latency_ms omitted
      }),
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let success = false;
    await act(async () => {
      success = await result.current.testConnection("pg_override");
    });

    expect(success).toBe(true);
    expect(result.current.connectionStatus).toBe("connected");
    expect(result.current.connectionLatencyMs).toBeTypeOf("number");
  });

  it("tests connection when server reports healthy: false", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        healthy: false,
        error: "Database down",
      }),
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let success = true;
    await act(async () => {
      success = await result.current.testConnection();
    });

    expect(success).toBe(false);
    expect(result.current.connectionStatus).toBe("error");
    expect(result.current.connectionLatencyMs).toBeNull();
  });

  it("tests connection when endpoint returns HTTP error", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    });

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let success = true;
    await act(async () => {
      success = await result.current.testConnection();
    });

    expect(success).toBe(false);
    expect(result.current.connectionStatus).toBe("error");
  });

  it("tests connection when network throws", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new Error("Connection refused"));

    const { result } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    let success = true;
    await act(async () => {
      success = await result.current.testConnection();
    });

    expect(success).toBe(false);
    expect(result.current.connectionStatus).toBe("error");
  });

  it("clears results and error state", () => {
    const initial: LiveExecutionResult = {
      columns: ["id"],
      rows: [{ id: 1 }],
      rowCount: 1,
      executionTimeMs: 10,
    };

    const { result } = renderHook(() =>
      useLiveExecution({ initialResults: initial })
    );

    expect(result.current.results).not.toBeNull();

    act(() => {
      result.current.clearResults();
    });

    expect(result.current.results).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.executionTimeMs).toBeNull();
  });

  it("allows setting results directly", () => {
    const { result } = renderHook(() => useLiveExecution());

    const custom: LiveExecutionResult = {
      columns: ["a"],
      rows: [{ a: 10 }],
      rowCount: 1,
    };

    act(() => {
      result.current.setResults(custom);
    });

    expect(result.current.results).toEqual(custom);
  });

  it("aborts active execution on unmount", () => {
    const mockFetch = vi.fn().mockImplementation(() => new Promise(() => {}));

    const { result, unmount } = renderHook(() =>
      useLiveExecution({
        fetchFn: mockFetch as unknown as typeof fetch,
      })
    );

    act(() => {
      void result.current.executeQuery("SELECT 1");
    });

    expect(result.current.isExecuting).toBe(true);

    unmount();
    // Verify no unhandled exceptions on unmount
  });

  it("triggers timeout when execution exceeds timeoutMs", async () => {
    vi.useFakeTimers();
    try {
      const mockFetch = vi.fn().mockImplementation((_url, init) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const err = new Error("The operation was aborted");
            err.name = "AbortError";
            reject(err);
          });
        });
      });

      const { result } = renderHook(() =>
        useLiveExecution({
          fetchFn: mockFetch as unknown as typeof fetch,
        })
      );

      let promise: Promise<any>;
      act(() => {
        promise = result.current.executeQuery("SELECT 1", { timeoutMs: 50 });
      });

      act(() => {
        vi.advanceTimersByTime(100);
      });

      await act(async () => {
        await promise;
      });

      expect(result.current.error).toBe("Query execution was cancelled.");
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses globalThis.fetch when fetchFn is not provided", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ columns: ["id"], rows: [{ id: 1 }], count: 1 }),
    });

    const { result } = renderHook(() => useLiveExecution());

    let res = null as LiveExecutionResult | null;
    await act(async () => {
      res = await result.current.executeQuery("SELECT 1");
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/query/execute",
      expect.anything()
    );
    expect(res?.rowCount).toBe(1);
  });
});


