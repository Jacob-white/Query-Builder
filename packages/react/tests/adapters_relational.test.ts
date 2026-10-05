import { describe, it, expect } from "vitest";
import {
  fromPrisma,
  fromDrizzle,
  fromSqlAlchemy,
  fromJsonSchema,
  toSchemaSnapshot,
} from "../src/adapters";
import { findBestJoinCondition } from "../src/utils/joinUtils";
import { normalizeSchema } from "../src/utils/schemaUtils";

const PRISMA_ECOMMERCE = `
enum Role {
  admin
  customer
}

model User {
  id     Int    @id @default(autoincrement())
  email  String
  role   Role   @default(customer)
  orders Order[]
  @@map("users")
}

model Order {
  id     Int         @id @default(autoincrement())
  userId Int
  user   User        @relation(fields: [userId], references: [id])
  items  OrderItem[]
  @@map("orders")
}

model Product {
  id    Int         @id @default(autoincrement())
  name  String
  items OrderItem[]
  @@map("products")
}

model OrderItem {
  orderId   Int
  productId Int
  order     Order   @relation(fields: [orderId], references: [id])
  product   Product @relation(fields: [productId], references: [id])
  @@id([orderId, productId])
  @@map("order_items")
}
`;

const DRIZZLE_ECOMMERCE = `
import { pgTable, serial, integer, text, pgEnum, primaryKey } from 'drizzle-orm/pg-core';

export const roleEnum = pgEnum('role', ['admin', 'customer']);

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: text('email').notNull(),
  role: roleEnum('role').default('customer'),
});

export const orders = pgTable('orders', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id).notNull(),
});

export const products = pgTable('products', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
});

export const orderItems = pgTable('order_items', {
  orderId: integer('order_id').references(() => orders.id).notNull(),
  productId: integer('product_id').references(() => products.id).notNull(),
}, (table) => ({
  pk: primaryKey({ columns: [table.orderId, table.productId] }),
}));
`;

const SQLALCHEMY_ECOMMERCE = `
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    role = Column(Enum('admin', 'customer', name='role'), default='customer')

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

class OrderItem(Base):
    __tablename__ = 'order_items'
    __table_args__ = (PrimaryKeyConstraint('order_id', 'product_id'),)
    order_id = Column(Integer, ForeignKey('orders.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
`;

const JSON_SCHEMA_ECOMMERCE = {
  components: {
    schemas: {
      users: {
        type: "object",
        required: ["id", "email"],
        properties: {
          id: { type: "integer", "x-primary-key": true },
          email: { type: "string" },
          role: { type: "string", enum: ["admin", "customer"] },
        },
      },
      orders: {
        type: "object",
        required: ["id", "user_id"],
        properties: {
          id: { type: "integer", "x-primary-key": true },
          user_id: { type: "integer", "x-foreign-key": "users.id" },
        },
      },
      products: {
        type: "object",
        required: ["id", "name"],
        properties: {
          id: { type: "integer", "x-primary-key": true },
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
        },
      },
    },
  },
};

describe("Multi-Table Relational Integration across all Adapters", () => {
  it("conforms across Prisma, Drizzle, SQLAlchemy, and JSON Schema", () => {
    const prismaTables = fromPrisma(PRISMA_ECOMMERCE);
    const drizzleTables = fromDrizzle(DRIZZLE_ECOMMERCE);
    const saTables = fromSqlAlchemy(SQLALCHEMY_ECOMMERCE);
    const jsonTables = fromJsonSchema(JSON_SCHEMA_ECOMMERCE);

    const allAdapters = [prismaTables, drizzleTables, saTables, jsonTables];

    for (const tables of allAdapters) {
      expect(tables.map((t) => t.name).sort()).toEqual(
        ["order_items", "orders", "products", "users"].sort(),
      );

      const users = tables.find((t) => t.name === "users")!;
      expect(users.primaryKeys).toContain("id");

      const orderItems = tables.find((t) => t.name === "order_items")!;
      expect(orderItems.primaryKeys).toHaveLength(2);

      const orders = tables.find((t) => t.name === "orders")!;
      expect(orders.foreignKeys!.some((fk) => fk.foreignTable === "users")).toBe(true);
    }
  });

  it("finds join relationships automatically via findBestJoinCondition", () => {
    const drizzleTables = fromDrizzle(DRIZZLE_ECOMMERCE);
    const snapshot = toSchemaSnapshot(drizzleTables);

    const joinCondition = findBestJoinCondition("users", "orders", snapshot);
    expect(joinCondition).not.toBeNull();
    expect(joinCondition?.leftCol).toBe("id");
    expect(joinCondition?.rightCol).toBe("user_id");
  });

  it("works with normalizeSchema when passed TableSchema[] directly", () => {
    const saTables = fromSqlAlchemy(SQLALCHEMY_ECOMMERCE);
    const normalized = normalizeSchema(saTables);

    expect(normalized).not.toBeNull();
    expect(normalized!.tables["users"]).toBeDefined();
    expect(normalized!.tables["orders"]).toBeDefined();
    expect(normalized!.foreign_keys!.length).toBeGreaterThanOrEqual(3);
  });
});
