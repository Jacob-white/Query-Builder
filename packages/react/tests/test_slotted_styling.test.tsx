import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import {
  QueryBuilder,
  QueryBuilderCanvas,
  QueryBuilderColumns,
  QueryBuilderFilters,
  QueryBuilderJoins,
  QueryBuilderSorts,
  QueryBuilderResults,
  QueryBuilderSqlEditor,
} from "../src/components/compound";
import type { SchemaSnapshot, QuerySpec, QueryResultData } from "../src/types";
import { makeSpec } from "./helpers";

describe("Milestone 3: Slotted Styling & ClassNames API", () => {
  const mockSchema: SchemaSnapshot = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "name", data_type: "text", is_nullable: false, is_primary: false },
        ],
      },
      orders: {
        name: "orders",
        columns: [
          { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
        ],
      },
    },
    foreign_keys: [
      {
        table: "orders",
        column: "user_id",
        foreign_table: "users",
        foreign_column: "id",
      },
    ],
  };

  const sampleSpec: QuerySpec = makeSpec({
    table: "users",
    columns: ["users.id", "users.name"],
    filters: [{ column: "users.name", op: "=", value: "Alice" }],
    order_by: [{ column: "users.name", direction: "ASC" }],
    joins: [
      {
        table: "orders",
        type: "LEFT JOIN",
        left_col: "id",
        right_col: "user_id",
        on: [{ left: "users.id", right: "orders.user_id" }],
      },
    ],
  });

  it("applies classNames and className to VisualQueryBuilder root, header, tabs, and canvas slots", () => {
    const { container } = render(
      <VisualQueryBuilder
        schema={mockSchema}
        initialSpec={sampleSpec}
        className="custom-root-class"
        classNames={{
          root: "tw-bg-slate-900 tw-rounded-2xl",
          header: "tw-border-b tw-p-4",
          tabs: "tw-flex tw-gap-2",
          tab: "tw-px-3 tw-py-1 tw-rounded",
          tabActive: "tw-bg-blue-600 tw-text-white",
          canvas: "tw-p-6 tw-space-y-4",
          tableCard: "tw-bg-slate-800 tw-shadow-xl",
          tableCardHeader: "tw-p-3 tw-font-bold",
          tableCardTitle: "tw-text-blue-400",
          columnList: "tw-divide-y",
          columnItem: "tw-hover:bg-slate-700",
          columnCheckbox: "tw-accent-blue-500",
          columnName: "tw-font-medium",
          columnType: "tw-text-xs tw-text-gray-400",
          columns: "tw-bg-slate-800/80 tw-rounded-lg",
          columnsHeader: "tw-flex tw-justify-between",
          projectionItem: "tw-badge tw-bg-blue-900/50",
          filters: "tw-bg-slate-800/90",
          filterItem: "tw-border tw-border-slate-700",
          filterAddButton: "tw-btn tw-btn-primary",
          joins: "tw-bg-slate-800/70",
          joinItem: "tw-border tw-border-blue-900",
          sorts: "tw-bg-slate-800/60",
          sortItem: "tw-border tw-border-purple-900",
          sortAddButton: "tw-btn tw-btn-secondary",
          tableCardBadge: "tw-badge-pk",
          title: "tw-section-title",
        }}
      />,
    );

    // Root element
    const rootEl = container.querySelector('[data-qb="root"]');
    expect(rootEl?.className).toContain("custom-root-class");
    expect(rootEl?.className).toContain("tw-bg-slate-900");
    expect(rootEl?.className).toContain("tw-rounded-2xl");

    // Header / top-bar
    const headerEl = container.querySelector('[data-qb="top-bar"]');
    expect(headerEl?.className).toContain("tw-border-b");
    expect(headerEl?.className).toContain("tw-p-4");

    // Tabs container
    const tabsEl = container.querySelector('[data-qb="tab-list"]');
    expect(tabsEl?.className).toContain("tw-flex");
    expect(tabsEl?.className).toContain("tw-gap-2");

    // Active Tab button
    const activeTabEl = container.querySelector('[data-qb-tab="visual"]');
    expect(activeTabEl?.className).toContain("tw-px-3");
    expect(activeTabEl?.className).toContain("tw-bg-blue-600");
    expect(activeTabEl?.className).toContain("tw-text-white");

    // Inactive Tab button
    const inactiveTabEl = container.querySelector('[data-qb-tab="sql"]');
    expect(inactiveTabEl?.className).toContain("tw-px-3");
    expect(inactiveTabEl?.className).not.toContain("tw-bg-blue-600");

    // Canvas container
    const canvasEl = container.querySelector('[data-qb="canvas"]');
    expect(canvasEl?.className).toContain("tw-p-6");
    expect(canvasEl?.className).toContain("tw-space-y-4");

    // TableCard
    const tableCardEl = container.querySelector('[data-qb="table-card"]');
    expect(tableCardEl?.className).toContain("tw-bg-slate-800");
    expect(tableCardEl?.className).toContain("tw-shadow-xl");

    // TableCard header & title
    const cardHeader = container.querySelector('[data-qb="table-card-header"]');
    expect(cardHeader?.className).toContain("tw-p-3");

    const cardTitle = container.querySelector('[data-qb="table-card-title"]');
    expect(cardTitle?.className).toContain("tw-text-blue-400");

    // TableCard PK badge
    const pkBadge = container.querySelector('[data-qb="table-card-badge-pk"]');
    expect(pkBadge?.className).toContain("tw-badge-pk");

    // Columns section
    const columnsEl = container.querySelector('[data-qb="canvas-projections"]');
    expect(columnsEl?.className).toContain("tw-bg-slate-800/80");

    // Projection items
    const projectionItem = container.querySelector('[data-qb="projection-item"]');
    expect(projectionItem?.className).toContain("tw-badge");

    // Filters editor
    const filtersEl = container.querySelector('[data-qb="filters-editor"]');
    expect(filtersEl?.className).toContain("tw-bg-slate-800/90");

    const filterAddBtn = container.querySelector('[data-qb="btn-add-filter"]');
    expect(filterAddBtn?.className).toContain("tw-btn-primary");

    // Joins editor
    const joinsEl = container.querySelector('[data-qb="joins-editor"]');
    expect(joinsEl?.className).toContain("tw-bg-slate-800/70");

    // Sorts editor
    const sortsEl = container.querySelector('[data-qb="sorts-editor"]');
    expect(sortsEl?.className).toContain("tw-bg-slate-800/60");

    // Section title
    const filterTitle = container.querySelector('[data-qb="filters-editor"] span');
    expect(filterTitle?.className).toContain("tw-section-title");
  });

  it("applies classNames to compound component primitives directly", () => {
    const mockResults: QueryResultData = {
      columns: ["id", "name"],
      rows: [{ id: 1, name: "Alice" }],
      count: 1,
    };

    const { container } = render(
      <QueryBuilder.Root
        schema={mockSchema}
        initialSpec={sampleSpec}
        className="compound-root-tailwind"
        classNames={{
          root: "tw-card",
          canvas: "tw-canvas-grid",
          columns: "tw-columns-chip-group",
          filters: "tw-filters-container",
          joins: "tw-joins-container",
          sorts: "tw-sorts-container",
          sqlEditor: "tw-sql-wrapper",
          sqlTextarea: "tw-font-mono tw-bg-black",
          results: "tw-results-wrapper",
          resultsTable: "tw-table-auto tw-w-full",
          resultsRow: "tw-border-b tw-border-slate-800",
          resultsCell: "tw-px-4 tw-py-2",
        }}
      >
        <QueryBuilderCanvas className="canvas-override" />
        <QueryBuilderColumns className="columns-override" />
        <QueryBuilderFilters className="filters-override" />
        <QueryBuilderJoins className="joins-override" />
        <QueryBuilderSorts className="sorts-override" />
        <QueryBuilderSqlEditor className="sql-override" />
        <QueryBuilderResults results={mockResults} className="results-override" />
      </QueryBuilder.Root>,
    );

    // Root
    const rootEl = container.querySelector('[data-qb="root"]');
    expect(rootEl?.className).toContain("compound-root-tailwind");
    expect(rootEl?.className).toContain("tw-card");

    // Canvas
    const canvasEl = container.querySelector('[data-qb="canvas"]');
    expect(canvasEl?.className).toContain("canvas-override");
    expect(canvasEl?.className).toContain("tw-canvas-grid");

    // Columns
    const columnsEl = container.querySelector('[data-qb="canvas-projections"]');
    expect(columnsEl?.className).toContain("columns-override");
    expect(columnsEl?.className).toContain("tw-columns-chip-group");

    // Filters
    const filtersEl = container.querySelector('[data-qb="filters-editor"]');
    expect(filtersEl?.className).toContain("filters-override");
    expect(filtersEl?.className).toContain("tw-filters-container");

    // Joins
    const joinsEl = container.querySelector('[data-qb="joins-editor"]');
    expect(joinsEl?.className).toContain("joins-override");
    expect(joinsEl?.className).toContain("tw-joins-container");

    // Sorts
    const sortsEl = container.querySelector('[data-qb="sorts-editor"]');
    expect(sortsEl?.className).toContain("sorts-override");
    expect(sortsEl?.className).toContain("tw-sorts-container");

    // SQL Editor
    const sqlEl = container.querySelector('[data-qb="sql-editor-panel"]');
    expect(sqlEl?.className).toContain("sql-override");
    expect(sqlEl?.className).toContain("tw-sql-wrapper");

    const sqlTextarea = container.querySelector('[data-qb="sql-editor"]');
    expect(sqlTextarea?.className).toContain("tw-font-mono");
    expect(sqlTextarea?.className).toContain("tw-bg-black");

    // Results table
    const resultsEl = container.querySelector('[data-qb="results-table-root"]');
    expect(resultsEl?.className).toContain("results-override");
    expect(resultsEl?.className).toContain("tw-results-wrapper");

    const tableEl = container.querySelector('[data-qb="results-table"]');
    expect(tableEl?.className).toContain("tw-table-auto");

    const rowEl = container.querySelector('tbody tr[role="row"]');
    expect(rowEl?.className).toContain("tw-border-b");

    const cellEl = container.querySelector('tbody td[role="cell"]');
    expect(cellEl?.className).toContain("tw-px-4");
  });
});
