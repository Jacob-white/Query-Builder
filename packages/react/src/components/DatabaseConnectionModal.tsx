/**
 * Database Connection & Switcher Modal Component.
 * ================================================
 * Provides a friendly, non-intimidating UI for connecting to PostgreSQL,
 * MySQL/MariaDB, SQLite, DuckDB, connection URIs, or uploaded local files
 * (.sqlite, .db, .csv, .json), testing connections with live feedback, and
 * switching or disconnecting databases.
 */

import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useTheme } from "../theme/ThemeProvider";
import { darkTheme, lightTheme, themeToCssVariables, type QueryBuilderTheme } from "../theme/tokens";
import type { SchemaSnapshot } from "../types";

export type DatabaseEngineOption = "postgres" | "mysql" | "sqlite" | "duckdb" | "upload" | "uri";

export interface DatabaseConnectionInfo {
  id: string;
  name: string;
  group?: string;
  dialect: string;
  schema_name?: string;
  description?: string;
  icon?: string;
  default_table?: string;
  available?: boolean;
  is_custom?: boolean;
  table_count?: number | null;
  foreign_key_count?: number | null;
}

export interface DatabaseConnectionConfig {
  id?: string;
  name: string;
  dialect: string;
  connection_uri?: string;
  host?: string;
  port?: number;
  database?: string;
  user?: string;
  password?: string;
  schema_name?: string;
  sslmode?: string;
  file_path?: string;
  filename?: string;
  content_base64?: string;
}

export interface DatabaseTestResult {
  ok: boolean;
  status: string;
  dialect: string;
  latency_ms?: number;
  engine_version?: string;
  table_count: number;
  foreign_key_count: number;
  sample_tables?: string[];
  default_table?: string;
  message?: string;
  detail?: string;
}

export interface ParsedDatabaseUri {
  dialect: "postgres" | "mysql" | "sqlite" | "duckdb";
  host?: string;
  port?: number;
  database?: string;
  user?: string;
  password?: string;
  schema_name?: string;
  sslmode?: string;
  file_path?: string;
}

/**
 * Parses a database connection URI (postgresql://, mysql://, sqlite:///, duckdb:///)
 * into structured connection fields.
 */
export function parseDatabaseUri(rawUri: string): ParsedDatabaseUri | null {
  const trimmed = rawUri.trim();
  if (!trimmed) return null;

  const lower = trimmed.toLowerCase();
  if (lower.startsWith("sqlite:///") || lower.startsWith("sqlite://")) {
    const rawPath = trimmed.replace(/^sqlite:\/\/\/?/i, "").split("?")[0].trim() || ":memory:";
    const pathPart = rawPath.replace(/^\/+([A-Za-z]:[\\/]|\\\\)/, "$1");
    return {
      dialect: "sqlite",
      file_path: pathPart,
      database: pathPart.split(/[/\\]/).pop()!,
    };
  }

  if (lower.startsWith("duckdb:///") || lower.startsWith("duckdb://")) {
    const rawPath = trimmed.replace(/^duckdb:\/\/\/?/i, "").split("?")[0].trim() || ":memory:";
    const pathPart = rawPath.replace(/^\/+([A-Za-z]:[\\/]|\\\\)/, "$1");
    return {
      dialect: "duckdb",
      file_path: pathPart,
      database: pathPart.split(/[/\\]/).pop()!,
    };
  }

  let dialect: "postgres" | "mysql" | null = null;
  let normalized = trimmed;
  if (/^postgres(ql)?(\+\w+)?:\/\//i.test(trimmed)) {
    dialect = "postgres";
    normalized = trimmed.replace(/^postgres(ql)?(\+\w+)?:\/\//i, "http://");
  } else if (/^(mysql|mariadb)(\+\w+)?:\/\//i.test(trimmed)) {
    dialect = "mysql";
    normalized = trimmed.replace(/^(mysql|mariadb)(\+\w+)?:\/\//i, "http://");
  }

  if (!dialect) return null;

  try {
    const url = new URL(normalized);
    const defaultPort = dialect === "postgres" ? 5432 : 3306;
    const port = url.port ? Number.parseInt(url.port, 10) : defaultPort;
    const database = decodeURIComponent(url.pathname.replace(/^\/+/, ""));
    const user = url.username ? decodeURIComponent(url.username) : undefined;
    const password = url.password ? decodeURIComponent(url.password) : undefined;
    const schemaParam = url.searchParams.get("schema") || url.searchParams.get("currentSchema");
    const schema_name = schemaParam || (dialect === "postgres" ? "public" : undefined);
    const sslmode = url.searchParams.get("sslmode") || undefined;

    return {
      dialect,
      host: url.hostname,
      port,
      database,
      user,
      password,
      schema_name,
      sslmode,
    };
  } catch {
    return null;
  }
}

export interface DatabaseConnectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  databases?: DatabaseConnectionInfo[];
  activeDatabaseId?: string;
  onSelectDatabase?: (dbId: string) => void;
  onDatabaseConnected?: (db: DatabaseConnectionInfo, schema?: SchemaSnapshot) => void;
  onDatabaseDisconnected?: (dbId: string) => void;
  onTestConnection?: (config: DatabaseConnectionConfig) => Promise<DatabaseTestResult>;
  onConnectDatabase?: (
    config: DatabaseConnectionConfig,
  ) => Promise<{ database: DatabaseConnectionInfo; schema?: SchemaSnapshot }>;
  onDisconnectDatabase?: (dbId: string) => Promise<void>;
  apiBaseUrl?: string;
  defaultTab?: "connect" | "manage";
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
}

const ENGINE_OPTIONS: {
  id: DatabaseEngineOption;
  label: string;
  badge: string;
  subtitle: string;
}[] = [
  { id: "postgres", label: "PostgreSQL", badge: "PG", subtitle: "PostgreSQL, Supabase, Neon, Timescale" },
  { id: "mysql", label: "MySQL / MariaDB", badge: "MY", subtitle: "MySQL, MariaDB, TiDB, PlanetScale" },
  { id: "sqlite", label: "SQLite File", badge: "SQ", subtitle: "Local .db / .sqlite file path" },
  { id: "duckdb", label: "DuckDB", badge: "DK", subtitle: "Analytical .duckdb or :memory:" },
  { id: "upload", label: "Upload File", badge: "UP", subtitle: "Drop .sqlite, .db, .csv, or .json" },
  { id: "uri", label: "Connection URL", badge: "URL", subtitle: "Paste postgres:// or mysql:// URI" },
];

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

export const DatabaseConnectionModal: React.FC<DatabaseConnectionModalProps> = ({
  isOpen,
  onClose,
  databases = [],
  activeDatabaseId,
  onSelectDatabase,
  onDatabaseConnected,
  onDatabaseDisconnected,
  onTestConnection,
  onConnectDatabase,
  onDisconnectDatabase,
  apiBaseUrl = "/api/databases",
  defaultTab = "connect",
  theme: propTheme,
  unstyled = false,
}) => {
  const { theme: contextTheme } = useTheme();

  const activeTheme: QueryBuilderTheme = useMemo(() => {
    if (propTheme && typeof propTheme === "object" && "colors" in propTheme) {
      return propTheme;
    }
    if (propTheme === "light") return lightTheme;
    if (propTheme === "dark") return darkTheme;
    return contextTheme;
  }, [propTheme, contextTheme]);

  const colors = activeTheme.colors;
  const cssVariables = useMemo(() => themeToCssVariables(activeTheme), [activeTheme]);

  const [activeTab, setActiveTab] = useState<"connect" | "manage">(defaultTab);
  const [engine, setEngine] = useState<DatabaseEngineOption>("postgres");

  const [name, setName] = useState("");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("5432");
  const [database, setDatabase] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [schemaName, setSchemaName] = useState("public");
  const [filePath, setFilePath] = useState("");
  const [connectionUri, setConnectionUri] = useState("");
  const [quickUriInput, setQuickUriInput] = useState("");

  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadFileSize, setUploadFileSize] = useState(0);
  const [uploadBase64, setUploadBase64] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [isTesting, setIsTesting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [testResult, setTestResult] = useState<DatabaseTestResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState<string>("ALL");

  useEffect(() => {
    if (!isOpen) return;
    setActiveTab(defaultTab);
    setTestResult(null);
    setErrorMessage(null);
  }, [isOpen, defaultTab]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  const handleEngineSwitch = (nextEngine: DatabaseEngineOption) => {
    setEngine(nextEngine);
    setTestResult(null);
    setErrorMessage(null);
    if (nextEngine === "postgres" && port === "3306") {
      setPort("5432");
    } else if (nextEngine === "mysql" && port === "5432") {
      setPort("3306");
    }
  };

  const handleApplyUri = useCallback((uriText: string) => {
    const parsed = parseDatabaseUri(uriText);
    if (!parsed) {
      setErrorMessage(
        "Could not parse connection URL. Expected format: postgresql://user:pass@host:5432/dbname or sqlite:///path/to/db.sqlite",
      );
      return;
    }
    setErrorMessage(null);
    setTestResult(null);
    setEngine(parsed.dialect);
    if (parsed.dialect === "postgres" || parsed.dialect === "mysql") {
      setHost(parsed.host!);
      setPort(String(parsed.port));
      setDatabase(parsed.database!);
      setUser(parsed.user || "");
      setPassword(parsed.password || "");
      setSchemaName(parsed.schema_name || "public");
    } else {
      setFilePath(parsed.file_path!);
    }
  }, []);

  const handleFilePicked = useCallback(
    async (file?: File) => {
      if (!file) return;
      setErrorMessage(null);
      setTestResult(null);
      setUploadFileName(file.name);
      setUploadFileSize(file.size);
      if (!name.trim()) {
        const stem = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
        setName(stem.charAt(0).toUpperCase() + stem.slice(1));
      }
      const buf = await file.arrayBuffer();
      setUploadBase64(arrayBufferToBase64(buf));
    },
    [name],
  );

  const buildConfigPayload = useCallback((): DatabaseConnectionConfig | null => {
    setErrorMessage(null);

    if (engine === "upload") {
      if (!uploadFileName || !uploadBase64) {
        setErrorMessage("Please select a .sqlite, .db, .csv, or .json file to upload.");
        return null;
      }
      return {
        name: name.trim(),
        dialect: "sqlite",
        filename: uploadFileName,
        content_base64: uploadBase64,
      };
    }

    if (engine === "uri") {
      const trimmedUri = connectionUri.trim();
      if (!trimmedUri) {
        setErrorMessage("Please paste a database connection URL.");
        return null;
      }
      const parsed = parseDatabaseUri(trimmedUri);
      if (!parsed) {
        setErrorMessage(
          "Could not parse connection URL. Expected format: postgresql://user:pass@host:5432/dbname or sqlite:///path/to/db.sqlite",
        );
        return null;
      }
      return {
        name: name.trim() || parsed.database!,
        dialect: parsed.dialect,
        connection_uri: trimmedUri,
        host: parsed.host,
        port: parsed.port,
        database: parsed.database,
        user: parsed.user,
        password: parsed.password,
        schema_name: parsed.schema_name,
        file_path: parsed.file_path,
      };
    }

    if (engine === "sqlite" || engine === "duckdb") {
      const trimmedPath = filePath.trim();
      if (!trimmedPath) {
        setErrorMessage(
          `Please enter a ${engine === "sqlite" ? "SQLite" : "DuckDB"} database file path (or :memory:).`,
        );
        return null;
      }
      const fileBase = trimmedPath.split("/").pop()!;
      return {
        name: name.trim() || `${engine.toUpperCase()} — ${fileBase}`,
        dialect: engine,
        file_path: trimmedPath,
        database: trimmedPath,
      };
    }

    const trimmedHost = host.trim();
    const trimmedDb = database.trim();
    if (!trimmedDb) {
      setErrorMessage("Please enter the database name.");
      return null;
    }
    const parsedPort = Number.parseInt(port, 10);

    return {
      name: name.trim() || trimmedDb,
      dialect: engine,
      host: trimmedHost,
      port: parsedPort,
      database: trimmedDb,
      user: user.trim() || undefined,
      password: password || undefined,
      schema_name: engine === "postgres" ? schemaName.trim() : trimmedDb,
    };
  }, [
    engine,
    name,
    host,
    port,
    database,
    user,
    password,
    schemaName,
    filePath,
    connectionUri,
    uploadFileName,
    uploadBase64,
  ]);

  const handleTest = async () => {
    const payload = buildConfigPayload();
    if (!payload) return;

    if (engine === "upload") {
      setTestResult({
        ok: true,
        status: "ready",
        dialect: "sqlite",
        table_count: 1,
        foreign_key_count: 0,
        message: `File "${uploadFileName}" (${Math.max(1, Math.round(uploadFileSize / 1024))} KB) is ready to import and connect.`,
      });
      return;
    }

    setIsTesting(true);
    setTestResult(null);
    setErrorMessage(null);
    try {
      if (onTestConnection) {
        const res = await onTestConnection(payload);
        setTestResult(res);
        if (!res.ok) {
          setErrorMessage(res.detail || "Connection test failed.");
        }
      } else {
        const res = await fetch(`${apiBaseUrl}/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok || data.ok === false) {
          setErrorMessage(data.detail || `Connection failed (HTTP ${res.status})`);
        } else {
          setTestResult(data as DatabaseTestResult);
        }
      }
    } catch (err) {
      setErrorMessage((err as Error).message);
    } finally {
      setIsTesting(false);
    }
  };

  const handleConnect = async () => {
    const payload = buildConfigPayload();
    if (!payload) return;

    setIsConnecting(true);
    setErrorMessage(null);
    try {
      let connectedDb: DatabaseConnectionInfo;
      let connectedSchema: SchemaSnapshot | undefined;

      if (onConnectDatabase) {
        const result = await onConnectDatabase(payload);
        connectedDb = result.database;
        connectedSchema = result.schema;
      } else {
        const endpoint = engine === "upload" ? `${apiBaseUrl}/upload` : `${apiBaseUrl}/connect`;
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok || data.ok === false) {
          throw new Error(data.detail || `Failed to connect database (HTTP ${res.status})`);
        }
        connectedDb = data.database as DatabaseConnectionInfo;
        connectedSchema = data.schema as SchemaSnapshot | undefined;
      }

      if (onDatabaseConnected) {
        onDatabaseConnected(connectedDb, connectedSchema);
      } else if (onSelectDatabase) {
        onSelectDatabase(connectedDb.id);
      }
      onClose();
    } catch (err) {
      setErrorMessage((err as Error).message);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async (dbId: string) => {
    setErrorMessage(null);
    try {
      if (onDisconnectDatabase) {
        await onDisconnectDatabase(dbId);
      } else {
        const res = await fetch(`${apiBaseUrl}/${encodeURIComponent(dbId)}`, {
          method: "DELETE",
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || `Failed to disconnect database (HTTP ${res.status})`);
        }
      }
      if (onDatabaseDisconnected) {
        onDatabaseDisconnected(dbId);
      }
    } catch (err) {
      setErrorMessage((err as Error).message);
    }
  };

  const filteredDatabases = useMemo(() => {
    return databases.filter((db) => {
      if (groupFilter === "CUSTOM" && !db.is_custom) return false;
      if (groupFilter === "POSTGRES" && db.dialect !== "postgres") return false;
      if (groupFilter === "MYSQL" && db.dialect !== "mysql") return false;
      if (groupFilter === "SQLITE" && db.dialect !== "sqlite" && db.dialect !== "duckdb") {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase();
        return (
          db.name.toLowerCase().includes(q) ||
          db.id.toLowerCase().includes(q) ||
          (db.description || "").toLowerCase().includes(q) ||
          db.dialect.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [databases, groupFilter, searchQuery]);

  const parsedPreview = useMemo(() => {
    if (engine !== "uri" || !connectionUri.trim()) return null;
    return parseDatabaseUri(connectionUri);
  }, [engine, connectionUri]);

  if (!isOpen) return null;

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: "0.78rem",
    fontWeight: 600,
    color: colors.textSecondary,
    marginBottom: "4px",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    boxSizing: "border-box",
    padding: "8px 11px",
    borderRadius: "6px",
    border: `1px solid ${colors.border}`,
    backgroundColor: colors.background,
    color: colors.text,
    fontSize: "0.875rem",
    outline: "none",
  };

  return (
    <div
      role="presentation"
      data-testid="database-connection-modal-backdrop"
      data-qb="database-connection-backdrop"
      onClick={onClose}
      style={
        unstyled
          ? undefined
          : {
              position: "fixed",
              inset: 0,
              zIndex: 9999,
              backgroundColor: "rgba(2, 6, 23, 0.72)",
              backdropFilter: "blur(5px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "20px",
            }
      }
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Connect or Switch Database"
        data-testid="database-connection-modal"
        data-qb="database-connection-modal"
        onClick={(e) => e.stopPropagation()}
        style={
          unstyled
            ? undefined
            : {
                ...(cssVariables as React.CSSProperties),
                backgroundColor: colors.surface,
                color: colors.text,
                border: `1px solid ${colors.border}`,
                borderRadius: "12px",
                width: "100%",
                maxWidth: "680px",
                maxHeight: "88vh",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
                boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.55)",
              }
        }
      >
        {/* Header */}
        <div
          style={{
            padding: "14px 20px",
            borderBottom: `1px solid ${colors.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            backgroundColor: colors.surfaceHover,
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: colors.text }}>
              Database Connections
            </h2>
            <p style={{ margin: "2px 0 0 0", fontSize: "0.8rem", color: colors.textSecondary }}>
              Connect to PostgreSQL, MySQL, SQLite, DuckDB, or upload a data file directly from your browser.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Database Connections Modal"
            data-testid="btn-close-connect-modal"
            style={{
              background: "transparent",
              border: "none",
              color: colors.textSecondary,
              fontSize: "1.15rem",
              cursor: "pointer",
              padding: "4px 8px",
              borderRadius: "6px",
            }}
          >
            ✕
          </button>
        </div>

        {/* Mode Switcher Tabs */}
        <div
          style={{
            display: "flex",
            gap: "8px",
            padding: "10px 20px",
            borderBottom: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
          }}
        >
          <button
            type="button"
            data-testid="tab-connect-new"
            onClick={() => {
              setActiveTab("connect");
              setErrorMessage(null);
            }}
            style={{
              padding: "6px 14px",
              borderRadius: "6px",
              border: activeTab === "connect" ? `1px solid ${colors.primary}` : `1px solid ${colors.border}`,
              backgroundColor: activeTab === "connect" ? "rgba(56, 189, 248, 0.14)" : "transparent",
              color: activeTab === "connect" ? colors.primary : colors.textSecondary,
              fontSize: "0.84rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            + Connect New Database
          </button>
          {databases.length > 0 && (
            <button
              type="button"
              data-testid="tab-manage-dbs"
              onClick={() => {
                setActiveTab("manage");
                setErrorMessage(null);
              }}
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                border: activeTab === "manage" ? `1px solid ${colors.primary}` : `1px solid ${colors.border}`,
                backgroundColor: activeTab === "manage" ? "rgba(56, 189, 248, 0.14)" : "transparent",
                color: activeTab === "manage" ? colors.primary : colors.textSecondary,
                fontSize: "0.84rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Connected Databases ({databases.length})
            </button>
          )}
        </div>

        {/* Modal Body */}
        <div
          style={{
            padding: "18px 20px",
            overflowY: "auto",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            gap: "16px",
          }}
        >
          {activeTab === "connect" ? (
            <>
              {/* Step 1: Engine Picker Cards */}
              <div>
                <span style={labelStyle}>1. Select Database Type</span>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))",
                    gap: "8px",
                    marginTop: "6px",
                  }}
                >
                  {ENGINE_OPTIONS.map((opt) => {
                    const selected = engine === opt.id;
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        data-testid={`engine-option-${opt.id}`}
                        onClick={() => handleEngineSwitch(opt.id)}
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "flex-start",
                          gap: "3px",
                          padding: "10px 12px",
                          borderRadius: "8px",
                          border: selected ? `1.5px solid ${colors.primary}` : `1px solid ${colors.border}`,
                          backgroundColor: selected ? "rgba(56, 189, 248, 0.12)" : colors.surfaceHover,
                          color: colors.text,
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            width: "100%",
                          }}
                        >
                          <span style={{ fontSize: "0.86rem", fontWeight: 700 }}>{opt.label}</span>
                          <span
                            style={{
                              fontSize: "0.68rem",
                              fontWeight: 700,
                              padding: "1px 6px",
                              borderRadius: "4px",
                              backgroundColor: "rgba(56, 189, 248, 0.16)",
                              color: colors.primary,
                            }}
                          >
                            {opt.badge}
                          </span>
                        </div>
                        <span style={{ fontSize: "0.74rem", color: colors.textSecondary }}>{opt.subtitle}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Step 2: Connection Form */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "12px",
                  padding: "14px",
                  borderRadius: "8px",
                  border: `1px solid ${colors.border}`,
                  backgroundColor: colors.surfaceHover,
                }}
              >
                <div>
                  <label htmlFor="qb-db-conn-name" style={labelStyle}>
                    Display Name (optional)
                  </label>
                  <input
                    id="qb-db-conn-name"
                    data-testid="input-db-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Analytics Production, Staging DB, Customer Data..."
                    style={inputStyle}
                  />
                </div>

                {(engine === "postgres" || engine === "mysql") && (
                  <>
                    <div>
                      <label htmlFor="qb-db-quick-uri" style={labelStyle}>
                        Have a Connection URL? Paste to auto-fill (optional)
                      </label>
                      <div style={{ display: "flex", gap: "8px" }}>
                        <input
                          id="qb-db-quick-uri"
                          data-testid="input-db-uri-autofill"
                          type="text"
                          value={quickUriInput}
                          onChange={(e) => {
                            const val = e.target.value;
                            setQuickUriInput(val);
                            if (val.includes("://") && val.split("/").length >= 4) {
                              handleApplyUri(val);
                            }
                          }}
                          placeholder="postgresql://user:password@localhost:5432/dbname"
                          style={{ ...inputStyle, flex: 1 }}
                        />
                        {quickUriInput.trim() && (
                          <button
                            type="button"
                            data-testid="btn-parse-uri"
                            onClick={() => handleApplyUri(quickUriInput)}
                            style={{
                              padding: "6px 12px",
                              borderRadius: "6px",
                              border: `1px solid ${colors.border}`,
                              backgroundColor: colors.surface,
                              color: colors.text,
                              fontSize: "0.78rem",
                              fontWeight: 600,
                              cursor: "pointer",
                              whiteSpace: "nowrap",
                            }}
                          >
                            Auto-Fill
                          </button>
                        )}
                      </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "10px" }}>
                      <div>
                        <label htmlFor="qb-db-host" style={labelStyle}>
                          Host *
                        </label>
                        <input
                          id="qb-db-host"
                          data-testid="input-db-host"
                          type="text"
                          value={host}
                          onChange={(e) => setHost(e.target.value)}
                          placeholder="localhost or db.example.com"
                          style={inputStyle}
                        />
                      </div>
                      <div>
                        <label htmlFor="qb-db-port" style={labelStyle}>
                          Port *
                        </label>
                        <input
                          id="qb-db-port"
                          data-testid="input-db-port"
                          type="number"
                          value={port}
                          onChange={(e) => setPort(e.target.value)}
                          placeholder="5432"
                          style={inputStyle}
                        />
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: engine === "postgres" ? "1.5fr 1fr" : "1fr",
                        gap: "10px",
                      }}
                    >
                      <div>
                        <label htmlFor="qb-db-database" style={labelStyle}>
                          Database Name *
                        </label>
                        <input
                          id="qb-db-database"
                          data-testid="input-db-database"
                          type="text"
                          value={database}
                          onChange={(e) => setDatabase(e.target.value)}
                          placeholder="analytics_db or my_database"
                          style={inputStyle}
                        />
                      </div>
                      {engine === "postgres" && (
                        <div>
                          <label htmlFor="qb-db-schema" style={labelStyle}>
                            Schema
                          </label>
                          <input
                            id="qb-db-schema"
                            data-testid="input-db-schema"
                            type="text"
                            value={schemaName}
                            onChange={(e) => setSchemaName(e.target.value)}
                            placeholder="public"
                            style={inputStyle}
                          />
                        </div>
                      )}
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <div>
                        <label htmlFor="qb-db-user" style={labelStyle}>
                          Username
                        </label>
                        <input
                          id="qb-db-user"
                          data-testid="input-db-user"
                          type="text"
                          value={user}
                          onChange={(e) => setUser(e.target.value)}
                          placeholder="postgres"
                          style={inputStyle}
                        />
                      </div>
                      <div>
                        <label htmlFor="qb-db-password" style={labelStyle}>
                          Password
                        </label>
                        <div style={{ display: "flex", gap: "6px" }}>
                          <input
                            id="qb-db-password"
                            data-testid="input-db-password"
                            type={showPassword ? "text" : "password"}
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="••••••••"
                            style={{ ...inputStyle, flex: 1 }}
                          />
                          <button
                            type="button"
                            onClick={() => setShowPassword((prev) => !prev)}
                            style={{
                              padding: "0 10px",
                              borderRadius: "6px",
                              border: `1px solid ${colors.border}`,
                              backgroundColor: colors.surface,
                              color: colors.textSecondary,
                              fontSize: "0.75rem",
                              cursor: "pointer",
                            }}
                          >
                            {showPassword ? "Hide" : "Show"}
                          </button>
                        </div>
                      </div>
                    </div>
                  </>
                )}

                {(engine === "sqlite" || engine === "duckdb") && (
                  <div>
                    <label htmlFor="qb-db-filepath" style={labelStyle}>
                      Database File Path *
                    </label>
                    <input
                      id="qb-db-filepath"
                      data-testid="input-db-filepath"
                      type="text"
                      value={filePath}
                      onChange={(e) => setFilePath(e.target.value)}
                      placeholder="/path/to/database.db or :memory:"
                      style={inputStyle}
                    />
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        flexWrap: "wrap",
                        gap: "8px",
                        marginTop: "8px",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setFilePath(":memory:")}
                        style={{
                          padding: "3px 8px",
                          borderRadius: "999px",
                          border: `1px solid ${colors.border}`,
                          backgroundColor: colors.surface,
                          color: colors.textSecondary,
                          fontSize: "0.73rem",
                          cursor: "pointer",
                        }}
                      >
                        Use :memory:
                      </button>
                      <button
                        type="button"
                        onClick={() => handleEngineSwitch("upload")}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: colors.primary,
                          fontSize: "0.78rem",
                          fontWeight: 600,
                          cursor: "pointer",
                          padding: 0,
                        }}
                      >
                        Or upload a file from your computer →
                      </button>
                    </div>
                  </div>
                )}

                {engine === "upload" && (
                  <div>
                    <span style={labelStyle}>
                      Upload SQLite (.db, .sqlite, .sqlite3), SQL Dump (.sql), CSV/TSV (.csv, .tsv), or JSON (.json, .jsonl) File *
                    </span>
                    <div
                      data-testid="db-upload-dropzone"
                      onDragOver={(e) => {
                        e.preventDefault();
                        setIsDragOver(true);
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        setIsDragOver(false);
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        setIsDragOver(false);
                        void handleFilePicked(e.dataTransfer.files?.[0]);
                      }}
                      onClick={() => fileInputRef.current?.click()}
                      style={{
                        border: `2px dashed ${isDragOver ? colors.primary : colors.border}`,
                        borderRadius: "8px",
                        padding: "22px 16px",
                        textAlign: "center",
                        backgroundColor: colors.surface,
                        cursor: "pointer",
                      }}
                    >
                      <input
                        ref={fileInputRef}
                        data-testid="db-upload-input"
                        type="file"
                        accept=".sqlite,.sqlite3,.db,.sql,.csv,.tsv,.json,.jsonl,.ndjson"
                        style={{ display: "none" }}
                        onChange={(e) => {
                          void handleFilePicked(e.target.files?.[0]);
                        }}
                      />
                      <div style={{ fontSize: "0.9rem", fontWeight: 600, color: colors.text }}>
                        {uploadFileName
                          ? `Selected: ${uploadFileName} (${Math.max(1, Math.round(uploadFileSize / 1024))} KB)`
                          : "Drop a database or data file here, or click to browse"}
                      </div>
                      <div style={{ fontSize: "0.76rem", color: colors.textSecondary, marginTop: "4px" }}>
                        SQLite files connect directly in read-only mode. SQL scripts, CSV, TSV, JSON & JSONL files are automatically converted into queryable tables.
                      </div>
                    </div>
                  </div>
                )}

                {engine === "uri" && (
                  <div>
                    <label htmlFor="qb-db-uri" style={labelStyle}>
                      Connection URL / URI *
                    </label>
                    <input
                      id="qb-db-uri"
                      data-testid="input-db-uri"
                      type="text"
                      value={connectionUri}
                      onChange={(e) => setConnectionUri(e.target.value)}
                      placeholder="postgresql://user:password@host:5432/database?schema=public"
                      style={inputStyle}
                    />
                    {parsedPreview && (
                      <div
                        data-testid="uri-parsed-preview"
                        style={{
                          marginTop: "8px",
                          padding: "8px 10px",
                          borderRadius: "6px",
                          backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          fontSize: "0.78rem",
                          color: colors.textSecondary,
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "10px",
                        }}
                      >
                        <span>
                          <strong style={{ color: colors.text }}>Engine:</strong>{" "}
                          {parsedPreview.dialect.toUpperCase()}
                        </span>
                        {parsedPreview.host && (
                          <span>
                            <strong style={{ color: colors.text }}>Host:</strong>{" "}
                            {parsedPreview.host}:{parsedPreview.port}
                          </span>
                        )}
                        {parsedPreview.database && (
                          <span>
                            <strong style={{ color: colors.text }}>Database:</strong>{" "}
                            {parsedPreview.database}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Feedback Banner */}
              {errorMessage && (
                <div
                  role="alert"
                  data-testid="db-connection-error"
                  style={{
                    padding: "10px 14px",
                    borderRadius: "8px",
                    border: "1px solid rgba(239, 68, 68, 0.45)",
                    backgroundColor: "rgba(239, 68, 68, 0.12)",
                    color: colors.error,
                    fontSize: "0.84rem",
                    fontWeight: 500,
                  }}
                >
                  {errorMessage}
                </div>
              )}

              {testResult && testResult.ok && (
                <div
                  role="status"
                  data-testid="db-connection-success"
                  style={{
                    padding: "10px 14px",
                    borderRadius: "8px",
                    border: "1px solid var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.45))",
                    backgroundColor: "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.12))",
                    color: "var(--qb-color-confirmed-text, #047857)",
                    fontSize: "0.84rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                  }}
                >
                  <div style={{ fontWeight: 700 }}>
                    ✓{" "}
                    {testResult.message ||
                      `Connected! Found ${testResult.table_count} tables and ${testResult.foreign_key_count} relationships`}
                  </div>
                  {testResult.sample_tables && testResult.sample_tables.length > 0 && (
                    <div style={{ fontSize: "0.76rem", opacity: 0.9 }}>
                      Tables preview: {testResult.sample_tables.slice(0, 8).join(", ")}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            /* Manage / Switch Connected Databases Tab */
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              {errorMessage && (
                <div
                  role="alert"
                  data-testid="db-connection-error"
                  style={{
                    padding: "10px 14px",
                    borderRadius: "8px",
                    border: "1px solid rgba(239, 68, 68, 0.45)",
                    backgroundColor: "rgba(239, 68, 68, 0.12)",
                    color: colors.error,
                    fontSize: "0.84rem",
                    fontWeight: 500,
                  }}
                >
                  {errorMessage}
                </div>
              )}
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
                <input
                  type="text"
                  data-testid="input-search-dbs"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search connected databases..."
                  style={{ ...inputStyle, flex: 1, minWidth: "180px" }}
                />
                <div style={{ display: "flex", gap: "4px" }}>
                  {[
                    { id: "ALL", label: "All" },
                    { id: "CUSTOM", label: "Custom" },
                    { id: "POSTGRES", label: "Postgres" },
                    { id: "MYSQL", label: "MySQL" },
                    { id: "SQLITE", label: "SQLite / DuckDB" },
                  ].map((g) => {
                    const active = groupFilter === g.id;
                    return (
                      <button
                        key={g.id}
                        type="button"
                        data-testid={`filter-group-${g.id}`}
                        onClick={() => setGroupFilter(g.id)}
                        style={{
                          padding: "6px 10px",
                          borderRadius: "6px",
                          fontSize: "0.76rem",
                          fontWeight: active ? 700 : 500,
                          border: active ? `1px solid ${colors.primary}` : `1px solid ${colors.border}`,
                          backgroundColor: active ? "rgba(56, 189, 248, 0.14)" : colors.surfaceHover,
                          color: active ? colors.primary : colors.textSecondary,
                          cursor: "pointer",
                        }}
                      >
                        {g.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                  maxHeight: "360px",
                  overflowY: "auto",
                }}
              >
                {filteredDatabases.length === 0 ? (
                  <div
                    data-testid="manage-db-empty"
                    style={{
                      padding: "20px",
                      textAlign: "center",
                      borderRadius: "8px",
                      border: `1px dashed ${colors.border}`,
                      color: colors.textSecondary,
                      fontSize: "0.84rem",
                    }}
                  >
                    No connected databases match your search or filter.
                  </div>
                ) : (
                  filteredDatabases.map((db) => {
                  const isCurrent = db.id === activeDatabaseId;
                  const isAvailable = db.available !== false;
                  return (
                    <div
                      key={db.id}
                      data-testid={`manage-db-row-${db.id}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "12px",
                        padding: "10px 14px",
                        borderRadius: "8px",
                        border: isCurrent ? `1.5px solid ${colors.primary}` : `1px solid ${colors.border}`,
                        backgroundColor: colors.surfaceHover,
                      }}
                    >
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                          <span style={{ fontWeight: 700, fontSize: "0.9rem", color: colors.text }}>
                            {db.icon ? `${db.icon} ` : ""}
                            {db.name}
                          </span>
                          <span
                            style={{
                              fontSize: "0.68rem",
                              fontWeight: 700,
                              padding: "1px 6px",
                              borderRadius: "4px",
                              backgroundColor: colors.surface,
                              color: colors.textSecondary,
                              textTransform: "uppercase",
                            }}
                          >
                            {db.dialect}
                          </span>
                          {db.is_custom && (
                            <span
                              style={{
                                fontSize: "0.68rem",
                                fontWeight: 700,
                                padding: "1px 6px",
                                borderRadius: "4px",
                                backgroundColor: "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.16))",
                                color: "var(--qb-color-confirmed-text, #047857)",
                              }}
                            >
                              Custom
                            </span>
                          )}
                          {typeof db.table_count === "number" && (
                            <span style={{ fontSize: "0.75rem", color: colors.textSecondary }}>
                              {db.table_count} tables
                            </span>
                          )}
                        </div>
                        {db.description && (
                          <div
                            style={{
                              fontSize: "0.76rem",
                              color: colors.textSecondary,
                              marginTop: "2px",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {db.description}
                          </div>
                        )}
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
                        {isCurrent ? (
                          <span
                            style={{
                              padding: "5px 10px",
                              borderRadius: "6px",
                              fontSize: "0.78rem",
                              fontWeight: 700,
                              backgroundColor: "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.16))",
                              color: "var(--qb-color-confirmed-text, #047857)",
                            }}
                          >
                            ✓ Active
                          </span>
                        ) : (
                          <button
                            type="button"
                            disabled={!isAvailable}
                            data-testid={`btn-switch-db-${db.id}`}
                            onClick={() => {
                              if (onSelectDatabase) {
                                onSelectDatabase(db.id);
                              }
                              onClose();
                            }}
                            style={{
                              padding: "6px 12px",
                              borderRadius: "6px",
                              border: `1px solid ${colors.border}`,
                              backgroundColor: colors.surface,
                              color: colors.text,
                              fontSize: "0.8rem",
                              fontWeight: 600,
                              cursor: isAvailable ? "pointer" : "not-allowed",
                              opacity: isAvailable ? 1 : 0.5,
                            }}
                          >
                            Switch
                          </button>
                        )}
                        {db.is_custom && (
                          <button
                            type="button"
                            data-testid={`btn-disconnect-db-${db.id}`}
                            onClick={() => void handleDisconnect(db.id)}
                            title={`Disconnect ${db.name}`}
                            style={{
                              padding: "6px 10px",
                              borderRadius: "6px",
                              border: "1px solid rgba(239, 68, 68, 0.35)",
                              backgroundColor: "transparent",
                              color: colors.error,
                              fontSize: "0.78rem",
                              fontWeight: 600,
                              cursor: "pointer",
                            }}
                          >
                            Disconnect
                          </button>
                        )}
                      </div>
                    </div>
                  );
                  })
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "12px 20px",
            borderTop: `1px solid ${colors.border}`,
            backgroundColor: colors.surfaceHover,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "10px",
          }}
        >
          <span style={{ fontSize: "0.76rem", color: colors.textSecondary }}>
            🔒 Connections are enforced as read-only sessions.
          </span>

          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: "7px 14px",
                borderRadius: "6px",
                border: `1px solid ${colors.border}`,
                backgroundColor: "transparent",
                color: colors.textSecondary,
                fontSize: "0.84rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>

            {activeTab === "connect" && (
              <>
                <button
                  type="button"
                  data-testid="btn-test-db-connection"
                  disabled={isTesting || isConnecting}
                  onClick={() => void handleTest()}
                  style={{
                    padding: "7px 14px",
                    borderRadius: "6px",
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.surface,
                    color: colors.text,
                    fontSize: "0.84rem",
                    fontWeight: 600,
                    cursor: isTesting || isConnecting ? "not-allowed" : "pointer",
                  }}
                >
                  {isTesting ? "Testing..." : "Test Connection"}
                </button>
                <button
                  type="button"
                  data-testid="btn-save-db-connection"
                  disabled={isConnecting || isTesting}
                  onClick={() => void handleConnect()}
                  style={{
                    padding: "7px 16px",
                    borderRadius: "6px",
                    border: "none",
                    backgroundColor: colors.primary,
                    color: "#ffffff",
                    fontSize: "0.84rem",
                    fontWeight: 700,
                    cursor: isConnecting || isTesting ? "not-allowed" : "pointer",
                  }}
                >
                  {isConnecting ? "Connecting..." : "Connect Database"}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
