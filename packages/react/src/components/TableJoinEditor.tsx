import React from "react";
import type { VisualJoin, TableMeta, SchemaSnapshot, QueryBuilderClassNames } from "../types";
import { findBestJoinCondition } from "../utils/joinUtils";
import { cx } from "../utils/classNames";

export interface TableJoinEditorProps {
  joins: VisualJoin[];
  activeTables: TableMeta[];
  allTables: TableMeta[];
  schema?: SchemaSnapshot | null;
  onChange: (joins: VisualJoin[]) => void;
  unstyled?: boolean;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

export const TableJoinEditor: React.FC<TableJoinEditorProps> = ({
  joins,
  activeTables,
  allTables,
  schema,
  onChange,
  unstyled = false,
  className,
  classNames,
}) => {
  const handleAddJoin = (targetTable: string) => {
    if (!targetTable || activeTables.length === 0) return;
    const baseTable = activeTables[0].name;
    const cond = findBestJoinCondition(baseTable, targetTable, schema);

    const newJoin: VisualJoin = {
      id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      type: "LEFT JOIN",
      left_table: cond.leftTable,
      left_col: cond.leftCol,
      table: cond.rightTable,
      right_col: cond.rightCol,
    };
    onChange([...joins, newJoin]);
  };

  const handleUpdate = (id: string, updates: Partial<VisualJoin>) => {
    onChange(joins.map((j) => (j.id === id ? { ...j, ...updates } : j)));
  };

  const handleRemove = (id: string) => {
    onChange(joins.filter((j) => j.id !== id));
  };

  // Tables not yet joined
  const unjoinedTables = allTables.filter(
    (t) => !activeTables.some((a) => a.name === t.name),
  );

  return (
    <div
      data-qb="joins-editor"
      className={cx(className, classNames?.joins)}
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
              gap: "10px",
            }
      }
    >
      <div
        data-qb="joins-header"
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
          className={cx(classNames?.title)}
          style={
            unstyled
              ? undefined
              : { fontSize: "0.85rem", fontWeight: 600, color: "#94a3b8" }
          }
        >
          🔗 Table Relationships & Joins ({joins.length})
        </span>

        {unjoinedTables.length > 0 && (
          <div
            style={
              unstyled
                ? undefined
                : { display: "flex", alignItems: "center", gap: "6px" }
            }
          >
            <select
              defaultValue=""
              aria-label="Join table"
              data-qb="select-add-join"
              onChange={(e) => {
                if (e.target.value) {
                  handleAddJoin(e.target.value);
                  e.target.value = "";
                }
              }}
              style={
                unstyled
                  ? undefined
                  : {
                      background: "#1e293b",
                      color: "#60a5fa",
                      border: "1px solid rgba(59, 130, 246, 0.4)",
                      borderRadius: "6px",
                      padding: "4px 8px",
                      fontSize: "0.75rem",
                      cursor: "pointer",
                      fontWeight: 600,
                    }
              }
            >
              <option value="" disabled>
                + Join Table...
              </option>
              {unjoinedTables.map((t) => (
                <option key={t.name} value={t.name}>
                  + {t.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {joins.length === 0 ? (
        <div
          style={
            unstyled
              ? undefined
              : {
                  fontSize: "0.78rem",
                  color: "#64748b",
                  fontStyle: "italic",
                  textAlign: "center",
                  padding: "12px 0",
                }
          }
        >
          Single table query. Add another table to configure relational joins.
        </div>
      ) : (
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          {joins.map((j) => (
            <div
              key={j.id}
              data-qb="join-row"
              data-qb-join-id={j.id}
              className={cx(classNames?.joinItem)}
              style={
                unstyled
                  ? undefined
                  : {
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      flexWrap: "wrap",
                      background: "rgba(30, 41, 59, 0.5)",
                      padding: "8px 10px",
                      borderRadius: "6px",
                    }
              }
            >
              {/* Join type */}
              <select
                value={j.type}
                aria-label="Join type"
                data-qb="join-type"
                onChange={(e) =>
                  handleUpdate(j.id, {
                    type: e.target.value as VisualJoin["type"],
                  })
                }
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "#1e293b",
                        color: "#38bdf8",
                        border: "1px solid #475569",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                      }
                }
              >
                <option value="LEFT JOIN">LEFT JOIN</option>
                <option value="INNER JOIN">INNER JOIN</option>
                <option value="RIGHT JOIN">RIGHT JOIN</option>
                <option value="FULL JOIN">FULL JOIN</option>
              </select>

              <span
                style={
                  unstyled
                    ? undefined
                    : { fontWeight: 600, color: "#f8fafc", fontSize: "0.8rem" }
                }
              >
                {j.table}
              </span>

              <span style={unstyled ? undefined : { fontSize: "0.75rem", color: "#64748b" }}>
                ON
              </span>

              {/* Left col */}
              <input
                type="text"
                aria-label="Join left column"
                data-qb="join-left-col"
                value={`${j.left_table || activeTables[0]?.name}.${j.left_col}`}
                onChange={(e) => {
                  const val = e.target.value;
                  const lastDot = val.lastIndexOf(".");
                  if (lastDot !== -1) {
                    handleUpdate(j.id, {
                      left_table: val.substring(0, lastDot),
                      left_col: val.substring(lastDot + 1),
                    });
                  }
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "#1e293b",
                        color: "#cbd5e1",
                        border: "1px solid #475569",
                        borderRadius: "4px",
                        padding: "4px 6px",
                        fontSize: "0.75rem",
                        width: "140px",
                      }
                }
              />

              <span style={unstyled ? undefined : { fontSize: "0.75rem", color: "#64748b" }}>
                =
              </span>

              {/* Right col */}
              <input
                type="text"
                aria-label="Join right column"
                data-qb="join-right-col"
                value={`${j.table}.${j.right_col}`}
                onChange={(e) => {
                  const val = e.target.value;
                  const lastDot = val.lastIndexOf(".");
                  if (lastDot !== -1) {
                    handleUpdate(j.id, { right_col: val.substring(lastDot + 1) });
                  }
                }}
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "#1e293b",
                        color: "#cbd5e1",
                        border: "1px solid #475569",
                        borderRadius: "4px",
                        padding: "4px 6px",
                        fontSize: "0.75rem",
                        width: "140px",
                      }
                }
              />

              <button
                type="button"
                aria-label="Remove join"
                onClick={() => handleRemove(j.id)}
                data-qb="btn-remove-join"
                style={
                  unstyled
                    ? undefined
                    : {
                        background: "transparent",
                        border: "none",
                        color: "#ef4444",
                        cursor: "pointer",
                        fontSize: "0.9rem",
                        padding: "2px 6px",
                      }
                }
                title="Remove join"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
