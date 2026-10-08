/**
 * React Hook for In-Browser Client OLAP and DuckDB-Wasm Engine.
 * =============================================================
 * Manages local tables, file ingestion, query caching, and dynamic SchemaSnapshot
 * generation for the Visual Query Builder.
 */

import { useState, useCallback, useMemo, useEffect } from "react";
import { getClientOlapEngine, DuckDBDriverConfig } from "../drivers/duckdbDriver";
import { ingestLocalFile } from "../utils/localDataIngest";
import type {
  ClientOlapEngine,
  DuckDBQueryResult,
  DuckDBTableMeta,
  SchemaSnapshot,
} from "../types";

export interface UseClientOlapResult {
  engine: ClientOlapEngine;
  tables: Record<string, DuckDBTableMeta>;
  activeTable?: string;
  schemaSnapshot: SchemaSnapshot;
  isLoading: boolean;
  error: Error | null;
  ingestFile: (file: File, tableName?: string) => Promise<DuckDBTableMeta>;
  ingestCsv: (tableName: string, csvContent: string) => Promise<DuckDBTableMeta>;
  ingestJson: (tableName: string, rows: Record<string, unknown>[]) => Promise<DuckDBTableMeta>;
  cacheQueryResults: (tableName: string, rows: Record<string, unknown>[]) => Promise<DuckDBTableMeta>;
  query: (sql: string) => Promise<DuckDBQueryResult>;
  dropTable: (tableName: string) => Promise<void>;
  clear: () => Promise<void>;
  setActiveTable: (tableName: string) => void;
}

export function useClientOlap(config?: DuckDBDriverConfig): UseClientOlapResult {
  const engine = useMemo(() => getClientOlapEngine(config), [config]);
  const [tables, setTables] = useState<Record<string, DuckDBTableMeta>>(() => ({ ...engine.tables }));
  const [activeTable, setActiveTableState] = useState<string | undefined>(engine.activeTable);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const syncState = useCallback(() => {
    setTables({ ...engine.tables });
    setActiveTableState(engine.activeTable);
  }, [engine]);

  useEffect(() => {
    syncState();
  }, [syncState]);

  const schemaSnapshot = useMemo<SchemaSnapshot>(() => {
    return engine.getSchemaSnapshot();
  }, [engine, tables]);

  const ingestFile = useCallback(
    async (file: File, tableName?: string): Promise<DuckDBTableMeta> => {
      setIsLoading(true);
      setError(null);
      let meta: DuckDBTableMeta;
      try {
        meta = await ingestLocalFile(file, engine, tableName);
        syncState();
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsLoading(false);
      }
      return meta;
    },
    [engine, syncState],
  );

  const ingestCsv = useCallback(
    async (tableName: string, csvContent: string): Promise<DuckDBTableMeta> => {
      setIsLoading(true);
      setError(null);
      let meta: DuckDBTableMeta;
      try {
        meta = await engine.ingestCsv(tableName, csvContent);
        syncState();
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsLoading(false);
      }
      return meta;
    },
    [engine, syncState],
  );

  const ingestJson = useCallback(
    async (tableName: string, rows: Record<string, unknown>[]): Promise<DuckDBTableMeta> => {
      setIsLoading(true);
      setError(null);
      let meta: DuckDBTableMeta;
      try {
        meta = await engine.ingestJson(tableName, rows);
        syncState();
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsLoading(false);
      }
      return meta;
    },
    [engine, syncState],
  );

  const cacheQueryResults = useCallback(
    async (tableName: string, rows: Record<string, unknown>[]): Promise<DuckDBTableMeta> => {
      setIsLoading(true);
      setError(null);
      let meta: DuckDBTableMeta;
      try {
        meta = await engine.registerBackendResults(tableName, rows);
        syncState();
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsLoading(false);
      }
      return meta;
    },
    [engine, syncState],
  );

  const query = useCallback(
    async (sql: string): Promise<DuckDBQueryResult> => {
      setIsLoading(true);
      setError(null);
      let result: DuckDBQueryResult;
      try {
        result = await engine.query(sql);
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsLoading(false);
      }
      return result;
    },
    [engine],
  );

  const dropTable = useCallback(
    async (tableName: string): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        await engine.dropTable(tableName);
        syncState();
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [engine, syncState],
  );

  const clear = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError(null);
    try {
      await engine.clear();
      syncState();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [engine, syncState]);

  const setActiveTable = useCallback(
    (name: string) => {
      engine.activeTable = name;
      setActiveTableState(name);
    },
    [engine],
  );

  return {
    engine,
    tables,
    activeTable,
    schemaSnapshot,
    isLoading,
    error,
    ingestFile,
    ingestCsv,
    ingestJson,
    cacheQueryResults,
    query,
    dropTable,
    clear,
    setActiveTable,
  };
}
