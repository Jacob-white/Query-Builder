import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryPerformanceAdvisor } from "../src/components/QueryPerformanceAdvisor";
import type { QuerySpec } from "../src/types";

describe("QueryPerformanceAdvisor Component", () => {
  beforeEach(() => {
    // Mock navigator.clipboard
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });
  });

  it("renders top summary bar with cost badge, warnings, and index counts", () => {
    const spec: Partial<QuerySpec> = {
      table: "users",
      columns: ["*"],
      filters: [{ column: "email", op: "=", value: "a@b.com" }],
    };
    const sql = "SELECT * FROM users WHERE email = 'a@b.com';";

    render(<QueryPerformanceAdvisor querySpec={spec} sql={sql} dialect="bigquery" />);

    expect(screen.getByTestId("query-performance-advisor")).toBeDefined();
    expect(screen.getByTestId("cost-estimate-badge")).toBeDefined();
    expect(screen.getByTestId("warning-count-badge")).toBeDefined();
    expect(screen.getByTestId("index-rec-count-badge")).toBeDefined();
  });

  it("toggles insights expanded panel open and closed", () => {
    const spec: Partial<QuerySpec> = { table: "logs" };
    const sql = "SELECT * FROM logs;";

    render(<QueryPerformanceAdvisor querySpec={spec} sql={sql} />);

    expect(screen.queryByTestId("advisor-expanded-panel")).toBeNull();

    const toggleBtn = screen.getByTestId("toggle-advisor-details-btn");
    fireEvent.click(toggleBtn);

    expect(screen.getByTestId("advisor-expanded-panel")).toBeDefined();
    expect(screen.getByText("Hide Insights ▲")).toBeDefined();

    fireEvent.click(toggleBtn);
    expect(screen.queryByTestId("advisor-expanded-panel")).toBeNull();
  });

  it("copies index DDL and triggers onApplyIndexDdl callback", () => {
    const spec: Partial<QuerySpec> = {
      table: "orders",
      filters: [{ column: "customer_id", op: "=", value: 123 }],
    };
    const sql = "SELECT * FROM orders WHERE customer_id = 123 LIMIT 10;";
    const onApply = vi.fn();

    render(
      <QueryPerformanceAdvisor
        querySpec={spec}
        sql={sql}
        dialect="postgres"
        onApplyIndexDdl={onApply}
      />,
    );

    // Expand
    fireEvent.click(screen.getByTestId("toggle-advisor-details-btn"));

    const copyBtn = screen.getByTestId("copy-ddl-btn-0");
    fireEvent.click(copyBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      "CREATE INDEX idx_orders_customer_id ON orders (customer_id);",
    );
    expect(onApply).toHaveBeenCalledWith(
      "CREATE INDEX idx_orders_customer_id ON orders (customer_id);",
    );
    expect(screen.getByText("✓ Copied")).toBeDefined();
  });
});
