/**
 * Typed prop factory for <QueryCanvas />. Supplies no-op handlers and empty
 * collections so tests only specify the props they exercise.
 */
import type { QueryCanvasProps } from "../../src/components/QueryCanvas";

export function makeCanvasProps(overrides: Partial<QueryCanvasProps> = {}): QueryCanvasProps {
  return {
    activeTables: [],
    primaryTable: "",
    selectedColumns: {},
    orderedProjectionKeys: [],
    joins: [],
    filters: [],
    sorts: [],
    isDistinct: false,
    limit: 100,
    onToggleColumn: () => {},
    onRemoveTable: () => {},
    onAddTableToCanvas: () => {},
    onUpdateColumnSelect: () => {},
    onRemoveColumnProjection: () => {},
    onJoinsChange: () => {},
    onFiltersChange: () => {},
    onSortsChange: () => {},
    onDistinctChange: () => {},
    onLimitChange: () => {},
    ...overrides,
  };
}
