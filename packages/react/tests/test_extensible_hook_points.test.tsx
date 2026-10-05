import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  TableFiltersEditor,
  TableCard,
  QueryResultsTable,
  compileVisualState,
  type SchemaSnapshot,
  type VisualFilter,
  type TableMeta,
  type QueryResultData,
} from "../src";

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
  },
};

describe("Extensible Hook Points (Custom Operators, Field Renderers, Cell Renderers, Execution)", () => {
  describe("Custom Filter Operators", () => {
    it("renders custom operators in TableFiltersEditor dropdown and hides input for unary operator", () => {
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

      // Verify custom options in select
      const operatorSelect = screen.getByDisplayValue("Is Empty");
      expect(operatorSelect).toBeDefined();

      // For IS_EMPTY (hasValue: false), input should not be rendered
      const valueInput = screen.queryByPlaceholderText("Value...");
      expect(valueInput).toBeNull();

      // Rerender with binary custom operator
      rerender(
        <TableFiltersEditor
          filters={[{ id: "f1", column: "email", operator: "REGEX", value: "test" }]}
          activeTables={activeTables}
          onChange={onChange}
          customOperators={{
            REGEX: { label: "Matches Regex (~)", value: "REGEX", placeholder: "^admin.*" },
            IS_EMPTY: { label: "Is Empty", value: "IS_EMPTY", hasValue: false },
          }}
        />,
      );

      const regexInput = screen.getByPlaceholderText("^admin.*");
      expect(regexInput).toBeDefined();
    });

    it("compileVisualState uses formatSql from custom operators", () => {
      const compiled = compileVisualState(
        "users",
        {},
        [],
        [],
        [
          {
            id: "f1",
            column: "email",
            operator: "REGEX",
            value: "^[a-z]+@",
          },
        ],
        [],
        false,
        50,
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

      expect(compiled.sql).toContain('"users"."email" ~ \'^[a-z]+@\'');
    });
  });

  describe("Custom Field Renderers", () => {
    it("renders custom field renderer in TableCard for specific column name", () => {
      render(
        <TableCard
          table={sampleSchema.tables.users}
          selectedColumns={{}}
          onToggleColumn={vi.fn()}
          fieldRenderers={{
            email: ({ column, isSelected, onToggle }) => (
              <div data-testid="custom-email-renderer">
                <span data-testid="col-label">Secure {column.name}</span>
                <button data-testid="custom-toggle-btn" onClick={onToggle}>
                  {isSelected ? "Deselect" : "Select"}
                </button>
              </div>
            ),
          }}
        />,
      );

      expect(screen.getByTestId("custom-email-renderer")).toBeDefined();
      expect(screen.getByTestId("col-label").textContent).toBe("Secure email");
    });
  });

  describe("Custom Cell Renderers", () => {
    it("renders custom cell renderer in QueryResultsTable", () => {
      const results: QueryResultData = {
        columns: ["id", "email", "created_at"],
        rows: [
          {
            id: 1,
            email: "alice@example.com",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        count: 1,
      };

      render(
        <QueryResultsTable
          results={results}
          cellRenderers={{
            created_at: (val) => (
              <span data-testid="formatted-date">
                Formatted: {new Date(String(val)).getUTCFullYear()}
              </span>
            ),
          }}
        />,
      );

      const formattedEl = screen.getByTestId("formatted-date");
      expect(formattedEl).toBeDefined();
      expect(formattedEl.textContent).toContain("Formatted: 2026");
    });
  });

  describe("Custom Query Execution Handler in QueryBuilderProvider", () => {
    it("propagates onExecuteQuery from QueryBuilderProvider to VisualQueryBuilder Run Query button", async () => {
      const mockExecute = vi.fn().mockResolvedValue({
        columns: ["id", "email"],
        rows: [{ id: 1, email: "alice@example.com" }],
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
      // Results tab should show row
      expect(screen.getByText("alice@example.com")).toBeDefined();
    });
  });
});
