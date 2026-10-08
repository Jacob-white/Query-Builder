/**
 * Local Data File Ingest Utility for In-Browser OLAP.
 * ==================================================
 * Provides file format detection, text/binary intake, and automatic
 * table registration for CSV, TSV, JSON, and Parquet files into the ClientOlapEngine.
 */

import type { ClientOlapEngine, DuckDBTableMeta } from "../types";

/**
 * Capability check by property access (no `in` operator) so Proxy / RPC-facade engines that only
 * trap `get`, and function-target proxies (Comlink style), are recognised like plain objects.
 */
function isClientOlapEngine(value: unknown): value is ClientOlapEngine {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) return false;
  const candidate: { query?: unknown; ingestCsv?: unknown } = value;
  return typeof candidate.query === "function" && typeof candidate.ingestCsv === "function";
}

export type IngestibleFormat = "csv" | "tsv" | "json" | "parquet" | "unknown";

/**
 * Detects format of file from filename or mime type.
 */
export function detectFileFormat(file: { name: string; type?: string }): IngestibleFormat {
  const name = file.name.toLowerCase();
  if (name.endsWith(".csv")) return "csv";
  if (name.endsWith(".tsv") || name.endsWith(".tab")) return "tsv";
  if (name.endsWith(".json") || name.endsWith(".jsonl") || name.endsWith(".ndjson")) return "json";
  if (name.endsWith(".parquet") || name.endsWith(".pq")) return "parquet";

  if (file.type) {
    if (file.type.includes("csv")) return "csv";
    if (file.type.includes("tab-separated")) return "tsv";
    if (file.type.includes("json")) return "json";
  }

  return "unknown";
}

/**
 * Sanitizes file base name to a valid SQL table identifier.
 */
export function sanitizeTableName(fileName: string): string {
  const base = fileName.replace(/\.[^/.]+$/, "");
  const sanitized = base.replace(/[^a-zA-Z0-9_]/g, "_").toLowerCase();
  return sanitized.replace(/^_+|_+$/g, "") || "local_table";
}

/**
 * Reads browser Blob/File as text.
 */
export function readFileAsText(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file as text"));
    reader.readAsText(file);
  });
}

/**
 * Reads browser Blob/File as ArrayBuffer.
 */
export function readFileAsArrayBuffer(file: Blob): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(new Error("Failed to read file as ArrayBuffer"));
    reader.readAsArrayBuffer(file);
  });
}

export interface LocalFileIngestOptions {
  tableName?: string;
}

/**
 * Coordinates reading and ingesting a local file into the client OLAP engine.
 * Supports both `(file, engine, options?)` and `(engine, file, options?)` invocation patterns.
 */
export function ingestLocalFile(
  file: File,
  engine: ClientOlapEngine,
  customTableName?: string | LocalFileIngestOptions,
): Promise<DuckDBTableMeta>;
export function ingestLocalFile(
  engine: ClientOlapEngine,
  file: File,
  options?: string | LocalFileIngestOptions,
): Promise<DuckDBTableMeta>;
export async function ingestLocalFile(
  first: File | ClientOlapEngine,
  second: File | ClientOlapEngine,
  third?: string | LocalFileIngestOptions,
): Promise<DuckDBTableMeta> {
  let file: File;
  let engine: ClientOlapEngine;

  if (isClientOlapEngine(first)) {
    engine = first as ClientOlapEngine;
    file = second as File;
  } else {
    file = first as File;
    engine = second as ClientOlapEngine;
  }

  let rawTableName: string | undefined;
  if (typeof third === "string") {
    rawTableName = third;
  } else if (third && typeof third === "object" && "tableName" in third) {
    rawTableName = third.tableName;
  }

  const format = detectFileFormat(file);
  if (format === "unknown") {
    throw new Error(`Unsupported file format for '${file.name}'. Supported formats: CSV, TSV, JSON, Parquet.`);
  }

  const tableName = rawTableName ? sanitizeTableName(rawTableName) : sanitizeTableName(file.name);

  if (format === "csv" || format === "tsv") {
    const text = await readFileAsText(file);
    const meta = await engine.ingestCsv(tableName, text, {
      delimiter: format === "tsv" ? "\t" : ",",
      header: true,
      inferTypes: true,
    });
    meta.fileSource = file.name;
    return meta;
  }

  if (format === "json") {
    const text = await readFileAsText(file);
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      // Try JSON Lines (NDJSON)
      const lines = text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
      parsed = lines.map((l) => JSON.parse(l));
    }
    const rows: Record<string, unknown>[] = Array.isArray(parsed) ? parsed : [parsed as Record<string, unknown>];
    const meta = await engine.ingestJson(tableName, rows);
    meta.fileSource = file.name;
    return meta;
  }

  const buffer = await readFileAsArrayBuffer(file);
  const meta = await engine.ingestParquet(tableName, new Uint8Array(buffer));
  meta.fileSource = file.name;
  return meta;
}

