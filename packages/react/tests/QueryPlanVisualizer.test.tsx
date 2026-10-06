import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryPlanVisualizer } from "../src/components/QueryPlanVisualizer";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type { QueryPlanNode } from "../src/types";

describe("QueryPlanVisualizer Component", () => {
  const samplePlan: QueryPlanNode = {
    node_type: "Limit",
    cost_estimate: 250,
    cost_percentage: 100,
    rows_estimated: 10,
    warnings: ["Root bottleneck"],
    children: [
      {
        node_type: "Sort",
        cost_estimate: 240,
        cost_percentage: 96,
        rows_estimated: 5000,
        children: [
          {
            node_type: "Seq Scan",
            table: "customers",
            cost_estimate: 200,
            cost_percentage: 80,
            rows_estimated: 50000,
            filter_predicate: "status = 'active'",
            warnings: [
              "Sequential table scan on 'customers' with 50,000 estimated rows. Consider adding an index on relevant filter columns.",
            ],
            children: [],
          },
        ],
      },
    ],
  };

  it("renders plan visual tree with node types, table names, and cost badges", () => {
    render(<QueryPlanVisualizer plan={samplePlan} />);

    expect(screen.getByText("Visual Query Execution Plan")).toBeTruthy();
    expect(screen.getByText("Limit")).toBeTruthy();
    expect(screen.getByText("Sort")).toBeTruthy();
    expect(screen.getByText("Seq Scan")).toBeTruthy();
    expect(screen.getByText("customers")).toBeTruthy();
    expect(screen.getByText("80.0% cost")).toBeTruthy();
  });

  it("displays node details when a tree node is clicked", () => {
    const onNodeSelect = vi.fn();
    render(<QueryPlanVisualizer plan={samplePlan} onNodeSelect={onNodeSelect} />);

    const seqScanNode = screen.getByText("Seq Scan");
    fireEvent.click(seqScanNode);

    expect(onNodeSelect).toHaveBeenCalledWith(
      expect.objectContaining({ node_type: "Seq Scan", table: "customers" })
    );

    expect(screen.getByText("Selected Node: Seq Scan")).toBeTruthy();
    expect(screen.getAllByText("customers").length).toBeGreaterThan(0);
  });

  it("switches to Optimization Insights tab and renders aggregated warnings", () => {
    render(<QueryPlanVisualizer plan={samplePlan} />);

    const insightsTabBtn = screen.getByRole("button", {
      name: /Optimization Insights/i,
    });
    fireEvent.click(insightsTabBtn);

    expect(
      screen.getByText(/Sequential table scan on 'customers'/i)
    ).toBeTruthy();
    expect(screen.getByText("Root bottleneck")).toBeTruthy();
  });

  it("switches to Raw Plan tab, supports copying JSON with copied reset timer, and switches back to tree", async () => {
    vi.useFakeTimers();
    try {
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      render(<QueryPlanVisualizer plan={samplePlan} />);

      const rawTabBtn = screen.getByRole("button", { name: "Raw Plan" });
      fireEvent.click(rawTabBtn);

      const copyBtn = screen.getByRole("button", { name: "Copy JSON" });
      expect(copyBtn).toBeTruthy();

      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextMock).toHaveBeenCalled();

      // Advance timer by 2000ms to trigger setCopied(false) callback
      act(() => {
        vi.advanceTimersByTime(2000);
      });

      // Switch back to Execution Tree tab
      const treeTabBtn = screen.getByRole("button", { name: "Visual Tree" });
      fireEvent.click(treeTabBtn);
      expect(screen.getByText("Limit")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("toggles collapse on tree nodes with children", () => {
    render(<QueryPlanVisualizer plan={samplePlan} />);

    expect(screen.getByText("Seq Scan")).toBeTruthy();

    // Click collapse button on Limit node
    const collapseButtons = screen.getAllByRole("button", {
      name: /Collapse node/i,
    });
    expect(collapseButtons.length).toBeGreaterThan(0);

    // Collapse the root Limit node
    fireEvent.click(collapseButtons[0]);

    // The children should no longer be visible
    expect(screen.queryByText("Seq Scan")).toBeNull();

    // Expand again
    const expandButton = screen.getByRole("button", { name: /Expand node/i });
    fireEvent.click(expandButton);

    expect(screen.getByText("Seq Scan")).toBeTruthy();
  });

  it("renders Query Plan tab in VisualQueryBuilder when showPlanTab or queryPlan is provided", () => {
    const mockSchema = {
      tables: {
        users: {
          name: "users",
          columns: {
            id: { name: "id", type: "integer" },
            name: { name: "name", type: "varchar" },
          },
        },
      },
    };

    const { rerender } = render(
      <VisualQueryBuilder schema={mockSchema} initialTable="users" />
    );

    // By default, plan tab is not present
    expect(screen.queryByRole("tab", { name: /Query Plan/i })).toBeNull();

    // When showPlanTab is true, tab is rendered
    rerender(
      <VisualQueryBuilder
        schema={mockSchema}
        initialTable="users"
        showPlanTab={true}
        queryPlan={samplePlan}
      />
    );

    const planTab = screen.getByRole("tab", { name: /Query Plan/i });
    expect(planTab).toBeTruthy();

    // Click tab to activate
    fireEvent.click(planTab);
    expect(screen.getByText("Visual Query Execution Plan")).toBeTruthy();
    expect(screen.getByText("Limit")).toBeTruthy();
  });

  it("renders optimal plan efficiency banner when there are no warnings", () => {
    const perfectPlan: QueryPlanNode = {
      node_type: "Index Scan",
      table: "users",
      cost_estimate: 10,
      cost_percentage: 5, // optimal (< 10%)
      rows_estimated: 1,
      children: [],
      warnings: [],
    };

    render(<QueryPlanVisualizer plan={perfectPlan} />);
    const insightsTabBtn = screen.getByRole("button", { name: /Optimization Insights/i });
    fireEvent.click(insightsTabBtn);

    expect(screen.getByText("Optimal Plan Efficiency")).toBeTruthy();
    expect(screen.getByText(/All query nodes operate within normal cost bounds/i)).toBeTruthy();
  });

  it("renders index_name, actual timings, moderate/optimal badges, and supports unstyled mode and rawPlan", async () => {
    const detailedPlan: QueryPlanNode = {
      node_type: "Index Scan",
      table: "orders",
      index_name: "idx_orders_customer_id",
      cost_estimate: 45,
      cost_percentage: 20, // moderate cost (10-30%)
      actual_time_ms: 1.45,
      rows_estimated: 100,
      rows_actual: 98,
      filter_predicate: "customer_id = 123",
      warnings: ["Minor index fragmentation"],
      children: [
        {
          node_type: "Bitmap Index Scan",
          cost_estimate: 5,
          cost_percentage: 5, // optimal (< 10%)
          rows_estimated: 100,
          children: [],
        },
      ],
    };

    const rawVendorPlan = { format: "postgres-json", total_cost: 50 };
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });

    render(
      <QueryPlanVisualizer
        plan={detailedPlan}
        rawPlan={rawVendorPlan}
        unstyled={true}
        className="custom-visualizer-class"
      />
    );

    // Index badge
    expect(screen.getByText("index: idx_orders_customer_id")).toBeTruthy();

    // Click node to view details panel
    const indexNode = screen.getByText("index: idx_orders_customer_id");
    fireEvent.click(indexNode);

    expect(screen.getByText("Selected Node: Index Scan")).toBeTruthy();
    expect(screen.getByText("1.45 ms")).toBeTruthy();
    expect(screen.getByText("98")).toBeTruthy();
    expect(screen.getByText("customer_id = 123")).toBeTruthy();

    // Dismiss the selected node details by clicking the ✕ button
    const closeDetailsBtn = screen.getByRole("button", { name: "✕" });
    fireEvent.click(closeDetailsBtn);
    expect(screen.queryByText("Selected Node: Index Scan")).toBeNull();

    // Raw Plan tab with custom rawPlan
    const rawTabBtn = screen.getByRole("button", { name: "Raw Plan" });
    fireEvent.click(rawTabBtn);
    expect(screen.getByText(/"format": "postgres-json"/i)).toBeTruthy();

    const copyBtn = screen.getByRole("button", { name: "Copy JSON" });
    await act(async () => {
      fireEvent.click(copyBtn);
    });
    expect(writeTextMock).toHaveBeenCalledWith(JSON.stringify(rawVendorPlan, null, 2));
  });

  it("renders multiple warnings plural badge and handles fallback nullish cost/rows in node details", () => {
    const multiWarnPlan: QueryPlanNode = {
      node_type: "Nested Loop",
      cost_estimate: undefined as any,
      cost_percentage: undefined as any,
      rows_estimated: undefined as any,
      warnings: ["Heavy loop join", "Cartesian volume risk"],
      children: [],
    };

    render(<QueryPlanVisualizer plan={multiWarnPlan} />);

    // Renders "warnings" plural badge
    expect(screen.getByText("⚠️ 2 warnings")).toBeTruthy();
    expect(screen.getByText("est. 0 rows")).toBeTruthy();

    // Click to select
    const node = screen.getByText("Nested Loop");
    fireEvent.click(node);

    expect(screen.getByText("Selected Node: Nested Loop")).toBeTruthy();
    expect(screen.getByText("Cost Estimate:")).toBeTruthy();
  });
});



