import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  QueryTemplateManager,
  SEED_TEMPLATES,
  loadTemplates,
  saveTemplates,
  resetTemplateStorage,
} from "../src/components/QueryTemplateManager";
import type { QueryTemplate } from "../src/types";

describe("QueryTemplateManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetTemplateStorage();
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(
      <QueryTemplateManager
        isOpen={false}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders modal in library mode by default with seed templates", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Query Template Manager")).toBeTruthy();
    expect(screen.getByText("Active Users Directory")).toBeTruthy();
    expect(screen.getByText("High-Value Orders Audit")).toBeTruthy();
    expect(screen.getByText("User Order Aggregates")).toBeTruthy();
    expect(screen.getAllByText("Built-in").length).toBe(3);
  });

  it("filters templates by search term matching title or description", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    const searchInput = screen.getByLabelText("Search templates");
    fireEvent.change(searchInput, { target: { value: "Audit" } });

    expect(screen.getByText("High-Value Orders Audit")).toBeTruthy();
    expect(screen.queryByText("Active Users Directory")).toBeNull();
    expect(screen.queryByText("User Order Aggregates")).toBeNull();

    // Search by category
    fireEvent.change(searchInput, { target: { value: "analytics" } });
    expect(screen.getByText("User Order Aggregates")).toBeTruthy();
    expect(screen.queryByText("High-Value Orders Audit")).toBeNull();
  });

  it("filters templates by category selector pills", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    const usersPill = screen.getByRole("button", { name: "Users" });
    fireEvent.click(usersPill);

    expect(screen.getByText("Active Users Directory")).toBeTruthy();
    expect(screen.queryByText("High-Value Orders Audit")).toBeNull();
    expect(screen.queryByText("User Order Aggregates")).toBeNull();

    // Click "All" to restore
    const allPill = screen.getByRole("button", { name: "All" });
    fireEvent.click(allPill);
    expect(screen.getByText("Active Users Directory")).toBeTruthy();
    expect(screen.getByText("High-Value Orders Audit")).toBeTruthy();
  });

  it("displays empty state message when search query has no matches", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    const searchInput = screen.getByLabelText("Search templates");
    fireEvent.change(searchInput, { target: { value: "nonexistent query xyz" } });

    expect(screen.getByText(/No templates found matching your criteria/i)).toBeTruthy();
  });

  it("toggles SQL preview on template card", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    const previewBtn = screen.getByLabelText("Preview SQL for Active Users Directory");
    fireEvent.click(previewBtn);

    // SQL Code Preview should be visible
    const sqlTextarea = screen.getByLabelText("SQL Code Preview");
    expect(sqlTextarea).toBeTruthy();
    expect((sqlTextarea as HTMLTextAreaElement).value).toContain('SELECT "users"."id"');

    // Click again to hide
    fireEvent.click(screen.getByText("Hide SQL"));
    expect(screen.queryByLabelText("SQL Code Preview")).toBeNull();
  });

  it("loads template and closes modal", () => {
    const handleLoad = vi.fn();
    const handleClose = vi.fn();

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={handleClose}
        onLoadTemplate={handleLoad}
      />
    );

    const loadBtns = screen.getAllByText("▶ Load Template");
    fireEvent.click(loadBtns[0]);

    expect(handleLoad).toHaveBeenCalledOnce();
    expect(handleLoad).toHaveBeenCalledWith(
      expect.objectContaining({ id: "tpl_default_users" })
    );
    expect(handleClose).toHaveBeenCalledOnce();
  });

  it("deletes user-created template and calls onDeleteTemplate", () => {
    const handleDeleteProp = vi.fn();

    const customTemplate: QueryTemplate = {
      id: "custom_tpl_1",
      title: "My Custom Metric",
      category: "Custom",
      sql: "SELECT 1;",
      createdAt: new Date().toISOString(),
      isDefault: false,
    };

    saveTemplates([customTemplate, ...SEED_TEMPLATES]);

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        onDeleteTemplate={handleDeleteProp}
      />
    );

    expect(screen.getByText("My Custom Metric")).toBeTruthy();

    const deleteBtn = screen.getByLabelText("Delete My Custom Metric");
    fireEvent.click(deleteBtn);

    expect(screen.queryByText("My Custom Metric")).toBeNull();
    expect(handleDeleteProp).toHaveBeenCalledWith("custom_tpl_1");
  });

  it("prevents deletion of default seed templates (no delete button rendered)", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    expect(screen.queryByLabelText("Delete Active Users Directory")).toBeNull();
    expect(screen.queryByLabelText("Delete High-Value Orders Audit")).toBeNull();
  });

  it("switches between Library and Save modes and supports Cancel", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    const saveTabBtn = screen.getByText("➕ Save Current Query");
    fireEvent.click(saveTabBtn);

    expect(screen.getByLabelText("Template Title")).toBeTruthy();
    expect(screen.getByLabelText("Template Category")).toBeTruthy();

    // Click Cancel to return to Library
    const cancelBtn = screen.getByText("Cancel");
    fireEvent.click(cancelBtn);

    expect(screen.getByLabelText("Search templates")).toBeTruthy();

    // Switch to save again and click Library tab in header
    fireEvent.click(saveTabBtn);
    expect(screen.getByLabelText("Template Title")).toBeTruthy();
    const libraryTabBtn = screen.getByText(/📚 Library/);
    fireEvent.click(libraryTabBtn);
    expect(screen.getByLabelText("Search templates")).toBeTruthy();
  });

  it("validates template title on save form submission and clears error on change", () => {
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        defaultMode="save"
      />
    );

    const submitBtn = screen.getByText("💾 Save Template");
    fireEvent.click(submitBtn);

    expect(screen.getByText("⚠️ Title is required.")).toBeTruthy();

    // Type in title to clear error
    const titleInput = screen.getByLabelText("Template Title");
    fireEvent.change(titleInput, { target: { value: "New Title" } });

    expect(screen.queryByText("⚠️ Title is required.")).toBeNull();
  });

  it("saves new template successfully with title, category, description, and spec", () => {
    const handleSaveProp = vi.fn();

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        onSaveTemplate={handleSaveProp}
        currentSql="SELECT * FROM orders;"
        currentSpec={{ table: "orders" }}
        defaultMode="save"
      />
    );

    const titleInput = screen.getByLabelText("Template Title");
    const categoryInput = screen.getByLabelText("Template Category");
    const descInput = screen.getByLabelText("Template Description");

    fireEvent.change(titleInput, { target: { value: "Orders Overview" } });
    fireEvent.change(categoryInput, { target: { value: "Finance" } });
    fireEvent.change(descInput, { target: { value: "Summary of recent orders" } });

    const submitBtn = screen.getByText("💾 Save Template");
    fireEvent.click(submitBtn);

    expect(handleSaveProp).toHaveBeenCalledOnce();
    expect(handleSaveProp).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Orders Overview",
        category: "Finance",
        description: "Summary of recent orders",
        sql: "SELECT * FROM orders;",
        spec: { table: "orders" },
        isDefault: false,
      })
    );

    // Modal should have transitioned back to library view
    expect(screen.getByLabelText("Search templates")).toBeTruthy();
    expect(screen.getByText("Orders Overview")).toBeTruthy();
  });

  it("falls back to in-memory store when localStorage throws SecurityError", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError: Access denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError: Access denied");
    });

    const handleSave = vi.fn();
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        onSaveTemplate={handleSave}
        defaultMode="save"
      />
    );

    const titleInput = screen.getByLabelText("Template Title");
    fireEvent.change(titleInput, { target: { value: "Memory Fallback Query" } });
    fireEvent.click(screen.getByText("💾 Save Template"));

    expect(handleSave).toHaveBeenCalledOnce();
    expect(screen.getByText("Memory Fallback Query")).toBeTruthy();
  });

  it("closes modal when Escape key is pressed", () => {
    const handleClose = vi.fn();

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={handleClose}
        onLoadTemplate={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(handleClose).toHaveBeenCalledOnce();
  });

  it("closes modal when header close button or backdrop is clicked", () => {
    const handleClose = vi.fn();

    const { container } = render(
      <QueryTemplateManager
        isOpen={true}
        onClose={handleClose}
        onLoadTemplate={vi.fn()}
      />
    );

    const closeBtn = screen.getByLabelText("Close template manager");
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledOnce();

    // Click backdrop
    const backdrop = container.firstChild as HTMLElement;
    fireEvent.click(backdrop);
    expect(handleClose).toHaveBeenCalledTimes(2);
  });

  it("uses custom initialTemplates when provided", () => {
    const customSeeds: QueryTemplate[] = [
      {
        id: "c_1",
        title: "Custom Seed Only",
        category: "Custom",
        sql: "SELECT 42;",
        createdAt: "2026-01-01T00:00:00.000Z",
        isDefault: true,
      },
    ];

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        initialTemplates={customSeeds}
      />
    );

    expect(screen.getByText("Custom Seed Only")).toBeTruthy();
    expect(screen.queryByText("Active Users Directory")).toBeNull();
  });

  it("handles saving and deleting when optional callbacks are omitted", () => {
    const customTemplate: QueryTemplate = {
      id: "opt_del",
      title: "No Callback Delete",
      category: "Test",
      sql: "SELECT 1;",
      createdAt: new Date().toISOString(),
      isDefault: false,
    };
    saveTemplates([customTemplate, ...SEED_TEMPLATES]);

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        defaultMode="save"
      />
    );

    // Save without onSaveTemplate prop
    const titleInput = screen.getByLabelText("Template Title");
    fireEvent.change(titleInput, { target: { value: "No Callback Save" } });
    fireEvent.click(screen.getByText("💾 Save Template"));
    expect(screen.getByText("No Callback Save")).toBeTruthy();

    // Delete without onDeleteTemplate prop
    const delBtn = screen.getByLabelText("Delete No Callback Delete");
    fireEvent.click(delBtn);
    expect(screen.queryByText("No Callback Delete")).toBeNull();
  });

  it("does not close modal when clicking inside dialog card", () => {
    const handleClose = vi.fn();
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={handleClose}
        onLoadTemplate={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog");
    fireEvent.click(dialog);
    expect(handleClose).not.toHaveBeenCalled();
  });

  it("switches view when defaultMode prop changes", () => {
    const { rerender } = render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        defaultMode="library"
      />
    );
    expect(screen.getByLabelText("Search templates")).toBeTruthy();

    rerender(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        defaultMode="save"
      />
    );
    expect(screen.getByLabelText("Template Title")).toBeTruthy();
  });

  it("handles corrupted JSON and empty stored array in loadTemplates gracefully", () => {
    // 1. Corrupted JSON
    window.localStorage.setItem("query_builder_templates", "NOT_JSON{{{");
    const res1 = loadTemplates();
    expect(res1.length).toBeGreaterThan(0);

    // 2. Empty stored array
    window.localStorage.setItem("query_builder_templates", "[]");
    resetTemplateStorage();
    const res2 = loadTemplates();
    expect(res2.length).toBeGreaterThan(0);
  });

  it("handles localStorage.removeItem throwing in resetTemplateStorage", () => {
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("Remove forbidden");
    });
    expect(() => resetTemplateStorage()).not.toThrow();
  });

  it("saves template with default General category and undefined description when left blank", () => {
    const handleSave = vi.fn();
    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
        onSaveTemplate={handleSave}
        defaultMode="save"
      />
    );

    fireEvent.change(screen.getByLabelText("Template Title"), { target: { value: "Minimal Query" } });
    fireEvent.click(screen.getByText("💾 Save Template"));

    expect(handleSave).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Minimal Query",
        category: "General",
        description: undefined,
      })
    );
  });

  it("renders templates without category under General category pill", () => {
    const noCatTemplate: QueryTemplate = {
      id: "no_cat_1",
      title: "No Category Query",
      sql: "SELECT 99;",
      createdAt: "2026-01-01T00:00:00.000Z",
      isDefault: false,
    };
    saveTemplates([noCatTemplate]);

    render(
      <QueryTemplateManager
        isOpen={true}
        onClose={vi.fn()}
        onLoadTemplate={vi.fn()}
      />
    );

    expect(screen.getAllByText("General").length).toBe(2);
    expect(screen.getByText("No Category Query")).toBeTruthy();

    // Click General pill
    const generalPill = screen.getByRole("button", { name: "General" });
    fireEvent.click(generalPill);
    expect(screen.getByText("No Category Query")).toBeTruthy();
  });
});
