import React, { useState, useMemo, useCallback, useEffect } from "react";
import type {
  DatabaseSchemaDefinition,
  SchemaSnapshot,
  TableMeta,
  ForeignKeyMeta,
} from "../types";
import { normalizeSchema } from "../utils/schemaUtils";
import { useTheme } from "../theme/ThemeProvider";
import { darkTheme, lightTheme, type QueryBuilderTheme } from "../theme/tokens";

export interface SchemaExplorerProps {
  schema?: DatabaseSchemaDefinition | SchemaSnapshot | null;
  selectedTable?: string;
  onSelectTable?: (tableName: string) => void;
  onAddToCanvas?: (tableName: string) => void;
  onOpenErd?: (tableName: string) => void;
  onQuickQuery?: (tableName: string) => void;
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
  className?: string;
}

export const SchemaExplorer: React.FC<SchemaExplorerProps> = ({
  schema,
  selectedTable: propSelectedTable,
  onSelectTable,
  onAddToCanvas,
  onOpenErd,
  onQuickQuery,
  theme: propTheme,
  unstyled = false,
  className,
}) => {
  const { theme: contextTheme } = useTheme();

  const activeTheme: QueryBuilderTheme = useMemo(() => {
    if (propTheme && typeof propTheme === "object" && "colors" in propTheme) {
      return propTheme as QueryBuilderTheme;
    }
    if (propTheme === "light") return lightTheme;
    if (propTheme === "dark") return darkTheme;
    return contextTheme;
  }, [propTheme, contextTheme]);

  const normalizedSchema = useMemo(() => normalizeSchema(schema), [schema]);
  const tablesMap = useMemo(() => normalizedSchema?.tables || {}, [normalizedSchema]);
  const allTables = useMemo(() => Object.values(tablesMap), [tablesMap]);
  const foreignKeys = useMemo(
    () => normalizedSchema?.foreign_keys || [],
    [normalizedSchema],
  );

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [activeTableName, setActiveTableName] = useState<string>(
    propSelectedTable || allTables[0]?.name || "",
  );
  const [columnFilter, setColumnFilter] = useState("");
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

  // Sync prop selection if changed externally
  useEffect(() => {
    if (propSelectedTable) {
      setActiveTableName(propSelectedTable);
    }
  }, [propSelectedTable]);

  const handleSelectTable = useCallback(
    (tblName: string) => {
      setActiveTableName(tblName);
      if (onSelectTable) {
        onSelectTable(tblName);
      }
    },
    [onSelectTable],
  );

  // Extract categories
  const categories = useMemo(() => {
    const cats = new Set<string>();
    if (normalizedSchema?.categories) {
      Object.keys(normalizedSchema.categories).forEach((c) => cats.add(c));
    }
    // Infer categories from table name prefix if underscore present
    allTables.forEach((t) => {
      if (t.schema) {
        cats.add(t.schema);
      } else if (t.name.includes("_")) {
        const prefix = t.name.split("_")[0];
        if (prefix.length > 2) cats.add(prefix);
      }
    });
    return Array.from(cats);
  }, [normalizedSchema, allTables]);

  // Outgoing & incoming foreign keys per table
  const tableFkMaps = useMemo(() => {
    const outgoing: Record<string, ForeignKeyMeta[]> = {};
    const incoming: Record<string, ForeignKeyMeta[]> = {};

    allTables.forEach((t) => {
      outgoing[t.name] = [];
      incoming[t.name] = [];
    });

    foreignKeys.forEach((fk) => {
      if (outgoing[fk.table]) outgoing[fk.table].push(fk);
      if (incoming[fk.foreign_table]) incoming[fk.foreign_table].push(fk);
    });

    return { outgoing, incoming };
  }, [allTables, foreignKeys]);

  // Filtered tables
  const filteredTables = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allTables.filter((table) => {
      // Category filter
      if (selectedCategory !== "all") {
        if (normalizedSchema?.categories?.[selectedCategory]) {
          if (!normalizedSchema.categories[selectedCategory].includes(table.name)) {
            return false;
          }
        } else if (
          table.schema !== selectedCategory &&
          !table.name.startsWith(selectedCategory + "_")
        ) {
          return false;
        }
      }

      if (!q) return true;

      // Table name match
      if (table.name.toLowerCase().includes(q)) return true;
      if (table.comment?.toLowerCase().includes(q)) return true;

      // Columns match
      return table.columns.some(
        (col) =>
          col.name.toLowerCase().includes(q) ||
          col.data_type.toLowerCase().includes(q) ||
          col.comment?.toLowerCase().includes(q),
      );
    });
  }, [allTables, searchQuery, selectedCategory, normalizedSchema]);

  const activeTable: TableMeta | undefined = tablesMap[activeTableName] || filteredTables[0];

  // Columns for active table matching column filter
  const displayedColumns = useMemo(() => {
    if (!activeTable) return [];
    const cf = columnFilter.toLowerCase().trim();
    if (!cf) return activeTable.columns;
    return activeTable.columns.filter(
      (c) =>
        c.name.toLowerCase().includes(cf) ||
        c.data_type.toLowerCase().includes(cf) ||
        c.comment?.toLowerCase().includes(cf),
    );
  }, [activeTable, columnFilter]);

  const activeOutgoingFks = useMemo(() => {
    return activeTable ? tableFkMaps.outgoing[activeTable.name] : [];
  }, [activeTable, tableFkMaps]);

  const activeIncomingFks = useMemo(() => {
    return activeTable ? tableFkMaps.incoming[activeTable.name] : [];
  }, [activeTable, tableFkMaps]);

  const showCopyMessage = (msg: string) => {
    setCopyFeedback(msg);
    setTimeout(() => setCopyFeedback(null), 1800);
  };

  const handleCopyTableName = () => {
    /* v8 ignore next */
    if (!activeTable) return;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        navigator.clipboard.writeText(activeTable.name);
      }
      showCopyMessage(`Copied "${activeTable.name}"`);
    } catch {
      showCopyMessage("Failed to copy");
    }
  };

  const handleCopySqlSelect = () => {
    /* v8 ignore next */
    if (!activeTable) return;
    const colList =
      activeTable.columns.length > 0
        ? activeTable.columns.map((c) => `"${c.name}"`).join(",\n  ")
        : "*";
    const sql = `SELECT\n  ${colList}\nFROM "${activeTable.name}"\nLIMIT 50;`;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        navigator.clipboard.writeText(sql);
      }
      showCopyMessage("Copied SQL query!");
    } catch {
      showCopyMessage("Failed to copy SQL");
    }
  };

  const getTypeColor = (dataType: string): { bg: string; text: string } => {
    const dt = dataType.toLowerCase();
    if (dt.includes("int") || dt.includes("num") || dt.includes("dec") || dt.includes("float")) {
      return { bg: "rgba(59, 130, 246, 0.15)", text: "#60a5fa" };
    }
    if (dt.includes("char") || dt.includes("text") || dt.includes("str")) {
      return { bg: "rgba(16, 185, 129, 0.15)", text: "#34d399" };
    }
    if (dt.includes("date") || dt.includes("time")) {
      return { bg: "rgba(168, 85, 247, 0.15)", text: "#c084fc" };
    }
    if (dt.includes("bool")) {
      return { bg: "rgba(245, 158, 11, 0.15)", text: "#fbbf24" };
    }
    if (dt.includes("json") || dt.includes("uuid")) {
      return { bg: "rgba(6, 182, 212, 0.15)", text: "#22d3ee" };
    }
    return { bg: "rgba(148, 163, 184, 0.15)", text: "#94a3b8" };
  };

  return (
    <div
      role="region"
      aria-label="Schema Explorer"
      data-qb="schema-explorer"
      className={className}
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              flexDirection: "column",
              gap: "14px",
              background: activeTheme.colors.background,
              color: activeTheme.colors.text,
              borderRadius: activeTheme.radii.lg,
              border: `1px solid ${activeTheme.colors.border}`,
              padding: "16px",
              fontFamily: activeTheme.typography.fontFamily,
              minHeight: "560px",
            }
      }
    >
      {/* Explorer Top Toolbar */}
      <div
        data-qb="schema-explorer-header"
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
                borderBottom: `1px solid ${activeTheme.colors.border}`,
              }
        }
      >
        <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={unstyled ? undefined : { fontSize: "1.3rem" }}>🗄️</span>
          <div>
            <div
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: activeTheme.typography.fontSizeBase,
                      fontWeight: activeTheme.typography.fontWeightBold,
                    }
              }
            >
              Schema Explorer
            </div>
            <div
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: activeTheme.typography.fontSizeXs,
                      color: activeTheme.colors.textMuted,
                    }
              }
            >
              Browse catalog hierarchy, primary/foreign keys, and data relationships.
            </div>
          </div>
        </div>

        {/* Global Stats Badges */}
        <div style={unstyled ? undefined : { display: "flex", gap: "8px", alignItems: "center" }}>
          <span
            data-qb="stat-tables-badge"
            data-testid="stat-tables-badge"
            style={
              unstyled
                ? undefined
                : {
                    padding: "4px 8px",
                    borderRadius: activeTheme.radii.sm,
                    background: activeTheme.colors.surface,
                    border: `1px solid ${activeTheme.colors.border}`,
                    fontSize: activeTheme.typography.fontSizeXs,
                    color: activeTheme.colors.textSecondary,
                  }
            }
          >
            {allTables.length} Tables
          </span>
          <span
            data-qb="stat-fks-badge"
            data-testid="stat-fks-badge"
            style={
              unstyled
                ? undefined
                : {
                    padding: "4px 8px",
                    borderRadius: activeTheme.radii.sm,
                    background: activeTheme.colors.surface,
                    border: `1px solid ${activeTheme.colors.border}`,
                    fontSize: activeTheme.typography.fontSizeXs,
                    color: activeTheme.colors.textSecondary,
                  }
            }
          >
            {foreignKeys.length} Foreign Keys
          </span>
          {onOpenErd && (
            <button
              type="button"
              onClick={() => onOpenErd(activeTable?.name || "")}
              aria-label="View interactive ERD graph"
              data-qb="btn-open-erd"
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                      padding: "5px 10px",
                      borderRadius: activeTheme.radii.sm,
                      background: activeTheme.colors.surface,
                      border: `1px solid ${activeTheme.colors.border}`,
                      color: activeTheme.colors.primary,
                      fontSize: activeTheme.typography.fontSizeSm,
                      fontWeight: activeTheme.typography.fontWeightMedium,
                      cursor: "pointer",
                    }
              }
            >
              🗺️ Interactive ERD
            </button>
          )}
        </div>
      </div>

      {/* Search and Category Filter Bar */}
      <div
        data-qb="schema-search-bar"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                flexWrap: "wrap",
                gap: "10px",
                alignItems: "center",
              }
        }
      >
        <div
          style={
            unstyled
              ? undefined
              : {
                  position: "relative",
                  flex: "1 1 260px",
                }
          }
        >
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search tables, columns, data types..."
            aria-label="Search schema"
            data-qb="schema-search-input"
            style={
              unstyled
                ? undefined
                : {
                    width: "100%",
                    boxSizing: "border-box",
                    padding: "8px 12px",
                    background: activeTheme.colors.surface,
                    border: `1px solid ${activeTheme.colors.border}`,
                    borderRadius: activeTheme.radii.sm,
                    color: activeTheme.colors.text,
                    fontSize: activeTheme.typography.fontSizeSm,
                    outline: "none",
                  }
            }
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              aria-label="Clear schema search"
              style={
                unstyled
                  ? undefined
                  : {
                      position: "absolute",
                      right: "8px",
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "transparent",
                      border: "none",
                      color: activeTheme.colors.textMuted,
                      cursor: "pointer",
                      fontSize: "0.85rem",
                    }
              }
            >
              ✕
            </button>
          )}
        </div>

        {/* Category Pills */}
        {categories.length > 0 && (
          <div
            data-qb="category-pills"
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    gap: "6px",
                    overflowX: "auto",
                    paddingBottom: "2px",
                  }
            }
          >
            <button
              type="button"
              onClick={() => setSelectedCategory("all")}
              aria-pressed={selectedCategory === "all"}
              style={
                unstyled
                  ? undefined
                  : {
                      padding: "4px 10px",
                      borderRadius: activeTheme.radii.full,
                      border: "none",
                      background:
                        selectedCategory === "all"
                          ? activeTheme.colors.primary
                          : activeTheme.colors.surface,
                      color:
                        selectedCategory === "all" ? "#fff" : activeTheme.colors.textSecondary,
                      fontSize: activeTheme.typography.fontSizeXs,
                      fontWeight: activeTheme.typography.fontWeightMedium,
                      cursor: "pointer",
                    }
              }
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setSelectedCategory(cat)}
                aria-pressed={selectedCategory === cat}
                style={
                  unstyled
                    ? undefined
                    : {
                        padding: "4px 10px",
                        borderRadius: activeTheme.radii.full,
                        border: "none",
                        background:
                          selectedCategory === cat
                            ? activeTheme.colors.primary
                            : activeTheme.colors.surface,
                        color:
                          selectedCategory === cat ? "#fff" : activeTheme.colors.textSecondary,
                        fontSize: activeTheme.typography.fontSizeXs,
                        fontWeight: activeTheme.typography.fontWeightMedium,
                        cursor: "pointer",
                      }
                }
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main Master-Detail Grid */}
      <div
        data-qb="schema-master-detail"
        style={
          unstyled
            ? undefined
            : {
                display: "grid",
                gridTemplateColumns: "280px 1fr",
                gap: "16px",
                flex: "1 1 auto",
                minHeight: "440px",
              }
        }
      >
        {/* Left Side: Table Navigation List */}
        <div
          data-qb="schema-table-list"
          role="navigation"
          aria-label="Database Tables List"
          style={
            unstyled
              ? undefined
              : {
                  background: activeTheme.colors.surface,
                  borderRadius: activeTheme.radii.md,
                  border: `1px solid ${activeTheme.colors.border}`,
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                }
          }
        >
          <div
            style={
              unstyled
                ? undefined
                : {
                    padding: "10px 12px",
                    background: "rgba(0, 0, 0, 0.15)",
                    borderBottom: `1px solid ${activeTheme.colors.border}`,
                    fontSize: activeTheme.typography.fontSizeXs,
                    fontWeight: activeTheme.typography.fontWeightBold,
                    color: activeTheme.colors.textMuted,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    display: "flex",
                    justifyContent: "space-between",
                  }
            }
          >
            <span>Tables ({filteredTables.length})</span>
            {searchQuery && (
              <span style={unstyled ? undefined : { color: activeTheme.colors.primary }}>
                Filtered
              </span>
            )}
          </div>

          <div
            style={
              unstyled
                ? undefined
                : {
                    flex: "1 1 auto",
                    overflowY: "auto",
                    padding: "6px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }
            }
          >
            {filteredTables.length === 0 ? (
              <div
                style={
                  unstyled
                    ? undefined
                    : {
                        padding: "24px 12px",
                        textAlign: "center",
                        color: activeTheme.colors.textMuted,
                        fontSize: activeTheme.typography.fontSizeSm,
                      }
                }
              >
                No tables match &quot;{searchQuery}&quot;
              </div>
            ) : (
              filteredTables.map((table) => {
                const isSelected = activeTable?.name === table.name;
                const outgoingCount = tableFkMaps.outgoing[table.name]?.length || 0;
                const incomingCount = tableFkMaps.incoming[table.name]?.length || 0;
                const isUserIsolated =
                  table.has_user_id ||
                  table.columns.some((c) => c.name === "user_id" || c.name === "tenant_id");

                return (
                  <div
                    key={table.name}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleSelectTable(table.name)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        handleSelectTable(table.name);
                      }
                    }}
                    aria-label={`Select table ${table.name}`}
                    aria-selected={isSelected}
                    data-qb="table-item"
                    data-qb-table-name={table.name}
                    style={
                      unstyled
                        ? undefined
                        : {
                            padding: "8px 10px",
                            borderRadius: activeTheme.radii.sm,
                            background: isSelected
                              ? activeTheme.colors.surfaceActive
                              : "transparent",
                            border: isSelected
                              ? `1px solid ${activeTheme.colors.primary}`
                              : "1px solid transparent",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: "8px",
                            transition: "background 0.15s ease",
                          }
                    }
                  >
                    <div
                      style={
                        unstyled
                          ? undefined
                          : {
                              display: "flex",
                              alignItems: "center",
                              gap: "8px",
                              overflow: "hidden",
                            }
                      }
                    >
                      <span style={unstyled ? undefined : { fontSize: "0.9rem" }}>📄</span>
                      <span
                        data-qb="table-name-label"
                        style={
                          unstyled
                            ? undefined
                            : {
                                fontSize: activeTheme.typography.fontSizeSm,
                                fontWeight: isSelected
                                  ? activeTheme.typography.fontWeightBold
                                  : activeTheme.typography.fontWeightMedium,
                                color: isSelected
                                  ? activeTheme.colors.primaryLight
                                  : activeTheme.colors.text,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }
                        }
                      >
                        {table.name}
                      </span>
                    </div>

                    <div
                      style={
                        unstyled
                          ? undefined
                          : { display: "flex", alignItems: "center", gap: "4px" }
                      }
                    >
                      {isUserIsolated && (
                        <span
                          title="User/Tenant Isolated Table"
                          style={
                            unstyled
                              ? undefined
                              : {
                                  fontSize: "0.68rem",
                                  padding: "1px 4px",
                                  borderRadius: activeTheme.radii.xs,
                                  background: "rgba(245, 158, 11, 0.18)",
                                  color: "#fbbf24",
                                }
                          }
                        >
                          🔒
                        </span>
                      )}
                      <span
                        title={`${table.columns.length} columns`}
                        style={
                          unstyled
                            ? undefined
                            : {
                                fontSize: "0.7rem",
                                color: activeTheme.colors.textMuted,
                                padding: "1px 5px",
                                borderRadius: activeTheme.radii.xs,
                                background: "rgba(255, 255, 255, 0.05)",
                              }
                        }
                      >
                        {table.columns.length}
                      </span>
                      {outgoingCount + incomingCount > 0 && (
                        <span
                          title={`${outgoingCount} outgoing FKs, ${incomingCount} incoming references`}
                          style={
                            unstyled
                              ? undefined
                              : {
                                  fontSize: "0.7rem",
                                  color: activeTheme.colors.accent,
                                  padding: "1px 4px",
                                  borderRadius: activeTheme.radii.xs,
                                  background: "rgba(56, 189, 248, 0.1)",
                                }
                          }
                        >
                          🔗
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Side: Table Deep Inspector */}
        <div
          data-qb="schema-table-detail"
          role="region"
          aria-label={
            activeTable ? `Table Details for ${activeTable.name}` : "Table Details Inspector"
          }
          style={
            unstyled
              ? undefined
              : {
                  background: activeTheme.colors.surface,
                  borderRadius: activeTheme.radii.md,
                  border: `1px solid ${activeTheme.colors.border}`,
                  padding: "16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "16px",
                  overflowY: "auto",
                }
          }
        >
          {activeTable ? (
            <>
              {/* Detail Header */}
              <div
                data-qb="table-detail-header"
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        flexWrap: "wrap",
                        gap: "12px",
                        paddingBottom: "12px",
                        borderBottom: `1px solid ${activeTheme.colors.border}`,
                      }
                }
              >
                <div>
                  <div
                    style={
                      unstyled
                        ? undefined
                        : { display: "flex", alignItems: "center", gap: "8px" }
                    }
                  >
                    <span style={unstyled ? undefined : { fontSize: "1.2rem" }}>🗄️</span>
                    <h3
                      data-qb="detail-table-title"
                      data-testid="detail-table-title"
                      style={
                        unstyled
                          ? undefined
                          : {
                              margin: 0,
                              fontSize: activeTheme.typography.fontSizeLg,
                              fontWeight: activeTheme.typography.fontWeightBold,
                            }
                      }
                    >
                      {activeTable.name}
                    </h3>
                    {activeTable.schema && (
                      <span
                        style={
                          unstyled
                            ? undefined
                            : {
                                fontSize: activeTheme.typography.fontSizeXs,
                                color: activeTheme.colors.textMuted,
                                padding: "2px 6px",
                                borderRadius: activeTheme.radii.xs,
                                background: "rgba(255, 255, 255, 0.08)",
                              }
                        }
                      >
                        schema: {activeTable.schema}
                      </span>
                    )}
                  </div>
                  {activeTable.comment && (
                    <div
                      data-qb="table-comment"
                      data-testid="table-comment"
                      style={
                        unstyled
                          ? undefined
                          : {
                              marginTop: "4px",
                              fontSize: activeTheme.typography.fontSizeSm,
                              color: activeTheme.colors.textSecondary,
                            }
                      }
                    >
                      {activeTable.comment}
                    </div>
                  )}
                </div>

                {/* Table Action Buttons */}
                <div
                  style={
                    unstyled
                      ? undefined
                      : { display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" }
                  }
                >
                  {copyFeedback && (
                    <span
                      role="status"
                      data-qb="copy-feedback"
                      data-testid="copy-feedback"
                      style={
                        unstyled
                          ? undefined
                          : {
                              fontSize: activeTheme.typography.fontSizeXs,
                              color: activeTheme.colors.success,
                              fontWeight: activeTheme.typography.fontWeightBold,
                            }
                      }
                    >
                      ✓ {copyFeedback}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={handleCopyTableName}
                    aria-label="Copy table name"
                    style={
                      unstyled
                        ? undefined
                        : {
                            padding: "6px 10px",
                            borderRadius: activeTheme.radii.sm,
                            background: "transparent",
                            border: `1px solid ${activeTheme.colors.border}`,
                            color: activeTheme.colors.textSecondary,
                            fontSize: activeTheme.typography.fontSizeXs,
                            cursor: "pointer",
                          }
                    }
                  >
                    🏷️ Copy Name
                  </button>
                  <button
                    type="button"
                    onClick={handleCopySqlSelect}
                    aria-label="Copy SQL select template"
                    data-qb="btn-copy-sql"
                    style={
                      unstyled
                        ? undefined
                        : {
                            padding: "6px 10px",
                            borderRadius: activeTheme.radii.sm,
                            background: "transparent",
                            border: `1px solid ${activeTheme.colors.border}`,
                            color: activeTheme.colors.textSecondary,
                            fontSize: activeTheme.typography.fontSizeXs,
                            cursor: "pointer",
                          }
                    }
                  >
                    📋 Copy SQL
                  </button>
                  {onQuickQuery && (
                    <button
                      type="button"
                      onClick={() => onQuickQuery(activeTable.name)}
                      aria-label={`Quick query table ${activeTable.name}`}
                      data-qb="btn-quick-query"
                      style={
                        unstyled
                          ? undefined
                          : {
                              padding: "6px 12px",
                              borderRadius: activeTheme.radii.sm,
                              background: activeTheme.colors.surfaceActive,
                              border: `1px solid ${activeTheme.colors.primary}`,
                              color: activeTheme.colors.primaryLight,
                              fontSize: activeTheme.typography.fontSizeSm,
                              fontWeight: activeTheme.typography.fontWeightMedium,
                              cursor: "pointer",
                            }
                      }
                    >
                      ⚡ Quick Query
                    </button>
                  )}
                  {onAddToCanvas && (
                    <button
                      type="button"
                      onClick={() => onAddToCanvas(activeTable.name)}
                      aria-label={`Add table ${activeTable.name} to canvas`}
                      data-qb="btn-add-to-canvas"
                      style={
                        unstyled
                          ? undefined
                          : {
                              padding: "6px 14px",
                              borderRadius: activeTheme.radii.sm,
                              background: activeTheme.colors.primary,
                              border: "none",
                              color: "#fff",
                              fontSize: activeTheme.typography.fontSizeSm,
                              fontWeight: activeTheme.typography.fontWeightBold,
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              gap: "4px",
                            }
                      }
                    >
                      ➕ Add to Canvas
                    </button>
                  )}
                </div>
              </div>

              {/* Columns Section */}
              <div data-qb="columns-inspector">
                <div
                  style={
                    unstyled
                      ? undefined
                      : {
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: "10px",
                        }
                  }
                >
                  <div
                    style={
                      unstyled
                        ? undefined
                        : {
                            fontSize: activeTheme.typography.fontSizeSm,
                            fontWeight: activeTheme.typography.fontWeightBold,
                            color: activeTheme.colors.text,
                          }
                    }
                  >
                    Columns ({activeTable.columns.length})
                  </div>
                  {activeTable.columns.length > 5 && (
                    <input
                      type="text"
                      value={columnFilter}
                      onChange={(e) => setColumnFilter(e.target.value)}
                      placeholder="Filter columns..."
                      aria-label="Filter columns"
                      data-qb="column-filter-input"
                      style={
                        unstyled
                          ? undefined
                          : {
                              padding: "4px 8px",
                              background: activeTheme.colors.background,
                              border: `1px solid ${activeTheme.colors.border}`,
                              borderRadius: activeTheme.radii.sm,
                              color: activeTheme.colors.text,
                              fontSize: activeTheme.typography.fontSizeXs,
                              outline: "none",
                              width: "160px",
                            }
                      }
                    />
                  )}
                </div>

                <div
                  style={
                    unstyled
                      ? undefined
                      : {
                          overflowX: "auto",
                          borderRadius: activeTheme.radii.sm,
                          border: `1px solid ${activeTheme.colors.border}`,
                        }
                  }
                >
                  <table
                    data-qb="columns-table"
                    style={
                      unstyled
                        ? undefined
                        : {
                            width: "100%",
                            borderCollapse: "collapse",
                            fontSize: activeTheme.typography.fontSizeSm,
                            textAlign: "left",
                          }
                    }
                  >
                    <thead>
                      <tr
                        style={
                          unstyled
                            ? undefined
                            : {
                                background: "rgba(0, 0, 0, 0.2)",
                                borderBottom: `1px solid ${activeTheme.colors.border}`,
                                color: activeTheme.colors.textMuted,
                                fontSize: activeTheme.typography.fontSizeXs,
                              }
                        }
                      >
                        <th style={unstyled ? undefined : { padding: "8px 12px" }}>Column</th>
                        <th style={unstyled ? undefined : { padding: "8px 12px" }}>Data Type</th>
                        <th style={unstyled ? undefined : { padding: "8px 12px" }}>Key</th>
                        <th style={unstyled ? undefined : { padding: "8px 12px" }}>Nullable</th>
                        <th style={unstyled ? undefined : { padding: "8px 12px" }}>Comment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayedColumns.map((col) => {
                        const typeColor = getTypeColor(col.data_type);
                        const isFk = activeOutgoingFks.some((fk) => fk.column === col.name);
                        return (
                          <tr
                            key={col.name}
                            data-qb="column-row"
                            data-qb-column-name={col.name}
                            style={
                              unstyled
                                ? undefined
                                : {
                                    borderBottom: `1px solid ${activeTheme.colors.border}`,
                                  }
                            }
                          >
                            <td
                              style={
                                unstyled
                                  ? undefined
                                  : {
                                      padding: "8px 12px",
                                      fontFamily: activeTheme.typography.fontMono,
                                      fontWeight: activeTheme.typography.fontWeightMedium,
                                    }
                              }
                            >
                              {col.name}
                            </td>
                            <td style={unstyled ? undefined : { padding: "8px 12px" }}>
                              <span
                                style={
                                  unstyled
                                    ? undefined
                                    : {
                                        padding: "2px 6px",
                                        borderRadius: activeTheme.radii.xs,
                                        background: typeColor.bg,
                                        color: typeColor.text,
                                        fontSize: activeTheme.typography.fontSizeXs,
                                        fontFamily: activeTheme.typography.fontMono,
                                      }
                                }
                              >
                                {col.data_type}
                              </span>
                            </td>
                            <td style={unstyled ? undefined : { padding: "8px 12px" }}>
                              <div
                                style={
                                  unstyled
                                    ? undefined
                                    : { display: "flex", gap: "4px", alignItems: "center" }
                                }
                              >
                                {col.is_primary && (
                                  <span
                                    title="Primary Key"
                                    data-qb="badge-pk"
                                    style={
                                      unstyled
                                        ? undefined
                                        : {
                                            padding: "2px 6px",
                                            borderRadius: activeTheme.radii.xs,
                                            background: "rgba(245, 158, 11, 0.2)",
                                            color: "#fbbf24",
                                            fontSize: "0.7rem",
                                            fontWeight: activeTheme.typography.fontWeightBold,
                                          }
                                    }
                                  >
                                    🔑 PK
                                  </span>
                                )}
                                {isFk && (
                                  <span
                                    title="Foreign Key"
                                    data-qb="badge-fk"
                                    style={
                                      unstyled
                                        ? undefined
                                        : {
                                            padding: "2px 6px",
                                            borderRadius: activeTheme.radii.xs,
                                            background: "rgba(56, 189, 248, 0.2)",
                                            color: "#38bdf8",
                                            fontSize: "0.7rem",
                                            fontWeight: activeTheme.typography.fontWeightBold,
                                          }
                                    }
                                  >
                                    🔗 FK
                                  </span>
                                )}
                              </div>
                            </td>
                            <td style={unstyled ? undefined : { padding: "8px 12px" }}>
                              <span
                                style={
                                  unstyled
                                    ? undefined
                                    : {
                                        color: col.is_nullable
                                          ? activeTheme.colors.textMuted
                                          : activeTheme.colors.textSecondary,
                                        fontSize: activeTheme.typography.fontSizeXs,
                                      }
                                }
                              >
                                {col.is_nullable ? "Nullable" : "NOT NULL"}
                              </span>
                            </td>
                            <td
                              style={
                                unstyled
                                  ? undefined
                                  : {
                                      padding: "8px 12px",
                                      color: activeTheme.colors.textMuted,
                                      fontSize: activeTheme.typography.fontSizeXs,
                                    }
                              }
                            >
                              {col.comment || "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Relationships & Foreign Keys Panel */}
              <div
                data-qb="relationships-inspector"
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        flexDirection: "column",
                        gap: "12px",
                        paddingTop: "6px",
                      }
                }
              >
                <div
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: activeTheme.typography.fontSizeSm,
                          fontWeight: activeTheme.typography.fontWeightBold,
                          color: activeTheme.colors.text,
                        }
                  }
                >
                  Relationships & Foreign Keys
                </div>

                {activeOutgoingFks.length === 0 && activeIncomingFks.length === 0 ? (
                  <div
                    style={
                      unstyled
                        ? undefined
                        : {
                            fontSize: activeTheme.typography.fontSizeXs,
                            color: activeTheme.colors.textMuted,
                            padding: "8px",
                            background: "rgba(0,0,0,0.1)",
                            borderRadius: activeTheme.radii.sm,
                          }
                    }
                  >
                    No direct foreign keys configured for this table.
                  </div>
                ) : (
                  <div
                    style={
                      unstyled
                        ? undefined
                        : {
                            display: "grid",
                            gridTemplateColumns:
                              activeOutgoingFks.length > 0 && activeIncomingFks.length > 0
                                ? "1fr 1fr"
                                : "1fr",
                            gap: "12px",
                          }
                    }
                  >
                    {/* Outgoing Foreign Keys */}
                    {activeOutgoingFks.length > 0 && (
                      <div
                        data-qb="outgoing-fks"
                        style={
                          unstyled
                            ? undefined
                            : {
                                background: "rgba(0, 0, 0, 0.12)",
                                padding: "10px",
                                borderRadius: activeTheme.radii.sm,
                                border: `1px solid ${activeTheme.colors.border}`,
                              }
                        }
                      >
                        <div
                          style={
                            unstyled
                              ? undefined
                              : {
                                  fontSize: activeTheme.typography.fontSizeXs,
                                  color: activeTheme.colors.textMuted,
                                  fontWeight: activeTheme.typography.fontWeightBold,
                                  marginBottom: "8px",
                                  textTransform: "uppercase",
                                }
                          }
                        >
                          References Other Tables ({activeOutgoingFks.length})
                        </div>
                        <div
                          style={
                            unstyled
                              ? undefined
                              : { display: "flex", flexDirection: "column", gap: "6px" }
                          }
                        >
                          {activeOutgoingFks.map((fk, idx) => (
                            <div
                              key={`${fk.column}-${fk.foreign_table}-${idx}`}
                              style={
                                unstyled
                                  ? undefined
                                  : {
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "space-between",
                                      fontSize: activeTheme.typography.fontSizeXs,
                                      padding: "4px 8px",
                                      borderRadius: activeTheme.radii.xs,
                                      background: activeTheme.colors.surface,
                                    }
                              }
                            >
                              <span>
                                <strong style={{ color: activeTheme.colors.text }}>
                                  {fk.column}
                                </strong>{" "}
                                ➔ {fk.foreign_table}.{fk.foreign_column}
                              </span>
                              <button
                                type="button"
                                onClick={() => handleSelectTable(fk.foreign_table)}
                                aria-label={`Jump to table ${fk.foreign_table}`}
                                style={
                                  unstyled
                                    ? undefined
                                    : {
                                        background: "transparent",
                                        border: "none",
                                        color: activeTheme.colors.primary,
                                        cursor: "pointer",
                                        fontWeight: activeTheme.typography.fontWeightBold,
                                        fontSize: activeTheme.typography.fontSizeXs,
                                      }
                                }
                              >
                                View ➔
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Incoming Foreign Keys */}
                    {activeIncomingFks.length > 0 && (
                      <div
                        data-qb="incoming-fks"
                        style={
                          unstyled
                            ? undefined
                            : {
                                background: "rgba(0, 0, 0, 0.12)",
                                padding: "10px",
                                borderRadius: activeTheme.radii.sm,
                                border: `1px solid ${activeTheme.colors.border}`,
                              }
                        }
                      >
                        <div
                          style={
                            unstyled
                              ? undefined
                              : {
                                  fontSize: activeTheme.typography.fontSizeXs,
                                  color: activeTheme.colors.textMuted,
                                  fontWeight: activeTheme.typography.fontWeightBold,
                                  marginBottom: "8px",
                                  textTransform: "uppercase",
                                }
                          }
                        >
                          Referenced By ({activeIncomingFks.length})
                        </div>
                        <div
                          style={
                            unstyled
                              ? undefined
                              : { display: "flex", flexDirection: "column", gap: "6px" }
                          }
                        >
                          {activeIncomingFks.map((fk, idx) => (
                            <div
                              key={`${fk.table}-${fk.column}-${idx}`}
                              style={
                                unstyled
                                  ? undefined
                                  : {
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "space-between",
                                      fontSize: activeTheme.typography.fontSizeXs,
                                      padding: "4px 8px",
                                      borderRadius: activeTheme.radii.xs,
                                      background: activeTheme.colors.surface,
                                    }
                              }
                            >
                              <span>
                                {fk.table}.{fk.column} ➔{" "}
                                <strong style={{ color: activeTheme.colors.text }}>
                                  {fk.foreign_column}
                                </strong>
                              </span>
                              <button
                                type="button"
                                onClick={() => handleSelectTable(fk.table)}
                                aria-label={`Jump to table ${fk.table}`}
                                style={
                                  unstyled
                                    ? undefined
                                    : {
                                        background: "transparent",
                                        border: "none",
                                        color: activeTheme.colors.primary,
                                        cursor: "pointer",
                                        fontWeight: activeTheme.typography.fontWeightBold,
                                        fontSize: activeTheme.typography.fontSizeXs,
                                      }
                                }
                              >
                                View ➔
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      justifyContent: "center",
                      height: "100%",
                      color: activeTheme.colors.textMuted,
                      gap: "8px",
                    }
              }
            >
              <span style={{ fontSize: "2rem" }}>🗄️</span>
              <div>Select a table from the list to explore columns and relationships.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
