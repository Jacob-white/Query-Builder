import React, { useState } from "react";
import type {
  VectorSearchSpec,
  HybridSearchSpec,
  TableMeta,
  ColumnMeta,
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
      type: c.data_type || (c as ColumnMeta & { type?: string }).type || "string",
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
  const [minScore] = useState<number | undefined>(
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

  // Sync state when external vectorSearch / hybridSearch props change (e.g. Undo/Redo, loadSpec, clear)
  const prevPropsRef = React.useRef({ vectorSearch, hybridSearch });
  React.useEffect(() => {
    if (
      prevPropsRef.current.vectorSearch === vectorSearch &&
      prevPropsRef.current.hybridSearch === hybridSearch
    ) {
      return;
    }
    prevPropsRef.current = { vectorSearch, hybridSearch };
    if (hybridSearch) {
      setMode("hybrid");
      setVectorColumn(hybridSearch.vector_column || defaultVectorCol);
      setVectorInput(
        hybridSearch.vector ? JSON.stringify(hybridSearch.vector) : "[0.12, 0.45, -0.23, 0.88, 0.05]"
      );
      setMetric(hybridSearch.metric || "cosine");
      setTopK(hybridSearch.top_k || 10);
      setQueryText(hybridSearch.query_text || "");
      setTextColumns(hybridSearch.text_columns || [defaultTextCol]);
      setFusion(hybridSearch.fusion || "rrf");
      setAlpha(hybridSearch.alpha ?? 0.5);
      setRrfK(hybridSearch.rrf_k ?? 60);
    } else if (vectorSearch) {
      setMode("vector");
      setVectorColumn(vectorSearch.column || defaultVectorCol);
      setVectorInput(
        vectorSearch.vector ? JSON.stringify(vectorSearch.vector) : "[0.12, 0.45, -0.23, 0.88, 0.05]"
      );
      setMetric(vectorSearch.metric || "cosine");
      setTopK(vectorSearch.top_k || 10);
      setIncludeDistances(vectorSearch.include_distances ?? true);
    } else {
      setMode("off");
    }
  }, [vectorSearch, hybridSearch, defaultVectorCol, defaultTextCol]);

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

  const emitChange = (overrides: {
    vectorColumn?: string;
    vectorInput?: string;
    metric?: "cosine" | "euclidean" | "l2" | "dot_product" | "inner_product";
    topK?: number;
    includeDistances?: boolean;
    queryText?: string;
    textColumns?: string[];
    fusion?: "rrf" | "linear";
    alpha?: number;
    rrfK?: number;
  }) => {
    const nextVectorCol = overrides.vectorColumn ?? vectorColumn;
    const nextVectorInput = overrides.vectorInput ?? vectorInput;
    const nextMetric = overrides.metric ?? metric;
    const nextTopK = overrides.topK ?? topK;
    const nextIncludeDist = overrides.includeDistances ?? includeDistances;
    const nextQueryText = overrides.queryText ?? queryText;
    const nextTextCols = overrides.textColumns ?? textColumns;
    const nextFusion = overrides.fusion ?? fusion;
    const nextAlpha = overrides.alpha ?? alpha;
    const nextRrfK = overrides.rrfK ?? rrfK;

    const vec = parseVector(nextVectorInput);
    const validVec = vec.length > 0 ? vec : [0.1, 0.2, 0.3];
    if (mode === "vector") {
      onVectorChange({
        column: nextVectorCol,
        vector: validVec,
        metric: nextMetric,
        top_k: nextTopK,
        include_distances: nextIncludeDist,
        min_score: minScore,
      });
    } else if (mode === "hybrid") {
      onHybridChange({
        vector_column: nextVectorCol,
        vector: validVec,
        query_text: nextQueryText,
        text_columns: nextTextCols.length > 0 ? nextTextCols : [defaultTextCol],
        alpha: nextAlpha,
        fusion: nextFusion,
        rrf_k: nextRrfK,
        top_k: nextTopK,
        metric: nextMetric,
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
    emitChange({ vectorInput: str });
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
    emitChange({ textColumns: next });
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
              padding: mode === "off" ? "8px 12px" : "12px",
              display: "flex",
              flexDirection: "column",
              gap: mode === "off" ? "6px" : "12px",
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
                  const nextCol = e.target.value;
                  setVectorColumn(nextCol);
                  emitChange({ vectorColumn: nextCol });
                }}
                style={unstyled ? undefined : SR_ONLY_STYLE}
              >
                {allColumns.map((col) => (
                  <option key={col.label} value={col.column}>
                    {col.label}
                  </option>
                ))}
              </select>
              {!unstyled && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                  {allColumns.slice(0, 12).map((col) => {
                    const isSelected = vectorColumn === col.column;
                    return (
                      <button
                        key={col.label}
                        type="button"
                        aria-label={`Select vector column ${col.label}`}
                        onClick={() => {
                          setVectorColumn(col.column);
                          emitChange({ vectorColumn: col.column });
                        }}
                        style={{
                          padding: "3px 8px",
                          borderRadius: "5px",
                          fontSize: "11px",
                          fontWeight: isSelected ? 600 : 500,
                          cursor: "pointer",
                          border: isSelected
                            ? "1px solid rgba(56, 189, 248, 0.7)"
                            : "1px solid rgba(255, 255, 255, 0.12)",
                          background: isSelected
                            ? "rgba(56, 189, 248, 0.18)"
                            : "rgba(15, 23, 42, 0.7)",
                          color: isSelected ? "#38bdf8" : "#94a3b8",
                        }}
                      >
                        {col.label}
                      </button>
                    );
                  })}
                </div>
              )}
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
                  const nextMetric = e.target.value as
                    | "cosine"
                    | "euclidean"
                    | "l2"
                    | "dot_product"
                    | "inner_product";
                  setMetric(nextMetric);
                  emitChange({ metric: nextMetric });
                }}
                style={unstyled ? undefined : SR_ONLY_STYLE}
              >
                <option value="cosine">Cosine Distance (&lt;=&gt;)</option>
                <option value="l2">Euclidean / L2 (&lt;-&gt;)</option>
                <option value="inner_product">Inner Product (&lt;#&gt;)</option>
              </select>
              {!unstyled && (
                <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                  {(
                    [
                      { value: "cosine", label: "Cosine (<=>)" },
                      { value: "l2", label: "L2 (<->)" },
                      { value: "inner_product", label: "Inner (<#>)" },
                    ] as const
                  ).map((opt) => {
                    const isSelected = metric === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => {
                          setMetric(opt.value);
                          emitChange({ metric: opt.value });
                        }}
                        style={{
                          padding: "4px 8px",
                          borderRadius: "5px",
                          fontSize: "11px",
                          fontWeight: isSelected ? 600 : 500,
                          cursor: "pointer",
                          border: isSelected
                            ? "1px solid rgba(99, 102, 241, 0.7)"
                            : "1px solid rgba(255, 255, 255, 0.12)",
                          background: isSelected
                            ? "rgba(99, 102, 241, 0.22)"
                            : "rgba(15, 23, 42, 0.7)",
                          color: isSelected ? "#a5b4fc" : "#94a3b8",
                        }}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                </div>
              )}
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
                const nextInput = e.target.value;
                setVectorInput(nextInput);
                emitChange({ vectorInput: nextInput });
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
                  emitChange({ topK: val });
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
                  const checked = e.target.checked;
                  setIncludeDistances(checked);
                  emitChange({ includeDistances: checked });
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
                    const nextText = e.target.value;
                    setQueryText(nextText);
                    emitChange({ queryText: nextText });
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
                      const nextFusion = e.target.value as "rrf" | "linear";
                      setFusion(nextFusion);
                      emitChange({ fusion: nextFusion });
                    }}
                    style={unstyled ? undefined : SR_ONLY_STYLE}
                  >
                    <option value="rrf">Reciprocal Rank Fusion (RRF)</option>
                    <option value="linear">Linear Combination (Weighted)</option>
                  </select>
                  {!unstyled && (
                    <div style={{ display: "flex", gap: "4px" }}>
                      {(
                        [
                          { value: "rrf", label: "RRF (Rank)" },
                          { value: "linear", label: "Linear (Weighted)" },
                        ] as const
                      ).map((opt) => {
                        const isSelected = fusion === opt.value;
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => {
                              setFusion(opt.value);
                              emitChange({ fusion: opt.value });
                            }}
                            style={{
                              padding: "4px 8px",
                              borderRadius: "5px",
                              fontSize: "11px",
                              fontWeight: isSelected ? 600 : 500,
                              cursor: "pointer",
                              border: isSelected
                                ? "1px solid rgba(192, 132, 252, 0.7)"
                                : "1px solid rgba(255, 255, 255, 0.12)",
                              background: isSelected
                                ? "rgba(192, 132, 252, 0.22)"
                                : "rgba(15, 23, 42, 0.7)",
                              color: isSelected ? "#e9d5ff" : "#94a3b8",
                            }}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>
                  )}
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
                        emitChange({ rrfK: val });
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
                        emitChange({ alpha: val });
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
