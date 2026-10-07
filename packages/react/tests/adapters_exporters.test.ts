import { describe, it, expect } from "vitest";
import {
  toPrisma,
  toPrismaSchema,
  fromPrisma,
  toDrizzle,
  toDrizzleSchema,
  fromDrizzle,
  toSqlAlchemy,
  toSqlAlchemyModels,
  fromSqlAlchemy,
  toPascalCase,
  toCamelCase,
  toSnakeCase,
  extractSnapshotData,
  toSchemaSnapshot,
} from "../src/adapters";
import type { TableSchema } from "../src/types";

describe("Identifier Utilities", () => {
  it("converts names to PascalCase", () => {
    expect(toPascalCase("users")).toBe("Users");
    expect(toPascalCase("user_accounts")).toBe("UserAccounts");
    expect(toPascalCase("firm-master-v2")).toBe("FirmMasterV2");
    expect(toPascalCase("123_reports")).toBe("Model123Reports");
    expect(toPascalCase("")).toBe("Model");
    expect(toPascalCase("   ")).toBe("Model");
  });

  it("converts names to camelCase", () => {
    expect(toCamelCase("id")).toBe("id");
    expect(toCamelCase("user_id")).toBe("userId");
    expect(toCamelCase("first_name_field")).toBe("firstNameField");
    expect(toCamelCase("123_val")).toBe("col123Val");
    expect(toCamelCase("")).toBe("field");
    expect(toCamelCase("   ")).toBe("field");
  });

  it("converts names to snake_case", () => {
    expect(toSnakeCase("UserID")).toBe("user_id");
    expect(toSnakeCase("UserAccounts")).toBe("user_accounts");
    expect(toSnakeCase("firm_master")).toBe("firm_master");
    expect(toSnakeCase("123_val")).toBe("col_123_val");
    expect(toSnakeCase("")).toBe("col");
    expect(toSnakeCase("   ")).toBe("col");
  });
});

describe("extractSnapshotData Helper", () => {
  it("extracts from TableSchema array", () => {
    const tables: TableSchema[] = [
      {
        name: "users",
        columns: [
          { name: "id", dataType: "integer", isPrimary: true, isNullable: false },
          { name: "name", dataType: "text", isNullable: true },
        ],
        foreignKeys: [],
      },
    ];
    const { tables: extracted, foreignKeys } = extractSnapshotData(tables);
    expect(extracted.users).toBeDefined();
    expect(extracted.users.columns).toHaveLength(2);
    expect(extracted.users.columns[0].is_primary).toBe(true);
    expect(foreignKeys).toHaveLength(0);
  });

  it("extracts from SchemaSnapshot object", () => {
    const snapshot = {
      tables: {
        posts: {
          name: "posts",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "user_id", data_type: "int" },
          ],
        },
      },
      foreign_keys: [
        { table: "posts", column: "user_id", foreign_table: "users", foreign_column: "id" },
      ],
      relationships: [],
    };
    const { tables, foreignKeys } = extractSnapshotData(snapshot);
    expect(tables.posts).toBeDefined();
    expect(foreignKeys).toHaveLength(1);
    expect(foreignKeys[0].table).toBe("posts");
  });
});

describe("toPrisma Converter", () => {
  const sampleSchema = {
    tables: {
      users: {
        columns: [
          { name: "id", data_type: "integer", is_primary: true, is_nullable: false },
          { name: "email", data_type: "text", is_nullable: false },
          { name: "age", data_type: "integer", is_nullable: true },
        ],
      },
    },
  };

  it("generates basic postgres prisma schema", () => {
    const out = toPrisma(sampleSchema, { provider: "postgresql" });
    expect(out).toContain('provider = "postgresql"');
    expect(out).toContain('url      = env("DATABASE_URL")');
    expect(out).toContain("generator client {");
    expect(out).toContain("model Users {");
    expect(out).toContain("id Int @id @default(autoincrement())");
    expect(out).toContain("email String");
    expect(out).toContain("age Int?");
    expect(out).toContain('@@map("users")');
  });

  it("supports alias export toPrismaSchema", () => {
    expect(toPrismaSchema).toBe(toPrisma);
  });

  it("supports all providers and aliases", () => {
    const providers = [
      ["postgresql", "postgresql"],
      ["postgres", "postgresql"],
      ["mysql", "mysql"],
      ["sqlite", "sqlite"],
      ["sqlserver", "sqlserver"],
      ["mssql", "sqlserver"],
      ["cockroachdb", "cockroachdb"],
      ["mongodb", "mongodb"],
    ];

    for (const [input, expected] of providers) {
      const out = toPrisma({}, input);
      expect(out).toContain(`provider = "${expected}"`);
    }
  });

  it("throws on unsupported provider", () => {
    expect(() => toPrisma({}, "oracle_db")).toThrow("Unsupported Prisma provider 'oracle_db'");
  });

  it("maps SQL types to Prisma scalar types", () => {
    const schema = {
      tables: {
        all_types: {
          columns: [
            { name: "c_bigint", data_type: "bigint" },
            { name: "c_bool", data_type: "boolean" },
            { name: "c_float", data_type: "float" },
            { name: "c_decimal", data_type: "numeric" },
            { name: "c_date", data_type: "timestamptz" },
            { name: "c_json", data_type: "jsonb" },
            { name: "c_bytes", data_type: "bytea" },
            { name: "c_unknown", data_type: "custom_domain" },
          ],
        },
      },
    };
    const out = toPrisma(schema);
    expect(out).toContain('cBigint BigInt? @map("c_bigint")');
    expect(out).toContain('cBool Boolean? @map("c_bool")');
    expect(out).toContain('cFloat Float? @map("c_float")');
    expect(out).toContain('cDecimal Decimal? @map("c_decimal")');
    expect(out).toContain('cDate DateTime? @map("c_date")');
    expect(out).toContain('cJson Json? @map("c_json")');
    expect(out).toContain('cBytes Bytes? @map("c_bytes")');
    expect(out).toContain('cUnknown String? @map("c_unknown")');
  });

  it("handles single and multiple foreign key relations", () => {
    const schema = {
      tables: {
        users: {
          columns: [
            { name: "id", data_type: "int", is_primary: true, is_nullable: false },
            { name: "name", data_type: "text" },
          ],
        },
        posts: {
          columns: [
            { name: "id", data_type: "int", is_primary: true, is_nullable: false },
            { name: "author_id", data_type: "int", is_nullable: true },
            { name: "editor_id", data_type: "int", is_nullable: false },
          ],
        },
      },
      foreign_keys: [
        { table: "posts", column: "author_id", foreign_table: "users", foreign_column: "id" },
        { table: "posts", column: "editor_id", foreign_table: "users", foreign_column: "id" },
      ],
    };

    const out = toPrisma(schema);
    // Disambiguated relation names when multiple FKs point between same pair of tables
    expect(out).toContain('author Users? @relation("Users_authorId", fields: [authorId], references: [id])');
    expect(out).toContain('editor Users @relation("Users_editorId", fields: [editorId], references: [id])');
    // Back-relations in Users
    expect(out).toContain('postsByAuthorId Posts[] @relation("Users_authorId")');
    expect(out).toContain('postsByEditorId Posts[] @relation("Users_editorId")');
  });

  it("handles relation name disambiguation when clashing with scalar column", () => {
    const schema = {
      tables: {
        users: {
          columns: [{ name: "id", data_type: "int", is_primary: true }],
        },
        orders: {
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "user", data_type: "text" },
            { name: "user_id", data_type: "int" },
          ],
        },
      },
      foreign_keys: [
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
      ],
    };

    const out = toPrisma(schema);
    expect(out).toContain("user String?");
    expect(out).toContain("userRel Users? @relation(fields: [userId], references: [id])");
  });

  it("handles empty schema", () => {
    const out = toPrisma({});
    expect(out).toContain("datasource db {");
    expect(out).toContain("generator client {");
    expect(out).not.toContain("model");
  });
});

describe("toDrizzle Converter", () => {
  const schema = {
    tables: {
      users: {
        columns: [
          { name: "id", data_type: "integer", is_primary: true, is_nullable: false },
          { name: "email", data_type: "text", is_nullable: false },
          { name: "bio", data_type: "varchar", is_nullable: true },
        ],
      },
      posts: {
        columns: [
          { name: "id", data_type: "serial", is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false },
          { name: "title", data_type: "text", is_nullable: false },
        ],
      },
    },
    foreign_keys: [
      { table: "posts", column: "user_id", foreign_table: "users", foreign_column: "id" },
    ],
  };

  it("generates postgres drizzle schema", () => {
    const out = toDrizzle(schema, "postgres");
    expect(out).toContain('from "drizzle-orm/pg-core";');
    expect(out).toContain('export const users = pgTable("users", {');
    expect(out).toContain('id: serial("id").primaryKey(),');
    expect(out).toContain('email: text("email").notNull(),');
    expect(out).toContain('export const posts = pgTable("posts", {');
    expect(out).toContain('userId: integer("user_id").references(() => users.id).notNull(),');
  });

  it("generates mysql drizzle schema", () => {
    const out = toDrizzle(schema, { dialect: "mysql" });
    expect(out).toContain('from "drizzle-orm/mysql-core";');
    expect(out).toContain('export const users = mysqlTable("users", {');
    expect(out).toContain('id: serial("id").primaryKey(),');
    expect(out).toContain('email: varchar("email", { length: 255 }).notNull(),');
    expect(out).toContain('userId: int("user_id").references(() => users.id).notNull(),');
  });

  it("generates sqlite drizzle schema", () => {
    const out = toDrizzle(schema, "sqlite");
    expect(out).toContain('from "drizzle-orm/sqlite-core";');
    expect(out).toContain('export const users = sqliteTable("users", {');
    expect(out).toContain('id: integer("id").primaryKey({ autoIncrement: true }),');
    expect(out).toContain('email: text("email").notNull(),');
    expect(out).toContain('userId: integer("user_id").references(() => users.id).notNull(),');
  });

  it("supports alias export toDrizzleSchema", () => {
    expect(toDrizzleSchema).toBe(toDrizzle);
  });

  it("throws on unsupported dialect", () => {
    expect(() => toDrizzle(schema, "oracle")).toThrow(
      "Unsupported Drizzle dialect 'oracle'. Supported: ('postgres', 'mysql', 'sqlite')",
    );
  });

  it("handles empty schema", () => {
    const out = toDrizzle({}, "postgres");
    expect(out).toContain('from "drizzle-orm/pg-core";');
    expect(out).not.toContain("export const");
  });
});

describe("toSqlAlchemy Converter", () => {
  const schema = {
    tables: {
      users: {
        comment: "User accounts table",
        columns: [
          { name: "id", data_type: "integer", is_primary: true, is_nullable: false },
          { name: "username", data_type: "text", is_nullable: false },
          { name: "is_active", data_type: "boolean", is_nullable: false },
          { name: "score", data_type: "float", is_nullable: true },
        ],
      },
      orders: {
        columns: [
          { name: "id", data_type: "integer", is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false },
          { name: "total", data_type: "decimal", is_nullable: false },
        ],
      },
    },
    foreign_keys: [
      { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
    ],
  };

  it("generates sqlalchemy declarative models", () => {
    const out = toSqlAlchemy(schema);
    expect(out).toContain("from __future__ import annotations");
    expect(out).toContain("from sqlalchemy.orm import declarative_base, relationship");
    expect(out).toContain("Base = declarative_base()");
    expect(out).toContain("class Users(Base):");
    expect(out).toContain('"""User accounts table"""');
    expect(out).toContain('__tablename__ = "users"');
    expect(out).toContain("id = Column(Integer, primary_key=True, nullable=False)");
    expect(out).toContain("username = Column(Text, primary_key=False, nullable=False)");
    expect(out).toContain("is_active = Column(Boolean, primary_key=False, nullable=False)");
    expect(out).toContain("score = Column(Float, primary_key=False, nullable=True)");

    expect(out).toContain("class Orders(Base):");
    expect(out).toContain('user_id = Column(Integer, ForeignKey("users.id"), primary_key=False, nullable=False)');
    expect(out).toContain('user = relationship("Users", foreign_keys=[user_id])');
  });

  it("supports alias export toSqlAlchemyModels", () => {
    expect(toSqlAlchemyModels).toBe(toSqlAlchemy);
  });

  it("handles table with no columns", () => {
    const emptyTableSchema = {
      tables: {
        empty_table: {
          columns: [],
        },
      },
    };
    const out = toSqlAlchemy(emptyTableSchema);
    expect(out).toContain("class EmptyTable(Base):");
    expect(out).toContain("pass");
  });

  it("handles empty schema", () => {
    const out = toSqlAlchemy({});
    expect(out).toContain("Base = declarative_base()");
    expect(out).not.toContain("class ");
  });
});

describe("Bidirectional Adapter Interoperability", () => {
  it("converts Prisma schema to TableSchema and back to Prisma", () => {
    const initialPrisma = `
model Customer {
  id    Int     @id @default(autoincrement())
  email String  @unique
  name  String?

  @@map("customers")
}
`;
    const tables = fromPrisma(initialPrisma);
    expect(tables).toHaveLength(1);
    expect(tables[0].name).toBe("customers");

    const exported = toPrisma(tables);
    expect(exported).toContain("model Customers {");
    expect(exported).toContain("id Int @id @default(autoincrement())");
    expect(exported).toContain("email String");
    expect(exported).toContain("name String?");
    expect(exported).toContain('@@map("customers")');
  });

  it("converts Drizzle schema to TableSchema and back to Drizzle", () => {
    const initialDrizzle = `
import { pgTable, serial, text } from "drizzle-orm/pg-core";

export const customers = pgTable("customers", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
});
`;
    const tables = fromDrizzle(initialDrizzle);
    expect(tables).toHaveLength(1);

    const exported = toDrizzle(tables, "postgres");
    expect(exported).toContain('export const customers = pgTable("customers", {');
    expect(exported).toContain('id: serial("id").primaryKey(),');
    expect(exported).toContain('name: text("name").notNull(),');
  });

  it("converts SQLAlchemy models to TableSchema and back to SQLAlchemy", () => {
    const initialPy = `
class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
`;
    const tables = fromSqlAlchemy(initialPy);
    expect(tables).toHaveLength(1);

    const exported = toSqlAlchemy(tables);
    expect(exported).toContain("class Customers(Base):");
    expect(exported).toContain('__tablename__ = "customers"');
    expect(exported).toContain("id = Column(Integer, primary_key=True");
    expect(exported).toContain("name = Column(Text, primary_key=False, nullable=False)");
  });
});

describe("Robustness Edge Cases in Exporters", () => {
  it("handles composite primary keys in toPrisma", () => {
    const schema = {
      tables: {
        order_items: {
          columns: [
            { name: "order_id", data_type: "integer", is_primary: true },
            { name: "product_id", data_type: "integer", is_primary: true },
            { name: "quantity", data_type: "integer", is_nullable: false },
          ],
        },
      },
    };
    const out = toPrisma(schema);
    // Fields should not have individual @id or autoincrement
    expect(out).toContain('orderId Int @map("order_id")');
    expect(out).toContain('productId Int @map("product_id")');
    expect(out).not.toContain("orderId Int @id");
    expect(out).not.toContain("productId Int @id");
    // Model-level composite @@id
    expect(out).toContain("@@id([orderId, productId])");
    expect(out).toContain('@@map("order_items")');
  });

  it("handles self-referential relations with relation tags in toPrisma", () => {
    const schema = {
      tables: {
        categories: {
          columns: [
            { name: "id", data_type: "integer", is_primary: true },
            { name: "name", data_type: "text", is_nullable: false },
            { name: "parent_id", data_type: "integer", is_nullable: true },
          ],
        },
      },
      foreign_keys: [
        { table: "categories", column: "parent_id", foreign_table: "categories", foreign_column: "id" },
      ],
    };
    const out = toPrisma(schema);
    // Forward relation has explicit relation name tag
    expect(out).toContain('parent Categories? @relation("Categories_parentId", fields: [parentId], references: [id])');
    // Back-relation has matching tag and descriptive child field name
    expect(out).toContain('childCategoriesByParentId Categories[] @relation("Categories_parentId")');
  });

  it("handles composite primary keys in toDrizzle across dialects", () => {
    const schema = {
      tables: {
        role_permissions: {
          columns: [
            { name: "role_id", data_type: "integer", is_primary: true },
            { name: "perm_id", data_type: "integer", is_primary: true },
            { name: "granted", data_type: "boolean", is_nullable: false },
          ],
        },
      },
    };

    // Postgres
    const pgOut = toDrizzle(schema, "postgres");
    expect(pgOut).toContain("primaryKey({ columns: [table.roleId, table.permId] })");
    expect(pgOut).not.toContain(".primaryKey()");

    // MySQL
    const myOut = toDrizzle(schema, "mysql");
    expect(myOut).toContain("primaryKey({ columns: [table.roleId, table.permId] })");
    expect(myOut).not.toContain(".primaryKey()");

    // SQLite
    const sqOut = toDrizzle(schema, "sqlite");
    expect(sqOut).toContain("primaryKey({ columns: [table.roleId, table.permId] })");
    expect(sqOut).not.toContain(".primaryKey()");
  });

  it("safely ignores missing target tables for foreign keys in toDrizzle", () => {
    const schema = {
      tables: {
        items: {
          columns: [
            { name: "id", data_type: "integer", is_primary: true },
            { name: "external_id", data_type: "integer", is_nullable: true },
          ],
        },
      },
      foreign_keys: [
        { table: "items", column: "external_id", foreign_table: "external_service_table", foreign_column: "id" },
      ],
    };
    const out = toDrizzle(schema, "postgres");
    expect(out).toContain('externalId: integer("external_id"),');
    expect(out).not.toContain(".references(");
  });

  it("sanitizes Python keywords and preserves external FKs in toSqlAlchemy", () => {
    const schema = {
      tables: {
        events: {
          columns: [
            { name: "id", data_type: "integer", is_primary: true },
            { name: "from", data_type: "text", is_nullable: false },
            { name: "class", data_type: "text", is_nullable: true },
            { name: "remote_id", data_type: "integer", is_nullable: false },
          ],
        },
      },
      foreign_keys: [
        { table: "events", column: "remote_id", foreign_table: "remote_users", foreign_column: "id" },
      ],
    };
    const out = toSqlAlchemy(schema);
    // Python keyword fields should be suffixed with _ and have explicit column name
    expect(out).toContain('from_ = Column("from", Text, primary_key=False, nullable=False)');
    expect(out).toContain('class_ = Column("class", Text, primary_key=False, nullable=True)');
    // External FK column keeps ForeignKey directive
    expect(out).toContain('remote_id = Column(Integer, ForeignKey("remote_users.id"), primary_key=False, nullable=False)');
    // But does NOT generate a relationship to remote_users because it is missing from snapshot
    expect(out).not.toContain("relationship(");
  });
});


