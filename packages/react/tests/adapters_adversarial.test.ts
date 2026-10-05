import { describe, it, expect } from "vitest";
import {
  fromPrisma,
  fromDrizzle,
  fromSqlAlchemy,
  fromJsonSchema,
  toSchemaSnapshot,
} from "../src/adapters";
import { findBestJoinCondition, findJoinPath } from "../src/utils/joinUtils";
import { normalizeSchema } from "../src/utils/schemaUtils";

// ============================================================================
// 1. EMPTY & MALFORMED INPUTS
// ============================================================================

describe("Empty and Malformed Inputs across TS Adapters", () => {
  it("handles empty strings and empty objects gracefully", () => {
    expect(fromPrisma("")).toEqual([]);
    expect(fromDrizzle("")).toEqual([]);
    expect(fromSqlAlchemy("")).toEqual([]);
    expect(fromJsonSchema({})).toEqual([]);
    expect(fromPrisma({})).toEqual([]);
    expect(fromDrizzle({})).toEqual([]);
  });

  it("handles whitespace and non-schema strings cleanly", () => {
    expect(fromPrisma("   \n\t  ")).toEqual([]);
    expect(fromDrizzle("   \n\t  ")).toEqual([]);
    expect(fromSqlAlchemy("   \n\t  ")).toEqual([]);
    expect(fromPrisma("some random text with no models")).toEqual([]);
    expect(fromDrizzle("console.log('hello world'); const x = 1;")).toEqual([]);
    expect(fromSqlAlchemy("def foo(): return 42")).toEqual([]);
  });

  it("handles truncated models cleanly without throwing", () => {
    expect(fromPrisma("model Truncated { id Int @id")).toEqual([]);
    expect(fromDrizzle("export const t = pgTable('t', {")).toEqual([]);
  });
});

// ============================================================================
// 2. CIRCULAR FOREIGN KEYS (A <-> B)
// ============================================================================

const CIRCULAR_PRISMA = `
model Department {
  id        Int       @id
  managerId Int?
  manager   Employee? @relation("DeptManager", fields: [managerId], references: [id])
  employees Employee[] @relation("DeptEmployees")
  @@map("departments")
}

model Employee {
  id           Int         @id
  departmentId Int?
  department   Department? @relation("DeptEmployees", fields: [departmentId], references: [id])
  deptManaged  Department[] @relation("DeptManager")
  @@map("employees")
}
`;

const CIRCULAR_DRIZZLE = `
import { pgTable, serial, integer } from 'drizzle-orm/pg-core';

export const departments = pgTable('departments', {
  id: serial('id').primaryKey(),
  managerId: integer('manager_id').references(() => employees.id),
});

export const employees = pgTable('employees', {
  id: serial('id').primaryKey(),
  departmentId: integer('department_id').references(() => departments.id),
});
`;

const CIRCULAR_SQLALCHEMY = `
class Department(Base):
    __tablename__ = 'departments'
    id = Column(Integer, primary_key=True)
    manager_id = Column(Integer, ForeignKey('employees.id'), nullable=True)

class Employee(Base):
    __tablename__ = 'employees'
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey('departments.id'), nullable=True)
`;

const CIRCULAR_JSON_SCHEMA = {
  departments: {
    type: "object",
    required: ["id"],
    properties: {
      id: { type: "integer", "x-primary-key": true },
      manager_id: { type: "integer", "x-foreign-key": "employees.id" },
    },
  },
  employees: {
    type: "object",
    required: ["id"],
    properties: {
      id: { type: "integer", "x-primary-key": true },
      department_id: { type: "integer", "x-foreign-key": "departments.id" },
    },
  },
};

describe("Circular Foreign Keys across all TS Adapters", () => {
  const cases = [
    { name: "Prisma", fn: () => fromPrisma(CIRCULAR_PRISMA) },
    { name: "Drizzle", fn: () => fromDrizzle(CIRCULAR_DRIZZLE) },
    { name: "SQLAlchemy", fn: () => fromSqlAlchemy(CIRCULAR_SQLALCHEMY) },
    { name: "JSON Schema", fn: () => fromJsonSchema(CIRCULAR_JSON_SCHEMA) },
  ];

  for (const c of cases) {
    it(`parses circular FKs bidirectional and pathfinds safely for ${c.name}`, () => {
      const tables = c.fn();
      expect(tables.map((t) => t.name).sort()).toEqual(["departments", "employees"]);

      const snapshot = toSchemaSnapshot(tables);
      expect(snapshot.foreign_keys.length).toBe(2);

      const normalized = normalizeSchema(tables);
      expect(normalized).not.toBeNull();
      expect(normalized!.foreign_keys.length).toBe(2);

      // Verify pathfinding terminates and doesn't cycle infinitely
      const path = findJoinPath(["departments"], "employees", normalized);
      expect(path).toHaveLength(1);
      expect(["departments", "employees"]).toContain(path[0].left_table);
      expect(["departments", "employees"]).toContain(path[0].table);

      const cond = findBestJoinCondition("departments", "employees", normalized);
      expect(cond.isFk).toBe(true);
    });
  }
});

// ============================================================================
// 3. SELF-REFERENCING FOREIGN KEYS
// ============================================================================

const SELF_REF_PRISMA = `
model Employee {
  id        Int        @id
  name      String
  managerId Int?
  manager   Employee?  @relation("ReportsTo", fields: [managerId], references: [id])
  reports   Employee[] @relation("ReportsTo")
  @@map("employees")
}
`;

const SELF_REF_DRIZZLE = `
import { pgTable, serial, integer, text } from 'drizzle-orm/pg-core';

export const employees = pgTable('employees', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  managerId: integer('manager_id').references(() => employees.id),
});
`;

const SELF_REF_SQLALCHEMY = `
class Employee(Base):
    __tablename__ = 'employees'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    manager_id = Column(Integer, ForeignKey('employees.id'), nullable=True)
`;

const SELF_REF_JSON_SCHEMA = {
  employees: {
    type: "object",
    required: ["id", "name"],
    properties: {
      id: { type: "integer", "x-primary-key": true },
      name: { type: "string" },
      manager_id: { type: "integer", "x-foreign-key": "employees.id" },
    },
  },
};

describe("Self-Referencing Foreign Keys across TS Adapters", () => {
  const cases = [
    { name: "Prisma", fn: () => fromPrisma(SELF_REF_PRISMA) },
    { name: "Drizzle", fn: () => fromDrizzle(SELF_REF_DRIZZLE) },
    { name: "SQLAlchemy", fn: () => fromSqlAlchemy(SELF_REF_SQLALCHEMY) },
    { name: "JSON Schema", fn: () => fromJsonSchema(SELF_REF_JSON_SCHEMA) },
  ];

  for (const c of cases) {
    it(`records self-referencing foreign keys cleanly for ${c.name}`, () => {
      const tables = c.fn();
      const emp = tables.find((t) => t.name === "employees");
      expect(emp).toBeDefined();

      const fks = emp!.foreignKeys || emp!.foreign_keys || [];
      expect(fks.length).toBe(1);
      const fk = fks[0];
      const fTable = fk.foreignTable || fk.foreign_table;
      const fCol = fk.foreignColumn || fk.foreign_column;
      expect(fTable).toBe("employees");
      expect(fCol).toBe("id");
    });
  }
});

// ============================================================================
// 4. COMPOSITE PRIMARY KEYS
// ============================================================================

const COMPOSITE_PRISMA = `
model Membership {
  tenantId String
  orgId    String
  userId   String
  role     String
  @@id([tenantId, orgId, userId])
  @@map("memberships")
}
`;

const COMPOSITE_DRIZZLE = `
import { pgTable, text, primaryKey } from 'drizzle-orm/pg-core';

export const memberships = pgTable('memberships', {
  tenantId: text('tenant_id').notNull(),
  orgId: text('org_id').notNull(),
  userId: text('user_id').notNull(),
  role: text('role').notNull(),
}, (table) => ({
  pk: primaryKey({ columns: [table.tenantId, table.orgId, table.userId] }),
}));
`;

const COMPOSITE_SQLALCHEMY = `
class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (PrimaryKeyConstraint('tenant_id', 'org_id', 'user_id'),)
    tenant_id = Column(String, primary_key=True)
    org_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    role = Column(String, nullable=False)
`;

const COMPOSITE_JSON_SCHEMA = {
  memberships: {
    type: "object",
    "x-primary-keys": ["tenant_id", "org_id", "user_id"],
    required: ["tenant_id", "org_id", "user_id"],
    properties: {
      tenant_id: { type: "string" },
      org_id: { type: "string" },
      user_id: { type: "string" },
      role: { type: "string" },
    },
  },
};

describe("Composite Primary Keys across TS Adapters", () => {
  const cases = [
    {
      name: "Prisma",
      fn: () => fromPrisma(COMPOSITE_PRISMA),
      expectedCols: ["tenantId", "orgId", "userId"],
    },
    {
      name: "Drizzle",
      fn: () => fromDrizzle(COMPOSITE_DRIZZLE),
      expectedCols: ["tenant_id", "org_id", "user_id"],
    },
    {
      name: "SQLAlchemy",
      fn: () => fromSqlAlchemy(COMPOSITE_SQLALCHEMY),
      expectedCols: ["tenant_id", "org_id", "user_id"],
    },
    {
      name: "JSON Schema",
      fn: () => fromJsonSchema(COMPOSITE_JSON_SCHEMA),
      expectedCols: ["tenant_id", "org_id", "user_id"],
    },
  ];

  for (const c of cases) {
    it(`identifies 3-column composite PKs for ${c.name}`, () => {
      const tables = c.fn();
      const tbl = tables.find((t) => t.name === "memberships")!;
      const pks = tbl.primaryKeys || tbl.primary_keys || [];
      expect([...pks].sort()).toEqual([...c.expectedCols].sort());

      const pkCols = tbl.columns
        .filter((col) => col.isPrimary || col.is_primary)
        .map((col) => col.name);
      expect([...pkCols].sort()).toEqual([...c.expectedCols].sort());
    });
  }
});

// ============================================================================
// 5. ENUMS, NULLABLE TYPES & DEFAULTS
// ============================================================================

const ENUM_PRISMA = `
enum Status {
  draft
  published
  archived
}

model Article {
  id        Int      @id @default(autoincrement())
  title     String
  subtitle  String?
  status    Status   @default(draft)
  views     Int      @default(0)
  isPinned  Boolean  @default(false)
  @@map("articles")
}
`;

const ENUM_DRIZZLE = `
import { pgTable, serial, text, integer, boolean, pgEnum } from 'drizzle-orm/pg-core';

export const statusEnum = pgEnum('status', ['draft', 'published', 'archived']);

export const articles = pgTable('articles', {
  id: serial('id').primaryKey(),
  title: text('title').notNull(),
  subtitle: text('subtitle'),
  status: statusEnum('status').default('draft'),
  views: integer('views').default(0),
  isPinned: boolean('is_pinned').default(false),
});
`;

const ENUM_SQLALCHEMY = `
class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    subtitle = Column(String, nullable=True)
    status = Column(Enum('draft', 'published', 'archived', name='status_enum'), default='draft')
    views = Column(Integer, default=0)
    is_pinned = Column(Boolean, default=False)
`;

const ENUM_JSON_SCHEMA = {
  articles: {
    type: "object",
    required: ["id", "title"],
    properties: {
      id: { type: "integer", "x-primary-key": true },
      title: { type: "string" },
      subtitle: { type: ["string", "null"] },
      status: {
        type: "string",
        enum: ["draft", "published", "archived"],
        default: "draft",
      },
      views: { type: "integer", default: 0 },
      is_pinned: { type: "boolean", default: false },
    },
  },
};

describe("Enums, Nullables, and Defaults across TS Adapters", () => {
  const cases = [
    { name: "Prisma", fn: () => fromPrisma(ENUM_PRISMA) },
    { name: "Drizzle", fn: () => fromDrizzle(ENUM_DRIZZLE) },
    { name: "SQLAlchemy", fn: () => fromSqlAlchemy(ENUM_SQLALCHEMY) },
    { name: "JSON Schema", fn: () => fromJsonSchema(ENUM_JSON_SCHEMA) },
  ];

  for (const c of cases) {
    it(`parses enums, nullability, and defaults for ${c.name}`, () => {
      const tables = c.fn();
      const art = tables.find((t) => t.name === "articles")!;
      const colMap = new Map(art.columns.map((col) => [col.name, col]));

      const titleCol = colMap.get("title")!;
      const isTitleNullable =
        titleCol.isNullable !== undefined ? titleCol.isNullable : titleCol.is_nullable;
      expect(isTitleNullable).toBe(false);

      const subtitleCol = colMap.get("subtitle")!;
      const isSubNullable =
        subtitleCol.isNullable !== undefined
          ? subtitleCol.isNullable
          : subtitleCol.is_nullable;
      expect(isSubNullable).toBe(true);

      const statusCol = colMap.get("status")!;
      expect(statusCol.enums).toEqual(["draft", "published", "archived"]);

      const viewsCol = colMap.get("views")!;
      expect(viewsCol.default === 0 || viewsCol.default === "0").toBe(true);
    });
  }
});

// ============================================================================
// 6. MULTI-HOP PATHFINDING & NORMALIZE_SCHEMA INTEGRATION
// ============================================================================

const MULTI_HOP_DRIZZLE = `
import { pgTable, serial, integer, text } from 'drizzle-orm/pg-core';

export const organizations = pgTable('organizations', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
});

export const departments = pgTable('departments', {
  id: serial('id').primaryKey(),
  orgId: integer('org_id').references(() => organizations.id).notNull(),
  name: text('name').notNull(),
});

export const employees = pgTable('employees', {
  id: serial('id').primaryKey(),
  deptId: integer('department_id').references(() => departments.id).notNull(),
  name: text('name').notNull(),
});

export const tasks = pgTable('tasks', {
  id: serial('id').primaryKey(),
  assigneeId: integer('assignee_id').references(() => employees.id).notNull(),
  title: text('title').notNull(),
  status: text('status').notNull(),
});
`;

describe("Multi-hop Pathfinding and Normalization in React", () => {
  it("resolves multi-hop join path through 4 tables from adapted schema", () => {
    const tables = fromDrizzle(MULTI_HOP_DRIZZLE);
    const normalized = normalizeSchema(tables);

    expect(normalized).not.toBeNull();
    expect(Object.keys(normalized!.tables)).toHaveLength(4);
    expect(normalized!.foreign_keys).toHaveLength(3);

    // Path from organizations to tasks: organizations -> departments -> employees -> tasks
    const path = findJoinPath(["organizations"], "tasks", normalized);
    expect(path).toHaveLength(3);

    // Sequential join chain verification
    const joinedTables = path.map((j) => j.table);
    expect(joinedTables).toContain("departments");
    expect(joinedTables).toContain("employees");
    expect(joinedTables).toContain("tasks");
  });
});
