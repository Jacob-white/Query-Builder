import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { ComponentShowcase, type SchemaSnapshot } from "../src/index";

const MOCK_CUSTOM_SCHEMA: SchemaSnapshot = {
  tables: {
    accounts: {
      name: "accounts",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "balance", data_type: "DECIMAL", is_nullable: false, is_primary: false },
      ],
    },
  },
};

describe("ComponentShowcase", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders with default props and mounts Studio tab by default", async () => {
    render(<ComponentShowcase />);

    expect(
      screen.getByText(/Query-Builder Component Catalog & Documentation/i),
    ).toBeDefined();

    // Tabs exist
    expect(screen.getByRole("button", { name: "Full Studio" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Headless Hooks" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Visual Charts" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Theming Playground" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Template Library" })).toBeDefined();

    // Studio content is mounted
    expect(screen.getByRole("tab", { name: /visual builder/i })).toBeDefined();

    // Run query in Studio
    const runStudioBtn = screen.getByRole("button", { name: /run query/i });
    await act(async () => {
      fireEvent.click(runStudioBtn);
    });

    // Live code snippet displayed
    expect(screen.getByText(/Live Code Snippet \(studio\)/i)).toBeDefined();
  });

  it("supports copying code snippets to clipboard with feedback", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<ComponentShowcase />);

    const copyBtn = screen.getByRole("button", { name: /copy code/i });
    expect(copyBtn).toBeDefined();

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextMock).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /copied!/i })).toBeDefined();

    // Fast-forward timeout to revert copy button text
    act(() => {
      vi.advanceTimersByTime(2100);
    });

    expect(screen.getByRole("button", { name: /copy code/i })).toBeDefined();
  });

  it("navigates to Headless Hooks tab and exercises interactive state", async () => {
    render(<ComponentShowcase />);

    const headlessTabBtn = screen.getByRole("button", { name: "Headless Hooks" });
    fireEvent.click(headlessTabBtn);

    expect(screen.getByText(/Headless Query State & Controls/i)).toBeDefined();

    // Run query with zero projection keys selected (tests line 120 fallback)
    const runBtn = screen.getByRole("button", { name: /run headless query/i });
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByText(/Query Results:/i)).toBeDefined();

    // Add orders table
    const addOrdersBtn = screen.getByRole("button", { name: /\+ orders/i });
    fireEvent.click(addOrdersBtn);
    expect(screen.getByRole("button", { name: /✓ orders/i })).toBeDefined();

    // Remove orders table
    fireEvent.click(screen.getByRole("button", { name: /✓ orders/i }));
    expect(screen.getByRole("button", { name: /\+ orders/i })).toBeDefined();

    // Toggle column checkbox
    const nameCheckbox = screen.getByLabelText("name");
    fireEvent.click(nameCheckbox);

    // Change limit input with empty string then number
    const limitInput = screen.getByLabelText(/limit/i);
    fireEvent.change(limitInput, { target: { value: "" } });
    fireEvent.change(limitInput, { target: { value: "5" } });

    // Run query again with selected projection
    await act(async () => {
      fireEvent.click(runBtn);
    });
    expect(screen.getByText(/Query Results:/i)).toBeDefined();
  });

  it("navigates to Visual Charts tab", () => {
    render(<ComponentShowcase />);

    const chartsTabBtn = screen.getByRole("button", { name: "Visual Charts" });
    fireEvent.click(chartsTabBtn);

    expect(screen.getByRole("button", { name: "Bar Chart" })).toBeDefined();
    expect(screen.getByText(/Live Code Snippet \(charts\)/i)).toBeDefined();
  });

  it("navigates to Theming Playground and tests theme mode & color swatches", () => {
    render(<ComponentShowcase />);

    const themingTabBtn = screen.getByRole("button", { name: "Theming Playground" });
    fireEvent.click(themingTabBtn);

    expect(screen.getByText(/Primary Color:/i)).toBeDefined();

    // Toggle to Light Mode
    const lightBtn = screen.getByRole("button", { name: /light mode/i });
    fireEvent.click(lightBtn);

    // Toggle back to Dark Mode
    const darkBtn = screen.getByRole("button", { name: /dark mode/i });
    fireEvent.click(darkBtn);

    // Pick Emerald color
    const emeraldSwatch = screen.getByTitle("Emerald");
    fireEvent.click(emeraldSwatch);

    // Pick Violet color
    const violetSwatch = screen.getByTitle("Violet");
    fireEvent.click(violetSwatch);

    expect(screen.getByText(/Live Code Snippet \(theming\)/i)).toBeDefined();
  });

  it("navigates to Template Library, selects a template, opens and closes modal", () => {
    render(<ComponentShowcase />);

    const templatesTabBtn = screen.getByRole("button", { name: "Template Library" });
    fireEvent.click(templatesTabBtn);

    expect(
      screen.getByText(/Pre-configured query templates available for self-service analysts:/i),
    ).toBeDefined();

    // Select first template card
    const templateCard = screen.getByText("Active Users Directory");
    fireEvent.click(templateCard);

    expect(screen.getByText(/Selected Template:/i)).toBeDefined();

    // Open template manager modal
    const openMgrBtn = screen.getByRole("button", { name: /open template manager/i });
    fireEvent.click(openMgrBtn);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeDefined();

    // Close modal via close button
    const closeBtn = screen.getByText("✕");
    fireEvent.click(closeBtn);
    expect(screen.queryByRole("dialog")).toBeNull();

    // Open again and click Load on a template inside modal
    fireEvent.click(openMgrBtn);
    const loadButtons = screen.getAllByRole("button", { name: /load/i });
    if (loadButtons[0]) {
      fireEvent.click(loadButtons[0]);
    }
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("supports custom initialTab, initialSchema, className, and style props", () => {
    const { container } = render(
      <ComponentShowcase
        initialTab="charts"
        initialSchema={MOCK_CUSTOM_SCHEMA}
        className="custom-showcase-class"
        style={{ margin: "20px" }}
      />,
    );

    expect((container.firstChild as HTMLElement)?.className).toContain("custom-showcase-class");
    expect(screen.getByText(/Live Code Snippet \(charts\)/i)).toBeDefined();
  });
});
