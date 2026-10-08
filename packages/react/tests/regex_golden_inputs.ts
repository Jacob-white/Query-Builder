/**
 * Deterministic input corpora for the golden-snapshot tests in
 * `regex_linear_misc.test.ts`. The expected outputs (recorded from the original,
 * pre-hardening implementations) live in `tests/fixtures/regex_golden_*.json`.
 * Inputs are regenerated from fixed seeds, so only outputs are stored.
 */
import { createHash } from "node:crypto";

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic random concatenations of `tokens` (with random separators). */
export function fuzz(
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

/** Short outputs are stored verbatim, long ones as an md5 digest. */
export function digest(output: string): string {
  return output.length <= 120 ? output : "md5:" + createHash("md5").update(output).digest("hex");
}

export const WS_SEPS = ["", " ", "  ", "\n", "\t", "\u00a0", " \n "];

export const ENGINE_ROWS = [
  { dept: "a", salary: 10, name: "x" },
  { dept: "b", salary: 20, name: "y" },
  { dept: "a", salary: 30, name: "xz" },
  { dept: "c", salary: 5, name: null },
];

function engineTemplated(count: number): string[] {
  const rand = mulberry32(21);
  const pick = <T>(xs: T[]): T => xs[Math.floor(rand() * xs.length)];
  const ws = () => pick([" ", "  ", "\n", "\t", " \n "]);
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
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
    out.push(sql);
  }
  return out;
}

const ENGINE_TOKENS = [
  "SELECT", "select", "*", "dept", "salary", "name", "SUM(salary)", "COUNT(*)", "MAX( salary ) AS m",
  "dept AS d", "FROM emp", "from emp", "WHERE", "salary > 10", "dept = 'a'", "name LIKE 'x%'",
  "salary BETWEEN 5 AND 25", "dept IN ('a','b')", "IS NULL", "GROUP BY", "ORDER BY", "salary DESC",
  "LIMIT 2", "OFFSET 1", "AND", "AS", "x", ",", ";", "(", ")",
];

export const CORPORA = {
  splitOnAnd: [
    "", "1 AND 5", "1  and  5", "a AND b AND c", "a  AND  AND  b", " AND x", "x AND ", "x AND", "ANDx",
    "x\nAND\ty", "x\u00a0AND\u00a0y", "xAND y",
    ...fuzz(["AND", "and", "a", "1", "AN", "D", "x"], 800, 10, 11, WS_SEPS),
  ],
  matchAlias: [
    "a b", "SUM(x) AS total", "SUM(x)  as  total", "x AS", "x AS y", "a AS AS b", "AS b", "a\nb c", "a b\nc",
    "a  \n AS \n b", "single", "", " b", "a ", "a $", "a.b c_d",
    ...fuzz(["AS", "as", "a", "b1", "_", "(", ")", ".", "x", "\n", "-"], 1200, 9, 12, WS_SEPS),
  ],
  matchAggregate: [
    "COUNT(*)", "count( * )", "SUM ( salary )", "AVG(a)(b)", "MIN()", "MAX(   )", "COUNT(", "COUNT", "SUM(a\nb)",
    "SUM(\na\n)", "SUMX(a)", "SUM(a) x", "SUM(a))",
    ...fuzz(["COUNT", "sum", "MAX", "(", ")", "a", "*", "\n"], 1200, 9, 13, WS_SEPS),
  ],
  matchSelectList: [
    "SELECT a FROM t", "select  a ,  b   from t", "SELECT * FROM t WHERE x FROM y", "SELECT FROM t", "SELECT  FROM t",
    "SELECT   FROM t", "SELECT     FROM t", "SELECT FROM t FROM u", "SELECT a FROMx t", "SELECT a\nFROM t",
    "SELECTa FROM t", "SELECT ", "SELECT a", "",
    ...fuzz(["SELECT", "select", "FROM", "from", "a", "*", ",", "FROMx", "_FROM"], 1500, 9, 14, WS_SEPS),
  ],
  semicolons: [
    "", ";", ";;;", "a;", "a; ;", "a ;; \n", "a;b", "a ", "; a;", ";\n;\n", " ;",
    ...fuzz([";", "a", "x"], 500, 10, 15, WS_SEPS),
  ],
  betweenValues: ["5 AND 10", "5  and\n10", "5 AND 10 AND 12", "5AND10", " AND 10", "8 AND 9", "5 AND"],
  engineQueries: [
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
    ...engineTemplated(500),
    ...fuzz(ENGINE_TOKENS, 700, 9, 22, [" ", "  ", "\n", "\t", ""]),
  ],
  sqlalchemy: [
    "class User(Base):\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n    name: Mapped[str] = mapped_column(String(50), nullable=False)\n",
    "class A(Base):\n  __tablename__ = 'a'\n  x : Mapped[int] = mapped_column(Integer)\n  y: = Column(Integer)\n  z :Integer= Column(Integer)\n\n\n\nclass B(Base):\n  __tablename__ = 'b'\n  k = Column(Integer)\n",
    "class A(Base):\n  a: Mapped[int]   =   mapped_column(ForeignKey(\"b.id\"))\n  \n   \n   class C:\n  c = Column(Integer)\n",
    ...fuzz(
      [
        "class", "User", "(Base)", ":", "\n", "  ", "id", "=", "Column(", "Integer", ")", "mapped_column(",
        "Mapped[int]", "__tablename__ = 'users'", ",", "primary_key=True", "ForeignKey('x.id')", " ", "#c",
      ],
      900, 14, 31, ["", " ", "\n", "\n\n", "  "],
    ),
  ],
  drizzle: [
    "export const users = pgTable('users', {\n  id: serial('id').primaryKey(),\n  name: text('name').notNull(),\n});",
    "const t: Foo<Bar> = mysqlTable(\"t\", {\n  a: int(\"a\"),\n  b : varchar ( 'b' , { length: 5 }),\n});",
    "const  x :  Y   =   sqliteTable ( `x` , { id: integer() })",
    "pgTable('bare', { id: serial() })",
    ...fuzz(
      [
        "export ", "const ", "users", " = ", "pgTable(", "mysqlTable(", "sqliteTable (", "'users'", "\"t\"", ", {", "}",
        ")", ";", "\n", "  id: serial('id').primaryKey(),", "name: text(\"n\")", ": Foo<T>", " ", ":", "=", "x:int(", "(",
      ],
      900, 14, 32, ["", " ", "\n"],
    ),
  ],
  prisma: [
    "model User {\n  id Int @id @default(autoincrement())\n  posts Post[]\n  @@map(\"users\")\n}\n",
    "model A { id Int @default({x}) \n b Int }\nmodel B { id Int }",
    "model A { { } { } }\nmodel B { x }",
    "model A {\n id Int\n}\n}\nmodel C { id Int }",
    "model A { {{ } } }",
    "model A { nested { inner } tail }",
    ...fuzz(
      ["model", " ", "User", "A", "{", "}", "id Int @id", "\n", "enum", "Role", "ADMIN", "x String", "@@map(\"t\")", "{ }", "y"],
      1000, 14, 33, ["", " ", "\n"],
    ),
  ],
  names: [
    "", "_", "___", "UserName", "_user_", "__a__b__", "HTTPServer", "a b", " a ", "123", "_1_", "x-y.z", "Ünï", "A_B",
    ...fuzz(["_", "a", "B", "-", " ", ".", "1", "é"], 600, 10, 34),
  ],
  baseUrls: ["", "/", "///", "http://a/b", "http://a/b/", "http://a/b///", "//a//b//", "a/ "],
  safety: [
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
    ...fuzz(
      ["WAITFOR", "waitfor", "DELAY", "delay", "/*", "*/", "/**/", "x", "1", "\n", "'", "DELAYX", "*", "/"],
      1200, 8, 41, ["", " ", "  ", "\n", "\t"],
    ),
  ],
  hookSemicolons: [
    "", ";", "a;;", "a; ;", "a ;\n", "a", "a ;b",
    ...fuzz([";", "a", "x"], 400, 10, 51, WS_SEPS),
  ],
  hookOrderBy: [
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
    ...fuzz(["ORDER", "order", "BY", "by", "a", ")", "(", "x", "ORDERS", "BYE"], 1200, 9, 52, WS_SEPS),
  ],
  vqb: [
    "SELECT  a , b FROM t WHERE x = 'A  b' ;",
    'SELECT "A" FROM `T` WHERE (a=1)  AND ( b ,c )',
    "select [col name] from [t] ;; ",
    "SELECT 'it''s'  ,  x\n=\n1;\n",
    "a ( b ) = ( c ) , d",
    "",
    " ; ",
    ...fuzz(
      ["SELECT", "a", "'x  y'", "'", "(", ")", ",", "=", ";", '"', "`", "[a b]", "[", "]", "FROM", "T"],
      1000, 10, 53, WS_SEPS,
    ),
  ],
};

export async function outcome(fn: () => unknown | Promise<unknown>): Promise<string> {
  try {
    return "OK:" + JSON.stringify(await fn());
  } catch (e) {
    return "ERR:" + (e instanceof Error ? e.message : String(e));
  }
}
