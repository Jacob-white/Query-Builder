import React, { createRef } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type { QuerySpec, QueryResultData, SchemaSnapshot, VisualQueryBuilderRef } from "../src/types";

/**
 * Characterization tests pinning observable behavior of VisualQueryBuilder
 * (tab switching, raw-SQL notice, undo/redo shortcuts, persisted advanced mode,
 * controlled value sync, imperative ref API) so the component can be split safely.
 */
const schema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "email", data_type: "text", is_nullable: false, is_primary: false },
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
  foreign_keys: [],
};

const results: QueryResultData = { columns: ["id"], rows: [{ id: 1 }], count: 1, durationMs: 3 };

function tab(name: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-qb-tab="${name}"]`);
  if (!el) throw new Error(`tab ${name} not found`);
  return el;
}
function panel(name: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-qb-panel="${name}"]`);
}
function sqlEditor(): HTMLTextAreaElement {
  return screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement;
}

beforeEach(() => {
  localStorage.clear();
});

describe("VisualQueryBuilder characterization: tabs", () => {
  it("starts on the visual tab and switches panels/ARIA on click", () => {
    render(<VisualQueryBuilder schema={schema} initialTable="users" />);
    const root = document.querySelector('[data-qb="root"]') as HTMLElement;
    expect(root.getAttribute("data-qb-mode")).toBe("visual");
    expect(tab("visual").getAttribute("aria-selected")).toBe("true");
    expect(tab("visual").getAttribute("tabindex")).toBe("0");
    expect(tab("sql").getAttribute("tabindex")).toBe("-1");
    expect(panel("visual")?.getAttribute("role")).toBe("tabpanel");
    expect(panel("visual")?.getAttribute("aria-labelledby")).toBe("tab-visual");

    fireEvent.click(tab("sql"));
    expect(root.getAttribute("data-qb-mode")).toBe("sql");
    expect(panel("visual")).toBeNull();
    expect(panel("sql")).not.toBeNull();
    expect(sqlEditor().value).toContain("users");

    fireEvent.click(tab("results"));
    expect(panel("results")).not.toBeNull();
    fireEvent.click(tab("chart"));
    expect(panel("chart")).not.toBeNull();
  });

  it("supports arrow/Home/End keyboard navigation across visible tabs", () => {
    render(<VisualQueryBuilder schema={schema} initialTable="users" />);
    fireEvent.keyDown(tab("visual"), { key: "ArrowRight" });
    expect(tab("sql").getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab("sql"));
    fireEvent.keyDown(tab("sql"), { key: "ArrowLeft" });
    expect(tab("visual").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab("visual"), { key: "ArrowLeft" });
    expect(tab("chart").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab("chart"), { key: "Home" });
    expect(tab("visual").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab("visual"), { key: "End" });
    expect(tab("chart").getAttribute("aria-selected")).toBe("true");
  });

  it("only renders plan and pipeline tabs when enabled", () => {
    const { unmount } = render(<VisualQueryBuilder schema={schema} initialTable="users" />);
    expect(document.querySelector('[data-qb-tab="plan"]')).toBeNull();
    expect(document.querySelector('[data-qb-tab="pipeline"]')).toBeNull();
    unmount();
    render(<VisualQueryBuilder schema={schema} initialTable="users" showPlanTab showPipelineTab />);
    fireEvent.click(tab("plan"));
    expect(panel("plan")).not.toBeNull();
    fireEvent.click(tab("pipeline"));
    expect(panel("pipeline")).not.toBeNull();
  });

  it("shows the result count in the results tab label after running a query", async () => {
    const onExecuteQuery = vi.fn().mockResolvedValue(results);
    render(<VisualQueryBuilder schema={schema} initialTable="users" onExecuteQuery={onExecuteQuery} />);
    fireEvent.click(screen.getByLabelText("Run query"));
    await waitFor(() => expect(panel("results")).not.toBeNull());
    expect(tab("results").textContent).toContain("(1)");
    expect(onExecuteQuery).toHaveBeenCalledTimes(1);
  });

  it("surfaces execution errors in an alert", async () => {
    const onExecuteQuery = vi.fn().mockRejectedValue(new Error("boom"));
    render(<VisualQueryBuilder schema={schema} initialTable="users" onExecuteQuery={onExecuteQuery} />);
    fireEvent.click(screen.getByLabelText("Run query"));
    expect((await screen.findByRole("alert")).textContent).toContain("boom");
  });
});

describe("VisualQueryBuilder characterization: raw SQL mode", () => {
  it("edits to the raw SQL tab are returned by the ref and survive tab switches", () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    fireEvent.click(tab("sql"));
    expect(screen.queryByText("Custom Raw SQL (Visual Canvas Unsynced)")).toBeNull();
    fireEvent.change(sqlEditor(), { target: { value: "SELECT 1" } });
    expect(document.querySelector('[data-qb="sql-sync-badge"]')?.textContent).toContain("Unsynced");
    expect(ref.current?.getSql()).toBe("SELECT 1");
    expect(ref.current?.getSpec()).toBeNull();
    fireEvent.click(tab("visual"));
    fireEvent.click(tab("sql"));
    expect(sqlEditor().value).toBe("SELECT 1");
  });

  it("parseable raw SQL shows the synced badge", () => {
    render(<VisualQueryBuilder schema={schema} initialTable="users" />);
    fireEvent.click(tab("sql"));
    fireEvent.change(sqlEditor(), { target: { value: "SELECT id FROM orders" } });
    expect(document.querySelector('[data-qb="sql-sync-badge"]')?.textContent).toContain("Synced");
  });

  it("shows a discard notice when a visual edit replaces unmappable raw SQL, and restores or dismisses it", async () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    fireEvent.click(tab("sql"));
    fireEvent.change(sqlEditor(), { target: { value: "SELECT 1" } });
    // Flush the snapshot effect, then perform a visual-side change.
    act(() => {
      ref.current?.reset();
    });
    const notice = document.querySelector('[data-qb="raw-sql-discarded-notice"]');
    expect(notice).not.toBeNull();
    expect(notice?.textContent).toContain("Restore my SQL");

    fireEvent.click(document.querySelector('[data-qb="btn-dismiss-raw-sql-notice"]') as HTMLElement);
    expect(document.querySelector('[data-qb="raw-sql-discarded-notice"]')).toBeNull();

    act(() => {
      ref.current?.setSpec({ table: "orders", columns: ["orders.id"] });
    });
    // Back in raw mode on re-entry? Restore flow: put raw SQL back via the editor first.
    fireEvent.change(sqlEditor(), { target: { value: "SELECT 2" } });
    act(() => {
      ref.current?.reset();
    });
    fireEvent.click(document.querySelector('[data-qb="btn-restore-raw-sql"]') as HTMLElement);
    expect(sqlEditor().value).toBe("SELECT 2");
    expect(document.querySelector('[data-qb="raw-sql-discarded-notice"]')).toBeNull();
  });

  it("does not show a notice when the raw SQL maps cleanly onto the visual model", () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    fireEvent.click(tab("sql"));
    fireEvent.change(sqlEditor(), { target: { value: "SELECT id FROM orders" } });
    act(() => {
      ref.current?.reset();
    });
    expect(document.querySelector('[data-qb="raw-sql-discarded-notice"]')).toBeNull();
  });

  it("'Sync with visual canvas' returns to compiled SQL", () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    fireEvent.click(tab("sql"));
    fireEvent.change(sqlEditor(), { target: { value: "SELECT 1" } });
    fireEvent.click(screen.getByLabelText("Sync with visual canvas"));
    expect(document.querySelector('[data-qb="sql-sync-badge"]')).toBeNull();
    expect(ref.current?.getSql()).toContain("users");
  });

  it("selecting a preset loads its SQL into the raw editor", () => {
    render(
      <VisualQueryBuilder
        schema={schema}
        initialTable="users"
        presets={[{ id: "p1", title: "Preset one", sql: "SELECT id FROM users" } as never]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Starter query presets"), { target: { value: "p1" } });
    expect(panel("sql")).not.toBeNull();
    expect(sqlEditor().value).toBe("SELECT id FROM users");
  });
});

describe("VisualQueryBuilder characterization: undo/redo shortcuts", () => {
  it("Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y undo and redo, and buttons mirror history", () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    const undo = screen.getByLabelText(/Undo query changes/) as HTMLButtonElement;
    const redo = screen.getByLabelText(/Redo query changes/) as HTMLButtonElement;
    expect(undo.disabled).toBe(true);
    act(() => {
      ref.current?.setSpec({ table: "orders", columns: ["orders.id"], limit: 5 });
    });
    expect(undo.disabled).toBe(false);
    expect(ref.current?.canUndo()).toBe(true);

    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(ref.current?.canRedo()).toBe(true);
    fireEvent.keyDown(window, { key: "Z", metaKey: true, shiftKey: true });
    expect(ref.current?.canRedo()).toBe(false);
    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(ref.current?.canRedo()).toBe(true);
    fireEvent.keyDown(window, { key: "y", ctrlKey: true });
    expect(ref.current?.canRedo()).toBe(false);
    fireEvent.click(undo);
    expect(ref.current?.canRedo()).toBe(true);
    fireEvent.click(redo);
    expect(ref.current?.canRedo()).toBe(false);
  });

  it("ignores undo shortcuts while typing in an input", () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    act(() => {
      ref.current?.setSpec({ table: "orders", columns: ["orders.id"] });
    });
    fireEvent.click(tab("sql"));
    fireEvent.keyDown(sqlEditor(), { key: "z", ctrlKey: true });
    expect(ref.current?.canRedo()).toBe(false);
  });

  it("Escape closes the schema explorer and ERD modals", () => {
    render(<VisualQueryBuilder schema={schema} initialTable="users" />);
    fireEvent.click(screen.getByLabelText("Open schema ERD modal"));
    expect(screen.queryAllByRole("dialog").length).toBeGreaterThan(0);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryAllByRole("dialog").length).toBe(0);
  });
});

describe("VisualQueryBuilder characterization: advanced mode persistence", () => {
  it("defaults to advanced mode, persists toggles, and reads them back", () => {
    const onAdvancedModeChange = vi.fn();
    const { unmount } = render(
      <VisualQueryBuilder schema={schema} initialTable="users" onAdvancedModeChange={onAdvancedModeChange} />,
    );
    const toggle = screen.getByTestId("btn-toggle-advanced");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(localStorage.getItem("qb_advanced_mode")).toBe("false");
    expect(onAdvancedModeChange).toHaveBeenCalledWith(false);
    unmount();

    render(<VisualQueryBuilder schema={schema} initialTable="users" />);
    expect(screen.getByTestId("btn-toggle-advanced").getAttribute("aria-pressed")).toBe("false");
  });

  it("honors a custom storageKey, defaultAdvancedMode, and storageKey={''} disabling persistence", () => {
    localStorage.setItem("custom_key", "false");
    const { unmount } = render(
      <VisualQueryBuilder schema={schema} initialTable="users" storageKey="custom_key" />,
    );
    expect(screen.getByTestId("btn-toggle-advanced").getAttribute("aria-pressed")).toBe("false");
    unmount();

    render(
      <VisualQueryBuilder schema={schema} initialTable="users" storageKey="" defaultAdvancedMode={false} />,
    );
    const t = screen.getByTestId("btn-toggle-advanced");
    expect(t.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(t);
    expect(t.getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("")).toBeNull();
  });

  it("a controlled advancedMode prop wins over storage and does not follow internal toggles", () => {
    localStorage.setItem("qb_advanced_mode", "false");
    const onAdvancedModeChange = vi.fn();
    render(
      <VisualQueryBuilder
        schema={schema}
        initialTable="users"
        advancedMode
        onAdvancedModeChange={onAdvancedModeChange}
      />,
    );
    const t = screen.getByTestId("btn-toggle-advanced");
    expect(t.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(t);
    expect(onAdvancedModeChange).toHaveBeenCalledWith(false);
    expect(t.getAttribute("aria-pressed")).toBe("true");
  });

  it("survives a throwing localStorage", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    try {
      render(<VisualQueryBuilder schema={schema} initialTable="users" defaultAdvancedMode={false} />);
      const t = screen.getByTestId("btn-toggle-advanced");
      expect(t.getAttribute("aria-pressed")).toBe("false");
      fireEvent.click(t);
      expect(t.getAttribute("aria-pressed")).toBe("true");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it("hidden advanced clauses banner appears in simple mode and can be cleared", () => {
    const ctes = [
      { name: "c1", query: { table: "users", columns: ["users.id"] } },
    ] as never;
    render(
      <VisualQueryBuilder
        schema={schema}
        initialTable="users"
        defaultAdvancedMode={false}
        initialCtes={ctes}
      />,
    );
    expect(screen.queryByTestId("active-advanced-clauses-banner")).not.toBeNull();
    fireEvent.click(screen.getByTestId("btn-clear-advanced-clauses"));
    expect(screen.queryByTestId("active-advanced-clauses-banner")).toBeNull();
  });
});

describe("VisualQueryBuilder characterization: controlled value and onChange", () => {
  it("syncs a changed value prop, ignores equivalent re-renders, and reports user edits", async () => {
    const onChange = vi.fn();
    const ref = createRef<VisualQueryBuilderRef>();
    const a: QuerySpec = { table: "orders", columns: ["orders.id"], limit: 10 };
    const { rerender } = render(
      <VisualQueryBuilder ref={ref} schema={schema} value={a} onChange={onChange} />,
    );
    expect(ref.current?.getSpec()?.limit).toBe(10);
    onChange.mockClear();

    // Structurally equal value with a new identity: no reload, no onChange.
    rerender(
      <VisualQueryBuilder ref={ref} schema={schema} value={{ ...a }} onChange={onChange} />,
    );
    expect(onChange).not.toHaveBeenCalled();

    const b: QuerySpec = { table: "orders", columns: ["orders.id", "orders.amount"], limit: 99 };
    rerender(<VisualQueryBuilder ref={ref} schema={schema} value={b} onChange={onChange} />);
    await waitFor(() => expect(ref.current?.getSpec()?.limit).toBe(99));
    expect(onChange).not.toHaveBeenCalled();

    act(() => {
      ref.current?.setSpec({ table: "users", columns: ["users.id"] });
    });
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const [spec, sql] = onChange.mock.calls[onChange.mock.calls.length - 1];
    expect((spec as QuerySpec).table).toBe("users");
    expect(String(sql)).toContain("users");
  });

  it("reports unparsed raw SQL with a null spec", async () => {
    const onChange = vi.fn();
    render(<VisualQueryBuilder schema={schema} initialTable="users" onChange={onChange} />);
    fireEvent.click(tab("sql"));
    fireEvent.change(sqlEditor(), { target: { value: "SELECT 1" } });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null, "SELECT 1"));
  });
});

describe("VisualQueryBuilder characterization: imperative ref API", () => {
  it("exposes getSpec/getSql/setSpec/reset/undo/redo/execute", async () => {
    const ref = createRef<VisualQueryBuilderRef>();
    const onExecuteQuery = vi.fn().mockResolvedValue(results);
    render(
      <VisualQueryBuilder ref={ref} schema={schema} initialTable="users" onExecuteQuery={onExecuteQuery} />,
    );
    expect(ref.current?.getSpec()?.table).toBe("users");
    expect(ref.current?.getSql()).toContain("users");
    expect(ref.current?.canUndo()).toBe(false);

    act(() => {
      ref.current?.setSpec({ table: "orders", columns: ["orders.amount"] });
    });
    expect(ref.current?.getSpec()?.table).toBe("orders");
    act(() => {
      ref.current?.undo();
    });
    expect(ref.current?.getSpec()?.table).toBe("users");
    act(() => {
      ref.current?.redo();
    });
    expect(ref.current?.getSpec()?.table).toBe("orders");
    act(() => {
      ref.current?.reset();
    });
    expect(ref.current?.getSpec()?.table).not.toBe("orders");

    let out: QueryResultData | undefined | void;
    await act(async () => {
      out = await ref.current?.execute();
    });
    expect(out).toEqual(results);
    expect(onExecuteQuery).toHaveBeenCalled();
    expect(panel("results")).not.toBeNull();
  });

  it("execute resolves undefined when no executor is configured", async () => {
    const ref = createRef<VisualQueryBuilderRef>();
    render(<VisualQueryBuilder ref={ref} schema={schema} initialTable="users" />);
    let out: unknown = "unset";
    await act(async () => {
      out = await ref.current?.execute();
    });
    expect(out).toBeUndefined();
  });
});

describe("VisualQueryBuilder characterization: theming and structure", () => {
  it("applies css variables when styled and none when unstyled", () => {
    const { unmount } = render(<VisualQueryBuilder schema={schema} initialTable="users" theme="light" />);
    const root = document.querySelector('[data-qb="root"]') as HTMLElement;
    expect(root.getAttribute("data-qb-unstyled")).toBeNull();
    expect(root.getAttribute("style") ?? "").toContain("--");
    unmount();
    render(<VisualQueryBuilder schema={schema} initialTable="users" unstyled />);
    const root2 = document.querySelector('[data-qb="root"]') as HTMLElement;
    expect(root2.getAttribute("data-qb-unstyled")).toBe("true");
    expect(root2.getAttribute("style")).toBeNull();
  });

  it("renders the toolbar controls and safety badge", () => {
    render(<VisualQueryBuilder schema={schema} initialTable="users" dialect="mysql" />);
    expect(screen.getByTestId("dialect-badge").textContent).toBe("mysql");
    expect(document.querySelector('[data-qb="safety-badge"]')?.getAttribute("data-qb-safety")).toBe("valid");
    expect(document.querySelector('[data-qb="btn-run"]')).not.toBeNull();
    expect(document.querySelector('[data-qb="btn-undo"]')).not.toBeNull();
    expect(document.querySelectorAll('[data-qb="btn-templates"]').length).toBe(2);
  });

  it("hides Run in readOnly mode and opens the feature settings popover", () => {
    render(<VisualQueryBuilder schema={schema} initialTable="users" readOnly />);
    expect(document.querySelector('[data-qb="btn-run"]')).toBeNull();
    fireEvent.click(screen.getByTestId("btn-feature-settings"));
    expect(screen.getByTestId("feature-settings-popover")).toBeTruthy();
    fireEvent.change(screen.getByTestId("feature-select-raw_sql"), { target: { value: "disabled" } });
    expect(document.querySelector('[data-qb-tab="sql"]')).toBeNull();
  });
});
