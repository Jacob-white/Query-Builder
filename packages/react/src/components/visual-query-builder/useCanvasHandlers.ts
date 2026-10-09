import { useCallback } from "react";
import type { SchemaSnapshot, TableMeta, VisualFilter, VisualJoin, VisualSort } from "../../types";
import type { QueryState, QueryStateActions } from "../../hooks/useQueryState";
import { findBestJoinCondition } from "../../utils/joinUtils";

export interface UseCanvasHandlersOptions {
  state: QueryState;
  actions: QueryStateActions;
  leaveRawMode: () => void;
  augmentedSchema: SchemaSnapshot | null | undefined;
  normalizedSchema: SchemaSnapshot | null | undefined;
}

/** Visual-edit handlers; each leaves raw-SQL mode first so discarded SQL is surfaced to the user. */
export function useCanvasHandlers({
  state,
  actions,
  leaveRawMode,
  augmentedSchema,
  normalizedSchema,
}: UseCanvasHandlersOptions) {
  const setSorts = useCallback(
    (newSorts: VisualSort[]) => {
      leaveRawMode();
      actions.setSorts(newSorts);
    },
    [actions, leaveRawMode],
  );

  const setFilters = useCallback(
    (newFilters: VisualFilter[]) => {
      leaveRawMode();
      actions.setFilters(newFilters);
    },
    [actions, leaveRawMode],
  );

  const handleToggleColumn = (tableName: string, colName: string) => {
    leaveRawMode();
    const key = `${tableName}.${colName}`;
    const nextSelected = { ...state.selectedColumns };
    let nextKeys = [...state.orderedProjectionKeys];
    if (nextSelected[key]) {
      delete nextSelected[key];
      nextKeys = nextKeys.filter((k) => k !== key);
    } else {
      const tblMeta: TableMeta | undefined = augmentedSchema?.tables?.[tableName];
      const isMetric = tblMeta?.metrics?.find((m) => m.name === colName);
      nextSelected[key] = {
        table: tableName,
        name: colName,
        metric: isMetric || undefined,
      };
      if (!nextKeys.includes(key)) {
        nextKeys.push(key);
      }
    }
    actions.setSelectedColumns(nextSelected, nextKeys);
  };

  const handleAddTableToCanvas = (tableName: string) => {
    if (!tableName) return;
    leaveRawMode();
    actions.addTable(tableName);
  };

  const handleRemoveTable = (tableName: string) => {
    leaveRawMode();
    actions.removeTable(tableName);
  };

  /** Synchronizes joins and the set of active tables. */
  const handleJoinsChange = (newJoins: VisualJoin[]) => {
    leaveRawMode();
    actions.setJoins(newJoins);
    const set = new Set(state.activeTables);
    for (const j of newJoins) {
      if (j.table) set.add(j.table);
      if (j.left_table) set.add(j.left_table);
    }
    actions.setTables(Array.from(set));
  };

  const handleAddJoinToTable = (tableName: string) => {
    const allTableNames = normalizedSchema?.tables ? Object.keys(normalizedSchema.tables) : [];
    const candidate = allTableNames.find((t) => t !== tableName && !state.activeTables.includes(t));
    if (candidate) {
      const cond = findBestJoinCondition(tableName, candidate, normalizedSchema);
      const newJoin: VisualJoin = {
        id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        type: "LEFT JOIN",
        left_table: cond.leftTable,
        left_col: cond.leftCol,
        table: cond.rightTable,
        right_col: cond.rightCol,
      };
      handleJoinsChange([...state.joins, newJoin]);
    }
  };

  return {
    setSorts,
    setFilters,
    handleToggleColumn,
    handleAddTableToCanvas,
    handleRemoveTable,
    handleJoinsChange,
    handleAddJoinToTable,
  };
}
