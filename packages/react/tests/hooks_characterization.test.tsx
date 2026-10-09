import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  useQueryBuilder,
  useQueryState,
  stateToSpec,
  specToState,
  compileSpecToSql,
  type QueryBuilderActions,
  type QueryStateActions,
  type QueryState,
  type SchemaSnapshot,
} from "../src";
import type { LooseQuerySpec } from "../src/types";

/**
 * Characterization suite: pins the observable behavior of useQueryBuilder and useQueryState across
 * the whole action set, plus the spec<->state<->SQL conversion table. Expected values live in
 * tests/fixtures/hooks_characterization.json (recorded from the pre-refactor implementation;
 * regenerate deliberately with UPDATE_HOOKS_FIXTURE=1).
 */

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURE = resolve(here, "fixtures/hooks_characterization.json");

const schema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "name", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    orders: {
      name: "orders",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "total", data_type: "numeric", is_nullable: false, is_primary: false },
      ],
    },
    order_items: {
      name: "order_items",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "order_id", data_type: "integer", is_nullable: false, is_primary: false },
        { name: "product_id", data_type: "integer", is_nullable: false, is_primary: false },
      ],
    },
    products: {
      name: "products",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "title", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
    isolated: {
      name: "isolated",
      columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }],
    },
  },
  foreign_keys: [
    { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
    { table: "order_items", column: "order_id", foreign_table: "orders", foreign_column: "id" },
    { table: "order_items", column: "product_id", foreign_table: "products", foreign_column: "id" },
  ],
};

/** Fallback auto-join ids embed Date.now()/Math.random(); mask them so snapshots are stable. */
function norm<T>(value: T): T {
  return JSON.parse(JSON.stringify(value).replace(/join-\d+-[a-z0-9]+/g, "join-X")) as T;
}

type BuilderStep = (a: QueryBuilderActions) => void;
type StateStep = (a: QueryStateActions) => void;

const savedSpec: LooseQuerySpec = {
  table: "orders",
  columns: ["orders.id", { column: "orders.total", agg: "sum", alias: "t" }],
  joins: [{ table: "users", type: "inner", on: [{ left: "orders.user_id", right: "users.id" }] }],
  filters: [
    { column: "orders.total", op: "gt", value: 5 },
    { column: "users.name", op: "=", value: "a", combiner: "OR" },
  ],
  order_by: [{ column: "orders.total", direction: "DESC" }],
  filter_join: "OR",
  distinct: true,
  limit: 7,
};

const builderScenarios: Record<string, BuilderStep[]> = {
  tables_and_columns: [
    (a) => a.addTable("users"),
    (a) => a.addTable("users"),
    (a) => a.addTable("orders"),
    (a) => a.toggleColumn("users", "id"),
    (a) => a.toggleColumn("orders", "total"),
    (a) => a.toggleColumn("users", "id"),
    (a) => a.updateColumnSelect("orders.total", { aggregate: "SUM", alias: "t" }),
    (a) => a.updateColumnSelect("nope.x", { alias: "z" }),
    (a) => a.toggleColumn("users", "name"),
    (a) => a.removeColumnProjection("users.name"),
    (a) => a.removeTable("orders"),
    (a) => a.removeTable("users"),
    (a) => a.setPrimaryTable("products"),
  ],
  joins_filters_sorts: [
    (a) => a.addTable("users"),
    (a) =>
      a.addJoin({
        id: "j1",
        table: "orders",
        type: "LEFT JOIN",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
      }),
    (a) => a.updateJoin("j1", { type: "INNER JOIN" }),
    (a) => a.addFilter({ id: "f1", tablePrefix: "users", column: "id", operator: ">", value: 1 }),
    (a) =>
      a.addFilter({
        id: "f2",
        tablePrefix: "users",
        column: "name",
        operator: "=",
        value: "a",
        combiner: "OR",
      }),
    (a) => a.updateFilter("f1", { value: 2 }),
    (a) => a.removeFilter("f2"),
    (a) => a.addSort({ id: "s1", tablePrefix: "users", column: "id", direction: "DESC" }),
    (a) => a.addSort({ id: "s2", tablePrefix: "users", column: "name", direction: "ASC" }),
    (a) => a.updateSort("s1", { direction: "ASC" }),
    (a) => a.removeSort("s2"),
    (a) => a.removeJoin("j1"),
    (a) => a.setFilterJoin?.("OR"),
    (a) => a.setIsDistinct(true),
    (a) => a.setLimit(9),
    (a) => a.setDialect("mysql"),
  ],
  auto_join: [
    (a) => a.addTable("users"),
    (a) => a.autoJoinTable("orders"),
    (a) => a.autoJoinTable("products"),
    (a) => a.autoJoinTable("isolated"),
    (a) => a.autoJoinTable(""),
  ],
  spec_template_raw_reset_clean: [
    (a) => a.loadSpec(savedSpec),
    (a) => a.markClean(),
    (a) => a.addTable("products"),
    (a) => a.reset(),
    (a) => a.loadSpec({ table: "users", filters: [{ column: "id", op: "=", value: 1 }] }),
    (a) => a.loadTemplate({ id: "t", title: "t", sql: "SELECT 1", createdAt: "x" }),
    (a) => a.setRawSql("SELECT 2"),
    (a) => a.loadTemplate({ id: "t2", title: "t", sql: "SELECT 1", spec: savedSpec, createdAt: "x" }),
    (a) => a.setIsRawMode(true),
    (a) => a.setIsRawMode(false),
    (a) => a.setCtes?.([{ name: "c", query: { table: "users" } }]),
    (a) => a.setWindowFunctions?.([{ function: "ROW_NUMBER", alias: "rn" }]),
    (a) => a.setSemanticModels?.([]),
    (a) => a.setVectorSearch?.(null),
    (a) => a.setHybridSearch?.(null),
  ],
};

const stateScenarios: Record<string, StateStep[]> = {
  tables_and_columns: [
    (a) => a.addTable("users"),
    (a) => a.addTable("users"),
    (a) => a.addTable("orders"),
    (a) => a.toggleColumn("users", "id"),
    (a) => a.toggleColumn("orders", "total"),
    (a) => a.toggleColumn("users", "id"),
    (a) => a.updateColumnSelect("orders.total", { aggregate: "SUM", alias: "t" }),
    (a) => a.updateColumnSelect("nope.x", { alias: "z" }),
    (a) => a.removeColumnProjection("orders.total"),
    (a) => a.removeTable("orders"),
    (a) => a.setTables(["products", "users"]),
    (a) => a.setPrimaryTable("isolated"),
    (a) => a.setSelectedColumns({ "users.id": { table: "users", name: "id" } }),
    (a) => a.setOrderedProjectionKeys(["users.id"]),
    (a) => a.removeTable("users"),
  ],
  joins_filters_sorts: [
    (a) => a.addTable("users"),
    (a) =>
      a.addJoin({
        id: "j1",
        table: "orders",
        type: "LEFT JOIN",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
      }),
    (a) => a.updateJoin("j1", { type: "INNER JOIN" }),
    (a) => a.addFilter({ id: "f1", tablePrefix: "users", column: "id", operator: ">", value: 1 }),
    (a) =>
      a.addFilter({
        id: "f2",
        tablePrefix: "users",
        column: "name",
        operator: "=",
        value: "a",
        combiner: "OR",
      }),
    (a) => a.updateFilter("f1", { value: 2 }),
    (a) => a.removeFilter("f2"),
    (a) => a.setFilters([{ id: "f3", tablePrefix: "users", column: "id", operator: "=", value: 3 }]),
    (a) => a.addSort({ id: "s1", tablePrefix: "users", column: "id", direction: "DESC" }),
    (a) => a.addSort({ id: "s2", tablePrefix: "users", column: "name", direction: "ASC" }),
    (a) => a.updateSort("s1", { direction: "ASC" }),
    (a) => a.removeSort("s2"),
    (a) => a.setSorts([]),
    (a) => a.setJoins([]),
    (a) => a.setDistinct(true),
    (a) => a.setLimit(9),
    (a) => a.setOffset(4),
    (a) => a.setDialect("mysql"),
    (a) => a.setCtes([{ name: "c", query: { table: "users" } }]),
    (a) => a.setWindowFunctions([{ function: "ROW_NUMBER", alias: "rn" }]),
    (a) => a.setVectorSearch(null),
    (a) => a.setHybridSearch(null),
  ],
  auto_join: [
    (a) => a.addTable("users"),
    (a) => a.autoJoinTable("orders", schema),
    (a) => a.autoJoinTable("products", schema),
    (a) => a.autoJoinTable("isolated", schema),
    (a) => a.autoJoinTable("", schema),
    (a) => a.autoJoinTable("orders"),
  ],
  spec_history_reset_clean: [
    (a) => a.loadSpec(savedSpec),
    (a) => a.markClean(),
    (a) => a.addTable("products"),
    (a) => a.undo(),
    (a) => a.undo(),
    (a) => a.redo(),
    (a) => a.redo(),
    (a) => a.redo(),
    (a) => a.loadSpec({ limit: 3 }),
    (a) => a.loadSpec({ table: "users", filters: [{ column: "id", op: "=", value: 1 }] }),
    (a) => a.clearHistory(),
    (a) => a.undo(),
    (a) => a.addTable("orders"),
    (a) => a.reset(),
  ],
};

function builderSnap(r: ReturnType<typeof useQueryBuilder>) {
  const { activeTables, ...state } = r.state;
  return norm({
    state,
    activeTableNames: activeTables.map((t) => t.name),
    currentSql: r.currentSql,
    compiledSpec: r.compiled.spec,
    safety: r.safety,
  });
}

function stateSnap(r: ReturnType<typeof useQueryState>) {
  return norm({
    state: r.state,
    spec: r.spec,
    canUndo: r.history.canUndo,
    canRedo: r.history.canRedo,
    pastLen: r.history.past.length,
    futureLen: r.history.future.length,
  });
}

const stateInputs: Record<string, Record<string, unknown>> = {
  empty: {},
  savedSpec: { ...savedSpec },
  stateShaped: {
    primaryTable: "users",
    activeTables: ["users", "orders"],
    selectedColumns: { "users.id": { table: "users", name: "id", alias: "uid" } },
    filters: [{ id: "f", tablePrefix: "users", column: "id", operator: "IN", value: "1,2" }],
    sorts: [{ id: "s", tablePrefix: "users", column: "id", direction: "DESC" }],
    isDistinct: true,
    limit: 12,
  },
  columnsOnly: {
    table: "orders",
    columns: ["id", "orders.total", "*", null, { column: "users.name", agg: "count" }],
  },
  joinsVariants: {
    table: "orders",
    joins: [
      { table: "users", type: "left", left_col: "user_id", right_col: "id" },
      { table: "products", type: "RIGHT JOIN", on: [{ left: "orders.pid", right: "products.id" }] },
      { table: "isolated" },
    ],
  },
  filtersVariants: {
    table: "orders",
    filter_join: "OR",
    filters: [
      { column: "total", operator: "not_in", value: "1" },
      { column: "orders.status", op: "like", value: "x", combiner: "AND" },
      { table: "users", column: "name", op: "=", value: null },
      { column: "x", operator: "raw", rawExpression: "1=1" },
    ],
  },
  sortsVariants: {
    table: "orders",
    order_by: [
      { column: "orders.total", direction: "DESC" },
      { column: "id" },
      { column: "total", tablePrefix: "users" },
    ],
  },
  filterJoinCamel: { table: "orders", filterJoin: "or", filters: [{ column: "id", op: "=", value: 1 }] },
  withExtras: {
    table: "orders",
    dialect: "sqlite",
    offset: 5,
    vector_search: null,
    hybrid_search: null,
    ctes: [{ name: "c", query: { table: "users" } }],
    window_functions: [{ function: "RANK", alias: "r" }],
    isDistinct: false,
    limit: 1,
  },
};

interface Recorded {
  builderScenarios: Record<string, unknown[]>;
  stateScenarios: Record<string, unknown[]>;
  builderInit: Record<string, unknown>;
  stateInit: Record<string, unknown>;
  conversions: Record<string, unknown>;
  actionNames: { builder: string[]; state: string[] };
}

function runBuilder(steps: BuilderStep[]): unknown[] {
  const { result } = renderHook(() => useQueryBuilder({ schema, initialTable: "users" }));
  const out: unknown[] = [builderSnap(result.current)];
  for (const step of steps) {
    act(() => step(result.current.actions));
    out.push(builderSnap(result.current));
  }
  return out;
}

function runState(steps: StateStep[]): unknown[] {
  const { result } = renderHook(() => useQueryState({ table: "users", columns: ["users.id"] }));
  const out: unknown[] = [stateSnap(result.current)];
  for (const step of steps) {
    act(() => step(result.current.actions));
    out.push(stateSnap(result.current));
  }
  return out;
}

function record(): Recorded {
  const b = renderHook(() => useQueryBuilder({ schema, initialTable: "users" }));
  const s = renderHook(() => useQueryState({ table: "users" }));
  const rec: Recorded = {
    builderScenarios: {},
    stateScenarios: {},
    builderInit: {},
    stateInit: {},
    conversions: {},
    actionNames: {
      builder: Object.keys(b.result.current.actions).sort(),
      state: Object.keys(s.result.current.actions).sort(),
    },
  };
  for (const [k, steps] of Object.entries(builderScenarios)) rec.builderScenarios[k] = runBuilder(steps);
  for (const [k, steps] of Object.entries(stateScenarios)) rec.stateScenarios[k] = runState(steps);
  for (const [k, input] of Object.entries(stateInputs)) {
    // initialSpec conversion, loadSpec conversion and the pure converters must all stay stable.
    const init = renderHook(() => useQueryBuilder({ schema, initialSpec: input }));
    rec.builderInit[k] = builderSnap(init.result.current);
    const loaded = renderHook(() => useQueryBuilder({ schema, initialTable: "users" }));
    act(() => loaded.result.current.actions.loadSpec(input));
    rec.builderInit[`${k}:loadSpec`] = builderSnap(loaded.result.current);
    const st = renderHook(() => useQueryState(input));
    rec.stateInit[k] = stateSnap(st.result.current);
    const full: QueryState = st.result.current.state;
    rec.conversions[k] = norm({
      specToState: specToState(input),
      stateToSpec: stateToSpec(full),
      sqlPostgres: compileSpecToSql(input, "postgres", schema),
      sqlMysql: compileSpecToSql(input, "mysql", schema),
    });
  }
  return rec;
}

describe("hooks characterization", () => {
  const recorded = record();

  if (process.env.UPDATE_HOOKS_FIXTURE === "1") {
    it("writes the fixture", () => {
      mkdirSync(dirname(FIXTURE), { recursive: true });
      writeFileSync(FIXTURE, JSON.stringify(recorded, null, 1) + "\n");
    });
    return;
  }

  const expected = JSON.parse(readFileSync(FIXTURE, "utf8")) as Recorded;

  for (const k of Object.keys(builderScenarios)) {
    it(`useQueryBuilder scenario ${k}`, () => {
      expect(recorded.builderScenarios[k]).toEqual(expected.builderScenarios[k]);
    });
  }
  for (const k of Object.keys(stateScenarios)) {
    it(`useQueryState scenario ${k}`, () => {
      expect(recorded.stateScenarios[k]).toEqual(expected.stateScenarios[k]);
    });
  }
  for (const k of Object.keys(stateInputs)) {
    it(`spec/state/SQL conversions for ${k}`, () => {
      expect(recorded.builderInit[k]).toEqual(expected.builderInit[k]);
      expect(recorded.builderInit[`${k}:loadSpec`]).toEqual(expected.builderInit[`${k}:loadSpec`]);
      expect(recorded.stateInit[k]).toEqual(expected.stateInit[k]);
      expect(recorded.conversions[k]).toEqual(expected.conversions[k]);
    });
  }

  it("keeps the public action sets, return shapes and stable reset identity", () => {
    const b = renderHook(() => useQueryBuilder({ schema, initialTable: "users" }));
    const s = renderHook(() => useQueryState({ table: "users" }));
    expect(Object.keys(b.result.current).sort()).toEqual(["actions", "compiled", "currentSql", "safety", "state"]);
    expect(Object.keys(s.result.current).sort()).toEqual(["actions", "history", "spec", "state"]);
    expect(Object.keys(b.result.current.actions).sort()).toEqual(expected.actionNames.builder);
    expect(Object.keys(s.result.current.actions).sort()).toEqual(expected.actionNames.state);
    const resetB = b.result.current.actions.reset;
    const resetS = s.result.current.actions.reset;
    b.rerender();
    s.rerender();
    expect(b.result.current.actions.reset).toBe(resetB);
    expect(s.result.current.actions.reset).toBe(resetS);
  });
});
