import { describe, expect, it, vi } from "vitest";
import { completeJoins, loadCompleted, type ForeignKeyEdge } from "../src/utils/queryHelpers";
import { joinsSummary } from "../src/utils/queryHelpers/summaryText";

const link = (table: string, column: string, foreign_table: string, foreign_column = "id"): ForeignKeyEdge => ({
  table,
  column,
  foreign_table,
  foreign_column,
});

const LINKS: ForeignKeyEdge[] = [
  link("orders", "customer_id", "customers"),
  link("orders", "billing_region_id", "regions"),
  link("orders", "shipping_region_id", "regions"),
  link("shipments", "order_id", "orders"),
];

const specWith = (joins: unknown, table = "orders") => ({ table, columns: ["orders.id"], joins });

describe("completeJoins", () => {
  it("fills the matching columns from the one link between the tables, leaving the kind alone", () => {
    const { spec, unresolved } = completeJoins(specWith([{ table: "customers", type: "INNER" }]), LINKS);
    expect(spec.joins).toEqual([{ table: "customers", type: "INNER", left_table: "orders", left_col: "customer_id", right_col: "id" }]);
    expect(unresolved).toEqual([]);
  });

  it("reads a link in either direction", () => {
    const { spec } = completeJoins(specWith([{ table: "orders" }], "customers"), LINKS);
    expect(spec.joins).toEqual([{ table: "orders", left_table: "customers", left_col: "id", right_col: "customer_id" }]);
  });

  it("can join from a table an earlier join added", () => {
    const { spec, unresolved } = completeJoins(specWith([{ table: "customers" }, { table: "shipments" }]), LINKS);
    expect(unresolved).toEqual([]);
    expect(spec.joins).toEqual([
      { table: "customers", left_table: "orders", left_col: "customer_id", right_col: "id" },
      { table: "shipments", left_table: "orders", left_col: "id", right_col: "order_id" },
    ]);
  });

  it("leaves a join that already says what it matches on exactly as it is", () => {
    const joins = [{ table: "regions", type: "LEFT", left_table: "orders", left_col: "shipping_region_id", right_col: "id" }];
    const { spec, unresolved } = completeJoins(specWith(joins), LINKS);
    expect(spec.joins).toEqual(joins);
    expect(unresolved).toEqual([]);
  });

  it("treats a join written with an ON condition as complete", () => {
    const joins = [{ table: "customers", on: [{ left: "orders.customer_id", right: "customers.id" }] }];
    expect(completeJoins(specWith(joins), LINKS).spec.joins).toEqual(joins);
  });

  it("fills only what is missing when a join is half written", () => {
    const { spec } = completeJoins(specWith([{ table: "customers", left_col: "customer_id" }]), LINKS);
    expect(spec.joins).toEqual([{ table: "customers", left_col: "customer_id", left_table: "orders", right_col: "id" }]);
  });

  it("does not guess between several links, and reports the join so it can be left blank", () => {
    const joins = [{ table: "regions", type: "LEFT" }];
    const { spec, unresolved } = completeJoins(specWith(joins), LINKS);
    expect(spec.joins).toEqual(joins);
    expect(unresolved).toEqual([{ id: "join_1", table: "regions", reason: "several" }]);
  });

  it("uses what the join does say to choose between several links", () => {
    const { spec, unresolved } = completeJoins(specWith([{ table: "regions", left_col: "billing_region_id" }]), LINKS);
    expect(unresolved).toEqual([]);
    expect(spec.joins).toEqual([{ table: "regions", left_col: "billing_region_id", left_table: "orders", right_col: "id" }]);
  });

  it("does not invent a link between tables that have none", () => {
    const { spec, unresolved } = completeJoins(specWith([{ table: "notes" }]), LINKS);
    expect(spec.joins).toEqual([{ table: "notes" }]);
    expect(unresolved).toEqual([{ id: "join_1", table: "notes", reason: "none" }]);
  });

  it("counts the same link once even when two sources declare it", () => {
    const { unresolved } = completeJoins(specWith([{ table: "customers" }]), [...LINKS, link("orders", "customer_id", "customers")]);
    expect(unresolved).toEqual([]);
  });

  it("names an unresolved join by its own id when it has one, as the builder does", () => {
    const { unresolved } = completeJoins(specWith([{ table: "customers" }, { id: "mine", table: "notes" }]), LINKS);
    expect(unresolved).toEqual([{ id: "mine", table: "notes", reason: "none" }]);
  });

  it("does not change the spec it was given", () => {
    const original = specWith([{ table: "customers" }]);
    const before = JSON.stringify(original);
    completeJoins(original, LINKS);
    expect(JSON.stringify(original)).toBe(before);
  });

  it.each([
    ["no joins", { table: "orders" }],
    ["joins that are not a list", { table: "orders", joins: "customers" }],
    ["entries that are not joins", { table: "orders", joins: [null, 7, "x", ["y"]] }],
    ["a join with no table", { table: "orders", joins: [{}] }],
    ["no base table", { joins: [{ table: "customers" }] }],
  ])("copes with %s", (_label, spec) => {
    expect(() => completeJoins(spec as Record<string, unknown>, LINKS)).not.toThrow();
  });

  it("returns a spec with no joins unchanged", () => {
    const spec = { table: "orders", columns: ["orders.id"] };
    expect(completeJoins(spec, LINKS)).toEqual({ spec, unresolved: [] });
  });
});

describe("loadCompleted", () => {
  const actions = () => ({ loadSpec: vi.fn(), updateJoin: vi.fn() });

  it("loads the completed spec, and hands it back so the caller restores the same one", () => {
    const a = actions();
    const { spec, unresolved } = loadCompleted(a, specWith([{ table: "customers" }]), LINKS);
    expect(a.loadSpec).toHaveBeenCalledWith(spec);
    expect((spec.joins as unknown[])[0]).toMatchObject({ left_table: "orders", left_col: "customer_id", right_col: "id" });
    expect(unresolved).toEqual([]);
    expect(a.updateJoin).not.toHaveBeenCalled();
  });

  it("blanks the columns a builder would default to id = id, for a join it could not resolve, after the load", () => {
    const a = actions();
    const { unresolved } = loadCompleted(a, specWith([{ table: "notes" }, { table: "regions" }]), LINKS);
    expect(unresolved.map((u) => u.id)).toEqual(["join_1", "join_2"]);
    expect(a.updateJoin).toHaveBeenCalledWith("join_1", { left_table: undefined, left_col: "", right_col: "" });
    expect(a.updateJoin).toHaveBeenCalledWith("join_2", { left_table: undefined, left_col: "", right_col: "" });
    expect(a.updateJoin.mock.invocationCallOrder[0]).toBeGreaterThan(a.loadSpec.mock.invocationCallOrder[0]);
  });

  it("loads a spec with no joins untouched, and never needs to blank anything", () => {
    const a = actions();
    const spec = { table: "orders", columns: ["orders.id"] };
    loadCompleted(a, spec, LINKS);
    expect(a.loadSpec).toHaveBeenCalledWith(spec);
    expect(a.updateJoin).not.toHaveBeenCalled();
  });

  it("copes with a builder that cannot update a join, and with no links at all", () => {
    const a = { loadSpec: vi.fn() };
    expect(() => loadCompleted(a, specWith([{ table: "notes" }]), [])).not.toThrow();
    expect(a.loadSpec).toHaveBeenCalledTimes(1);
  });
});

describe("joinsSummary says the kind of join and what it joins on", () => {
  const join = (over = {}) => ({ table: "customers", type: "LEFT JOIN", left_table: "orders", left_col: "customer_id", right_col: "id", ...over });

  it("is unchanged for joins that carry only a table (compatibility)", () => {
    expect(joinsSummary([])).toBe("None");
    expect(joinsSummary([{ table: "orders" }, { table: "customers" }])).toBe("orders, customers");
    expect(joinsSummary([{ table: "a" }, { table: "b" }, { table: "c" }, { table: "d" }])).toBe("a, b, c and 1 more");
  });

  it("names the kind, the table and both columns", () => {
    expect(joinsSummary([join()])).toBe("Left join customers on orders.customer_id = customers.id");
  });

  it.each([
    ["INNER JOIN", "Inner join"],
    ["LEFT JOIN", "Left join"],
    ["RIGHT JOIN", "Right join"],
    ["FULL JOIN", "Full join"],
    ["INNER", "Inner join"],
    ["full outer", "Full join"],
  ])("writes %s as %s", (type, words) => {
    expect(joinsSummary([join({ type })])).toBe(`${words} customers on orders.customer_id = customers.id`);
  });

  it("does not invent a kind the join does not have", () => {
    expect(joinsSummary([join({ type: undefined })])).toBe("Join customers on orders.customer_id = customers.id");
  });

  it("says plainly when the matching column was never chosen, rather than showing a half-filled join as complete", () => {
    expect(joinsSummary([join({ left_table: undefined })])).toBe("Left join customers: choose the matching column");
    expect(joinsSummary([join({ left_col: "" })])).toBe("Left join customers: choose the matching column");
    expect(joinsSummary([join({ right_col: "" })])).toBe("Left join customers: choose the matching column");
  });

  it("lists each join, and says how many more when there are many", () => {
    const two = joinsSummary([join(), join({ table: "regions", type: "INNER JOIN", left_col: "shipping_region_id" })]);
    expect(two).toBe("Left join customers on orders.customer_id = customers.id; Inner join regions on orders.shipping_region_id = regions.id");
    const four = joinsSummary(["a", "b", "c", "d"].map((table) => join({ table })));
    expect(four.endsWith("; and 2 more")).toBe(true);
    expect(four).not.toContain("join c");
  });

  it("mixes a bare table among full joins without losing it", () => {
    expect(joinsSummary([join(), { table: "regions" }])).toBe("Left join customers on orders.customer_id = customers.id; Join regions: choose the matching column");
  });
});
