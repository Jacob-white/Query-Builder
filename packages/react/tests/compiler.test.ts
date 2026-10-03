import { describe, it, expect } from "vitest";
import {
  compileVisualState,
  formatIlike,
  formatLimit,
  quoteAlias,
  quoteIdent,
} from "../src/utils/compiler";
import type { SchemaSnapshot } from "../src/types";

describe("compileVisualState", () => {
  const mockSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "email", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
        ],
      },
    },
    foreign_keys: [],
  };

  it("compiles empty query when no table selected", () => {
    const res = compileVisualState("", {}, [], [], [], []);
    expect(res.sql).toBe("");
  });

  it("compiles basic SELECT query with selected columns", () => {
    const res = compileVisualState(
      "users",
      {
        "users.id": { table: "users", name: "id" },
        "users.email": { table: "users", name: "email" },
      },
      ["users.id", "users.email"],
      [],
      [],
      [],
      false,
      50,
    );

    expect(res.sql).toContain('SELECT "users"."id", "users"."email"');
    expect(res.sql).toContain('FROM "users"');
    expect(res.sql).toContain("LIMIT 50;");
    expect(res.spec.columns).toHaveLength(2);
  });

  it("falls back to wildcard when no columns explicitly selected", () => {
    const res = compileVisualState(
      "users",
      {},
      [],
      [],
      [],
      [],
      false,
      25,
      mockSchema,
    );
    expect(res.sql).toContain("SELECT *");
    expect(res.spec.columns).toEqual(["*"]);
  });

  it("compiles DISTINCT modifier when requested", () => {
    const res = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [],
      [],
      true,
      10,
    );
    expect(res.sql).toContain('SELECT DISTINCT "users"."id"');
  });

  it("compiles joins, filters, and sorts", () => {
    const res = compileVisualState(
      "users",
      {
        "users.name": { table: "users", name: "name" },
        "orders.amount": { table: "orders", name: "amount" },
      },
      ["users.name", "orders.amount"],
      [
        {
          id: "j1",
          type: "LEFT JOIN",
          left_table: "users",
          left_col: "id",
          table: "orders",
          right_col: "user_id",
        },
      ],
      [
        {
          id: "f1",
          column: "status",
          operator: "=",
          value: "ACTIVE",
          tablePrefix: "users",
        },
      ],
      [
        {
          id: "s1",
          column: "name",
          tablePrefix: "users",
          direction: "ASC",
        },
      ],
    );

    expect(res.sql).toContain('LEFT JOIN "orders" ON "users"."id" = "orders"."user_id"');
    expect(res.sql).toContain('WHERE "users"."status" = \'ACTIVE\'');
    expect(res.sql).toContain('ORDER BY "users"."name" ASC');
  });

  it("compiles filter operators: IS NULL, IS NOT NULL, STARTS_WITH, ENDS_WITH, CONTAINS, LIKE, ILIKE", () => {
    const res = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [
        { id: "f1", tablePrefix: "users", column: "email", operator: "IS NULL", value: "" },
        { id: "f2", tablePrefix: "users", column: "email", operator: "IS NOT NULL", value: "" },
        { id: "f3", tablePrefix: "users", column: "name", operator: "STARTS_WITH", value: "J" },
        { id: "f4", tablePrefix: "users", column: "name", operator: "ENDS_WITH", value: "e" },
        { id: "f5", tablePrefix: "users", column: "name", operator: "CONTAINS", value: "ac" },
        { id: "f6", tablePrefix: "users", column: "name", operator: "LIKE", value: "%foo%" },
        { id: "f7", tablePrefix: "users", column: "name", operator: "ILIKE", value: "%bar%" },
        { id: "f8", tablePrefix: "users", column: "age", operator: ">", value: "25" },
      ],
      [],
    );

    expect(res.sql).toContain('"users"."email" IS NULL');
    expect(res.sql).toContain('"users"."email" IS NOT NULL');
    expect(res.sql).toContain('"users"."name" ILIKE \'J%\'');
    expect(res.sql).toContain('"users"."name" ILIKE \'%e\'');
    expect(res.sql).toContain('"users"."name" ILIKE \'%ac%\'');
    expect(res.sql).toContain('"users"."name" LIKE \'%foo%\'');
    expect(res.sql).toContain('"users"."name" ILIKE \'%bar%\'');
    expect(res.sql).toContain('"users"."age" > 25');
  });

  it("compiles IN and NOT IN filter operators with numbers and strings", () => {
    const res = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [
        { id: "f1", tablePrefix: "users", column: "id", operator: "IN", value: "1, 2, 3" },
        { id: "f2", tablePrefix: "users", column: "role", operator: "NOT IN", value: "admin, guest" },
      ],
      [],
    );

    expect(res.sql).toContain('"users"."id" IN (1, 2, 3)');
    expect(res.sql).toContain('"users"."role" NOT IN (\'admin\', \'guest\')');
  });

  it("compiles BETWEEN filter operator with AND and comma delimiters", () => {
    const resAnd = compileVisualState(
      "orders",
      { "orders.id": { table: "orders", name: "id" } },
      ["orders.id"],
      [],
      [
        { id: "f1", tablePrefix: "orders", column: "amount", operator: "BETWEEN", value: "10 AND 50" },
        { id: "f2", tablePrefix: "orders", column: "created_at", operator: "BETWEEN", value: "2020-01-01, 2020-12-31" },
      ],
      [],
    );

    expect(resAnd.sql).toContain('"orders"."amount" BETWEEN 10 AND 50');
    expect(resAnd.sql).toContain('"orders"."created_at" BETWEEN \'2020-01-01\' AND \'2020-12-31\'');
  });

  it("compiles aggregate functions and derives GROUP BY for mixed projections", () => {
    const res = compileVisualState(
      "users",
      {
        "users.role": { table: "users", name: "role" },
        "users.id": { table: "users", name: "id", aggregate: "COUNT", alias: "user_count" },
      },
      ["users.role", "users.id"],
      [],
      [],
      [],
    );

    expect(res.sql).toContain('SELECT "users"."role", COUNT("users"."id") AS "user_count"');
    expect(res.sql).toContain('GROUP BY "users"."role"');
  });

  it("compiles column with custom alias without aggregate", () => {
    const res = compileVisualState(
      "users",
      {
        "users.email": { table: "users", name: "email", alias: "contact_email" },
      },
      ["users.email"],
      [],
      [],
      [],
    );

    expect(res.sql).toContain('"users"."email" AS "contact_email"');
    expect(res.spec.columns[0]).toEqual({
      column: "users.email",
      alias: "contact_email",
    });
  });

  it("skips filters with disallowed or malicious operators", () => {
    const res = compileVisualState(
      "users",
      {},
      [],
      [],
      [
        {
          id: "f1",
          column: "status",
          operator: "EXEC_COMMAND;" as any,
          value: "test",
        },
      ],
      [],
    );
    expect(res.sql).not.toContain("EXEC_COMMAND");
    expect(res.sql).not.toContain("WHERE");
  });

  it("handles non-string primary table input safely", () => {
    const res = compileVisualState(null as unknown as string, {}, [], [], [], []);
    expect(res.sql).toBe("");
    expect(res.spec.table).toBe("");
  });

  it("falls back to LEFT JOIN for invalid join type and ASC for invalid sort direction", () => {
    const res = compileVisualState(
      "users",
      {},
      [],
      [
        {
          id: "j1",
          type: "INVALID_JOIN" as any,
          table: "orders",
          left_col: "id",
          right_col: "user_id",
        },
      ],
      [],
      [
        {
          id: "s1",
          column: "created_at",
          direction: "SIDEWAYS" as any,
        },
      ],
    );
    expect(res.sql).toContain('LEFT JOIN "orders"');
    expect(res.sql).toContain('"users"."created_at" ASC');
  });

  it("compiles numeric filter value without quotes", () => {
    const res = compileVisualState(
      "users",
      { "users.age": { table: "users", name: "age" } },
      ["users.age"],
      [],
      [
        {
          id: "f1",
          tablePrefix: "users",
          column: "age",
          operator: "=",
          value: 25 as any,
        },
      ],
      [],
    );
    expect(res.sql).toContain('"users"."age" = 25');
  });

  it("handles aggregate without alias, DESC sort direction, undefined sorts, and table fallback in GROUP BY", () => {
    // 1. Aggregate without alias and non-agg column with empty table (testing fallback to cleanPrimary)
    const resAgg = compileVisualState(
      "users",
      {
        "users.id": { table: "users", name: "id", aggregate: "COUNT" },
        "users.status": { table: "", name: "status" },
      },
      ["users.id", "users.status"],
      [],
      [],
      [
        {
          id: "s1",
          column: "created_at",
          direction: "DESC",
        },
      ],
    );
    expect(resAgg.sql).toContain('COUNT("users"."id") AS "count_id"');
    expect(resAgg.sql).toContain('GROUP BY "users"."status"');
    expect(resAgg.sql).toContain('"users"."created_at" DESC');

    // 2. Undefined sorts, joins, filters parameter
    const resUndefSorts = compileVisualState(
      "users",
      {},
      [],
      undefined as any,
      undefined as any,
      undefined as any,
    );
    expect(resUndefSorts.sql).toContain('FROM "users"');

    // 3. Filter with empty tablePrefix, null value, and empty IN value
    const resFilterFallbacks = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [
        {
          id: "j1",
          type: "LEFT JOIN",
          left_table: "",
          left_col: "id",
          table: "orders",
          right_col: "user_id",
        },
      ],
      [
        {
          id: "f1",
          tablePrefix: "",
          column: "status",
          operator: "=",
          value: null as any,
        },
        {
          id: "f2",
          tablePrefix: "users",
          column: "role",
          operator: "IN",
          value: "",
        },
      ],
      [],
    );
    expect(resFilterFallbacks.sql).toContain('"users"."status" = \'\'');
    expect(resFilterFallbacks.sql).toContain('"users"."role" IN (NULL)');
    expect(resFilterFallbacks.sql).toContain('LEFT JOIN "orders" ON "users"."id" = "orders"."user_id"');

    // 4. Missing projection item in selectedColumns and invalid aggregate
    const resMissingItem = compileVisualState(
      "users",
      {
        "users.invalid_agg": { table: "users", name: "id", aggregate: "INVALID_AGG" },
      },
      ["missing_item", "users.invalid_agg"],
      [],
      [],
      [],
    );
    expect(resMissingItem.sql).toContain('SELECT "users"."id"');

    // 5. Undefined orderedProjectionKeys
    const resUndefProjections = compileVisualState(
      "users",
      {},
      undefined as any,
      [],
      [],
      [],
    );
    expect(resUndefProjections.sql).toContain("SELECT *");
  });

  it("handles multi-dialect compilation, identifier quoting, and pagination", () => {
    // MySQL / BigQuery / ClickHouse backtick quoting
    const resMySQL = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [
        {
          id: "j1",
          type: "LEFT JOIN",
          left_table: "users",
          table: "orders",
          left_col: "id",
          right_col: "user_id",
        },
      ],
      [
        {
          id: "f1",
          column: "email",
          operator: "STARTS_WITH",
          value: "admin",
          tablePrefix: "users",
        },
      ],
      [{ id: "s1", column: "id", direction: "DESC", tablePrefix: "users" }],
      false,
      25,
      null,
      "mysql",
    );
    expect(resMySQL.sql).toContain("SELECT `users`.`id`");
    expect(resMySQL.sql).toContain("FROM `users`");
    expect(resMySQL.sql).toContain("LEFT JOIN `orders` ON `users`.`id` = `orders`.`user_id`");
    expect(resMySQL.sql).toContain("LOWER(`users`.`email`) LIKE LOWER('admin%')");
    expect(resMySQL.sql).toContain("ORDER BY `users`.`id` DESC");
    expect(resMySQL.sql).toContain("LIMIT 25;");

    // BigQuery and ClickHouse quoting
    const resBQ = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id", alias: "user`id" } },
      ["users.id"],
      [],
      [],
      [],
      false,
      50,
      null,
      "bigquery",
    );
    expect(resBQ.sql).toContain("SELECT `users`.`id` AS `user``id`");

    const resCH = compileVisualState(
      "events",
      { "events.id": { table: "events", name: "id" } },
      ["events.id"],
      [],
      [
        {
          id: "f1",
          column: "action",
          operator: "ILIKE",
          value: "click",
        },
      ],
      [],
      false,
      10,
      null,
      "clickhouse",
    );
    expect(resCH.sql).toContain("`events`.`action` ILIKE 'click'");

    // MSSQL square brackets and FETCH pagination
    const resMSSQL = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id", alias: "col]name" } },
      ["users.id"],
      [],
      [],
      [{ id: "s1", column: "id", direction: "ASC" }],
      false,
      10,
      null,
      "mssql",
    );
    expect(resMSSQL.sql).toContain("SELECT [users].[id] AS [col]]name]");
    expect(resMSSQL.sql).toContain("FROM [users]");
    expect(resMSSQL.sql).toContain("ORDER BY [users].[id] ASC");
    expect(resMSSQL.sql).toContain("OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY;");

    // Oracle FETCH pagination
    const resOracle = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [],
      [],
      false,
      15,
      null,
      "oracle",
    );
    expect(resOracle.sql).toContain("OFFSET 0 ROWS FETCH NEXT 15 ROWS ONLY;");

    // Trino and Presto OFFSET LIMIT pagination
    const resTrino = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [],
      [],
      false,
      30,
      null,
      "trino",
    );
    expect(resTrino.sql).toContain("OFFSET 0 LIMIT 30;");

    const resPresto = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [],
      [],
      false,
      40,
      null,
      "presto",
    );
    expect(resPresto.sql).toContain("OFFSET 0 LIMIT 40;");

    // SQLite LIKE operator
    const resSQLite = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [
        {
          id: "f1",
          column: "email",
          operator: "STARTS_WITH",
          value: "test",
        },
      ],
      [],
      false,
      50,
      null,
      "sqlite",
    );
    expect(resSQLite.sql).toContain('"users"."email" LIKE \'test%\'');

    // DuckDB and Snowflake native ILIKE
    const resDuckDB = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [
        {
          id: "f1",
          column: "email",
          operator: "ENDS_WITH",
          value: "@corp.com",
        },
        {
          id: "f2",
          column: "name",
          operator: "CONTAINS",
          value: "Smith",
        },
      ],
      [],
      false,
      50,
      null,
      "duckdb",
    );
    expect(resDuckDB.sql).toContain('"users"."email" ILIKE \'%@corp.com\'');
    expect(resDuckDB.sql).toContain('"users"."name" ILIKE \'%Smith%\'');

    // Redshift and Snowflake
    const resRedshift = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [
        {
          id: "f1",
          column: "email",
          operator: "ILIKE",
          value: "admin",
        },
      ],
      [],
      false,
      50,
      null,
      "redshift",
    );
    expect(resRedshift.sql).toContain('"users"."email" ILIKE \'admin\'');

    const resSnowflake = compileVisualState(
      "users",
      { "users.id": { table: "users", name: "id" } },
      ["users.id"],
      [],
      [
        {
          id: "f1",
          column: "email",
          operator: "ILIKE",
          value: "admin",
        },
      ],
      [],
      false,
      50,
      null,
      "snowflake",
    );
    expect(resSnowflake.sql).toContain('"users"."email" ILIKE \'admin\'');
  });

  it("handles newly expanded dialects in quoteIdent and quoteAlias", () => {
    // Backtick dialects
    expect(quoteIdent("col", "databricks")).toBe("`col`");
    expect(quoteIdent("col`name", "databricks")).toBe("`col``name`");
    expect(quoteIdent("col", "spanner")).toBe("`col`");
    expect(quoteIdent("col`name", "spanner")).toBe("`col``name`");
    expect(quoteAlias("alias", "databricks")).toBe("`alias`");

    // Standard double-quote dialects
    expect(quoteIdent("col", "polars")).toBe('"col"');
    expect(quoteIdent("col", "athena")).toBe('"col"');
    expect(quoteIdent("col", "datafusion")).toBe('"col"');
    expect(quoteIdent("col", "timescaledb")).toBe('"col"');
    expect(quoteIdent("col", "cockroachdb")).toBe('"col"');
    expect(quoteIdent("col", "questdb")).toBe('"col"');
    expect(quoteIdent("col", "elasticsearch")).toBe('"col"');
    expect(quoteIdent("col", "dynamodb")).toBe('"col"');
  });

  it("handles newly expanded dialects in formatIlike", () => {
    // ILIKE supported
    expect(formatIlike("c", "'%val%'", "polars")).toBe("c ILIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "questdb")).toBe("c ILIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "timescaledb")).toBe("c ILIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "cockroachdb")).toBe("c ILIKE '%val%'");

    // LOWER(...) LIKE LOWER(...) fallback for other dialects
    expect(formatIlike("c", "'%val%'", "databricks")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "athena")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "spanner")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "datafusion")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "elasticsearch")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "dynamodb")).toBe("LOWER(c) LIKE LOWER('%val%')");
  });

  it("handles dialect-specific pagination in formatLimit", () => {
    expect(formatLimit(25, "mssql")).toBe("OFFSET 0 ROWS FETCH NEXT 25 ROWS ONLY;");
    expect(formatLimit(25, "oracle")).toBe("OFFSET 0 ROWS FETCH NEXT 25 ROWS ONLY;");
    expect(formatLimit(25, "trino")).toBe("OFFSET 0 LIMIT 25;");
    expect(formatLimit(25, "presto")).toBe("OFFSET 0 LIMIT 25;");
    expect(formatLimit(25, "polars")).toBe("LIMIT 25;");
    expect(formatLimit(25, "databricks")).toBe("LIMIT 25;");
    expect(formatLimit(25, "spanner")).toBe("LIMIT 25;");
  });

  it("handles the latest 10 production engine dialects in quoteIdent and quoteAlias", () => {
    // Backtick dialects: tidb, singlestore, couchbase
    expect(quoteIdent("col", "tidb")).toBe("`col`");
    expect(quoteIdent("col`name", "tidb")).toBe("`col``name`");
    expect(quoteAlias("alias", "tidb")).toBe("`alias`");

    expect(quoteIdent("col", "singlestore")).toBe("`col`");
    expect(quoteIdent("col`name", "singlestore")).toBe("`col``name`");
    expect(quoteAlias("alias", "singlestore")).toBe("`alias`");
    expect(quoteIdent("col", "memsql")).toBe("`col`");

    expect(quoteIdent("col", "couchbase")).toBe("`col`");
    expect(quoteIdent("col`name", "couchbase")).toBe("`col``name`");
    expect(quoteAlias("alias", "couchbase")).toBe("`alias`");
    expect(quoteIdent("col", "n1ql")).toBe("`col`");

    // Double-quote dialects: dremio, firebolt, teradata, d1, mongodb, neon, supabase
    expect(quoteIdent("col", "dremio")).toBe('"col"');
    expect(quoteIdent("col\"name", "dremio")).toBe('"col""name"');
    expect(quoteAlias("alias", "dremio")).toBe('"alias"');

    expect(quoteIdent("col", "firebolt")).toBe('"col"');
    expect(quoteIdent("col", "teradata")).toBe('"col"');
    expect(quoteIdent("col", "d1")).toBe('"col"');
    expect(quoteIdent("col", "cloudflare_d1")).toBe('"col"');
    expect(quoteIdent("col", "mongodb")).toBe('"col"');
    expect(quoteIdent("col", "mongo")).toBe('"col"');
    expect(quoteIdent("col", "atlas_sql")).toBe('"col"');
    expect(quoteIdent("col", "neon")).toBe('"col"');
    expect(quoteIdent("col", "supabase")).toBe('"col"');
  });

  it("handles the latest 10 production engine dialects in formatIlike", () => {
    // SQLite-style LIKE: d1, cloudflare_d1
    expect(formatIlike("c", "'%val%'", "d1")).toBe("c LIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "cloudflare_d1")).toBe("c LIKE '%val%'");

    // Native ILIKE: dremio, firebolt, neon, supabase
    expect(formatIlike("c", "'%val%'", "dremio")).toBe("c ILIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "firebolt")).toBe("c ILIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "neon")).toBe("c ILIKE '%val%'");
    expect(formatIlike("c", "'%val%'", "supabase")).toBe("c ILIKE '%val%'");

    // LOWER(...) LIKE LOWER(...): tidb, singlestore, teradata, couchbase, mongodb
    expect(formatIlike("c", "'%val%'", "tidb")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "singlestore")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "memsql")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "teradata")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "couchbase")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "n1ql")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "mongodb")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "mongo")).toBe("LOWER(c) LIKE LOWER('%val%')");
    expect(formatIlike("c", "'%val%'", "atlas_sql")).toBe("LOWER(c) LIKE LOWER('%val%')");
  });

  it("handles the latest 10 production engine dialects in formatLimit and compileVisualState", () => {
    expect(formatLimit(30, "teradata")).toBe("OFFSET 0 ROWS FETCH NEXT 30 ROWS ONLY;");
    expect(formatLimit(30, "dremio")).toBe("LIMIT 30;");
    expect(formatLimit(30, "firebolt")).toBe("LIMIT 30;");
    expect(formatLimit(30, "tidb")).toBe("LIMIT 30;");
    expect(formatLimit(30, "singlestore")).toBe("LIMIT 30;");
    expect(formatLimit(30, "memsql")).toBe("LIMIT 30;");
    expect(formatLimit(30, "couchbase")).toBe("LIMIT 30;");
    expect(formatLimit(30, "n1ql")).toBe("LIMIT 30;");
    expect(formatLimit(30, "d1")).toBe("LIMIT 30;");
    expect(formatLimit(30, "cloudflare_d1")).toBe("LIMIT 30;");
    expect(formatLimit(30, "mongodb")).toBe("LIMIT 30;");
    expect(formatLimit(30, "mongo")).toBe("LIMIT 30;");
    expect(formatLimit(30, "atlas_sql")).toBe("LIMIT 30;");
    expect(formatLimit(30, "neon")).toBe("LIMIT 30;");
    expect(formatLimit(30, "supabase")).toBe("LIMIT 30;");

    // Test Couchbase compilation
    const resCouchbase = compileVisualState(
      "airline",
      { "airline.id": { table: "airline", name: "id" } },
      ["airline.id"],
      [],
      [{ id: "f1", column: "name", operator: "CONTAINS", value: "Air" }],
      [{ id: "s1", column: "id", direction: "ASC" }],
      false,
      25,
      null,
      "couchbase",
    );
    expect(resCouchbase.sql).toContain("SELECT `airline`.`id`");
    expect(resCouchbase.sql).toContain("FROM `airline`");
    expect(resCouchbase.sql).toContain("LOWER(`airline`.`name`) LIKE LOWER('%Air%')");
    expect(resCouchbase.sql).toContain("ORDER BY `airline`.`id` ASC");
    expect(resCouchbase.sql).toContain("LIMIT 25;");

    // Test Cloudflare D1 compilation
    const resD1 = compileVisualState(
      "customers",
      { "customers.name": { table: "customers", name: "name" } },
      ["customers.name"],
      [],
      [{ id: "f1", column: "name", operator: "STARTS_WITH", value: "Acme" }],
      [],
      false,
      10,
      null,
      "d1",
    );
    expect(resD1.sql).toContain('SELECT "customers"."name"');
    expect(resD1.sql).toContain('"customers"."name" LIKE \'Acme%\'');
    expect(resD1.sql).toContain("LIMIT 10;");

    // Test Teradata compilation
    const resTeradata = compileVisualState(
      "accounts",
      { "accounts.balance": { table: "accounts", name: "balance" } },
      ["accounts.balance"],
      [],
      [],
      [],
      false,
      50,
      null,
      "teradata",
    );
    expect(resTeradata.sql).toContain("OFFSET 0 ROWS FETCH NEXT 50 ROWS ONLY;");

    // Test Dremio compilation
    const resDremio = compileVisualState(
      "orders",
      { "orders.status": { table: "orders", name: "status" } },
      ["orders.status"],
      [],
      [{ id: "f1", column: "status", operator: "CONTAINS", value: "shipped" }],
      [],
      false,
      20,
      null,
      "dremio",
    );
    expect(resDremio.sql).toContain('"orders"."status" ILIKE \'%shipped%\'');
    expect(resDremio.sql).toContain("LIMIT 20;");

    // Test PrestoDB compilation
    const resPresto = compileVisualState(
      "metrics",
      { "metrics.val": { table: "metrics", name: "val" } },
      ["metrics.val"],
      [],
      [],
      [],
      false,
      15,
      null,
      "prestodb",
    );
    expect(resPresto.sql).toContain('SELECT "metrics"."val"');
    expect(resPresto.sql).toContain("OFFSET 0 LIMIT 15;");

    // Test StarRocks compilation
    const resStarRocks = compileVisualState(
      "events",
      { "events.type": { table: "events", name: "type" } },
      ["events.type"],
      [],
      [{ id: "f1", column: "type", operator: "CONTAINS", value: "click" }],
      [],
      false,
      10,
      null,
      "starrocks",
    );
    expect(resStarRocks.sql).toContain("SELECT `events`.`type`");
    expect(resStarRocks.sql).toContain("`events`.`type` ILIKE '%click%'");
    expect(resStarRocks.sql).toContain("LIMIT 10;");

    // Test Materialize & RisingWave compilation
    const resMaterialize = compileVisualState(
      "mv_stream",
      { "mv_stream.data": { table: "mv_stream", name: "data" } },
      ["mv_stream.data"],
      [],
      [{ id: "f1", column: "data", operator: "CONTAINS", value: "live" }],
      [],
      false,
      30,
      null,
      "materialize",
    );
    expect(resMaterialize.sql).toContain('"mv_stream"."data" ILIKE \'%live%\'');

    const resRisingWave = compileVisualState(
      "rw_source",
      { "rw_source.msg": { table: "rw_source", name: "msg" } },
      ["rw_source.msg"],
      [],
      [{ id: "f1", column: "msg", operator: "CONTAINS", value: "alert" }],
      [],
      false,
      25,
      null,
      "risingwave",
    );
    expect(resRisingWave.sql).toContain('"rw_source"."msg" ILIKE \'%alert%\'');

    // Test CrateDB & InfluxDB compilation
    const resCrate = compileVisualState(
      "logs",
      { "logs.message": { table: "logs", name: "message" } },
      ["logs.message"],
      [],
      [{ id: "f1", column: "message", operator: "CONTAINS", value: "err" }],
      [],
      false,
      40,
      null,
      "cratedb",
    );
    expect(resCrate.sql).toContain('"logs"."message" ILIKE \'%err%\'');

    const resInflux = compileVisualState(
      "cpu",
      { "cpu.usage": { table: "cpu", name: "usage" } },
      ["cpu.usage"],
      [],
      [{ id: "f1", column: "usage", operator: "CONTAINS", value: "high" }],
      [],
      false,
      50,
      null,
      "influxdb",
    );
    expect(resInflux.sql).toContain('"cpu"."usage" ILIKE \'%high%\'');

    // Test AlloyDB & Vertica compilation
    const resAlloy = compileVisualState(
      "analytics",
      { "analytics.kpi": { table: "analytics", name: "kpi" } },
      ["analytics.kpi"],
      [],
      [{ id: "f1", column: "kpi", operator: "CONTAINS", value: "rev" }],
      [],
      false,
      5,
      null,
      "alloydb",
    );
    expect(resAlloy.sql).toContain('"analytics"."kpi" ILIKE \'%rev%\'');

    const resVertica = compileVisualState(
      "fact_sales",
      { "fact_sales.tier": { table: "fact_sales", name: "tier" } },
      ["fact_sales.tier"],
      [],
      [{ id: "f1", column: "tier", operator: "CONTAINS", value: "gold" }],
      [],
      false,
      12,
      null,
      "vertica",
    );
    expect(resVertica.sql).toContain('"fact_sales"."tier" ILIKE \'%gold%\'');

    // Test Druid, Pinot, SAP HANA, OceanBase, ScyllaDB
    const resDruid = compileVisualState(
      "druid_tbl",
      { "druid_tbl.dim": { table: "druid_tbl", name: "dim" } },
      ["druid_tbl.dim"],
      [],
      [{ id: "f1", column: "dim", operator: "CONTAINS", value: "geo" }],
      [],
      false,
      10,
      null,
      "druid",
    );
    expect(resDruid.sql).toContain("LOWER(\"druid_tbl\".\"dim\") LIKE LOWER('%geo%')");

    const resPinot = compileVisualState(
      "pinot_tbl",
      { "pinot_tbl.segment": { table: "pinot_tbl", name: "segment" } },
      ["pinot_tbl.segment"],
      [],
      [{ id: "f1", column: "segment", operator: "CONTAINS", value: "us" }],
      [],
      false,
      10,
      null,
      "pinot",
    );
    expect(resPinot.sql).toContain("LOWER(\"pinot_tbl\".\"segment\") LIKE LOWER('%us%')");

    const resHana = compileVisualState(
      "hana_tbl",
      { "hana_tbl.code": { table: "hana_tbl", name: "code" } },
      ["hana_tbl.code"],
      [],
      [{ id: "f1", column: "code", operator: "CONTAINS", value: "fin" }],
      [],
      false,
      10,
      null,
      "saphana",
    );
    expect(resHana.sql).toContain("LOWER(\"hana_tbl\".\"code\") LIKE LOWER('%fin%')");

    const resOcean = compileVisualState(
      "ob_tbl",
      { "ob_tbl.region": { table: "ob_tbl", name: "region" } },
      ["ob_tbl.region"],
      [],
      [{ id: "f1", column: "region", operator: "CONTAINS", value: "apac" }],
      [],
      false,
      10,
      null,
      "oceanbase",
    );
    expect(resOcean.sql).toContain("SELECT `ob_tbl`.`region`");
    expect(resOcean.sql).toContain("LOWER(`ob_tbl`.`region`) LIKE LOWER('%apac%')");

    const resScylla = compileVisualState(
      "cql_tbl",
      { "cql_tbl.key": { table: "cql_tbl", name: "key" } },
      ["cql_tbl.key"],
      [],
      [{ id: "f1", column: "key", operator: "CONTAINS", value: "row" }],
      [],
      false,
      10,
      null,
      "scylladb",
    );
    expect(resScylla.sql).toContain('SELECT "cql_tbl"."key"');
    expect(resScylla.sql).toContain("LOWER(\"cql_tbl\".\"key\") LIKE LOWER('%row%')");
    expect(resScylla.sql).toContain("LIMIT 10;");
  });
});
