import { describe, it, expect } from "vitest";
import { fromDrizzle, toSchemaSnapshot } from "../src/adapters";
import { normalizeSchema } from "../src/utils/schemaUtils";

const DRIZZLE_CODE = `
import { pgTable, serial, text, integer, timestamp, doublePrecision, pgEnum, primaryKey } from 'drizzle-orm/pg-core';

export const userRoleEnum = pgEnum('user_role', ['admin', 'customer', 'guest']);
export const orderStatusEnum = pgEnum('order_status', ['pending', 'paid', 'shipped']);

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: text('email').notNull(),
  name: text('name'),
  role: userRoleEnum('role').default('customer'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const profiles = pgTable('profiles', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id).notNull(),
  bio: text('bio'),
});

export const orders = pgTable('orders', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id).notNull(),
  status: orderStatusEnum('status').default('pending'),
  total: doublePrecision('total').notNull(),
});

export const products = pgTable('products', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  price: doublePrecision('price').notNull(),
});

export const orderItems = pgTable('order_items', {
  orderId: integer('order_id').references(() => orders.id).notNull(),
  productId: integer('product_id').references(() => products.id).notNull(),
  quantity: integer('quantity').default(1),
}, (table) => ({
  pk: primaryKey({ columns: [table.orderId, table.productId] }),
}));
`;

describe("fromDrizzle Adapter", () => {
  it("parses Drizzle TypeScript code into TableSchema[]", () => {
    const tables = fromDrizzle(DRIZZLE_CODE);
    expect(tables).toHaveLength(5);

    const users = tables.find((t) => t.name === "users")!;
    expect(users).toBeDefined();
    expect(users.primaryKeys).toEqual(["id"]);

    const idCol = users.columns.find((c) => c.name === "id")!;
    expect(idCol.dataType).toBe("integer");
    expect(idCol.isNullable).toBe(false);
    expect(idCol.isPrimary).toBe(true);

    const emailCol = users.columns.find((c) => c.name === "email")!;
    expect(emailCol.isNullable).toBe(false);

    const nameCol = users.columns.find((c) => c.name === "name")!;
    expect(nameCol.isNullable).toBe(true);

    const roleCol = users.columns.find((c) => c.name === "role")!;
    expect(roleCol.enums).toEqual(["admin", "customer", "guest"]);

    // Foreign key resolution
    const profiles = tables.find((t) => t.name === "profiles")!;
    expect(profiles.foreignKeys).toHaveLength(1);
    expect(profiles.foreignKeys![0].foreignTable).toBe("users");

    // Composite primary key
    const orderItems = tables.find((t) => t.name === "order_items")!;
    expect(orderItems.primaryKeys).toEqual(["order_id", "product_id"]);
    expect(orderItems.foreignKeys).toHaveLength(2);
  });

  it("handles runtime Drizzle table objects", () => {
    const mockUsersTable = {
      [Symbol.for("drizzle:Name")]: "users",
      id: { name: "id", dataType: "number", primary: true, notNull: true },
      email: { name: "email", dataType: "string", notNull: true },
      bio: { name: "bio", dataType: "string", notNull: false },
    };

    const mockOrdersTable = {
      [Symbol.for("drizzle:Name")]: "orders",
      id: { name: "id", dataType: "number", primary: true, notNull: true },
      userId: {
        name: "user_id",
        dataType: "number",
        notNull: true,
        references: () => ({ table: mockUsersTable, name: "id" }),
      },
    };

    const tables = fromDrizzle({ users: mockUsersTable, orders: mockOrdersTable });
    expect(tables).toHaveLength(2);

    const users = tables.find((t) => t.name === "users")!;
    expect(users.primaryKeys).toEqual(["id"]);

    const orders = tables.find((t) => t.name === "orders")!;
    expect(orders.foreignKeys).toHaveLength(1);
    expect(orders.foreignKeys![0].foreignTable).toBe("users");
  });

  it("converts to SchemaSnapshot and works with normalizeSchema", () => {
    const tables = fromDrizzle(DRIZZLE_CODE);
    const snapshot = toSchemaSnapshot(tables);
    expect(Object.keys(snapshot.tables)).toHaveLength(5);

    const normalized = normalizeSchema(tables);
    expect(normalized).not.toBeNull();
    expect(Object.keys(normalized!.tables)).toHaveLength(5);
  });
});
