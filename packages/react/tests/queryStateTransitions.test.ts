import { describe, it, expect } from "vitest";
import {
  addTableToState,
  appendItem,
  applyBuilderSpecPatch,
  autoJoinOnState,
  isSpecShaped,
  narrowSerializedSpec,
  removeColumnProjectionFromState,
  removeItemById,
  removeTableFromState,
  setPrimaryTableOnState,
  setTablesOnState,
  specToBuilderPatch,
  specToState,
  stateToSpec,
  toggleColumnOnState,
  updateColumnSelectOnState,
  updateItemById,
  type BuilderPatchTarget,
  type QueryCoreState,
} from "../src/utils/queryStateTransitions";
import { useQueryBuilder, useQueryState, type SchemaSnapshot } from "../src";
import { renderHook, act } from "@testing-library/react";

const core = (over: Partial<QueryCoreState> = {}): QueryCoreState => ({
  primaryTable: "",
  activeTables: [],
  selectedColumns: {},
  orderedProjectionKeys: [],
  joins: [],
  filters: [],
  sorts: [],
  ...over,
});

const schema: SchemaSnapshot = {
  tables: {
    a: { name: "a", columns: [{ name: "id", data_type: "integer", is_nullable: false, is_primary: true }] },
    b: {
      name: "b",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "a_id", data_type: "integer", is_nullable: false, is_primary: false },
      ],
    },
  },
  foreign_keys: [{ table: "b", column: "a_id", foreign_table: "a", foreign_column: "id" }],
};

describe("queryStateTransitions", () => {
  it("adds tables, adopting the first as primary even when it is already active", () => {
    const added = addTableToState(core(), "a");
    expect(added.primaryTable).toBe("a");
    expect(added.activeTables).toEqual(["a"]);
    const again = addTableToState(core({ activeTables: ["a"] }), "a");
    expect(again.activeTables).toEqual(["a"]);
    expect(again.primaryTable).toBe("a");
    expect(addTableToState(core({ primaryTable: "z" }), "a").primaryTable).toBe("z");
  });

  it("sets the primary table and the table list", () => {
    expect(setPrimaryTableOnState(core({ activeTables: ["a"] }), "a").activeTables).toEqual(["a"]);
    expect(setPrimaryTableOnState(core({ activeTables: ["a"] }), "b").activeTables).toEqual(["a", "b"]);
    expect(setTablesOnState(core({ primaryTable: "a" }), ["a", "b"]).primaryTable).toBe("a");
    expect(setTablesOnState(core({ primaryTable: "z" }), ["b"]).primaryTable).toBe("b");
    expect(setTablesOnState(core({ primaryTable: "z" }), []).primaryTable).toBe("");
  });

  it("removes a table with its joins, columns and projection keys", () => {
    const state = core({
      primaryTable: "a",
      activeTables: ["a", "b"],
      selectedColumns: { "a.id": { table: "a", name: "id" }, "b.id": { table: "b", name: "id" } },
      orderedProjectionKeys: ["a.id", "b.id"],
      joins: [{ id: "j", table: "b", left_table: "a", left_col: "id", right_col: "a_id", type: "LEFT JOIN" }],
    });
    const next = removeTableFromState(state, "a");
    expect(next.primaryTable).toBe("b");
    expect(next.activeTables).toEqual(["b"]);
    expect(Object.keys(next.selectedColumns)).toEqual(["b.id"]);
    expect(next.orderedProjectionKeys).toEqual(["b.id"]);
    expect(next.joins).toEqual([]);
    expect(removeTableFromState(state, "b").primaryTable).toBe("a");
  });

  it("toggles, updates and removes columns", () => {
    const on = toggleColumnOnState(core(), "a", "id");
    expect(on.selectedColumns["a.id"]).toEqual({ table: "a", name: "id" });
    expect(on.orderedProjectionKeys).toEqual(["a.id"]);
    const dup = toggleColumnOnState(core({ orderedProjectionKeys: ["a.id"] }), "a", "id");
    expect(dup.orderedProjectionKeys).toEqual(["a.id"]);
    const off = toggleColumnOnState(on, "a", "id");
    expect(off.selectedColumns).toEqual({});
    expect(off.orderedProjectionKeys).toEqual([]);

    const updated = updateColumnSelectOnState(on, "a.id", { alias: "x" });
    expect(updated.selectedColumns["a.id"].alias).toBe("x");
    expect(updateColumnSelectOnState(on, "missing", { alias: "x" })).toBe(on);

    const removed = removeColumnProjectionFromState(on, "a.id");
    expect(removed.selectedColumns).toEqual({});
    expect(removed.orderedProjectionKeys).toEqual([]);
  });

  it("operates on id-keyed lists without mutating them", () => {
    const list = [{ id: "1", v: 1 }];
    expect(appendItem(list, { id: "2", v: 2 })).toHaveLength(2);
    expect(updateItemById(list, "1", { v: 5 })).toEqual([{ id: "1", v: 5 }]);
    expect(removeItemById(list, "1")).toEqual([]);
    expect(list).toEqual([{ id: "1", v: 1 }]);
  });

  it("auto-joins along an FK path and falls back to a best-effort condition", () => {
    const base = core({ primaryTable: "a", activeTables: ["a"] });
    const viaPath = autoJoinOnState(base, "b", schema);
    expect(viaPath.joins.length).toBeGreaterThan(0);
    expect(viaPath.activeTables).toContain("b");

    const fallback = autoJoinOnState(core({ primaryTable: "a", activeTables: ["a"] }), "zzz", schema);
    expect(fallback.joins).toHaveLength(1);
    expect(fallback.joins[0].id.startsWith("join-")).toBe(true);
    expect(fallback.activeTables).toContain("zzz");

    expect(autoJoinOnState(base, "", schema)).toBe(base);
    // No active tables: falls back to the primary table.
    expect(autoJoinOnState(core({ primaryTable: "a" }), "b", schema).joins.length).toBeGreaterThan(0);
    // Nothing at all: uses the literal placeholder base table.
    expect(autoJoinOnState(core(), "b", null).joins).toHaveLength(1);
  });

  it("round-trips state and spec", () => {
    const spec = stateToSpec({
      primaryTable: "a",
      selectedColumns: { "a.id": { table: "a", name: "id", aggregate: "COUNT", alias: "n" } },
      orderedProjectionKeys: [],
      joins: [{ id: "j", table: "b", left_col: "id", right_col: "a_id", type: "LEFT JOIN" }],
      filters: [{ id: "f", tablePrefix: "a", column: "id", operator: "=", value: 1, combiner: "OR" }],
      sorts: [{ id: "s", tablePrefix: "a", column: "id", direction: "DESC" }],
      isDistinct: true,
      limit: 5,
      offset: 2,
      vectorSearch: null,
      hybridSearch: null,
      ctes: [{ name: "c", query: { table: "a" } }],
      windowFunctions: [{ function: "RANK" }],
    });
    expect(spec.filter_join).toBe("OR");
    expect(spec.offset).toBe(2);
    expect(spec.ctes).toHaveLength(1);
    const back = specToState(spec);
    expect(back.primaryTable).toBe("a");
    expect(back.joins?.[0].left_table).toBe("a");
    expect(back.limit).toBe(5);
  });

  it("applies builder patches only for the keys they carry", () => {
    const target: BuilderPatchTarget = {
      ...core({ activeTables: ["x"] }),
      isDistinct: false,
      limit: 1,
      vectorSearch: null,
      hybridSearch: null,
      ctes: null,
      windowFunctions: null,
      semanticModels: null,
      filterJoin: "AND",
    };
    expect(applyBuilderSpecPatch(target, {})).toEqual(target);
    const patch = specToBuilderPatch({
      table: "a",
      columns: ["a.id"],
      joins: [{ table: "b", type: "inner", on: [{ left: "a.id", right: "b.a_id" }] }],
      filters: [{ column: "a.id", op: "not_in", value: 1 }],
      order_by: [{ column: "a.id", direction: "DESC" }],
      distinct: true,
      limit: 9,
      vector_search: null,
      hybrid_search: null,
      ctes: null,
      window_functions: null,
      semantic_models: null,
      filter_join: "OR",
    });
    const next = applyBuilderSpecPatch(target, patch);
    expect(next.primaryTable).toBe("a");
    expect(next.activeTables).toEqual(["a", "b"]);
    expect(next.joins[0].type).toBe("INNER JOIN");
    expect(next.filters[0].operator).toBe("NOT IN");
    expect(next.sorts[0].tablePrefix).toBe("a");
    expect(next.isDistinct).toBe(true);
    expect(next.limit).toBe(9);
    expect(next.filterJoin).toBe("OR");
    expect(next.vectorSearch).toBeNull();
  });

  it("detects spec-shaped initial values", () => {
    expect(isSpecShaped({ selectedColumns: {} })).toBe(false);
    expect(isSpecShaped({ columns: ["a.id"] })).toBe(true);
    expect(isSpecShaped({ filters: [{ op: "=" }] })).toBe(true);
    expect(isSpecShaped({ joins: [{ table: "b", type: "left" }] })).toBe(true);
    expect(isSpecShaped({ joins: [{ table: "b", type: "LEFT JOIN" }] })).toBe(false);
    expect(isSpecShaped({})).toBe(false);
  });

  it("narrows untrusted input at the boundary", () => {
    expect(narrowSerializedSpec(null)).toEqual({});
    expect(narrowSerializedSpec("select 1")).toEqual({});
    expect(narrowSerializedSpec([1, 2])).toEqual({});
    const narrowed = narrowSerializedSpec({
      table: "a",
      limit: "5",
      distinct: "yes",
      columns: "id",
      joins: [],
      ctes: null,
      vector_search: "nope",
      selectedColumns: { k: { table: "a", name: "k" } },
      table_extra: 1,
    });
    expect(narrowed).toEqual({
      table: "a",
      joins: [],
      ctes: null,
      selectedColumns: { k: { table: "a", name: "k" } },
      table_extra: 1,
    });
  });
});

describe("hook boundary behavior", () => {
  it("ignores non-object specs passed to loadSpec instead of throwing", () => {
    const b = renderHook(() => useQueryBuilder({ schema, initialTable: "a" }));
    const s = renderHook(() => useQueryState({ table: "a" }));
    act(() => b.result.current.actions.loadSpec(null as never));
    act(() => s.result.current.actions.loadSpec(undefined as never));
    expect(b.result.current.state.primaryTable).toBe("a");
    expect(s.result.current.state.primaryTable).toBe("a");
  });

  it("builder addTable fills an empty primary even for an already-active table; useQueryState leaves it", () => {
    const b = renderHook(() => useQueryBuilder({ schema, initialTable: "a" }));
    act(() => b.result.current.actions.setPrimaryTable(""));
    act(() => b.result.current.actions.addTable("a"));
    expect(b.result.current.state.primaryTable).toBe("a");

    const s = renderHook(() => useQueryState({ activeTables: ["a"] }));
    expect(s.result.current.state.primaryTable).toBe("");
    act(() => s.result.current.actions.addTable("a"));
    expect(s.result.current.state.primaryTable).toBe("");
  });

  it("builder setters still accept updater functions", () => {
    const b = renderHook(() => useQueryBuilder({ schema, initialTable: "a" }));
    act(() => b.result.current.actions.setJoins((prev) => [...prev, { id: "j", table: "b", left_col: "id", right_col: "a_id", type: "LEFT JOIN" }]));
    expect(b.result.current.state.joins).toHaveLength(1);
    act(() => b.result.current.actions.setFilters([]));
    act(() => b.result.current.actions.setSorts((prev) => prev));
    expect(b.result.current.state.filters).toEqual([]);
  });
});
