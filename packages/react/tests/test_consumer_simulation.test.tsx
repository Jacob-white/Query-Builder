import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { createRequire } from "module";

import {
  VisualQueryBuilder,
  QueryBuilderProvider,
  TableCard,
  TableFiltersEditor,
  QueryResultsTable,
  compileVisualState,
  useQueryBuilder,
  useQueryState,
  useSqlCompiler,
  useQueryExecution,
  useSchemaIntrospection,
  type SchemaSnapshot,
  type VisualFilter,
  type TableMeta,
  type QueryResultData,
} from "../src";

import {
  fromPrisma,
  fromDrizzle,
  fromSqlAlchemy,
  fromJsonSchema,
  toSchemaSnapshot,
} from "../src/adapters";

const sampleSchema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
  },
  relationships: [
    {
      source_table: "orders",
      source_column: "user_id",
      target_table: "users",
      target_column: "id",
    },
  ],
};

describe("Milestone 5 Consumer Simulation: @jacob-white/query-builder-react", () => {
  // 1. Dual dist bundle exports parity (ESM & CJS)
  it("verifies dual dist bundle exports parity between ESM and CJS", async () => {
    const require = createRequire(import.meta.url);
    const cjsModule = require("../dist/index.cjs");
    const esmModule = await import("../dist/index.mjs");

    const criticalSymbols = [
      "VisualQueryBuilder",
      "QueryBuilderProvider",
      "useQueryBuilder",
      "useQueryState",
      "useSqlCompiler",
      "useQueryExecution",
      "useSchemaIntrospection",
      "fromPrisma",
      "fromDrizzle",
      "fromSqlAlchemy",
      "fromJsonSchema",
      "toSchemaSnapshot",
      "darkTheme",
      "lightTheme",
      "compileVisualState",
      "validateSqlSafety",
    ];

    for (const sym of criticalSymbols) {
      expect(esmModule[sym], `ESM bundle missing ${sym}`).toBeDefined();
      expect(cjsModule[sym], `CJS bundle missing ${sym}`).toBeDefined();
      expect(typeof esmModule[sym]).toBe(typeof cjsModule[sym]);
    }

    const esmKeys = Object.keys(esmModule).filter((k) => k !== "default");
    const cjsKeys = Object.keys(cjsModule).filter(
      (k) => k !== "default" && k !== "__esModule",
    );
    expect(esmKeys.length).toBeGreaterThanOrEqual(50);
    expect(cjsKeys.length).toBeGreaterThanOrEqual(50);
  });

  // 2. VisualQueryBuilder in styled mode with custom ThemeProvider tokens and scoped CSS vars
  it("renders VisualQueryBuilder in styled mode with custom ThemeProvider tokens and scoped CSS variables", () => {
    const customTheme = {
      colors: {
        primary: "#10b981",
        background: "#0f172a",
      },
    };

    const { container } = render(
      <QueryBuilderProvider mode="styled" theme={customTheme}>
        <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
      </QueryBuilderProvider>,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBeNull();

    const styleAttr = root?.getAttribute("style") ?? "";
    expect(styleAttr).toContain("--qb-color-primary");
    expect(styleAttr).toContain("#10b981");
  });

  // 3. VisualQueryBuilder in zero-CSS unstyled mode
  it("renders VisualQueryBuilder in zero-CSS unstyled mode", () => {
    const { container } = render(
      <QueryBuilderProvider mode="unstyled">
        <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
      </QueryBuilderProvider>,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
    expect(root?.getAttribute("style")).toBeNull();

    const topBar = container.querySelector('[data-qb="top-bar"]');
    expect(topBar).not.toBeNull();
    expect(topBar?.getAttribute("style")).toBeNull();
  });

  // 4. Custom filter operators with unary and binary handling
  it("integrates custom filter operators with unary and binary handling", () => {
    const filters: VisualFilter[] = [
      {
        id: "f1",
        column: "email",
        operator: "IS_EMPTY",
        value: "",
      },
    ];
    const onChange = vi.fn();
    const activeTables: TableMeta[] = [sampleSchema.tables.users];

    const { rerender } = render(
      <TableFiltersEditor
        filters={filters}
        activeTables={activeTables}
        onChange={onChange}
        customOperators={{
          REGEX: { label: "Matches Regex (~)", value: "REGEX", placeholder: "^admin.*" },
          IS_EMPTY: { label: "Is Empty", value: "IS_EMPTY", hasValue: false },
        }}
      />,
    );

    // Unary operator shows in dropdown and has NO value input rendered
    expect(screen.getByDisplayValue("Is Empty")).toBeDefined();
    expect(screen.queryByPlaceholderText("Value...")).toBeNull();

    // Rerender with binary operator
    rerender(
      <TableFiltersEditor
        filters={[{ id: "f1", column: "email", operator: "REGEX", value: "^user" }]}
        activeTables={activeTables}
        onChange={onChange}
        customOperators={{
          REGEX: { label: "Matches Regex (~)", value: "REGEX", placeholder: "^admin.*" },
          IS_EMPTY: { label: "Is Empty", value: "IS_EMPTY", hasValue: false },
        }}
      />,
    );
    expect(screen.getByPlaceholderText("^admin.*")).toBeDefined();

    // Verify compileVisualState with custom operator formatSql
    const compiled = compileVisualState(
      "users",
      {},
      [],
      [],
      [{ id: "f1", column: "email", operator: "REGEX", value: "^admin.*" }],
      [],
      false,
      25,
      sampleSchema,
      "postgres",
      "AND",
      {
        REGEX: {
          label: "Regex",
          value: "REGEX",
          formatSql: (colRef, val) => `${colRef} ~ '${val}'`,
        },
      },
    );
    expect(compiled.sql).toContain('"users"."email" ~ \'^admin.*\'');
  });

  // 5. Custom cell renderers and field renderers
  it("renders custom cell renderers and field renderers", () => {
    // 5a. Custom field renderer in TableCard
    render(
      <TableCard
        table={sampleSchema.tables.users}
        selectedColumns={{}}
        onToggleColumn={vi.fn()}
        fieldRenderers={{
          email: ({ column, isSelected, onToggle }) => (
            <div data-testid="custom-email-field">
              <span>Secure {column.name}</span>
              <button data-testid="toggle-email-btn" onClick={onToggle}>
                {isSelected ? "Deselect" : "Select"}
              </button>
            </div>
          ),
        }}
      />,
    );
    expect(screen.getByTestId("custom-email-field")).toBeDefined();
    expect(screen.getByText("Secure email")).toBeDefined();

    // 5b. Custom cell renderer in QueryResultsTable
    const results: QueryResultData = {
      columns: ["id", "amount"],
      rows: [{ id: 1, amount: 249.99 }],
      count: 1,
    };
    render(
      <QueryResultsTable
        results={results}
        cellRenderers={{
          amount: (val) => (
            <span data-testid="currency-cell">${Number(val).toFixed(2)} USD</span>
          ),
        }}
      />,
    );
    const cellEl = screen.getByTestId("currency-cell");
    expect(cellEl).toBeDefined();
    expect(cellEl.textContent).toBe("$249.99 USD");
  });

  // 6. Custom onExecuteQuery propagation
  it("propagates custom onExecuteQuery handler in QueryBuilderProvider", async () => {
    const mockExecute = vi.fn().mockResolvedValue({
      columns: ["id", "email"],
      rows: [{ id: 1, email: "consumer@example.com" }],
      count: 1,
    });

    render(
      <QueryBuilderProvider onExecuteQuery={mockExecute}>
        <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
      </QueryBuilderProvider>,
    );

    const runButton = screen.getByRole("button", { name: /run query/i });
    expect(runButton).toBeDefined();

    await act(async () => {
      fireEvent.click(runButton);
    });

    expect(mockExecute).toHaveBeenCalledTimes(1);
    expect(screen.getByText("consumer@example.com")).toBeDefined();
  });

  // 7. Custom UI using headless hooks without default styles
  it("builds custom UI using headless hooks without default styles", async () => {
    const HeadlessConsumerApp: React.FC = () => {
      const { schema } = useSchemaIntrospection({ initialSchema: sampleSchema });
      const queryState = useQueryState({ table: "users" });
      const { sql, isValid } = useSqlCompiler(queryState.state, {
        schema: sampleSchema,
        dialect: "postgres",
      });
      const execution = useQueryExecution({
        onExecuteQuery: async () => ({
          columns: ["id", "email"],
          rows: [{ id: 42, email: "headless@example.com" }],
          count: 1,
        }),
      });

      return (
        <div data-testid="headless-consumer">
          <span data-testid="table-name">{queryState.state.primaryTable}</span>
          <span data-testid="compiled-sql">{sql}</span>
          <span data-testid="is-valid">{isValid ? "yes" : "no"}</span>
          <button
            data-testid="toggle-email-btn"
            onClick={() => queryState.actions.toggleColumn("users", "email")}
          >
            Toggle Email
          </button>
          <button
            data-testid="run-headless-btn"
            onClick={() => execution.executeQuery(sql)}
          >
            Execute
          </button>
          <span data-testid="result-count">{execution.results?.count ?? 0}</span>
        </div>
      );
    };

    render(<HeadlessConsumerApp />);

    expect(screen.getByTestId("table-name").textContent).toBe("users");
    expect(screen.getByTestId("is-valid").textContent).toBe("yes");
    expect(screen.getByTestId("compiled-sql").textContent).toContain('FROM "users"');

    // Toggle column
    act(() => {
      fireEvent.click(screen.getByTestId("toggle-email-btn"));
    });
    expect(screen.getByTestId("compiled-sql").textContent).toContain("email");

    // Execute query
    await act(async () => {
      fireEvent.click(screen.getByTestId("run-headless-btn"));
    });
    expect(screen.getByTestId("result-count").textContent).toBe("1");
  });

  // 8. ORM schemas conversion in browser and mounting into VisualQueryBuilder
  it("converts ORM schemas in browser and mounts into VisualQueryBuilder", () => {
    const rawPrisma = `
      enum Role {
        USER
        ADMIN
      }

      model User {
        id    Int    @id @default(autoincrement())
        name  String
        email String @unique
        role  Role   @default(USER)
        posts Post[]
        @@map("users")
      }

      model Post {
        id       Int    @id @default(autoincrement())
        title    String
        authorId Int
        author   User   @relation(fields: [authorId], references: [id])
        @@map("posts")
      }
    `;

    const rawDrizzle = `
      import { pgTable, serial, text, integer } from 'drizzle-orm/pg-core';

      export const users = pgTable('users', {
        id: serial('id').primaryKey(),
        name: text('name').notNull(),
        email: text('email').notNull(),
      });

      export const posts = pgTable('posts', {
        id: serial('id').primaryKey(),
        title: text('title').notNull(),
        authorId: integer('author_id').references(() => users.id).notNull(),
      });
    `;

    const rawSqlAlchemy = `
      from sqlalchemy import Column, Integer, String, ForeignKey
      from sqlalchemy.orm import declarative_base

      Base = declarative_base()

      class User(Base):
          __tablename__ = 'users'
          id = Column(Integer, primary_key=True)
          name = Column(String)
          email = Column(String)

      class Post(Base):
          __tablename__ = 'posts'
          id = Column(Integer, primary_key=True)
          title = Column(String)
          author_id = Column(Integer, ForeignKey('users.id'))
    `;

    const prismaTables = fromPrisma(rawPrisma);
    const drizzleTables = fromDrizzle(rawDrizzle);
    const saTables = fromSqlAlchemy(rawSqlAlchemy);

    expect(prismaTables.length).toBe(2);
    expect(drizzleTables.length).toBe(2);
    expect(saTables.length).toBe(2);

    // Convert to SchemaSnapshot
    const snapshot = toSchemaSnapshot(prismaTables);
    expect(snapshot.tables.users).toBeDefined();
    expect(snapshot.tables.posts).toBeDefined();
    expect(snapshot.relationships.length).toBeGreaterThan(0);

    // Mount into VisualQueryBuilder
    const { container } = render(
      <VisualQueryBuilder schema={snapshot} initialTable="users" />,
    );

    expect(container.querySelector('[data-qb="root"]')).not.toBeNull();
    expect(screen.getByText("users")).toBeDefined();
  });
});
