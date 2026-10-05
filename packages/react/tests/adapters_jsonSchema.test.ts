import { describe, it, expect } from "vitest";
import { fromJsonSchema, toSchemaSnapshot } from "../src/adapters";
import { normalizeSchema } from "../src/utils/schemaUtils";

const OPENAPI_SPEC = {
  openapi: "3.1.0",
  components: {
    schemas: {
      users: {
        type: "object",
        required: ["id", "email"],
        properties: {
          id: { type: "integer", "x-primary-key": true },
          email: { type: "string" },
          name: { type: "string" },
          role: {
            type: "string",
            enum: ["admin", "customer", "guest"],
            default: "customer",
          },
        },
      },
      profiles: {
        type: "object",
        required: ["id", "user_id"],
        properties: {
          id: { type: "integer", primaryKey: true },
          user_id: { type: "integer", "x-foreign-key": "users.id" },
          bio: { type: "string" },
        },
      },
      orders: {
        type: "object",
        required: ["id", "user_id"],
        properties: {
          id: { type: "integer", is_primary: true },
          user_id: { type: "integer", "x-foreign-key": "users.id" },
          status: {
            type: "string",
            enum: ["pending", "paid", "shipped"],
            default: "pending",
          },
        },
      },
      products: {
        type: "object",
        required: ["id", "name"],
        properties: {
          id: { type: "integer" },
          name: { type: "string" },
        },
      },
      order_items: {
        type: "object",
        "x-primary-keys": ["order_id", "product_id"],
        required: ["order_id", "product_id"],
        properties: {
          order_id: { type: "integer", "x-foreign-key": "orders.id" },
          product_id: { type: "integer", "x-foreign-key": "products.id" },
          quantity: { type: "integer", default: 1 },
        },
      },
    },
  },
};

describe("fromJsonSchema Adapter", () => {
  it("parses OpenAPI 3.x components.schemas", () => {
    const tables = fromJsonSchema(OPENAPI_SPEC);
    expect(tables).toHaveLength(5);

    const users = tables.find((t) => t.name === "users")!;
    expect(users).toBeDefined();
    expect(users.primaryKeys).toEqual(["id"]);

    const idCol = users.columns.find((c) => c.name === "id")!;
    expect(idCol.dataType).toBe("integer");
    expect(idCol.isNullable).toBe(false);

    const emailCol = users.columns.find((c) => c.name === "email")!;
    expect(emailCol.isNullable).toBe(false);

    const nameCol = users.columns.find((c) => c.name === "name")!;
    expect(nameCol.isNullable).toBe(true);

    const roleCol = users.columns.find((c) => c.name === "role")!;
    expect(roleCol.enums).toEqual(["admin", "customer", "guest"]);

    // Foreign keys
    const profiles = tables.find((t) => t.name === "profiles")!;
    expect(profiles.foreignKeys).toHaveLength(1);
    expect(profiles.foreignKeys![0].foreignTable).toBe("users");

    // Composite primary key
    const orderItems = tables.find((t) => t.name === "order_items")!;
    expect(orderItems.primaryKeys).toEqual(["order_id", "product_id"]);
    expect(orderItems.foreignKeys).toHaveLength(2);
  });

  it("parses JSON Schema string format", () => {
    const jsonStr = JSON.stringify(OPENAPI_SPEC);
    const tables = fromJsonSchema(jsonStr);
    expect(tables).toHaveLength(5);
  });

  it("handles $ref relationships in JSON Schema definitions", () => {
    const schemaWithRef = {
      definitions: {
        Company: {
          type: "object",
          properties: {
            id: { type: "integer" },
            name: { type: "string" },
          },
        },
        Employee: {
          type: "object",
          properties: {
            id: { type: "integer" },
            company_id: {
              type: "integer",
              $ref: "#/definitions/Company",
            },
          },
        },
      },
    };

    const tables = fromJsonSchema(schemaWithRef);
    expect(tables).toHaveLength(2);

    const emp = tables.find((t) => t.name === "Employee")!;
    expect(emp.foreignKeys).toHaveLength(1);
    expect(emp.foreignKeys![0].foreignTable).toBe("Company");
  });

  it("converts to SchemaSnapshot and integrates with normalizeSchema", () => {
    const tables = fromJsonSchema(OPENAPI_SPEC);
    const snapshot = toSchemaSnapshot(tables);
    expect(Object.keys(snapshot.tables)).toHaveLength(5);

    const normalized = normalizeSchema(tables);
    expect(normalized).not.toBeNull();
    expect(Object.keys(normalized!.tables)).toHaveLength(5);
  });
});
