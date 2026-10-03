import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, fireEvent, act } from "@testing-library/react";
import {
  VisualQueryBuilder,
  QueryCanvas,
  TableCard,
  TableFiltersEditor,
  TableJoinEditor,
  TableSortsEditor,
  QueryResultsTable,
  QueryChartPreview,
  QueryTemplateManager,
  type SchemaSnapshot,
  type QueryResultData,
} from "../src";

const sampleSchema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
  },
};

const sampleResults: QueryResultData = {
  columns: ["id", "email"],
  rows: [{ id: 1, email: "alice@example.com" }],
  count: 1,
};

describe("Zero-CSS Unstyled Mode & Semantic Data Attributes", () => {
  it("renders VisualQueryBuilder with unstyled={true} having data-qb attributes and no default inline styles", () => {
    const { container } = render(
      <VisualQueryBuilder schema={sampleSchema} initialTable="users" unstyled={true} />,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBe("true");
    expect(root?.getAttribute("data-qb-mode")).toBe("visual");

    // Root should have no style attribute or empty style
    expect(root?.getAttribute("style")).toBeNull();

    // Check top bar and tab list
    const topBar = container.querySelector('[data-qb="top-bar"]');
    expect(topBar).not.toBeNull();
    expect(topBar?.getAttribute("style")).toBeNull();

    const tabList = container.querySelector('[data-qb="tab-list"]');
    expect(tabList).not.toBeNull();
    expect(tabList?.getAttribute("style")).toBeNull();

    const tabs = container.querySelectorAll('[data-qb="tab"]');
    expect(tabs.length).toBe(4);
    tabs.forEach((tab) => {
      expect(tab.getAttribute("style")).toBeNull();
    });

    const runBtn = container.querySelector('[data-qb="btn-run"]');
    expect(runBtn).not.toBeNull();
    expect(runBtn?.getAttribute("style")).toBeNull();

    const safetyBadge = container.querySelector('[data-qb="safety-badge"]');
    expect(safetyBadge).not.toBeNull();
    expect(safetyBadge?.getAttribute("style")).toBeNull();
  });

  it("renders VisualQueryBuilder with unstyled={false} (default) preserving inline styles", () => {
    const { container } = render(
      <VisualQueryBuilder schema={sampleSchema} initialTable="users" />,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBeNull();
    expect(root?.getAttribute("style")).toContain("display: flex");
  });

  it("renders QueryCanvas with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <QueryCanvas
        schema={sampleSchema}
        activeTables={[sampleSchema.tables.users]}
        primaryTable="users"
        selectedColumns={{ "users.id": { table: "users", name: "id" } }}
        orderedProjectionKeys={["users.id"]}
        joins={[]}
        filters={[]}
        sorts={[]}
        isDistinct={false}
        limit={50}
        onToggleColumn={() => {}}
        onRemoveTable={() => {}}
        onAddTableToCanvas={() => {}}
        onUpdateColumnSelect={() => {}}
        onRemoveColumnProjection={() => {}}
        onJoinsChange={() => {}}
        onFiltersChange={() => {}}
        onSortsChange={() => {}}
        onDistinctChange={() => {}}
        onLimitChange={() => {}}
        unstyled={true}
      />,
    );

    const canvas = container.querySelector('[data-qb="canvas"]');
    expect(canvas).not.toBeNull();
    expect(canvas?.getAttribute("style")).toBeNull();

    const canvasTables = container.querySelector('[data-qb="canvas-tables"]');
    expect(canvasTables).not.toBeNull();
    expect(canvasTables?.getAttribute("style")).toBeNull();

    const tableCardsList = container.querySelector('[data-qb="table-cards-list"]');
    expect(tableCardsList).not.toBeNull();
    expect(tableCardsList?.getAttribute("style")).toBeNull();

    const projections = container.querySelector('[data-qb="canvas-projections"]');
    expect(projections).not.toBeNull();
    expect(projections?.getAttribute("style")).toBeNull();

    const projItem = container.querySelector('[data-qb="projection-item"]');
    expect(projItem).not.toBeNull();
    expect(projItem?.getAttribute("data-qb-column")).toBe("users.id");
    expect(projItem?.getAttribute("style")).toBeNull();

    const distinct = container.querySelector('[data-qb="checkbox-distinct"]');
    expect(distinct).not.toBeNull();

    const limit = container.querySelector('[data-qb="input-limit"]');
    expect(limit).not.toBeNull();
  });

  it("renders TableCard with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <TableCard
        table={sampleSchema.tables.users}
        isSelected={true}
        selectedColumns={{ "users.id": { table: "users", name: "id" } }}
        onToggleColumn={() => {}}
        onRemoveTable={() => {}}
        onAddJoin={() => {}}
        unstyled={true}
      />,
    );

    const card = container.querySelector('[data-qb="table-card"]');
    expect(card).not.toBeNull();
    expect(card?.getAttribute("data-qb-table")).toBe("users");
    expect(card?.getAttribute("data-qb-selected")).toBe("true");
    expect(card?.getAttribute("style")).toBeNull();

    const header = container.querySelector('[data-qb="table-card-header"]');
    expect(header).not.toBeNull();

    const title = container.querySelector('[data-qb="table-card-title"]');
    expect(title).not.toBeNull();
    expect(title?.textContent).toBe("users");

    const joinBtn = container.querySelector('[data-qb="table-card-btn-join"]');
    expect(joinBtn).not.toBeNull();

    const removeBtn = container.querySelector('[data-qb="table-card-btn-remove"]');
    expect(removeBtn).not.toBeNull();

    const colList = container.querySelector('[data-qb="table-card-columns-list"]');
    expect(colList).not.toBeNull();

    const colRows = container.querySelectorAll('[data-qb="table-card-column-row"]');
    expect(colRows.length).toBe(2);
    expect(colRows[0].getAttribute("data-qb-column")).toBe("id");
    expect(colRows[0].getAttribute("data-qb-selected")).toBe("true");

    const checkbox = container.querySelector('[data-qb="table-card-column-checkbox"]');
    expect(checkbox).not.toBeNull();

    const colType = container.querySelector('[data-qb="table-card-column-type"]');
    expect(colType).not.toBeNull();
  });

  it("renders TableFiltersEditor with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <TableFiltersEditor
        filters={[
          { id: "f1", tablePrefix: "users", column: "id", operator: ">", value: 5 },
          { id: "f2", tablePrefix: "users", column: "email", operator: "LIKE", value: "%@gmail%" },
        ]}
        activeTables={[sampleSchema.tables.users]}
        onChange={() => {}}
        unstyled={true}
      />,
    );

    const editor = container.querySelector('[data-qb="filters-editor"]');
    expect(editor).not.toBeNull();
    expect(editor?.getAttribute("style")).toBeNull();

    const header = container.querySelector('[data-qb="filters-header"]');
    expect(header).not.toBeNull();

    const addBtn = container.querySelector('[data-qb="btn-add-filter"]');
    expect(addBtn).not.toBeNull();

    const rows = container.querySelectorAll('[data-qb="filter-row"]');
    expect(rows.length).toBe(2);

    const combiner = container.querySelector('[data-qb="filter-combiner"]');
    expect(combiner).not.toBeNull();

    const colSelect = container.querySelector('[data-qb="filter-column"]');
    expect(colSelect).not.toBeNull();

    const opSelect = container.querySelector('[data-qb="filter-operator"]');
    expect(opSelect).not.toBeNull();

    const valInput = container.querySelector('[data-qb="filter-value"]');
    expect(valInput).not.toBeNull();

    const removeBtn = container.querySelector('[data-qb="btn-remove-filter"]');
    expect(removeBtn).not.toBeNull();
  });

  it("renders TableJoinEditor with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <TableJoinEditor
        joins={[
          {
            id: "j1",
            type: "LEFT JOIN",
            left_table: "users",
            left_col: "id",
            table: "orders",
            right_col: "user_id",
          },
        ]}
        activeTables={[sampleSchema.tables.users]}
        allTables={[sampleSchema.tables.users, sampleSchema.tables.orders]}
        onChange={() => {}}
        unstyled={true}
      />,
    );

    const editor = container.querySelector('[data-qb="joins-editor"]');
    expect(editor).not.toBeNull();
    expect(editor?.getAttribute("style")).toBeNull();

    const header = container.querySelector('[data-qb="joins-header"]');
    expect(header).not.toBeNull();

    const addSelect = container.querySelector('[data-qb="select-add-join"]');
    expect(addSelect).not.toBeNull();

    const joinRow = container.querySelector('[data-qb="join-row"]');
    expect(joinRow).not.toBeNull();
    expect(joinRow?.getAttribute("data-qb-join-id")).toBe("j1");

    const joinType = container.querySelector('[data-qb="join-type"]');
    expect(joinType).not.toBeNull();

    const leftCol = container.querySelector('[data-qb="join-left-col"]');
    expect(leftCol).not.toBeNull();

    const rightCol = container.querySelector('[data-qb="join-right-col"]');
    expect(rightCol).not.toBeNull();

    const removeBtn = container.querySelector('[data-qb="btn-remove-join"]');
    expect(removeBtn).not.toBeNull();
  });

  it("renders TableSortsEditor with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <TableSortsEditor
        sorts={[{ id: "s1", tablePrefix: "users", column: "id", direction: "ASC" }]}
        activeTables={[sampleSchema.tables.users]}
        onChange={() => {}}
        unstyled={true}
      />,
    );

    const editor = container.querySelector('[data-qb="sorts-editor"]');
    expect(editor).not.toBeNull();
    expect(editor?.getAttribute("style")).toBeNull();

    const header = container.querySelector('[data-qb="sorts-header"]');
    expect(header).not.toBeNull();

    const addBtn = container.querySelector('[data-qb="btn-add-sort"]');
    expect(addBtn).not.toBeNull();

    const sortRow = container.querySelector('[data-qb="sort-row"]');
    expect(sortRow).not.toBeNull();

    const sortCol = container.querySelector('[data-qb="sort-column"]');
    expect(sortCol).not.toBeNull();

    const sortDir = container.querySelector('[data-qb="sort-direction"]');
    expect(sortDir).not.toBeNull();

    const removeBtn = container.querySelector('[data-qb="btn-remove-sort"]');
    expect(removeBtn).not.toBeNull();
  });

  it("renders QueryResultsTable with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <QueryResultsTable results={sampleResults} unstyled={true} />,
    );

    const root = container.querySelector('[data-qb="results-table-root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("style")).toBeNull();

    const toolbar = container.querySelector('[data-qb="results-toolbar"]');
    expect(toolbar).not.toBeNull();

    const pagination = container.querySelector('[data-qb="results-pagination"]');
    expect(pagination).not.toBeNull();

    const exportCsv = container.querySelector('[data-qb="btn-export-csv"]');
    expect(exportCsv).not.toBeNull();

    const exportJson = container.querySelector('[data-qb="btn-export-json"]');
    expect(exportJson).not.toBeNull();

    const table = container.querySelector('[data-qb="results-table"]');
    expect(table).not.toBeNull();

    const ths = container.querySelectorAll('[data-qb="results-th"]');
    expect(ths.length).toBe(2);

    const tds = container.querySelectorAll('[data-qb="results-td"]');
    expect(tds.length).toBe(2);
  });

  it("renders QueryChartPreview with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <QueryChartPreview results={sampleResults} unstyled={true} />,
    );

    const root = container.querySelector('[data-qb="chart-preview-root"]');
    expect(root).not.toBeNull();

    const controls = container.querySelector('[data-qb="chart-controls"]');
    expect(controls).not.toBeNull();

    const typeSelect = container.querySelector('[data-qb="select-chart-type"]');
    expect(typeSelect).not.toBeNull();

    const chartContainer = container.querySelector('[data-qb="chart-display-container"]');
    expect(chartContainer).not.toBeNull();
  });

  it("renders QueryTemplateManager with unstyled={true} and semantic attributes", () => {
    const { container } = render(
      <QueryTemplateManager
        isOpen={true}
        onClose={() => {}}
        onLoadTemplate={() => {}}
        unstyled={true}
      />,
    );

    const backdrop = container.querySelector('[data-qb="modal-backdrop"]');
    expect(backdrop).not.toBeNull();
    expect(backdrop?.getAttribute("style")).toBeNull();

    const modal = container.querySelector('[data-qb="template-manager-modal"]');
    expect(modal).not.toBeNull();
    expect(modal?.getAttribute("style")).toBeNull();

    const cards = container.querySelectorAll('[data-qb="template-card"]');
    expect(cards.length).toBeGreaterThan(0);
    cards.forEach((c) => {
      expect(c.getAttribute("style")).toBeNull();
    });
  });

  it("renders VisualQueryBuilder code editor tab in unstyled mode", () => {
    const { container } = render(
      <VisualQueryBuilder schema={sampleSchema} initialTable="users" unstyled={true} />,
    );
    const codeTab = container.querySelector('[data-qb="tab"][data-qb-tab="sql"]');
    expect(codeTab).not.toBeNull();
    fireEvent.click(codeTab!);

    const sqlEditor = container.querySelector('[data-qb="sql-editor"]');
    expect(sqlEditor).not.toBeNull();
    expect(sqlEditor?.getAttribute("style")).toBeNull();
  });

  it("renders QueryResultsTable loading, empty, and latency states in unstyled mode", () => {
    const { container: loadingContainer } = render(
      <QueryResultsTable results={null} isLoading={true} unstyled={true} />,
    );
    const loadingRoot = loadingContainer.querySelector('[data-qb="results-table-root"]');
    expect(loadingRoot?.getAttribute("style")).toBeNull();

    const { container: emptyContainer } = render(
      <QueryResultsTable results={null} isLoading={false} unstyled={true} />,
    );
    const emptyRoot = emptyContainer.querySelector('[data-qb="results-table-root"]');
    expect(emptyRoot?.getAttribute("style")).toBeNull();

    const { container: latencyContainer } = render(
      <QueryResultsTable
        results={{ ...sampleResults, latency_ms: 42 }}
        unstyled={true}
      />,
    );
    expect(latencyContainer.textContent).toContain("42 ms");
  });

  it("renders TableFiltersEditor with BETWEEN operator", () => {
    const { container } = render(
      <TableFiltersEditor
        filters={[{ id: "f1", tablePrefix: "users", column: "id", operator: "BETWEEN", value: "1 AND 10" }]}
        activeTables={[sampleSchema.tables.users]}
        onChange={() => {}}
        unstyled={true}
      />,
    );
    const input = container.querySelector('[data-qb="filter-value"]') as HTMLInputElement;
    expect(input.placeholder).toBe("10 AND 50");
  });

  it("renders VisualQueryBuilder presets and execution error banner in unstyled mode", async () => {
    const onExecuteQuery = vi.fn().mockRejectedValue(new Error("Database timeout"));
    const { container } = render(
      <VisualQueryBuilder
        schema={sampleSchema}
        initialTable="users"
        presets={[{ id: "p1", title: "Preset 1", sql: "SELECT 1;" }]}
        onExecuteQuery={onExecuteQuery}
        unstyled={true}
      />,
    );
    const presetSelect = container.querySelector('select[aria-label="Starter query presets"]');
    expect(presetSelect).not.toBeNull();
    expect(presetSelect?.getAttribute("style")).toBeNull();

    const runBtn = container.querySelector('[data-qb="btn-run"]') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(runBtn);
    });

    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.getAttribute("style")).toBeNull();
    expect(alert?.textContent).toContain("Database timeout");
  });

  it("renders QueryResultsTable null cells in unstyled mode", () => {
    const { container } = render(
      <QueryResultsTable
        results={{
          columns: ["email"],
          rows: [{ email: null }],
          count: 1,
        }}
        unstyled={true}
      />,
    );
    const span = container.querySelector('[data-qb="results-td"] span');
    expect(span?.textContent).toBe("null");
    expect(span?.getAttribute("style")).toBeNull();
  });

  it("renders TableFiltersEditor with undefined filter value", () => {
    const { container } = render(
      <TableFiltersEditor
        filters={[{ id: "f1", tablePrefix: "users", column: "id", operator: ">", value: undefined as any }]}
        activeTables={[sampleSchema.tables.users]}
        onChange={() => {}}
        unstyled={true}
      />,
    );
    const input = container.querySelector('[data-qb="filter-value"]') as HTMLInputElement;
    expect(input.value).toBe("");
  });
});
