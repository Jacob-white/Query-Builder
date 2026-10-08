/**
 * Regression tests for the ReDoS (polynomial regular expression) hardening of
 * duckdbDriver, the schema adapters, the client, the SQL compiler hook, the visual
 * query builder and the safety validator.
 *
 * 1. Differential tests: the verbatim pre-hardening sources live in
 *    `tests/legacy_regex/` and are compared with the current implementations on
 *    representative tables and on deterministic fuzzed inputs. Private helpers are
 *    loaded straight from the source files and compared with the original regexes.
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

import { InMemoryOlapEngine as LegacyEngine } from "./legacy_regex/duckdbDriver";
import { fromSqlAlchemy as legacyFromSqlAlchemy } from "./legacy_regex/adapters/sqlalchemy";
import { fromDrizzle as legacyFromDrizzle } from "./legacy_regex/adapters/drizzle";
import { fromPrisma as legacyFromPrisma } from "./legacy_regex/adapters/prisma";
import { toSnakeCase as legacyToSnakeCase } from "./legacy_regex/adapters/utils";
import { sanitizeTableName as legacySanitizeTableName } from "./legacy_regex/localDataIngest";
import { validateSqlSafety as legacyValidateSqlSafety } from "./legacy_regex/safety";
import { createQueryBuilderClient as legacyCreateClient } from "./legacy_regex/client";

const N = 50_000;
const BUDGET_MS = 1000;

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic random concatenations of `tokens` (with random separators). */
function fuzz(
  tokens: string[],
  count: number,
  maxTokens: number,
  seed: number,
  seps: string[] = [""],
): string[] {
  const rand = mulberry32(seed);
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const len = Math.floor(rand() * (maxTokens + 1));
    let s = "";
    for (let k = 0; k < len; k++) {
      s += tokens[Math.floor(rand() * tokens.length)];
      s += seps[Math.floor(rand() * seps.length)];
    }
    out.push(s);
  }
  return out;
}

/** Loads private top-level helpers (and `const X = /re/;` lines) out of a source file. */
function loadPrivate<T>(relPath: string, names: string[]): T {
  const src = fs.readFileSync(path.resolve(process.cwd(), relPath), "utf8");
  const parts: string[] = [];
  for (const m of src.matchAll(/^const [A-Za-z_]+ = \/.*\/[a-z]*;$/gm)) parts.push(m[0]);
  for (const m of src.matchAll(/^function \w+[\s\S]*?^}$/gm)) parts.push(m[0]);
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

async function outcome(fn: () => unknown | Promise<unknown>): Promise<string> {
  try {
    return "OK:" + JSON.stringify(await fn());
  } catch (e) {
    return "ERR:" + (e instanceof Error ? e.message : String(e));
  }
}

// ---------------------------------------------------------------------------
// duckdbDriver private helpers vs the original regexes
// ---------------------------------------------------------------------------

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

const WS_SEPS = ["", " ", "  ", "\n", "\t", "\u00a0", " \n "];

describe("duckdbDriver helpers match the original regexes", () => {
  it("splitOnAnd === split(/\\s+AND\\s+/i)", () => {
    const table = [
      "",
      "1 AND 5",
      "1  and  5",
      "a AND b AND c",
      "a  AND  AND  b",
      " AND x",
      "x AND ",
      "x AND",
      "ANDx",
      "x\nAND\ty",
      "x\u00a0AND\u00a0y",
      "xAND y",
    ];
    for (const s of table) expect(duck.splitOnAnd(s)).toEqual(s.split(/\s+AND\s+/i));
    const inputs = fuzz(["AND", "and", "a", "1", "AN", "D", "x"], 4000, 10, 11, WS_SEPS);
    for (const s of inputs) expect(duck.splitOnAnd(s)).toEqual(s.split(/\s+AND\s+/i));
  });

  it("matchAlias === /^(.*?)\\s+(?:AS\\s+)?([a-zA-Z0-9_]+)$/i", () => {
    const re = /^(.*?)\s+(?:AS\s+)?([a-zA-Z0-9_]+)$/i;
    const table = [
      "a b",
      "SUM(x) AS total",
      "SUM(x)  as  total",
      "x AS",
      "x AS y",
      "a AS AS b",
      "AS b",
      "a\nb c",
      "a b\nc",
      "a  \n AS \n b",
      "single",
      "",
      " b",
      "a ",
      "a $",
      "a.b c_d",
    ];
    for (const s of table) {
      const m = re.exec(s);
      expect(duck.matchAlias(s)).toEqual(m ? { expr: m[1], alias: m[2] } : null);
    }
    const inputs = fuzz(["AS", "as", "a", "b1", "_", "(", ")", ".", "x", "\n", "-"], 6000, 9, 12, WS_SEPS);
    for (const s of inputs) {
      const m = re.exec(s);
      expect(duck.matchAlias(s)).toEqual(m ? { expr: m[1], alias: m[2] } : null);
    }
  });

  it("matchAggregate === /^(COUNT|SUM|AVG|MIN|MAX)\\s*\\(\\s*(.*?)\\s*\\)$/i", () => {
    const re = /^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(.*?)\s*\)$/i;
    const table = [
      "COUNT(*)",
      "count( * )",
      "SUM ( salary )",
      "AVG(a)(b)",
      "MIN()",
      "MAX(   )",
      "COUNT(",
      "COUNT",
      "SUM(a\nb)",
      "SUM(\na\n)",
      "SUMX(a)",
      "SUM(a) x",
      "SUM(a))",
    ];
    for (const s of table) {
      const m = re.exec(s);
      expect(duck.matchAggregate(s)).toEqual(m ? { fn: m[1], arg: m[2] } : null);
    }
    const inputs = fuzz(["COUNT", "sum", "MAX", "(", ")", "a", "*", "\n"], 6000, 9, 13, WS_SEPS);
    for (const s of inputs) {
      const m = re.exec(s);
      expect(duck.matchAggregate(s)).toEqual(m ? { fn: m[1], arg: m[2] } : null);
    }
  });

  it("matchSelectList === /^SELECT\\s+([\\s\\S]+?)\\s+\\bFROM\\b/i (incl. quirks)", () => {
    const re = /^SELECT\s+([\s\S]+?)\s+\bFROM\b/i;
    const table = [
      "SELECT a FROM t",
      "select  a ,  b   from t",
      "SELECT * FROM t WHERE x FROM y",
      "SELECT FROM t",
      "SELECT  FROM t",
      "SELECT   FROM t",
      "SELECT     FROM t",
      "SELECT FROM t FROM u",
      "SELECT a FROMx t",
      "SELECT a\nFROM t",
      "SELECTa FROM t",
      "SELECT ",
      "SELECT a",
      "",
    ];
    for (const s of table) {
      const m = re.exec(s);
      const got = duck.matchSelectList(s);
      expect(got === null ? null : got.trim()).toEqual(m ? m[1].trim() : null);
    }
    const inputs = fuzz(["SELECT", "select", "FROM", "from", "a", "*", ",", "FROMx", "_FROM"], 8000, 9, 14, WS_SEPS);
    for (const s of inputs) {
      const m = re.exec(s);
      const got = duck.matchSelectList(s);
      expect(got === null ? null : got.trim()).toEqual(m ? m[1].trim() : null);
    }
  });

  it("stripTrailingSemicolons === replace(/;+\\s*$/, '')", () => {
    const table = ["", ";", ";;;", "a;", "a; ;", "a ;; \n", "a;b", "a ", "; a;", ";\n;\n", " ;"];
    for (const s of table) expect(duck.stripTrailingSemicolons(s)).toBe(s.replace(/;+\s*$/, ""));
    const inputs = fuzz([";", "a", "x"], 3000, 10, 15, WS_SEPS);
    for (const s of inputs) expect(duck.stripTrailingSemicolons(s)).toBe(s.replace(/;+\s*$/, ""));
  });
});

// ---------------------------------------------------------------------------
// InMemoryOlapEngine end to end: legacy vs hardened
// ---------------------------------------------------------------------------

describe("InMemoryOlapEngine matches the legacy implementation", () => {
  const rows = [
    { dept: "a", salary: 10, name: "x" },
    { dept: "b", salary: 20, name: "y" },
    { dept: "a", salary: 30, name: "xz" },
    { dept: "c", salary: 5, name: null },
  ];

  async function engines(): Promise<[InMemoryOlapEngine, LegacyEngine]> {
    const fresh = new InMemoryOlapEngine();
    const legacy = new LegacyEngine();
    await fresh.ingestJson("emp", rows);
    await legacy.ingestJson("emp", rows);
    return [fresh, legacy];
  }

  async function same(fresh: InMemoryOlapEngine, legacy: LegacyEngine, sql: string): Promise<void> {
    const run = (e: { query(q: string): Promise<{ columns: string[]; rows: unknown[] }> }) =>
      outcome(async () => {
        const r = await e.query(sql);
        return { columns: r.columns, rows: r.rows };
      });
    expect(await run(fresh), `query: ${JSON.stringify(sql)}`).toBe(await run(legacy));
  }

  it("agrees on representative queries (recorded original behavior)", async () => {
    const [fresh, legacy] = await engines();
    const queries = [
      "SELECT * FROM emp",
      "select dept, salary from emp where salary > 5 order by salary desc limit 2",
      "SELECT dept, SUM(salary) AS total FROM emp GROUP BY dept ORDER BY total DESC;",
      "SELECT COUNT(*) AS n FROM emp;;  ",
      "SELECT AVG( salary ) avg_sal FROM emp",
      "SELECT MAX(salary) AS m, MIN(salary) lo FROM emp",
      "SELECT name AS n, dept d FROM emp WHERE dept IN ('a','b')",
      "SELECT * FROM emp WHERE name LIKE 'x%' AND salary BETWEEN 5 AND 25",
      "SELECT * FROM emp WHERE dept NOT IN ('a')",
      "SELECT * FROM emp WHERE name IS NULL",
      "SELECT * FROM emp WHERE name IS NOT NULL",
      "SELECT * FROM emp WHERE  ",
      "SELECT * FROM emp WHERE",
      "SELECT * FROM emp GROUP BY   ",
      "SELECT dept FROM emp GROUP BY  ",
      "SELECT * FROM emp ORDER BY  ",
      "SELECT * FROM emp ORDER BY salary  OFFSET 1",
      "SELECT   FROM emp",
      "SELECT  FROM emp",
      "SHOW TABLES",
      "SELECT 1",
      "SELECT * FROM emp WHERE salary>10",
      "SELECT * FROM emp WHERE emp.salary >= 10 AND dept = 'a'",
      "SELECT * FROM emp WHERE x_IN IN (1)",
      "SELECT * FROM emp WHERE a.IN IN (1)",
      "SELECT * FROM emp WHERE NOT IN (1)",
      "SELECT sum( salary ) , count(*) FROM emp",
      "SELECT SUM(salary\n) AS s FROM emp",
    ];
    for (const sql of queries) await same(fresh, legacy, sql);
  });

  it("agrees on templated queries", async () => {
    const [fresh, legacy] = await engines();
    const rand = mulberry32(21);
    const pick = <T>(xs: T[]): T => xs[Math.floor(rand() * xs.length)];
    const ws = () => pick([" ", "  ", "\n", "\t", " \n "]);
    for (let i = 0; i < 1500; i++) {
      const sel = pick(["*", "dept", "name, salary", "SUM(salary) AS s", "dept, COUNT(*) AS n", "AVG( salary )  a", "salary  AS  pay", ""]);
      const where = pick(["", "salary > 5", "dept = 'a'", "name LIKE 'x%'", "salary BETWEEN 5 AND 25", "dept IN ('a','b') AND salary < 30", "name IS NULL", " ", "x"]);
      const group = pick(["", "dept", " dept ", " "]);
      const order = pick(["", "salary", "salary DESC", "dept , salary", " "]);
      const tail = pick(["", "LIMIT 2", "OFFSET 1", "LIMIT 3 OFFSET 1", ";", ";  ;", " ; "]);
      let sql = `SELECT${ws()}${sel}${ws()}FROM${ws()}emp`;
      if (where !== "x" || rand() < 0.5) sql += `${ws()}WHERE${ws()}${where}`;
      if (group) sql += `${ws()}GROUP${ws()}BY${ws()}${group}`;
      if (order) sql += `${ws()}ORDER${ws()}BY${ws()}${order}`;
      if (tail) sql += `${ws()}${tail}`;
      await same(fresh, legacy, sql);
    }
  });

  it("agrees on fuzzed token soup", async () => {
    const [fresh, legacy] = await engines();
    const tokens = [
      "SELECT", "select", "*", "dept", "salary", "name", "SUM(salary)", "COUNT(*)", "MAX( salary ) AS m",
      "dept AS d", "FROM emp", "from emp", "WHERE", "salary > 10", "dept = 'a'", "name LIKE 'x%'",
      "salary BETWEEN 5 AND 25", "dept IN ('a','b')", "IS NULL", "GROUP BY", "ORDER BY", "salary DESC",
      "LIMIT 2", "OFFSET 1", "AND", "AS", "x", ",", ";", "(", ")",
    ];
    for (const sql of fuzz(tokens, 3500, 9, 22, [" ", "  ", "\n", "\t", ""])) {
      await same(fresh, legacy, sql);
    }
  });
});

describe("evaluateCondition BETWEEN keeps its behavior", () => {
  it("splits on whitespace-delimited AND exactly like before", () => {
    const row = { v: 7 };
    const vals = ["5 AND 10", "5  and\n10", "5 AND 10 AND 12", "5AND10", " AND 10", "8 AND 9", "5 AND"];
    for (const v of vals) {
      const legacyParts = v.split(/\s+AND\s+/i);
      const expected = legacyParts.length === 2 ? 7 >= Number(legacyParts[0]) && 7 <= Number(legacyParts[1]) : true;
      expect(evaluateCondition(row, "v", "BETWEEN", v)).toBe(expected);
    }
  });
});

// ---------------------------------------------------------------------------
// adapters
// ---------------------------------------------------------------------------

describe("adapters match the legacy implementations", () => {
  it("fromSqlAlchemy on python sources", async () => {
    const table = [
      "class User(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n    name: Mapped[str] = mapped_column(String(50), nullable=False)\n",
      "class A(Base):\n  __tablename__ = 'a'\n  x : Mapped[int] = mapped_column(Integer)\n  y: = Column(Integer)\n  z :Integer= Column(Integer)\n\n\n\nclass B(Base):\n  __tablename__ = 'b'\n  k = Column(Integer)\n",
      "class A(Base):\n  a: Mapped[int]   =   mapped_column(ForeignKey(\"b.id\"))\n  \n   \n   class C:\n  c = Column(Integer)\n",
    ];
    for (const src of table) {
      expect(await outcome(() => fromSqlAlchemy(src))).toBe(await outcome(() => legacyFromSqlAlchemy(src)));
    }
    const tokens = [
      "class", "User", "(Base)", ":", "\n", "  ", "id", "=", "Column(", "Integer", ")", "mapped_column(",
      "Mapped[int]", "__tablename__ = 'users'", ",", "primary_key=True", "ForeignKey('x.id')", " ", "#c",
    ];
    for (const src of fuzz(tokens, 2500, 14, 31, ["", " ", "\n", "\n\n", "  "])) {
      expect(await outcome(() => fromSqlAlchemy(src)), JSON.stringify(src)).toBe(
        await outcome(() => legacyFromSqlAlchemy(src)),
      );
    }
  });

  it("fromDrizzle on typescript sources", async () => {
    const table = [
      "export const users = pgTable('users', {\n  id: serial('id').primaryKey(),\n  name: text('name').notNull(),\n});",
      "const t: Foo<Bar> = mysqlTable(\"t\", {\n  a: int(\"a\"),\n  b : varchar ( 'b' , { length: 5 }),\n});",
      "const  x :  Y   =   sqliteTable ( `x` , { id: integer() })",
      "pgTable('bare', { id: serial() })",
    ];
    for (const src of table) {
      expect(await outcome(() => fromDrizzle(src))).toBe(await outcome(() => legacyFromDrizzle(src)));
    }
    const tokens = [
      "export ", "const ", "users", " = ", "pgTable(", "mysqlTable(", "sqliteTable (", "'users'", "\"t\"", ", {", "}",
      ")", ";", "\n", "  id: serial('id').primaryKey(),", "name: text(\"n\")", ": Foo<T>", " ", ":", "=", "x:int(", "(",
    ];
    for (const src of fuzz(tokens, 2500, 14, 32, ["", " ", "\n"])) {
      expect(await outcome(() => fromDrizzle(src)), JSON.stringify(src)).toBe(
        await outcome(() => legacyFromDrizzle(src)),
      );
    }
  });

  it("fromPrisma on schema sources", async () => {
    const table = [
      "model User {\n  id Int @id @default(autoincrement())\n  posts Post[]\n  @@map(\"users\")\n}\n",
      "model A { id Int @default({x}) \n b Int }\nmodel B { id Int }",
      "model A { { } { } }\nmodel B { x }",
      "model A {\n id Int\n}\n}\nmodel C { id Int }",
      "model A { {{ } } }",
      "model A { nested { inner } tail }",
    ];
    for (const src of table) {
      expect(await outcome(() => fromPrisma(src))).toBe(await outcome(() => legacyFromPrisma(src)));
    }
    const tokens = [
      "model", " ", "User", "A", "{", "}", "id Int @id", "\n", "enum", "Role", "ADMIN", "x String", "@@map(\"t\")", "{ }", "y",
    ];
    for (const src of fuzz(tokens, 3500, 14, 33, ["", " ", "\n"])) {
      expect(await outcome(() => fromPrisma(src)), JSON.stringify(src)).toBe(
        await outcome(() => legacyFromPrisma(src)),
      );
    }
  });

  it("toSnakeCase and sanitizeTableName", () => {
    const names = ["", "_", "___", "UserName", "_user_", "__a__b__", "HTTPServer", "a b", " a ", "123", "_1_", "x-y.z", "Ünï", "A_B"];
    for (const n of names) {
      expect(toSnakeCase(n)).toBe(legacyToSnakeCase(n));
      expect(sanitizeTableName(n)).toBe(legacySanitizeTableName(n));
      expect(sanitizeTableName(n + ".csv")).toBe(legacySanitizeTableName(n + ".csv"));
    }
    for (const n of fuzz(["_", "a", "B", "-", " ", ".", "1", "é"], 3000, 10, 34)) {
      expect(toSnakeCase(n)).toBe(legacyToSnakeCase(n));
      expect(sanitizeTableName(n)).toBe(legacySanitizeTableName(n));
    }
  });
});

// ---------------------------------------------------------------------------
// client baseUrl
// ---------------------------------------------------------------------------

describe("createQueryBuilderClient baseUrl normalization", () => {
  async function requestedUrl(make: typeof createQueryBuilderClient, baseUrl: string): Promise<string> {
    const fetchFn = vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: "x" });
    const client = make({ baseUrl, fetchFn: fetchFn as unknown as typeof fetch });
    await client.request("/p").catch(() => undefined);
    return String(fetchFn.mock.calls[0][0]);
  }

  it("strips trailing slashes exactly like before", async () => {
    for (const base of ["", "/", "///", "http://a/b", "http://a/b/", "http://a/b///", "//a//b//", "a/ "]) {
      expect(await requestedUrl(createQueryBuilderClient, base)).toBe(await requestedUrl(legacyCreateClient, base));
    }
  });
});

// ---------------------------------------------------------------------------
// safety validator (WAITFOR DELAY)
// ---------------------------------------------------------------------------

describe("validateSqlSafety WAITFOR DELAY detection", () => {
  it("matches the legacy detector on representative inputs", () => {
    const sqls = [
      "SELECT 1; WAITFOR DELAY '0:0:5'",
      "WAITFOR   DELAY '0:0:5'",
      "waitfor/**/delay '0:0:1'",
      "WAITFOR /* a */ /* b */ DELAY '0:0:1'",
      "WAITFOR /* a */ b */ DELAY '0:0:1'",
      "WAITFOR /*/ DELAY",
      "WAITFOR /**/DELAYED",
      "WAITFOR\n/* multi\nline */ DELAY x",
      "WAITFOR /* a\n*/ DELAY x",
      "WAITFOR TIME '10:00'",
      "WAITFOR",
      "xWAITFOR DELAY 1",
      "SELECT 1",
    ];
    for (const sql of sqls) {
      expect(validateSqlSafety(sql), sql).toEqual(legacyValidateSqlSafety(sql));
    }
    const tokens = ["WAITFOR", "waitfor", "DELAY", "delay", "/*", "*/", "/**/", "x", "1", "\n", "'", "DELAYX", "*", "/"];
    for (const sql of fuzz(tokens, 4000, 8, 41, ["", " ", "  ", "\n", "\t"])) {
      expect(validateSqlSafety(sql), JSON.stringify(sql)).toEqual(legacyValidateSqlSafety(sql));
    }
  });
});

// ---------------------------------------------------------------------------
// hook / component private helpers
// ---------------------------------------------------------------------------

describe("useSqlCompiler count query helpers", () => {
  interface HookHelpers {
    stripTrailingSemicolons(s: string): string;
    stripTrailingOrderBy(s: string): string;
  }
  const hook = loadPrivate<HookHelpers>("src/hooks/useSqlCompiler.ts", [
    "stripTrailingSemicolons",
    "stripTrailingOrderBy",
  ]);

  it("stripTrailingSemicolons === replace(/;+\\s*$/, '')", () => {
    for (const s of ["", ";", "a;;", "a; ;", "a ;\n", "a", "a ;b"]) {
      expect(hook.stripTrailingSemicolons(s)).toBe(s.replace(/;+\s*$/, ""));
    }
    for (const s of fuzz([";", "a", "x"], 2000, 10, 51, WS_SEPS)) {
      expect(hook.stripTrailingSemicolons(s)).toBe(s.replace(/;+\s*$/, ""));
    }
  });

  it("stripTrailingOrderBy === replace(/\\s+ORDER\\s+BY\\s+[^)]+$/i, '')", () => {
    const re = /\s+ORDER\s+BY\s+[^)]+$/i;
    const table = [
      "SELECT * FROM t ORDER BY a",
      "SELECT * FROM t  order  by  a desc, b",
      "SELECT * FROM (SELECT * FROM t ORDER BY a) x",
      "SELECT * FROM (SELECT * FROM t ORDER BY a) x ORDER BY b",
      "SELECT * FROM t ORDER BY a ORDER BY b",
      "SELECT * FROM t ORDER BY ",
      "SELECT * FROM t ORDER BY  ",
      "SELECT * FROM t ORDER BYa",
      "SELECT * FROM t\nORDER\nBY\nx",
      "ORDER BY x",
      " ORDER BY x",
      "x ORDERBY y",
    ];
    for (const s of table) expect(hook.stripTrailingOrderBy(s)).toBe(s.replace(re, ""));
    const tokens = ["ORDER", "order", "BY", "by", "a", ")", "(", "x", "ORDERS", "BYE"];
    for (const s of fuzz(tokens, 6000, 9, 52, WS_SEPS)) {
      expect(hook.stripTrailingOrderBy(s), JSON.stringify(s)).toBe(s.replace(re, ""));
    }
  });
});

describe("VisualQueryBuilder normalizeSqlForCompare", () => {
  interface VqbHelpers {
    normalizeSqlForCompare(s: string): string;
  }
  const vqb = loadPrivate<VqbHelpers>("src/components/VisualQueryBuilder.tsx", [
    "normalizeSqlForCompare",
    "stripTrailingSemicolons",
  ]);

  function legacyNormalize(sql: string): string {
    return sql
      .split(/('(?:[^']|'')*')/)
      .map((seg, i) =>
        i % 2 === 1
          ? seg
          : seg
              .replace(/["`]/g, "")
              .replace(/\[([A-Za-z_][\w ]*)\]/g, "$1")
              .replace(/\s+/g, " ")
              .replace(/\s*([(),=])\s*/g, "$1")
              .toLowerCase(),
      )
      .join("")
      .replace(/;+\s*$/, "")
      .trim();
  }

  it("is unchanged by the rewrite", () => {
    const table = [
      "SELECT  a , b FROM t WHERE x = 'A  b' ;",
      'SELECT "A" FROM `T` WHERE (a=1)  AND ( b ,c )',
      "select [col name] from [t] ;; ",
      "SELECT 'it''s'  ,  x\n=\n1;\n",
      "a ( b ) = ( c ) , d",
      "",
      " ; ",
    ];
    for (const s of table) expect(vqb.normalizeSqlForCompare(s)).toBe(legacyNormalize(s));
    const tokens = ["SELECT", "a", "'x  y'", "'", "(", ")", ",", "=", ";", '"', "`", "[a b]", "[", "]", "FROM", "T"];
    for (const s of fuzz(tokens, 5000, 10, 53, WS_SEPS)) {
      expect(vqb.normalizeSqlForCompare(s), JSON.stringify(s)).toBe(legacyNormalize(s));
    }
  });
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
