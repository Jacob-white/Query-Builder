"""
Adversarial Stress Test Suite for Schema Adapters.
=================================================
Stress-tests all 4 ORM adapters (Prisma, Drizzle, SQLAlchemy, JSON Schema)
against adversarial edge cases:
- Circular foreign keys (A <-> B)
- Self-referencing foreign keys (employees.manager_id -> employees.id)
- Multi-column composite primary keys ([tenant_id, org_id, user_id])
- Enums, nullable fields, and diverse default values
- Empty, whitespace, malformed, and truncated inputs
- QueryCompiler multi-hop join queries across multiple SQL dialects
- JoinSolver cyclic graph traversal and shortest-path discovery
"""

from __future__ import annotations

import pytest

from query_builder.adapters import (
    from_drizzle,
    from_json_schema,
    from_prisma,
    from_sqlalchemy,
)
from query_builder.compiler import QueryCompiler
from query_builder.join_solver import find_best_join_condition, find_join_path
from query_builder.models import QuerySpec

# ============================================================================
# 1. EMPTY, MALFORMED & DEGRADED INPUTS
# ============================================================================


class TestEmptyAndMalformedInputs:
    """Tests adapter resilience when given empty, whitespace, or malformed inputs."""

    @pytest.mark.parametrize("empty_input", ["", "   \n\t   ", "\n\n"])
    def test_empty_string_inputs(self, empty_input):
        assert len(from_prisma(empty_input)) == 0
        assert len(from_drizzle(empty_input)) == 0
        assert len(from_sqlalchemy(empty_input)) == 0

    def test_empty_dict_inputs(self):
        assert len(from_prisma({})) == 0
        assert len(from_drizzle({})) == 0
        assert len(from_json_schema({})) == 0

    def test_malformed_syntax_graceful_handling(self):
        # Non-model syntax or garbage returns empty tables
        non_model_drizzle = "console.log('hello'); const a = 123;"
        assert len(from_prisma("some text with no models")) == 0
        assert len(from_drizzle(non_model_drizzle)) == 0

        # Non-model valid Python code returns empty
        assert len(from_sqlalchemy("x = 42\ndef helper(): pass")) == 0

        # Malformed Python syntax raises standard SyntaxError
        with pytest.raises(SyntaxError):
            from_sqlalchemy("class Broken Python Syntax %^&*")

        # JSON schema with invalid JSON string degrades gracefully to empty/main schema
        json_res = from_json_schema("{broken json syntax")
        assert "main" in json_res
        assert len(json_res["main"].columns) == 0

    def test_truncated_prisma_and_drizzle_models(self):
        # Truncated prisma model missing closing brace
        assert len(from_prisma("model Incomplete { id Int @id")) == 0

        # Truncated drizzle definition
        assert len(from_drizzle("export const t = pgTable('t', {")) == 0


# ============================================================================
# 2. CIRCULAR FOREIGN KEYS (A <-> B)
# ============================================================================

CIRCULAR_PRISMA = """
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
"""

CIRCULAR_DRIZZLE = """
import { pgTable, serial, integer } from 'drizzle-orm/pg-core';

export const departments = pgTable('departments', {
  id: serial('id').primaryKey(),
  managerId: integer('manager_id').references(() => employees.id),
});

export const employees = pgTable('employees', {
  id: serial('id').primaryKey(),
  departmentId: integer('department_id').references(() => departments.id),
});
"""

CIRCULAR_SQLALCHEMY = """
class Department(Base):
    __tablename__ = 'departments'
    id = Column(Integer, primary_key=True)
    manager_id = Column(Integer, ForeignKey('employees.id'), nullable=True)

class Employee(Base):
    __tablename__ = 'employees'
    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey('departments.id'), nullable=True)
"""

CIRCULAR_JSON_SCHEMA = {
    "departments": {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer", "x-primary-key": True},
            "manager_id": {"type": "integer", "x-foreign-key": "employees.id"},
        },
    },
    "employees": {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer", "x-primary-key": True},
            "department_id": {"type": "integer", "x-foreign-key": "departments.id"},
        },
    },
}


class TestCircularForeignKeys:
    """Verifies that circular foreign keys parse both directions and traverse cleanly."""

    @pytest.mark.parametrize(
        ("adapter_fn", "source"),
        [
            (from_prisma, CIRCULAR_PRISMA),
            (from_drizzle, CIRCULAR_DRIZZLE),
            (from_sqlalchemy, CIRCULAR_SQLALCHEMY),
            (from_json_schema, CIRCULAR_JSON_SCHEMA),
        ],
    )
    def test_circular_fks_bidirectional(self, adapter_fn, source):
        tables = adapter_fn(source)
        assert "departments" in tables
        assert "employees" in tables

        snapshot = tables.to_snapshot()
        fks = [
            (fk["table"], fk["column"], fk["foreign_table"], fk["foreign_column"])
            for fk in snapshot.foreign_keys
        ]
        assert len(fks) == 2

        # Check pathfinding does not enter infinite recursion
        path = find_join_path(["departments"], "employees", snapshot)
        assert len(path) == 1
        assert path[0]["left_table"] in ("departments", "employees")

        cond = find_best_join_condition("departments", "employees", snapshot)
        assert cond["is_fk"] is True


# ============================================================================
# 3. SELF-REFERENCING FOREIGN KEYS
# ============================================================================

SELF_REF_PRISMA = """
model Employee {
  id        Int        @id
  name      String
  managerId Int?
  manager   Employee?  @relation("ReportsTo", fields: [managerId], references: [id])
  reports   Employee[] @relation("ReportsTo")
  @@map("employees")
}
"""

SELF_REF_DRIZZLE = """
import { pgTable, serial, integer, text } from 'drizzle-orm/pg-core';

export const employees = pgTable('employees', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  managerId: integer('manager_id').references(() => employees.id),
});
"""

SELF_REF_SQLALCHEMY = """
class Employee(Base):
    __tablename__ = 'employees'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    manager_id = Column(Integer, ForeignKey('employees.id'), nullable=True)
"""

SELF_REF_JSON_SCHEMA = {
    "employees": {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "integer", "x-primary-key": True},
            "name": {"type": "string"},
            "manager_id": {"type": "integer", "x-foreign-key": "employees.id"},
        },
    }
}


class TestSelfReferencingForeignKeys:
    """Verifies that self-referencing foreign keys (e.g. hierarchical trees) are captured correctly."""

    @pytest.mark.parametrize(
        ("adapter_fn", "source"),
        [
            (from_prisma, SELF_REF_PRISMA),
            (from_drizzle, SELF_REF_DRIZZLE),
            (from_sqlalchemy, SELF_REF_SQLALCHEMY),
            (from_json_schema, SELF_REF_JSON_SCHEMA),
        ],
    )
    def test_self_referencing_fk_detection(self, adapter_fn, source):
        tables = adapter_fn(source)
        emp_table = tables["employees"]
        assert len(emp_table.foreign_keys) == 1
        fk = emp_table.foreign_keys[0]
        assert fk.table == "employees"
        assert fk.foreign_table == "employees"
        assert fk.foreign_column == "id"


# ============================================================================
# 4. COMPOSITE PRIMARY KEYS
# ============================================================================

COMPOSITE_PRISMA = """
model Membership {
  tenantId String
  orgId    String
  userId   String
  role     String
  @@id([tenantId, orgId, userId])
  @@map("memberships")
}
"""

COMPOSITE_DRIZZLE = """
import { pgTable, text, primaryKey } from 'drizzle-orm/pg-core';

export const memberships = pgTable('memberships', {
  tenantId: text('tenant_id').notNull(),
  orgId: text('org_id').notNull(),
  userId: text('user_id').notNull(),
  role: text('role').notNull(),
}, (table) => ({
  pk: primaryKey({ columns: [table.tenantId, table.orgId, table.userId] }),
}));
"""

COMPOSITE_SQLALCHEMY = """
class Membership(Base):
    __tablename__ = 'memberships'
    __table_args__ = (PrimaryKeyConstraint('tenant_id', 'org_id', 'user_id'),)
    tenant_id = Column(String, primary_key=True)
    org_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    role = Column(String, nullable=False)
"""

COMPOSITE_JSON_SCHEMA = {
    "memberships": {
        "type": "object",
        "x-primary-keys": ["tenant_id", "org_id", "user_id"],
        "required": ["tenant_id", "org_id", "user_id"],
        "properties": {
            "tenant_id": {"type": "string"},
            "org_id": {"type": "string"},
            "user_id": {"type": "string"},
            "role": {"type": "string"},
        },
    }
}


class TestCompositePrimaryKeys:
    """Verifies that multi-column composite primary keys are identified across all columns."""

    @pytest.mark.parametrize(
        ("adapter_fn", "source", "expected_cols"),
        [
            (from_prisma, COMPOSITE_PRISMA, {"tenantId", "orgId", "userId"}),
            (
                from_drizzle,
                COMPOSITE_DRIZZLE,
                {"tenant_id", "org_id", "user_id"},
            ),
            (from_sqlalchemy, COMPOSITE_SQLALCHEMY, {"tenant_id", "org_id", "user_id"}),
            (
                from_json_schema,
                COMPOSITE_JSON_SCHEMA,
                {"tenant_id", "org_id", "user_id"},
            ),
        ],
    )
    def test_three_column_composite_pk(self, adapter_fn, source, expected_cols):
        tables = adapter_fn(source)
        tbl = tables["memberships"]
        assert set(tbl.primary_keys) == expected_cols
        pk_cols = {c.name for c in tbl.columns if c.is_primary}
        assert pk_cols == expected_cols


# ============================================================================
# 5. ENUMS, NULLABLE TYPES & DEFAULTS
# ============================================================================

ENUM_PRISMA = """
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
"""

ENUM_DRIZZLE = """
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
"""

ENUM_SQLALCHEMY = """
class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    subtitle = Column(String, nullable=True)
    status = Column(Enum('draft', 'published', 'archived', name='status_enum'), default='draft')
    views = Column(Integer, default=0)
    is_pinned = Column(Boolean, default=False)
"""

ENUM_JSON_SCHEMA = {
    "articles": {
        "type": "object",
        "required": ["id", "title"],
        "properties": {
            "id": {"type": "integer", "x-primary-key": True},
            "title": {"type": "string"},
            "subtitle": {"type": ["string", "null"]},
            "status": {
                "type": "string",
                "enum": ["draft", "published", "archived"],
                "default": "draft",
            },
            "views": {"type": "integer", "default": 0},
            "is_pinned": {"type": "boolean", "default": False},
        },
    }
}


class TestEnumsNullablesAndDefaults:
    """Verifies that enums, nullability rules, and column defaults parse reliably."""

    @pytest.mark.parametrize(
        ("adapter_fn", "source"),
        [
            (from_prisma, ENUM_PRISMA),
            (from_drizzle, ENUM_DRIZZLE),
            (from_sqlalchemy, ENUM_SQLALCHEMY),
            (from_json_schema, ENUM_JSON_SCHEMA),
        ],
    )
    def test_enums_nullables_and_defaults(self, adapter_fn, source):
        tables = adapter_fn(source)
        tbl = tables["articles"]
        cols = {c.name: c for c in tbl.columns}

        # Nullability
        assert cols["title"].is_nullable is False
        assert cols["subtitle"].is_nullable is True

        # Enums
        status_col = cols["status"]
        assert status_col.enums == ["draft", "published", "archived"]

        # Defaults
        assert status_col.default in ("draft", "'draft'")
        assert cols["views"].default in (0, "0")


# ============================================================================
# 6. QUERYCOMPILER MULTI-HOP JOIN COMPILATION
# ============================================================================

MULTI_HOP_DRIZZLE = """
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
"""


class TestQueryCompilerIntegration:
    """Verifies that adapted schemas directly feed into QueryCompiler for multi-hop joins."""

    def test_multi_hop_query_compilation_across_dialects(self):
        tables = from_drizzle(MULTI_HOP_DRIZZLE)
        snapshot = tables.to_snapshot()

        spec = QuerySpec(
            table="organizations",
            columns=[
                "organizations.name",
                "departments.name",
                "employees.name",
                "tasks.title",
            ],
            joins=[
                {
                    "table": "departments",
                    "type": "INNER",
                    "on": [{"left": "organizations.id", "right": "departments.org_id"}],
                },
                {
                    "table": "employees",
                    "type": "INNER",
                    "on": [
                        {
                            "left": "departments.id",
                            "right": "employees.department_id",
                        }
                    ],
                },
                {
                    "table": "tasks",
                    "type": "LEFT",
                    "on": [{"left": "employees.id", "right": "tasks.assignee_id"}],
                },
            ],
            filters=[
                {"column": "tasks.status", "op": "eq", "value": "done"},
                {"column": "organizations.id", "op": "gt", "value": 10},
            ],
        )

        for dialect in ["postgres", "mysql", "sqlite", "snowflake"]:
            compiler = QueryCompiler(spec, schema=snapshot, dialect=dialect)
            sql, params, _, _ = compiler.compile()
            assert "SELECT" in sql
            assert "departments" in sql
            assert "employees" in sql
            assert "tasks" in sql
            assert "JOIN" in sql
            assert "done" in params or "%s" in sql or "?" in sql
