import { useState, useRef, useCallback, useEffect } from "react";

export type LiveExecutionStatus =
  | "idle"
  | "testing"
  | "connected"
  | "disconnected"
  | "error";

export interface LiveExecutionResult {
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
  executionId?: string;
  executionTimeMs?: number;
  dialect?: string;
  truncated?: boolean;
}

export interface UseLiveExecutionOptions {
  apiUrl?: string;
  connectionId?: string;
  dialect?: string;
  defaultTimeoutMs?: number;
  initialResults?: LiveExecutionResult | null;
  onSuccess?: (results: LiveExecutionResult) => void;
  onError?: (error: Error) => void;
  fetchFn?: typeof fetch;
}

export interface ExecuteQueryOptions {
  connectionId?: string;
  limit?: number;
  params?: unknown[];
  timeoutMs?: number;
}

export interface UseLiveExecutionReturn {
  isExecuting: boolean;
  executionTimeMs: number | null;
  results: LiveExecutionResult | null;
  error: string | null;
  connectionStatus: LiveExecutionStatus;
  connectionLatencyMs: number | null;
  activeExecutionId: string | null;
  executeQuery: (
    queryOrSql: string | object,
    options?: ExecuteQueryOptions
  ) => Promise<LiveExecutionResult | null>;
  cancelExecution: () => Promise<boolean>;
  testConnection: (targetConnId?: string) => Promise<boolean>;
  clearResults: () => void;
  setResults: (res: LiveExecutionResult | null) => void;
}

export function useLiveExecution(
  options: UseLiveExecutionOptions = {}
): UseLiveExecutionReturn {
  const {
    apiUrl = "/api/v1",
    connectionId,
    dialect = "sqlite",
    defaultTimeoutMs = 30000,
    initialResults = null,
    onSuccess,
    onError,
    fetchFn,
  } = options;

  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [executionTimeMs, setExecutionTimeMs] = useState<number | null>(
    initialResults?.executionTimeMs ?? null
  );
  const [results, setResults] = useState<LiveExecutionResult | null>(
    initialResults
  );
  const [error, setError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] =
    useState<LiveExecutionStatus>("idle");
  const [connectionLatencyMs, setConnectionLatencyMs] = useState<number | null>(
    null
  );
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(
    null
  );

  const abortControllerRef = useRef<AbortController | null>(null);
  const currentExecIdRef = useRef<string | null>(null);

  const getEffectiveFetch = useCallback((): typeof fetch => {
    return fetchFn ?? fetch;
  }, [fetchFn]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const clearResults = useCallback(() => {
    setResults(null);
    setError(null);
    setExecutionTimeMs(null);
  }, []);

  const cancelExecution = useCallback(async (): Promise<boolean> => {
    const execIdToCancel = currentExecIdRef.current;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    let remoteCancelled = false;
    if (execIdToCancel) {
      try {
        const fetcher = getEffectiveFetch();
        const resp = await fetcher(`${apiUrl}/connections/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ execution_id: execIdToCancel }),
        });
        if (resp.ok) {
          const data = await resp.json();
          remoteCancelled = Boolean(data?.cancelled);
        }
      } catch {
        // Fall back to local abort state
      }
    }

    setIsExecuting(false);
    setActiveExecutionId(null);
    currentExecIdRef.current = null;
    return remoteCancelled || Boolean(execIdToCancel);
  }, [apiUrl, getEffectiveFetch]);

  const testConnection = useCallback(
    async (targetConnId?: string): Promise<boolean> => {
      const conn = targetConnId ?? connectionId;
      setConnectionStatus("testing");
      const startTime = Date.now();

      try {
        const fetcher = getEffectiveFetch();
        const payload = conn ? { connection_id: conn } : {};
        const resp = await fetcher(`${apiUrl}/connections/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        const endTime = Date.now();
        const latency = endTime - startTime;

        if (!resp.ok) {
          setConnectionStatus("error");
          setConnectionLatencyMs(null);
          return false;
        }

        const data = await resp.json();
        if (data && data.healthy) {
          setConnectionStatus("connected");
          setConnectionLatencyMs(
            typeof data.latency_ms === "number" ? data.latency_ms : latency
          );
          return true;
        }

        setConnectionStatus("error");
        setConnectionLatencyMs(null);
        return false;
      } catch {
        setConnectionStatus("error");
        setConnectionLatencyMs(null);
        return false;
      }
    },
    [apiUrl, connectionId, getEffectiveFetch]
  );

  const executeQuery = useCallback(
    async (
      queryOrSql: string | object,
      execOptions: ExecuteQueryOptions = {}
    ): Promise<LiveExecutionResult | null> => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      const randomSuffix = Math.random().toString(36).substring(2, 8);
      const executionId = `exec_${Date.now()}_${randomSuffix}`;
      currentExecIdRef.current = executionId;
      setActiveExecutionId(executionId);

      setIsExecuting(true);
      setError(null);

      const effectiveTimeout = execOptions.timeoutMs ?? defaultTimeoutMs;
      let timerId: ReturnType<typeof setTimeout> | undefined;
      if (effectiveTimeout > 0) {
        timerId = setTimeout(() => {
          controller.abort();
        }, effectiveTimeout);
      }

      const startTime = Date.now();

      try {
        const effectiveConn = execOptions.connectionId ?? connectionId;
        const requestBody: Record<string, unknown> = {
          execution_id: executionId,
        };

        if (effectiveConn) {
          requestBody.connection_id = effectiveConn;
        }

        if (typeof execOptions.limit === "number") {
          requestBody.limit = execOptions.limit;
        }

        if (typeof queryOrSql === "string") {
          requestBody.sql = queryOrSql;
          if (execOptions.params) {
            requestBody.params = execOptions.params;
          }
        } else {
          requestBody.query = queryOrSql;
        }

        const fetcher = getEffectiveFetch();
        const resp = await fetcher(`${apiUrl}/query/execute`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestBody),
          signal: controller.signal,
        });

        if (timerId) {
          clearTimeout(timerId);
        }

        const endTime = Date.now();
        const elapsed = endTime - startTime;

        if (!resp.ok) {
          let errorMsg = `Query execution failed with status ${resp.status}`;
          try {
            const errData = await resp.json();
            if (errData?.error?.message) {
              errorMsg = errData.error.message;
            } else if (errData?.message) {
              errorMsg = errData.message;
            }
          } catch {
            // Non-JSON error body
          }
          throw new Error(errorMsg);
        }

        const data = await resp.json();
        const rows = Array.isArray(data?.rows) ? data.rows : [];
        const columns = Array.isArray(data?.columns)
          ? data.columns
          : rows.length > 0 && typeof rows[0] === "object" && rows[0] !== null
          ? Object.keys(rows[0])
          : [];

        const liveResult: LiveExecutionResult = {
          columns,
          rows,
          rowCount:
            typeof data?.count === "number"
              ? data.count
              : rows.length,
          executionId: data?.execution_id || executionId,
          executionTimeMs:
            typeof data?.duration_ms === "number"
              ? data.duration_ms
              : elapsed,
          dialect: data?.dialect || dialect,
          truncated: Boolean(data?.truncated),
        };

        setResults(liveResult);
        setExecutionTimeMs(liveResult.executionTimeMs ?? null);
        setIsExecuting(false);
        setActiveExecutionId(null);
        currentExecIdRef.current = null;

        onSuccess?.(liveResult);
        return liveResult;
      } catch (err: unknown) {
        if (timerId) {
          clearTimeout(timerId);
        }

        const isAborted =
          controller.signal.aborted ||
          (err instanceof Error && err.name === "AbortError");
        const errMsg = isAborted
          ? "Query execution was cancelled."
          : err instanceof Error
          ? err.message
          : "An unknown execution error occurred.";

        const errorObj = err instanceof Error ? err : new Error(errMsg);

        setError(errMsg);
        setIsExecuting(false);
        setActiveExecutionId(null);
        currentExecIdRef.current = null;

        onError?.(errorObj);
        return null;
      }
    },
    [
      apiUrl,
      connectionId,
      dialect,
      defaultTimeoutMs,
      getEffectiveFetch,
      onSuccess,
      onError,
    ]
  );

  return {
    isExecuting,
    executionTimeMs,
    results,
    error,
    connectionStatus,
    connectionLatencyMs,
    activeExecutionId,
    executeQuery,
    cancelExecution,
    testConnection,
    clearResults,
    setResults,
  };
}
