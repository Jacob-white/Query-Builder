import { describe, it, expect } from "vitest";
import { parseSqlToSpec, cleanIdentifier } from "../src/utils/sqlParser";
import { invalid } from "./helpers";

describe("sqlParser", () => {
  it("cleans quoted, bracketed, backticked, and dotted identifiers", () => {
    expect(cleanIdentifier('"users"')).toBe("users");
    expect(cleanIdentifier("`orders`")).toBe("orders");
    expect(cleanIdentifier("[id]")).toBe("id");
    expect(cleanIdentifier('"users"."id"')).toBe("users.id");
    expect(cleanIdentifier("`users`.`id`")).toBe("users.id");
    expect(cleanIdentifier("")).toBe("");
  });

  it("returns null for empty or non-string inputs", () => {
    expect(parseSqlToSpec("")).toBeNull();
    expect(parseSqlToSpec(invalid<string>(null))).toBeNull();
    expect(parseSqlToSpec(invalid<string>(undefined))).toBeNull();
    expect(parseSqlToSpec("   ")).toBeNull();
  });

  it("returns null for non-SELECT or disallowed statements", () => {
    expect(parseSqlToSpec("INSERT INTO users VALUES (1);")).toBeNull();
    expect(parseSqlToSpec("UPDATE users SET name = 'test';")).toBeNull();
    expect(parseSqlToSpec("DELETE FROM users WHERE id = 1;")).toBeNull();
    expect(parseSqlToSpec("DROP TABLE users;")).toBeNull();
    expect(parseSqlToSpec("ALTER TABLE users ADD col int;")).toBeNull();
    expect(parseSqlToSpec("SELECT 1 FROM users UNION SELECT 2 FROM orders;")).toBeNull();
    expect(parseSqlToSpec("NOT A SQL QUERY")).toBeNull();
  });

  it("parses basic SELECT * FROM table", () => {
    const spec = parseSqlToSpec("SELECT * FROM users;");
    expect(spec).not.toBeNull();
    expect(spec?.table).toBe("users");
    expect(spec?.columns).toEqual(["*"]);
    expect(spec?.distinct).toBe(false);
    expect(spec?.limit).toBe(50);
  });

  it("parses SELECT DISTINCT with column lists and aliases", () => {
    const sql = `
      SELECT DISTINCT users.id AS user_id, email, COUNT(orders.id) AS order_cnt
      FROM users;
    `;
    const spec = parseSqlToSpec(sql);
    expect(spec).not.toBeNull();
    expect(spec?.table).toBe("users");
    expect(spec?.distinct).toBe(true);
    expect(spec?.columns).toHaveLength(3);
    expect(spec?.columns[0]).toEqual({ column: "users.id", alias: "user_id" });
    expect(spec?.columns[1]).toBe("email");
    expect(spec?.columns[2]).toEqual({
      column: "orders.id",
      agg: "COUNT",
      alias: "order_cnt",
    });
  });

  it("strips single-line and multi-line comments", () => {
    const sql = `
      -- Header comment
      SELECT id, name /* inline comment */
      FROM users -- trailing comment
      WHERE id = 5;
    `;
    const spec = parseSqlToSpec(sql);
    expect(spec).not.toBeNull();
    expect(spec?.table).toBe("users");
    expect(spec?.columns).toEqual(["id", "name"]);
    expect(spec?.filters).toHaveLength(1);
    expect(spec?.filters[0].value).toBe(5);
  });

  it("parses JOINs with ON conditions", () => {
    const sql = `
      SELECT u.id, o.amount
      FROM users
      LEFT JOIN orders ON users.id = orders.user_id
      INNER JOIN accounts ON accounts.user_id = users.id;
    `;
    const spec = parseSqlToSpec(sql);
    expect(spec).not.toBeNull();
    expect(spec?.joins).toHaveLength(2);
    expect(spec?.joins[0].table).toBe("orders");
    expect(spec?.joins[0].type).toBe("LEFT JOIN");
    expect(spec?.joins[0].left_table).toBe("users");
    expect(spec?.joins[0].left_col).toBe("id");
    expect(spec?.joins[0].right_col).toBe("user_id");

    expect(spec?.joins[1].table).toBe("accounts");
    expect(spec?.joins[1].type).toBe("INNER JOIN");
    expect(spec?.joins[1].left_table).toBe("users");
    expect(spec?.joins[1].left_col).toBe("id");
    expect(spec?.joins[1].right_col).toBe("user_id");
  });

  it("parses WHERE predicates with various operators and combiners", () => {
    const sql = `
      SELECT id FROM users
      WHERE status = 'active'
        AND age >= 21
        AND deleted IS NULL
        OR is_admin = true
        AND role IN (admin, superuser)
        AND score BETWEEN 10 AND 50;
    `;
    const spec = parseSqlToSpec(sql);
    expect(spec).not.toBeNull();
    expect(spec?.filters).toHaveLength(6);
    expect(spec?.filter_join).toBe("OR");

    expect(spec?.filters[0]).toMatchObject({
      column: "status",
      op: "=",
      value: "active",
    });
    expect(spec?.filters[1]).toMatchObject({
      column: "age",
      op: ">=",
      value: 21,
    });
    expect(spec?.filters[2]).toMatchObject({
      column: "deleted",
      op: "IS NULL",
      value: "",
    });
    expect(spec?.filters[3]).toMatchObject({
      column: "is_admin",
      op: "=",
      value: true,
    });
    expect(spec?.filters[4]).toMatchObject({
      column: "role",
      op: "IN",
      value: "admin, superuser",
    });
    expect(spec?.filters[5]).toMatchObject({
      column: "score",
      op: "BETWEEN",
      value: "10 AND 50",
    });
  });

  it("parses ORDER BY, LIMIT, and OFFSET", () => {
    const sql = `
      SELECT id FROM users
      ORDER BY users.created_at DESC, id ASC
      LIMIT 100 OFFSET 20;
    `;
    const spec = parseSqlToSpec(sql);
    expect(spec).not.toBeNull();
    expect(spec?.order_by).toHaveLength(2);
    expect(spec?.order_by[0]).toMatchObject({
      column: "created_at",
      direction: "DESC",
      tablePrefix: "users",
    });
    expect(spec?.order_by[1]).toMatchObject({
      column: "id",
      direction: "ASC",
    });
    expect(spec?.limit).toBe(100);
  });

  it("parses strings with commas/escaped quotes and additional edge cases", () => {
    const sql = `
      SELECT id, 'hello''world, foo' AS str, * FROM users
      JOIN orders ON user_id = id
      WHERE name = 'O''Connor' AND users.age > 21;
    `;
    const spec = parseSqlToSpec(sql);
    expect(spec).not.toBeNull();
    expect(spec?.columns).toContain("*");
    expect(spec?.joins[0]).toMatchObject({
      left_col: "user_id",
      right_col: "id",
    });
    expect(spec?.filters).toHaveLength(2);
    expect(spec?.filters[0].value).toBe("O''Connor");
    expect(spec?.filters[1]).toMatchObject({
      tablePrefix: "users",
      column: "age",
      op: ">",
      value: 21,
    });

    expect(parseSqlToSpec("SELECT+1")).toBeNull();
    expect(parseSqlToSpec("SELECT 1;")).toBeNull();

    const specUnquoted = parseSqlToSpec("SELECT * FROM users WHERE status = pending;");
    expect(specUnquoted?.filters?.[0].value).toBe("pending");

    const specNotEqual = parseSqlToSpec("SELECT * FROM users WHERE status <> 'inactive';");
    expect(specNotEqual?.filters?.[0].op).toBe("!=");
  });

  describe("uncovered branch test cases", () => {
    it("parses double-quoted string literals in WHERE clauses", () => {
      const spec = parseSqlToSpec('SELECT * FROM users WHERE status = "active";');
      expect(spec).not.toBeNull();
      expect(spec?.filters).toHaveLength(1);
      expect(spec?.filters?.[0]).toMatchObject({
        column: "status",
        op: "=",
        value: "active",
      });
    });

    it("parses boolean false literals in WHERE clauses", () => {
      const spec = parseSqlToSpec("SELECT * FROM users WHERE is_active = false;");
      expect(spec).not.toBeNull();
      expect(spec?.filters).toHaveLength(1);
      expect(spec?.filters?.[0]).toMatchObject({
        column: "is_active",
        op: "=",
        value: false,
      });
    });

    it("parses SQL queries ending exactly at a keyword boundary", () => {
      const spec = parseSqlToSpec("SELECT * FROM users WHERE");
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("users");
      expect(spec?.filters).toEqual([]);
    });

    it("returns null when FROM table identifier cleans to empty string", () => {
      expect(parseSqlToSpec('SELECT * FROM "";')).toBeNull();
      expect(parseSqlToSpec("SELECT * FROM '';")).toBeNull();
    });

    it("handles queries without SELECT projection content by defaulting columns to wildcard", () => {
      const spec = parseSqlToSpec("SELECT FROM users;");
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("users");
      expect(spec?.columns).toEqual(["*"]);

      const spec2 = parseSqlToSpec("SELECT* FROM users;");
      expect(spec2).not.toBeNull();
      expect(spec2?.table).toBe("users");
      expect(spec2?.columns).toEqual(["*"]);
    });

    it("skips empty items caused by double commas in SELECT projection list", () => {
      const spec = parseSqlToSpec("SELECT id, , email FROM users;");
      expect(spec).not.toBeNull();
      expect(spec?.columns).toEqual(["id", "email"]);
    });

    it("parses aggregate functions without AS alias clause", () => {
      const spec = parseSqlToSpec("SELECT COUNT(id) FROM users;");
      expect(spec).not.toBeNull();
      expect(spec?.columns[0]).toEqual({
        column: "id",
        agg: "COUNT",
        alias: undefined,
      });
    });

    it("skips joins lacking ON condition", () => {
      const spec = parseSqlToSpec("SELECT * FROM users CROSS JOIN orders;");
      expect(spec).not.toBeNull();
      expect(spec?.joins).toEqual([]);
    });

    it("parses WITH and WITH RECURSIVE CTE clauses", () => {
      const sql = `
        WITH RECURSIVE subordinates AS (
          SELECT id, manager_id FROM employees WHERE id = 1
        ),
        summary (dept, total) AS MATERIALIZED (
          SELECT dept, SUM(salary) FROM employees GROUP BY dept
        )
        SELECT * FROM subordinates;
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("subordinates");
      expect(spec?.ctes).toHaveLength(2);
      expect(spec?.ctes?.[0].name).toBe("subordinates");
      expect(spec?.ctes?.[0].recursive).toBe(true);
      expect(spec?.ctes?.[1].name).toBe("summary");
      expect(spec?.ctes?.[1].columns).toEqual(["dept", "total"]);
      expect(spec?.ctes?.[1].materialized).toBe(true);
    });

    it("parses window functions with PARTITION BY and ORDER BY", () => {
      const sql = `
        SELECT
          id,
          ROW_NUMBER() OVER (PARTITION BY dept_id ORDER BY hire_date DESC) AS rank_in_dept
        FROM employees;
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.window_functions).toHaveLength(1);
      expect(spec?.window_functions?.[0].function).toBe("ROW_NUMBER");
      expect(spec?.window_functions?.[0].partition_by).toEqual(["dept_id"]);
      expect(spec?.window_functions?.[0].order_by).toEqual([{ column: "hire_date", direction: "DESC" }]);
      expect(spec?.window_functions?.[0].alias).toBe("rank_in_dept");
    });

    it("parses temporal time grains (DATE_TRUNC, DATETRUNC)", () => {
      const sql = `
        SELECT
          DATE_TRUNC('month', created_at) AS signup_month,
          DATETRUNC(day, last_login) AS login_day
        FROM users;
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.columns[0]).toEqual({
        column: "created_at",
        time_grain: "month",
        alias: "signup_month",
      });
      expect(spec?.columns[1]).toEqual({
        column: "last_login",
        time_grain: "day",
        alias: "login_day",
      });
    });

    it("parses filtered aggregates and raw CASE expressions with graceful degradation", () => {
      const sql = `
        SELECT
          SUM(amount) FILTER (WHERE status = 'paid') AS paid_revenue,
          CASE WHEN age >= 18 THEN 'Adult' ELSE 'Minor' END AS age_group
        FROM customers
        WHERE EXISTS (SELECT 1 FROM orders WHERE orders.customer_id = customers.id);
      `;
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.columns[0]).toEqual({
        column: "amount",
        agg: "SUM",
        metric: "paid_revenue",
        alias: "paid_revenue",
      });
      expect((spec?.columns[1] as { raw_expression?: string }).raw_expression).toBe("CASE WHEN age >= 18 THEN 'Adult' ELSE 'Minor' END");
      expect(spec?.filters).toHaveLength(1);
      expect(spec?.filters?.[0].op).toBe("RAW");
      expect(spec?.filters?.[0].column).toContain("EXISTS");
    });

    it("parses OFFSET clause alongside LIMIT", () => {
      const sql = "SELECT * FROM items LIMIT 20 OFFSET 40;";
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.limit).toBe(20);
      expect(spec?.offset).toBe(40);
    });

    it("parses raw expressions without an AS alias clause", () => {
      const sql = "SELECT CASE WHEN age > 10 THEN 'kid' ELSE 'baby' END FROM users;";
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect((spec?.columns[0] as { raw_expression?: string }).raw_expression).toBe("CASE WHEN age > 10 THEN 'kid' ELSE 'baby' END");
    });

    it("returns null if CTE has no main SELECT or post-CTE statement is not a SELECT", () => {
      expect(parseSqlToSpec("WITH cte AS (SELECT 1)")).toBeNull();
      expect(parseSqlToSpec("WITH cte AS (SELECT 1) VALUES (1, 2);")).toBeNull();
    });

    it("handles unstructured CTE definitions gracefully", () => {
      const sql = "WITH cte_plain AS NOT_A_PAREN SELECT * FROM cte_plain;";
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.ctes?.[0].name).toBe("cte_plain");
    });

    it("parses CTE definitions containing strings with escaped quotes", () => {
      const sql = "WITH cte AS (SELECT 'hel''lo' AS str) SELECT * FROM cte;";
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.ctes?.[0].name).toBe("cte");
    });

    it("handles conditions with unmatched parentheses or bare columns", () => {
      const sql = "SELECT * FROM users WHERE ) OR just_col;";
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.filters).toHaveLength(2);
      expect(spec?.filters?.[0].op).toBe("RAW");
      expect(spec?.filters?.[1].op).toBe("RAW");
    });

    it("parses conditions where string literal or escaped string precedes operator", () => {
      const sql = "SELECT * FROM users WHERE 'a''b' = col AND (flag) = true;";
      const spec = parseSqlToSpec(sql);
      expect(spec).not.toBeNull();
      expect(spec?.filters).toHaveLength(2);
    });
  });
});
