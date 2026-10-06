import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useNlqQuery } from "../src/hooks/useNlqQuery";
import type { QuerySpec } from "../src/types";

describe("useNlqQuery hook", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  const mockQuerySpec: QuerySpec = {
    table: "users",
    columns: ["id", "name"],
    joins: [],
    filters: [{ column: "status", op: "=", value: "active" }],
    filter_join: "AND",
    order_by: [],
    limit: 50,
    distinct: false,
  };

  it("initializes with default values", () => {
    const { result } = renderHook(() => useNlqQuery());

    expect(result.current.prompt).toBe("");
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isExplaining).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.confidence).toBeNull();
    expect(result.current.explanation).toBeNull();
    expect(result.current.explanationSteps).toEqual([]);
    expect(result.current.provider).toBe("mock");
    expect(result.current.history).toEqual([]);
    expect(result.current.canUndo).toBe(false);
  });

  it("rejects empty prompt with validation error", async () => {
    const { result } = renderHook(() => useNlqQuery());

    let res: QuerySpec | null = null;
    await act(async () => {
      res = await result.current.translatePrompt("");
    });

    expect(res).toBeNull();
    expect(result.current.error).toBe("Prompt cannot be empty.");
  });

  it("translates prompt successfully via API and applies spec", async () => {
    const onApply = vi.fn();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: 0.95,
        explanation: "Selects active users.",
        steps: ["From users table", "Filter status = active"],
      }),
    });

    const { result } = renderHook(() =>
      useNlqQuery({
        apiUrl: "/api/v1/nlq",
        autoApply: true,
        onApply,
      })
    );

    let res: QuerySpec | null = null;
    await act(async () => {
      res = await result.current.translatePrompt("Find active users");
    });

    expect(res).toEqual(mockQuerySpec);
    expect(result.current.confidence).toBe(0.95);
    expect(result.current.explanation).toBe("Selects active users.");
    expect(result.current.explanationSteps).toEqual([
      "From users table",
      "Filter status = active",
    ]);
    expect(result.current.history).toEqual(["Find active users"]);
    expect(onApply).toHaveBeenCalledWith(mockQuerySpec);
  });

  it("does not call onApply when autoApply is false", async () => {
    const onApply = vi.fn();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: 0.88,
      }),
    });

    const { result } = renderHook(() =>
      useNlqQuery({
        autoApply: false,
        onApply,
      })
    );

    await act(async () => {
      await result.current.translatePrompt("Find active users");
    });

    expect(onApply).not.toHaveBeenCalled();
    expect(result.current.confidence).toBe(0.88);
  });

  it("handles HTTP error response with JSON error message", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({
        error: { message: "Invalid prompt syntax" },
      }),
    });

    const { result } = renderHook(() => useNlqQuery());

    let res: QuerySpec | null = null;
    await act(async () => {
      res = await result.current.translatePrompt("invalid query");
    });

    expect(res).toBeNull();
    expect(result.current.error).toBe("Invalid prompt syntax");
  });

  it("handles HTTP error response when json() throws", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("Bad Gateway");
      },
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.translatePrompt("something");
    });

    expect(result.current.error).toBe("Translation request failed (502)");
  });

  it("handles network failure gracefully", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network connection lost"));

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.translatePrompt("hello");
    });

    expect(result.current.error).toBe("Network connection lost");
  });

  it("uses customTranslator when provider is custom", async () => {
    const customTranslator = vi.fn().mockResolvedValue(mockQuerySpec);
    const { result } = renderHook(() =>
      useNlqQuery({
        defaultProvider: "custom",
        customTranslator,
      })
    );

    await act(async () => {
      await result.current.translatePrompt("custom translate text");
    });

    expect(customTranslator).toHaveBeenCalledWith(
      "custom translate text",
      undefined,
      "postgres"
    );
    expect(result.current.confidence).toBe(1.0);
    expect(result.current.explanation).toBe('Translated: "custom translate text"');
  });

  it("explains query successfully", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        explanation: "This query filters active users.",
        steps: ["Step 1: Read users", "Step 2: Filter active"],
      }),
    });

    const { result } = renderHook(() => useNlqQuery());

    let expl: string | null = null;
    await act(async () => {
      expl = await result.current.explainQuery(mockQuerySpec);
    });

    expect(expl).toBe("This query filters active users.");
    expect(result.current.explanation).toBe("This query filters active users.");
    expect(result.current.explanationSteps).toEqual([
      "Step 1: Read users",
      "Step 2: Filter active",
    ]);
  });

  it("handles explain query missing spec error", async () => {
    const { result } = renderHook(() => useNlqQuery());

    let expl: string | null = null;
    await act(async () => {
      expl = await result.current.explainQuery(undefined);
    });

    expect(expl).toBeNull();
    expect(result.current.error).toBe("No query specification provided to explain.");
  });

  it("handles explain query API error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({
        error: { message: "Explain engine crashed" },
      }),
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.explainQuery(mockQuerySpec);
    });

    expect(result.current.error).toBe("Explain engine crashed");
  });

  it("supports undoing translations across history stack", async () => {
    const onApply = vi.fn();
    const spec1 = { ...mockQuerySpec, table: "users" };
    const spec2 = { ...mockQuerySpec, table: "orders" };

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ spec: spec1 }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ spec: spec2 }),
      });

    const { result } = renderHook(() =>
      useNlqQuery({
        onApply,
      })
    );

    // Initial state: canUndo is false
    expect(result.current.canUndo).toBe(false);

    await act(async () => {
      await result.current.translatePrompt("query 1");
    });
    expect(result.current.canUndo).toBe(false);

    await act(async () => {
      await result.current.translatePrompt("query 2");
    });
    expect(result.current.canUndo).toBe(true);

    // Undo returns spec1 and invokes onApply
    let undone: QuerySpec | null = null;
    act(() => {
      undone = result.current.undoLastTranslation();
    });

    expect(undone).toEqual(spec1);
    expect(onApply).toHaveBeenLastCalledWith(spec1);
    expect(result.current.canUndo).toBe(false);

    // Second undo returns null
    act(() => {
      undone = result.current.undoLastTranslation();
    });
    expect(undone).toBeNull();
  });

  it("clears state properly", () => {
    const { result } = renderHook(() => useNlqQuery());

    act(() => {
      result.current.setPrompt("some text");
      result.current.setProvider("gemini");
    });
    expect(result.current.prompt).toBe("some text");
    expect(result.current.provider).toBe("gemini");

    act(() => {
      result.current.clearState();
    });

    expect(result.current.prompt).toBe("");
    expect(result.current.error).toBeNull();
    expect(result.current.confidence).toBeNull();
    expect(result.current.explanation).toBeNull();
    expect(result.current.explanationSteps).toEqual([]);
  });

  it("handles explain query HTTP error when json parsing fails", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => {
        throw new Error("Bad JSON");
      },
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.explainQuery(mockQuerySpec);
    });

    expect(result.current.error).toBe("Explain request failed (503)");
  });

  it("handles explain query response with summary fallback and non-array steps", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        summary: "Summary only",
        steps: "not an array",
      }),
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.explainQuery(mockQuerySpec);
    });

    expect(result.current.explanation).toBe("Summary only");
    expect(result.current.explanationSteps).toEqual([]);
  });

  it("handles explain query default text fallback and non-Error throw", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.explainQuery(mockQuerySpec);
    });

    expect(result.current.explanation).toBe("Explanation generated.");

    // Throw non-Error object
    global.fetch = vi.fn().mockRejectedValue("string error");
    await act(async () => {
      await result.current.explainQuery(mockQuerySpec);
    });
    expect(result.current.error).toBe("Failed to explain query.");
  });

  it("handles translatePrompt non-number confidence, non-array steps, and non-Error throw", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: "not a number",
        explanation: null,
        steps: null,
      }),
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.translatePrompt("query");
    });

    expect(result.current.confidence).toBe(0.9);
    expect(result.current.explanation).toBe("");
    expect(result.current.explanationSteps).toEqual([]);

    // Throw non-Error object
    global.fetch = vi.fn().mockRejectedValue("raw string rejection");
    await act(async () => {
      await result.current.translatePrompt("query 2");
    });
    expect(result.current.error).toBe("Failed to translate natural language prompt.");
  });

  it("handles undo without onApply prop", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ spec: { ...mockQuerySpec, table: "t1" } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ spec: { ...mockQuerySpec, table: "t2" } }) });

    // No onApply provided
    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.translatePrompt("p1");
    });
    await act(async () => {
      await result.current.translatePrompt("p2");
    });

    let undone: QuerySpec | null = null;
    act(() => {
      undone = result.current.undoLastTranslation();
    });
    expect(undone).toEqual({ ...mockQuerySpec, table: "t1" });
  });

  it("handles HTTP error without error message property", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({}),
    });

    const { result } = renderHook(() => useNlqQuery());

    await act(async () => {
      await result.current.translatePrompt("forbidden prompt");
    });

    expect(result.current.error).toBe("Translation request failed (403)");
  });

  it("uses prompt state when translatePrompt is called without override argument", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: 0.98,
        explanation: "Done",
        steps: ["Step 1"],
      }),
    });

    const { result } = renderHook(() => useNlqQuery());

    // Call without prompt or override should fail validation
    await act(async () => {
      await result.current.translatePrompt();
    });
    expect(result.current.error).toBe("Prompt cannot be empty.");

    // Now set prompt in state and call without arguments
    act(() => {
      result.current.setPrompt("show active users from state");
    });

    let spec: QuerySpec | null = null;
    await act(async () => {
      spec = await result.current.translatePrompt();
    });

    expect(spec).toEqual(mockQuerySpec);
    expect(result.current.confidence).toBe(0.98);
    expect(result.current.explanation).toBe("Done");
  });
});
