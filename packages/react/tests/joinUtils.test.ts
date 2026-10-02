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
});
