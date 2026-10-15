import { describe, it, expect } from "vitest";
import { coerceValue } from "../src/utils/queryHelpers/filterKinds";
import {
  describeHaving,
  havingForSpec,
  havingKind,
  havingTargets,
  type HavingFilter,
} from "../src/utils/queryHelpers/havingFilters";
import { columnLabel } from "../src/utils/queryHelpers/summaryText";

const types: Record<string, string> = { "t.when": "DATE", "t.flag": "BOOLEAN", "t.n": "INTEGER" };
const typeOf = (table: string, column: string) => types[`${table}.${column}`];

describe("edges of the query helpers", () => {
  it("refuses an operator that does not fit the kind, and a Yes/No with no choice, with a message", () => {
    expect(coerceValue("json", "=", "x")).toEqual({ ok: false, error: "That choice does not fit this column. Pick another." });
    expect(coerceValue("boolean", "=", null)).toEqual({ ok: false, error: "Choose Yes or No." });
  });

  it("skips an aggregate it does not know, and a MIN or MAX over a Yes/No column", () => {
    const selected = {
      "t.n": { table: "t", name: "n", aggregate: "stddev" },
      "t.flag": { table: "t", name: "flag", aggregate: "max" },
      "t.when": { table: "t", name: "when", aggregate: "max" },
    };
    const targets = havingTargets(selected, ["t.n", "t.flag", "t.when"], typeOf);
    expect(targets.map((t) => t.column)).toEqual(["*", "t.when"]); // the row count is always offered
  });

  it("takes the kind of a MIN or MAX from the column, and a number for the rest", () => {
    expect(havingKind({ column: "t.when", agg: "MAX", label: "x", baseType: "DATE" })).toBe("date");
    expect(havingKind({ column: "t.when", agg: "MIN", label: "x" })).toBe("other");
    expect(havingKind({ column: "t.n", agg: "SUM", label: "x" })).toBe("number");
  });

  it("describes a filter whose aggregate is no longer in the query, with a fallback name", () => {
    const rows: HavingFilter = { id: "1", column: "*", agg: "COUNT", operator: ">", value: 5 };
    expect(describeHaving(rows, [])).toBe("Number of rows is greater than 5");
    const column: HavingFilter = { id: "2", column: "t.n", agg: "SUM", operator: ">=", value: 7 };
    expect(describeHaving(column, [])).toBe("SUM(t.n) is at least 7");
  });

  it("keeps a filter only while its aggregate is in the spec, reading either spelling of the key and ignoring junk", () => {
    const having: HavingFilter[] = [{ id: "1", column: "t.n", agg: "SUM", operator: ">", value: 1 }];
    expect(havingForSpec(having, [{ column: "t.n", aggregate: "sum" }])).toHaveLength(1);
    expect(havingForSpec(having, [{ column: "t.n", agg: "sum" }, "plain", null])).toHaveLength(1);
    expect(havingForSpec(having, "not a list")).toEqual([]);
    expect(havingForSpec(having, [{ column: "t.n" }])).toEqual([]);
  });

  it("names an aggregate it has no words for by the aggregate itself", () => {
    expect(columnLabel({ table: "t", name: "n", aggregate: "median" })).toBe("median n");
  });
});
