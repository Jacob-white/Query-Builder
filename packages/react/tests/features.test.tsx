import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  VisualQueryBuilder,
  resolveFeatureConfig,
  isFeatureVisible,
  normalizeTier,
  detectActiveAdvancedClauses,
  DEFAULT_FEATURE_CONFIG,
  FEATURE_PRESETS,
  QueryBuilderProvider,
  useQueryBuilderContext,
} from "../src";
import type { SchemaSnapshot } from "../src/types";

describe("Feature Flags & Advanced Mode Governance", () => {
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
  };

  beforeEach(() => {
    localStorage.clear();
  });

  describe("Utility & Registry Resolution", () => {
    it("normalizes boolean and string tiers correctly", () => {
      expect(normalizeTier(true)).toBe("standard");
      expect(normalizeTier(false)).toBe("disabled");
      expect(normalizeTier("standard")).toBe("standard");
      expect(normalizeTier("std")).toBe("standard");
      expect(normalizeTier("advanced")).toBe("advanced");
      expect(normalizeTier("adv")).toBe("advanced");
      expect(normalizeTier("disabled")).toBe("disabled");
      expect(normalizeTier("off")).toBe("disabled");
      expect(normalizeTier(undefined)).toBe("standard");
    });

    it("resolves default feature config when no overrides or preset given", () => {
      const resolved = resolveFeatureConfig();
      expect(resolved.projections).toBe("standard");
      expect(resolved.ctes).toBe("advanced");
      expect(resolved.window_functions).toBe("advanced");
      expect(resolved.raw_sql).toBe("advanced");
    });

    it("applies 'simple' preset with all advanced features disabled", () => {
      const resolved = resolveFeatureConfig(undefined, "simple");
      expect(resolved.projections).toBe("standard");
      expect(resolved.ctes).toBe("disabled");
      expect(resolved.window_functions).toBe("disabled");
      expect(resolved.raw_sql).toBe("disabled");
      expect(resolved.vector_search).toBe("disabled");
    });

    it("applies 'all' preset with everything standard", () => {
      const resolved = resolveFeatureConfig(undefined, "all");
      expect(resolved.projections).toBe("standard");
      expect(resolved.ctes).toBe("standard");
      expect(resolved.window_functions).toBe("standard");
      expect(resolved.raw_sql).toBe("standard");
    });

    it("merges server capabilities and prop overrides with precedence", () => {
      const serverCaps = { ctes: "disabled", vector_search: "standard" };
      const propOverrides = { ctes: "advanced" as const };
      const resolved = resolveFeatureConfig(propOverrides, "standard", serverCaps);

      // Server capability set vector_search to standard
      expect(resolved.vector_search).toBe("standard");
      // Explicit prop override takes precedence over server capability
      expect(resolved.ctes).toBe("advanced");
    });

    it("evaluates feature visibility properly against active mode", () => {
      const config = { ...DEFAULT_FEATURE_CONFIG };
      expect(isFeatureVisible("projections", config, false)).toBe(true);
      expect(isFeatureVisible("projections", config, true)).toBe(true);

      expect(isFeatureVisible("raw_sql", config, false)).toBe(false);
      expect(isFeatureVisible("raw_sql", config, true)).toBe(true);

      config.raw_sql = "disabled";
      expect(isFeatureVisible("raw_sql", config, false)).toBe(false);
      expect(isFeatureVisible("raw_sql", config, true)).toBe(false);
    });

    it("detects active advanced clauses in query state accurately", () => {
      const config = { ...DEFAULT_FEATURE_CONFIG };
      const state = {
        ctes: [{ name: "cte1", query: "SELECT 1" }],
        windowFunctions: [{ id: "wf1", functionName: "ROW_NUMBER" }],
        vectorSearch: { column: "embedding", vector: [0.1, 0.2] },
        selectedColumns: {
          "users.custom": { table: "users", name: "custom", rawExpression: "price * 1.1" },
        },
      };

      const clauses = detectActiveAdvancedClauses(state, config);
      expect(clauses.length).toBe(4);
      expect(clauses.some((c) => c.key === "ctes")).toBe(true);
      expect(clauses.some((c) => c.key === "window_functions")).toBe(true);
      expect(clauses.some((c) => c.key === "vector_search")).toBe(true);
      expect(clauses.some((c) => c.key === "calculated_fields")).toBe(true);
    });
  });

  describe("VisualQueryBuilder Component Integration", () => {
    it("renders Advanced Mode toggle switch in toolbar", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          defaultAdvancedMode={true}
        />,
      );

      const toggleBtn = screen.getByTestId("btn-toggle-advanced");
      expect(toggleBtn).toBeTruthy();
      expect(toggleBtn.getAttribute("aria-pressed")).toBe("true");
      expect(screen.getByText("📝 Raw SQL")).toBeTruthy();
    });

    it("toggles Advanced Mode OFF and hides advanced UI controls", () => {
      const onModeChange = vi.fn();
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          defaultAdvancedMode={true}
          onAdvancedModeChange={onModeChange}
        />,
      );

      expect(screen.getByText("📝 Raw SQL")).toBeTruthy();
      expect(screen.getByTestId("btn-open-wf-builder")).toBeTruthy();

      const toggleBtn = screen.getByTestId("btn-toggle-advanced");
      fireEvent.click(toggleBtn);

      expect(onModeChange).toHaveBeenCalledWith(false);
      expect(toggleBtn.getAttribute("aria-pressed")).toBe("false");

      // Advanced features should now be hidden
      expect(screen.queryByText("📝 Raw SQL")).toBeNull();
      expect(screen.queryByTestId("btn-open-wf-builder")).toBeNull();
      expect(screen.queryByText("🗺️ ERD")).toBeNull();
    });

    it("respects defaultAdvancedMode={false} initially", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          defaultAdvancedMode={false}
        />,
      );

      const toggleBtn = screen.getByTestId("btn-toggle-advanced");
      expect(toggleBtn.getAttribute("aria-pressed")).toBe("false");
      expect(screen.queryByText("📝 Raw SQL")).toBeNull();

      fireEvent.click(toggleBtn);
      expect(toggleBtn.getAttribute("aria-pressed")).toBe("true");
      expect(screen.getByText("📝 Raw SQL")).toBeTruthy();
    });

    it("hides toggle switch when allowToggleAdvanced={false}", () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          allowToggleAdvanced={false}
        />,
      );

      expect(screen.queryByTestId("btn-toggle-advanced")).toBeNull();
    });

    it("supports controlled advancedMode prop", () => {
      const { rerender } = render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          advancedMode={false}
        />,
      );

      expect(screen.queryByText("📝 Raw SQL")).toBeNull();

      rerender(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          advancedMode={true}
        />,
      );

      expect(screen.getByText("📝 Raw SQL")).toBeTruthy();
    });

    it("opens granular feature settings popover and overrides individual feature", async () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          defaultAdvancedMode={false}
        />,
      );

      // Raw SQL is initially hidden in simple mode
      expect(screen.queryByText("📝 Raw SQL")).toBeNull();

      // Open settings popover
      const settingsBtn = screen.getByTestId("btn-feature-settings");
      fireEvent.click(settingsBtn);

      expect(screen.getByText("Feature Tiers")).toBeTruthy();

      // Toggle raw_sql override select to standard
      const rawSqlSelect = screen.getByTestId("feature-select-raw_sql");
      fireEvent.change(rawSqlSelect, { target: { value: "standard" } });

      // Now Raw SQL tab becomes visible even though Advanced Mode is OFF
      expect(screen.getByText("📝 Raw SQL")).toBeTruthy();
    });

    it("displays active advanced clause warning banner and allows viewing or clearing", async () => {
      render(
        <VisualQueryBuilder
          schema={mockSchema}
          initialTable="users"
          defaultAdvancedMode={true}
        />,
      );

      // Open window function builder and add a function
      const wfBtn = screen.getByTestId("btn-open-wf-builder");
      fireEvent.click(wfBtn);

      // Save window function
      const saveBtn = screen.getByTestId("wf-save-btn");
      fireEvent.click(saveBtn);

      // Now toggle Advanced Mode OFF
      const toggleBtn = screen.getByTestId("btn-toggle-advanced");
      fireEvent.click(toggleBtn);
      expect(toggleBtn.getAttribute("aria-pressed")).toBe("false");

      // Non-destructive warning banner should appear
      const alertBanner = await screen.findByTestId("active-advanced-clauses-banner");
      expect(alertBanner).toBeTruthy();
      expect(alertBanner.textContent).toContain("hidden advanced clause(s) active");

      // Test "View in Advanced Mode" button
      const viewBtn = screen.getByText("View in Advanced Mode");
      fireEvent.click(viewBtn);
      expect(toggleBtn.getAttribute("aria-pressed")).toBe("true");

      // Toggle OFF again to test "Clear Clauses"
      fireEvent.click(toggleBtn);
      const clearBtn = await screen.findByText("Clear Clauses");
      fireEvent.click(clearBtn);

      // Banner should disappear after clearing clauses
      await waitFor(() => {
        expect(screen.queryByTestId("active-advanced-clauses-banner")).toBeNull();
      });
    });
  });

  describe("QueryBuilderProvider Context Integration", () => {
    it("provides feature visibility helpers to nested consumers", () => {
      const TestConsumer = () => {
        const ctx = useQueryBuilderContext();
        return (
          <div>
            <span data-testid="is-advanced">
              {ctx?.isAdvancedMode ? "advanced" : "simple"}
            </span>
            <span data-testid="is-raw-sql-visible">
              {ctx?.isFeatureVisible?.("raw_sql") ? "visible" : "hidden"}
            </span>
            <button
              data-testid="toggle-ctx-btn"
              onClick={() => ctx?.setIsAdvancedMode?.(!ctx.isAdvancedMode)}
            >
              Toggle
            </button>
          </div>
        );
      };

      render(
        <QueryBuilderProvider defaultAdvancedMode={false}>
          <TestConsumer />
        </QueryBuilderProvider>,
      );

      expect(screen.getByTestId("is-advanced").textContent).toBe("simple");
      expect(screen.getByTestId("is-raw-sql-visible").textContent).toBe("hidden");

      fireEvent.click(screen.getByTestId("toggle-ctx-btn"));
      expect(screen.getByTestId("is-advanced").textContent).toBe("advanced");
      expect(screen.getByTestId("is-raw-sql-visible").textContent).toBe("visible");
    });
  });
});
