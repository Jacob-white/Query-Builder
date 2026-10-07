import React, { useState } from "react";
import type {
  CalculatedFieldSpec,
  CaseWhenBranch,
  CaseWhenSpec,
  ColumnMeta,
  TableMeta,
} from "../types";

export interface CalculatedFieldEditorProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (field: CalculatedFieldSpec) => void;
  tables: TableMeta[];
  initialField?: CalculatedFieldSpec | null;
  unstyled?: boolean;
}

export const CalculatedFieldEditor: React.FC<CalculatedFieldEditorProps> = ({
  isOpen,
  onClose,
  onSave,
  tables,
  initialField,
  unstyled = false,
}) => {
  const [alias, setAlias] = useState<string>(initialField?.alias || "calculated_col");
  const [type, setType] = useState<"case_when" | "expression">(
    initialField?.type || "case_when",
  );
  const [expression, setExpression] = useState<string>(
    initialField?.expression || "",
  );
  const [branches, setBranches] = useState<CaseWhenBranch[]>(
    initialField?.case_when?.branches || [
      {
        condition: { column: "", op: "eq", value: "" },
        then_value: "",
      },
    ],
  );
  const [elseValue, setElseValue] = useState<string>(
    initialField?.case_when?.else_value ?? "",
  );

  if (!isOpen) return null;

  const allColumns: { table: string; column: ColumnMeta }[] = [];
  tables.forEach((t) => {
    t.columns.forEach((c) => {
      allColumns.push({ table: t.name, column: c });
    });
  });

  const handleAddBranch = () => {
    setBranches([
      ...branches,
      {
        condition: { column: allColumns[0]?.column.name || "", op: "eq", value: "" },
        then_value: "",
      },
    ]);
  };

  const handleRemoveBranch = (index: number) => {
    setBranches(branches.filter((_, i) => i !== index));
  };

  const handleUpdateBranch = (
    index: number,
    field: "column" | "op" | "value" | "then_value",
    val: any,
  ) => {
    const updated = [...branches];
    if (field === "then_value") {
      updated[index] = { ...updated[index], then_value: val };
    } else {
      updated[index] = {
        ...updated[index],
        condition: { ...updated[index].condition, [field]: val },
      };
    }
    setBranches(updated);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!alias.trim()) return;

    if (type === "case_when") {
      const caseWhenSpec: CaseWhenSpec = {
        branches,
        else_value: elseValue ? elseValue : null,
        alias: alias.trim(),
      };
      onSave({
        id: initialField?.id || `calc_${Date.now()}`,
        name: alias.trim(),
        alias: alias.trim(),
        type: "case_when",
        case_when: caseWhenSpec,
      });
    } else {
      onSave({
        id: initialField?.id || `calc_${Date.now()}`,
        name: alias.trim(),
        alias: alias.trim(),
        type: "expression",
        expression: expression.trim(),
      });
    }
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Calculated Field Editor"
      data-qb="calculated-field-editor-modal"
      style={
        unstyled
          ? undefined
          : {
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: "rgba(0, 0, 0, 0.65)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1000,
              backdropFilter: "blur(4px)",
            }
      }
    >
      <div
        data-qb="calculated-field-editor-content"
        style={
          unstyled
            ? undefined
            : {
                background: "var(--qb-bg-surface, #1e293b)",
                color: "var(--qb-text-primary, #f8fafc)",
                border: "1px solid var(--qb-border-subtle, #334155)",
                borderRadius: "var(--qb-radius-lg, 8px)",
                padding: "24px",
                width: "90%",
                maxWidth: "600px",
                maxHeight: "85vh",
                overflowY: "auto",
                boxShadow: "0 20px 25px -5px rgba(0,0,0,0.5)",
              }
        }
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px" }}>
          <h3 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 600 }}>
            ✨ Calculated Column Editor
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close calculated column editor"
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

        <form onSubmit={handleSubmit}>
          {/* Alias */}
          <div style={{ marginBottom: "14px" }}>
            <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "4px" }}>
              Column Output Alias:
            </label>
            <input
              type="text"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              placeholder="e.g. status_tier"
              aria-label="Calculated column alias"
              required
              style={{
                width: "100%",
                padding: "8px 12px",
                background: "var(--qb-bg-canvas, #0f172a)",
                color: "inherit",
                border: "1px solid var(--qb-border-subtle, #334155)",
                borderRadius: "6px",
              }}
            />
          </div>

          {/* Type Toggle */}
          <div style={{ marginBottom: "16px", display: "flex", gap: "10px" }}>
            <label style={{ fontSize: "0.85rem", display: "flex", alignItems: "center", gap: "6px" }}>
              <input
                type="radio"
                name="calcType"
                value="case_when"
                checked={type === "case_when"}
                onChange={() => setType("case_when")}
              />
              CASE WHEN Conditional
            </label>
            <label style={{ fontSize: "0.85rem", display: "flex", alignItems: "center", gap: "6px" }}>
              <input
                type="radio"
                name="calcType"
                value="expression"
                checked={type === "expression"}
                onChange={() => setType("expression")}
              />
              SQL Formula Expression
            </label>
          </div>

          {type === "case_when" ? (
            <div style={{ marginBottom: "16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>WHEN Branches:</span>
                <button
                  type="button"
                  data-qb="btn-add-branch"
                  onClick={handleAddBranch}
                  style={{
                    background: "var(--qb-primary, #3b82f6)",
                    color: "#fff",
                    border: "none",
                    borderRadius: "4px",
                    padding: "4px 8px",
                    fontSize: "0.75rem",
                    cursor: "pointer",
                  }}
                >
                  + Add Branch
                </button>
              </div>

              {branches.map((b, idx) => (
                <div
                  key={idx}
                  style={{
                    background: "var(--qb-bg-canvas, #0f172a)",
                    border: "1px solid var(--qb-border-subtle, #334155)",
                    borderRadius: "6px",
                    padding: "10px",
                    marginBottom: "8px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "#94a3b8" }}>
                    <span>WHEN:</span>
                    {branches.length > 1 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveBranch(idx)}
                        aria-label={`Remove branch ${idx + 1}`}
                        style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer" }}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                    <select
                      value={b.condition.column}
                      onChange={(e) => handleUpdateBranch(idx, "column", e.target.value)}
                      aria-label={`Branch ${idx + 1} column`}
                      style={{ padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    >
                      <option value="">Select Column...</option>
                      {allColumns.map((col, cidx) => (
                        <option key={cidx} value={col.column.name}>
                          {col.table}.{col.column.name}
                        </option>
                      ))}
                    </select>

                    <select
                      value={b.condition.op}
                      onChange={(e) => handleUpdateBranch(idx, "op", e.target.value)}
                      aria-label={`Branch ${idx + 1} operator`}
                      style={{ padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    >
                      <option value="eq">=</option>
                      <option value="neq">!=</option>
                      <option value="gt">&gt;</option>
                      <option value="gte">&gt;=</option>
                      <option value="lt">&lt;</option>
                      <option value="lte">&lt;=</option>
                      <option value="is_null">IS NULL</option>
                      <option value="is_not_null">IS NOT NULL</option>
                    </select>

                    <input
                      type="text"
                      placeholder="Value"
                      value={b.condition.value ?? ""}
                      onChange={(e) => handleUpdateBranch(idx, "value", e.target.value)}
                      aria-label={`Branch ${idx + 1} condition value`}
                      style={{ flex: 1, minWidth: "80px", padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    />
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    <span style={{ fontSize: "0.8rem", color: "#10b981", fontWeight: 600 }}>THEN:</span>
                    <input
                      type="text"
                      placeholder="Then Result"
                      value={b.then_value ?? ""}
                      onChange={(e) => handleUpdateBranch(idx, "then_value", e.target.value)}
                      aria-label={`Branch ${idx + 1} then value`}
                      required
                      style={{ flex: 1, padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    />
                  </div>
                </div>
              ))}

              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "10px" }}>
                <span style={{ fontSize: "0.8rem", color: "#f59e0b", fontWeight: 600 }}>ELSE:</span>
                <input
                  type="text"
                  placeholder="Default / fallback value"
                  value={elseValue}
                  onChange={(e) => setElseValue(e.target.value)}
                  aria-label="Else fallback value"
                  style={{ flex: 1, padding: "6px", background: "#0f172a", color: "#fff", border: "1px solid #334155", borderRadius: "4px" }}
                />
              </div>
            </div>
          ) : (
            <div style={{ marginBottom: "16px" }}>
              <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "4px" }}>
                Formula Expression:
              </label>
              <textarea
                value={expression}
                onChange={(e) => setExpression(e.target.value)}
                placeholder="e.g. price * quantity or DATEDIFF(day, start_date, end_date)"
                aria-label="Formula expression"
                rows={3}
                required
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  background: "var(--qb-bg-canvas, #0f172a)",
                  color: "inherit",
                  border: "1px solid var(--qb-border-subtle, #334155)",
                  borderRadius: "6px",
                  fontFamily: "monospace",
                }}
              />
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "20px" }}>
            <button
              type="button"
              data-qb="btn-cancel-calc"
              onClick={onClose}
              style={{
                padding: "8px 16px",
                background: "transparent",
                color: "#94a3b8",
                border: "1px solid #475569",
                borderRadius: "6px",
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              data-qb="btn-save-calc"
              style={{
                padding: "8px 16px",
                background: "var(--qb-primary, #3b82f6)",
                color: "#ffffff",
                border: "none",
                borderRadius: "6px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Save Column
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
