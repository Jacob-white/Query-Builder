import React, { useState, useEffect } from "react";
import type {
  VectorSearchSpec,
  HybridSearchSpec,
  TableMeta,
} from "../types";

export interface VectorHybridControlProps {
  vectorSearch?: VectorSearchSpec | null;
  hybridSearch?: HybridSearchSpec | null;
  activeTables: TableMeta[];
  onVectorChange: (vs: VectorSearchSpec | null) => void;
  onHybridChange: (hs: HybridSearchSpec | null) => void;
  unstyled?: boolean;
}

export type SearchMode = "off" | "vector" | "hybrid";

export const VectorHybridControl: React.FC<VectorHybridControlProps> = ({
  vectorSearch,
  hybridSearch,
  activeTables,
  onVectorChange,
  onHybridChange,
  unstyled = false,
}) => {
  const allColumns = activeTables.flatMap((tbl) =>
    tbl.columns.map((c) => ({
      table: tbl.name,
      column: c.name,
      type: c.data_type || (c as any).type || "string",
      label: `${tbl.name}.${c.name}`,
    }))
  );

  const defaultVectorCol =
    allColumns.find(
      (c) =>
        c.column.toLowerCase().includes("embed") ||
        c.column.toLowerCase().includes("vector")
    )?.column ||
    allColumns[0]?.column ||
    "embedding";

  const defaultTextCol =
    allColumns.find(
      (c) =>
        c.type.toLowerCase().includes("text") ||
        c.type.toLowerCase().includes("char") ||
        c.column.toLowerCase().includes("content") ||
        c.column.toLowerCase().includes("title") ||
        c.column.toLowerCase().includes("name")
    )?.column ||
    allColumns[0]?.column ||
    "content";

  const [mode, setMode] = useState<SearchMode>(() => {
    if (hybridSearch) return "hybrid";
    if (vectorSearch) return "vector";
    return "off";
  });

  // Vector state
  const [vectorColumn, setVectorColumn] = useState<string>(
    vectorSearch?.column || hybridSearch?.vector_column || defaultVectorCol
  );
  const [vectorInput, setVectorInput] = useState<string>(() => {
    const v = vectorSearch?.vector || hybridSearch?.vector;
    return v ? JSON.stringify(v) : "[0.12, 0.45, -0.23, 0.88, 0.05]";
  });
  const [metric, setMetric] = useState<
    "cosine" | "euclidean" | "l2" | "dot_product" | "inner_product"
  >(vectorSearch?.metric || hybridSearch?.metric || "cosine");
  const [topK, setTopK] = useState<number>(
    vectorSearch?.top_k || hybridSearch?.top_k || 10
  );
  const [includeDistances, setIncludeDistances] = useState<boolean>(
    vectorSearch?.include_distances ?? true
  );
  const [minScore, setMinScore] = useState<number | undefined>(
    vectorSearch?.min_score
  );

  // Hybrid state
  const [queryText, setQueryText] = useState<string>(
    hybridSearch?.query_text || ""
  );
  const [textColumns, setTextColumns] = useState<string[]>(
    hybridSearch?.text_columns || [defaultTextCol]
  );
  const [fusion, setFusion] = useState<"rrf" | "linear">(
    hybridSearch?.fusion || "rrf"
  );
  const [alpha, setAlpha] = useState<number>(hybridSearch?.alpha ?? 0.5);
  const [rrfK, setRrfK] = useState<number>(hybridSearch?.rrf_k ?? 60);

  // Parse vector string safely
  const parseVector = (str: string): number[] => {
    try {
      const parsed = JSON.parse(str);
      if (Array.isArray(parsed)) {
        return parsed.map((n) => Number(n)).filter((n) => !isNaN(n));
      }
    } catch {
      // Fallback comma-delimited
      return str
        .replace(/[\[\]]/g, "")
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => !isNaN(n));
    }
    return [0.1, 0.2, 0.3];
  };

  // Synchronize when mode or settings change
  const handleModeChange = (newMode: SearchMode) => {
    setMode(newMode);
    if (newMode === "off") {
      onVectorChange(null);
      onHybridChange(null);
    } else if (newMode === "vector") {
      onHybridChange(null);
      const vec = parseVector(vectorInput);
      onVectorChange({
        column: vectorColumn,
        vector: vec.length > 0 ? vec : [0.1, 0.2, 0.3],
        metric,
        top_k: topK,
        include_distances: includeDistances,
        min_score: minScore,
      });
    } else if (newMode === "hybrid") {
      onVectorChange(null);
      const vec = parseVector(vectorInput);
      onHybridChange({
        vector_column: vectorColumn,
        vector: vec.length > 0 ? vec : [0.1, 0.2, 0.3],
        query_text: queryText,
        text_columns: textColumns.length > 0 ? textColumns : [defaultTextCol],
        alpha,
        fusion,
        rrf_k: rrfK,
        top_k: topK,
        metric,
        include_scores: true,
      });
    }
  };

  const notifyChange = () => {
    const vec = parseVector(vectorInput);
    const validVec = vec.length > 0 ? vec : [0.1, 0.2, 0.3];
    if (mode === "vector") {
      onVectorChange({
        column: vectorColumn,
        vector: validVec,
        metric,
        top_k: topK,
        include_distances: includeDistances,
        min_score: minScore,
      });
    } else if (mode === "hybrid") {
      onHybridChange({
        vector_column: vectorColumn,
        vector: validVec,
        query_text: queryText,
        text_columns: textColumns.length > 0 ? textColumns : [defaultTextCol],
        alpha,
        fusion,
        rrf_k: rrfK,
        top_k: topK,
        metric,
        include_scores: true,
      });
    }
  };

  const handleGenerateMockEmbedding = () => {
    const dims = 8;
    const randomVec = Array.from({ length: dims }, () =>
      parseFloat((Math.random() * 2 - 1).toFixed(4))
    );
    // Normalize to unit length
    const norm = Math.sqrt(randomVec.reduce((sum, val) => sum + val * val, 0));
    const normalized = randomVec.map((v) =>
      parseFloat((v / (norm || 1)).toFixed(4))
    );
    const str = JSON.stringify(normalized);
    setVectorInput(str);
    const validVec = normalized;
    if (mode === "vector") {
      onVectorChange({
        column: vectorColumn,
        vector: validVec,
        metric,
        top_k: topK,
        include_distances: includeDistances,
        min_score: minScore,
      });
    } else if (mode === "hybrid") {
      onHybridChange({
        vector_column: vectorColumn,
        vector: validVec,
        query_text: queryText,
        text_columns: textColumns.length > 0 ? textColumns : [defaultTextCol],
        alpha,
        fusion,
        rrf_k: rrfK,
        top_k: topK,
        metric,
        include_scores: true,
      });
    }
  };

  const toggleTextColumn = (col: string) => {
    let next: string[];
    if (textColumns.includes(col)) {
      next = textColumns.filter((c) => c !== col);
      if (next.length === 0) next = [col]; // keep at least 1
    } else {
      next = [...textColumns, col];
    }
    setTextColumns(next);
    if (mode === "hybrid") {
      const vec = parseVector(vectorInput);
      onHybridChange({
        vector_column: vectorColumn,
        vector: vec.length > 0 ? vec : [0.1, 0.2, 0.3],
        query_text: queryText,
        text_columns: next,
        alpha,
        fusion,
        rrf_k: rrfK,
        top_k: topK,
        metric,
        include_scores: true,
      });
    }
  };

  return (
    <div
      data-qb="vector-hybrid-control"
      style={
        unstyled
          ? undefined
          : {
              background: "rgba(15, 23, 42, 0.6)",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              padding: "12px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }
      }
    >
      <div
        data-qb="vector-hybrid-header"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }
        }
      >
        <span
          style={
            unstyled
              ? undefined
              : {
                  fontSize: "12px",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  color: "#94a3b8",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }
          }
        >
          <span>⚡</span> Semantic & Vector Retrieval
        </span>

        {/* Mode Selector */}
        <div data-qb="mode-selector-group" style={unstyled ? undefined : { display: "flex", gap: "4px" }}>
          {(["off", "vector", "hybrid"] as SearchMode[]).map((m) => (
            <button
              key={m}
              type="button"
              data-qb={`mode-${m}`}
              onClick={() => handleModeChange(m)}
              style={
                unstyled
                  ? undefined
                  : {
                      padding: "4px 8px",
                      borderRadius: "4px",
                      fontSize: "11px",
                      fontWeight: 500,
                      cursor: "pointer",
                      border: "1px solid",
                      borderColor:
                        mode === m
                          ? "rgba(99, 102, 241, 0.8)"
                          : "rgba(255, 255, 255, 0.1)",
                      background:
                        mode === m
                          ? "rgba(99, 102, 241, 0.25)"
                          : "rgba(255, 255, 255, 0.03)",
                      color: mode === m ? "#a5b4fc" : "#94a3b8",
                      transition: "all 0.15s ease",
                    }
              }
            >
              {m === "off" ? "Off" : m === "vector" ? "Vector (KNN)" : "Hybrid (RRF)"}
            </button>
          ))}
        </div>
      </div>

      {mode !== "off" && (
        <div
          data-qb="vector-hybrid-body"
          style={
            unstyled
              ? undefined
              : {
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                  paddingTop: "4px",
                }
          }
        >
          {/* Vector Configuration */}
          <div
            style={
              unstyled
                ? undefined
                : {
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "8px",
                  }
            }
          >
            <div>
              <label
                style={
                  unstyled
                    ? undefined
                    : {
                        fontSize: "11px",
                        color: "#94a3b8",
                        marginBottom: "4px",
                        display: "block",
                      }
                }
              >
                Vector Column
              </label>
              <select
                data-qb="vector-column-select"
                value={vectorColumn}
                onChange={(e) => {
                  setVectorColumn(e.target.value);
                  setTimeout(notifyChange, 0);
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        width: "100%",
                        background: "#0f172a",
                        color: "#e2e8f0",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        fontSize: "12px",
                      }
                }
              >
                {allColumns.map((col) => (
                  <option key={col.label} value={col.column}>
                    {col.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                style={
                  unstyled
                    ? undefined
                    : {
                        fontSize: "11px",
                        color: "#94a3b8",
                        marginBottom: "4px",
                        display: "block",
                      }
                }
              >
                Distance Metric
              </label>
              <select
                data-qb="metric-select"
                value={metric}
                onChange={(e) => {
                  setMetric(
                    e.target.value as
                      | "cosine"
                      | "euclidean"
                      | "l2"
                      | "dot_product"
                      | "inner_product"
                  );
                  setTimeout(notifyChange, 0);
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        width: "100%",
                        background: "#0f172a",
                        color: "#e2e8f0",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        fontSize: "12px",
                      }
                }
              >
                <option value="cosine">Cosine Distance (&lt;=&gt;)</option>
                <option value="l2">Euclidean / L2 (&lt;-&gt;)</option>
                <option value="inner_product">Inner Product (&lt;#&gt;)</option>
              </select>
            </div>
          </div>

          {/* Vector Array Input & Generator */}
          <div>
            <div
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "4px",
                    }
              }
            >
              <label style={unstyled ? undefined : { fontSize: "11px", color: "#94a3b8" }}>
                Query Embedding Vector (float array)
              </label>
              <button
                type="button"
                data-qb="mock-embedding-btn"
                onClick={handleGenerateMockEmbedding}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "none",
                        border: "none",
                        color: "#818cf8",
                        fontSize: "11px",
                        cursor: "pointer",
                        textDecoration: "underline",
                      }
                }
              >
                🎲 Random Normalized Vector
              </button>
            </div>
            <textarea
              data-qb="vector-input"
              rows={2}
              value={vectorInput}
              onChange={(e) => {
                setVectorInput(e.target.value);
                setTimeout(notifyChange, 0);
              }}
              placeholder="[0.1, 0.4, -0.2, ...]"
              style={
                unstyled
                  ? undefined
                  : {
                      width: "100%",
                      boxSizing: "border-box",
                      background: "#090d16",
                      color: "#38bdf8",
                      fontFamily: "monospace",
                      fontSize: "11px",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      borderRadius: "4px",
                      padding: "6px",
                      resize: "vertical",
                    }
              }
            />
          </div>

          {/* Top-K and Distances */}
          <div
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    alignItems: "center",
                    gap: "16px",
                  }
            }
          >
            <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "6px" }}>
              <label style={unstyled ? undefined : { fontSize: "11px", color: "#94a3b8" }}>Top K:</label>
              <input
                data-qb="top-k-input"
                type="number"
                min={1}
                max={1000}
                value={topK}
                onChange={(e) => {
                  const val = Math.max(1, parseInt(e.target.value) || 10);
                  setTopK(val);
                  setTimeout(notifyChange, 0);
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        width: "60px",
                        background: "#0f172a",
                        color: "#e2e8f0",
                        border: "1px solid rgba(255, 255, 255, 0.15)",
                        borderRadius: "4px",
                        padding: "3px 6px",
                        fontSize: "12px",
                      }
                }
              />
            </div>

            <label
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      fontSize: "11px",
                      color: "#cbd5e1",
                      cursor: "pointer",
                    }
              }
            >
              <input
                data-qb="include-distances-toggle"
                type="checkbox"
                checked={includeDistances}
                onChange={(e) => {
                  setIncludeDistances(e.target.checked);
                  setTimeout(notifyChange, 0);
                }}
              />
              Include distance column (_distance)
            </label>
          </div>

          {/* HYBRID SEARCH SECTION */}
          {mode === "hybrid" && (
            <div
              data-qb="hybrid-section"
              style={
                unstyled
                  ? undefined
                  : {
                      borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                      paddingTop: "10px",
                      display: "flex",
                      flexDirection: "column",
                      gap: "10px",
                    }
              }
            >
              <div
                style={
                  unstyled
                    ? undefined
                    : {
                        fontSize: "11px",
                        fontWeight: 600,
                        color: "#c084fc",
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                      }
                }
              >
                <span>🔍</span> Keyword / Full-Text Search Configuration
              </div>

              <div>
                <label
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "11px",
                          color: "#94a3b8",
                          marginBottom: "4px",
                          display: "block",
                        }
                  }
                >
                  Query Text
                </label>
                <input
                  data-qb="query-text-input"
                  type="text"
                  placeholder="e.g. distributed vector database clustering"
                  value={queryText}
                  onChange={(e) => {
                    setQueryText(e.target.value);
                    setTimeout(notifyChange, 0);
                  }}
                  style={
                    unstyled
                      ? undefined
                      : {
                          width: "100%",
                          boxSizing: "border-box",
                          background: "#0f172a",
                          color: "#e2e8f0",
                          border: "1px solid rgba(255, 255, 255, 0.15)",
                          borderRadius: "4px",
                          padding: "6px 8px",
                          fontSize: "12px",
                        }
                  }
                />
              </div>

              {/* Text Search Columns */}
              <div>
                <label
                  style={
                    unstyled
                      ? undefined
                      : {
                          fontSize: "11px",
                          color: "#94a3b8",
                          marginBottom: "4px",
                          display: "block",
                        }
                  }
                >
                  Target Text Columns:
                </label>
                <div
                  data-qb="text-columns-container"
                  style={unstyled ? undefined : { display: "flex", flexWrap: "wrap", gap: "6px" }}
                >
                  {allColumns.map((col) => {
                    const isSelected = textColumns.includes(col.column);
                    return (
                      <button
                        key={col.label}
                        type="button"
                        data-qb={`text-col-${col.column}`}
                        onClick={() => toggleTextColumn(col.column)}
                        style={
                          unstyled
                            ? undefined
                            : {
                                padding: "3px 6px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                cursor: "pointer",
                                border: "1px solid",
                                borderColor: isSelected
                                  ? "rgba(192, 132, 252, 0.8)"
                                  : "rgba(255, 255, 255, 0.1)",
                                background: isSelected
                                  ? "rgba(192, 132, 252, 0.2)"
                                  : "rgba(255, 255, 255, 0.02)",
                                color: isSelected ? "#e9d5ff" : "#94a3b8",
                              }
                        }
                      >
                        {isSelected ? "✓ " : ""}
                        {col.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Fusion Strategy */}
              <div
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "8px",
                        alignItems: "center",
                      }
                }
              >
                <div>
                  <label
                    style={
                      unstyled
                        ? undefined
                        : {
                            fontSize: "11px",
                            color: "#94a3b8",
                            marginBottom: "4px",
                            display: "block",
                          }
                    }
                  >
                    Fusion Algorithm
                  </label>
                  <select
                    data-qb="fusion-select"
                    value={fusion}
                    onChange={(e) => {
                      setFusion(e.target.value as "rrf" | "linear");
                      setTimeout(notifyChange, 0);
                    }}
                    style={
                      unstyled
                        ? undefined
                        : {
                            width: "100%",
                            background: "#0f172a",
                            color: "#e2e8f0",
                            border: "1px solid rgba(255, 255, 255, 0.15)",
                            borderRadius: "4px",
                            padding: "4px 8px",
                            fontSize: "12px",
                          }
                    }
                  >
                    <option value="rrf">Reciprocal Rank Fusion (RRF)</option>
                    <option value="linear">Linear Combination (Weighted)</option>
                  </select>
                </div>

                {fusion === "rrf" ? (
                  <div>
                    <label
                      style={
                        unstyled
                          ? undefined
                          : {
                              fontSize: "11px",
                              color: "#94a3b8",
                              marginBottom: "4px",
                              display: "block",
                            }
                      }
                    >
                      RRF Constant (k): {rrfK}
                    </label>
                    <input
                      data-qb="rrf-k-input"
                      type="number"
                      min={1}
                      max={200}
                      value={rrfK}
                      onChange={(e) => {
                        const val = Math.max(1, parseInt(e.target.value) || 60);
                        setRrfK(val);
                        setTimeout(notifyChange, 0);
                      }}
                      style={
                        unstyled
                          ? undefined
                          : {
                              width: "100%",
                              boxSizing: "border-box",
                              background: "#0f172a",
                              color: "#e2e8f0",
                              border: "1px solid rgba(255, 255, 255, 0.15)",
                              borderRadius: "4px",
                              padding: "4px 8px",
                              fontSize: "12px",
                            }
                      }
                    />
                  </div>
                ) : (
                  <div>
                    <label
                      style={
                        unstyled
                          ? undefined
                          : {
                              fontSize: "11px",
                              color: "#94a3b8",
                              marginBottom: "4px",
                              display: "block",
                            }
                      }
                    >
                      Weight (Alpha): {Math.round(alpha * 100)}% Vector /{" "}
                      {Math.round((1 - alpha) * 100)}% Text
                    </label>
                    <input
                      data-qb="alpha-slider"
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={alpha}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value);
                        setAlpha(val);
                        setTimeout(notifyChange, 0);
                      }}
                      style={unstyled ? undefined : { width: "100%" }}
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
