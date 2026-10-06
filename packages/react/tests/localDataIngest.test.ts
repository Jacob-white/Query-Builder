import { describe, it, expect, beforeEach } from "vitest";
import {
  detectFileFormat,
  sanitizeTableName,
  readFileAsText,
  readFileAsArrayBuffer,
  ingestLocalFile,
} from "../src/utils/localDataIngest";
import { InMemoryOlapEngine } from "../src/drivers/duckdbDriver";

describe("localDataIngest Utilities", () => {
  let engine: InMemoryOlapEngine;

  beforeEach(() => {
    engine = new InMemoryOlapEngine();
  });

  describe("detectFileFormat", () => {
    it("detects format by extension", () => {
      expect(detectFileFormat({ name: "data.csv" })).toBe("csv");
      expect(detectFileFormat({ name: "DATA.CSV" })).toBe("csv");
      expect(detectFileFormat({ name: "export.tsv" })).toBe("tsv");
      expect(detectFileFormat({ name: "export.tab" })).toBe("tsv");
      expect(detectFileFormat({ name: "records.json" })).toBe("json");
      expect(detectFileFormat({ name: "stream.jsonl" })).toBe("json");
      expect(detectFileFormat({ name: "stream.ndjson" })).toBe("json");
      expect(detectFileFormat({ name: "metrics.parquet" })).toBe("parquet");
      expect(detectFileFormat({ name: "metrics.pq" })).toBe("parquet");
      expect(detectFileFormat({ name: "random.txt" })).toBe("unknown");
    });

    it("detects format by mime type fallback", () => {
      expect(detectFileFormat({ name: "blob", type: "text/csv" })).toBe("csv");
      expect(detectFileFormat({ name: "blob", type: "text/tab-separated-values" })).toBe("tsv");
      expect(detectFileFormat({ name: "blob", type: "application/json" })).toBe("json");
      expect(detectFileFormat({ name: "blob", type: "application/octet-stream" })).toBe("unknown");
    });
  });

  describe("sanitizeTableName", () => {
    it("converts filename to valid SQL identifier", () => {
      expect(sanitizeTableName("customer_churn_2026.csv")).toBe("customer_churn_2026");
      expect(sanitizeTableName("My Sales Report (Q1).xlsx.tsv")).toBe("my_sales_report__q1__xlsx");
      expect(sanitizeTableName("___leading_and_trailing___")).toBe("leading_and_trailing");
      expect(sanitizeTableName("")).toBe("local_table");
    });
  });

  describe("readFileAsText and readFileAsArrayBuffer", () => {
    it("reads a Blob as text", async () => {
      const blob = new Blob(["hello world"], { type: "text/plain" });
      const text = await readFileAsText(blob);
      expect(text).toBe("hello world");
    });

    it("reads a Blob as ArrayBuffer", async () => {
      const bytes = new Uint8Array([1, 2, 3, 4]);
      const blob = new Blob([bytes]);
      const buffer = await readFileAsArrayBuffer(blob);
      expect(new Uint8Array(buffer)).toEqual(bytes);
    });
  });

  describe("ingestLocalFile", () => {
    it("ingests CSV file", async () => {
      const file = new File(["id,val\n1,foo\n2,bar"], "test_data.csv", { type: "text/csv" });
      const meta = await ingestLocalFile(file, engine);

      expect(meta.name).toBe("test_data");
      expect(meta.rowCount).toBe(2);
      expect(meta.fileSource).toBe("test_data.csv");
    });

    it("ingests TSV file", async () => {
      const file = new File(["id\tval\n1\tfoo"], "test_data.tsv", { type: "text/tab-separated-values" });
      const meta = await ingestLocalFile(file, engine, "custom_tsv");

      expect(meta.name).toBe("custom_tsv");
      expect(meta.rowCount).toBe(1);
    });

    it("ingests JSON and NDJSON files", async () => {
      const jsonFile = new File([JSON.stringify([{ a: 1 }, { a: 2 }])], "records.json", {
        type: "application/json",
      });
      const meta = await ingestLocalFile(jsonFile, engine);
      expect(meta.name).toBe("records");
      expect(meta.rowCount).toBe(2);

      const ndjsonFile = new File(['{"x": 10}\n{"x": 20}'], "stream.ndjson");
      const meta2 = await ingestLocalFile(ndjsonFile, engine);
      expect(meta2.name).toBe("stream");
      expect(meta2.rowCount).toBe(2);
    });

    it("ingests Parquet file", async () => {
      const validBuffer = new Uint8Array([0x50, 0x41, 0x52, 0x31, 0x00, 0x00]);
      const parquetFile = new File([validBuffer], "dataset.parquet");
      const meta = await ingestLocalFile(parquetFile, engine);

      expect(meta.name).toBe("dataset");
      expect(meta.sourceType).toBe("parquet");
    });

    it("throws error on unsupported file format", async () => {
      const badFile = new File(["unknown"], "image.png");
      await expect(ingestLocalFile(badFile, engine)).rejects.toThrow("Unsupported file format");
    });
  });
});
