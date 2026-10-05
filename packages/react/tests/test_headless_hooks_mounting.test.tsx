import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, act } from "@testing-library/react";
import {
  useQueryBuilder,
  useSchemaIntrospection,
  useQueryExecution,
  useQueryState,
  useSqlCompiler,
  type SchemaSnapshot,
} from "../src";

const sampleSchema: SchemaSnapshot = {
  tables: {
    customers: {
      name: "customers",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "company", data_type: "varchar", is_nullable: false, is_primary: false },
        { name: "status", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    invoices: {
      name: "invoices",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "customer_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
  },
  relationships: [
    {
      source_table: "invoices",
      source_column: "customer_id",
      target_table: "customers",
      target_column: "id",
    },
  ],
};

/**
 * Pure headless harness component mounting all 5 headless hooks without any DOM styles.
 */
const PureHeadlessHarness: React.FC = () => {
  // 1. Schema Introspection Hook
  const { schema, isLoading: schemaLoading } = useSchemaIntrospection({
    initialSchema: sampleSchema,
  });
  const tableCount = schema?.tables ? Object.keys(schema.tables).length : 0;

  // 2. Query State Hook
  const queryState = useQueryState({
    table: "customers",
  });

  // 3. SQL Compiler Hook
  const { sql, isValid } = useSqlCompiler(queryState.state, {
    schema: sampleSchema,
    dialect: "postgres",
  });

  // 4. Query Builder Master Hook
  const qb = useQueryBuilder({
    schema: sampleSchema,
    initialTable: "customers",
  });

  // 5. Query Execution Hook
  const execution = useQueryExecution({
    onExecuteQuery: async () => ({
      columns: ["id", "company"],
      rows: [{ id: 101, company: "Acme Corp" }],
      count: 1,
    }),
  });

  return (
    <div data-testid="headless-container">
      <div data-testid="schema-status">{schemaLoading ? "loading" : "loaded"}</div>
      <div data-testid="table-count">{tableCount}</div>
      <div data-testid="primary-table">{queryState.state.primaryTable}</div>
      <div data-testid="compiled-sql">{sql}</div>
      <div data-testid="sql-valid">{isValid ? "valid" : "invalid"}</div>
      <div data-testid="qb-primary">{qb.state.primaryTable}</div>

      {/* Action buttons */}
      <button
        onClick={() => queryState.actions.toggleColumn("customers", "company")}
        data-testid="toggle-col-btn"
      >
        Toggle Company
      </button>

      <button
        onClick={() =>
          queryState.actions.addFilter({
            id: "f-status",
            column: "status",
            operator: "=",
            value: "active",
          })
        }
        data-testid="add-filter-btn"
      >
        Add Filter
      </button>

      <button
        onClick={() => execution.executeQuery(sql)}
        data-testid="exec-btn"
      >
        Execute Query
      </button>

      <div data-testid="exec-status">
        {execution.isLoading ? "loading" : execution.results ? "completed" : "idle"}
      </div>
      <div data-testid="exec-count">{execution.results?.count ?? 0}</div>
    </div>
  );
};

describe("React Headless Hooks Independent Mounting Harness", () => {
  it("mounts all 5 headless hooks in a pure headless component with zero DOM styles", async () => {
    const { container } = render(<PureHeadlessHarness />);

    // Verify hooks initialized properly
    expect(screen.getByTestId("schema-status").textContent).toBe("loaded");
    expect(screen.getByTestId("table-count").textContent).toBe("2");
    expect(screen.getByTestId("primary-table").textContent).toBe("customers");
    expect(screen.getByTestId("sql-valid").textContent).toBe("valid");

    // Verify initial SQL is valid SELECT
    const initialSql = screen.getByTestId("compiled-sql").textContent;
    expect(initialSql).toContain("FROM");
    expect(initialSql).toContain('"customers"');

    // Verify NO inline styles are injected anywhere in the container
    const allElements = container.querySelectorAll("*");
    allElements.forEach((el) => {
      expect(el.getAttribute("style")).toBeNull();
    });

    // Test mutating state via headless hook
    act(() => {
      screen.getByTestId("toggle-col-btn").click();
    });

    const sqlAfterCol = screen.getByTestId("compiled-sql").textContent;
    expect(sqlAfterCol).toContain('"company"');

    // Add filter via headless hook
    act(() => {
      screen.getByTestId("add-filter-btn").click();
    });

    const sqlAfterFilter = screen.getByTestId("compiled-sql").textContent;
    expect(sqlAfterFilter).toContain('"status" = \'active\'');

    // Execute query via headless hook
    await act(async () => {
      screen.getByTestId("exec-btn").click();
    });

    expect(screen.getByTestId("exec-status").textContent).toBe("completed");
    expect(screen.getByTestId("exec-count").textContent).toBe("1");
  });
});
