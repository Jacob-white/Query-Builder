import React from "react";
import type { QueryBuilderClassNames } from "../../types";
import { useCompoundQueryBuilder } from "./QueryBuilderContext";
import { TableCard } from "../TableCard";
import { cx } from "../../utils/classNames";

export interface QueryBuilderCanvasProps {
  /** Optional container class name */
  className?: string;
  /** Granular slot class names mapping */
  classNames?: QueryBuilderClassNames;
  /** Unstyled mode flag */
  unstyled?: boolean;
}

export const QueryBuilderCanvas: React.FC<QueryBuilderCanvasProps> = ({
  className,
  classNames: propClassNames,
  unstyled: propUnstyled,
}) => {
  const {
    activeTables,
    primaryTable,
    selectedColumns,
    normalizedSchema,
    actions,
    unstyled: rootUnstyled,
    classNames: rootClassNames,
    fieldRenderers,
  } = useCompoundQueryBuilder();

  const unstyled = propUnstyled ?? rootUnstyled;
  const classNames = propClassNames || rootClassNames;

  const allTables = Object.values(normalizedSchema?.tables || {});
  const availableToAdd = allTables.filter(
    (t) => !activeTables.some((a) => a.name === t.name),
  );

  return (
    <div
      data-qb="canvas"
      className={cx(className, classNames?.canvas)}
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              flexDirection: "column",
              gap: "16px",
              fontFamily: "system-ui, -apple-system, sans-serif",
            }
      }
    >
      <div
        data-qb="canvas-tables"
        className={cx(classNames?.canvasTables)}
        style={unstyled ? undefined : { display: "flex", flexDirection: "column", gap: "10px" }}
      >
        <div
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
                : { fontSize: "0.88rem", fontWeight: 700, color: "#cbd5e1" }
            }
          >
            {`📋 Active Tables in Query (${activeTables.length})`}
          </span>
          {availableToAdd.length > 0 && (
            <select
              defaultValue=""
              data-qb="select-add-table"
              aria-label="Add table to canvas"
              onChange={(e) => {
                if (e.target.value) {
                  actions.addTable(e.target.value);
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
                      padding: "4px 10px",
                      fontSize: "0.78rem",
                      cursor: "pointer",
                      fontWeight: 600,
                    }
              }
            >
              <option value="" disabled>
                + Add Table to Canvas...
              </option>
              {availableToAdd.map((t) => (
                <option key={t.name} value={t.name}>
                  + {t.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {activeTables.length === 0 ? (
          <div
            data-qb="canvas-empty-state"
            className={cx(classNames?.canvasEmpty)}
            style={
              unstyled
                ? undefined
                : {
                    padding: "32px",
                    textAlign: "center",
                    color: "#94a3b8",
                    border: "2px dashed rgba(255, 255, 255, 0.1)",
                    borderRadius: "10px",
                    width: "100%",
                  }
            }
          >
            No tables in query. Select a table to start building.
          </div>
        ) : (
          <div
            data-qb="table-cards-list"
            style={
              unstyled
                ? undefined
                : {
                    display: "flex",
                    gap: "16px",
                    overflowX: "auto",
                    paddingBottom: "8px",
                  }
            }
          >
            {activeTables.map((t) => (
              <TableCard
                key={t.name}
                table={t}
                isSelected={t.name === primaryTable}
                selectedColumns={selectedColumns}
                onToggleColumn={(col) => actions.toggleColumn(t.name, col)}
                onRemoveTable={() => actions.removeTable(t.name)}
                onAddJoin={() => actions.autoJoinTable(t.name, normalizedSchema)}
                unstyled={unstyled}
                fieldRenderers={fieldRenderers}
                classNames={classNames}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
