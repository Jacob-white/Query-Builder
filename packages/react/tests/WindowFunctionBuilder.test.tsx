import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { WindowFunctionBuilder } from "../src/components/WindowFunctionBuilder";
import { ThemeContext } from "../src/theme/ThemeProvider";
import type { QueryBuilderTheme } from "../src/theme/tokens";
import { invalid } from "./helpers";
import type { WindowFunctionSpec } from "../src/types";

describe("WindowFunctionBuilder Component", () => {
  const dummyCols = [
    { table: "employees", name: "dept_id" },
    { table: "employees", name: "salary" },
    { name: "age" },
  ];

  it("returns null when isOpen is false", () => {
    const { container } = render(
      <WindowFunctionBuilder
        isOpen={false}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={dummyCols}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders with default props and handles close and cancel", () => {
    const onClose = vi.fn();
    const onSave = vi.fn();

    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={onClose}
        onSave={onSave}
        availableColumns={dummyCols}
      />
    );

    expect(screen.getByTestId("window-function-builder-modal")).toBeTruthy();
    expect(screen.getByText("Window Function Builder")).toBeTruthy();

    // Close button click
    fireEvent.click(screen.getByTestId("wf-close-btn"));
    expect(onClose).toHaveBeenCalledTimes(1);

    // Cancel button click
    fireEvent.click(screen.getByTestId("wf-cancel-btn"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("changes function and updates argument visibility and SQL preview", () => {
    const onSave = vi.fn();

    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={onSave}
        availableColumns={dummyCols}
      />
    );

    // Default is ROW_NUMBER -> target column selector not rendered
    expect(screen.queryByTestId("wf-arg-select")).toBeNull();
    expect(screen.getByTestId("wf-sql-preview").textContent).toContain("ROW_NUMBER() OVER ()");

    // Change function to SUM -> target column selector appears
    fireEvent.change(screen.getByTestId("wf-function-select"), {
      target: { value: "SUM" },
    });
    expect(screen.getByTestId("wf-arg-select")).toBeTruthy();

    // Change target column
    fireEvent.change(screen.getByTestId("wf-arg-select"), {
      target: { value: "employees.salary" },
    });
    expect(screen.getByTestId("wf-sql-preview").textContent).toContain("SUM(employees.salary) OVER ()");

    // Change to COUNT without arg column -> COUNT(*)
    fireEvent.change(screen.getByTestId("wf-function-select"), {
      target: { value: "COUNT" },
    });
    fireEvent.change(screen.getByTestId("wf-arg-select"), {
      target: { value: "" },
    });
    expect(screen.getByTestId("wf-sql-preview").textContent).toContain("COUNT(*) OVER ()");
  });

  it("toggles partition columns correctly", () => {
    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={dummyCols}
      />
    );

    const deptCheckbox = screen.getByTestId("wf-part-employees.dept_id");
    expect((deptCheckbox as HTMLInputElement).checked).toBe(false);

    // Check dept_id
    fireEvent.click(deptCheckbox);
    expect((deptCheckbox as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId("wf-sql-preview").textContent).toContain("PARTITION BY employees.dept_id");

    // Uncheck dept_id
    fireEvent.click(deptCheckbox);
    expect((deptCheckbox as HTMLInputElement).checked).toBe(false);
    expect(screen.getByTestId("wf-sql-preview").textContent).not.toContain("PARTITION BY");
  });

  it("handles order by column and direction changes", () => {
    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={dummyCols}
      />
    );

    fireEvent.change(screen.getByTestId("wf-order-col-select"), {
      target: { value: "employees.salary" },
    });
    fireEvent.change(screen.getByTestId("wf-order-dir-select"), {
      target: { value: "DESC" },
    });

    expect(screen.getByTestId("wf-sql-preview").textContent).toContain("ORDER BY employees.salary DESC");
  });

  it("handles window frame options and exclusion", () => {
    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={dummyCols}
      />
    );

    const frameCheckbox = screen.getByTestId("wf-enable-frame-checkbox");
    expect((frameCheckbox as HTMLInputElement).checked).toBe(false);

    // Enable framing
    fireEvent.click(frameCheckbox);
    expect((frameCheckbox as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId("wf-frame-type-select")).toBeTruthy();

    // Configure frame type, start, end, exclusion
    fireEvent.change(screen.getByTestId("wf-frame-type-select"), {
      target: { value: "RANGE" },
    });
    fireEvent.change(screen.getByTestId("wf-start-bound-input"), {
      target: { value: "1 PRECEDING" },
    });
    fireEvent.change(screen.getByTestId("wf-end-bound-input"), {
      target: { value: "1 FOLLOWING" },
    });
    fireEvent.change(screen.getByTestId("wf-exclusion-select"), {
      target: { value: "CURRENT ROW" },
    });

    expect(screen.getByTestId("wf-sql-preview").textContent).toContain(
      "RANGE BETWEEN 1 PRECEDING AND 1 FOLLOWING EXCLUDE CURRENT ROW"
    );
  });

  it("configures alias and calls onSave with complete payload", () => {
    const onSave = vi.fn();
    const onClose = vi.fn();

    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={onClose}
        onSave={onSave}
        availableColumns={dummyCols}
      />
    );

    fireEvent.change(screen.getByTestId("wf-function-select"), {
      target: { value: "AVG" },
    });
    fireEvent.change(screen.getByTestId("wf-arg-select"), {
      target: { value: "employees.salary" },
    });
    fireEvent.click(screen.getByTestId("wf-part-employees.dept_id"));
    fireEvent.change(screen.getByTestId("wf-order-col-select"), {
      target: { value: "employees.salary" },
    });
    fireEvent.change(screen.getByTestId("wf-order-dir-select"), {
      target: { value: "ASC" },
    });
    fireEvent.click(screen.getByTestId("wf-enable-frame-checkbox"));
    fireEvent.change(screen.getByTestId("wf-alias-input"), {
      target: { value: "avg_dept_sal" },
    });

    expect(screen.getByTestId("wf-sql-preview").textContent).toContain("AS avg_dept_sal");

    fireEvent.click(screen.getByTestId("wf-save-btn"));

    expect(onClose).toHaveBeenCalled();
    expect(onSave).toHaveBeenCalledWith({
      function: "AVG",
      arguments: ["employees.salary"],
      partition_by: ["employees.dept_id"],
      order_by: [{ column: "employees.salary", direction: "ASC" }],
      alias: "avg_dept_sal",
      frame: {
        frame_type: "ROWS",
        start: "UNBOUNDED PRECEDING",
        end: "CURRENT ROW",
        exclusion: undefined,
      },
    });
  });

  it("renders with initialSpec pre-populated", () => {
    const initialSpec: Partial<WindowFunctionSpec> = {
      function: "LEAD",
      arguments: ["salary"],
      partition_by: ["dept_id"],
      order_by: [{ column: "salary", direction: "DESC" }],
      frame: {
        frame_type: "GROUPS",
        start: "1 PRECEDING",
        end: "CURRENT ROW",
        exclusion: "GROUP",
      },
      alias: "lead_sal",
    };

    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={dummyCols}
        initialSpec={initialSpec}
      />
    );

    expect((screen.getByTestId("wf-function-select") as HTMLSelectElement).value).toBe("LEAD");
    expect((screen.getByTestId("wf-alias-input") as HTMLInputElement).value).toBe("lead_sal");
    expect((screen.getByTestId("wf-enable-frame-checkbox") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("wf-frame-type-select") as HTMLSelectElement).value).toBe("GROUPS");
    expect((screen.getByTestId("wf-exclusion-select") as HTMLSelectElement).value).toBe("GROUP");
  });

  it("renders with empty available columns and unstyled mode", () => {
    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={[]}
        unstyled={true}
      />
    );

    expect(screen.getByText("No columns available")).toBeTruthy();

    // unstyled with function SUM
    render(
      <WindowFunctionBuilder
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        availableColumns={dummyCols}
        initialSpec={{ function: "SUM", arguments: ["employees.salary"] }}
        unstyled={true}
      />
    );
    expect(screen.getAllByTestId("wf-arg-select").length).toBeGreaterThan(0);
  });

  it("renders with fallback theme colors when colors are omitted", () => {
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
        <WindowFunctionBuilder
          isOpen={true}
          onClose={vi.fn()}
          onSave={vi.fn()}
          availableColumns={dummyCols}
        />
      </ThemeContext.Provider>
    );
    expect(screen.getByTestId("window-function-builder-modal")).toBeTruthy();
  });
});
