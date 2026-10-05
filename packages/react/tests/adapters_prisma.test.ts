import { describe, it, expect } from "vitest";
import { fromPrisma, toSchemaSnapshot } from "../src/adapters";
import { normalizeSchema } from "../src/utils/schemaUtils";

const PRISMA_SCHEMA = `
enum UserRole {
  ADMIN
  CUSTOMER
  GUEST
}

enum OrderStatus {
  PENDING
  PAID
  SHIPPED
}

model User {
  id        Int       @id @default(autoincrement())
  email     String    @unique
  name      String?
  role      UserRole  @default(CUSTOMER)
  orders    Order[]

  @@map("users")
}

model Profile {
  id      Int     @id @default(autoincrement())
  userId  Int     @unique
  bio     String?
  user    User    @relation(fields: [userId], references: [id])

  @@map("profiles")
}

model Order {
  id      Int         @id @default(autoincrement())
  userId  Int
  status  OrderStatus @default(PENDING)
  total   Float
  user    User        @relation(fields: [userId], references: [id])
  items   OrderItem[]

  @@map("orders")
}

model Product {
  id      Int         @id @default(autoincrement())
  name    String
  price   Float
  items   OrderItem[]

  @@map("products")
}

model OrderItem {
  orderId   Int
  productId Int
  quantity  Int     @default(1)
  order     Order   @relation(fields: [orderId], references: [id])
  product   Product @relation(fields: [productId], references: [id])

  @@id([orderId, productId])
  @@map("order_items")
}
`;

describe("fromPrisma Adapter", () => {
  it("parses multi-table relational schema correctly", () => {
    const tables = fromPrisma(PRISMA_SCHEMA);
    expect(tables).toHaveLength(5);

    const users = tables.find((t) => t.name === "users")!;
    expect(users).toBeDefined();
    expect(users.primaryKeys).toEqual(["id"]);

    const idCol = users.columns.find((c) => c.name === "id")!;
    expect(idCol.dataType).toBe("integer");
    expect(idCol.isNullable).toBe(false);
    expect(idCol.isPrimary).toBe(true);

    const emailCol = users.columns.find((c) => c.name === "email")!;
    expect(emailCol.dataType).toBe("text");
    expect(emailCol.isNullable).toBe(false);

    const nameCol = users.columns.find((c) => c.name === "name")!;
    expect(nameCol.isNullable).toBe(true);

    const roleCol = users.columns.find((c) => c.name === "role")!;
    expect(roleCol.enums).toEqual(["ADMIN", "CUSTOMER", "GUEST"]);
    expect(roleCol.default).toBe("CUSTOMER");

    // Foreign key on profiles
    const profiles = tables.find((t) => t.name === "profiles")!;
    expect(profiles.foreignKeys).toHaveLength(1);
    expect(profiles.foreignKeys![0].foreignTable).toBe("users");
    expect(profiles.foreignKeys![0].foreignColumn).toBe("id");

    // Composite primary key on order_items
    const orderItems = tables.find((t) => t.name === "order_items")!;
    expect(orderItems.primaryKeys).toEqual(["orderId", "productId"]);
    expect(orderItems.foreignKeys).toHaveLength(2);
  });

  it("parses DMMF object input", () => {
    const dmmf = {
      datamodel: {
        enums: [
          { name: "Plan", values: [{ name: "FREE" }, { name: "PRO" }] },
        ],
        models: [
          {
            name: "Member",
            dbName: "members",
            fields: [
              { name: "id", type: "Int", isId: true, isRequired: true },
              { name: "plan", type: "Plan", kind: "enum", isRequired: true },
            ],
          },
        ],
      },
    };

    const tables = fromPrisma(dmmf);
    expect(tables).toHaveLength(1);
    expect(tables[0].name).toBe("members");
    expect(tables[0].primaryKeys).toEqual(["id"]);
    expect(tables[0].columns[1].enums).toEqual(["FREE", "PRO"]);
  });

  it("converts to SchemaSnapshot and integrates with normalizeSchema", () => {
    const tables = fromPrisma(PRISMA_SCHEMA);
    const snapshot = toSchemaSnapshot(tables);
    expect(Object.keys(snapshot.tables)).toHaveLength(5);
    expect(snapshot.foreign_keys!.length).toBeGreaterThanOrEqual(3);

    // Direct integration with normalizeSchema
    const normalized = normalizeSchema(tables);
    expect(normalized).not.toBeNull();
    expect(Object.keys(normalized!.tables)).toHaveLength(5);
    expect(normalized!.foreign_keys!.length).toBeGreaterThanOrEqual(3);
  });
});
