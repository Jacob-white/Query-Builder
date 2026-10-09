import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useStreamingQuery } from "../src/hooks/useStreamingQuery";

describe("useStreamingQuery Hook", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function createMockSseResponse(chunks: string[], status = 200, statusText = "OK"): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });

    return new Response(stream, {
      status,
      statusText,
      headers: { "Content-Type": "text/event-stream" },
    });
  }

  it("handles successful SSE streaming with metadata, batch, stats, and done events", async () => {
    const sseData = [
      'event: metadata\ndata: {"columns": ["id", "title"], "total_estimated": 2}\n\n',
      'event: batch\ndata: {"rows": [{"id": 1, "title": "Doc 1"}], "batch_index": 0}\n\n',
      'event: batch\ndata: {"rows": [{"id": 2, "title": "Doc 2"}], "batch_index": 1}\n\n',
      'event: stats\ndata: {"elapsed_ms": 12.5, "cache_hit": false}\n\n',
      'event: done\ndata: {"status": "complete"}\n\n',
    ];

    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(sseData));

    const onBatch = vi.fn();
    const onComplete = vi.fn();

    const { result } = renderHook(() =>
      useStreamingQuery(undefined, {
        onBatch,
        onComplete,
      })
    );

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.rows).toEqual([]);

    await act(async () => {
      await result.current.execute({ table: "documents" });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.columns).toEqual(["id", "title"]);
    expect(result.current.rows).toEqual([
      { id: 1, title: "Doc 1" },
      { id: 2, title: "Doc 2" },
    ]);
    expect(result.current.progress.rowsReceived).toBe(2);
    expect(result.current.progress.totalEstimated).toBe(2);
    expect(result.current.stats.elapsedMs).toBe(12.5);
    expect(onBatch).toHaveBeenCalledTimes(2);
    expect(onComplete).toHaveBeenCalledWith(2);
    expect(result.current.error).toBeNull();
  });

  it("handles chunk fragmentation across network packets", async () => {
    // Deliberately split an SSE message across multiple stream chunks
    const fragmentedChunks = [
      'event: meta',
      'data\ndata: {"columns": ["val"]}\n\n',
      'event: batch\ndata: {"rows": [{"val": 10',
      '0}]}\n\n',
      'event: done\ndata: {}\n\n',
    ];

    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(fragmentedChunks));

    const { result } = renderHook(() => useStreamingQuery());

    await act(async () => {
      await result.current.execute({ spec: { table: "nums" } });
    });

    expect(result.current.columns).toEqual(["val"]);
    expect(result.current.rows).toEqual([{ val: 100 }]);
  });

  it("handles HTTP error response gracefully", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { message: "Table not permitted" } }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      })
    );

    const onError = vi.fn();
    const { result } = renderHook(() => useStreamingQuery(undefined, { onError }));

    await act(async () => {
      await result.current.execute({ table: "restricted" });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.error).toBe("Table not permitted");
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });

  it("supports manual reset", async () => {
    const sseData = [
      'event: metadata\ndata: {"columns": ["id"]}\n\n',
      'event: batch\ndata: {"rows": [{"id": 1}]}\n\n',
      'event: done\ndata: {}\n\n',
    ];

    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(sseData));

    const { result } = renderHook(() => useStreamingQuery());

    await act(async () => {
      await result.current.execute({ table: "t" });
    });

    expect(result.current.rows.length).toBe(1);

    act(() => {
      result.current.reset();
    });

    expect(result.current.rows).toEqual([]);
    expect(result.current.columns).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.progress.rowsReceived).toBe(0);

    // Also call reset() while a stream is in flight to test abort-on-reset branch
    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const err = new Error("Aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });

    let activeExecPromise: Promise<void> | undefined;
    act(() => {
      activeExecPromise = result.current.execute({ table: "reset_active" });
    });
    act(() => {
      result.current.reset();
    });
    await act(async () => {
      await activeExecPromise;
    });
    expect(result.current.isStreaming).toBe(false);
  });

  it("handles manual abort() during active stream", async () => {
    globalThis.fetch = vi.fn().mockImplementation((_url, init) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const err = new Error("The operation was aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });

    const { result } = renderHook(() => useStreamingQuery());

    let execPromise: Promise<void> | undefined;
    act(() => {
      execPromise = result.current.execute({ table: "items" });
    });

    act(() => {
      result.current.abort();
    });

    await act(async () => {
      await execPromise;
    });

    expect(result.current.isStreaming).toBe(false);
  });

  it("triggers autoExecute and cleans up on unmount", async () => {
    const sseData = ['event: batch\ndata: {"rows": [{"id": 42}]}\n\n', 'event: done\ndata: {}\n\n'];
    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(sseData));

    let hookResult!: { current: ReturnType<typeof useStreamingQuery> };
    let hookUnmount!: () => void;

    await act(async () => {
      const rendered = renderHook(() =>
        useStreamingQuery(
          { table: "auto_test" },
          { autoExecute: true }
        )
      );
      hookResult = rendered.result;
      hookUnmount = rendered.unmount;
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(hookResult.current.rows).toEqual([{ id: 42 }]);

    // Unmount triggers abort controller cleanup
    hookUnmount();
  });

  it("handles event: error from stream server", async () => {
    // 1. With message
    const sseData = ['event: error\ndata: {"message": "Execution timeout exceeded"}\n\n'];
    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(sseData));

    const onError = vi.fn();
    const { result } = renderHook(() => useStreamingQuery(undefined, { onError }));

    await act(async () => {
      await result.current.execute({ table: "timeout_table" });
    });

    expect(result.current.error).toBe("Execution timeout exceeded");
    expect(onError).toHaveBeenCalledWith(expect.any(Error));

    // 2. Without message (falls back to "Stream error")
    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(['event: error\ndata: {}\n\n']));
    await act(async () => {
      await result.current.execute({ table: "err_fallback" });
    });
    expect(result.current.error).toBe("Stream error");
  });

  it("handles null response.body", async () => {
    const mockResp = new Response(null, { status: 200 });
    Object.defineProperty(mockResp, "body", { value: null });
    globalThis.fetch = vi.fn().mockResolvedValue(mockResp);

    const onError = vi.fn();
    const { result } = renderHook(() => useStreamingQuery(undefined, { onError }));

    await act(async () => {
      await result.current.execute({ table: "no_body" });
    });

    expect(result.current.error).toContain("ReadableStream not supported");
    expect(onError).toHaveBeenCalled();
  });

  it("handles non-JSON error bodies and non-Error exceptions", async () => {
    // 1. Non-JSON error body (e.g. text/html 502 Bad Gateway)
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("Bad Gateway HTML", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "Content-Type": "text/plain" },
      })
    );

    const { result } = renderHook(() => useStreamingQuery());

    await act(async () => {
      await result.current.execute({ table: "gateway" });
    });

    expect(result.current.error).toBe("Streaming request failed with HTTP 502");

    // 2. Non-Error thrown rejection
    globalThis.fetch = vi.fn().mockRejectedValue("Fatal Network Socket Crash");

    await act(async () => {
      await result.current.execute({ table: "crash" });
    });

    expect(result.current.error).toBe("Fatal Network Socket Crash");
  });

  it("ignores malformed JSON chunks and blank messages", async () => {
    const sseData = [
      "\n\n", // blank message line 166
      "event: message\n\n", // no dataStr line 180
      'event: batch\ndata: {MALFORMED JSON}\n\n', // JSON parse catch line 217-219
      'event: batch\ndata: {"rows": "not-an-array"}\n\n', // non-array batch rows line 194
      'event: batch\ndata: {"rows": [{"id": 99}]}\n\n',
      "event: done\ndata: {}\n\n",
    ];
    globalThis.fetch = vi.fn().mockResolvedValue(createMockSseResponse(sseData));

    const { result } = renderHook(() => useStreamingQuery());

    await act(async () => {
      await result.current.execute({ table: "malformed" });
    });

    expect(result.current.rows).toEqual([{ id: 99 }]);
  });

  it("handles execute() with no payload and aborts prior in-flight controller on concurrent execution", async () => {
    // 1. execute without payload and no initial payload
    const { result } = renderHook(() => useStreamingQuery());
    await act(async () => {
      await result.current.execute();
    });
    expect(result.current.isStreaming).toBe(false);

    // 2. concurrent execution aborts prior controller
    let streamCount = 0;
    globalThis.fetch = vi.fn().mockImplementation(() => {
      streamCount++;
      return Promise.resolve(createMockSseResponse(['event: done\ndata: {}\n\n']));
    });

    await act(async () => {
      const p1 = result.current.execute({ table: "first" });
      const p2 = result.current.execute({ table: "second" });
      await Promise.all([p1, p2]);
    });
    expect(streamCount).toBe(2);
  });
});



