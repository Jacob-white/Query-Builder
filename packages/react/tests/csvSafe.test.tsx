import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryResultsTable } from "../src/components/QueryResultsTable";
import { csvCellText } from "../src/utils/csvSafe";
import type { QueryResultData } from "../src/types";

/**
 * A CSV cell whose text starts with `=`, `+`, `-`, `@`, a tab or a carriage return is run as a formula by Excel and
 * LibreOffice when the file is opened, even when the cell is quoted. A query can return text someone else typed and a
 * column alias the caller chose, so the CSV download prefixes such text with an apostrophe. Numbers are left alone, so a
 * negative number stays a number.
 */
describe("csvCellText", () => {
  it.each(["=1+1", '=HYPERLINK("http://x","y")', "+SUM(A1)", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])(
    "puts an apostrophe in front of %j",
    (text) => {
      expect(csvCellText(text)).toBe(`'${text}`);
    },
  );

  it.each(["plain", "", "a=1", "1+1", "x@y.com", "'=quoted", " =1", "é"])("leaves %j as it is", (text) => {
    expect(csvCellText(text)).toBe(text);
  });

  it("leaves numbers, booleans and bigints as the text they print as, so a negative number stays a number", () => {
    expect(csvCellText(-5)).toBe("-5");
    expect(csvCellText(-2.5)).toBe("-2.5");
    expect(csvCellText(7)).toBe("7");
    expect(csvCellText(true)).toBe("true");
    expect(csvCellText(BigInt(-9))).toBe("-9");
  });

  it("writes null and undefined as empty", () => {
    expect(csvCellText(null)).toBe("");
    expect(csvCellText(undefined)).toBe("");
  });

  it("reads any other value as the text it prints as, and protects that", () => {
    expect(csvCellText({ toString: () => "=1+1" })).toBe("'=1+1");
    expect(csvCellText([1, 2])).toBe("1,2");
  });

  it("is linear for a hostile cell", () => {
    const started = performance.now();
    csvCellText("=" + "A".repeat(2_000_000));
    csvCellText("\t".repeat(2_000_000));
    expect(performance.now() - started).toBeLessThan(1000);
  });
});

describe("QueryResultsTable CSV download", () => {
  afterEach(() => vi.restoreAllMocks());

  function download(results: QueryResultData): Promise<string> {
    let created: Blob | null = null;
    global.URL.createObjectURL = vi.fn().mockImplementation((blob: Blob) => {
      created = blob;
      return "blob:csv";
    });
    global.URL.revokeObjectURL = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag === "a") el.click = vi.fn();
      return el;
    });
    render(<QueryResultsTable results={results} />);
    fireEvent.click(screen.getByRole("button", { name: "Export results as CSV" }));
    return new Promise((resolve, reject) => {
      const blob = created as Blob | null;
      if (!blob) return reject(new Error("no file was created"));
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
  }

  it("neutralises a formula in a cell and in a column name, and leaves a negative number alone", async () => {
    const text = await download({
      columns: ["=cmd", "note", "balance"],
      rows: [{ "=cmd": "x", note: "=1+1", balance: -5 }],
      count: 1,
    });
    expect(text).toBe(`"'=cmd","note","balance"\n"x","'=1+1","-5"`);
  });

  it("still doubles a quote inside a cell (control: the existing quoting is unchanged)", async () => {
    const text = await download({ columns: ["a"], rows: [{ a: 'say "hi"' }], count: 1 });
    expect(text).toBe(`"a"\n"say ""hi"""`);
  });
});
