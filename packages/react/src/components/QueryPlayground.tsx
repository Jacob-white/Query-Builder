import React, { useState, useEffect, useMemo } from "react";
import type {
  DatabaseSchemaDefinition,
  QueryPlaygroundProps,
  QuerySpec,
  SqlDialect,
  SchemaSnapshot,
  TableMeta,
} from "../types";
import { useQueryState } from "../hooks/useQueryState";
import { useSqlCompiler } from "../hooks/useSqlCompiler";
import { normalizeSchema } from "../utils/schemaUtils";

export const QueryPlayground: React.FC<QueryPlaygroundProps> = ({
  schema,
  initialSpec,
  initialTable,
  dialect: defaultDialect = "postgres",
  unstyled = false,
  className,
  style,
  onSpecChange,
  onSqlChange,
  readOnly = false,
}) => {
  const normalizedSchema: SchemaSnapshot | null = useMemo(
    () => normalizeSchema(schema),
    [schema],
  );

  const tableNames = useMemo(() => {
    return normalizedSchema?.tables ? Object.keys(normalizedSchema.tables) : [];
  }, [normalizedSchema]);

  const fallbackInitialSpec = useMemo<Partial<QuerySpec>>(() => {
    if (initialSpec) return initialSpec as Partial<QuerySpec>;
    const firstTable = initialTable || tableNames[0] || "users";
    return {
      table: firstTable,
      columns: [`${firstTable}.id`],
      joins: [],
      filters: [],
      order_by: [],
      distinct: false,
      limit: 50,
    };
  }, [initialSpec, initialTable, tableNames]);

  const { state, actions, spec } = useQueryState(fallbackInitialSpec);
  const [activeDialect, setActiveDialect] = useState<SqlDialect>(defaultDialect);

  const { sql, safety, countSql } = useSqlCompiler(spec, {
    dialect: activeDialect,
    schema: normalizedSchema,
  });

  const [activeTab, setActiveTab] = useState<"builder" | "ast" | "codegen">("builder");
  const [builderSubTab, setBuilderSubTab] = useState<"visual" | "json">("visual");
  const [codegenTarget, setCodegenTarget] = useState<"sdk" | "sql" | "ast">("sdk");
  const [jsonSpecText, setJsonSpecText] = useState<string>(() =>
    JSON.stringify(spec, null, 2),
  );
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [copiedTarget, setCopiedTarget] = useState<string | null>(null);

  // Sync external callbacks
  useEffect(() => {
    onSpecChange?.(spec);
  }, [spec, onSpecChange]);

  useEffect(() => {
    onSqlChange?.(sql);
  }, [sql, onSqlChange]);

  // Sync JSON text when visual builder updates
  useEffect(() => {
    if (builderSubTab === "visual") {
      setJsonSpecText(JSON.stringify(spec, null, 2));
      setJsonError(null);
    }
  }, [spec, builderSubTab]);

  const handleJsonChange = (text: string) => {
    setJsonSpecText(text);
    try {
      const parsed = JSON.parse(text);
      setJsonError(null);
      actions.loadSpec(parsed);
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCopy = async (text: string, targetKey: string) => {
    if (typeof navigator !== "undefined" && navigator?.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        setCopiedTarget(targetKey);
        setTimeout(() => {
          setCopiedTarget(null);
        }, 2000);
      } catch {
        /* ignore */
      }
    }
  };

  // Generate TypeScript SDK snippet
  const generateSdkSnippet = useMemo(() => {
    const tbl = spec.table || "table";
    const cols = spec.columns.map((c) =>
      typeof c === "string" ? c : c.alias ? `${c.column} AS ${c.alias}` : c.column,
    );
    const colsStr = cols.length > 0 ? JSON.stringify(cols) : "[]";

    let code = `import { createQuery } from "@jacob-white/query-builder";\n\n`;
    code += `const query = createQuery()\n  .from("${tbl}")\n  .select(${colsStr})`;

    if (spec.joins && spec.joins.length > 0) {
      for (const j of spec.joins) {
        code += `\n  .join("${j.table}", "${j.left_col}", "=", "${j.right_col}")`;
      }
    }

    if (spec.filters && spec.filters.length > 0) {
      for (const f of spec.filters) {
        code += `\n  .where("${f.column}", "${f.op}", ${JSON.stringify(f.value)})`;
      }
    }

    if (spec.order_by && spec.order_by.length > 0) {
      for (const s of spec.order_by) {
        code += `\n  .orderBy("${s.column}", "${s.direction}")`;
      }
    }

    if (spec.distinct) {
      code += `\n  .distinct()`;
    }

    if (spec.limit) {
      code += `\n  .limit(${spec.limit})`;
    }

    code += `;\n\nconst result = await query.execute();`;
    return code;
  }, [spec]);

  const activeTableMeta: TableMeta | undefined = useMemo(() => {
    return normalizedSchema?.tables?.[state.primaryTable];
  }, [normalizedSchema, state.primaryTable]);

  return (
    <div
      data-qb="playground-root"
      data-qb-unstyled={unstyled ? "true" : undefined}
      className={className}
      style={
        unstyled
          ? style
          : {
              display: "flex",
              flexDirection: "column",
              gap: "16px",
              background: "#0f172a",
              color: "#f8fafc",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              borderRadius: "12px",
              padding: "16px",
              fontFamily: "system-ui, -apple-system, sans-serif",
              ...style,
            }
      }
    >
      {/* Playground Header */}
      <div
        data-qb="playground-header"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "12px",
                paddingBottom: "12px",
                borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
              }
        }
      >
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={unstyled ? undefined : { fontSize: "1.2rem" }}>⚡</span>
          <span style={unstyled ? undefined : { fontWeight: 700, fontSize: "1rem" }}>
            Query-Builder Playground
          </span>
          <span
            data-qb="safety-badge"
            data-qb-safety={safety.valid ? "valid" : "invalid"}
            style={
              unstyled
                ? undefined
                : {
                    background: safety.valid
                      ? "rgba(16, 185, 129, 0.15)"
                      : "rgba(239, 68, 68, 0.15)",
                    color: safety.valid ? "#34d399" : "#f87171",
                    border: `1px solid ${
                      safety.valid ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"
                    }`,
                    padding: "2px 8px",
                    borderRadius: "12px",
                    fontSize: "0.72rem",
                    fontWeight: 600,
                  }
            }
          >
            {safety.valid ? "AST Safe" : "AST Risk"}
          </span>
        </div>

        {/* Mode Tabs */}
        <div
          data-qb="playground-tabs"
          role="tablist"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  background: "#1e293b",
                  borderRadius: "8px",
                  padding: "2px",
                  border: "1px solid #334155",
                }
          }
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "builder"}
            data-qb="playground-tab-builder"
            onClick={() => setActiveTab("builder")}
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "builder" ? "#3b82f6" : "transparent",
                    color: activeTab === "builder" ? "#ffffff" : "#94a3b8",
                    border: "none",
                    borderRadius: "6px",
                    padding: "6px 14px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            Query Editor
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "ast"}
            data-qb="playground-tab-ast"
            onClick={() => setActiveTab("ast")}
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "ast" ? "#3b82f6" : "transparent",
                    color: activeTab === "ast" ? "#ffffff" : "#94a3b8",
                    border: "none",
                    borderRadius: "6px",
                    padding: "6px 14px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            AST Visualizer
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "codegen"}
            data-qb="playground-tab-codegen"
            onClick={() => setActiveTab("codegen")}
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "codegen" ? "#3b82f6" : "transparent",
                    color: activeTab === "codegen" ? "#ffffff" : "#94a3b8",
                    border: "none",
                    borderRadius: "6px",
                    padding: "6px 14px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }
            }
          >
            Code Generation
          </button>
        </div>
      </div>

      {/* Tab 1: Query Editor (Builder) */}
      {activeTab === "builder" && (
        <div
          data-qb="playground-spec-editor"
          style={unstyled ? undefined : { display: "flex", flexDirection: "column", gap: "12px" }}
        >
          {/* Subtabs for Visual vs JSON */}
          <div
            style={
              unstyled
                ? undefined
                : { display: "flex", justifyContent: "space-between", alignItems: "center" }
            }
          >
            <div style={unstyled ? undefined : { display: "flex", gap: "6px" }}>
              <button
                type="button"
                onClick={() => setBuilderSubTab("visual")}
                data-qb="builder-subtab-visual"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: builderSubTab === "visual" ? "#334155" : "transparent",
                        color: builderSubTab === "visual" ? "#38bdf8" : "#94a3b8",
                        border: "1px solid #475569",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        fontSize: "0.75rem",
                        cursor: "pointer",
                        fontWeight: 600,
                      }
                }
              >
                Visual Controls
              </button>
              <button
                type="button"
                onClick={() => setBuilderSubTab("json")}
                data-qb="builder-subtab-json"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: builderSubTab === "json" ? "#334155" : "transparent",
                        color: builderSubTab === "json" ? "#38bdf8" : "#94a3b8",
                        border: "1px solid #475569",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        fontSize: "0.75rem",
                        cursor: "pointer",
                        fontWeight: 600,
                      }
                }
              >
                Live JSON Spec
              </button>
            </div>

            <span style={unstyled ? undefined : { fontSize: "0.75rem", color: "#64748b" }}>
              Table: <strong>{state.primaryTable || "None"}</strong> | Columns:{" "}
              <strong>{Object.keys(state.selectedColumns).length}</strong>
            </span>
          </div>

          {builderSubTab === "visual" ? (
            <div
              data-qb="playground-visual-controls"
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      flexDirection: "column",
                      gap: "10px",
                      background: "rgba(15, 23, 42, 0.4)",
                      padding: "12px",
                      borderRadius: "8px",
                      border: "1px solid rgba(255, 255, 255, 0.05)",
                    }
              }
            >
              {/* Primary table selection */}
              <div
                style={
                  unstyled
                    ? undefined
                    : { display: "flex", alignItems: "center", gap: "10px" }
                }
              >
                <label
                  style={
                    unstyled
                      ? undefined
                      : { fontSize: "0.8rem", color: "#94a3b8", fontWeight: 600 }
                  }
                >
                  Primary Table:
                </label>
                {tableNames.length > 0 ? (
                  <select
                    aria-label="Select Primary Table"
                    data-qb="playground-select-table"
                    value={state.primaryTable}
                    onChange={(e) => actions.setPrimaryTable(e.target.value)}
                    disabled={readOnly}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "#1e293b",
                            color: "#f8fafc",
                            border: "1px solid #475569",
                            borderRadius: "6px",
                            padding: "4px 10px",
                            fontSize: "0.8rem",
                          }
                    }
                  >
                    {tableNames.map((tbl) => (
                      <option key={tbl} value={tbl}>
                        {tbl}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    aria-label="Input Primary Table"
                    data-qb="playground-input-table"
                    value={state.primaryTable}
                    onChange={(e) => actions.setPrimaryTable(e.target.value)}
                    disabled={readOnly}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "#1e293b",
                            color: "#f8fafc",
                            border: "1px solid #475569",
                            borderRadius: "6px",
                            padding: "4px 8px",
                            fontSize: "0.8rem",
                            width: "160px",
                          }
                    }
                  />
                )}

                <label
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "0.8rem",
                          color: "#cbd5e1",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          cursor: "pointer",
                        }
                  }
                >
                  <input
                    type="checkbox"
                    data-qb="playground-checkbox-distinct"
                    checked={state.isDistinct}
                    onChange={(e) => actions.setDistinct(e.target.checked)}
                    disabled={readOnly}
                  />
                  DISTINCT
                </label>

                <div
                  style={
                    unstyled
                      ? undefined
                      : { display: "flex", alignItems: "center", gap: "6px" }
                  }
                >
                  <span style={unstyled ? undefined : { fontSize: "0.8rem", color: "#94a3b8" }}>
                    Limit:
                  </span>
                  <input
                    type="number"
                    aria-label="Limit rows"
                    data-qb="playground-input-limit"
                    value={state.limit}
                    onChange={(e) => actions.setLimit(Number(e.target.value))}
                    disabled={readOnly}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "#1e293b",
                            color: "#f8fafc",
                            border: "1px solid #475569",
                            borderRadius: "4px",
                            padding: "2px 6px",
                            fontSize: "0.8rem",
                            width: "70px",
                          }
                    }
                  />
                </div>
              </div>

              {/* Columns Quick Toggle */}
              {activeTableMeta && (
                <div
                  style={
                    unstyled
                      ? undefined
                      : {
                          display: "flex",
                          flexDirection: "column",
                          gap: "6px",
                          marginTop: "8px",
                        }
                  }
                >
                  <span
                    style={
                      unstyled
                        ? undefined
                        : { fontSize: "0.75rem", color: "#64748b", fontWeight: 600 }
                    }
                  >
                    Columns ({activeTableMeta.columns.length}):
                  </span>
                  <div
                    style={
                      unstyled
                        ? undefined
                        : { display: "flex", flexWrap: "wrap", gap: "6px" }
                    }
                  >
                    {activeTableMeta.columns.map((col) => {
                      const key = `${state.primaryTable}.${col.name}`;
                      const isSelected = Boolean(state.selectedColumns[key]);
                      return (
                        <button
                          key={col.name}
                          type="button"
                          onClick={() => actions.toggleColumn(state.primaryTable, col.name)}
                          disabled={readOnly}
                          data-qb="playground-col-toggle"
                          data-qb-selected={isSelected ? "true" : "false"}
                          style={
                            unstyled
                              ? undefined
                              : {
                                  background: isSelected
                                    ? "rgba(59, 130, 246, 0.3)"
                                    : "rgba(30, 41, 59, 0.6)",
                                  color: isSelected ? "#93c5fd" : "#94a3b8",
                                  border: `1px solid ${
                                    isSelected ? "#3b82f6" : "rgba(255, 255, 255, 0.1)"
                                  }`,
                                  borderRadius: "4px",
                                  padding: "2px 8px",
                                  fontSize: "0.75rem",
                                  cursor: "pointer",
                                }
                          }
                        >
                          {isSelected ? "✓ " : "+ "}
                          {col.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div
              style={
                unstyled
                  ? undefined
                  : { display: "flex", flexDirection: "column", gap: "8px" }
              }
            >
              <textarea
                aria-label="JSON Query Spec Editor"
                data-qb="playground-json-textarea"
                value={jsonSpecText}
                onChange={(e) => handleJsonChange(e.target.value)}
                disabled={readOnly}
                rows={14}
                style={
                  unstyled
                    ? undefined
                    : {
                        width: "100%",
                        background: "#090d16",
                        color: "#38bdf8",
                        fontFamily: "monospace",
                        fontSize: "0.8rem",
                        border: jsonError ? "1px solid #ef4444" : "1px solid #334155",
                        borderRadius: "8px",
                        padding: "10px",
                        lineHeight: 1.4,
                        boxSizing: "border-box",
                        resize: "vertical",
                      }
                }
              />
              {jsonError && (
                <div
                  role="alert"
                  data-qb="playground-json-error"
                  style={
                    unstyled
                      ? undefined
                      : {
                          color: "#ef4444",
                          fontSize: "0.75rem",
                          background: "rgba(239, 68, 68, 0.1)",
                          padding: "6px 10px",
                          borderRadius: "4px",
                        }
                  }
                >
                  Syntax Error: {jsonError}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: AST Visualizer */}
      {activeTab === "ast" && (
        <div
          data-qb="playground-ast-visualizer"
          style={
            unstyled
              ? undefined
              : {
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                  gap: "12px",
                }
          }
        >
          {/* FROM Clause */}
          <div
            data-qb="ast-clause-from"
            style={
              unstyled
                ? undefined
                : {
                    background: "#1e293b",
                    padding: "12px",
                    borderRadius: "8px",
                    border: "1px solid #334155",
                  }
            }
          >
            <div
              style={
                unstyled
                  ? undefined
                  : { fontWeight: 700, fontSize: "0.82rem", color: "#38bdf8", marginBottom: "6px" }
              }
            >
              FROM (Data Source)
            </div>
            <div style={unstyled ? undefined : { fontSize: "0.85rem", color: "#f8fafc" }}>
              Primary Table: <strong>{spec.table || "None"}</strong>
            </div>
          </div>

          {/* SELECT Clause */}
          <div
            data-qb="ast-clause-select"
            style={
              unstyled
                ? undefined
                : {
                    background: "#1e293b",
                    padding: "12px",
                    borderRadius: "8px",
                    border: "1px solid #334155",
                  }
            }
          >
            <div
              style={
                unstyled
                  ? undefined
                  : { fontWeight: 700, fontSize: "0.82rem", color: "#38bdf8", marginBottom: "6px" }
              }
            >
              SELECT (Projections: {spec.columns.length})
            </div>
            <div
              style={
                unstyled
                  ? undefined
                  : { display: "flex", flexWrap: "wrap", gap: "4px", fontSize: "0.78rem" }
              }
            >
              {spec.columns.length > 0 ? (
                spec.columns.map((c, i) => (
                  <span
                    key={i}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "rgba(59, 130, 246, 0.2)",
                            color: "#93c5fd",
                            padding: "2px 6px",
                            borderRadius: "4px",
                          }
                    }
                  >
                    {typeof c === "string" ? c : `${c.column}${c.agg ? ` (${c.agg})` : ""}`}
                  </span>
                ))
              ) : (
                <span style={unstyled ? undefined : { color: "#64748b", fontStyle: "italic" }}>
                  * (all columns)
                </span>
              )}
            </div>
          </div>

          {/* JOIN Clause */}
          <div
            data-qb="ast-clause-joins"
            style={
              unstyled
                ? undefined
                : {
                    background: "#1e293b",
                    padding: "12px",
                    borderRadius: "8px",
                    border: "1px solid #334155",
                  }
            }
          >
            <div
              style={
                unstyled
                  ? undefined
                  : { fontWeight: 700, fontSize: "0.82rem", color: "#38bdf8", marginBottom: "6px" }
              }
            >
              JOIN (Relational: {spec.joins.length})
            </div>
            <div style={unstyled ? undefined : { fontSize: "0.78rem" }}>
              {spec.joins.length > 0 ? (
                spec.joins.map((j, i) => (
                  <div key={i} style={unstyled ? undefined : { marginBottom: "4px" }}>
                    <span style={unstyled ? undefined : { color: "#f59e0b", fontWeight: 600 }}>
                      {j.type}{" "}
                    </span>
                    <span>{j.table}</span>
                  </div>
                ))
              ) : (
                <span style={unstyled ? undefined : { color: "#64748b", fontStyle: "italic" }}>
                  No joins configured
                </span>
              )}
            </div>
          </div>

          {/* WHERE Clause */}
          <div
            data-qb="ast-clause-where"
            style={
              unstyled
                ? undefined
                : {
                    background: "#1e293b",
                    padding: "12px",
                    borderRadius: "8px",
                    border: "1px solid #334155",
                  }
            }
          >
            <div
              style={
                unstyled
                  ? undefined
                  : { fontWeight: 700, fontSize: "0.82rem", color: "#38bdf8", marginBottom: "6px" }
              }
            >
              WHERE (Filters: {spec.filters.length})
            </div>
            <div style={unstyled ? undefined : { fontSize: "0.78rem" }}>
              {spec.filters.length > 0 ? (
                spec.filters.map((f, i) => (
                  <div key={i} style={unstyled ? undefined : { marginBottom: "4px" }}>
                    <span>{f.column}</span>{" "}
                    <span style={unstyled ? undefined : { color: "#ec4899", fontWeight: 600 }}>
                      {f.op}
                    </span>{" "}
                    <span style={unstyled ? undefined : { color: "#a7f3d0" }}>
                      {String(f.value)}
                    </span>
                  </div>
                ))
              ) : (
                <span style={unstyled ? undefined : { color: "#64748b", fontStyle: "italic" }}>
                  No filters applied
                </span>
              )}
            </div>
          </div>

          {/* ORDER BY Clause */}
          <div
            data-qb="ast-clause-orderby"
            style={
              unstyled
                ? undefined
                : {
                    background: "#1e293b",
                    padding: "12px",
                    borderRadius: "8px",
                    border: "1px solid #334155",
                  }
            }
          >
            <div
              style={
                unstyled
                  ? undefined
                  : { fontWeight: 700, fontSize: "0.82rem", color: "#38bdf8", marginBottom: "6px" }
              }
            >
              ORDER BY (Sorts: {spec.order_by.length})
            </div>
            <div style={unstyled ? undefined : { fontSize: "0.78rem" }}>
              {spec.order_by.length > 0 ? (
                spec.order_by.map((s, i) => (
                  <div key={i} style={unstyled ? undefined : { marginBottom: "4px" }}>
                    <span>{s.column}</span>{" "}
                    <span style={unstyled ? undefined : { color: "#a855f7", fontWeight: 600 }}>
                      {s.direction}
                    </span>
                  </div>
                ))
              ) : (
                <span style={unstyled ? undefined : { color: "#64748b", fontStyle: "italic" }}>
                  Default database ordering
                </span>
              )}
            </div>
          </div>

          {/* LIMIT & DISTINCT Clause */}
          <div
            data-qb="ast-clause-limits"
            style={
              unstyled
                ? undefined
                : {
                    background: "#1e293b",
                    padding: "12px",
                    borderRadius: "8px",
                    border: "1px solid #334155",
                  }
            }
          >
            <div
              style={
                unstyled
                  ? undefined
                  : { fontWeight: 700, fontSize: "0.82rem", color: "#38bdf8", marginBottom: "6px" }
              }
            >
              OPTIONS (Limit & Distinct)
            </div>
            <div style={unstyled ? undefined : { fontSize: "0.78rem" }}>
              <div>
                Distinct: <strong>{spec.distinct ? "YES" : "NO"}</strong>
              </div>
              <div>
                Limit: <strong>{spec.limit}</strong>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Code Generation */}
      {activeTab === "codegen" && (
        <div
          data-qb="playground-codegen"
          style={unstyled ? undefined : { display: "flex", flexDirection: "column", gap: "10px" }}
        >
          {/* Controls Bar for Codegen */}
          <div
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: "8px",
                  }
            }
          >
            <div style={unstyled ? undefined : { display: "flex", gap: "6px" }}>
              <button
                type="button"
                onClick={() => setCodegenTarget("sdk")}
                data-qb="codegen-tab-sdk"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: codegenTarget === "sdk" ? "#3b82f6" : "#1e293b",
                        color: codegenTarget === "sdk" ? "#ffffff" : "#94a3b8",
                        border: "1px solid #475569",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        fontSize: "0.75rem",
                        cursor: "pointer",
                        fontWeight: 600,
                      }
                }
              >
                TypeScript SDK
              </button>
              <button
                type="button"
                onClick={() => setCodegenTarget("sql")}
                data-qb="codegen-tab-sql"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: codegenTarget === "sql" ? "#3b82f6" : "#1e293b",
                        color: codegenTarget === "sql" ? "#ffffff" : "#94a3b8",
                        border: "1px solid #475569",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        fontSize: "0.75rem",
                        cursor: "pointer",
                        fontWeight: 600,
                      }
                }
              >
                Compiled SQL
              </button>
              <button
                type="button"
                onClick={() => setCodegenTarget("ast")}
                data-qb="codegen-tab-json"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: codegenTarget === "ast" ? "#3b82f6" : "#1e293b",
                        color: codegenTarget === "ast" ? "#ffffff" : "#94a3b8",
                        border: "1px solid #475569",
                        borderRadius: "6px",
                        padding: "4px 10px",
                        fontSize: "0.75rem",
                        cursor: "pointer",
                        fontWeight: 600,
                      }
                }
              >
                JSON AST
              </button>
            </div>

            <div
              style={
                unstyled
                  ? undefined
                  : { display: "flex", alignItems: "center", gap: "8px" }
              }
            >
              {codegenTarget === "sql" && (
                <select
                  aria-label="Select Dialect for compiled SQL"
                  data-qb="playground-dialect-select"
                  value={activeDialect}
                  onChange={(e) => setActiveDialect(e.target.value as SqlDialect)}
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "#1e293b",
                          color: "#38bdf8",
                          border: "1px solid #475569",
                          borderRadius: "6px",
                          padding: "4px 8px",
                          fontSize: "0.75rem",
                          fontWeight: 600,
                        }
                  }
                >
                  <option value="postgres">PostgreSQL</option>
                  <option value="mysql">MySQL</option>
                  <option value="sqlite">SQLite</option>
                  <option value="snowflake">Snowflake</option>
                  <option value="bigquery">BigQuery</option>
                  <option value="duckdb">DuckDB</option>
                </select>
              )}

              <button
                type="button"
                data-qb="playground-copy-btn"
                onClick={() => {
                  const textToCopy =
                    codegenTarget === "sdk"
                      ? generateSdkSnippet
                      : codegenTarget === "sql"
                        ? sql
                        : JSON.stringify(spec, null, 2);
                  handleCopy(textToCopy, codegenTarget);
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: copiedTarget === codegenTarget ? "#10b981" : "#334155",
                        color: "#ffffff",
                        border: "1px solid #475569",
                        borderRadius: "6px",
                        padding: "4px 12px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        cursor: "pointer",
                        transition: "background 0.2s",
                      }
                }
              >
                {copiedTarget === codegenTarget ? "✓ Copied!" : "📋 Copy Snippet"}
              </button>
            </div>
          </div>

          {/* Snippet Display */}
          <pre
            data-qb="playground-code-snippet"
            style={
              unstyled
                ? undefined
                : {
                    background: "#090d16",
                    color: codegenTarget === "sql" ? "#38bdf8" : "#e2e8f0",
                    border: "1px solid #1e293b",
                    borderRadius: "8px",
                    padding: "14px",
                    fontSize: "0.8rem",
                    overflowX: "auto",
                    margin: 0,
                    lineHeight: 1.5,
                  }
            }
          >
            <code>
              {codegenTarget === "sdk"
                ? generateSdkSnippet
                : codegenTarget === "sql"
                  ? sql
                  : JSON.stringify(spec, null, 2)}
            </code>
          </pre>
        </div>
      )}
    </div>
  );
};
