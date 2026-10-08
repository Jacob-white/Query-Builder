/**
 * CodeQL js/polynomial-redos hardening of the drizzle / prisma source-string parsers.
 *
 * 1. Golden test: `tests/fixtures/regex_codeql_adapters.json` holds outputs recorded from the
 *    original regex-based implementation for a table of hand written inputs plus seeded random
 *    corpora. The inputs are regenerated deterministically below.
 * 2. Timing tests: CodeQL's attack strings (and variants) at N = 50 000 repetitions.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fromDrizzle } from "../src/adapters/drizzle";
import { fromPrisma } from "../src/adapters/prisma";

const N = 50_000;
const BUDGET_MS = 1000;
const FIXTURE = path.join(__dirname, "fixtures", "regex_codeql_adapters.json");

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const DRIZZLE_FIXED: string[] = [
  `export const roleEnum = pgEnum("role", ["admin", "user", 'guest']);
export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  role: roleEnum("role").notNull(),
  name: text("name").default("x"),
});
export const posts = pgTable("posts", {
  id: serial("id").primaryKey(),
  authorId: integer("author_id").references(() => users.id),
}, (t) => ({ pk: primaryKey({ columns: [t.id] }) }));`,
  `export const users: PgTableWithColumns<any> = pgTable("users", { id: serial("id").primaryKey() });
const posts : Foo<Bar>
  = pgTable ( 'posts' , { id: serial("id"), uid: integer("uid").references(() => users.id) });`,
  `const t = mysqlTable("t", { id: int("id").primaryKey() });
const e = mysqlEnum("e", ["a","b"]);
const s = sqliteTable(\`s\`, { id: integer("id").primaryKey() });
const se = sqliteEnum('se', ['x']);
pgTable("bare", { id: serial("id").primaryKey() });
export  const   spaced   =   pgEnum( "sp" ,  [ "p" , "q" ] ) ;`,
  `const a = 5;
const x: Foo
export const y = pgTable("y", { id: serial("id").primaryKey() });
const z = pgEnum("z", []);
const mixed = pgEnum("m'x", ["a"]);
const bad = pgTable("nope"`,
  `const noClose = pgEnum("ne", ["a", "b"
const t2 = pgTable("t2", { id: serial("id").primaryKey() });
xconst q = pgTable("q", { id: serial("id") });
const w = pgTable ("w", { id: serial("id") });
const v = mypgTable("v", { id: serial("id") });`,
];

const PRISMA_FIXED: string[] = [
  `enum Role {
  ADMIN // admin
  USER
}
model User {
  id Int @id
  role Role
  @@map("users")
}`,
  "enum A {}\nenum B { X }\nenumx C { Y }\nenum  D\n{\n Z\n}\nenum E {\nenum F {\n P\n}",
  "enum Unclosed {\n A\n B\nmodel M {\n id Int @id\n}",
  "xenum G{H}enum I{J}enum 9{K}",
];

const DR_TOKENS = [
  "export ", "const ", "x", "y1", " ", "  ", "\n", " = ", "=", ": T", ":", ": Foo<Bar>",
  "pgTable", "pgEnum", "mysqlTable", "mysqlEnum", "sqliteTable", "sqliteEnum", "(", ")",
  '"t"', "'u'", "`v`", '"', "'", ", ", ",", "[", "]", '["a","b"]', '{ id: serial("id") }',
  "{", "}", "const a = ", "export const ", ";\n",
];

const PR_TOKENS = [
  "enum ", "enum", " ", "  ", "\n", "A", "B1", "{", "}", "X\n", "Y // c\n", "model ", "M ",
  '@@map("m")', "id Int @id\n", "enumenum", "{{", "|",
];

function soup(rand: () => number, tokens: string[], count: number): string {
  let s = "";
  for (let i = 0; i < count; i++) s += tokens[Math.floor(rand() * tokens.length)];
  return s;
}

function structuredDrizzle(rand: () => number): string {
  const pick = <T>(a: T[]): T => a[Math.floor(rand() * a.length)];
  const ws = () => pick(["", " ", "  ", "\n", " \n "]);
  const wsReq = () => pick([" ", "  ", "\n"]);
  const q = () => pick(['"', "'", "`"]);
  const parts: string[] = [];
  const nvars: string[] = [];
  const n = 1 + Math.floor(rand() * 5);
  for (let i = 0; i < n; i++) {
    const exp = rand() < 0.5 ? "export" + wsReq() : "";
    const v = `v${i}`;
    nvars.push(v);
    if (rand() < 0.3) {
      const kw = pick(["pgEnum", "mysqlEnum", "sqliteEnum"]);
      const vals = Array.from({ length: Math.floor(rand() * 4) }, (_, j) => `${q()}val${j}${q()}`);
      parts.push(
        `${exp}const${wsReq()}${v}${ws()}=${ws()}${kw}(${ws()}${q()}en${i}${q()}${ws()},${ws()}[${vals.join(pick([",", ", ", " ,\n"]))}]${ws()})${pick([";", ""])}`,
      );
    } else {
      const kw = pick(["pgTable", "mysqlTable", "sqliteTable"]);
      const type =
        rand() < 0.3 ? `${ws()}:${ws()}${pick(["PgTable", "Foo<Bar, Baz>", "Table<{ a: 1 }>"])}` : "";
      const head = rand() < 0.85 ? `${exp}const${wsReq()}${v}${ws()}${type}${ws()}=${ws()}` : "";
      const ref =
        i > 0 && rand() < 0.5 ? `, ref: integer("ref").references(() => ${nvars[i - 1]}.id)` : "";
      parts.push(
        `${head}${kw}${pick(["", " "])}(${ws()}${q()}tbl${i}${q()}${ws()},${ws()}{ id: serial("id").primaryKey()${ref}, name: text("name").notNull() }${ws()})${pick([";", ""])}`,
      );
    }
    if (rand() < 0.3) {
      parts.push(pick(["const k = 5;", "// comment", "import { x } from 'y';", "const o = { a: 1 };"]));
    }
  }
  return parts.join(pick(["\n", "\n\n", ";\n"]));
}

function structuredPrisma(rand: () => number): string {
  const pick = <T>(a: T[]): T => a[Math.floor(rand() * a.length)];
  const parts: string[] = [];
  const n = 1 + Math.floor(rand() * 4);
  for (let i = 0; i < n; i++) {
    if (rand() < 0.6) {
      const vals = Array.from({ length: Math.floor(rand() * 4) }, (_, j) => `V${j}${pick(["", " // c"])}`);
      parts.push(
        `enum${pick([" ", "  ", "\n"])}E${i}${pick(["", " ", "\n"])}{${pick(["", "\n"])}${vals.join("\n")}${pick(["", "\n"])}}`,
      );
    } else {
      parts.push(`model M${i} {\n  id Int @id\n  @@map("m${i}")\n}`);
    }
  }
  return parts.join("\n");
}

const N_STRUCT_D = 150;
const N_STRUCT_P = 100;

function build(): { drizzle: string[]; prisma: string[] } {
  const rand = mulberry32(20260508);
  const drizzle = [...DRIZZLE_FIXED];
  const prisma = [...PRISMA_FIXED];
  for (let i = 0; i < N_STRUCT_D; i++) drizzle.push(structuredDrizzle(rand));
  for (let i = 0; i < N_STRUCT_P; i++) prisma.push(structuredPrisma(rand));
  for (let i = 0; i < 150; i++) drizzle.push(soup(rand, DR_TOKENS, 3 + Math.floor(rand() * 40)));
  for (let i = 0; i < 100; i++) prisma.push(soup(rand, PR_TOKENS, 3 + Math.floor(rand() * 30)));
  return { drizzle, prisma };
}

function safe(fn: () => unknown): string {
  try {
    return JSON.stringify(fn()) ?? "undefined";
  } catch (e) {
    return "throws:" + (e as Error).name;
  }
}

function digestAll() {
  const c = build();
  return {
    drizzle: c.drizzle.map((s) => safe(() => fromDrizzle(s))),
    prisma: c.prisma.map((s) => safe(() => fromPrisma(s))),
  };
}

/**
 * Structured drizzle cases whose quote chars are mismatched at random (a double quote closed by a
 * backtick, ...). The shifted quote state makes an earlier table's call span run past later table
 * headers. Those headers lie inside an already-parsed call, so they are no longer parsed as tables:
 * a documented intentional difference from the pre-linear implementation, matching
 * query_builder/adapters/drizzle.py. Maps case index -> table names that are still produced
 * (written out literally; the golden output had exactly these plus the swallowed ones).
 */
const QUOTE_SHIFTED_DRIZZLE: Record<number, string[]> = {
  6: ["tbl0"],
  9: ["tbl0", "tbl2", "tbl3"],
  10: ["tbl0"],
  54: ["tbl0"],
  60: ["tbl0"],
  95: ["tbl2"],
  104: ["tbl0"],
  147: ["tbl0"],
  152: ["tbl0", "tbl3"],
};

describe("drizzle/prisma golden outputs (recorded from the original regex implementation)", () => {
  const golden = JSON.parse(fs.readFileSync(FIXTURE, "utf8")) as { drizzle: string[]; prisma: string[] };
  const now = digestAll();
  const dEnd = DRIZZLE_FIXED.length + N_STRUCT_D;
  const pEnd = PRISMA_FIXED.length + N_STRUCT_P;

  it("fixture covers the whole corpus", () => {
    expect(golden.drizzle.length).toBe(now.drizzle.length);
    expect(golden.prisma.length).toBe(now.prisma.length);
  });
  it("drizzle: hand written + structured inputs match exactly", () => {
    for (let i = 0; i < dEnd; i++) {
      if (i in QUOTE_SHIFTED_DRIZZLE) continue; // covered by the explicit test below
      expect(now.drizzle[i], `drizzle #${i}`).toBe(golden.drizzle[i]);
    }
  });
  it("drizzle: quote-shifted call spans: later tables inside an already-parsed call span are skipped", () => {
    for (const [key, kept] of Object.entries(QUOTE_SHIFTED_DRIZZLE)) {
      const i = Number(key);
      const original = JSON.parse(golden.drizzle[i]) as { name: string }[];
      const current = JSON.parse(now.drizzle[i]) as { name: string }[];
      expect(current.map((t) => t.name), `drizzle #${i}`).toEqual(kept);
      // New output is exactly the original output minus the swallowed tables: nothing else changed.
      expect(current, `drizzle #${i}`).toEqual(original.filter((t) => kept.includes(t.name)));
      expect(current.length).toBeLessThan(original.length);
    }
  });
  it("drizzle: random token soup matches", () => {
    for (let i = dEnd; i < now.drizzle.length; i++) {
      expect(now.drizzle[i], `drizzle soup #${i}`).toBe(golden.drizzle[i]);
    }
  });
  it("prisma: hand written + structured inputs match exactly", () => {
    for (let i = 0; i < pEnd; i++) expect(now.prisma[i], `prisma #${i}`).toBe(golden.prisma[i]);
  });
  it("prisma: random token soup matches", () => {
    for (let i = pEnd; i < now.prisma.length; i++) {
      expect(now.prisma[i], `prisma soup #${i}`).toBe(golden.prisma[i]);
    }
  });
});

function timed(fn: () => unknown): number {
  const t0 = performance.now();
  fn();
  return performance.now() - t0;
}

describe("linear-time behaviour on CodeQL attack strings (N = 50 000)", () => {
  const drizzleAttacks: [string, string][] = [
    ["enum attack", 'const 0=pgEnum("!",['.repeat(N)],
    ["enum attack with quotes", "const 0=pgEnum(\"!\",[\\'\"".repeat(N)],
    ["enum header no bracket", 'const 0=pgEnum("!",'.repeat(N)],
    ["table head colon + spaces", "const 0:" + " ".repeat(N)],
    ["table head colon + ' x'", "const 0:" + " x".repeat(N)],
    ["table head colon repeated", "const 0:".repeat(N)],
    ["const x: repeated", "const x: ".repeat(N)],
    ["const x = pgTable( repeated", "const x = pgTable(".repeat(N)],
    ["keyword + open paren", "pgTable(".repeat(N)],
    ["keyword + spaces", "pgTable" + " ".repeat(N)],
    ["typed heads, no table", "const a: T = ".repeat(N)],
    ["typed heads then keyword", "const a: T\n".repeat(N) + 'pgTable("t")'],
    ["many equals", "= ".repeat(N) + 'pgTable("t"'],
    ["enum body never closes", 'const e = pgEnum("e", ['.repeat(N / 2) + "a, ".repeat(N)],
  ];
  const prismaAttacks: [string, string][] = [
    ["enum 0{{", "enum 0{{".repeat(N)],
    ["enum 0{{|", "enum 0{{|".repeat(N)],
    ["enum A {", "enum A {".repeat(N)],
    ["enum + spaces", "enum" + " ".repeat(N)],
    ["enum x + spaces", "enum x" + " ".repeat(N)],
    ["enum x repeated", "enum x".repeat(N)],
    ["enum + two spaces repeated", "enum  ".repeat(N)],
  ];

  for (const [name, input] of drizzleAttacks) {
    it(`fromDrizzle: ${name}`, () => {
      expect(timed(() => fromDrizzle(input))).toBeLessThan(BUDGET_MS);
    });
  }
  for (const [name, input] of prismaAttacks) {
    it(`fromPrisma: ${name}`, () => {
      expect(timed(() => fromPrisma(input))).toBeLessThan(BUDGET_MS);
    });
  }
});
