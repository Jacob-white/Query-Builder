import { describe, it, expect } from "vitest";
import { fromSqlAlchemy, toSchemaSnapshot } from "../src/adapters";
import { normalizeSchema } from "../src/utils/schemaUtils";

const SQLALCHEMY_CODE = `
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    name = Column(String, nullable=True)
    role = Column(Enum('admin', 'customer', 'guest', name='role'), default='customer')

class Profile(Base):
    __tablename__ = 'profiles'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    bio = Column(String)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(Enum('pending', 'paid', 'shipped', name='status'), default='pending')
    total = Column(Float, nullable=False)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)

class OrderItem(Base):
    __tablename__ = 'order_items'
    __table_args__ = (PrimaryKeyConstraint('order_id', 'product_id'),)
    order_id = Column(Integer, ForeignKey('orders.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    quantity = Column(Integer, default=1)
`;

describe("fromSqlAlchemy Adapter", () => {
  it("parses Python model code into TableSchema[]", () => {
    const tables = fromSqlAlchemy(SQLALCHEMY_CODE);
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

    // Foreign key
    const profiles = tables.find((t) => t.name === "profiles")!;
    expect(profiles.foreignKeys).toHaveLength(1);
    expect(profiles.foreignKeys![0].foreignTable).toBe("users");
    expect(profiles.foreignKeys![0].foreignColumn).toBe("id");

    // Composite primary key
    const orderItems = tables.find((t) => t.name === "order_items")!;
    expect(orderItems.primaryKeys).toEqual(["order_id", "product_id"]);
    expect(orderItems.foreignKeys).toHaveLength(2);
  });

  it("parses serialized metadata dictionary", () => {
    const metadata = {
      tables: {
        accounts: {
          columns: [
            { name: "id", data_type: "integer", is_primary: true },
            { name: "balance", data_type: "decimal", is_nullable: false },
          ],
          primary_keys: ["id"],
        },
      },
    };

    const tables = fromSqlAlchemy(metadata);
    expect(tables).toHaveLength(1);
    expect(tables[0].name).toBe("accounts");
    expect(tables[0].columns).toHaveLength(2);
    expect(tables[0].primaryKeys).toEqual(["id"]);
  });

  it("converts to SchemaSnapshot and works with normalizeSchema", () => {
    const tables = fromSqlAlchemy(SQLALCHEMY_CODE);
    const snapshot = toSchemaSnapshot(tables);
    expect(Object.keys(snapshot.tables)).toHaveLength(5);

    const normalized = normalizeSchema(tables);
    expect(normalized).not.toBeNull();
    expect(Object.keys(normalized!.tables)).toHaveLength(5);
  });
});
