/**
 * First-Class TypeScript API Client for Query-Builder.
 * ===================================================
 * Provides typed, zero-React HTTP communication with backend Query-Builder routers
 * (FastAPI, Django, Express, Native Microservice).
 * Supports typed methods, custom authorization tokens, request timeout,
 * and AbortSignal cancellation.
 */

import type {
  QuerySpec,
  FilterValue,
  SchemaSnapshot,
  QueryResultData,
  SqlDialect,
  SqlSafetyValidation,
} from "../types";

export type {
  QuerySpec,
  SchemaSnapshot,
  QueryResultData,
  SqlDialect,
  SqlSafetyValidation,
};

export interface QueryBuilderClientConfig {
  /**
   * Base URL of the query builder backend endpoint.
   * e.g., "/api/qb", "/api/v1", or "https://api.example.com/api/qb"
   */
  baseUrl: string;

  /**
   * Static or dynamic HTTP headers.
   * If a function is provided, it is evaluated before each request.
   */
  headers?:
    | Record<string, string>
    | (() => Promise<Record<string, string>> | Record<string, string>);

  /**
   * Optional authentication token or token resolver function.
   * Automatically adds `Authorization: Bearer <token>` (or uses existing prefix).
   */
  token?: string | (() => Promise<string | null | undefined> | string | null | undefined);

  /**
   * Default request timeout in milliseconds. Defaults to 30000 (30 seconds).
   */
  timeoutMs?: number;

  /**
   * Custom fetch function implementation (defaults to globalThis.fetch).
   */
  fetchFn?: typeof fetch;
}

export interface RequestOptions {
  /**
   * Optional AbortSignal to cancel in-flight HTTP requests.
   */
  signal?: AbortSignal;

  /**
   * Per-request timeout in milliseconds (overrides client default).
   */
  timeoutMs?: number;

  /**
   * Per-request additional headers (overrides client headers).
   */
  headers?: Record<string, string>;
}

export interface CompileResult {
  sql: string;
  params: unknown[];
  count_sql?: string;
  count_params?: unknown[];
}

/** Loose shape of a JSON error body returned by backends. */
interface ErrorPayload {
  detail?: unknown;
  message?: unknown;
  error?: unknown;
}

/** Loose shape of schema responses that may wrap the snapshot under `schema`. */
interface SchemaEnvelope {
  schema?: SchemaSnapshot;
  capabilities?: Record<string, string>;
}

interface CapabilitiesEnvelope {
  capabilities?: Record<string, string>;
}

export class QueryBuilderApiError extends Error {
  public status: number;
  public statusText: string;
  public data?: unknown;
  public url: string;

  constructor(message: string, status: number, statusText: string, data: unknown, url: string) {
    super(message);
    this.name = "QueryBuilderApiError";
    this.status = status;
    this.statusText = statusText;
    this.data = data;
    this.url = url;
  }
}

/**
 * Fluent query builder helper for programmatic query construction.
 */
export class FluentQuery {
  private _spec: QuerySpec;
  private _client?: QueryBuilderClient;

  constructor(table?: string, client?: QueryBuilderClient) {
    this._client = client;
    this._spec = {
      table: table || "",
      columns: [],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit: 50,
    };
  }

  from(table: string): this {
    this._spec.table = table;
    return this;
  }

  select(columns: (string | { column: string; agg?: string; alias?: string })[]): this {
    this._spec.columns = columns;
    return this;
  }

  join(
    table: string,
    leftCol: string,
    _op: string = "=",
    rightCol: string = "id",
    type: string = "LEFT JOIN",
  ): this {
    const fullType = type.toUpperCase().endsWith("JOIN")
      ? type.toUpperCase()
      : `${type.toUpperCase()} JOIN`;
    this._spec.joins.push({
      table,
      type: fullType,
      left_col: leftCol,
      right_col: rightCol,
      on: [{ left: leftCol, right: rightCol }],
    });
    return this;
  }

  where(column: string, op: string, value: FilterValue, tablePrefix?: string): this {
    this._spec.filters.push({
      column,
      op,
      value,
      tablePrefix,
    });
    return this;
  }

  groupBy(columns: string[]): this {
    this._spec.group_by = columns;
    return this;
  }

  having(column: string, op: string, value: unknown): this {
    if (!this._spec.having) {
      this._spec.having = [];
    }
    this._spec.having.push({ column, op, value });
    return this;
  }

  orderBy(column: string, direction: "ASC" | "DESC" = "ASC", tablePrefix?: string): this {
    this._spec.order_by.push({
      column,
      direction,
      tablePrefix,
    });
    return this;
  }

  distinct(isDistinct: boolean = true): this {
    this._spec.distinct = isDistinct;
    return this;
  }

  limit(n: number): this {
    this._spec.limit = n;
    return this;
  }

  offset(n: number): this {
    this._spec.offset = n;
    return this;
  }

  toSpec(): QuerySpec {
    return JSON.parse(JSON.stringify(this._spec));
  }

  async execute(client?: QueryBuilderClient): Promise<QueryResultData> {
    const activeClient = client || this._client;
    if (!activeClient) {
      throw new Error(
        "FluentQuery: No client provided to execute query. Pass a client to execute(client) or construct via client.query().",
      );
    }
    return activeClient.execute(this._spec);
  }
}

/**
 * Creates a lightweight, chainable query specification builder.
 */
export function createQuery(table?: string, client?: QueryBuilderClient): FluentQuery {
  return new FluentQuery(table, client);
}

export interface QueryBuilderClient {
  /**
   * Introspects and retrieves the full relational database schema snapshot.
   */
  getSchema(options?: RequestOptions): Promise<SchemaSnapshot>;

  /**
   * Compiles a declarative QuerySpec AST into parameterized SQL.
   */
  compile(
    spec: QuerySpec,
    dialect?: SqlDialect,
    options?: RequestOptions,
  ): Promise<CompileResult>;

  /**
   * Validates raw SQL or AST for safety violations (forbidden DDL, injection, write operations).
   */
  validate(sql: string, options?: RequestOptions): Promise<SqlSafetyValidation>;

  /**
   * Executes a query specification or pre-compiled SQL query against the backend.
   */
  execute(
    specOrSql: QuerySpec | { sql: string; params?: unknown[] },
    options?: RequestOptions,
  ): Promise<QueryResultData>;

  /**
   * Exports dataset into tabular formats (CSV, JSON, Parquet, Excel, Arrow) as a downloadable Blob.
   */
  export(
    spec: QuerySpec,
    format: "csv" | "json" | "parquet" | "excel" | "arrow",
    options?: RequestOptions,
  ): Promise<Blob>;

  /**
   * Introspects backend engine capabilities and active feature tiers.
   */
  getCapabilities(options?: RequestOptions): Promise<Record<string, string>>;

  /**
   * Starts a fluent query builder bound to this client.
   */
  query(table?: string): FluentQuery;

  /**
   * Directly executes an HTTP request via the client's configured transport and credentials.
   * The response type defaults to `unknown` (it was `any` in earlier releases); pass the expected
   * shape explicitly, e.g. `client.request<MyRow[]>("/rows")`. Clients returned by
   * `createQueryBuilderClient` always provide this method.
   */
  request?<T = unknown>(path: string, init?: RequestInit, options?: RequestOptions): Promise<T>;
}

/**
 * Creates an official QueryBuilderClient instance.
 */
export function createQueryBuilderClient(
  config: QueryBuilderClientConfig,
): QueryBuilderClient & Required<Pick<QueryBuilderClient, "request">> {
  const rawBaseUrl = config.baseUrl || "";
  // Strip trailing slashes (linear-time `.replace(/\/+$/, "")`).
  let baseUrlEnd = rawBaseUrl.length;
  while (baseUrlEnd > 0 && rawBaseUrl[baseUrlEnd - 1] === "/") baseUrlEnd--;
  const cleanBaseUrl = rawBaseUrl.slice(0, baseUrlEnd);
  const defaultTimeoutMs = config.timeoutMs ?? 30000;
  const fetchFn = config.fetchFn ?? globalThis.fetch;

  if (typeof fetchFn !== "function") {
    throw new Error(
      "QueryBuilderClient: globalThis.fetch is not defined. Please supply a custom fetchFn in config.",
    );
  }

  async function resolveHeaders(perRequestHeaders?: Record<string, string>): Promise<Record<string, string>> {
    let baseHeaders: Record<string, string> = {};
    if (typeof config.headers === "function") {
      baseHeaders = await config.headers();
    } else if (config.headers) {
      baseHeaders = { ...config.headers };
    }

    const merged: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...baseHeaders,
    };

    // Resolve token if Authorization header not already set
    if (!merged["Authorization"] && !merged["authorization"]) {
      let resolvedToken: string | null | undefined = null;
      if (typeof config.token === "function") {
        resolvedToken = await config.token();
      } else if (typeof config.token === "string") {
        resolvedToken = config.token;
      }

      if (resolvedToken && resolvedToken.trim()) {
        const trimmed = resolvedToken.trim();
        merged["Authorization"] =
          trimmed.startsWith("Bearer ") || trimmed.startsWith("Token ")
            ? trimmed
            : `Bearer ${trimmed}`;
      }
    }

    if (perRequestHeaders) {
      Object.assign(merged, perRequestHeaders);
    }

    return merged;
  }

  async function makeRequest<T = unknown>(
    path: string,
    init: RequestInit,
    options?: RequestOptions,
    isBlobResponse: boolean = false,
  ): Promise<T> {
    const url = path.startsWith("http://") || path.startsWith("https://")
      ? path
      : `${cleanBaseUrl}${path.startsWith("/") ? "" : "/"}${path}`;

    const headers = await resolveHeaders(options?.headers);
    const timeoutMs = options?.timeoutMs ?? defaultTimeoutMs;

    const controller = new AbortController();
    let timeoutId: ReturnType<typeof setTimeout> | undefined = undefined;

    if (timeoutMs > 0 && timeoutMs !== Infinity) {
      timeoutId = setTimeout(() => {
        controller.abort(new Error(`QueryBuilderClient: Request timed out after ${timeoutMs}ms`));
      }, timeoutMs);
    }

    let onExternalAbort: (() => void) | undefined;
    if (options?.signal) {
      if (options.signal.aborted) {
        if (timeoutId) clearTimeout(timeoutId);
        throw options.signal.reason || new Error("Request aborted");
      }
      onExternalAbort = () => {
        controller.abort(options.signal?.reason);
      };
      options.signal.addEventListener("abort", onExternalAbort);
    }

    try {
      const response = await fetchFn(url, {
        ...init,
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        let errorData: ErrorPayload | null = null;
        let errorMessage = `QueryBuilderClient HTTP ${response.status}: ${response.statusText}`;
        try {
          const contentType = response.headers?.get ? response.headers.get("content-type") || "" : "";
          if (contentType.includes("application/json") || typeof response.json === "function") {
            try {
              errorData = await response.json();
              const serverMsg = errorData?.detail || errorData?.message || errorData?.error;
              if (serverMsg) {
                const strMsg = typeof serverMsg === "string" ? serverMsg : JSON.stringify(serverMsg);
                errorMessage = `${errorMessage} - ${strMsg}`;
              }
            } catch {
              if (typeof response.text === "function") {
                const text = await response.text();
                if (text) errorMessage = `${errorMessage} - ${text}`;
              }
            }
          } else if (typeof response.text === "function") {
            const text = await response.text();
            if (text) errorMessage = `${errorMessage} - ${text}`;
          }
        } catch {
          // Response body parsing failed; keep default message
        }

        throw new QueryBuilderApiError(
          errorMessage,
          response.status,
          response.statusText,
          errorData,
          url,
        );
      }

      if (isBlobResponse) {
        return (await response.blob()) as unknown as T;
      }

      return (await response.json()) as T;
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (options?.signal && onExternalAbort) {
        options.signal.removeEventListener("abort", onExternalAbort);
      }
    }
  }

  const client: QueryBuilderClient & Required<Pick<QueryBuilderClient, "request">> = {
    async getSchema(options?: RequestOptions): Promise<SchemaSnapshot> {
      // First try standard GET /schema
      try {
        const data = await makeRequest<SchemaEnvelope>("/schema", { method: "GET" }, options);
        return (data?.schema || data) as SchemaSnapshot;
      } catch (err) {
        // If 404 or method not allowed, try fallback POST /introspect or POST /schema
        if (err instanceof QueryBuilderApiError && (err.status === 404 || err.status === 405)) {
          const fallbackData = await makeRequest<SchemaEnvelope>(
            "/introspect",
            {
              method: "POST",
              body: JSON.stringify({ connector: "sqlite" }),
            },
            options,
          );
          return (fallbackData?.schema || fallbackData) as SchemaSnapshot;
        }
        throw err;
      }
    },

    async getCapabilities(options?: RequestOptions): Promise<Record<string, string>> {
      try {
        const data = await makeRequest<CapabilitiesEnvelope>("/capabilities", { method: "GET" }, options);
        return (data?.capabilities || data) as Record<string, string>;
      } catch (err) {
        try {
          const schema = await client.getSchema(options);
          const schemaCapabilities = (schema as SchemaEnvelope | undefined)?.capabilities;
          if (schemaCapabilities) {
            return schemaCapabilities;
          }
        } catch {
          // ignore fallback error
        }
        return {};
      }
    },

    async compile(
      spec: QuerySpec,
      dialect: SqlDialect = "postgres",
      options?: RequestOptions,
    ): Promise<CompileResult> {
      return makeRequest<CompileResult>(
        "/compile",
        {
          method: "POST",
          body: JSON.stringify({ spec, dialect }),
        },
        options,
      );
    },

    async validate(sql: string, options?: RequestOptions): Promise<SqlSafetyValidation> {
      return makeRequest<SqlSafetyValidation>(
        "/validate",
        {
          method: "POST",
          body: JSON.stringify({ sql }),
        },
        options,
      );
    },

    async execute(
      specOrSql: QuerySpec | { sql: string; params?: unknown[] },
      options?: RequestOptions,
    ): Promise<QueryResultData> {
      const payload = "sql" in specOrSql && typeof specOrSql.sql === "string"
        ? { sql: specOrSql.sql, params: specOrSql.params || [] }
        : { spec: specOrSql };

      return makeRequest<QueryResultData>(
        "/execute",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
        options,
      );
    },

    async export(
      spec: QuerySpec,
      format: "csv" | "json" | "parquet" | "excel" | "arrow" = "csv",
      options?: RequestOptions,
    ): Promise<Blob> {
      return makeRequest<Blob>(
        "/export",
        {
          method: "POST",
          body: JSON.stringify({ spec, format }),
        },
        options,
        true,
      );
    },

    query(table?: string): FluentQuery {
      return createQuery(table, client);
    },

    request<T = unknown>(path: string, init: RequestInit = { method: "GET" }, options?: RequestOptions): Promise<T> {
      return makeRequest<T>(path, init, options);
    },
  };

  return client;
}
