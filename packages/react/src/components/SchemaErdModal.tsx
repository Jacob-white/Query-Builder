import React, { useEffect, useState, useRef, useMemo } from "react";
import type { SchemaSnapshot, VisualJoin } from "../types";
import { findJoinPath, findBestJoinCondition } from "../utils/joinUtils";

export interface SchemaErdModalProps {
  isOpen: boolean;
  onClose: () => void;
  schema?: SchemaSnapshot | null;
  onSelectTable?: (tableName: string) => void;
  onAddJoins?: (joins: VisualJoin[]) => void;
}

export const SchemaErdModal: React.FC<SchemaErdModalProps> = ({
  isOpen,
  onClose,
  schema,
  onSelectTable,
  onAddJoins,
}) => {
  const [searchQuery, setSearchQuery] = useState("");
  const [bridgeSource, setBridgeSource] = useState("");
  const [bridgeTarget, setBridgeTarget] = useState("");
  const [bridgePath, setBridgePath] = useState<VisualJoin[] | null>(null);
  const [bridgeSearched, setBridgeSearched] = useState(false);

  const modalRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const sourceSelectRef = useRef<HTMLSelectElement | null>(null);
  const targetSelectRef = useRef<HTMLSelectElement | null>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);

  // Focus trap and keyboard handling
  useEffect(() => {
    if (!isOpen) return;

    if (typeof document !== "undefined") {
      previousActiveElementRef.current = document.activeElement as HTMLElement | null;
    }

    const timer = setTimeout(() => {
      searchInputRef.current?.focus();
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      if (e.key === "Tab" && modalRef.current) {
        const focusableElements = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusableElements.length === 0) return;

        const first = focusableElements[0];
        const last = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
    }

    return () => {
      clearTimeout(timer);
      if (typeof window !== "undefined") {
        window.removeEventListener("keydown", handleKeyDown);
      }
      if (previousActiveElementRef.current && typeof previousActiveElementRef.current.focus === "function") {
        previousActiveElementRef.current.focus();
      }
    };
  }, [isOpen, onClose]);

  const tables = useMemo(() => Object.values(schema?.tables || {}), [schema]);
  const foreignKeys = useMemo(() => schema?.foreign_keys || [], [schema]);

  const filteredTables = useMemo(() => {
    if (!searchQuery.trim()) return tables;
    const q = searchQuery.toLowerCase().trim();
    return tables.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.columns || []).some((c) => c.name.toLowerCase().includes(q)),
    );
  }, [tables, searchQuery]);

  const handleFindBridge = () => {
    setBridgeSearched(true);
    const src = sourceSelectRef.current?.value || bridgeSource;
    const tgt = targetSelectRef.current?.value || bridgeTarget;
    if (!src || !tgt || src === tgt) {
      setBridgePath([]);
      return;
    }
    const path = findJoinPath([src], tgt, schema);
    if (path.length === 1) {
      const cond = findBestJoinCondition(src, tgt, schema);
      if (!cond.isFk) {
        setBridgePath([]);
        return;
      }
    }
    setBridgePath(path);
  };

  if (!isOpen) return null;

  return (
    <div
      role="presentation"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(0, 0, 0, 0.75)",
        backdropFilter: "blur(6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="schema-erd-title"
        style={{
          background: "#0f172a",
          border: "1px solid rgba(255, 255, 255, 0.15)",
          borderRadius: "14px",
          width: "90vw",
          maxWidth: "1100px",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7)",
          color: "#f8fafc",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            background: "rgba(30, 41, 59, 0.5)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "1.2rem" }}>🗺️</span>
            <span id="schema-erd-title" style={{ fontWeight: 700, fontSize: "1.1rem" }}>
              Schema Entity Relationship Diagram (ERD)
            </span>
            <span style={{ fontSize: "0.8rem", color: "#64748b", marginLeft: "8px" }}>
              {tables.length} tables · {foreignKeys.length} foreign keys
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close schema ERD modal"
            style={{
              background: "transparent",
              border: "none",
              color: "#94a3b8",
              cursor: "pointer",
              fontSize: "1.2rem",
            }}
          >
            ✕
          </button>
        </div>

        {/* Toolbar: Search and Bridge Discovery */}
        <div
          style={{
            padding: "12px 20px",
            background: "rgba(15, 23, 42, 0.7)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            display: "flex",
            flexDirection: "column",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
            <input
              ref={searchInputRef}
              type="text"
              data-qb="erd-search-input"
              aria-label="Search tables or columns"
              placeholder="Search tables or columns..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                flex: "1 1 240px",
                background: "rgba(30, 41, 59, 0.8)",
                border: "1px solid rgba(255, 255, 255, 0.15)",
                borderRadius: "6px",
                padding: "6px 12px",
                color: "#f8fafc",
                fontSize: "0.82rem",
                outline: "none",
              }}
            />
          </div>

          {/* Bridge Discovery Tool */}
          <div
            data-qb="erd-bridge-tool"
            style={{
              background: "rgba(30, 41, 59, 0.4)",
              border: "1px solid rgba(255, 255, 255, 0.06)",
              borderRadius: "6px",
              padding: "8px 12px",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: "0.78rem", color: "#38bdf8" }}>
              🌉 Foreign Key Bridge Discovery
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
              <select
                ref={sourceSelectRef}
                aria-label="Bridge source table"
                data-qb="erd-bridge-source"
                value={bridgeSource}
                onChange={(e) => setBridgeSource(e.target.value)}
                style={{
                  background: "#1e293b",
                  color: "#cbd5e1",
                  border: "1px solid rgba(255, 255, 255, 0.15)",
                  borderRadius: "4px",
                  padding: "3px 8px",
                  fontSize: "0.75rem",
                }}
              >
                <option value="">Source Table...</option>
                {tables.map((t) => (
                  <option key={t.name} value={t.name}>
                    Table: {t.name}
                  </option>
                ))}
              </select>
              <span style={{ color: "#64748b", fontSize: "0.8rem" }}>➔</span>
              <select
                ref={targetSelectRef}
                aria-label="Bridge target table"
                data-qb="erd-bridge-target"
                value={bridgeTarget}
                onChange={(e) => setBridgeTarget(e.target.value)}
                style={{
                  background: "#1e293b",
                  color: "#cbd5e1",
                  border: "1px solid rgba(255, 255, 255, 0.15)",
                  borderRadius: "4px",
                  padding: "3px 8px",
                  fontSize: "0.75rem",
                }}
              >
                <option value="">Target Table...</option>
                {tables.map((t) => (
                  <option key={t.name} value={t.name}>
                    Table: {t.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                data-qb="erd-bridge-find-btn"
                onClick={handleFindBridge}
                style={{
                  background: "#3b82f6",
                  color: "#ffffff",
                  border: "none",
                  borderRadius: "4px",
                  padding: "3px 10px",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Discover Bridge
              </button>
            </div>

            {bridgePath && bridgePath.length > 0 && (
              <div
                data-qb="erd-bridge-result"
                style={{
                  marginTop: "4px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  flexWrap: "wrap",
                  gap: "6px",
                }}
              >
                <div style={{ fontSize: "0.75rem", color: "#34d399" }}>
                  Path ({bridgePath.length} hop{bridgePath.length > 1 ? "s" : ""}):{" "}
                  {bridgeSource} ➔{" "}
                  {bridgePath.map((j) => `${j.table} (${j.left_col}=${j.right_col})`).join(" ➔ ")}
                </div>
                {onAddJoins && (
                  <button
                    type="button"
                    data-qb="erd-bridge-add-btn"
                    onClick={() => {
                      onAddJoins(bridgePath);
                      onClose();
                    }}
                    style={{
                      background: "#10b981",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "4px",
                      padding: "2px 8px",
                      fontSize: "0.72rem",
                      fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    Add Bridge Joins to Canvas
                  </button>
                )}
              </div>
            )}

            {bridgeSearched && (!bridgePath || bridgePath.length === 0) && (
              <div
                data-qb="erd-bridge-no-path"
                style={{ fontSize: "0.72rem", color: "#f87171", marginTop: "2px" }}
              >
                No bridge path found between selected tables.
              </div>
            )}
          </div>
        </div>

        {/* Content grid */}
        <div
          style={{
            padding: "20px",
            overflowY: "auto",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: "16px",
          }}
        >
          {filteredTables.map((t) => {
            const relatedFks = foreignKeys.filter(
              (fk) => fk.table === t.name || fk.foreign_table === t.name,
            );

            return (
              <div
                key={t.name}
                data-qb="erd-table-card"
                data-qb-table={t.name}
                style={{
                  background: "rgba(30, 41, 59, 0.7)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "8px",
                  overflow: "hidden",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div
                  style={{
                    padding: "10px 12px",
                    background: "rgba(15, 23, 42, 0.8)",
                    borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span style={{ fontWeight: 600, fontSize: "0.85rem", color: "#38bdf8" }}>
                    {t.name}
                  </span>
                  {onSelectTable && (
                    <button
                      type="button"
                      onClick={() => {
                        onSelectTable(t.name);
                        onClose();
                      }}
                      aria-label={`Select table ${t.name}`}
                      style={{
                        background: "rgba(56, 189, 248, 0.15)",
                        color: "#38bdf8",
                        border: "1px solid rgba(56, 189, 248, 0.3)",
                        borderRadius: "4px",
                        padding: "2px 8px",
                        fontSize: "0.7rem",
                        cursor: "pointer",
                      }}
                    >
                      Use Table
                    </button>
                  )}
                </div>

                <div style={{ maxHeight: "180px", overflowY: "auto", padding: "6px 0" }}>
                  {(t.columns || []).map((c) => (
                    <div
                      key={c.name}
                      style={{
                        padding: "4px 12px",
                        fontSize: "0.75rem",
                        display: "flex",
                        justifyContent: "space-between",
                        color: c.is_primary ? "#fbbf24" : "#cbd5e1",
                      }}
                    >
                      <span>
                        {c.name} {c.is_primary ? "🔑" : ""}
                      </span>
                      <span style={{ color: "#64748b", fontSize: "0.7rem" }}>
                        {c.data_type}
                      </span>
                    </div>
                  ))}
                </div>

                {relatedFks.length > 0 && (
                  <div
                    style={{
                      padding: "6px 12px",
                      background: "rgba(15, 23, 42, 0.4)",
                      borderTop: "1px solid rgba(255, 255, 255, 0.05)",
                      fontSize: "0.7rem",
                      color: "#94a3b8",
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: "2px" }}>
                      🔗 {relatedFks.length} relationship{relatedFks.length > 1 ? "s" : ""}
                    </div>
                    <div
                      data-qb="erd-relationship-list"
                      style={{ display: "flex", flexDirection: "column", gap: "2px" }}
                    >
                      {relatedFks.map((fk, idx) => (
                        <div
                          key={idx}
                          data-qb="erd-relationship-item"
                          style={{ fontSize: "0.68rem", color: "#38bdf8" }}
                        >
                          {fk.table}.{fk.column} ➔ {fk.foreign_table}.{fk.foreign_column} (FK)
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
