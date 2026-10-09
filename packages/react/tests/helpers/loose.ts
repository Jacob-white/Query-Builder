/**
 * Deliberately-incomplete fixtures.
 *
 * Many tests exercise defensive/default-filling runtime paths by passing a spec, tile, result or
 * client that omits fields the static type requires. `loose<T>` keeps the provided keys
 * type-checked against `T` (typos and wrong value types are still compile errors) while
 * documenting, at the call site, that the object is intentionally incomplete. Unlike `makeSpec`
 * it does NOT fill defaults, so the runtime value is exactly what the test wrote.
 */
export function loose<T>(value: Partial<T>): T {
  return value as T;
}

/**
 * Hand-rolled mock (members are usually `vi.fn()`) presented as `T`. Member names are checked
 * against `T`; member types are not (mocks are intentionally loose).
 */
export function asMock<T>(mock: { [K in keyof T]?: unknown }): T {
  return mock as T;
}

/**
 * Typed read access to an engine's private row store, for tests that seed internal state
 * directly. Reflect avoids a cast at each call site.
 */
export function olapTableData(engine: object): Map<string, Record<string, unknown>[]> {
  return Reflect.get(engine, "tableData") as Map<string, Record<string, unknown>[]>;
}
