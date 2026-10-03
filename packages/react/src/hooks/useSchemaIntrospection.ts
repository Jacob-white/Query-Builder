import { useState, useCallback, useEffect } from "react";
import type { SchemaSnapshot } from "../types";

export interface UseSchemaIntrospectionOptions {
  initialSchema?: SchemaSnapshot | null;
  apiEndpoint?: string;
  connector?: string;
  connectorConfig?: Record<string, unknown>;
  fetchOnInit?: boolean;
  cacheKey?: string;
  onSchemaLoaded?: (schema: SchemaSnapshot) => void;
  onError?: (error: Error) => void;
}

export interface UseSchemaIntrospectionReturn {
  schema: SchemaSnapshot | null;
  isLoading: boolean;
  error: string | null;
  refreshSchema: () => Promise<SchemaSnapshot | null>;
  setSchema: (schema: SchemaSnapshot | null) => void;
  clearSchema: () => void;
}

export function useSchemaIntrospection(
  options: UseSchemaIntrospectionOptions = {},
): UseSchemaIntrospectionReturn {
  const {
    initialSchema,
    apiEndpoint,
    connector,
    connectorConfig,
    fetchOnInit,
    cacheKey,
    onSchemaLoaded,
    onError,
  } = options;

  const [schema, setSchema] = useState<SchemaSnapshot | null>(() => {
    if (cacheKey && typeof window !== "undefined" && window.localStorage) {
      try {
        const cached = window.localStorage.getItem(cacheKey);
        if (cached) {
          return JSON.parse(cached) as SchemaSnapshot;
        }
      } catch {
        // Fall back to initialSchema if JSON.parse fails
      }
    }
    return initialSchema || null;
  });

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const refreshSchema = useCallback(async (): Promise<SchemaSnapshot | null> => {
    if (!apiEndpoint) {
      return schema;
    }

    setIsLoading(true);
    setError(null);

    try {
      const resp = await fetch(apiEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connector: connector || "duckdb",
          config: connectorConfig || {},
        }),
      });

      if (!resp.ok) {
        throw new Error(`HTTP error ${resp.status}`);
      }

      const data = await resp.json();
      const loadedSchema: SchemaSnapshot = data?.schema || data;

      setSchema(loadedSchema);

      if (cacheKey && typeof window !== "undefined" && window.localStorage) {
        try {
          window.localStorage.setItem(cacheKey, JSON.stringify(loadedSchema));
        } catch {
          // Ignore cache write failures
        }
      }

      setIsLoading(false);
      onSchemaLoaded?.(loadedSchema);
      return loadedSchema;
    } catch (err: unknown) {
      const errorObj = err instanceof Error ? err : new Error(String(err));
      setError(errorObj.message);
      setIsLoading(false);
      onError?.(errorObj);
      return null;
    }
  }, [apiEndpoint, connector, connectorConfig, cacheKey, onSchemaLoaded, onError, schema]);

  useEffect(() => {
    if (fetchOnInit && apiEndpoint && !initialSchema) {
      refreshSchema();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clearSchema = useCallback(() => {
    setSchema(null);
    setError(null);
    if (cacheKey && typeof window !== "undefined" && window.localStorage) {
      try {
        window.localStorage.removeItem(cacheKey);
      } catch {
        // Ignore cache remove failures
      }
    }
  }, [cacheKey]);

  return {
    schema,
    isLoading,
    error,
    refreshSchema,
    setSchema,
    clearSchema,
  };
}
