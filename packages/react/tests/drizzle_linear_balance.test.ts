import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { fromDrizzle } from "../src/adapters";

interface Case {
  input: string;
  expected: unknown;
}
interface NestedCase {
  input: string;
  original: unknown;
  expected: unknown;
}
interface Fixture {
  hand: Case[];
  random: Case[];
  nested: NestedCase[];
}

// Outputs recorded from the original per-header parenthesis-balancing implementation.
const fixture = JSON.parse(
  readFileSync(path.join(__dirname, "fixtures", "drizzle_linear_balance.json"), "utf8"),
) as Fixture;

const roundTrip = (source: string): unknown => JSON.parse(JSON.stringify(fromDrizzle(source)));

describe("drizzle linear balancing: parity with the original implementation", () => {
  it("reproduces the hand-written schemas", () => {
    expect(fixture.hand.length).toBeGreaterThan(10);
    for (const c of fixture.hand) expect(roundTrip(c.input)).toEqual(c.expected);
  });

  it("reproduces the seeded random corpus", () => {
    expect(fixture.random.length).toBeGreaterThan(300);
    for (const c of fixture.random) expect(roundTrip(c.input)).toEqual(c.expected);
  });
});

describe("drizzle linear balancing: nested headers (intentional difference)", () => {
  it("does not treat a pgTable inside an already-parsed call as a new table", () => {
    const tables = fromDrizzle("pgTable('a', { x: pgTable('inner', { id: serial('id') }) });");
    expect(tables.map((t) => t.name)).toEqual(["a"]);
  });

  it("keeps a sibling table after a call that contains a nested header", () => {
    const code =
      "pgTable('a', { n: pgTable('inner', { q: text('q') }) });\npgTable('b', { id: serial('id') });";
    expect(fromDrizzle(code).map((t) => t.name)).toEqual(["a", "b"]);
  });

  it("matches the recorded new output, which only drops the nested tables", () => {
    expect(fixture.nested.length).toBeGreaterThan(2);
    for (const c of fixture.nested) {
      const now = roundTrip(c.input);
      expect(now).toEqual(c.expected);
      expect((now as unknown[]).length).toBeLessThan((c.original as unknown[]).length);
    }
  });
});

const N = 50_000;
const BOUND_MS = 1000;

function timed(source: string): number {
  const t0 = performance.now();
  fromDrizzle(source);
  return performance.now() - t0;
}

describe("drizzle linear balancing: timing", () => {
  const unterminated: [string, string][] = [
    ["pgTable('x' repeated", "pgTable('x'".repeat(N)],
    ["const a = pgTable('x' repeated", "const a = pgTable('x'".repeat(N)],
    ["const a = pgTable('x', { repeated", "const a = pgTable('x', {".repeat(N)],
    ["quote-with-paren mix", "pgTable('a(' + ')'".repeat(N)],
    ["escaped quote mix", "pgTable('a\'(' + \")\"".repeat(N)],
    ["backtick mix", "pgTable('a', `(`".repeat(N)],
  ];
  for (const [label, source] of unterminated) {
    it(`${label} (N=${N}) stays under ${BOUND_MS} ms`, () => {
      expect(timed(source)).toBeLessThan(BOUND_MS);
    });
  }

  it("a long single table with N columns stays under the bound", () => {
    let cols = "";
    for (let i = 0; i < N; i++) cols += `c${i}: text('c${i}'),\n`;
    const source = `export const big = pgTable('big', {\n${cols}});`;
    const t0 = performance.now();
    const tables = fromDrizzle(source);
    expect(performance.now() - t0).toBeLessThan(BOUND_MS * 3);
    expect(tables).toHaveLength(1);
    expect(tables[0].columns).toHaveLength(N);
  });

  it("N sequential valid tables stay under the bound", () => {
    const parts: string[] = [];
    for (let i = 0; i < N; i++) parts.push(`export const t${i} = pgTable('t${i}', { id: serial('id') });`);
    const source = parts.join("\n");
    const t0 = performance.now();
    const tables = fromDrizzle(source);
    expect(performance.now() - t0).toBeLessThan(BOUND_MS * 3);
    expect(tables).toHaveLength(N);
  });
});
