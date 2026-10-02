import { describe, it, expect } from "vitest";
import { compileVisualState } from "../src/utils/compiler";

describe("compileVisualState", () => {
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

  it("compiles aggregate functions and aliases", () => {
    const res = compileVisualState(
      "users",
      {
        "users.id": { table: "users", name: "id", aggregate: "COUNT", alias: "user_count" },
      },
      ["users.id"],
      [],
      [],
      [],
    );

    expect(res.sql).toContain('COUNT("users"."id") AS "user_count"');
  });
});
