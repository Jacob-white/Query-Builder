import { describe, it, expect } from "vitest";
import { findBestJoinCondition, findJoinPath } from "../src/utils/joinUtils";
import type { SchemaSnapshot } from "../src/types";

describe("joinUtils", () => {
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
      order_items: {
        name: "order_items",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "order_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "item_name", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
      system_logs: {
        name: "system_logs",
        columns: [
          { name: "log_id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "message", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
    },
    foreign_keys: [
      {
        table: "orders",
        column: "user_id",
        foreign_table: "users",
        foreign_column: "id",
      },
      {
        table: "order_items",
        column: "order_id",
        foreign_table: "orders",
        foreign_column: "id",
      },
    ],
  };

  it("finds best join condition using explicit schema foreign key", () => {
    const match = findBestJoinCondition("users", "orders", mockSchema);
    expect(match.isFk).toBe(true);
    expect(match.leftTable).toBe("users");
    expect(match.leftCol).toBe("id");
    expect(match.rightTable).toBe("orders");
    expect(match.rightCol).toBe("user_id");
  });

  it("finds best join condition using reverse schema foreign key", () => {
    const match = findBestJoinCondition("orders", "users", mockSchema);
    expect(match.isFk).toBe(true);
    expect(match.leftTable).toBe("orders");
    expect(match.leftCol).toBe("user_id");
    expect(match.rightTable).toBe("users");
    expect(match.rightCol).toBe("id");
  });

  it("finds multi-hop join path using BFS graph search", () => {
    const path = findJoinPath(["users"], "order_items", mockSchema);
    expect(path).toHaveLength(2);
    expect(path[0].table).toBe("orders");
    expect(path[1].table).toBe("order_items");
  });

  it("returns empty join path if table is already active", () => {
    const path = findJoinPath(["users", "orders"], "orders", mockSchema);
    expect(path).toHaveLength(0);
  });

  it("returns empty join path if active tables list is empty", () => {
    const path = findJoinPath([], "orders", mockSchema);
    expect(path).toHaveLength(0);
  });

  it("discovers entity bridge joins when explicit FK array is absent", () => {
    const schemaWithBridgesOnly: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
        },
        user: {
          name: "user",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
        },
        profiles: {
          name: "profiles",
          columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }, { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false }],
        },
      },
      foreign_keys: [],
    };

    const path = findJoinPath(["user"], "profiles", schemaWithBridgesOnly);
    expect(path.length).toBeGreaterThanOrEqual(1);
    expect(path[0].table).toBe("profiles");
  });

  it("uses fallback direct join when BFS cannot find a connected path", () => {
    // system_logs has no relationship to users
    const path = findJoinPath(["users"], "system_logs", mockSchema);
    expect(path).toHaveLength(1);
    expect(path[0].table).toBe("system_logs");
  });

  it("falls back gracefully when schema is null", () => {
    const match = findBestJoinCondition("accounts", "transactions", null);
    expect(match.leftTable).toBe("accounts");
    expect(match.rightTable).toBe("transactions");
  });

  it("matches tables on canonical identifier like firm_id when no FK is defined", () => {
    const canonicalSchema: SchemaSnapshot = {
      tables: {
        advisors: {
          name: "advisors",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "firm_id", data_type: "integer", is_nullable: false, is_primary: false },
          ],
        },
        branches: {
          name: "branches",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "firm_id", data_type: "integer", is_nullable: false, is_primary: false },
          ],
        },
      },
      foreign_keys: [],
    };

    const match = findBestJoinCondition("advisors", "branches", canonicalSchema);
    expect(match.leftCol).toBe("firm_id");
    expect(match.rightCol).toBe("firm_id");
    expect(match.reason).toContain("Canonical identifier match");
  });

  it("infers named entity foreign key when left table has cleanRight_id column", () => {
    const inferredSchema: SchemaSnapshot = {
      tables: {
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "users_id", data_type: "integer", is_nullable: false, is_primary: false },
          ],
        },
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          ],
        },
      },
      foreign_keys: [],
    };

    const match = findBestJoinCondition("orders", "users", inferredSchema);
    expect(match.leftCol).toBe("users_id");
    expect(match.rightCol).toBe("id");
    expect(match.isFk).toBe(true);
  });

  it("handles empty or invalid table names in findBestJoinCondition", () => {
    const match1 = findBestJoinCondition("", "orders");
    expect(match1.leftTable).toBe("t1");
    expect(match1.rightTable).toBe("orders");

    const match2 = findBestJoinCondition("users", "");
    expect(match2.leftTable).toBe("users");
    expect(match2.rightTable).toBe("t2");
  });

  it("handles invalid targetTable or activeTables inputs in findJoinPath", () => {
    expect(findJoinPath(["users"], "")).toEqual([]);
    expect(findJoinPath(["users"], null as unknown as string)).toEqual([]);
    expect(findJoinPath(null as unknown as string[], "orders")).toEqual([]);
  });

  it("limits activeTables to MAX_ACTIVE_TABLES", () => {
    const manyActive = Array.from({ length: 60 }, (_, i) => `table_${i}`);
    const path = findJoinPath(manyActive, "target_table", mockSchema);
    expect(path).toHaveLength(1);
  });

  it("skips malformed table metadata in entity bridges", () => {
    const badSchema: SchemaSnapshot = {
      tables: {
        bad1: null as unknown as any,
        bad2: { name: "bad2", columns: null as unknown as any },
      },
      foreign_keys: [],
    };
    const path = findJoinPath(["a"], "b", badSchema);
    expect(path).toHaveLength(1);
  });

  it("respects MAX_JOIN_DEPTH in BFS search", () => {
    // 12-hop linear chain
    const deepFks = Array.from({ length: 12 }, (_, i) => ({
      table: String.fromCharCode(97 + i + 1),
      column: "fk",
      foreign_table: String.fromCharCode(97 + i),
      foreign_column: "id",
    }));
    const deepSchema: SchemaSnapshot = {
      tables: {},
      foreign_keys: deepFks,
    };
    const path = findJoinPath(["a"], "m", deepSchema);
    // Over 10 hops cannot be reached via BFS; falls back to direct join
    expect(path).toHaveLength(1);
  });
});
