// @vitest-environment node
import { describe, it, expect } from "vitest";
import React from "react";
import { renderToString } from "react-dom/server";
import {
  VisualQueryBuilder,
  QueryPlayground,
  QueryCanvas,
  TableCard,
  TableFiltersEditor,
  TableJoinEditor,
  TableSortsEditor,
  QueryResultsTable,
  QueryChartPreview,
  useQueryBuilder,
  useQueryState,
  useSqlCompiler,
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

describe("SSR Hydration Safety (Pure Node Environment)", () => {
  it("confirms pure Node.js server environment without DOM globals", () => {
    expect(typeof window).toBe("undefined");
    expect(typeof document).toBe("undefined");
  });

  it("renders VisualQueryBuilder to string without throwing reference errors", () => {
    const html = renderToString(
      <VisualQueryBuilder schema={sampleSchema} initialTable="users" />,
    );
    expect(html).toContain('data-qb="root"');
    expect(html).toContain("users");
    expect(html).toContain("Visual Builder");
  });

  it("renders VisualQueryBuilder unstyled={true} to string", () => {
    const html = renderToString(
      <VisualQueryBuilder schema={sampleSchema} initialTable="users" unstyled={true} />,
    );
    expect(html).toContain('data-qb-unstyled="true"');
    expect(html).toContain('data-qb="top-bar"');
  });

  it("renders QueryPlayground to string without throwing reference errors", () => {
    const html = renderToString(<QueryPlayground schema={sampleSchema} />);
    expect(html).toContain('data-qb="playground-root"');
    expect(html).toContain("Query-Builder Playground");
  });

  it("renders QueryPlayground unstyled={true} to string", () => {
    const html = renderToString(
      <QueryPlayground schema={sampleSchema} unstyled={true} />,
    );
    expect(html).toContain('data-qb-unstyled="true"');
    expect(html).toContain('data-qb="playground-root"');
  });

  it("renders QueryResultsTable to string", () => {
    const html = renderToString(
      <QueryResultsTable results={sampleResults} />,
    );
    expect(html).toContain('data-qb="results-table-root"');
    expect(html).toContain("alice@example.com");
  });

  it("renders QueryChartPreview to string", () => {
    const html = renderToString(
      <QueryChartPreview results={sampleResults} />,
    );
    expect(html).toContain('data-qb="chart-preview-root"');
    expect(html).toContain("<svg");
  });

  it("renders child components to string", () => {
    const canvasHtml = renderToString(
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
      />,
    );
    expect(canvasHtml).toContain('data-qb="canvas"');

    const cardHtml = renderToString(
      <TableCard
        table={sampleSchema.tables.users}
        selectedColumns={{}}
        onToggleColumn={() => {}}
      />,
    );
    expect(cardHtml).toContain('data-qb="table-card"');

    const filtersHtml = renderToString(
      <TableFiltersEditor
        filters={[{ id: "f1", tablePrefix: "users", column: "id", operator: "=", value: 1 }]}
        activeTables={[sampleSchema.tables.users]}
        onChange={() => {}}
      />,
    );
    expect(filtersHtml).toContain('data-qb="filters-editor"');

    const joinsHtml = renderToString(
      <TableJoinEditor
        joins={[]}
        activeTables={[sampleSchema.tables.users]}
        allTables={[sampleSchema.tables.users]}
        onChange={() => {}}
      />,
    );
    expect(joinsHtml).toContain('data-qb="joins-editor"');

    const sortsHtml = renderToString(
      <TableSortsEditor
        sorts={[]}
        activeTables={[sampleSchema.tables.users]}
        onChange={() => {}}
      />,
    );
    expect(sortsHtml).toContain('data-qb="sorts-editor"');
  });

  it("executes headless hooks during SSR render without DOM", () => {
    const TestComponent = () => {
      const qb = useQueryBuilder({ schema: sampleSchema, initialTable: "users" });
      const qs = useQueryState({ table: "users", limit: 10 });
      const qc = useSqlCompiler({ table: "users", columns: ["users.id"] });

      return (
        <div>
          <span id="qb-sql">{qb.compiled.sql}</span>
          <span id="qs-limit">{qs.state.limit}</span>
          <span id="qc-sql">{qc.sql}</span>
        </div>
      );
    };

    const html = renderToString(<TestComponent />);
    expect(html).toContain('FROM &quot;users&quot;');
    expect(html).toContain("10");
  });
});
