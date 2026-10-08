import { useState, useCallback, useRef, useEffect } from "react";
import type { StreamingQueryState } from "../types";

export interface UseStreamingQueryOptions {
  /** Target endpoint for SSE streaming. Defaults to "/api/v1/stream". */
  endpoint?: string;
  /** Whether to execute automatically when initial payload is provided. */
  autoExecute?: boolean;
  /** Batch size per chunk request. Defaults to 250. */
  batchSize?: number;
  /** Optional custom headers to send with the POST request. */
  headers?: Record<string, string>;
  /** Callback fired whenever a new batch chunk of rows arrives. */
  onBatch?: (batch: Record<string, any>[]) => void;
  /** Callback fired when streaming finishes successfully. */
  onComplete?: (totalRows: number) => void;
  /** Callback fired on streaming or connection error. */
  onError?: (err: Error) => void;
}

export interface UseStreamingQueryReturn extends StreamingQueryState {
  stats: {
    elapsedMs?: number;
    cacheHit?: boolean;
  };
  execute: (payload?: Record<string, any>) => Promise<void>;
  abort: () => void;
  reset: () => void;
}

/**
 * React hook for consuming SSE query streams with line-buffered event parsing,
 * backpressure management, progress telemetry, and abort signals.
 */
export function useStreamingQuery(
  initialPayload?: Record<string, any>,
  options: UseStreamingQueryOptions = {}
): UseStreamingQueryReturn {
  const {
    endpoint = "/api/v1/stream",
    autoExecute = false,
    batchSize = 250,
    headers = {},
    onBatch,
    onComplete,
    onError,
  } = options;

  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [progress, setProgress] = useState<{
    rowsReceived: number;
    totalEstimated?: number;
    elapsedMs: number;
  }>({
    rowsReceived: 0,
    totalEstimated: undefined,
    elapsedMs: 0,
  });
  const [stats, setStats] = useState<{
    elapsedMs?: number;
    cacheHit?: boolean;
  }>({});
  const [error, setError] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const activePayloadRef = useRef<Record<string, any> | undefined>(initialPayload);

  const reset = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setRows([]);
    setColumns([]);
    setIsStreaming(false);
    setProgress({ rowsReceived: 0, totalEstimated: undefined, elapsedMs: 0 });
    setStats({});
    setError(null);
  }, []);

  const abort = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);
    }
  }, []);

  const execute = useCallback(
    async (overridePayload?: Record<string, any>) => {
      const payloadToSend = overridePayload || activePayloadRef.current;
      if (!payloadToSend) {
        return;
      }

      // Abort any existing stream
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setRows([]);
      setColumns([]);
      setIsStreaming(true);
      setError(null);
      setProgress({ rowsReceived: 0, totalEstimated: undefined, elapsedMs: 0 });
      setStats({});

      const startTime = performance.now();
      let hasCompleted = false;

      try {
        const bodyPayload = {
          ...payloadToSend,
          batch_size: payloadToSend.batch_size || batchSize,
        };

        const response = await fetch(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
            ...headers,
          },
          body: JSON.stringify(bodyPayload),
          signal: controller.signal,
        });

        if (!response.ok) {
          let errorMsg = `Streaming request failed with HTTP ${response.status}`;
          try {
            const errJson = await response.json();
            if (errJson?.error?.message) {
              errorMsg = errJson.error.message;
            }
          } catch {
            // response was not JSON
          }
          throw new Error(errorMsg);
        }

        if (!response.body) {
          throw new Error("ReadableStream not supported by response body.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let accumulatedRows: Record<string, any>[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const messages = buffer.split("\n\n");
          // Keep the last partial event fragment in buffer
          buffer = messages.pop() || "";

          for (const message of messages) {
            if (!message.trim()) continue;

            let eventName = "message";
            let dataStr = "";

            const lines = message.split("\n");
            for (const line of lines) {
              if (line.startsWith("event:")) {
                eventName = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                dataStr = line.slice(5).trim();
              }
            }

            if (!dataStr) continue;

            try {
              const parsed = JSON.parse(dataStr);
              if (eventName === "metadata") {
                if (Array.isArray(parsed.columns)) {
                  setColumns(parsed.columns);
                }
                setProgress((prev) => ({
                  ...prev,
                  totalEstimated: parsed.total_estimated,
                  elapsedMs: performance.now() - startTime,
                }));
              } else if (eventName === "batch") {
                const batchRows = Array.isArray(parsed.rows) ? parsed.rows : [];
                accumulatedRows = accumulatedRows.concat(batchRows);
                setRows((prev) => [...prev, ...batchRows]);
                setProgress((prev) => ({
                  ...prev,
                  rowsReceived: accumulatedRows.length,
                  elapsedMs: performance.now() - startTime,
                }));
                onBatch?.(batchRows);
              } else if (eventName === "stats") {
                setStats({
                  elapsedMs: parsed.elapsed_ms,
                  cacheHit: parsed.cache_hit,
                });
              } else if (eventName === "done") {
                setIsStreaming(false);
                if (!hasCompleted) {
                  hasCompleted = true;
                  onComplete?.(accumulatedRows.length);
                }
              } else if (eventName === "error") {
                const errText = parsed.message || "Stream error";
                setError(errText);
                setIsStreaming(false);
                hasCompleted = true;
                onError?.(new Error(errText));
              }
            } catch {
              // Ignore malformed chunk JSON
            }
          }
        }

        setIsStreaming(false);
        if (!hasCompleted) {
          hasCompleted = true;
          onComplete?.(accumulatedRows.length);
        }
      } catch (err: any) {
        hasCompleted = true;
        if (err.name === "AbortError") {
          // User aborted stream intentionally
          setIsStreaming(false);
          return;
        }
        const errorInstance = err instanceof Error ? err : new Error(String(err));
        setError(errorInstance.message);
        setIsStreaming(false);
        onError?.(errorInstance);
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
      }
    },
    [batchSize, endpoint, headers, onBatch, onComplete, onError]
  );

  const hasAutoExecutedRef = useRef(false);

  useEffect(() => {
    activePayloadRef.current = initialPayload;
    if (autoExecute && initialPayload && !hasAutoExecutedRef.current) {
      hasAutoExecutedRef.current = true;
      execute(initialPayload);
    }
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [autoExecute, execute, initialPayload]);

  return {
    rows,
    columns,
    isStreaming,
    progress,
    stats,
    error,
    execute,
    abort,
    reset,
  };
}
