/**
 * Regression tests for the ReDoS (polynomial regular expression) hardening of
 * duckdbDriver, the schema adapters, the client, the SQL compiler hook, the visual
 * query builder and the safety validator.
 *
 * 1. Golden tests: outputs recorded from the original (pre-hardening) implementations
 *    are stored in `tests/fixtures/regex_golden_*.json`; the inputs are regenerated
 *    deterministically by `regex_golden_inputs.ts`. The current implementations must
 *    reproduce every recorded output. Private helpers are loaded straight from the
 *    source files.
 * 2. Linear-time tests: adversarial 50 000 character inputs must finish well under 1s.
 */
import { describe, it, expect, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

import { InMemoryOlapEngine, evaluateCondition } from "../src/drivers/duckdbDriver";
import { fromSqlAlchemy } from "../src/adapters/sqlalchemy";
import { fromDrizzle } from "../src/adapters/drizzle";
import { fromPrisma } from "../src/adapters/prisma";
import { toSnakeCase } from "../src/adapters/utils";
import { sanitizeTableName } from "../src/utils/localDataIngest";
import { validateSqlSafety } from "../src/utils/safety";
import { createQueryBuilderClient } from "../src/client";

import { CORPORA, ENGINE_ROWS, digest, outcome } from "./regex_golden_inputs";

const N = 50_000;
const BUDGET_MS = 1000;
const J = JSON.stringify;

type Golden = Record<string, string[]>;
function loadGolden(name: string): Golden {
  return JSON.parse(fs.readFileSync(path.resolve(process.cwd(), `tests/fixtures/regex_golden_${name}.json`), "utf8")) as Golden;
}
const goldenDuckdb = loadGolden("duckdb");
const goldenAdapters = loadGolden("adapters");
const goldenMisc = loadGolden("misc");

/** Asserts `compute(input)` reproduces the recorded output for every input of a corpus. */
async function expectGolden(
  golden: Golden,
  site: keyof typeof CORPORA,
  compute: (input: string) => string | Promise<string>,
): Promise<void> {
  const inputs = CORPORA[site];
  const expected = golden[site];
  expect(expected, `fixture for ${site}`).toBeDefined();
  expect(expected.length, `fixture size for ${site}`).toBe(inputs.length);
  for (let i = 0; i < inputs.length; i++) {
    expect(digest(await compute(inputs[i])), `${site}: ${J(inputs[i])}`).toBe(expected[i]);
  }
}

/** Loads private top-level helpers (and `const X = /re/;` lines) out of a source file. */
function loadPrivate<T>(relPath: string, names: string[]): T {
  const src = fs.readFileSync(path.resolve(process.cwd(), relPath), "utf8");
  const parts: string[] = [];
  for (const m of src.matchAll(/^const [A-Za-z_]+ = \/.*\/[a-z]*;$/gm)) parts.push(m[0]);
  // Top-level functions: from a `function` line to the next line that is exactly `}`.
  const lines = src.split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].startsWith("function ")) continue;
    let end = i;
    while (end < lines.length && lines[end].replace(/\r$/, "") !== "}") end++;
    parts.push(lines.slice(i, end + 1).join("\n"));
    i = end;
  }
  const js = ts.transpileModule(parts.join("\n\n"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(`${js}\nreturn { ${names.join(", ")} };`)() as T;
}

async function timed<R>(fn: () => R | Promise<R>): Promise<number> {
  const start = performance.now();
  await fn();
  return performance.now() - start;
}

interface DuckHelpers {
  splitOnAnd(s: string): string[];
  matchAlias(s: string): { expr: string; alias: string } | null;
  matchAggregate(s: string): { fn: string; arg: string } | null;
  matchSelectList(s: string): string | null;
  stripTrailingSemicolons(s: string): string;
}
const duck = loadPrivate<DuckHelpers>("src/drivers/duckdbDriver.ts", [
  "splitOnAnd",
  "matchAlias",
  "matchAggregate",
  "matchSelectList",
  "stripTrailingSemicolons",
]);

describe("duckdbDriver helpers reproduce the recorded original behavior", () => {
  it("splitOnAnd", () => expectGolden(goldenDuckdb, "splitOnAnd", (s) => J(duck.splitOnAnd(s))));
  it("matchAlias", () => expectGolden(goldenDuckdb, "matchAlias", (s) => J(duck.matchAlias(s))));
  it("matchAggregate", () => expectGolden(goldenDuckdb, "matchAggregate", (s) => J(duck.matchAggregate(s))));
  it("matchSelectList (incl. quirks)", () =>
    expectGolden(goldenDuckdb, "matchSelectList", (s) => {
      const r = duck.matchSelectList(s);
      return J(r === null ? null : r.trim());
    }));
  it("stripTrailingSemicolons", () =>
    expectGolden(goldenDuckdb, "semicolons", (s) => J(duck.stripTrailingSemicolons(s))));
});

describe("InMemoryOlapEngine reproduces the recorded original behavior", () => {
  it("queries (representative, templated and token-soup)", async () => {
    const engine = new InMemoryOlapEngine();
    await engine.ingestJson("emp", ENGINE_ROWS);
    await expectGolden(goldenDuckdb, "engineQueries", (sql) =>
      outcome(async () => {
        const r = await engine.query(sql);
        return { columns: r.columns, rows: r.rows };
      }),
    );
  });

  it("evaluateCondition BETWEEN", async () => {
    await expectGolden(goldenDuckdb, "betweenValues", (v) => J(evaluateCondition({ v: 7 }, "v", "BETWEEN", v)));
  });
});

describe("adapters reproduce the recorded original behavior", () => {
  it("fromSqlAlchemy", () => expectGolden(goldenAdapters, "sqlalchemy", (s) => outcome(() => fromSqlAlchemy(s))));
  it("fromDrizzle", () => expectGolden(goldenAdapters, "drizzle", (s) => outcome(() => fromDrizzle(s))));
  it("fromPrisma", () => expectGolden(goldenAdapters, "prisma", (s) => outcome(() => fromPrisma(s))));
  it("toSnakeCase and sanitizeTableName", () =>
    expectGolden(goldenAdapters, "names", (n) => J([toSnakeCase(n), sanitizeTableName(n), sanitizeTableName(n + ".csv")])));
});

describe("createQueryBuilderClient baseUrl normalization", () => {
  it("strips trailing slashes exactly like before", async () => {
    await expectGolden(goldenMisc, "baseUrls", async (base) => {
      const fetchFn = vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: "x" });
      const client = createQueryBuilderClient({ baseUrl: base, fetchFn: fetchFn as unknown as typeof fetch });
      await client.request("/p").catch(() => undefined);
      return String(fetchFn.mock.calls[0][0]);
    });
  });
});

describe("validateSqlSafety WAITFOR DELAY detection", () => {
  it("reproduces the recorded results", () =>
    expectGolden(goldenMisc, "safety", (sql) => J(validateSqlSafety(sql))));
});

describe("useSqlCompiler count query helpers", () => {
  const hook = loadPrivate<{
    stripTrailingSemicolons(s: string): string;
    stripTrailingOrderBy(s: string): string;
  }>("src/hooks/useSqlCompiler.ts", ["stripTrailingSemicolons", "stripTrailingOrderBy"]);

  it("stripTrailingSemicolons", () =>
    expectGolden(goldenMisc, "hookSemicolons", (s) => J(hook.stripTrailingSemicolons(s))));
  it("stripTrailingOrderBy", () =>
    expectGolden(goldenMisc, "hookOrderBy", (s) => J(hook.stripTrailingOrderBy(s))));
});

describe("VisualQueryBuilder normalizeSqlForCompare", () => {
  const vqb = loadPrivate<{ normalizeSqlForCompare(s: string): string }>(
    "src/components/VisualQueryBuilder.tsx",
    ["normalizeSqlForCompare", "stripTrailingSemicolons"],
  );
  it("reproduces the recorded results", () =>
    expectGolden(goldenMisc, "vqb", (s) => J(vqb.normalizeSqlForCompare(s))));
});

// ---------------------------------------------------------------------------
// linear time on adversarial input
// ---------------------------------------------------------------------------

describe("adversarial inputs run in linear time", () => {
  const sp = " ".repeat(N);

  it("InMemoryOlapEngine.query", async () => {
    const engine = new InMemoryOlapEngine();
    await engine.ingestJson("emp", [{ a: 1, dept: "x" }, { a: 2, dept: "y" }]);
    const queries = [
      `SELECT a${sp}! FROM emp`,
      `SELECT a${sp}`,
      `SELECT dept, SUM(a${sp}b FROM emp`,
      `SELECT a FROM emp WHERE ${"a".repeat(N)}`,
      `SELECT a FROM emp WHERE a${sp}x`,
      `SELECT a FROM emp WHERE a BETWEEN 1${sp}x`,
      `SELECT a FROM emp${";".repeat(N)}x`,
      `SELECT a FROM emp WHERE a > 0${sp}GROUP${sp}BY${sp}`,
      `SELECT a FROM emp ORDER${sp}x`,
      `SELECT a ${"AS ".repeat(N / 3)}`,
      `SELECT ${"SUM( ".repeat(N / 5)} FROM emp`,
      `SELECT * FROM emp${sp};${sp}`,
    ];
    for (const sql of queries) {
      const ms = await timed(() => engine.query(sql).catch(() => undefined));
      expect(ms, sql.slice(0, 40)).toBeLessThan(BUDGET_MS);
    }
  });

  it("evaluateCondition BETWEEN", async () => {
    expect(await timed(() => evaluateCondition({ v: 1 }, "v", "BETWEEN", `${sp}x`))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => evaluateCondition({ v: 1 }, "v", "BETWEEN", `1${sp}ANDx`))).toBeLessThan(BUDGET_MS);
  });

  it("fromSqlAlchemy", async () => {
    const inputs = [
      "class A(Base):\n" + "\n".repeat(N) + "x = 1",
      "\n".repeat(N) + "x",
      "class A(Base):\n  a: " + sp + "Column(",
      "class A(Base):\n  a" + sp + ": x" + sp + "Column(",
      " ".repeat(N) + "classx",
    ];
    for (const src of inputs) {
      expect(await timed(() => fromSqlAlchemy(src))).toBeLessThan(BUDGET_MS);
    }
  });

  it("fromDrizzle", async () => {
    const inputs = [
      "const a:" + sp + "x",
      "const a" + sp + ":" + sp + "pgTable(",
      "const t = pgTable('t', {\n  id: " + "a".repeat(N) + "\n});",
      "const t = pgTable('t', {\n  id: " + "a ".repeat(N / 2) + "\n});",
      "const ".repeat(N / 6),
    ];
    for (const src of inputs) {
      expect(await timed(() => fromDrizzle(src))).toBeLessThan(BUDGET_MS);
    }
  });

  it("fromPrisma", async () => {
    const inputs = [
      "model A {" + "{ ".repeat(N / 2),
      "model A {" + "x{".repeat(N / 2) + "}",
      "model A {" + "{}".repeat(N / 2),
      "model A {" + "}".repeat(N),
      "model A {".repeat(N / 9 + 1),
      "model A {".repeat(N / 9 + 1) + "}",
    ];
    for (const src of inputs) {
      expect(await timed(() => fromPrisma(src))).toBeLessThan(BUDGET_MS);
    }
  });

  it("toSnakeCase, sanitizeTableName", async () => {
    expect(await timed(() => toSnakeCase("_".repeat(N) + "a" + "_".repeat(N) + "!"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => sanitizeTableName("a" + "_".repeat(N) + "b"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => sanitizeTableName("_".repeat(N) + "b" + "_".repeat(N) + "!.csv"))).toBeLessThan(BUDGET_MS);
  });

  it("createQueryBuilderClient baseUrl", async () => {
    const fetchFn = vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: "x" });
    const ms = await timed(() =>
      createQueryBuilderClient({ baseUrl: "/".repeat(4 * N) + "x", fetchFn: fetchFn as unknown as typeof fetch }),
    );
    expect(ms).toBeLessThan(BUDGET_MS);
  });

  it("validateSqlSafety WAITFOR scanning", async () => {
    const inputs = [
      "WAITFOR " + "/**/ ".repeat(N / 5) + "X",
      "WAITFOR" + sp + "X",
      "WAITFOR /*" + "*/ /*".repeat(N / 5) + "X",
      "WAITFOR ".repeat(N / 8),
      "WAITFOR /* ".repeat(N / 11),
      "WAITFOR /**/ " + "/**/ ".repeat(N / 6) + "DELAY '0:0:1'",
    ];
    for (const sql of inputs) {
      expect(await timed(() => validateSqlSafety(sql))).toBeLessThan(BUDGET_MS);
    }
    expect(validateSqlSafety(inputs[5]).violations.join(" ")).toContain("WAITFOR DELAY");
  });

  it("useSqlCompiler and VisualQueryBuilder helpers", async () => {
    const hook = loadPrivate<{
      stripTrailingSemicolons(s: string): string;
      stripTrailingOrderBy(s: string): string;
    }>("src/hooks/useSqlCompiler.ts", ["stripTrailingSemicolons", "stripTrailingOrderBy"]);
    const vqb = loadPrivate<{ normalizeSqlForCompare(s: string): string }>(
      "src/components/VisualQueryBuilder.tsx",
      ["normalizeSqlForCompare", "stripTrailingSemicolons"],
    );
    expect(await timed(() => hook.stripTrailingSemicolons(";".repeat(N) + "x"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => hook.stripTrailingSemicolons(";" + sp + "x"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => hook.stripTrailingOrderBy(sp + "x"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => hook.stripTrailingOrderBy("x" + sp + "ORDER" + sp + "BY"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => hook.stripTrailingOrderBy(" ORDER BY".repeat(N / 9) + ")"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => vqb.normalizeSqlForCompare(";".repeat(N) + "x"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => vqb.normalizeSqlForCompare(" , ".repeat(N / 3) + sp + "a"))).toBeLessThan(BUDGET_MS);
    expect(await timed(() => vqb.normalizeSqlForCompare("'".repeat(N)))).toBeLessThan(BUDGET_MS);
  });
});
