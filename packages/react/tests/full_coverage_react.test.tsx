import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, renderHook, act } from "@testing-library/react";

import { QueryBuilderProvider, useQueryBuilderContext } from "../src/theme/QueryBuilderProvider";
import { useQueryExecution } from "../src/hooks/useQueryExecution";
import { TableCard } from "../src/components/TableCard";
import { TableFiltersEditor } from "../src/components/TableFiltersEditor";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import { SchemaExplorerModal } from "../src/components/SchemaExplorerModal";
import { SchemaExplorer } from "../src/components/SchemaExplorer";
import { estimateClientPlan, compileVisualState } from "../src/utils/compiler";
import { normalizeSchema } from "../src/utils/schemaUtils";
import { toSchemaSnapshot, normalizeDataType } from "../src/adapters/utils";
import { fromDrizzle } from "../src/adapters/drizzle";
import { fromJsonSchema } from "../src/adapters/jsonSchema";
import { fromPrisma } from "../src/adapters/prisma";
import { fromSqlAlchemy } from "../src/adapters/sqlalchemy";
import { TableSchema } from "../src/types";

describe("React SDK 100% Coverage Suite", () => {
  describe("1. QueryBuilderProvider & useQueryExecution", () => {
    it("inherits mode from parentContext when mode prop is null, and falls back to styled", () => {
      let capturedContext: any = null;
      const Consumer = () => {
        capturedContext = useQueryBuilderContext();
        return <div>Mode: {capturedContext?.mode}</div>;
      };

      // Nested provider: outer has mode="unstyled", inner has mode={null as any}
      render(
        <QueryBuilderProvider mode="unstyled">
          <QueryBuilderProvider mode={null as any}>
            <Consumer />
          </QueryBuilderProvider>
        </QueryBuilderProvider>
      );
      expect(capturedContext.mode).toBe("unstyled");

      // Standalone provider with null mode falls back to "styled"
      render(
        <QueryBuilderProvider mode={null as any}>
          <Consumer />
        </QueryBuilderProvider>
      );
      expect(capturedContext.mode).toBe("styled");
    });

    it("falls back to qbContext.onExecuteQuery when propExecuteQuery is not provided", async () => {
      const mockQbExecute = vi.fn().mockResolvedValue({
        columns: ["count"],
        rows: [[42]],
      });

      const wrapper = ({ children }: { children: React.ReactNode }) => (
        <QueryBuilderProvider onExecuteQuery={mockQbExecute}>
          {children}
        </QueryBuilderProvider>
      );

      const { result } = renderHook(() => useQueryExecution(), { wrapper });

      await act(async () => {
        await result.current.executeQuery("SELECT COUNT(*) FROM users;", { table: "users" });
      });

      expect(mockQbExecute).toHaveBeenCalledWith("SELECT COUNT(*) FROM users;", { table: "users" });
      expect(result.current.results?.rows).toEqual([[42]]);
    });
  });

  describe("2. TableCard custom column toggle", () => {
    it("executes custom column renderer onToggle callback", () => {
      const onToggleColumn = vi.fn();
      const mockTable: TableSchema = {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_primary: true },
        ],
      };

      render(
        <TableCard
          table={mockTable}
          selectedColumns={["id"]}
          onToggleColumn={onToggleColumn}
          fieldRenderers={{
            id: ({ onToggle, isSelected }) => (
              <button
                type="button"
                data-testid="custom-toggle-btn"
                onClick={onToggle}
              >
                {isSelected ? "Selected" : "Unselected"}
              </button>
            ),
          }}
        />
      );

      const toggleBtn = screen.getByTestId("custom-toggle-btn");
      expect(toggleBtn).toBeDefined();
      fireEvent.click(toggleBtn);
      expect(onToggleColumn).toHaveBeenCalledWith("id");
    });

    it("renders custom column renderer for unselected column", () => {
      const mockTable: TableSchema = {
        name: "users",
        columns: [
          { name: "id", data_type: "integer" },
          { name: "email", data_type: "varchar" },
        ],
      };
      render(
        <TableCard
          table={mockTable}
          selectedColumns={{ "users.id": { table: "users", column: "id" } as any }}
          onToggleColumn={() => {}}
          fieldRenderers={{
            id: ({ isSelected }) => <div data-testid="sel-true">Selected: {String(isSelected)}</div>,
            email: ({ isSelected }) => <div data-testid="sel-false">Selected: {String(isSelected)}</div>,
          }}
        />
      );
      expect(screen.getByTestId("sel-true").textContent).toBe("Selected: true");
      expect(screen.getByTestId("sel-false").textContent).toBe("Selected: false");
    });
  });

  describe("3. TableFiltersEditor custom operator fallback", () => {
    it("renders cop.value as label when cop.label is empty", () => {
      const mockTable: TableSchema = {
        name: "items",
        columns: [{ name: "price", data_type: "float" }],
      };

      render(
        <TableFiltersEditor
          activeTables={[mockTable]}
          filters={[{ id: "f1", column: "price", operator: "NEAR", value: "10" }]}
          onChange={() => {}}
          customOperators={{
            NEAR: {
              value: "NEAR",
              label: "", // Empty label triggers cop.value fallback on line 257
              symbol: "~",
            },
          }}
        />
      );

      const option = screen.getByRole("option", { name: "NEAR" });
      expect(option).toBeDefined();
    });
  });

  describe("4. SchemaExplorerModal & SchemaExplorer edge cases", () => {
    const sampleSchema: TableSchema[] = [
      {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_primary: true },
          { name: "user_id", data_type: "integer" },
        ],
        foreign_keys: [
          {
            table: "orders",
            column: "user_id",
            foreign_table: "users",
            foreign_column: "id",
          },
        ],
      },
      {
        name: "users",
        columns: [{ name: "id", data_type: "integer", is_primary: true }],
      },
    ];

    it("handles Escape key, unstyled mode, and light/dark theme in SchemaExplorerModal", () => {
      const onClose = vi.fn();

      // Render with unstyled=true and theme="light"
      const { rerender } = render(
        <SchemaExplorerModal
          isOpen={true}
          onClose={onClose}
          schema={sampleSchema}
          unstyled={true}
          theme="light"
        />
      );

      // Verify close on Escape keydown
      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalled();

      // Rerender with theme="dark" and unstyled=false
      rerender(
        <SchemaExplorerModal
          isOpen={true}
          onClose={onClose}
          schema={sampleSchema}
          unstyled={false}
          theme="dark"
        />
      );
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    it("renders empty table placeholder in SchemaExplorer when no table is selected and unstyled=true", () => {
      render(
        <SchemaExplorer
          schema={[]}
          unstyled={true}
        />
      );

      expect(
        screen.getByText("Select a table from the list to explore columns and relationships.")
      ).toBeDefined();
    });

    it("renders FK jump button in unstyled mode inside SchemaExplorer", () => {
      const onSelectTable = vi.fn();
      render(
        <SchemaExplorer
          schema={sampleSchema}
          selectedTable="orders"
          onSelectTable={onSelectTable}
          unstyled={true}
        />
      );

      const jumpBtn = screen.getByLabelText("Jump to table users");
      expect(jumpBtn).toBeDefined();
      fireEvent.click(jumpBtn);
      expect(onSelectTable).toHaveBeenCalledWith("users");
    });

    it("falls back to contextTheme in SchemaExplorerModal when theme is undefined", () => {
      render(
        <SchemaExplorerModal
          isOpen={true}
          onClose={() => {}}
          theme={undefined}
          schema={sampleSchema}
        />
      );
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    it("renders empty table placeholder in SchemaExplorer with styled mode", () => {
      render(
        <SchemaExplorer
          schema={[]}
          unstyled={false}
        />
      );
      expect(
        screen.getByText("Select a table from the list to explore columns and relationships.")
      ).toBeDefined();
    });

    it("renders no FKs message in unstyled mode", () => {
      render(
        <SchemaExplorer
          schema={[{ name: "isolated", columns: [{ name: "id", data_type: "int" }] }]}
          selectedTable="isolated"
          unstyled={true}
        />
      );
      expect(screen.getByText("No direct foreign keys configured for this table.")).toBeDefined();
    });

    it("renders unstyled SchemaExplorer with quick query, add to canvas, and column search (>5 cols)", () => {
      const wideTable: TableSchema = {
        name: "wide_table",
        columns: [
          { name: "c1", data_type: "int" },
          { name: "c2", data_type: "text" },
          { name: "c3", data_type: "text" },
          { name: "c4", data_type: "text" },
          { name: "c5", data_type: "text" },
          { name: "c6", data_type: "text" },
        ],
      };
      render(
        <SchemaExplorer
          schema={[wideTable]}
          selectedTable="wide_table"
          unstyled={true}
          onQuickQuery={() => {}}
          onAddToCanvas={() => {}}
        />
      );
      expect(screen.getByLabelText("Quick query table wide_table")).toBeDefined();
      expect(screen.getByLabelText("Add table wide_table to canvas")).toBeDefined();
      expect(screen.getByLabelText("Filter columns")).toBeDefined();
    });

    it("covers SchemaExplorer unstyled clear search, copy feedback, onOpenErd, and FK pill", () => {
      const fkSchema: TableSchema[] = [
        {
          name: "orders",
          columns: [
            { name: "id", data_type: "int" },
            { name: "user_id", data_type: "int" },
          ],
          foreign_keys: [
            { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
          ],
        },
      ];

      // 1. Unstyled with search input typed and copy clicked
      const { rerender } = render(
        <SchemaExplorer
          schema={fkSchema}
          selectedTable="orders"
          unstyled={true}
          onOpenErd={() => {}}
        />
      );

      // Trigger search input to show Clear search button
      const searchInput = screen.getByPlaceholderText(/search tables/i);
      fireEvent.change(searchInput, { target: { value: "ord" } });
      const clearBtn = screen.getByLabelText("Clear schema search");
      expect(clearBtn).toBeDefined();

      // Click copy SQL button to show copy feedback
      const copyBtn = screen.getByRole("button", { name: /copy sql/i });
      fireEvent.click(copyBtn);
      expect(screen.getByTestId("copy-feedback")).toBeDefined();

      // 2. Styled mode with foreignKeys > 0 and onOpenErd
      rerender(
        <SchemaExplorer
          schema={fkSchema}
          selectedTable="orders"
          unstyled={false}
          onOpenErd={() => {}}
        />
      );
      expect(screen.getByText("1 Foreign Keys")).toBeDefined();
      expect(screen.getByLabelText("View interactive ERD graph")).toBeDefined();
    });

    it("handles table with empty columns, unknown data type color, and clipboard error in SchemaExplorer", () => {
      const edgeSchema: TableSchema[] = [
        {
          name: "blob_table",
          columns: [{ name: "binary_payload", data_type: "blob" }],
        },
        {
          name: "empty_cols_table",
          columns: [],
        },
      ];

      // 1. Unknown data type color
      const { rerender } = render(
        <SchemaExplorer
          schema={edgeSchema}
          selectedTable="blob_table"
        />
      );
      expect(screen.getByText("blob")).toBeDefined();

      // 2. Empty columns table with Copy SQL -> evaluates '*' on line 194
      rerender(
        <SchemaExplorer
          schema={edgeSchema}
          selectedTable="empty_cols_table"
        />
      );
      const copyBtn = screen.getByRole("button", { name: /copy sql/i });
      fireEvent.click(copyBtn);
      expect(screen.getByTestId("copy-feedback")).toBeDefined();

      // 3. Clipboard writeText rejection -> catches on lines 202-203
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: () => {
            throw new Error("Clipboard permission denied");
          },
        },
        configurable: true,
      });

      fireEvent.click(copyBtn);
      expect(screen.getByTestId("copy-feedback").textContent).toContain("Failed to copy SQL");

      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      });
    });

    it("handles category filtering, keyboard navigation, copy name failure, and theme variants in SchemaExplorer", () => {
      const catSchema: TableSchema[] = [
        {
          name: "orders",
          schema: "analytics",
          comment: "Contains customer orders",
          columns: [
            { name: "id", data_type: "int", comment: "Primary identity key" },
            { name: "c1", data_type: "text" },
            { name: "c2", data_type: "text" },
            { name: "c3", data_type: "text" },
            { name: "c4", data_type: "text" },
            { name: "c5", data_type: "text" },
          ],
        },
        {
          name: "users",
          schema: "public",
          columns: [{ name: "id", data_type: "int" }],
        },
        {
          name: "analytics_summary",
          columns: [{ name: "id", data_type: "int" }],
        },
      ];

      // 1. Render and filter by category (covers lines 126-130)
      const { rerender } = render(<SchemaExplorer schema={catSchema} />);
      const analyticsBtn = screen.getByRole("button", { name: "analytics" });
      fireEvent.click(analyticsBtn);
      expect(screen.getAllByText("orders").length).toBeGreaterThan(0);
      expect(screen.getByText("analytics_summary")).toBeDefined();
      expect(screen.queryByText("users")).toBeNull();

      // Reset filter
      const allBtn = screen.getByRole("button", { name: "All" });
      fireEvent.click(allBtn);
      expect(screen.getByText("users")).toBeDefined();

      // 2. Keyboard space key selection (covers line 613)
      const usersItem = screen.getByLabelText("Select table users");
      fireEvent.keyDown(usersItem, { key: " " });
      expect(screen.getByTestId("detail-table-title").textContent).toContain("users");

      // 3. Search table by comment (covers line 137)
      const searchInput = screen.getByPlaceholderText(/search tables/i);
      fireEvent.change(searchInput, { target: { value: "customer orders" } });
      expect(screen.getByLabelText("Select table orders")).toBeDefined();
      expect(screen.queryByLabelText("Select table users")).toBeNull();
      fireEvent.change(searchInput, { target: { value: "" } });

      // 4. Search columns by column comment (covers line 160)
      const ordersItem = screen.getByLabelText("Select table orders");
      fireEvent.click(ordersItem);
      const colSearchInput = screen.getByPlaceholderText(/filter columns/i);
      fireEvent.change(colSearchInput, { target: { value: "identity key" } });
      expect(screen.getByText("Primary identity key")).toBeDefined();

      // 5. Copy table name failure branch (covers lines 185-186)
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: () => {
            throw new Error("Copy error");
          },
        },
        configurable: true,
      });

      const copyNameBtn = screen.getByRole("button", { name: "Copy table name" });
      fireEvent.click(copyNameBtn);
      expect(screen.getByTestId("copy-feedback").textContent).toContain("Failed to copy");

      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      });

      // 6. Theme variants & empty activeTable ERD callback (covers lines 41-42, 337)
      rerender(<SchemaExplorer schema={catSchema} theme="light" />);
      rerender(<SchemaExplorer schema={catSchema} theme="dark" />);

      const erdSpy = vi.fn();
      rerender(<SchemaExplorer schema={[]} onOpenErd={erdSpy} />);
      const erdBtn = screen.getByRole("button", { name: "View interactive ERD graph" });
      fireEvent.click(erdBtn);
      expect(erdSpy).toHaveBeenCalledWith("");

      // 7. Undefined schema handles fallback tablesMap and foreignKeys
      rerender(<SchemaExplorer schema={undefined} />);
    });
  });

  describe("5. VisualQueryBuilder modal callbacks", () => {
    const mockSchema: TableSchema[] = [
      {
        name: "customers",
        columns: [{ name: "id", data_type: "integer", is_primary: true }],
      },
    ];

    it("triggers onOpenErd and onQuickQuery callbacks from SchemaExplorerModal inside VisualQueryBuilder", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          defaultTable="customers"
        />
      );

      // Open Schema Explorer modal via button with aria-label="Open schema explorer"
      const exploreBtn = screen.getByLabelText(/open schema explorer/i);
      fireEvent.click(exploreBtn);

      // Verify Schema Explorer modal is open
      const modal = screen.getByRole("dialog", { name: /database schema explorer/i });
      expect(modal).toBeDefined();

      // Trigger "View interactive ERD graph" button inside SchemaExplorer (line 338)
      const erdBtn = screen.getByLabelText(/view interactive erd graph/i);
      fireEvent.click(erdBtn);

      // Verify ERD modal opened
      expect(screen.getByRole("dialog", { name: /entity relationship diagram/i })).toBeDefined();
      // Close ERD using its close button
      const closeErdBtn = screen.getByLabelText("Close schema ERD modal");
      fireEvent.click(closeErdBtn);

      // Open Explorer again to test Quick Query callback
      fireEvent.click(exploreBtn);
      const quickQueryBtn = screen.getByLabelText(/quick query table customers/i);
      fireEvent.click(quickQueryBtn);

      // Modal closed and table added to canvas
      expect(screen.queryByRole("dialog", { name: /database schema explorer/i })).toBeNull();
    });

    it("renders query plan tab in unstyled mode and handles keyboard navigation", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          defaultTable="customers"
          showPlanTab={true}
          unstyled={true}
        />
      );
      const planTab = screen.getByRole("tab", { name: /query plan/i });
      expect(planTab).toBeDefined();
      fireEvent.keyDown(planTab, { key: "ArrowRight" });
    });

    it("handles onAddJoin button to link tables in VisualQueryBuilder", () => {
      const multiTableSchema: TableSchema[] = [
        {
          name: "orders",
          columns: [
            { name: "id", data_type: "integer", is_primary: true },
            { name: "customer_id", data_type: "integer" },
          ],
        },
        {
          name: "customers",
          columns: [{ name: "id", data_type: "integer", is_primary: true }],
        },
      ];

      render(
        <VisualQueryBuilder
          schema={multiTableSchema}
          defaultTable="orders"
        />
      );

      const addJoinBtn = screen.getByLabelText(/add join for table orders/i);
      expect(addJoinBtn).toBeDefined();
      fireEvent.click(addJoinBtn);
    });

    it("triggers onClose for SchemaExplorerModal in VisualQueryBuilder", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          defaultTable="customers"
        />
      );
      const exploreBtn = screen.getByLabelText(/open schema explorer/i);
      fireEvent.click(exploreBtn);
      expect(screen.getByRole("dialog", { name: /database schema explorer/i })).toBeDefined();

      // Trigger onClose by pressing Escape
      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.queryByRole("dialog", { name: /database schema explorer/i })).toBeNull();
    });
  });

  describe("6. Compiler estimateClientPlan full branches", () => {
    it("compiles visual state with vector search and distance projection", () => {
      // Wildcard select
      const res1 = compileVisualState(
        "docs",
        {},
        [],
        [],
        [],
        [],
        false,
        10,
        null,
        "postgres",
        "AND",
        undefined,
        {
          column: "embedding",
          vector: [0.1, 0.2, 0.3],
          include_distances: true,
        },
      );
      expect(res1.sql).toContain('AS "_distance"');
      expect(res1.sql).toContain("ORDER BY");

      // Custom select clause
      const res2 = compileVisualState(
        "docs",
        {
          "docs.title": { table: "docs", column: "title", name: "title" } as any,
        },
        ["docs.title"],
        [],
        [],
        [],
        false,
        10,
        null,
        "postgres",
        "AND",
        undefined,
        {
          column: "embedding",
          vector: [0.1, 0.2, 0.3],
          include_distances: true,
        },
      );
      expect(res2.sql).toContain('"title"');
      expect(res2.sql).toContain('AS "_distance"');

      // Vector search without column
      const resNoCol = compileVisualState(
        "docs",
        {},
        [],
        [],
        [],
        [],
        false,
        10,
        null,
        "postgres",
        "AND",
        undefined,
        {
          vector: [0.1, 0.2],
        },
      );
      expect(resNoCol.sql).toContain('"embedding"');

      // estimateClientPlan with empty object
      const emptyPlan = estimateClientPlan({});
      expect(emptyPlan.node_type).toBe("Limit");
    });

    it("compiles custom operator with hasValue === false (line 455)", () => {
      const res = compileVisualState(
        "users",
        {},
        [],
        [],
        [
          {
            id: "f1",
            column: "bio",
            operator: "IS_EMPTY" as any,
            value: null,
          },
        ],
        [],
        false,
        10,
        null,
        "postgres",
        "AND",
        {
          IS_EMPTY: {
            value: "IS EMPTY",
            label: "Is Empty",
            symbol: "Ø",
            hasValue: false,
          },
        },
      );
      expect(res.sql).toContain('"bio" IS EMPTY');
    });
    it("estimates plans for vector, hybrid, filters, and joins", () => {
      // 1. Hybrid search plan
      const hybridPlan = estimateClientPlan({
        table: "articles",
        hybrid_search: {
          vector: [0.1, 0.2],
          query_text: "science",
          text_columns: ["title"],
        },
      });
      expect(hybridPlan.node_type).toBe("Limit");
      const hybridScan = (hybridPlan.children?.[0] as any)?.children?.[0];
      expect(hybridScan?.node_type).toBe("Hybrid Search Merge");

      // 2. Vector search plan
      const vectorPlan = estimateClientPlan({
        table: "articles",
        vector_search: { vector: [0.1, 0.2] },
      });
      const vectorScan = (vectorPlan.children?.[0] as any)?.children?.[0];
      expect(vectorScan?.node_type).toBe("KNN Scan");

      // 3. Filters plan (Seq Scan with warnings on line 671-680)
      const filterPlan = estimateClientPlan({
        table: "articles",
        filters: [{ column: "author_id", operator: "=", value: 10 }],
      });
      const filterScan = (filterPlan.children?.[0] as any)?.children?.[0];
      expect(filterScan?.warnings?.[0]).toContain("Sequential table scan");

      // 4. Joins plan (lines 692-710)
      const joinPlan = estimateClientPlan({
        table: "articles",
        joins: [
          { table: "authors", type: "INNER", on: [] },
          { on: [] }, // falsy table and falsy type
        ],
      });
      const joinNode = (joinPlan.children?.[0] as any)?.children?.[0];
      expect(joinNode?.node_type).toBe("LEFT Join");
    });
  });

  describe("7. schemaUtils & adapters/utils column metadata normalization", () => {
    it("handles is_nullable fallback and missing type/nullable defaults", () => {
      const rawTables = [
        {
          name: "data",
          columns: [
            { name: "c1", is_nullable: false, data_type: "integer" },
            { name: "c2" }, // undefined isNullable and undefined is_nullable -> true
            { name: "c3", isNullable: true, dataType: "varchar" },
          ],
        },
      ];

      const norm1 = normalizeSchema(rawTables as any);
      expect(norm1?.tables.data.columns[0].is_nullable).toBe(false);
      expect(norm1?.tables.data.columns[1].is_nullable).toBe(true);
      expect(norm1?.tables.data.columns[1].data_type).toBe("text");
      expect(norm1?.tables.data.columns[2].is_nullable).toBe(true);
      expect(norm1?.tables.data.columns[2].data_type).toBe("varchar");

      const snap = toSchemaSnapshot(rawTables as any);
      expect(snap.tables.data.columns[0].is_nullable).toBe(false);
      expect(snap.tables.data.columns[1].is_nullable).toBe(true);
    });

    it("handles empty string in normalizeDataType and filters invalid tables", () => {
      expect(normalizeDataType("")).toBe("text");
      expect(normalizeDataType("custom_unknown_type")).toBe("custom_unknown_type");

      const malformed = [
        null as any,
        { name: "" } as any,
        {
          name: "valid_tbl",
          schema: "custom_schema",
          columns: [
            { name: "id", isPrimary: true, isNullable: false },
            { name: "desc", is_primary: false, is_nullable: true },
          ],
          foreign_keys: [
            { column: "ref_id", foreign_table: "target", foreign_column: "id" },
            { column: "ref_id", foreign_table: "target", foreign_column: "id" }, // duplicate FK
            { column: "bad_ref", foreignTable: "" }, // empty foreignTable
          ],
        },
      ];

      const norm = normalizeSchema(malformed as any);
      expect(norm?.tables.valid_tbl.schema).toBe("custom_schema");
      expect(norm?.tables.valid_tbl.columns[0].is_primary).toBe(true);
      expect(norm?.foreign_keys.length).toBe(2);

      const snap = toSchemaSnapshot(malformed as any);
      expect(snap.tables.valid_tbl.schema).toBe("custom_schema");
      expect(snap.tables.valid_tbl.columns[0].is_primary).toBe(true);
      expect(snap.foreign_keys.length).toBe(1);
    });

    it("handles table without columns array in normalizeSchema and toSchemaSnapshot", () => {
      const tableWithoutCols = [{ name: "no_cols_table" }];
      const norm = normalizeSchema(tableWithoutCols as any);
      expect(norm?.tables.no_cols_table.columns).toEqual([]);

      const snap = toSchemaSnapshot(tableWithoutCols as any);
      expect(snap.tables.no_cols_table.columns).toEqual([]);
    });
  });

  describe("8. Drizzle adapter extraBlock positional primaryKey & FK case matching", () => {
    it("parses positional primaryKey in extraBlock and case-matches foreign keys", () => {
      const drizzleCode = `
        export const parentTbl = pgTable('parent_tbl', {
          USER_ID: serial('USER_ID').primaryKey(),
        });

        export const childTbl = pgTable('child_tbl', {
          id: serial('id'),
          userId: integer('user_id').references(() => parentTbl.user_id),
        }, (table) => ({
          pk: primaryKey(table.id, table.userId),
        }));
      `;

      const tables = fromDrizzle(drizzleCode);
      const child = tables.find((t) => t.name === "child_tbl");
      expect(child?.primaryKeys).toEqual(["id", "user_id"]);
      const fk = child?.foreignKeys?.[0];
      expect(fk?.foreignColumn).toBe("USER_ID");
    });

    it("parses Drizzle runtime table objects with arrays, maps, references and enums", () => {
      const runtimeTable1 = {
        [Symbol.for("drizzle:Name")]: "users",
        [Symbol.for("drizzle:Columns")]: {
          id: { name: "id", dataType: "serial", primary: true, notNull: true },
          status: { name: "status", dataType: "varchar", enumValues: ["active", "inactive"] },
          roleId: {
            name: "role_id",
            dataType: "integer",
            references: () => ({
              table: { name: "roles" },
              column: { name: "id" },
            }),
          },
          _hidden: {},
        },
      };

      const runtimeTable2 = {
        name: "roles",
        columns: {
          id: { name: "id", isPrimaryKey: true, notNull: true },
        },
      };

      // 1. Array of runtime tables
      const fromArr = fromDrizzle([runtimeTable1, runtimeTable2]);
      expect(fromArr.length).toBe(2);
      expect(fromArr[0].name).toBe("users");
      expect(fromArr[0].primaryKeys).toEqual(["id"]);
      expect(fromArr[0].foreignKeys[0].foreignTable).toBe("roles");
      expect(fromArr[0].enums?.status).toEqual(["active", "inactive"]);

      // 2. Single table object
      const fromSingle = fromDrizzle(runtimeTable1);
      expect(fromSingle.length).toBe(1);
      expect(fromSingle[0].name).toBe("users");

      // 3. Map of table objects
      const fromMap = fromDrizzle({ users: runtimeTable1, roles: runtimeTable2 });
      expect(fromMap.length).toBe(2);

      // 4. Default value raw expression in string code
      const drizzleCodeWithRawDef = `
        export const items = pgTable('items', {
          id: serial('id').primaryKey(),
          createdAt: timestamp('created_at').default(CURRENT_TIMESTAMP),
        });
      `;
      const fromCode = fromDrizzle(drizzleCodeWithRawDef);
      expect(fromCode[0].columns[1].default).toBe("CURRENT_TIMESTAMP");
    });

    it("handles Drizzle table using nameOrKey fallback and throwing references()", () => {
      const namelessTable = {
        id: { name: "id", dataType: "serial" },
        brokenFk: {
          name: "broken_id",
          dataType: "integer",
          references: () => {
            throw new Error("Cannot resolve reference");
          },
        },
      };

      const fromObj = fromDrizzle({ inferred_name: namelessTable });
      expect(fromObj.length).toBe(1);
      expect(fromObj[0].name).toBe("inferred_name");
      expect(fromObj[0].foreignKeys.length).toBe(0);
    });

    it("handles Drizzle composite PK with non-existent column, external table references, double-quoted defaults, and Symbol table names", () => {
      const drizzleComplexCode = `
        export const emptyTable = pgTable("empty_table");
        export const users = pgTable("users", {
          id: serial("id").primaryKey(),
          status: text("status").default("active"),
          geom: custom_type("geom"),
          extId: integer("ext_id").references(() => externalTable.id),
        }, (table) => ({
          pk: primaryKey({ columns: [table.id, table.unknown_prop] }),
        }));
      `;
      const res = fromDrizzle(drizzleComplexCode, { defaultSchema: "custom_drizzle" });
      expect(res.length).toBe(2);
      const usersTable = res.find((t) => t.name === "users");
      expect(usersTable?.schema).toBe("custom_drizzle");
      expect(usersTable?.primaryKeys).toContain("unknown_prop");
      expect(usersTable?.columns.find((c) => c.name === "status")?.default).toBe("active");
      expect(usersTable?.columns.find((c) => c.name === "geom")?.dataType).toBe("custom_type");

      // Runtime object with Symbol.for("drizzle:Name") and refTarget.column.name
      const symTable = {
        [Symbol.for("drizzle:Name")]: "sym_table",
        id: { name: "id", dataType: "serial" },
        refId: {
          name: "ref_id",
          dataType: "integer",
          references: () => ({
            column: { name: "target_col" },
            table: { [Symbol.for("drizzle:Name")]: "target_tbl" },
          }),
        },
      };
      const resSym = fromDrizzle(symTable);
      expect(resSym[0].name).toBe("sym_table");
      expect(resSym[0].foreignKeys[0].foreignColumn).toBe("target_col");
    });

    it("exercises all Drizzle parsing edge cases, runtime shapes, and symbol properties", () => {
      // 1. Runtime shapes: null table, _: { name }, Symbol.for('drizzle:Columns'), _: { columns }, empty table
      const runtimeShapes = {
        nullTbl: null,
        emptyTbl: {},
        underNameTbl: {
          _: { name: "under_tbl", columns: { col1: { name: "col1", dataType: "text" } } },
        },
        colsSymTbl: {
          name: "cols_sym_tbl",
          [Symbol.for("drizzle:Columns")]: {
            c1: { name: "c1", dataType: "text" },
          },
        },
        refVariantsTbl: {
          name: "ref_variants_tbl",
          c1: {
            name: "c1",
            dataType: "integer",
            references: () => ({ name: "targetColName", table: { _: { name: "under_target" } } }),
          },
          c2: {
            name: "c2",
            dataType: "integer",
            references: () => ({ table: { name: "direct_name_target" } }),
          },
          c3: {
            name: "c3",
            dataType: "integer",
            references: () => ({ table: {} }),
          },
        },
      };

      const parsedShapes = fromDrizzle(runtimeShapes);
      expect(parsedShapes.some((t) => t.name === "under_tbl")).toBe(true);
      expect(parsedShapes.some((t) => t.name === "cols_sym_tbl")).toBe(true);

      // 2. Single table with _: { name }
      const singleUnder = fromDrizzle({
        _: { name: "single_under" },
        id: { name: "id", dataType: "serial" },
      });
      expect(singleUnder[0].name).toBe("single_under");

      // 3. String code edge cases:
      // - anonymous table call: pgTable('anon')
      // - column comments, missing colon, non-call expr, empty args: id: serial(), trailing comma in pk
      const edgeCode = `
        export const singleLine = pgTable('single_line_tbl', { id: serial('id') });
        pgTable('anon_tbl', {
          // comment line without colon
          invalidProp,
          noExpr: ,
          nonCall: 123,
          noArgCol: serial(),
          ,
        }, (table) => ({
          pk: primaryKey(table.noArgCol, ),
        }));
      `;
      const edgeTables = fromDrizzle(edgeCode);
      expect(edgeTables.some((t) => t.name === "single_line_tbl")).toBe(true);
      expect(edgeTables.some((t) => t.name === "anon_tbl")).toBe(true);
      expect(edgeTables.find((t) => t.name === "anon_tbl")?.columns.some((c) => c.name === "noArgCol")).toBe(true);
    });
  });

  describe("9. JSON Schema adapter invalid JSON & single schema object", () => {
    it("handles invalid JSON string and single schema object", () => {
      const invalid = fromJsonSchema("{ not valid json");
      expect(invalid.length).toBe(1);
      expect(invalid[0].name).toBe("main");

      const singleObj = fromJsonSchema({
        title: "Account",
        type: "object",
        properties: {
          id: { type: "integer" },
        },
      });
      expect(singleObj.length).toBe(1);
      expect(singleObj[0].name).toBe("Account");
      expect(singleObj[0].columns[0].name).toBe("id");
    });

    it("handles primitive property definition, custom data types, and object foreign keys", () => {
      const schemaObj = {
        title: "Products",
        type: "object",
        properties: {
          id: { type: "integer", "x-primary-key": true },
          tag: "string", // primitive raw property definition
          rawCustom: { type: "custom_geom" }, // unknown data type
          vendorId: {
            type: "integer",
            "x-foreign-key": { table: "vendors", column: "v_id" },
          },
        },
      };

      const tables = fromJsonSchema(schemaObj);
      expect(tables[0].columns.find((c) => c.name === "tag")?.dataType).toBe("text");
      expect(tables[0].columns.find((c) => c.name === "rawCustom")?.dataType).toBe("custom_geom");
      const vendorFk = tables[0].foreignKeys.find((fk) => fk.column === "vendorId");
      expect(vendorFk?.foreignTable).toBe("vendors");
      expect(vendorFk?.foreignColumn).toBe("v_id");
    });

    it("parses primary_keys array in JSON Schema", () => {
      const schemaWithSnakePk = {
        title: "Accounts",
        type: "object",
        primary_keys: ["acc_id"],
        properties: {
          acc_id: { type: "integer" },
        },
      };
      const tables = fromJsonSchema(schemaWithSnakePk);
      expect(tables[0].primaryKeys).toEqual(["acc_id"]);
    });

    it("handles null source, empty schema, missing prop types, array types, formats, and empty x-foreign-key", () => {
      // 1. null source
      const fromNull = fromJsonSchema(null as any);
      expect(fromNull.length).toBe(0);

      // 2. empty schema definition with no properties
      const emptyDef = fromJsonSchema({ type: "object", title: "NoProps" }, { defaultSchema: "custom_json" });
      expect(emptyDef[0].schema).toBe("custom_json");
      expect(emptyDef[0].columns.length).toBe(0);

      // 3. Various formats, array types, and empty x-foreign-key
      const formatsSchema = {
        title: "AllFormats",
        type: "object",
        properties: {
          noType: { description: "only description" },
          nullType: { type: ["null"] },
          dtCol: { type: "string", format: "date-time" },
          dCol: { type: "string", format: "date" },
          uCol: { type: "string", format: "uuid" },
          i32Col: { type: "integer", format: "int32" },
          i64Col: { type: "integer", format: "int64" },
          fCol: { type: "number", format: "float" },
          fkEmpty: {
            type: "integer",
            "x-foreign-key": {},
          },
          emptyRef: {
            $ref: "http://example.com/",
          },
        },
      };

      const res = fromJsonSchema(formatsSchema);
      const cols = res[0].columns;
      expect(cols.find((c) => c.name === "dtCol")?.dataType).toBe("timestamp");
      expect(cols.find((c) => c.name === "dCol")?.dataType).toBe("date");
      expect(cols.find((c) => c.name === "uCol")?.dataType).toBe("uuid");
      expect(cols.find((c) => c.name === "i32Col")?.dataType).toBe("integer");
      expect(cols.find((c) => c.name === "i64Col")?.dataType).toBe("bigint");
      expect(cols.find((c) => c.name === "fCol")?.dataType).toBe("float");
      expect(cols.find((c) => c.name === "noType")?.dataType).toBe("text");
      expect(cols.find((c) => c.name === "nullType")?.dataType).toBe("text");
      expect(res[0].foreignKeys.some((fk) => fk.foreignColumn === "id")).toBe(true);
      expect(res[0].foreignKeys.some((fk) => fk.foreignTable === "unknown")).toBe(true);
    });
  });

  describe("10. Prisma adapter relation doc comment & default values", () => {
    it("parses relation model mapping, triple slash comments, and string defaults", () => {
      const prismaCode = `
        model User {
          id String @id /// Primary identifier
          role String @default("MEMBER")
          profile Profile? @relation(fields: [id], references: [userId])
        }

        model Profile {
          userId String @id
        }
      `;

      const tables = fromPrisma(prismaCode);
      const user = tables.find((t) => t.name === "User");
      expect(user?.columns[0].comment).toBe("Primary identifier");
      expect(user?.columns[1].default).toBe("MEMBER");
      expect(user?.foreignKeys?.[0].foreignTable).toBe("Profile");
    });

    it("parses Prisma schema string with @map, single-quoted default, and custom type", () => {
      const prismaCode = `
        model Account {
          id String @id
          mappedField String @map("db_mapped_col") @default('single_quoted_val')
          customCol UnknownCustomType
          authorId String
          author User @relation(fields: [authorId], references: [id])
        }

        model User {
          id String @id
        }
      `;
      const tables = fromPrisma(prismaCode);
      const acc = tables.find((t) => t.name === "Account");
      const mapped = acc?.columns.find((c) => c.name === "db_mapped_col");
      expect(mapped?.default).toBe("single_quoted_val");
      const custom = acc?.columns.find((c) => c.name === "customCol");
      expect(custom?.dataType).toBe("unknowncustomtype");
    });

    it("parses Prisma DMMF JSON runtime objects", () => {
      const dmmf = {
        datamodel: {
          enums: [
            { name: "RoleType", values: [{ name: "ADMIN" }, "USER"] },
            null,
          ],
          models: [
            {
              name: "User",
              dbName: "users",
              primaryKey: { fields: ["id"] },
              fields: [
                {
                  name: "id",
                  type: "Int",
                  isId: true,
                  isRequired: true,
                  default: { name: "autoincrement" },
                },
                { name: "roleId", type: "Int", isRequired: false },
                {
                  name: "role",
                  kind: "object",
                  type: "Role",
                  relationFromFields: ["roleId"],
                  relationToFields: ["id"],
                },
                { name: "roleType", type: "RoleType", kind: "enum" },
              ],
            },
            {
              name: "Role",
              dbName: "roles",
              fields: [{ name: "id", type: "Int", isId: true, isRequired: true }],
            },
            null,
          ],
        },
      };

      const tables = fromPrisma(dmmf);
      expect(tables.length).toBe(2);
      const user = tables.find((t) => t.name === "users");
      expect(user?.columns[0].default).toBe("autoincrement()");
      expect(user?.foreignKeys[0].foreignTable).toBe("roles");
      expect(user?.foreignKeys[0].foreignColumn).toBe("id");
      expect(user?.enums?.roleType).toEqual(["ADMIN", "USER"]);
    });

    it("handles DMMF edge cases and relation via mapped DB column", () => {
      // 1. DMMF with null enum values, non-array fields, and unknown type
      const dmmfEdge = {
        datamodel: {
          enums: [{ name: "NullEnum", values: null }],
          models: [
            {
              name: "EdgeModel",
              dbName: "edge_table",
              fields: null,
            },
            {
              name: "RelationEdge",
              fields: [
                { name: "id", type: "Int", isId: true },
                {
                  name: "ext",
                  kind: "object",
                  type: "ExternalModel",
                  relationFromFields: ["extId"],
                  relationToFields: ["id"],
                },
                { name: "extId", type: "UnsupportedType" },
                { name: "relNoFields", kind: "object", type: "Target" },
                { name: "relWithoutType", kind: "object", relationFromFields: ["x"], relationToFields: ["y"] },
                { name: "untyped_col" },
                { type: "String" },
                { name: "mappedCol", dbName: "db_mapped_name", type: "String" },
              ],
            },
          ],
        },
      };

      const fromDmmfRes = fromPrisma(dmmfEdge, { defaultSchema: "custom_dmmf" });
      expect(fromDmmfRes[0].schema).toBe("custom_dmmf");
      const relTable = fromDmmfRes.find((t) => t.name === "RelationEdge");
      expect(relTable?.foreignKeys[0].foreignTable).toBe("ExternalModel");
      expect(relTable?.columns.find((c) => c.name === "extId")?.dataType).toBe("unsupportedtype");

      // 2. Prisma string code with invalid single word line and relation mapped by column name
      const prismaString = `
        model Post {
          id String @id
          singleWordLine
          authorId String @map("author_col")
          author User @relation(fields: [author_col], references: [id])
        }
      `;
      const fromStrRes = fromPrisma(prismaString);
      const post = fromStrRes.find((t) => t.name === "Post");
      expect(post?.foreignKeys[0].foreignTable).toBe("User");
      expect(post?.foreignKeys[0].column).toBe("author_col");
    });
  });

  describe("11. SQLAlchemy adapter literal column name & Mapped type annotations", () => {
    it("parses literal column name and Mapped[type] annotations without explicit type tokens", () => {
      const saCode = `
        from sqlalchemy import Column, Integer, String
        from sqlalchemy.orm import declarative_base, Mapped, mapped_column

        Base = declarative_base()

        class Entity(Base):
            __tablename__ = "entities"
            custom_id = Column('db_custom_id', Integer, primary_key=True)
            age: Mapped[int] = mapped_column()
            active: Mapped[bool] = mapped_column()
            ratio: Mapped[float] = mapped_column()
            bio: Mapped[str] = mapped_column()
      `;

      const tables = fromSqlAlchemy(saCode);
      const entity = tables.find((t) => t.name === "entities");
      expect(entity?.primaryKeys).toEqual(["db_custom_id"]);
      const colMap = Object.fromEntries(entity?.columns.map((c) => [c.name, c.dataType]) || []);
      expect(colMap.age).toBe("integer");
      expect(colMap.active).toBe("boolean");
      expect(colMap.ratio).toBe("float");
      expect(colMap.bio).toBe("text");
    });

    it("handles class without __tablename__, composite PK constraint, and runtime dictionary input", () => {
      const saCode = `
        from sqlalchemy import Column, Integer, String, PrimaryKeyConstraint
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class UserProfile(Base):
            user_id = Column(Integer)
            org_id = Column(Integer)
            __table_args__ = (PrimaryKeyConstraint('user_id', 'org_id'),)
      `;

      const tables = fromSqlAlchemy(saCode);
      const profile = tables.find((t) => t.name === "user_profile");
      expect(profile?.primaryKeys).toEqual(["user_id", "org_id"]);

      // Runtime dictionary object
      const runtimeSa = {
        tables: {
          accounts: {
            schema: "billing",
            columns: [
              { name: "acc_id", is_primary: true, type: "integer" },
              { name: "balance", is_nullable: false, type: "numeric" },
            ],
          },
        },
      };

      const fromObj = fromSqlAlchemy(runtimeSa);
      expect(fromObj.length).toBe(1);
      expect(fromObj[0].name).toBe("accounts");
      expect(fromObj[0].schema).toBe("billing");
      expect(fromObj[0].primaryKeys).toEqual(["acc_id"]);
      expect(fromObj[0].columns[1].isNullable).toBe(false);
    });

    it("parses SQLAlchemy comment, Enum without =, SmallInteger, and non-assignment Column line", () => {
      const saCode = `
        from sqlalchemy import Column, Integer, SmallInteger, Enum
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class AdvancedModel(Base):
            __tablename__ = "advanced"
            print(Column(Integer))
            status = Column(Enum('ACTIVE', 'PENDING', name='status_enum'))
            level = Column(SmallInteger, comment="small int level")
      `;
      const tables = fromSqlAlchemy(saCode);
      const adv = tables.find((t) => t.name === "advanced");
      const levelCol = adv?.columns.find((c) => c.name === "level");
      expect(levelCol?.dataType).toBe("integer");
      expect(levelCol?.comment).toBe("small int level");
      const statusCol = adv?.columns.find((c) => c.name === "status");
      expect(statusCol?.enums).toEqual(["ACTIVE", "PENDING"]);
    });

    it("handles SQLAlchemy dictionary input with tables key, non-object table def, and custom data types", () => {
      const runtimeSa = {
        tables: {
          invalid: null,
          users: {
            columns: [
              { name: "id", is_primary: true },
              { type: "integer" },
              { dataType: "custom_geom" },
              { name: "val" },
            ],
          },
        },
      };

      const res = fromSqlAlchemy(runtimeSa, { defaultSchema: "custom_sa" });
      expect(res.length).toBe(1);
      expect(res[0].schema).toBe("custom_sa");
      expect(res[0].columns[0].isPrimary).toBe(true);
      expect(res[0].columns[1].name).toBe("");
      expect(res[0].columns[2].dataType).toBe("custom_geom");
      expect(res[0].columns[3].dataType).toBe("text");

      // Direct table dictionary without tables key (covers line 42 source.tables || source)
      const directSa = fromSqlAlchemy({ direct_tbl: { columns: [{ name: "id" }] } });
      expect(directSa[0].name).toBe("direct_tbl");

      // Double-quoted enum in code (covers line 177 v.startsWith('"'))
      const saDoubleEnum = `
        from sqlalchemy import Column, Enum
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        class DoubleEnumModel(Base):
            __tablename__ = "double_enum"
            status = Column(Enum("OPT_A", "OPT_B"))
      `;
      const doubleEnumRes = fromSqlAlchemy(saDoubleEnum);
      expect(doubleEnumRes[0].columns[0].enums).toEqual(["OPT_A", "OPT_B"]);
    });
  });
});
