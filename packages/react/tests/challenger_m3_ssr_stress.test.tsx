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
  QueryTemplateManager,
  useQueryBuilder,
  useQueryState,
  useSqlCompiler,
  type SchemaSnapshot,
  type QueryResultData,
} from "../src";

const complexSsrSchema: SchemaSnapshot = {
  tables: {
    accounts: {
      name: "accounts",
      columns: [
        { name: "id", data_type: "int", is_nullable: false, is_primary: true },
        { name: "organization_id", data_type: "int", is_nullable: false, is_primary: false },
        { name: "balance", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
    organizations: {
      name: "organizations",
      columns: [
        { name: "id", data_type: "int", is_nullable: false, is_primary: true },
        { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
  },
  foreign_keys: [
    {
      table: "accounts",
      column: "organization_id",
      foreign_table: "organizations",
      foreign_column: "id",
    },
  ],
};

const complexSsrResults: QueryResultData = {
  columns: ["id", "balance", "org_name"],
  rows: [
    { id: 1, balance: 1000.5, org_name: "Acme Corp" },
    { id: 2, balance: null, org_name: "Beta Inc" },
  ],
  count: 2,
  latency_ms: 38,
};

describe("Milestone 3 SSR Hydration Safety & Pure Node Stress Harness", () => {
  it("verifies server execution environment has zero DOM globals", () => {
    expect(typeof window).toBe("undefined");
    expect(typeof document).toBe("undefined");
  });

  it("renders all 10 components under SSR without window/document/navigator crashes", () => {
    // 1. VisualQueryBuilder
    const vqbHtml = renderToString(
      <VisualQueryBuilder
        schema={complexSsrSchema}
        initialTable="accounts"
        unstyled={true}
      />,
    );
    expect(vqbHtml).toContain('data-qb="root"');
    expect(vqbHtml).toContain('data-qb-unstyled="true"');

    // 2. QueryPlayground
    const playgroundHtml = renderToString(
      <QueryPlayground
        schema={complexSsrSchema}
        initialTable="accounts"
        initialSpec={{
          table: "accounts",
          columns: ["accounts.id", "accounts.balance"],
          joins: [
            {
              table: "organizations",
              type: "INNER JOIN",
              left_table: "accounts",
              left_col: "organization_id",
              right_col: "id",
            },
          ],
          filters: [{ column: "accounts.balance", op: ">", value: 100 }],
          order_by: [{ column: "accounts.balance", direction: "DESC" }],
          distinct: true,
          limit: 20,
        }}
      />,
    );
    expect(playgroundHtml).toContain('data-qb="playground-root"');
    expect(playgroundHtml).toContain("Query-Builder Playground");
    expect(playgroundHtml).toContain("AST Safe");

    // 3. QueryCanvas
    const canvasHtml = renderToString(
      <QueryCanvas
        schema={complexSsrSchema}
        activeTables={[complexSsrSchema.tables.accounts]}
        primaryTable="accounts"
        selectedColumns={{ "accounts.id": { table: "accounts", name: "id" } }}
        orderedProjectionKeys={["accounts.id"]}
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
    expect(canvasHtml).toContain('data-qb="canvas"');

    // 4. TableCard
    const cardHtml = renderToString(
      <TableCard
        table={complexSsrSchema.tables.accounts}
        selectedColumns={{ "accounts.id": { table: "accounts", name: "id" } }}
        onToggleColumn={() => {}}
        unstyled={true}
      />,
    );
    expect(cardHtml).toContain('data-qb="table-card"');

    // 5. TableFiltersEditor
    const filtersHtml = renderToString(
      <TableFiltersEditor
        filters={[
          { id: "f1", tablePrefix: "accounts", column: "balance", operator: ">", value: 50 },
        ]}
        activeTables={[complexSsrSchema.tables.accounts]}
        onChange={() => {}}
        unstyled={true}
      />,
    );
    expect(filtersHtml).toContain('data-qb="filters-editor"');

    // 6. TableJoinEditor
    const joinsHtml = renderToString(
      <TableJoinEditor
        joins={[
          {
            id: "j1",
            type: "INNER JOIN",
            left_table: "accounts",
            left_col: "organization_id",
            table: "organizations",
            right_col: "id",
          },
        ]}
        activeTables={[complexSsrSchema.tables.accounts]}
        allTables={[complexSsrSchema.tables.accounts, complexSsrSchema.tables.organizations]}
        onChange={() => {}}
        unstyled={true}
      />,
    );
    expect(joinsHtml).toContain('data-qb="joins-editor"');

    // 7. TableSortsEditor
    const sortsHtml = renderToString(
      <TableSortsEditor
        sorts={[{ id: "s1", tablePrefix: "accounts", column: "balance", direction: "DESC" }]}
        activeTables={[complexSsrSchema.tables.accounts]}
        onChange={() => {}}
        unstyled={true}
      />,
    );
    expect(sortsHtml).toContain('data-qb="sorts-editor"');

    // 8. QueryResultsTable
    const resultsHtml = renderToString(
      <QueryResultsTable results={complexSsrResults} unstyled={true} />,
    );
    expect(resultsHtml).toContain('data-qb="results-table-root"');
    expect(resultsHtml).toContain("Acme Corp");
    expect(resultsHtml).toMatch(/38.*ms/);

    // 9. QueryChartPreview
    const chartHtml = renderToString(
      <QueryChartPreview results={complexSsrResults} unstyled={true} />,
    );
    expect(chartHtml).toContain('data-qb="chart-preview-root"');

    // 10. QueryTemplateManager
    const templateHtml = renderToString(
      <QueryTemplateManager
        isOpen={true}
        onClose={() => {}}
        onLoadTemplate={() => {}}
        unstyled={true}
      />,
    );
    expect(templateHtml).toContain('data-qb="template-manager-modal"');
  });

  it("safely evaluates headless hooks in SSR React component", () => {
    const HeadlessSsrConsumer: React.FC = () => {
      const { compiled, safety } = useQueryBuilder({
        schema: complexSsrSchema,
        initialTable: "accounts",
      });
      const { state, spec } = useQueryState({
        table: "organizations",
        limit: 15,
      });
      const { sql, countSql } = useSqlCompiler(spec);

      return (
        <div>
          <span data-testid="qb-sql">{compiled.sql}</span>
          <span data-testid="qb-safety">{safety.valid ? "VALID" : "INVALID"}</span>
          <span data-testid="qs-table">{state.primaryTable}</span>
          <span data-testid="qc-sql">{sql}</span>
          <span data-testid="qc-count">{countSql}</span>
        </div>
      );
    };

    const html = renderToString(<HeadlessSsrConsumer />);
    expect(html).toContain("accounts");
    expect(html).toContain("VALID");
    expect(html).toContain("organizations");
    expect(html).toContain("count_wrapper");
  });
});
