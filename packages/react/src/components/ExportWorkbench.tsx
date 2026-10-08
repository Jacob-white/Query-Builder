import React, { useState, useMemo, useEffect } from "react";
import type { QuerySpec, SqlDialect, ExportFormat } from "../types";
import { useSqlCompiler } from "../hooks/useSqlCompiler";

export interface ExportWorkbenchProps {
  spec: QuerySpec | Partial<QuerySpec>;
  sql?: string;
  dialect?: SqlDialect;
  onDialectChange?: (dialect: SqlDialect) => void;
  onCopy?: (text: string, format: string) => void;
  streamEndpoint?: string;
  onExportStream?: (format: ExportFormat) => Promise<void> | void;
  className?: string;
  style?: React.CSSProperties;
  unstyled?: boolean;
}

export function generateSdkSnippet(spec: QuerySpec | Partial<QuerySpec>): string {
  const tbl = spec.table || "table";
  const cols = (spec.columns || []).map((c) =>
    typeof c === "string" ? c : c.alias ? `${c.column} AS ${c.alias}` : c.column,
  );
  const colsStr = cols.length > 0 ? JSON.stringify(cols) : "[]";

  let code = `import { createQuery, createQueryBuilderClient } from "@jacob-white/query-builder-react/client";\n\n`;
  code += `const client = createQueryBuilderClient({ baseUrl: "/api/qb" });\n\n`;
  code += `const query = createQuery()\n  .from("${tbl}")\n  .select(${colsStr})`;

  if (spec.joins && spec.joins.length > 0) {
    for (const j of spec.joins) {
      code += `\n  .join("${j.table}", "${j.left_col || "id"}", "=", "${j.right_col || "id"}")`;
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

  code += `;\n\n// Compile SQL or execute\nconst { sql, params } = await client.compile(query.toSpec());\nconst result = await client.execute(query.toSpec());\n// or: const result = await query.execute(client);`;
  return code;
}

export const ExportWorkbench: React.FC<ExportWorkbenchProps> = ({
  spec,
  sql: externalSql,
  dialect: propDialect = "postgres",
  onDialectChange,
  onCopy,
  streamEndpoint = "/api/v1/export/stream",
  onExportStream,
  className,
  style,
  unstyled = false,
}) => {
  const [activeTab, setActiveTab] = useState<"sdk" | "sql" | "ast" | "export">("sdk");
  const [activeDialect, setActiveDialect] = useState<SqlDialect>(propDialect);
  const [copiedTarget, setCopiedTarget] = useState<string | null>(null);

  const [exportFormat, setExportFormat] = useState<ExportFormat>("csv");
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [exportStatus, setExportStatus] = useState<string | null>(null);

  useEffect(() => {
    if (propDialect) {
      setActiveDialect(propDialect);
    }
  }, [propDialect]);

  const { sql: compiledSql } = useSqlCompiler(spec, {
    dialect: activeDialect,
  });

  const displaySql =
    externalSql !== undefined && activeDialect === propDialect
      ? externalSql
      : compiledSql;

  const sdkCode = useMemo(() => generateSdkSnippet(spec), [spec]);
  const astJson = useMemo(() => JSON.stringify(spec, null, 2), [spec]);

  const currentContent = useMemo(() => {
    switch (activeTab) {
      case "sdk":
        return sdkCode;
      case "sql":
        return displaySql;
      case "ast":
        return astJson;
      case "export":
        return `// Streaming Export Config\n// Format: ${exportFormat}\n// Target: ${streamEndpoint}\n\nPOST ${streamEndpoint}\nPayload: ${JSON.stringify({ spec, format: exportFormat }, null, 2)}`;
    }
  }, [activeTab, sdkCode, displaySql, astJson, exportFormat, streamEndpoint, spec]);

  const handleDialectChange = (newDialect: SqlDialect) => {
    setActiveDialect(newDialect);
    onDialectChange?.(newDialect);
  };

  const handleCopy = async () => {
    const textToCopy = currentContent;
    onCopy?.(textToCopy, activeTab);

    if (typeof navigator !== "undefined" && navigator?.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(textToCopy);
        setCopiedTarget(activeTab);
        setTimeout(() => {
          setCopiedTarget(null);
        }, 2000);
      } catch {
        /* ignore */
      }
    }
  };

  const handleStreamDownload = async () => {
    setIsExporting(true);
    setExportStatus("Downloading...");

    try {
      if (onExportStream) {
        await onExportStream(exportFormat);
        setExportStatus("Download complete!");
        return;
      }

      if (typeof fetch !== "undefined") {
        const res = await fetch(streamEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spec, format: exportFormat }),
        });

        if (!res.ok) {
          throw new Error(`Export failed with HTTP ${res.status}`);
        }

        const blob = await res.blob();
        if (typeof window !== "undefined" && window.URL && document.createElement) {
          const downloadUrl = window.URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = downloadUrl;
          const ext = exportFormat === "excel" ? "xlsx" : exportFormat;
          link.download = `export.${ext}`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          window.URL.revokeObjectURL(downloadUrl);
        }
        setExportStatus("Download complete!");
      }
    } catch (err) {
      setExportStatus(`Export error: ${(err as Error | null | undefined)?.message || String(err)}`);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div
      data-qb="export-workbench"
      data-qb-codegen="true"
      data-qb-unstyled={unstyled ? "true" : undefined}
      className={className}
      style={
        unstyled
          ? style
          : {
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              ...style,
            }
      }
    >
      {/* Controls Bar */}
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
            onClick={() => setActiveTab("sdk")}
            data-qb="codegen-tab-sdk"
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "sdk" ? "#3b82f6" : "#1e293b",
                    color: activeTab === "sdk" ? "#ffffff" : "#94a3b8",
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
            onClick={() => setActiveTab("sql")}
            data-qb="codegen-tab-sql"
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "sql" ? "#3b82f6" : "#1e293b",
                    color: activeTab === "sql" ? "#ffffff" : "#94a3b8",
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
            onClick={() => setActiveTab("ast")}
            data-qb="codegen-tab-json"
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "ast" ? "#3b82f6" : "#1e293b",
                    color: activeTab === "ast" ? "#ffffff" : "#94a3b8",
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
          <button
            type="button"
            onClick={() => setActiveTab("export")}
            data-qb="codegen-tab-export"
            style={
              unstyled
                ? undefined
                : {
                    background: activeTab === "export" ? "#3b82f6" : "#1e293b",
                    color: activeTab === "export" ? "#ffffff" : "#94a3b8",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    fontSize: "0.75rem",
                    cursor: "pointer",
                    fontWeight: 600,
                  }
            }
          >
            Streaming Export
          </button>
        </div>

        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", gap: "8px" }
          }
        >
          {activeTab === "sql" && (
            <select
              aria-label="Select Dialect for compiled SQL"
              data-qb="playground-dialect-select"
              value={activeDialect}
              onChange={(e) => handleDialectChange(e.target.value as SqlDialect)}
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
              <option value="mssql">SQL Server</option>
              <option value="clickhouse">ClickHouse</option>
            </select>
          )}

          {activeTab === "export" && (
            <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "6px" }}>
              <select
                aria-label="Select Export Format"
                data-qb="export-format-select"
                value={exportFormat}
                onChange={(e) => setExportFormat(e.target.value as ExportFormat)}
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
                <option value="csv">CSV (.csv)</option>
                <option value="json">JSON (.json)</option>
                <option value="jsonl">JSON Lines (.jsonl)</option>
                <option value="parquet">Parquet (.parquet)</option>
                <option value="arrow">Arrow Stream (.arrow)</option>
                <option value="excel">Excel (.xlsx)</option>
              </select>

              <button
                type="button"
                data-qb="export-download-btn"
                disabled={isExporting}
                onClick={handleStreamDownload}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: isExporting ? "#475569" : "#2563eb",
                        color: "#ffffff",
                        border: "1px solid #3b82f6",
                        borderRadius: "6px",
                        padding: "4px 12px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        cursor: isExporting ? "wait" : "pointer",
                      }
                }
              >
                {isExporting ? "⏳ Downloading..." : "⬇ Download Stream"}
              </button>
            </div>
          )}

          <button
            type="button"
            data-qb="playground-copy-btn"
            onClick={handleCopy}
            style={
              unstyled
                ? undefined
                : {
                    background: copiedTarget === activeTab ? "#10b981" : "#334155",
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
            {copiedTarget === activeTab ? "✓ Copied!" : "📋 Copy Snippet"}
          </button>
        </div>
      </div>

      {exportStatus && (
        <div
          data-qb="export-status-badge"
          style={
            unstyled
              ? undefined
              : {
                  padding: "4px 8px",
                  borderRadius: "4px",
                  fontSize: "0.75rem",
                  background: exportStatus.includes("error")
                    ? "rgba(239, 68, 68, 0.2)"
                    : "rgba(16, 185, 129, 0.2)",
                  color: exportStatus.includes("error") ? "#f87171" : "#34d399",
                }
          }
        >
          {exportStatus}
        </div>
      )}

      {/* Snippet Display */}
      <pre
        data-qb="playground-code-snippet"
        style={
          unstyled
            ? undefined
            : {
                background: "#090d16",
                color: activeTab === "sql" ? "#38bdf8" : "#e2e8f0",
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
        <code>{currentContent}</code>
      </pre>
    </div>
  );
};
