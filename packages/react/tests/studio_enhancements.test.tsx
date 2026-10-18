import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  QueryBuilderProvider,
  VisualQueryBuilder,
  QueryResultsTable,
  parseSqlToSpec,
  compileSpecToSql,
  specToState,
  stateToSpec,
  createInitialState,
  type SchemaSnapshot,
} from "../src";
import { autoJoinOnState } from "../src/utils/queryStateTransitions";

const TEST_SCHEMA: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_primary: true, is_nullable: false },
        { name: "email", data_type: "text", is_primary: false, is_nullable: false },
        { name: "role", data_type: "text", is_primary: false, is_nullable: false, enums: ["ADMIN", "CUSTOMER"] },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_primary: true, is_nullable: false },
        {
          name: "user_id",
          data_type: "integer",
          is_primary: false,
          is_nullable: false,
          foreign_key: "users.id",
        },
        { name: "total_amount", data_type: "decimal", is_primary: false, is_nullable: false },
        { name: "status", data_type: "text", is_primary: false, is_nullable: false, enums: ["PENDING", "COMPLETED"] },
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
  relationships: [],
};

describe("Phase 3-5 Bug Fixes & Studio Enhancements", () => {
  it("resolves table aliases in SELECT, WHERE, and ORDER BY in parseSqlToSpec", () => {
    const spec = parseSqlToSpec(
      "SELECT u.email, o.total_amount AS amt FROM users u INNER JOIN orders o ON u.id = o.user_id WHERE u.role = 'ADMIN' ORDER BY o.total_amount DESC",
    );
    expect(spec).not.toBeNull();
    expect(spec?.table).toBe("users");
    expect(spec?.columns).toEqual([
      "users.email",
      { column: "orders.total_amount", alias: "amt" },
    ]);
    expect(spec?.filters[0]?.tablePrefix).toBe("users");
    expect(spec?.filters[0]?.column).toBe("role");
    expect(spec?.order_by[0]?.tablePrefix).toBe("orders");
    expect(spec?.order_by[0]?.column).toBe("total_amount");
  });

  it("parses COUNT(DISTINCT col) as COUNT_DISTINCT in parseSqlToSpec", () => {
    const spec = parseSqlToSpec(
      "SELECT COUNT(DISTINCT u.email) AS unique_emails FROM users u",
    );
    expect(spec?.columns).toEqual([
      {
        column: "users.email",
        agg: "COUNT_DISTINCT",
        alias: "unique_emails",
      },
    ]);
  });

  it("auto-populates FK join columns in autoJoinOnState when schema metadata is provided", () => {
    const initial = createInitialState({ table: "orders", dialect: "sqlite" });
    const next = autoJoinOnState(initial, "users", TEST_SCHEMA);
    expect(next.joins).toHaveLength(1);
    expect(next.joins[0]).toMatchObject({
      table: "users",
      left_table: "orders",
      left_col: "user_id",
      right_col: "id",
    });
  });

  it("preserves CaseWhenSpec across specToState, stateToSpec, and compileSpecToSql", () => {
    const initial = createInitialState({ table: "orders", dialect: "sqlite" });
    const partial = specToState({
      table: "orders",
      columns: [
        "orders.id",
        {
          column: "tier",
          alias: "order_tier",
          case_when: {
            branches: [
              {
                condition: {
                  tablePrefix: "orders",
                  column: "total_amount",
                  op: ">=",
                  value: 1000,
                },
                then_value: "VIP",
              },
            ],
            else_value: "Standard",
            alias: "order_tier",
          },
        },
      ],
    });
    const loaded = { ...initial, ...partial };

    const roundTripSpec = stateToSpec(loaded);
    const caseCol = roundTripSpec.columns.find(
      (c): c is Exclude<typeof c, string> => typeof c === "object" && c.alias === "order_tier",
    );
    expect(caseCol?.case_when).toBeDefined();

    const compiledSql = compileSpecToSql(roundTripSpec, "sqlite");
    expect(compiledSql).toContain("CASE WHEN");
    expect(compiledSql).toContain("THEN 'VIP' ELSE 'Standard' END AS \"order_tier\"");
  });

  it("matches unqualified column suffix in QueryResultsTable cellRenderers and filters rows via quick search", () => {
    render(
      <QueryBuilderProvider
        cellRenderers={{
          total_amount: (val) => <span data-testid="custom-amt">${String(val)}</span>,
        }}
      >
        <QueryResultsTable
          results={{
            columns: ["orders.id", "orders.total_amount"],
            rows: [
              { "orders.id": 1, "orders.total_amount": 99.5 },
              { "orders.id": 2, "orders.total_amount": 250.0 },
            ],
            count: 2,
          }}
        />
      </QueryBuilderProvider>,
    );

    const renderedAmts = screen.getAllByTestId("custom-amt");
    expect(renderedAmts).toHaveLength(2);
    expect(renderedAmts[0]?.textContent).toBe("$99.5");

    // Quick search filters rows
    const searchInput = screen.getByLabelText("Search query results");
    fireEvent.change(searchInput, { target: { value: "250" } });
    const filteredAmts = screen.getAllByTestId("custom-amt");
    expect(filteredAmts).toHaveLength(1);
    expect(filteredAmts[0]?.textContent).toBe("$250");
  });

  it("renders Query Plan tab, Pipeline tab, NLQ bar, Live SQL Preview, and Calculated Column Editor in VisualQueryBuilder", () => {
    render(
      <QueryBuilderProvider mode="styled" themeMode="dark">
        <VisualQueryBuilder
          schema={TEST_SCHEMA}
          initialTable="orders"
          showPlanTab={true}
          showPipelineTab={true}
          showNlqBar={true}
        />
      </QueryBuilderProvider>,
    );

    // NLQ input bar should be visible
    expect(screen.getByLabelText("NLQ Input")).toBeTruthy();

    // Query Plan and Pipeline tabs should be visible
    expect(screen.getByRole("tab", { name: /Query Plan/i })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Pipeline/i })).toBeTruthy();

    // Live SQL Preview bar should be visible
    expect(screen.getByText(/Live SQL Preview/i)).toBeTruthy();

    // + Calculated Field button opens CalculatedFieldEditor modal
    const calcBtn = screen.getByRole("button", { name: /\+ Calculated Field/i });
    fireEvent.click(calcBtn);
    expect(screen.getByText(/Calculated Column Editor/i)).toBeTruthy();
  });
});

