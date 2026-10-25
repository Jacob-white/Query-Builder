import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { NlqPromptBar } from "../src/components/NlqPromptBar";
import type { QuerySpec } from "../src/types";
import type { SchemaDict } from "./helpers/partial";

describe("NlqPromptBar component", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  const mockSchema: SchemaDict = {
    tables: {
      users: {
        columns: {
          id: { data_type: "int" },
          email: { data_type: "text" },
        },
      },
      orders: {
        columns: {
          id: { data_type: "int" },
          total: { data_type: "float" },
        },
      },
    },
  };

  const mockQuerySpec: QuerySpec = {
    table: "users",
    columns: ["id", "email"],
    joins: [],
    filters: [],
    filter_join: "AND",
    order_by: [],
    limit: 50,
    distinct: false,
  };

  it("renders with default UI controls", () => {
    render(<NlqPromptBar schema={mockSchema} />);

    expect(screen.getByText("Natural Language Query")).toBeTruthy();
    expect(screen.getByLabelText("NLQ Input")).toBeTruthy();
    expect(screen.getByLabelText("Generate Query Button")).toBeTruthy();
    expect(screen.getByLabelText("NLQ Provider")).toBeTruthy();
    expect(screen.getByLabelText("Auto-apply to canvas")).toBeTruthy();
    expect(screen.getByLabelText("Insert table users")).toBeTruthy();
    expect(screen.getByLabelText("Insert table orders")).toBeTruthy();
  });

  it("hides schema pills and suggestions when disabled via props", () => {
    render(
      <NlqPromptBar
        schema={mockSchema}
        showSchemaPills={false}
        showSuggestions={false}
      />
    );

    expect(screen.queryByText("Tables:")).toBeNull();
    expect(screen.queryByText("Suggestions:")).toBeNull();
  });

  it("inserts table name into input when clicking schema pill", () => {
    render(<NlqPromptBar schema={mockSchema} />);

    const input = screen.getByLabelText("NLQ Input") as HTMLInputElement;
    expect(input.value).toBe("");

    fireEvent.click(screen.getByLabelText("Insert table users"));
    expect(input.value).toBe("Query users");

    fireEvent.click(screen.getByLabelText("Insert table orders"));
    expect(input.value).toBe("Query users from orders");
  });

  it("triggers translation and calls onApplySpec when clicking Generate", async () => {
    const onApply = vi.fn();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: 0.92,
        explanation: "Selecting users table.",
        steps: ["Step A", "Step B"],
      }),
    });

    render(<NlqPromptBar schema={mockSchema} onApplySpec={onApply} />);

    const input = screen.getByLabelText("NLQ Input");
    fireEvent.change(input, { target: { value: "Show users" } });

    const btn = screen.getByLabelText("Generate Query Button");
    fireEvent.click(btn);

    await waitFor(() => {
      expect(onApply).toHaveBeenCalledWith(mockQuerySpec);
    });

    expect(screen.getByTestId("nlq-explanation-box")).toBeTruthy();
    expect(screen.getByTestId("nlq-confidence-badge").textContent).toBe("92% Confidence");
    expect(screen.getByText("Selecting users table.")).toBeTruthy();
    expect(screen.getByText("Step A")).toBeTruthy();
  });

  it("submits translation on Enter key and clears on Escape key", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: 0.95,
        explanation: "Done",
      }),
    });

    render(<NlqPromptBar schema={mockSchema} />);

    const input = screen.getByLabelText("NLQ Input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Show users" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByTestId("nlq-explanation-box")).toBeTruthy();
    });

    // Escape clears state
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
    expect(screen.queryByTestId("nlq-explanation-box")).toBeNull();
  });

  it("supports ArrowUp and ArrowDown history navigation", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ spec: mockQuerySpec }),
    });

    render(<NlqPromptBar schema={mockSchema} />);

    const input = screen.getByLabelText("NLQ Input") as HTMLInputElement;

    // Send query 1
    fireEvent.change(input, { target: { value: "Query 1" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    // Send query 2
    fireEvent.change(input, { target: { value: "Query 2" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

    // Clear input
    fireEvent.change(input, { target: { value: "" } });

    // ArrowUp loads "Query 2"
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input.value).toBe("Query 2");

    // ArrowUp loads "Query 1"
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input.value).toBe("Query 1");

    // ArrowDown goes back to "Query 2"
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.value).toBe("Query 2");

    // ArrowDown again clears to empty
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.value).toBe("");
  });

  it("clicks suggestion pill to run quick query", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ spec: mockQuerySpec }),
    });

    render(<NlqPromptBar schema={mockSchema} />);

    const sugBtn = screen.getByLabelText(
      "Suggestion: Top 10 customers sorted by balance descending"
    );
    fireEvent.click(sugBtn);

    const input = screen.getByLabelText("NLQ Input") as HTMLInputElement;
    expect(input.value).toBe("Top 10 customers sorted by balance descending");
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
  });

  it("renders and triggers Explain button when currentSpec is supplied", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        explanation: "Explaining existing spec",
        steps: ["Step 1"],
      }),
    });

    render(
      <NlqPromptBar schema={mockSchema} currentSpec={mockQuerySpec} />
    );

    const explainBtn = screen.getByLabelText("Explain Query Button");
    expect(explainBtn).toBeTruthy();

    fireEvent.click(explainBtn);
    await waitFor(() => {
      expect(screen.getByText("Explaining existing spec")).toBeTruthy();
    });
  });

  it("displays error message callout and dismisses it", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Translation API offline"));

    render(<NlqPromptBar schema={mockSchema} />);

    const input = screen.getByLabelText("NLQ Input");
    fireEvent.change(input, { target: { value: "invalid" } });
    fireEvent.click(screen.getByLabelText("Generate Query Button"));

    await waitFor(() => {
      expect(screen.getByTestId("nlq-error-message")).toBeTruthy();
    });
    expect(screen.getByText("Translation API offline")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Dismiss Error"));
    expect(screen.queryByTestId("nlq-error-message")).toBeNull();
  });

  it("allows changing provider and toggling auto-apply", () => {
    render(<NlqPromptBar schema={mockSchema} />);

    const providerSelect = screen.getByLabelText("NLQ Provider") as HTMLSelectElement;
    expect(providerSelect.value).toBe("mock");
    fireEvent.change(providerSelect, { target: { value: "gemini" } });
    expect(providerSelect.value).toBe("gemini");

    const autoApplyCheckbox = screen.getByLabelText("Auto-apply to canvas") as HTMLInputElement;
    expect(autoApplyCheckbox.checked).toBe(true);
    fireEvent.click(autoApplyCheckbox);
    expect(autoApplyCheckbox.checked).toBe(false);
  });

  it("renders Undo button after multiple queries and allows undoing", async () => {
    const onApply = vi.fn();
    const spec1 = { ...mockQuerySpec, table: "users" };
    const spec2 = { ...mockQuerySpec, table: "orders" };

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ spec: spec1 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ spec: spec2 }) });

    render(<NlqPromptBar schema={mockSchema} onApplySpec={onApply} />);

    const input = screen.getByLabelText("NLQ Input");
    fireEvent.change(input, { target: { value: "q1" } });
    fireEvent.click(screen.getByLabelText("Generate Query Button"));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    expect(screen.queryByLabelText("Undo Translation Button")).toBeNull();

    fireEvent.change(input, { target: { value: "q2" } });
    fireEvent.click(screen.getByLabelText("Generate Query Button"));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

    const undoBtn = screen.getByLabelText("Undo Translation Button");
    expect(undoBtn).toBeTruthy();

    fireEvent.click(undoBtn);
    expect(onApply).toHaveBeenLastCalledWith(spec1);
  });

  it("handles undefined schema and confidence below 0.8", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        spec: mockQuerySpec,
        confidence: 0.65,
        explanation: "Low confidence translation",
        steps: [],
      }),
    });

    render(<NlqPromptBar />);

    const input = screen.getByLabelText("NLQ Input");
    fireEvent.change(input, { target: { value: "vague query" } });

    // Press Shift+Enter -> does not trigger
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(screen.queryByTestId("nlq-explanation-box")).toBeNull();

    // Regular Enter -> triggers
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    await waitFor(() => {
      expect(screen.getByTestId("nlq-confidence-badge")).toBeTruthy();
    });

    const badge = screen.getByTestId("nlq-confidence-badge");
    expect(badge.textContent).toBe("65% Confidence");
    expect(badge.style.backgroundColor).toBe("rgb(254, 249, 195)"); // #fef9c3
  });

  it("renders with unstyled={true} without inline styles", () => {
    const { container } = render(<NlqPromptBar schema={mockSchema} unstyled={true} />);
    const bar = container.querySelector('[data-testid="nlq-prompt-bar"]') as HTMLElement;
    expect(bar).toBeTruthy();
    expect(bar.getAttribute("style")).toBeNull();
  });

  it("supports multi-shot follow-up refinement input, follow-up chips, and turn reversion", async () => {
    const onApply = vi.fn();
    const specTurn1: QuerySpec = { ...mockQuerySpec, table: "users", limit: 50 };
    const specTurn2: QuerySpec = { ...mockQuerySpec, table: "users", limit: 5 };

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          spec: specTurn1,
          confidence: 0.91,
          explanation: "Initial users query",
          follow_ups: ["Limit to 5 rows"],
        }),
      })
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          spec: specTurn2,
          confidence: 0.96,
          explanation: "Refined to 5 rows",
          follow_ups: ["Sort by email"],
        }),
      });

    render(<NlqPromptBar schema={mockSchema} onApplySpec={onApply} />);

    // Turn 1
    const input = screen.getByLabelText("NLQ Input");
    fireEvent.change(input, { target: { value: "Show users" } });
    fireEvent.click(screen.getByLabelText("Generate Query Button"));

    await waitFor(() => {
      expect(screen.getByText("Initial users query")).toBeTruthy();
    });
    expect(screen.getByTestId("nlq-turn-badge").textContent).toBe("Turn 1");

    // Turn 2 via Follow-up Refinement Input
    const followUpInput = screen.getByTestId("nlq-followup-input") as HTMLInputElement;
    fireEvent.change(followUpInput, { target: { value: "Only top 5" } });
    fireEvent.click(screen.getByTestId("nlq-followup-submit"));

    await waitFor(() => {
      expect(screen.getByText("Refined to 5 rows")).toBeTruthy();
    });
    expect(screen.getByTestId("nlq-turn-badge").textContent).toBe("Turn 2");
    expect(screen.getByTestId("nlq-conversation-thread")).toBeTruthy();

    // Revert back to Turn 1
    fireEvent.click(screen.getByLabelText("Restore turn 1"));
    expect(screen.getByText("Initial users query")).toBeTruthy();
    expect(onApply).toHaveBeenLastCalledWith(specTurn1);

    // Follow-up chip click, Enter key on followUpInput, and New Chat button
    const chipBtn = screen.getByLabelText("Follow-up: Limit to 5 rows");
    fireEvent.click(chipBtn);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));

    const fuInput2 = screen.getByTestId("nlq-followup-input") as HTMLInputElement;
    fireEvent.change(fuInput2, { target: { value: "sort asc" } });
    fireEvent.keyDown(fuInput2, { key: "Enter", shiftKey: false });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(4));

    fireEvent.click(screen.getByLabelText("New AI Conversation"));
    expect(screen.queryByTestId("nlq-explanation-box")).toBeNull();
  });

  it("supports AI Engine Selector pills, showMoreProviders toggle, and >6 schema tables filter", () => {
    const bigSchema = {
      tables: {
        t1: { name: "t1", columns: [] },
        t2: { name: "t2", columns: [] },
        t3: { name: "t3", columns: [] },
        t4: { name: "t4", columns: [] },
        t5: { name: "t5", columns: [] },
        t6: { name: "t6", columns: [] },
        t7_extra: { name: "t7_extra", columns: [] },
      },
    };
    render(<NlqPromptBar schema={bigSchema} />);

    // Provider pill selection and expand toggle
    const engineGroup = screen.getByRole("group", { name: "AI Engine Selector" });
    const expandProvidersBtn = engineGroup.querySelectorAll("button")[2];
    fireEvent.click(expandProvidersBtn);
    fireEvent.click(screen.getByText("OpenAI"));
    fireEvent.click(expandProvidersBtn);

    // Expand >6 tables and filter
    const moreTablesBtn = screen.getByText(/\+1 more tables/i);
    fireEvent.click(moreTablesBtn);
    const filterInput = screen.getByPlaceholderText("Filter tables...");
    fireEvent.change(filterInput, { target: { value: "t7" } });
    expect(screen.getByLabelText("Insert table t7_extra")).toBeTruthy();
    fireEvent.click(screen.getByText(/Show fewer/i));
  });
});
