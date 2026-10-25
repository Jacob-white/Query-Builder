import React, { useState, useMemo, useEffect } from "react";
import type { QuerySpec, SqlDialect, ExportFormat } from "../types";
import { useSqlCompiler } from "../hooks/useSqlCompiler";
import { useTheme } from "../theme/ThemeProvider";

const SR_ONLY_STYLE: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

export type SdkLanguage = "typescript" | "python" | "go" | "rust" | "prisma";

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

export function generateSdkSnippet(
  spec: QuerySpec | Partial<QuerySpec>,
  language: SdkLanguage = "typescript",
): string {
  const tbl = spec.table || "table";
  const cols: string[] = (spec.columns || []).map((c) =>
    typeof c === "string" ? c : c.alias ? `${c.column || ""} AS ${c.alias}` : c.column || "",
  );
  const colsStr = cols.length > 0 ? JSON.stringify(cols) : "[]";

  if (language === "python") {
    let py = `from query_builder import QueryCompiler, QuerySpec\n\n`;
    py += `spec = QuerySpec(\n    table=${JSON.stringify(tbl)},\n    columns=${colsStr},`;
    if (spec.joins && spec.joins.length > 0) {
      py += `\n    joins=${JSON.stringify(spec.joins)},`;
    }
    if (spec.filters && spec.filters.length > 0) {
      py += `\n    filters=${JSON.stringify(
        spec.filters.map((f) => [f.column, f.op, f.value]),
      )},`;
    }
    if (spec.group_by && spec.group_by.length > 0) {
      py += `\n    group_by=${JSON.stringify(spec.group_by)},`;
    }
    if (spec.having && spec.having.length > 0) {
      py += `\n    having=${JSON.stringify(
        spec.having.map((h) => [h.column, h.op, h.value]),
      )},`;
    }
    if (spec.order_by && spec.order_by.length > 0) {
      py += `\n    order_by=${JSON.stringify(
        spec.order_by.map((s) => `${s.column} ${s.direction}`),
      )},`;
    }
    if (spec.distinct) {
      py += `\n    distinct=True,`;
    }
    if (spec.limit) {
      py += `\n    limit=${spec.limit},`;
    }
    if (spec.offset) {
      py += `\n    offset=${spec.offset},`;
    }
    py += `\n)\n\ncompiler = QueryCompiler(spec, dialect="postgres")\nsql, params, _, _ = compiler.compile()`;
    return py;
  }

  if (language === "go") {
    let go = `package main\n\nimport "github.com/jacob-white/query-builder/sdk/go/qb"\n\nfunc buildQuery() *qb.Query {\n`;
    go += `    q := qb.From(${JSON.stringify(tbl)}).\n        Select(${cols.map((c) => JSON.stringify(c)).join(", ")})`;
    if (spec.joins && spec.joins.length > 0) {
      for (const j of spec.joins) {
        go += `.\n        Join(${JSON.stringify(j.table)}, ${JSON.stringify(j.left_col || "id")}, "=", ${JSON.stringify(j.right_col || "id")})`;
      }
    }
    if (spec.filters && spec.filters.length > 0) {
      for (const f of spec.filters) {
        go += `.\n        Where(${JSON.stringify(f.column)}, ${JSON.stringify(f.op)}, ${JSON.stringify(f.value)})`;
      }
    }
    if (spec.group_by && spec.group_by.length > 0) {
      go += `.\n        GroupBy(${spec.group_by.map((g) => JSON.stringify(g)).join(", ")})`;
    }
    if (spec.having && spec.having.length > 0) {
      for (const h of spec.having) {
        go += `.\n        Having(${JSON.stringify(h.column)}, ${JSON.stringify(h.op)}, ${JSON.stringify(h.value)})`;
      }
    }
    if (spec.order_by && spec.order_by.length > 0) {
      for (const s of spec.order_by) {
        go += `.\n        OrderBy(${JSON.stringify(s.column)}, ${JSON.stringify(s.direction)})`;
      }
    }
    if (spec.distinct) {
      go += `.\n        Distinct()`;
    }
    if (spec.limit) {
      go += `.\n        Limit(${spec.limit})`;
    }
    if (spec.offset) {
      go += `.\n        Offset(${spec.offset})`;
    }
    go += `\n    return q\n}`;
    return go;
  }

  if (language === "rust") {
    let rs = `use query_builder::QueryBuilder;\n\n`;
    rs += `let query = QueryBuilder::from(${JSON.stringify(tbl)})\n    .select(&${colsStr})`;
    if (spec.joins && spec.joins.length > 0) {
      for (const j of spec.joins) {
        rs += `\n    .join(${JSON.stringify(j.table)}, ${JSON.stringify(j.left_col || "id")}, "=", ${JSON.stringify(j.right_col || "id")})`;
      }
    }
    if (spec.filters && spec.filters.length > 0) {
      for (const f of spec.filters) {
        rs += `\n    .where_clause(${JSON.stringify(f.column)}, ${JSON.stringify(f.op)}, ${JSON.stringify(f.value)})`;
      }
    }
    if (spec.group_by && spec.group_by.length > 0) {
      rs += `\n    .group_by(&${JSON.stringify(spec.group_by)})`;
    }
    if (spec.having && spec.having.length > 0) {
      for (const h of spec.having) {
        rs += `\n    .having(${JSON.stringify(h.column)}, ${JSON.stringify(h.op)}, ${JSON.stringify(h.value)})`;
      }
    }
    if (spec.order_by && spec.order_by.length > 0) {
      for (const s of spec.order_by) {
        rs += `\n    .order_by(${JSON.stringify(s.column)}, ${JSON.stringify(s.direction)})`;
      }
    }
    if (spec.distinct) {
      rs += `\n    .distinct()`;
    }
    if (spec.limit) {
      rs += `\n    .limit(${spec.limit})`;
    }
    if (spec.offset) {
      rs += `\n    .offset(${spec.offset})`;
    }
    rs += `\n    .build();`;
    return rs;
  }

  if (language === "prisma") {
    const modelName = tbl.slice(tbl.lastIndexOf(".") + 1);
    const method = spec.group_by && spec.group_by.length > 0 ? "groupBy" : "findMany";
    const prismaArgs: Record<string, unknown> = {};
    if (spec.group_by && spec.group_by.length > 0) {
      prismaArgs.by = spec.group_by;
    } else if (cols.length > 0 && !cols.includes("*")) {
      prismaArgs.select = Object.fromEntries(
        cols.map((c) => [(c.split(" AS ")[0] ?? c).trim().split(".").pop() || c, true]),
      );
    }
    if (spec.filters && spec.filters.length > 0) {
      prismaArgs.where = Object.fromEntries(
        spec.filters.map((f) => [f.column.split(".").pop() || f.column, f.value]),
      );
    }
    if (spec.having && spec.having.length > 0) {
      prismaArgs.having = Object.fromEntries(
        spec.having.map((h) => [h.column.split(".").pop() || h.column, h.value]),
      );
    }
    if (spec.order_by && spec.order_by.length > 0) {
      prismaArgs.orderBy = spec.order_by.map((s) => ({
        [s.column.split(".").pop() || s.column]: s.direction.toLowerCase(),
      }));
    }
    if (spec.distinct) {
      prismaArgs.distinct = cols.filter((c) => c !== "*");
    }
    if (spec.limit) {
      prismaArgs.take = spec.limit;
    }
    if (spec.offset) {
      prismaArgs.skip = spec.offset;
    }
    return `const rows = await prisma.${modelName}.${method}(${JSON.stringify(prismaArgs, null, 2)});`;
  }

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

  if (spec.group_by && spec.group_by.length > 0) {
    code += `\n  .groupBy(${JSON.stringify(spec.group_by)})`;
  }

  if (spec.having && spec.having.length > 0) {
    for (const h of spec.having) {
      code += `\n  .having("${h.column}", "${h.op}", ${JSON.stringify(h.value)})`;
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

  if (spec.offset) {
    code += `\n  .offset(${spec.offset})`;
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
  const { cssVariables } = useTheme();
  const [activeTab, setActiveTab] = useState<"sdk" | "sql" | "ast" | "export">("sdk");
  const [sdkLanguage, setSdkLanguage] = useState<SdkLanguage>("typescript");
  const [activeDialect, setActiveDialect] = useState<SqlDialect>(propDialect);
  const [copiedTarget, setCopiedTarget] = useState<string | null>(null);

  useEffect(() => {
    if (!copiedTarget) return;
    const timer = setTimeout(() => setCopiedTarget(null), 2000);
    return () => clearTimeout(timer);
  }, [copiedTarget]);

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

  const sdkCode = useMemo(() => generateSdkSnippet(spec, sdkLanguage), [spec, sdkLanguage]);
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
              ...(cssVariables as React.CSSProperties),
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
                    background: activeTab === "sdk" ? "var(--qb-color-primary, #3b82f6)" : "var(--qb-color-surface, #1e293b)",
                    color: activeTab === "sdk" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
                    border: "1px solid var(--qb-color-border, #475569)",
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
                    background: activeTab === "sql" ? "var(--qb-color-primary, #3b82f6)" : "var(--qb-color-surface, #1e293b)",
                    color: activeTab === "sql" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
                    border: "1px solid var(--qb-color-border, #475569)",
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
                    background: activeTab === "ast" ? "var(--qb-color-primary, #3b82f6)" : "var(--qb-color-surface, #1e293b)",
                    color: activeTab === "ast" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
                    border: "1px solid var(--qb-color-border, #475569)",
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
                    background: activeTab === "export" ? "var(--qb-color-primary, #3b82f6)" : "var(--qb-color-surface, #1e293b)",
                    color: activeTab === "export" ? "#ffffff" : "var(--qb-color-text-muted, #94a3b8)",
                    border: "1px solid var(--qb-color-border, #475569)",
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
          {activeTab === "sdk" && (
            <>
              <select
                aria-label="Select SDK Language"
                data-qb="codegen-sdk-lang-select"
                value={sdkLanguage}
                onChange={(e) => setSdkLanguage(e.target.value as SdkLanguage)}
                style={unstyled ? undefined : SR_ONLY_STYLE}
              >
                <option value="typescript">TypeScript</option>
                <option value="python">Python</option>
                <option value="go">Go</option>
                <option value="rust">Rust</option>
                <option value="prisma">Prisma</option>
              </select>
              {!unstyled && (
                <div style={{ display: "inline-flex", gap: "3px", flexWrap: "wrap" }}>
                  {(
                    [
                      { v: "typescript", l: "TypeScript" },
                      { v: "python", l: "Python" },
                      { v: "go", l: "Go" },
                      { v: "rust", l: "Rust" },
                      { v: "prisma", l: "Prisma" },
                    ] as const
                  ).map((lang) => {
                    const isSelected = sdkLanguage === lang.v;
                    return (
                      <button
                        key={lang.v}
                        type="button"
                        data-qb={`codegen-lang-${lang.v}`}
                        onClick={() => setSdkLanguage(lang.v)}
                        style={{
                          padding: "3px 7px",
                          borderRadius: "5px",
                          fontSize: "0.7rem",
                          fontWeight: isSelected ? 700 : 500,
                          cursor: "pointer",
                          border: isSelected ? "1px solid var(--qb-color-primary, #38bdf8)" : "1px solid var(--qb-color-border, #334155)",
                          background: isSelected ? "rgba(56, 189, 248, 0.16)" : "var(--qb-color-surface, #1e293b)",
                          color: isSelected ? "var(--qb-color-primary, #38bdf8)" : "var(--qb-color-text-muted, #94a3b8)",
                        }}
                      >
                        {lang.l}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {activeTab === "sql" && (
            <>
              <select
                aria-label="Select Dialect for compiled SQL"
                data-qb="playground-dialect-select"
                value={activeDialect}
                onChange={(e) => handleDialectChange(e.target.value as SqlDialect)}
                style={unstyled ? undefined : SR_ONLY_STYLE}
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
              {!unstyled && (
                <div style={{ display: "inline-flex", gap: "3px", flexWrap: "wrap" }}>
                  {(
                    [
                      { v: "postgres", l: "Postgres" },
                      { v: "mysql", l: "MySQL" },
                      { v: "sqlite", l: "SQLite" },
                      { v: "snowflake", l: "Snowflake" },
                      { v: "bigquery", l: "BigQuery" },
                      { v: "duckdb", l: "DuckDB" },
                      { v: "mssql", l: "MSSQL" },
                      { v: "clickhouse", l: "ClickHouse" },
                    ] as const
                  ).map((d) => {
                    const isSelected = activeDialect === d.v;
                    return (
                      <button
                        key={d.v}
                        type="button"
                        onClick={() => handleDialectChange(d.v)}
                        style={{
                          padding: "3px 7px",
                          borderRadius: "5px",
                          fontSize: "0.7rem",
                          fontWeight: isSelected ? 700 : 500,
                          cursor: "pointer",
                          border: isSelected ? "1px solid var(--qb-color-primary, #38bdf8)" : "1px solid var(--qb-color-border, #334155)",
                          background: isSelected ? "rgba(56, 189, 248, 0.16)" : "var(--qb-color-surface, #1e293b)",
                          color: isSelected ? "var(--qb-color-primary, #38bdf8)" : "var(--qb-color-text-muted, #94a3b8)",
                        }}
                      >
                        {d.l}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {activeTab === "export" && (
            <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
              <select
                aria-label="Select Export Format"
                data-qb="export-format-select"
                value={exportFormat}
                onChange={(e) => setExportFormat(e.target.value as ExportFormat)}
                style={unstyled ? undefined : SR_ONLY_STYLE}
              >
                <option value="csv">CSV (.csv)</option>
                <option value="json">JSON (.json)</option>
                <option value="jsonl">JSON Lines (.jsonl)</option>
                <option value="parquet">Parquet (.parquet)</option>
                <option value="arrow">Arrow Stream (.arrow)</option>
                <option value="excel">Excel (.xlsx)</option>
              </select>
              {!unstyled && (
                <div style={{ display: "inline-flex", gap: "3px", flexWrap: "wrap" }}>
                  {(
                    [
                      { v: "csv", l: "CSV" },
                      { v: "json", l: "JSON" },
                      { v: "jsonl", l: "JSONL" },
                      { v: "parquet", l: "Parquet" },
                      { v: "arrow", l: "Arrow" },
                      { v: "excel", l: "Excel" },
                    ] as const
                  ).map((fmt) => {
                    const isSelected = exportFormat === fmt.v;
                    return (
                      <button
                        key={fmt.v}
                        type="button"
                        onClick={() => setExportFormat(fmt.v)}
                        style={{
                          padding: "3px 7px",
                          borderRadius: "5px",
                          fontSize: "0.7rem",
                          fontWeight: isSelected ? 700 : 500,
                          cursor: "pointer",
                          border: isSelected ? "1px solid var(--qb-color-primary, #38bdf8)" : "1px solid var(--qb-color-border, #334155)",
                          background: isSelected ? "rgba(56, 189, 248, 0.16)" : "var(--qb-color-surface, #1e293b)",
                          color: isSelected ? "var(--qb-color-primary, #38bdf8)" : "var(--qb-color-text-muted, #94a3b8)",
                        }}
                      >
                        {fmt.l}
                      </button>
                    );
                  })}
                </div>
              )}

              <button
                type="button"
                data-qb="export-download-btn"
                disabled={isExporting}
                onClick={handleStreamDownload}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: isExporting ? "#475569" : "var(--qb-color-primary, #2563eb)",
                        color: "#ffffff",
                        border: "1px solid var(--qb-color-primary, #3b82f6)",
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
                    background: copiedTarget === activeTab ? "#10b981" : "var(--qb-color-surface, #334155)",
                    color: copiedTarget === activeTab ? "#ffffff" : "var(--qb-color-text, #ffffff)",
                    border: "1px solid var(--qb-color-border, #475569)",
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
                    ? "rgba(239, 68, 68, 0.16)"
                    : "rgba(16, 185, 129, 0.16)",
                  color: exportStatus.includes("error")
                    ? "var(--qb-color-error, #f87171)"
                    : "var(--qb-color-success, #34d399)",
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
                background: "var(--qb-color-background, #090d16)",
                color: activeTab === "sql" ? "var(--qb-color-primary, #38bdf8)" : "var(--qb-color-text, #e2e8f0)",
                border: "1px solid var(--qb-color-border, #1e293b)",
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
