import { useCallback, useMemo, useState } from "react";
import type { ExecuteQueryHandler, QueryResultData, QuerySpec } from "../../types";
import type { QueryBuilderClient } from "../../client";
import { useLiveExecution, type LiveExecutionResult } from "../../hooks/useLiveExecution";
import type { ActiveTab } from "./types";
import type { DockTab } from "./WorkspaceDock";

export interface UseQueryRunnerOptions {
  propExecuteQuery?: ExecuteQueryHandler;
  contextExecuteQuery?: ExecuteQueryHandler;
  client?: QueryBuilderClient;
  getActiveSpec: () => QuerySpec | null;
  currentSql: string;
  activeTab?: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  dialect?: string;
  liveExecutionApiUrl?: string;
  liveExecutionConnectionId?: string;
  onLiveExecutionSuccess?: (results: LiveExecutionResult) => void;
  onLiveExecutionError?: (error: Error) => void;
}

/** Query execution (host handler or client) plus live-execution wiring and result/error/dock state. */
export function useQueryRunner({
  propExecuteQuery,
  contextExecuteQuery,
  client,
  getActiveSpec,
  currentSql,
  activeTab = "visual",
  setActiveTab,
  dialect,
  liveExecutionApiUrl,
  liveExecutionConnectionId,
  onLiveExecutionSuccess,
  onLiveExecutionError,
}: UseQueryRunnerOptions) {
  const [queryResults, setQueryResults] = useState<QueryResultData | null>(null);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [isDockOpen, setIsDockOpen] = useState<boolean>(false);
  const [dockTab, setDockTab] = useState<DockTab>("results");

  // Auto-wire client query execution if a client is provided and no handler is.
  const effectiveOnExecuteQuery = useMemo<ExecuteQueryHandler | undefined>(
    () =>
      propExecuteQuery ??
      contextExecuteQuery ??
      (client
        ? async (sql: string, spec?: QuerySpec | null) => client.execute(spec ? spec : { sql })
        : undefined),
    [propExecuteQuery, contextExecuteQuery, client],
  );

  const liveExec = useLiveExecution({
    apiUrl: liveExecutionApiUrl,
    connectionId: liveExecutionConnectionId,
    dialect,
    onSuccess: (res) => {
      setQueryResults({
        columns: res.columns,
        rows: res.rows,
        count: res.rowCount,
        durationMs: res.executionTimeMs,
      });
      if (activeTab === "visual") {
        setIsDockOpen(true);
        setDockTab("results");
      } else {
        setActiveTab("results");
      }
      onLiveExecutionSuccess?.(res);
    },
    onError: onLiveExecutionError,
  });

  const handleRunQuery = useCallback(async () => {
    if (!effectiveOnExecuteQuery) return;
    setIsRunning(true);
    setExecutionError(null);
    try {
      const parsedSpec = getActiveSpec();
      const result = await effectiveOnExecuteQuery(currentSql, parsedSpec);
      if (result) {
        setQueryResults(result);
        if (activeTab === "visual") {
          setIsDockOpen(true);
          setDockTab("results");
        } else {
          setActiveTab("results");
        }
      }
      return result;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setExecutionError(msg);
    } finally {
      setIsRunning(false);
    }
  }, [effectiveOnExecuteQuery, getActiveSpec, currentSql, activeTab, setActiveTab]);

  return {
    queryResults,
    isRunning,
    executionError,
    liveExec,
    handleRunQuery,
    isDockOpen,
    setIsDockOpen,
    dockTab,
    setDockTab,
  };
}
