import React, { useEffect } from "react";
import type { SchemaSnapshot } from "../types";

export interface SchemaErdModalProps {
  isOpen: boolean;
  onClose: () => void;
  schema?: SchemaSnapshot | null;
  onSelectTable?: (tableName: string) => void;
}

export const SchemaErdModal: React.FC<SchemaErdModalProps> = ({
  isOpen,
  onClose,
  schema,
  onSelectTable,
}) => {
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

  if (!isOpen) return null;

  const tables = Object.values(schema?.tables || {});
  const foreignKeys = schema?.foreign_keys || [];

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
          {tables.map((t) => {
            const relatedFks = foreignKeys.filter(
              (fk) => fk.table === t.name || fk.foreign_table === t.name,
            );

            return (
              <div
                key={t.name}
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
                  {t.columns.map((c) => (
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
                    🔗 {relatedFks.length} relationship{relatedFks.length > 1 ? "s" : ""}
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
