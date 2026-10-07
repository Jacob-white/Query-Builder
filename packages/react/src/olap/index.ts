/**
 * In-memory client OLAP SQL execution and local file ingestion.
 * ============================================================
 * 100% pure TypeScript engine with zero external wasm or CDN runtime dependencies.
 */

export * from "../drivers/duckdbDriver";
export * from "../utils/localDataIngest";
export type {
  SchemaSnapshot,
  TableMeta,
  QueryResultData,
  SqlDialect,
} from "../types";
