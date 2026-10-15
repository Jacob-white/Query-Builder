import { describe, it, expect } from "vitest";
import { slugifyFilenamePart, sqlFileText, sqlFilename } from "../src/utils/queryHelpers/sqlFile";

const NOW = new Date("2026-10-15T08:30:00Z");

describe("sql file helpers", () => {
  it("makes a file-name-safe piece, never empty", () => {
    expect(slugifyFilenamePart("  My table/1 ")).toBe("My-table-1");
    expect(slugifyFilenamePart("***")).toBe("export");
  });

  it("names the file for the table and the day", () => {
    expect(sqlFilename("feature_flag", NOW)).toBe("query-feature_flag-2026-10-15.sql");
    expect(sqlFilename(undefined, NOW)).toBe("query-results-2026-10-15.sql");
    expect(sqlFilename("a/b", NOW)).toBe("query-a-b-2026-10-15.sql");
  });

  it("puts a header comment first and ends the statement with exactly one semicolon", () => {
    const text = sqlFileText("SELECT 1\n", "account", NOW);
    expect(text.startsWith("-- Query Builder: account, 2026-10-15 08:30:00 UTC")).toBe(true);
    expect(text.trimEnd().endsWith("SELECT 1;")).toBe(true);
    expect(sqlFileText("SELECT 1;;", undefined, NOW).trimEnd().endsWith("SELECT 1;")).toBe(true);
    expect(sqlFileText("SELECT 1;", undefined, NOW)).toContain("-- Query Builder: query,");
  });

  it("uses today when no time is given", () => {
    expect(sqlFilename("t")).toMatch(/^query-t-\d{4}-\d{2}-\d{2}\.sql$/);
    expect(sqlFileText("SELECT 1", "t")).toMatch(/^-- Query Builder: t, \d{4}-/);
  });
});
