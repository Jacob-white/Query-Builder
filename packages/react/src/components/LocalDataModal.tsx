/**
 * Local Data & File Intake Modal Component.
 * =========================================
 * Allows users to drag-and-drop CSV, TSV, JSON, and Parquet files directly
 * into the in-browser DuckDB/OLAP engine, previewing columns, row count,
 * and staging tables for instant zero-backend querying.
 */

import React, { useState, useRef, useCallback } from "react";
import { useClientOlap } from "../hooks/useClientOlap";
import type { DuckDBTableMeta } from "../types";

export interface LocalDataModalProps {
  isOpen: boolean;
  onClose: () => void;
  onTableSelected?: (tableName: string) => void;
  unstyled?: boolean;
}

export const LocalDataModal: React.FC<LocalDataModalProps> = ({
  isOpen,
  onClose,
  onTableSelected,
  unstyled = false,
}) => {
  const { tables, activeTable, isLoading, error, ingestFile, dropTable, clear, setActiveTable } =
    useClientOlap();

  const [dragOver, setDragOver] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const processFile = useCallback(
    async (file: File) => {
      setSuccessMessage(null);
      try {
        const meta = await ingestFile(file);
        setSuccessMessage(`Successfully loaded '${meta.name}' (${meta.rowCount} rows, ${meta.columns.length} columns)`);
        if (onTableSelected) {
          onTableSelected(meta.name);
        }
      } catch {
        // Error captured by hook
      }
    },
    [ingestFile, onTableSelected],
  );

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const droppedFiles = e.dataTransfer.files;
      if (droppedFiles && droppedFiles.length > 0) {
        await processFile(droppedFiles[0]);
      }
    },
    [processFile],
  );

  const handleFileInputChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        await processFile(files[0]);
      }
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    },
    [processFile],
  );

  if (!isOpen) return null;

  const tableList = Object.values(tables);

  const overlayStyle: React.CSSProperties = unstyled
    ? {}
    : {
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.6)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        padding: "1.5rem",
      };

  const modalStyle: React.CSSProperties = unstyled
    ? {}
    : {
        backgroundColor: "#1e1e2e",
        color: "#cdd6f4",
        border: "1px solid #313244",
        borderRadius: "12px",
        width: "100%",
        maxWidth: "680px",
        maxHeight: "85vh",
        display: "flex",
        flexDirection: "column",
        boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)",
        overflow: "hidden",
      };

  const dropzoneStyle: React.CSSProperties = unstyled
    ? {}
    : {
        border: dragOver ? "2px dashed #89b4fa" : "2px dashed #45475a",
        backgroundColor: dragOver ? "rgba(137, 180, 250, 0.1)" : "#181825",
        borderRadius: "8px",
        padding: "2rem",
        textAlign: "center",
        cursor: "pointer",
        transition: "all 0.2s ease",
        marginBottom: "1.5rem",
      };

  return (
    <div style={overlayStyle} onClick={onClose} data-testid="local-data-modal-overlay">
      <div style={modalStyle} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {/* Header */}
        <div
          style={{
            padding: "1.25rem 1.5rem",
            borderBottom: "1px solid #313244",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 600, color: "#cdd6f4" }}>
              Client-Side OLAP & File Intake
            </h3>
            <p style={{ margin: "0.25rem 0 0 0", fontSize: "0.85rem", color: "#a6adc8" }}>
              Drag-and-drop CSV, TSV, JSON, or Parquet files for sub-10ms in-browser analytics.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              color: "#a6adc8",
              fontSize: "1.5rem",
              cursor: "pointer",
              lineHeight: 1,
            }}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: "1.5rem", overflowY: "auto", flex: 1 }}>
          {/* Dropzone */}
          <div
            style={dropzoneStyle}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            data-testid="local-data-dropzone"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.tab,.json,.jsonl,.ndjson,.parquet,.pq"
              style={{ display: "none" }}
              onChange={handleFileInputChange}
              data-testid="local-data-file-input"
            />
            <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📁</div>
            <div style={{ fontWeight: 600, fontSize: "0.95rem", color: "#cdd6f4" }}>
              {isLoading ? "Ingesting file..." : "Drop file here or click to browse"}
            </div>
            <div style={{ fontSize: "0.8rem", color: "#a6adc8", marginTop: "0.25rem" }}>
              Supports .csv, .tsv, .json, .parquet
            </div>
          </div>

          {/* Success / Error alerts */}
          {error && (
            <div
              style={{
                padding: "0.75rem 1rem",
                backgroundColor: "rgba(243, 139, 168, 0.15)",
                border: "1px solid #f38ba8",
                borderRadius: "6px",
                color: "#f38ba8",
                fontSize: "0.85rem",
                marginBottom: "1rem",
              }}
              data-testid="local-data-error"
            >
              {error.message}
            </div>
          )}

          {successMessage && (
            <div
              style={{
                padding: "0.75rem 1rem",
                backgroundColor: "rgba(166, 227, 161, 0.15)",
                border: "1px solid #a6e3a1",
                borderRadius: "6px",
                color: "#a6e3a1",
                fontSize: "0.85rem",
                marginBottom: "1rem",
              }}
              data-testid="local-data-success"
            >
              {successMessage}
            </div>
          )}

          {/* Ingested Tables */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <h4 style={{ margin: 0, fontSize: "0.95rem", color: "#cdd6f4" }}>
              In-Memory Tables ({tableList.length})
            </h4>
            {tableList.length > 0 && (
              <button
                onClick={() => clear()}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#f38ba8",
                  fontSize: "0.8rem",
                  cursor: "pointer",
                  textDecoration: "underline",
                }}
                data-testid="local-data-clear-all"
              >
                Clear all
              </button>
            )}
          </div>

          {tableList.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "2rem",
                color: "#6c7086",
                fontSize: "0.85rem",
                backgroundColor: "#181825",
                borderRadius: "6px",
              }}
            >
              No client tables loaded. Upload a dataset above to start querying.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {tableList.map((tbl) => {
                const isActive = tbl.name === activeTable;
                return (
                  <div
                    key={tbl.name}
                    style={{
                      padding: "0.75rem 1rem",
                      backgroundColor: isActive ? "rgba(137, 180, 250, 0.15)" : "#181825",
                      border: isActive ? "1px solid #89b4fa" : "1px solid #313244",
                      borderRadius: "6px",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                    data-testid={`local-table-row-${tbl.name}`}
                  >
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <span style={{ fontWeight: 600, color: "#cdd6f4" }}>{tbl.name}</span>
                        <span
                          style={{
                            fontSize: "0.7rem",
                            padding: "0.15rem 0.4rem",
                            borderRadius: "4px",
                            backgroundColor: "#313244",
                            color: "#89b4fa",
                            textTransform: "uppercase",
                          }}
                        >
                          {tbl.sourceType}
                        </span>
                      </div>
                      <div style={{ fontSize: "0.8rem", color: "#a6adc8", marginTop: "0.2rem" }}>
                        {tbl.rowCount.toLocaleString()} rows • {tbl.columns.length} columns
                        {tbl.fileSource ? ` • ${tbl.fileSource}` : ""}
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button
                        onClick={() => {
                          setActiveTable(tbl.name);
                          if (onTableSelected) onTableSelected(tbl.name);
                        }}
                        style={{
                          padding: "0.35rem 0.75rem",
                          backgroundColor: isActive ? "#89b4fa" : "#313244",
                          color: isActive ? "#11111b" : "#cdd6f4",
                          border: "none",
                          borderRadius: "4px",
                          fontSize: "0.8rem",
                          fontWeight: 500,
                          cursor: "pointer",
                        }}
                        data-testid={`local-table-select-${tbl.name}`}
                      >
                        {isActive ? "Active" : "Select"}
                      </button>
                      <button
                        onClick={() => dropTable(tbl.name)}
                        style={{
                          padding: "0.35rem 0.5rem",
                          backgroundColor: "transparent",
                          color: "#f38ba8",
                          border: "1px solid rgba(243, 139, 168, 0.4)",
                          borderRadius: "4px",
                          fontSize: "0.8rem",
                          cursor: "pointer",
                        }}
                        title="Drop table"
                        data-testid={`local-table-drop-${tbl.name}`}
                      >
                        🗑
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "1rem 1.5rem",
            borderTop: "1px solid #313244",
            display: "flex",
            justifyContent: "flex-end",
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: "0.5rem 1.25rem",
              backgroundColor: "#89b4fa",
              color: "#11111b",
              border: "none",
              borderRadius: "6px",
              fontWeight: 600,
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
