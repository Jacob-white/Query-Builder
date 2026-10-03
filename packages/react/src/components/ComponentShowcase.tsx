import React, { useState, useMemo, useCallback } from "react";
import type {
  SchemaSnapshot,
  QueryResultData,
  SqlPreset,
  QueryTemplate,
} from "../types";
import { VisualQueryBuilder } from "./VisualQueryBuilder";
import { QueryChartPreview } from "./QueryChartPreview";
import { QueryTemplateManager, SEED_TEMPLATES } from "./QueryTemplateManager";
import { useQueryBuilder } from "../hooks/useQueryBuilder";
import { useQueryExecution } from "../hooks/useQueryExecution";
import { ThemeProvider } from "../theme/ThemeProvider";
import { darkTheme, lightTheme, mergeTheme, type QueryBuilderTheme } from "../theme/tokens";

export type ShowcaseTab = "studio" | "headless" | "charts" | "theming" | "templates";

export interface ComponentShowcaseProps {
  initialSchema?: SchemaSnapshot;
  initialTab?: ShowcaseTab;
  className?: string;
  style?: React.CSSProperties;
}

const DEFAULT_SHOWCASE_SCHEMA: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "name", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "email", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "role", data_type: "VARCHAR", is_nullable: true, is_primary: false },
        { name: "created_at", data_type: "TIMESTAMP", is_nullable: false, is_primary: false },
      ],
      has_user_id: false,
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "INTEGER", is_nullable: false, is_primary: false },
        { name: "product_id", data_type: "INTEGER", is_nullable: false, is_primary: false },
        { name: "amount", data_type: "DECIMAL", is_nullable: false, is_primary: false },
        { name: "status", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "created_at", data_type: "TIMESTAMP", is_nullable: false, is_primary: false },
      ],
      has_user_id: true,
    },
    products: {
      name: "products",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "category_id", data_type: "INTEGER", is_nullable: false, is_primary: false },
        { name: "title", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "price", data_type: "DECIMAL", is_nullable: false, is_primary: false },
        { name: "stock", data_type: "INTEGER", is_nullable: false, is_primary: false },
      ],
      has_user_id: false,
    },
    categories: {
      name: "categories",
      columns: [
        { name: "id", data_type: "INTEGER", is_nullable: false, is_primary: true },
        { name: "name", data_type: "VARCHAR", is_nullable: false, is_primary: false },
        { name: "slug", data_type: "VARCHAR", is_nullable: false, is_primary: false },
      ],
      has_user_id: false,
    },
  },
  foreign_keys: [
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
    { table: "orders", column: "product_id", foreign_table: "products", foreign_column: "id" },
    { table: "products", column: "category_id", foreign_table: "categories", foreign_column: "id" },
  ],
};

const SHOWCASE_PRESETS: SqlPreset[] = [
  {
    id: "active-users",
    title: "All Users",
    description: "List all active users",
    sql: "SELECT id, name, email FROM users LIMIT 10;",
  },
  {
    id: "high-value-orders",
    title: "High Value Orders",
    description: "Orders over $100",
    sql: "SELECT id, amount, status FROM orders WHERE amount > 100 LIMIT 25;",
  },
];

const SAMPLE_CHART_RESULTS: QueryResultData = {
  columns: ["category", "sales", "units"],
  rows: [
    { category: "Electronics", sales: 12500, units: 140 },
    { category: "Home & Kitchen", sales: 8400, units: 95 },
    { category: "Books & Media", sales: 4300, units: 210 },
    { category: "Apparel", sales: 9100, units: 180 },
    { category: "Sports & Outdoors", sales: 6200, units: 88 },
  ],
  count: 5,
  latency_ms: 24,
};

// Headless Demo Component
const HeadlessDemoUI: React.FC<{ schema: SchemaSnapshot }> = ({ schema }) => {
  const { state, actions, compiled, safety } = useQueryBuilder({
    schema,
    initialTable: "users",
    initialLimit: 10,
  });

  const mockExecute = useCallback(
    async (_sql: string): Promise<QueryResultData> => {
      const activeTable = schema.tables[state.primaryTable];
      const cols =
        state.orderedProjectionKeys.length > 0
          ? state.orderedProjectionKeys.map((k) => k.split(".")[1])
          : activeTable.columns.map((c) => c.name);

      const rows = [
        { id: 1, name: "Alice Smith", email: "alice@example.com", amount: 150, category: "Tech" },
        { id: 2, name: "Bob Jones", email: "bob@example.com", amount: 220, category: "Design" },
        { id: 3, name: "Carol Vance", email: "carol@example.com", amount: 310, category: "Sales" },
      ].slice(0, state.limit);

      return {
        columns: cols,
        rows,
        count: rows.length,
        latency_ms: 12,
      };
    },
    [schema, state.primaryTable, state.orderedProjectionKeys, state.limit],
  );

  const { results, isLoading, executeQuery } = useQueryExecution({
    onExecuteQuery: mockExecute,
  });

  const availableTables = Object.keys(schema.tables);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "12px",
        background: "rgba(15, 23, 42, 0.6)",
        padding: "16px",
        borderRadius: "8px",
        border: "1px solid rgba(255, 255, 255, 0.1)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h4 style={{ margin: 0, fontSize: "0.95rem", color: "#38bdf8" }}>
          Headless Query State & Controls
        </h4>
        <span
          style={{
            padding: "2px 8px",
            borderRadius: "4px",
            fontSize: "0.75rem",
            background: "rgba(16, 185, 129, 0.15)",
            color: "#34d399",
          }}
        >
          AST Valid (Read-Only)
        </span>
      </div>

      {/* Table Selector Chips */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
        <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Active Tables:</span>
        {availableTables.map((t) => {
          const isActive = state.activeTableNames.includes(t);
          return (
            <button
              key={t}
              type="button"
              onClick={() => {
                if (isActive) {
                  actions.removeTable(t);
                } else {
                  actions.addTable(t);
                }
              }}
              style={{
                background: isActive ? "#2563eb" : "rgba(30, 41, 59, 0.6)",
                color: isActive ? "#ffffff" : "#94a3b8",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                borderRadius: "4px",
                padding: "3px 8px",
                fontSize: "0.75rem",
                cursor: "pointer",
              }}
            >
              {isActive ? `✓ ${t}` : `+ ${t}`}
            </button>
          );
        })}
      </div>

      {/* Column check toggles for primary table */}
      {state.primaryTable && schema.tables[state.primaryTable] && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
          <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Columns ({state.primaryTable}):</span>
          {schema.tables[state.primaryTable].columns.map((c) => {
            const key = `${state.primaryTable}.${c.name}`;
            const isSelected = Boolean(state.selectedColumns[key]);
            return (
              <label
                key={c.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  fontSize: "0.75rem",
                  color: isSelected ? "#60a5fa" : "#cbd5e1",
                  background: isSelected ? "rgba(37, 99, 235, 0.15)" : "transparent",
                  padding: "2px 6px",
                  borderRadius: "4px",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => actions.toggleColumn(state.primaryTable, c.name)}
                />
                {c.name}
              </label>
            );
          })}
        </div>
      )}

      {/* Limit & Run */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <label style={{ fontSize: "0.8rem", color: "#94a3b8", display: "flex", alignItems: "center", gap: "6px" }}>
          Limit:
          <input
            type="number"
            value={state.limit}
            onChange={(e) => actions.setLimit(Number(e.target.value) || 10)}
            style={{
              width: "60px",
              background: "#1e293b",
              border: "1px solid #475569",
              borderRadius: "4px",
              color: "#fff",
              padding: "3px 6px",
              fontSize: "0.8rem",
            }}
          />
        </label>
        <button
          type="button"
          onClick={() => executeQuery(compiled.sql, compiled.spec)}
          disabled={isLoading}
          style={{
            background: "#10b981",
            color: "#fff",
            border: "none",
            borderRadius: "6px",
            padding: "5px 14px",
            fontSize: "0.8rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {isLoading ? "Running..." : "▶ Run Headless Query"}
        </button>
      </div>

      {/* SQL Compiled Preview */}
      <div
        style={{
          background: "#090d16",
          padding: "8px 12px",
          borderRadius: "6px",
          fontFamily: "monospace",
          fontSize: "0.78rem",
          color: "#38bdf8",
        }}
      >
        <code>{compiled.sql}</code>
      </div>

      {/* Results View */}
      {results && (
        <div style={{ marginTop: "6px" }}>
          <div style={{ fontSize: "0.78rem", color: "#94a3b8", marginBottom: "4px" }}>
            Query Results: {results.count} rows ({results.latency_ms}ms)
          </div>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.75rem",
              background: "#1e293b",
              borderRadius: "4px",
              overflow: "hidden",
            }}
          >
            <thead>
              <tr style={{ background: "#0f172a", color: "#94a3b8" }}>
                {results.columns.map((col) => (
                  <th key={col} style={{ padding: "6px 8px", textAlign: "left" }}>
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.rows.map((row, idx) => (
                <tr key={idx} style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
                  {results.columns.map((col) => (
                    <td key={col} style={{ padding: "6px 8px", color: "#f8fafc" }}>
                      {String(row[col] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export const ComponentShowcase: React.FC<ComponentShowcaseProps> = ({
  initialSchema = DEFAULT_SHOWCASE_SCHEMA,
  initialTab = "studio",
  className,
  style,
}) => {
  const [activeTab, setActiveTab] = useState<ShowcaseTab>(initialTab);
  const [copiedCode, setCopiedCode] = useState<boolean>(false);

  // Theming playground state
  const [themeMode, setThemeMode] = useState<"dark" | "light">("dark");
  const [primaryColor, setPrimaryColor] = useState<string>("#3b82f6");

  // Template playground state
  const [isTemplateManagerOpen, setIsTemplateManagerOpen] = useState<boolean>(false);
  const [selectedTemplate, setSelectedTemplate] = useState<QueryTemplate | null>(null);

  // Code snippets per tab
  const codeSnippets: Record<ShowcaseTab, string> = {
    studio: `import React from "react";
import { VisualQueryBuilder } from "@jacob-white/query-builder-react";

export function QueryStudio() {
  return (
    <VisualQueryBuilder
      schema={schemaSnapshot}
      presets={presets}
      dialect="postgres"
      onExecuteQuery={async (sql, spec) => {
        const response = await fetch("/api/v1/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sql, spec }),
        });
        return await response.json();
      }}
    />
  );
}`,
    headless: `import React from "react";
import { useQueryBuilder, useQueryExecution } from "@jacob-white/query-builder-react";

export function CustomQueryUI({ schema }) {
  const { state, actions, compiled, safety } = useQueryBuilder({
    schema,
    initialTable: "users",
    initialLimit: 25,
  });

  const { results, isLoading, executeQuery } = useQueryExecution({
    onExecuteQuery: async (sql) => {
      return await api.runQuery(sql);
    },
  });

  return (
    <div>
      <h3>Primary Table: {state.primaryTable}</h3>
      <button onClick={() => actions.addTable("orders")}>Add Orders</button>
      <button onClick={() => executeQuery(compiled.sql)}>Execute</button>
      <pre>{compiled.sql}</pre>
    </div>
  );
}`,
    charts: `import React from "react";
import { QueryChartPreview } from "@jacob-white/query-builder-react";

export function DataInsights({ queryResults }) {
  return (
    <QueryChartPreview
      results={queryResults}
      defaultChartType="bar"
      defaultCategoryCol="category"
      defaultMetricCol="sales"
      defaultAggregation="SUM"
    />
  );
}`,
    theming: `import React from "react";
import { ThemeProvider, mergeTheme, darkTheme, VisualQueryBuilder } from "@jacob-white/query-builder-react";

const brandTheme = mergeTheme(darkTheme, {
  colors: {
    primary: "${primaryColor}",
    primaryHover: "#2563eb",
  },
});

export function BrandedStudio() {
  return (
    <ThemeProvider theme={brandTheme}>
      <VisualQueryBuilder schema={schema} />
    </ThemeProvider>
  );
}`,
    templates: `import React, { useState } from "react";
import { QueryTemplateManager } from "@jacob-white/query-builder-react";

export function TemplateLibrary() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button onClick={() => setIsOpen(true)}>Manage Templates</button>
      <QueryTemplateManager
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        onLoadTemplate={(template) => console.log("Loaded:", template)}
      />
    </>
  );
}`,
  };

  const handleCopyCode = async () => {
    const textToCopy = codeSnippets[activeTab];
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(textToCopy);
    }
    setCopiedCode(true);
    setTimeout(() => {
      setCopiedCode(false);
    }, 2000);
  };

  const customThemingObj: QueryBuilderTheme = useMemo(() => {
    const base = themeMode === "light" ? lightTheme : darkTheme;
    return mergeTheme(base, {
      colors: {
        primary: primaryColor,
        borderFocus: primaryColor,
      },
    });
  }, [themeMode, primaryColor]);

  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "16px",
        background: "#0b0f19",
        color: "#f8fafc",
        borderRadius: "14px",
        border: "1px solid rgba(255, 255, 255, 0.12)",
        padding: "20px",
        fontFamily: "system-ui, -apple-system, sans-serif",
        ...style,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          paddingBottom: "14px",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1.4rem" }}>🪐</span>
            <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700 }}>
              Query-Builder Component Catalog & Documentation
            </h2>
          </div>
          <p style={{ margin: "4px 0 0 0", fontSize: "0.82rem", color: "#94a3b8" }}>
            Interactive showcase of full studio, headless hooks, charting, theming, and template systems.
          </p>
        </div>

        {/* Tab Navigation */}
        <div
          style={{
            display: "flex",
            background: "rgba(30, 41, 59, 0.7)",
            borderRadius: "8px",
            padding: "3px",
            border: "1px solid rgba(255, 255, 255, 0.08)",
          }}
        >
          {(
            [
              ["studio", "Full Studio"],
              ["headless", "Headless Hooks"],
              ["charts", "Visual Charts"],
              ["theming", "Theming Playground"],
              ["templates", "Template Library"],
            ] as const
          ).map(([key, label]) => {
            const isTabActive = activeTab === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveTab(key)}
                style={{
                  background: isTabActive ? "#3b82f6" : "transparent",
                  color: isTabActive ? "#fff" : "#94a3b8",
                  border: "none",
                  borderRadius: "6px",
                  padding: "6px 12px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Content Pane */}
      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        {/* Tab 1: Studio */}
        {activeTab === "studio" && (
          <div>
            <VisualQueryBuilder
              schema={initialSchema}
              presets={SHOWCASE_PRESETS}
              onExecuteQuery={async () => SAMPLE_CHART_RESULTS}
            />
          </div>
        )}

        {/* Tab 2: Headless Hooks */}
        {activeTab === "headless" && (
          <div>
            <HeadlessDemoUI schema={initialSchema} />
          </div>
        )}

        {/* Tab 3: Visual Charts */}
        {activeTab === "charts" && (
          <div
            style={{
              background: "#0f172a",
              padding: "16px",
              borderRadius: "10px",
              border: "1px solid rgba(255, 255, 255, 0.1)",
            }}
          >
            <QueryChartPreview
              results={SAMPLE_CHART_RESULTS}
              defaultChartType="bar"
              defaultCategoryCol="category"
              defaultMetricCol="sales"
            />
          </div>
        )}

        {/* Tab 4: Theming Playground */}
        {activeTab === "theming" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            {/* Theming Controls Bar */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "16px",
                background: "rgba(30, 41, 59, 0.6)",
                padding: "10px 16px",
                borderRadius: "8px",
                border: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "0.82rem", color: "#94a3b8" }}>Mode:</span>
                <button
                  type="button"
                  onClick={() => setThemeMode("dark")}
                  style={{
                    background: themeMode === "dark" ? "#3b82f6" : "transparent",
                    color: themeMode === "dark" ? "#fff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.15)",
                    borderRadius: "4px",
                    padding: "4px 8px",
                    fontSize: "0.78rem",
                    cursor: "pointer",
                  }}
                >
                  🌙 Dark Mode
                </button>
                <button
                  type="button"
                  onClick={() => setThemeMode("light")}
                  style={{
                    background: themeMode === "light" ? "#3b82f6" : "transparent",
                    color: themeMode === "light" ? "#fff" : "#94a3b8",
                    border: "1px solid rgba(255, 255, 255, 0.15)",
                    borderRadius: "4px",
                    padding: "4px 8px",
                    fontSize: "0.78rem",
                    cursor: "pointer",
                  }}
                >
                  ☀️ Light Mode
                </button>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "0.82rem", color: "#94a3b8" }}>Primary Color:</span>
                {[
                  { name: "Blue", hex: "#3b82f6" },
                  { name: "Emerald", hex: "#10b981" },
                  { name: "Violet", hex: "#8b5cf6" },
                  { name: "Amber", hex: "#f59e0b" },
                ].map((c) => (
                  <button
                    key={c.hex}
                    type="button"
                    onClick={() => setPrimaryColor(c.hex)}
                    style={{
                      background: c.hex,
                      border: primaryColor === c.hex ? "2px solid #ffffff" : "none",
                      width: "22px",
                      height: "22px",
                      borderRadius: "50%",
                      cursor: "pointer",
                    }}
                    title={c.name}
                  />
                ))}
              </div>
            </div>

            {/* Live Theme Preview */}
            <ThemeProvider theme={customThemingObj}>
              <VisualQueryBuilder
                schema={initialSchema}
                readOnly
              />
            </ThemeProvider>
          </div>
        )}

        {/* Tab 5: Template Library */}
        {activeTab === "templates" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "0.88rem", color: "#cbd5e1" }}>
                Pre-configured query templates available for self-service analysts:
              </span>
              <button
                type="button"
                onClick={() => setIsTemplateManagerOpen(true)}
                style={{
                  background: "#6366f1",
                  color: "#fff",
                  border: "none",
                  borderRadius: "6px",
                  padding: "6px 14px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                📚 Open Template Manager
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                gap: "12px",
              }}
            >
              {SEED_TEMPLATES.map((tpl) => (
                <div
                  key={tpl.id}
                  onClick={() => setSelectedTemplate(tpl)}
                  style={{
                    background: "rgba(30, 41, 59, 0.6)",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                    borderRadius: "8px",
                    padding: "12px",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 600, fontSize: "0.85rem", color: "#f8fafc" }}>
                      {tpl.title}
                    </span>
                    <span
                      style={{
                        fontSize: "0.7rem",
                        padding: "1px 6px",
                        background: "rgba(99, 102, 241, 0.2)",
                        color: "#a5b4fc",
                        borderRadius: "4px",
                      }}
                    >
                      {tpl.category}
                    </span>
                  </div>
                  <p style={{ margin: 0, fontSize: "0.75rem", color: "#94a3b8" }}>
                    {tpl.description}
                  </p>
                  <code
                    style={{
                      marginTop: "4px",
                      background: "#090d16",
                      padding: "6px",
                      borderRadius: "4px",
                      fontSize: "0.7rem",
                      color: "#38bdf8",
                    }}
                  >
                    {tpl.sql}
                  </code>
                </div>
              ))}
            </div>

            <QueryTemplateManager
              isOpen={isTemplateManagerOpen}
              onClose={() => setIsTemplateManagerOpen(false)}
              onLoadTemplate={(tpl) => setSelectedTemplate(tpl)}
            />
            {selectedTemplate && (
              <div
                style={{
                  padding: "8px 12px",
                  background: "rgba(16, 185, 129, 0.15)",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                  borderRadius: "6px",
                  fontSize: "0.8rem",
                  color: "#34d399",
                }}
              >
                Selected Template: <strong>{selectedTemplate.title}</strong>
              </div>
            )}
          </div>
        )}

        {/* Live Code Snippet Display with Copy Button */}
        <div
          style={{
            background: "#090d16",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "8px",
            padding: "14px",
            marginTop: "8px",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "8px",
            }}
          >
            <span style={{ fontSize: "0.8rem", color: "#94a3b8", fontWeight: 600 }}>
              Live Code Snippet ({activeTab})
            </span>
            <button
              type="button"
              onClick={handleCopyCode}
              style={{
                background: copiedCode ? "rgba(16, 185, 129, 0.2)" : "rgba(255, 255, 255, 0.1)",
                color: copiedCode ? "#34d399" : "#cbd5e1",
                border: "none",
                borderRadius: "4px",
                padding: "4px 10px",
                fontSize: "0.75rem",
                cursor: "pointer",
              }}
            >
              {copiedCode ? "✅ Copied!" : "📋 Copy Code"}
            </button>
          </div>
          <pre
            style={{
              margin: 0,
              padding: "12px",
              background: "#030712",
              borderRadius: "6px",
              fontFamily: "ui-monospace, monospace",
              fontSize: "0.78rem",
              color: "#93c5fd",
              overflowX: "auto",
              lineHeight: 1.5,
            }}
          >
            <code>{codeSnippets[activeTab]}</code>
          </pre>
        </div>
      </div>
    </div>
  );
};
