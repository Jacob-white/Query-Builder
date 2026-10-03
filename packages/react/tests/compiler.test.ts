import { describe, it, expect } from "vitest";
import { compileVisualState } from "../src/utils/compiler";
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
});
