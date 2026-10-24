import { useCallback } from "react";
import type { CaseWhenSpec, SchemaSnapshot, TableMeta, VisualFilter, VisualJoin, VisualSort } from "../../types";
import type { QueryState, QueryStateActions } from "../../hooks/useQueryState";
import { findBestJoinCondition } from "../../utils/joinUtils";
import { directLinks } from "../../utils/queryHelpers/joinLinks";

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
    const tblMeta: TableMeta | undefined = augmentedSchema?.tables?.[tableName];
    const isMetric = tblMeta?.metrics?.find((m) => m.name === colName);
    actions.toggleColumn(tableName, colName);
    if (isMetric) {
      actions.updateColumnSelect(key, { metric: isMetric });
    }
  };

  const handleAddCalculatedField = (spec: {
    alias: string;
    expression?: string;
    case_when?: CaseWhenSpec;
  }) => {
    leaveRawMode();
    const key = `__calc_${spec.alias}`;
    const nextSelected = {
      ...state.selectedColumns,
      [key]: {
        table: state.primaryTable || state.activeTables[0] || "",
        name: spec.alias,
        alias: spec.alias,
        rawExpression: spec.expression,
        caseWhen: spec.case_when,
      },
    };
    const nextKeys = state.orderedProjectionKeys.includes(key)
      ? state.orderedProjectionKeys
      : [...state.orderedProjectionKeys, key];
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
    if (!tableName) return;
    const effectiveSchema = augmentedSchema || normalizedSchema;
    const fks = effectiveSchema?.foreign_keys || [];
    const primaryOrFirst = state.primaryTable || state.activeTables[0];
    const isAlreadyActive = state.activeTables.includes(tableName);
    const isAlreadyJoined = state.joins.some(
      (j) => j.table === tableName || j.left_table === tableName,
    );

    if (!isAlreadyActive || (tableName !== primaryOrFirst && !isAlreadyJoined)) {
      const candidateSources = state.activeTables.filter((t) => t !== tableName);
      const links = directLinks(tableName, candidateSources, fks);
      const linkedSource =
        links.length > 0
          ? links[0].table === tableName
            ? links[0].foreign_table
            : links[0].table
          : undefined;
      const sourceTable = linkedSource || primaryOrFirst;
      if (sourceTable && sourceTable !== tableName) {
        const cond = findBestJoinCondition(sourceTable, tableName, effectiveSchema);
        const newJoin: VisualJoin = {
          id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
          type: "LEFT JOIN",
          left_table: cond.leftTable,
          left_col: cond.leftCol,
          table: cond.rightTable,
          right_col: cond.rightCol,
        };
        handleJoinsChange([...state.joins, newJoin]);
      } else {
        handleAddTableToCanvas(tableName);
      }
      return;
    }

    const allTableNames = effectiveSchema?.tables ? Object.keys(effectiveSchema.tables) : [];
    const joinedSet = new Set<string>();
    for (const j of state.joins) {
      if (j.table) joinedSet.add(j.table);
      if (j.left_table) joinedSet.add(j.left_table);
    }
    const unjoined = allTableNames.filter(
      (t) => t !== tableName && (!state.activeTables.includes(t) || !joinedSet.has(t)),
    );
    const fkCandidate = unjoined.find((t) => directLinks(t, [tableName], fks).length > 0);
    const candidate = fkCandidate || unjoined[0];
    if (candidate) {
      const cond = findBestJoinCondition(tableName, candidate, effectiveSchema);
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
    handleAddCalculatedField,
    handleAddTableToCanvas,
    handleRemoveTable,
    handleJoinsChange,
    handleAddJoinToTable,
  };
}
