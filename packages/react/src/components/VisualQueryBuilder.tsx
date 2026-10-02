import React, { useState, useMemo } from "react";
import type {
  VisualQueryBuilderProps,
  TableMeta,
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  QueryResultData,
} from "../types";
import { QueryCanvas } from "./QueryCanvas";
import { QueryResultsTable } from "./QueryResultsTable";
import { SchemaErdModal } from "./SchemaErdModal";
import { compileVisualState } from "../utils/compiler";
import { validateSqlSafety } from "../utils/safety";

export const VisualQueryBuilder: React.FC<VisualQueryBuilderProps> = ({
  schema,
  presets = [],
  initialTable,
  onExecuteQuery,
  onSaveQuery,
  readOnly = false,
}) => {
  const allTables = useMemo(() => Object.values(schema?.tables || {}), [schema]);
  const defaultTable = initialTable || allTables[0]?.name || "";

  const [activeTab, setActiveTab] = useState<"visual" | "sql" | "results">("visual");
  const [primaryTable, setPrimaryTable] = useState<string>(defaultTable);
  const [activeTableNames, setActiveTableNames] = useState<string[]>(
    defaultTable ? [defaultTable] : [],
  );

  const [selectedColumns, setSelectedColumns] = useState<
    Record<string, VisualColumnSelect>
  >({});
  const [orderedProjectionKeys, setOrderedProjectionKeys] = useState<string[]>([]);
  const [joins, setJoins] = useState<VisualJoin[]>([]);
  const [filters, setFilters] = useState<VisualFilter[]>([]);
  const [sorts, setSorts] = useState<VisualSort[]>([]);
  const [isDistinct, setIsDistinct] = useState<boolean>(false);
  const [limit, setLimit] = useState<number>(50);

  const [rawSql, setRawSql] = useState<string>("");
  const [isRawMode, setIsRawMode] = useState<boolean>(false);
  const [isErdOpen, setIsErdOpen] = useState<boolean>(false);

  const [queryResults, setQueryResults] = useState<QueryResultData | null>(null);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [executionError, setExecutionError] = useState<string | null>(null);

  // Active table metadata
  const activeTables: TableMeta[] = useMemo(() => {
    return activeTableNames
      .map((name) => schema?.tables?.[name])
      .filter((t): t is TableMeta => Boolean(t));
  }, [activeTableNames, schema]);

  // Compiled visual query
  const compiled = useMemo(() => {
    return compileVisualState(
      primaryTable,
      selectedColumns,
      orderedProjectionKeys,
      joins,
      filters,
      sorts,
      isDistinct,
      limit,
      schema,
    );
  }, [
    primaryTable,
    selectedColumns,
    orderedProjectionKeys,
    joins,
    filters,
    sorts,
    isDistinct,
    limit,
    schema,
  ]);

  const currentSql = isRawMode ? rawSql : compiled.sql;
  const safety = useMemo(() => validateSqlSafety(currentSql), [currentSql]);

  // Handle column selection toggle
  const handleToggleColumn = (tableName: string, colName: string) => {
    const key = `${tableName}.${colName}`;
    setSelectedColumns((prev) => {
      const next = { ...prev };
      if (next[key]) {
        delete next[key];
        setOrderedProjectionKeys((keys) => keys.filter((k) => k !== key));
      } else {
        next[key] = { table: tableName, name: colName };
        setOrderedProjectionKeys((keys) => [...keys, key]);
      }
      return next;
    });
  };

  const handleAddTableToCanvas = (tableName: string) => {
    if (!activeTableNames.includes(tableName)) {
      setActiveTableNames((prev) => [...prev, tableName]);
      if (!primaryTable) {
        setPrimaryTable(tableName);
      }
    }
  };

  const handleRemoveTable = (tableName: string) => {
    setActiveTableNames((prev) => prev.filter((t) => t !== tableName));
    setJoins((prev) => prev.filter((j) => j.table !== tableName && j.left_table !== tableName));
    setSelectedColumns((prev) => {
      const next = { ...prev };
      Object.keys(next).forEach((k) => {
        if (next[k].table === tableName) delete next[k];
      });
      return next;
    });
    setOrderedProjectionKeys((prev) =>
      prev.filter((k) => !k.startsWith(`${tableName}.`)),
    );
    if (primaryTable === tableName) {
      const remaining = activeTableNames.filter((t) => t !== tableName);
      setPrimaryTable(remaining[0] || "");
    }
  };

  // Run Query handler
  const handleRunQuery = async () => {
    if (!currentSql.trim() || !safety.valid) return;
    setIsRunning(true);
    setExecutionError(null);
    try {
      if (onExecuteQuery) {
        const res = await onExecuteQuery(currentSql, compiled.spec);
        if (res) {
          setQueryResults(res);
          setActiveTab("results");
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setExecutionError(message);
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "14px",
        background: "#090d16",
        color: "#f8fafc",
        borderRadius: "12px",
        border: "1px solid rgba(255, 255, 255, 0.1)",
        padding: "16px",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Top Controls Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
          paddingBottom: "12px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {/* Tabs */}
          <div
            style={{
              display: "flex",
              background: "rgba(30, 41, 59, 0.7)",
              borderRadius: "8px",
              padding: "2px",
              border: "1px solid rgba(255, 255, 255, 0.08)",
            }}
          >
            <button
              type="button"
              onClick={() => setActiveTab("visual")}
              style={{
                background: activeTab === "visual" ? "#3b82f6" : "transparent",
                color: activeTab === "visual" ? "#fff" : "#94a3b8",
                border: "none",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              🎨 Visual Builder
            </button>
            <button
              type="button"
              onClick={() => {
                if (!isRawMode) setRawSql(compiled.sql);
                setActiveTab("sql");
              }}
              style={{
                background: activeTab === "sql" ? "#3b82f6" : "transparent",
                color: activeTab === "sql" ? "#fff" : "#94a3b8",
                border: "none",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              📝 Raw SQL
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("results")}
              style={{
                background: activeTab === "results" ? "#3b82f6" : "transparent",
                color: activeTab === "results" ? "#fff" : "#94a3b8",
                border: "none",
                borderRadius: "6px",
                padding: "6px 12px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              📊 Results {queryResults ? `(${queryResults.count})` : ""}
            </button>
          </div>

          {/* ERD Button */}
          <button
            type="button"
            onClick={() => setIsErdOpen(true)}
            style={{
              background: "rgba(30, 41, 59, 0.5)",
              color: "#38bdf8",
              border: "1px solid rgba(56, 189, 248, 0.3)",
              borderRadius: "6px",
              padding: "6px 12px",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            🗺️ Schema ERD
          </button>
        </div>

        {/* Action Controls */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          {/* Preset templates */}
          {presets.length > 0 && (
            <select
              defaultValue=""
              onChange={(e) => {
                const preset = presets.find((p) => p.id === e.target.value);
                if (preset?.sql) {
                  setRawSql(preset.sql);
                  setIsRawMode(true);
                  setActiveTab("sql");
                }
              }}
              style={{
                background: "#1e293b",
                color: "#e2e8f0",
                border: "1px solid #475569",
                borderRadius: "6px",
                padding: "6px 10px",
                fontSize: "0.8rem",
              }}
            >
              <option value="" disabled>
                ⚡ Starters & Presets...
              </option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          )}

          {/* Run Query Button */}
          {!readOnly && (
            <button
              type="button"
              onClick={handleRunQuery}
              disabled={isRunning || !safety.valid}
              style={{
                background: safety.valid ? "#10b981" : "#475569",
                color: "#ffffff",
                border: "none",
                borderRadius: "6px",
                padding: "6px 16px",
                fontSize: "0.85rem",
                fontWeight: 700,
                cursor: safety.valid && !isRunning ? "pointer" : "not-allowed",
                boxShadow: safety.valid ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "none",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              {isRunning ? "⏳ Running..." : "▶ Run Query"}
            </button>
          )}
        </div>
      </div>

      {/* Safety & AST Status banner */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: "0.78rem",
          padding: "6px 12px",
          borderRadius: "6px",
          background: safety.valid ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.1)",
          border: safety.valid ? "1px solid rgba(16, 185, 129, 0.2)" : "1px solid rgba(239, 68, 68, 0.3)",
          color: safety.valid ? "#34d399" : "#f87171",
        }}
      >
        <span>
          {safety.valid ? "🛡️ Read-Only Protected (AST Verified)" : `⚠️ Security Notice: ${safety.message}`}
        </span>
        <span style={{ color: "#64748b" }}>Dialect: ANSI / PostgreSQL</span>
      </div>

      {/* Error message banner */}
      {executionError && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: "6px",
            background: "rgba(239, 68, 68, 0.15)",
            border: "1px solid rgba(239, 68, 68, 0.4)",
            color: "#fca5a5",
            fontSize: "0.82rem",
          }}
        >
          ❌ {executionError}
        </div>
      )}

      {/* Tab Panels */}
      {activeTab === "visual" && (
        <QueryCanvas
          schema={schema}
          activeTables={activeTables}
          primaryTable={primaryTable}
          selectedColumns={selectedColumns}
          orderedProjectionKeys={orderedProjectionKeys}
          joins={joins}
          filters={filters}
          sorts={sorts}
          isDistinct={isDistinct}
          limit={limit}
          onToggleColumn={handleToggleColumn}
          onRemoveTable={handleRemoveTable}
          onAddTableToCanvas={handleAddTableToCanvas}
          onUpdateColumnSelect={(key, updates) =>
            setSelectedColumns((prev) => ({
              ...prev,
              [key]: { ...prev[key], ...updates },
            }))
          }
          onRemoveColumnProjection={(key) => {
            setSelectedColumns((prev) => {
              const next = { ...prev };
              delete next[key];
              return next;
            });
            setOrderedProjectionKeys((keys) => keys.filter((k) => k !== key));
          }}
          onJoinsChange={setJoins}
          onFiltersChange={setFilters}
          onSortsChange={setSorts}
          onDistinctChange={setIsDistinct}
          onLimitChange={setLimit}
        />
      )}

      {activeTab === "sql" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "0.85rem", color: "#94a3b8", fontWeight: 600 }}>
              Live SQL Code Editor
            </span>
            <button
              type="button"
              onClick={() => {
                setRawSql(compiled.sql);
                setIsRawMode(false);
              }}
              style={{
                background: "transparent",
                border: "none",
                color: "#60a5fa",
                cursor: "pointer",
                fontSize: "0.75rem",
              }}
            >
              🔄 Sync with Visual Canvas
            </button>
          </div>
          <textarea
            value={currentSql}
            onChange={(e) => {
              setIsRawMode(true);
              setRawSql(e.target.value);
            }}
            rows={12}
            style={{
              width: "100%",
              background: "#0f172a",
              color: "#38bdf8",
              fontFamily: "monospace",
              fontSize: "0.85rem",
              border: "1px solid #334155",
              borderRadius: "8px",
              padding: "12px",
              lineHeight: 1.5,
              resize: "vertical",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>
      )}

      {activeTab === "results" && (
        <QueryResultsTable results={queryResults} isLoading={isRunning} />
      )}

      {/* Schema ERD Modal */}
      <SchemaErdModal
        isOpen={isErdOpen}
        onClose={() => setIsErdOpen(false)}
        schema={schema}
        onSelectTable={(tbl) => handleAddTableToCanvas(tbl)}
      />
    </div>
  );
};
