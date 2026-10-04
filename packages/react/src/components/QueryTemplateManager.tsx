import React, { useState, useEffect, useMemo } from "react";
import type { QueryTemplate, QueryTemplateManagerProps } from "../types";

export const SEED_TEMPLATES: QueryTemplate[] = [
  {
    id: "tpl_default_users",
    title: "Active Users Directory",
    description: "Lists all registered active users sorted by email.",
    category: "Users",
    sql: 'SELECT "users"."id", "users"."email" FROM "users" ORDER BY "users"."id" ASC LIMIT 50;',
    spec: {
      primaryTable: "users",
      activeTables: ["users"],
      selectedColumns: {
        "users.id": { table: "users", name: "id" },
        "users.email": { table: "users", name: "email" },
      },
      orderedProjectionKeys: ["users.id", "users.email"],
      sorts: [{ id: "sort_1", column: "id", tablePrefix: "users", direction: "ASC" }],
      limit: 50,
    },
    createdAt: "2026-01-01T00:00:00.000Z",
    isDefault: true,
  },
  {
    id: "tpl_default_orders",
    title: "High-Value Orders Audit",
    description: "Orders exceeding threshold with total amounts.",
    category: "Sales",
    sql: 'SELECT "orders"."id", "orders"."user_id", "orders"."total" FROM "orders" WHERE "orders"."total" > 100 ORDER BY "orders"."total" DESC LIMIT 50;',
    spec: {
      primaryTable: "orders",
      activeTables: ["orders"],
      selectedColumns: {
        "orders.id": { table: "orders", name: "id" },
        "orders.user_id": { table: "orders", name: "user_id" },
        "orders.total": { table: "orders", name: "total" },
      },
      orderedProjectionKeys: ["orders.id", "orders.user_id", "orders.total"],
      filters: [{ id: "filter_1", column: "total", tablePrefix: "orders", operator: ">", value: "100" }],
      sorts: [{ id: "sort_1", column: "total", tablePrefix: "orders", direction: "DESC" }],
      limit: 50,
    },
    createdAt: "2026-01-01T00:00:00.000Z",
    isDefault: true,
  },
  {
    id: "tpl_default_joined",
    title: "User Order Aggregates",
    description: "Joins users with orders to aggregate customer lifetime value.",
    category: "Analytics",
    sql: 'SELECT "users"."email", COUNT("orders"."id") AS "order_count", SUM("orders"."total") AS "total_spend" FROM "users" LEFT JOIN "orders" ON "orders"."user_id" = "users"."id" GROUP BY "users"."email" LIMIT 50;',
    spec: {
      primaryTable: "users",
      activeTables: ["users", "orders"],
      joins: [{ id: "j1", type: "LEFT JOIN", left_table: "users", table: "orders", left_col: "id", right_col: "user_id" }],
      limit: 50,
    },
    createdAt: "2026-01-01T00:00:00.000Z",
    isDefault: true,
  },
];

const STORAGE_KEY = "query_builder_templates";
let memoryStorage: QueryTemplate[] | null = null;

export function loadTemplates(initialTemplates?: QueryTemplate[]): QueryTemplate[] {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    }
  } catch {
    // Fallback to in-memory storage below
  }
  if (memoryStorage !== null) return memoryStorage;
  const initial = initialTemplates && initialTemplates.length > 0 ? initialTemplates : SEED_TEMPLATES;
  saveTemplates(initial);
  return initial;
}

export function saveTemplates(templates: QueryTemplate[]): void {
  memoryStorage = templates;
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(templates));
    }
  } catch {
    // Ignore localStorage write error
  }
}

export function resetTemplateStorage(): void {
  memoryStorage = null;
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Ignore removal error
  }
}

export const QueryTemplateManager: React.FC<QueryTemplateManagerProps> = ({
  isOpen,
  onClose,
  currentSql = "",
  currentSpec,
  onLoadTemplate,
  onSaveTemplate,
  onDeleteTemplate,
  initialTemplates,
  defaultMode = "library",
  unstyled = false,
}) => {
  const [mode, setMode] = useState<"library" | "save">(defaultMode);
  const [templates, setTemplates] = useState<QueryTemplate[]>(() => loadTemplates(initialTemplates));
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [expandedSqlId, setExpandedSqlId] = useState<string | null>(null);

  // Save form fields
  const [saveTitle, setSaveTitle] = useState("");
  const [saveCategory, setSaveCategory] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    setMode(defaultMode);
  }, [defaultMode]);

  useEffect(() => {
    if (isOpen) {
      setTemplates(loadTemplates(initialTemplates));
      setValidationError(null);
    }
  }, [isOpen, initialTemplates]);

  // Keyboard navigation: Escape key closes modal
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, onClose]);

  // Unique categories for pills
  const categories = useMemo(() => {
    const set = new Set<string>();
    templates.forEach((t) => set.add(t.category || "General"));
    return ["All", ...Array.from(set)];
  }, [templates]);

  // Filtered templates list
  const filteredTemplates = useMemo(() => {
    return templates.filter((t) => {
      const term = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !term ||
        t.title.toLowerCase().includes(term) ||
        (t.description && t.description.toLowerCase().includes(term)) ||
        (t.category && t.category.toLowerCase().includes(term));
      const matchesCategory =
        selectedCategory === "All" || (t.category || "General") === selectedCategory;
      return matchesSearch && matchesCategory;
    });
  }, [templates, searchQuery, selectedCategory]);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!saveTitle.trim()) {
      setValidationError("Title is required.");
      return;
    }

    const newTemplate: QueryTemplate = {
      id: `tpl_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      title: saveTitle.trim(),
      category: saveCategory.trim() || "General",
      description: saveDescription.trim() || undefined,
      sql: currentSql || "",
      spec: currentSpec || {},
      createdAt: new Date().toISOString(),
      isDefault: false,
    };

    const updated = [newTemplate, ...templates];
    setTemplates(updated);
    saveTemplates(updated);
    onSaveTemplate?.(newTemplate);

    // Reset form and switch to library view
    setSaveTitle("");
    setSaveCategory("");
    setSaveDescription("");
    setValidationError(null);
    setMode("library");
  };

  const handleDelete = (id: string) => {
    const updated = templates.filter((t) => t.id !== id);
    setTemplates(updated);
    saveTemplates(updated);
    onDeleteTemplate?.(id);
  };

  return (
    <div
      data-qb="modal-backdrop"
      style={
        unstyled
          ? undefined
          : {
              position: "fixed",
              inset: 0,
              backgroundColor: "rgba(0, 0, 0, 0.75)",
              backdropFilter: "blur(4px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 9999,
              padding: "16px",
            }
      }
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="template-manager-title"
        data-qb="template-manager-modal"
        style={
          unstyled
            ? undefined
            : {
                width: "100%",
                maxWidth: "680px",
                maxHeight: "90vh",
                backgroundColor: "#0b1329",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                borderRadius: "12px",
                boxShadow: "0 20px 40px rgba(0, 0, 0, 0.6)",
                color: "#f8fafc",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
                fontFamily: "system-ui, -apple-system, sans-serif",
              }
        }
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "14px 20px",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            background: "rgba(15, 23, 42, 0.6)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <h3
              id="template-manager-title"
              style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: "#93c5fd" }}
            >
              Query Template Manager
            </h3>
            {/* View Mode Switcher */}
            <div
              style={{
                display: "flex",
                background: "rgba(30, 41, 59, 0.7)",
                borderRadius: "6px",
                padding: "2px",
                border: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <button
                type="button"
                onClick={() => setMode("library")}
                style={{
                  background: mode === "library" ? "#3b82f6" : "transparent",
                  color: mode === "library" ? "#ffffff" : "#94a3b8",
                  border: "none",
                  borderRadius: "4px",
                  padding: "4px 10px",
                  fontSize: "0.76rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                📚 Library ({templates.length})
              </button>
              <button
                type="button"
                onClick={() => setMode("save")}
                style={{
                  background: mode === "save" ? "#3b82f6" : "transparent",
                  color: mode === "save" ? "#ffffff" : "#94a3b8",
                  border: "none",
                  borderRadius: "4px",
                  padding: "4px 10px",
                  fontSize: "0.76rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                ➕ Save Current Query
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close template manager"
            style={{
              background: "transparent",
              border: "none",
              color: "#94a3b8",
              fontSize: "1.2rem",
              cursor: "pointer",
              padding: "4px 8px",
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "16px 20px", overflowY: "auto", flex: 1 }}>
          {/* Library Mode */}
          {mode === "library" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
              {/* Search & Category filter */}
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                <input
                  type="text"
                  placeholder="Search templates by title, description, or category..."
                  aria-label="Search templates"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    width: "100%",
                    background: "#1e293b",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    fontSize: "0.85rem",
                    boxSizing: "border-box",
                  }}
                />

                {/* Category Pills */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                  {categories.map((cat) => (
                    <button
                      key={cat}
                      type="button"
                      onClick={() => setSelectedCategory(cat)}
                      style={{
                        background:
                          selectedCategory === cat ? "rgba(59, 130, 246, 0.2)" : "rgba(30, 41, 59, 0.5)",
                        color: selectedCategory === cat ? "#60a5fa" : "#94a3b8",
                        border:
                          selectedCategory === cat
                            ? "1px solid rgba(59, 130, 246, 0.5)"
                            : "1px solid rgba(255, 255, 255, 0.08)",
                        borderRadius: "16px",
                        padding: "3px 10px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
              </div>

              {/* Template Cards List */}
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {filteredTemplates.length === 0 ? (
                  <div
                    style={{
                      textAlign: "center",
                      padding: "32px 16px",
                      color: "#64748b",
                      fontStyle: "italic",
                      fontSize: "0.85rem",
                    }}
                  >
                    No templates found matching your criteria.
                  </div>
                ) : (
                  filteredTemplates.map((t) => (
                    <div
                      key={t.id}
                      data-qb="template-card"
                      style={
                        unstyled
                          ? undefined
                          : {
                              background: "rgba(15, 23, 42, 0.6)",
                              border: "1px solid rgba(255, 255, 255, 0.08)",
                              borderRadius: "8px",
                              padding: "12px 14px",
                              display: "flex",
                              flexDirection: "column",
                              gap: "8px",
                            }
                      }
                    >
                      {/* Card Title & Badges */}
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "flex-start",
                          gap: "8px",
                        }}
                      >
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{ fontWeight: 600, fontSize: "0.9rem", color: "#f1f5f9" }}>
                              {t.title}
                            </span>
                            <span
                              style={{
                                background: "rgba(99, 102, 241, 0.15)",
                                color: "#818cf8",
                                border: "1px solid rgba(99, 102, 241, 0.3)",
                                borderRadius: "4px",
                                padding: "1px 6px",
                                fontSize: "0.7rem",
                                fontWeight: 600,
                              }}
                            >
                              {t.category || "General"}
                            </span>
                            {t.isDefault && (
                              <span
                                style={{
                                  background: "rgba(16, 185, 129, 0.15)",
                                  color: "#34d399",
                                  border: "1px solid rgba(16, 185, 129, 0.3)",
                                  borderRadius: "4px",
                                  padding: "1px 6px",
                                  fontSize: "0.7rem",
                                  fontWeight: 600,
                                }}
                              >
                                Built-in
                              </span>
                            )}
                          </div>
                          {t.description && (
                            <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginTop: "4px" }}>
                              {t.description}
                            </div>
                          )}
                        </div>

                        {/* Actions */}
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <button
                            type="button"
                            onClick={() => {
                              onLoadTemplate(t);
                              onClose();
                            }}
                            style={{
                              background: "#3b82f6",
                              color: "#ffffff",
                              border: "none",
                              borderRadius: "6px",
                              padding: "4px 10px",
                              fontSize: "0.76rem",
                              fontWeight: 600,
                              cursor: "pointer",
                            }}
                          >
                            ▶ Load Template
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedSqlId(expandedSqlId === t.id ? null : t.id)
                            }
                            aria-label={`Preview SQL for ${t.title}`}
                            style={{
                              background: "rgba(30, 41, 59, 0.8)",
                              color: "#94a3b8",
                              border: "1px solid rgba(255, 255, 255, 0.1)",
                              borderRadius: "6px",
                              padding: "4px 8px",
                              fontSize: "0.76rem",
                              cursor: "pointer",
                            }}
                          >
                            {expandedSqlId === t.id ? "Hide SQL" : "👁️ Preview SQL"}
                          </button>
                          {!t.isDefault && (
                            <button
                              type="button"
                              onClick={() => handleDelete(t.id)}
                              aria-label={`Delete ${t.title}`}
                              style={{
                                background: "rgba(239, 68, 68, 0.15)",
                                color: "#f87171",
                                border: "1px solid rgba(239, 68, 68, 0.3)",
                                borderRadius: "6px",
                                padding: "4px 8px",
                                fontSize: "0.76rem",
                                cursor: "pointer",
                              }}
                            >
                              🗑️ Delete
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Expanded SQL Preview */}
                      {expandedSqlId === t.id && (
                        <div
                          style={{
                            background: "#090d16",
                            border: "1px solid #1e293b",
                            borderRadius: "6px",
                            padding: "8px 10px",
                            marginTop: "4px",
                          }}
                        >
                          <textarea
                            readOnly
                            value={t.sql}
                            aria-label="SQL Code Preview"
                            rows={3}
                            style={{
                              width: "100%",
                              background: "transparent",
                              color: "#38bdf8",
                              fontFamily: "monospace",
                              fontSize: "0.76rem",
                              border: "none",
                              outline: "none",
                              resize: "vertical",
                              boxSizing: "border-box",
                            }}
                          />
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* Save Mode */}
          {mode === "save" && (
            <form onSubmit={handleSave} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
              {validationError && (
                <div
                  style={{
                    background: "rgba(239, 68, 68, 0.15)",
                    border: "1px solid rgba(239, 68, 68, 0.3)",
                    color: "#fca5a5",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    fontSize: "0.82rem",
                  }}
                >
                  ⚠️ {validationError}
                </div>
              )}

              {/* Title Field */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label
                  htmlFor="template-title-input"
                  style={{ fontSize: "0.82rem", fontWeight: 600, color: "#cbd5e1" }}
                >
                  Template Title <span style={{ color: "#f87171" }}>*</span>
                </label>
                <input
                  id="template-title-input"
                  type="text"
                  placeholder="e.g., Active Users Directory"
                  aria-label="Template Title"
                  value={saveTitle}
                  onChange={(e) => {
                    setSaveTitle(e.target.value);
                    if (validationError) setValidationError(null);
                  }}
                  style={{
                    background: "#1e293b",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    fontSize: "0.85rem",
                    boxSizing: "border-box",
                  }}
                />
              </div>

              {/* Category Field */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label
                  htmlFor="template-category-input"
                  style={{ fontSize: "0.82rem", fontWeight: 600, color: "#cbd5e1" }}
                >
                  Category
                </label>
                <input
                  id="template-category-input"
                  type="text"
                  placeholder="e.g., Analytics, Sales, Users"
                  aria-label="Template Category"
                  value={saveCategory}
                  onChange={(e) => setSaveCategory(e.target.value)}
                  style={{
                    background: "#1e293b",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    fontSize: "0.85rem",
                    boxSizing: "border-box",
                  }}
                />
              </div>

              {/* Description Field */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label
                  htmlFor="template-desc-input"
                  style={{ fontSize: "0.82rem", fontWeight: 600, color: "#cbd5e1" }}
                >
                  Description
                </label>
                <textarea
                  id="template-desc-input"
                  placeholder="Brief description of the query's business objective..."
                  aria-label="Template Description"
                  rows={2}
                  value={saveDescription}
                  onChange={(e) => setSaveDescription(e.target.value)}
                  style={{
                    background: "#1e293b",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    fontSize: "0.85rem",
                    boxSizing: "border-box",
                    resize: "vertical",
                  }}
                />
              </div>

              {/* SQL Code to Save */}
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "#cbd5e1" }}>
                  Query SQL
                </label>
                <textarea
                  readOnly
                  value={currentSql}
                  aria-label="Query SQL to be saved"
                  rows={4}
                  style={{
                    background: "#090d16",
                    color: "#38bdf8",
                    border: "1px solid #334155",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    fontSize: "0.8rem",
                    fontFamily: "monospace",
                    boxSizing: "border-box",
                    resize: "none",
                  }}
                />
              </div>

              {/* Submit Buttons */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "8px" }}>
                <button
                  type="button"
                  onClick={() => setMode("library")}
                  style={{
                    background: "transparent",
                    color: "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    borderRadius: "6px",
                    padding: "8px 16px",
                    fontSize: "0.85rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{
                    background: "#10b981",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    padding: "8px 20px",
                    fontSize: "0.85rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    boxShadow: "0 4px 12px rgba(16, 185, 129, 0.3)",
                  }}
                >
                  💾 Save Template
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
