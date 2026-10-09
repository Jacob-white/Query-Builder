/**
 * Shared, typed test helpers. Prefer these over `as any` in tests.
 */
import type {
  ColumnMeta,
  DashboardTile,
  DashboardTileLayout,
  QuerySpec,
  SchemaSnapshot,
  TableMeta,
} from "../../src/types";

/**
 * Deliberate runtime-validation escape hatch.
 *
 * Use ONLY when a test intentionally passes input that violates the static type
 * (null, wrong shape, junk) to verify runtime validation/defensive behaviour.
 * This is the single documented cast in the test suite; it keeps the intent
 * visible at the call site (`invalid<QuerySpec>(null)`).
 */
export function invalid<T>(value: unknown): T {
  return value as T;
}

/** Build a complete QuerySpec; only the fields a test cares about need be given. */
export function makeSpec(overrides: Partial<QuerySpec> = {}): QuerySpec {
  return {
    table: "users",
    columns: [],
    joins: [],
    filters: [],
    filter_join: "AND",
    order_by: [],
    distinct: false,
    limit: 100,
    ...overrides,
  };
}

/** Build a ColumnMeta with sensible defaults. */
export function makeColumn(name: string, overrides: Partial<ColumnMeta> = {}): ColumnMeta {
  return { name, data_type: "text", is_nullable: true, is_primary: false, ...overrides };
}

/** Build a TableMeta from column names or full ColumnMeta objects. */
export function makeTable(
  name: string,
  columns: (string | ColumnMeta)[] = [],
  overrides: Partial<TableMeta> = {},
): TableMeta {
  return {
    name,
    columns: columns.map((c) => (typeof c === "string" ? makeColumn(c) : c)),
    ...overrides,
  };
}

/** Build a SchemaSnapshot from a table-name -> TableMeta map. */
export function makeSnapshot(
  tables: Record<string, TableMeta>,
  overrides: Partial<SchemaSnapshot> = {},
): SchemaSnapshot {
  return { tables, ...overrides };
}

/** Build a DashboardTile with defaults. */
export function makeTile(
  overrides: Partial<Omit<DashboardTile, "layout">> & { layout?: Partial<DashboardTileLayout> } = {},
): DashboardTile {
  const { layout, ...rest } = overrides;
  return {
    id: "t1",
    title: "Tile",
    type: "chart",
    ...rest,
    layout: { w: 1, h: 1, ...layout },
  };
}
