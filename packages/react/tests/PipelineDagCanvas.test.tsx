import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  PipelineDagCanvas,
  detectCteCycles,
} from "../src/components/PipelineDagCanvas";
import { ThemeContext } from "../src/theme/ThemeProvider";
import type { QueryBuilderTheme } from "../src/theme/tokens";
import { invalid } from "./helpers";
import type { CteSpec, QuerySpec } from "../src/types";

describe("PipelineDagCanvas Component", () => {
  it("detectCteCycles detects circular dependencies accurately", () => {
    // No cycles
    const noCycleNodes = [
      { name: "a", dependencies: [] },
      { name: "b", dependencies: ["a"] },
      { name: "c", dependencies: ["b"] },
    ];
    expect(detectCteCycles(noCycleNodes)).toEqual([]);

    // Two-node cycle: a -> b -> a
    const twoNodeCycle = [
      { name: "a", dependencies: ["b"] },
      { name: "b", dependencies: ["a"] },
    ];
    const cycles2 = detectCteCycles(twoNodeCycle);
    expect(cycles2.length).toBeGreaterThan(0);
    expect(cycles2[0]).toContain("a");
    expect(cycles2[0]).toContain("b");

    // Three-node cycle: a -> b -> c -> a
    const threeNodeCycle = [
      { name: "a", dependencies: ["b"] },
      { name: "b", dependencies: ["c"] },
      { name: "c", dependencies: ["a"] },
    ];
    const cycles3 = detectCteCycles(threeNodeCycle);
    expect(cycles3.length).toBeGreaterThan(0);
  });

  it("renders with empty CTEs and displays Final Query node", () => {
    render(
      <PipelineDagCanvas
        ctes={[]}
        onCtesChange={vi.fn()}
        onSelectStage={vi.fn()}
        selectedStage={null}
      />
    );

    expect(screen.getByTestId("pipeline-dag-canvas")).toBeTruthy();
    expect(screen.getByText("CTE Pipeline DAG Canvas")).toBeTruthy();
    expect(screen.getByTestId("dag-node-Final Query")).toBeTruthy();
    expect(screen.getByText("Root query targeting active canvas")).toBeTruthy();
  });

  it("renders stages with dependencies and handles selection", () => {
    const onSelectStage = vi.fn();
    const ctes: CteSpec[] = [
      {
        name: "stage_raw",
        query: {
          table: "users",
          columns: ["id"],
          joins: [{ table: "orders", type: "INNER" }],
        } as unknown as QuerySpec,
      },
      {
        name: "stage_agg",
        query: {
          table: "stage_raw",
          columns: ["id"],
          joins: [],
        } as unknown as QuerySpec,
        recursive: true,
      },
    ];

    render(
      <PipelineDagCanvas
        ctes={ctes}
        onCtesChange={vi.fn()}
        onSelectStage={onSelectStage}
        selectedStage="stage_raw"
      />
    );

    expect(screen.getByTestId("dag-node-stage_raw")).toBeTruthy();
    expect(screen.getByTestId("dag-node-stage_agg")).toBeTruthy();
    expect(screen.getByText("Reads: users, orders")).toBeTruthy();
    expect(screen.getByText("Reads: stage_raw")).toBeTruthy();

    // Click on stage_agg
    fireEvent.click(screen.getByTestId("dag-node-stage_agg"));
    expect(onSelectStage).toHaveBeenCalledWith("stage_agg");

    // Click on Final Query
    fireEvent.click(screen.getByTestId("dag-node-Final Query"));
    expect(onSelectStage).toHaveBeenCalledWith(null);
  });

  it("adds a new stage and handles existing name collision", () => {
    const onCtesChange = vi.fn();
    const onSelectStage = vi.fn();

    // Has length 1, but name is stage_2, so stage_2 collides and while loop increments to stage_3
    const initialCtes: CteSpec[] = [
      { name: "stage_2", query: { table: "t1" } },
    ];

    render(
      <PipelineDagCanvas
        ctes={initialCtes}
        onCtesChange={onCtesChange}
        onSelectStage={onSelectStage}
        selectedStage="stage_1"
      />
    );

    fireEvent.click(screen.getByTestId("add-stage-btn"));

    expect(onCtesChange).toHaveBeenCalled();
    const passedCtes = onCtesChange.mock.calls[0][0];
    expect(passedCtes.length).toBe(2);
    expect(passedCtes[1].name).toBe("stage_3");
    expect(onSelectStage).toHaveBeenCalledWith("stage_3");
  });

  it("removes a stage and resets selection if removed stage was selected", () => {
    const onCtesChange = vi.fn();
    const onSelectStage = vi.fn();

    const ctes: CteSpec[] = [
      { name: "stage_1", query: { table: "t1" } },
      { name: "stage_2", query: { table: "t2" } },
    ];

    const { rerender } = render(
      <PipelineDagCanvas
        ctes={ctes}
        onCtesChange={onCtesChange}
        onSelectStage={onSelectStage}
        selectedStage="stage_1"
      />
    );

    const removeBtn = screen.getByTestId("remove-stage-stage_1");
    fireEvent.click(removeBtn);

    expect(onCtesChange).toHaveBeenCalledWith([ctes[1]]);
    expect(onSelectStage).toHaveBeenCalledWith(null);

    // Remove when different stage is selected
    rerender(
      <PipelineDagCanvas
        ctes={ctes}
        onCtesChange={onCtesChange}
        onSelectStage={onSelectStage}
        selectedStage="stage_2"
      />
    );
    fireEvent.click(screen.getByTestId("remove-stage-stage_1"));
    expect(onSelectStage).toHaveBeenCalledTimes(1); // not called again
  });

  it("toggles recursive property on a stage", () => {
    const onCtesChange = vi.fn();
    const ctes: CteSpec[] = [
      { name: "stage_rec", query: { table: "t1" }, recursive: false },
      { name: "other_stage", query: { table: "t2" }, recursive: false },
    ];

    render(
      <PipelineDagCanvas
        ctes={ctes}
        onCtesChange={onCtesChange}
        onSelectStage={vi.fn()}
        selectedStage={null}
      />
    );

    const checkbox = screen.getByTestId("toggle-recursive-stage_rec");
    expect((checkbox as HTMLInputElement).checked).toBe(false);

    fireEvent.click(checkbox);
    expect(onCtesChange).toHaveBeenCalledWith([
      { ...ctes[0], recursive: true },
      ctes[1],
    ]);
  });

  it("renders cycle alert warning banner when circular dependency exists", () => {
    const cyclicCtes: CteSpec[] = [
      { name: "stage_a", query: { table: "stage_b" } },
      { name: "stage_b", query: { table: "stage_a" } },
    ];

    const { rerender } = render(
      <PipelineDagCanvas
        ctes={cyclicCtes}
        onCtesChange={vi.fn()}
        onSelectStage={vi.fn()}
        selectedStage={null}
      />
    );

    expect(screen.getByTestId("dag-cycle-alert")).toBeTruthy();
    expect(screen.getByText("Warning: Circular Dependency Detected!")).toBeTruthy();

    // Also render unstyled
    rerender(
      <PipelineDagCanvas
        ctes={cyclicCtes}
        onCtesChange={vi.fn()}
        onSelectStage={vi.fn()}
        selectedStage={null}
        unstyled={true}
      />
    );
    expect(screen.getByTestId("dag-cycle-alert")).toBeTruthy();
  });

  it("renders properly with unstyled=true and no joins", () => {
    const ctes: CteSpec[] = [
      { name: "stage_no_joins", query: { table: "" } },
    ];

    render(
      <PipelineDagCanvas
        ctes={ctes}
        onCtesChange={vi.fn()}
        onSelectStage={vi.fn()}
        selectedStage={null}
        unstyled={true}
      />
    );

    expect(screen.getByText("Reads: (none)")).toBeTruthy();
  });

  it("renders with fallback theme colors when theme colors are omitted", () => {
    const ctes: CteSpec[] = [
      { name: "s1", query: { table: "users" } },
    ];
    render(
      <ThemeContext.Provider
        value={{
          theme: invalid<QueryBuilderTheme>({ colors: {} }),
          mode: "dark",
          cssVariables: {},
          setTheme: vi.fn(),
          setMode: vi.fn(),
          toggleMode: vi.fn(),
        }}
      >
        <PipelineDagCanvas
          ctes={ctes}
          onCtesChange={vi.fn()}
          onSelectStage={vi.fn()}
          selectedStage={null}
        />
      </ThemeContext.Provider>
    );
    expect(screen.getByTestId("dag-node-s1")).toBeTruthy();
  });
});
