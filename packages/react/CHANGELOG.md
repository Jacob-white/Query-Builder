# Changelog

## Unreleased

### Fixed
- **Loading a spec into the builder (`loadSpec`, `specToState`)** now matches what the Join step and the column pickers
  expect:
  - A join kind in the compiler's form (`"INNER"`, `"left"`, `"FULL OUTER"`, ...) is converted to the builder's form
    (`"INNER JOIN"`, ...). Before, the kind was copied as written, so no kind was highlighted, and a join loaded as
    `"inner"` compiled back to SQL as a `LEFT JOIN`.
  - A spec with no `activeTables` now activates its base table **and every joined table**. Before, only the base table
    was active, and the builder offers a table's columns only while the table is active, so a joined table's pickers were
    blank. A spec that lists `activeTables` is unchanged.
  - A join that names no columns still loads as `id = id` (unchanged, for compatibility).

### Query UI helpers (new, pure, no React)
- New exports for building a query UI on top of the package, extracted from a host application's Query Builder page and
  tested on their own (`src/utils/queryHelpers`):
  - **Filter kinds:** `columnKind(dataType)`, `operatorsFor(kind)`, `operatorHelp(kind, op)`, `coerceValue(kind, op, raw)`
    (a value to send or an error message), `describeFilter(filter, kind)` and `prettyDate`. Plain-language operator labels,
    one-sentence help per operator, and value checks for numbers, dates, UUIDs, lists and ranges.
  - **Filters on aggregated values (HAVING):** `havingTargets`, `havingKind`, `havingForSpec`, `parseHaving`,
    `describeHaving`. `havingForSpec` keeps only filters whose aggregate is still in the spec's columns.
  - **Join proof:** `directLinks`, `linkedTables`, `isProvenJoin`, `describeLink`: which joins a declared foreign key backs.
  - **Summaries and columns:** `columnsSummary`, `joinsSummary`, `sortsSummary`, `conditionsSummary`, `windowSummary`,
    `subqueriesSummary`, `aggregatesFor(dataType)` (only the aggregates that fit a type), `typeLookup`, `columnsOf`.
  - **SQL file:** `sqlFilename(table)` and `sqlFileText(sql, table)` for a `.sql` download of the runnable statement from the
    Python `QueryCompiler.compile_runnable()`.
- The helper's value type is exported as `ConditionValue` (`FilterValue` is already the package's filter value type).

### Packaging
- `dist/` contains only the Vite bundles (`.mjs`/`.cjs`, chunks under `dist/chunks/`) and type
  declarations; `tsc` runs with `emitDeclarationOnly` and the output directory is emptied on every build.
- `"type": "module"`, `"sideEffects": false` (the package has no import-time side effects or CSS),
  separate `types` per export condition (`.d.ts` for `import`, `.d.cts` for `require`), `typesVersions`
  for legacy `node10` resolution. `publint --strict` and `attw --pack` are clean (`pnpm run check:package`).
- `react` is now a required peer dependency (the main entry and `./hooks` need it); `react-dom` stays an
  optional peer because nothing imports it. `./adapters`, `./client` and `./olap` do not import React.
- The npm tarball ships `dist/`, `README.md`, `CHANGELOG.md` and `LICENSE` only (no `src/`).
- New scripts: `clean`, `check:package`, `prepublishOnly` (clean, typecheck, build, test, check).

### Spec types and hook consolidation

- New exported `SerializedQuerySpec` (the documented, loosely-typed serialized spec: snake_case
  `QuerySpec`, the hooks' own camelCase state shape, or a saved preset) and `narrowSerializedSpec(input: unknown)`
  which validates/narrows untrusted input (non-objects become `{}`, wrongly-typed top-level fields are dropped).
- **Type change:** the loose `Record<string, unknown>` spec parameters are now `SerializedQuerySpec`:
  `useQueryBuilder({ initialSpec })`, `actions.loadSpec` (both hooks), `QueryTemplate.spec`, `SqlPreset.spec`,
  `QueryTemplateManagerProps.currentSpec`, `QueryPlaygroundProps.initialSpec`, `onSaveQuery`'s `spec`,
  `compileSpecToSql`, `estimateClientPlan` and `useSqlCompiler`. Object literals and `QuerySpec`s keep compiling;
  a value typed as an arbitrary `Record<string, unknown>` must be narrowed with `narrowSerializedSpec` first.
  `useQueryState` / `createInitialState` take the new `QueryStateInit` union (also accepts `Partial<QuerySpec>`).
- `stateToSpec` now takes the structural `SpecSourceState` (any `QueryState` / builder-like state still fits).
- Runtime: `loadSpec(null | undefined | non-object)` is now ignored instead of throwing, and `toggleColumn` no
  longer duplicates an already-present projection key.
- Internal: `useQueryBuilder` and `useQueryState` share one pure module (`utils/queryStateTransitions.ts`) for
  table/column/join/filter/sort/auto-join transitions and spec conversion; `specToState`/`stateToSpec` moved
  there (still exported from the package root and from `hooks/useQueryState`).

### Type tightenings (`any` removal) - breaking-change note for the next major release

The `any` -> `unknown` cleanup narrowed several public types. Wherever it could be done without
reintroducing `any`, compatibility was restored (callbacks are method-bivariant, filter values accept
lists and `null`, schema props accept adapter output, `execute()` accepts any object). What remains
is intentional and will be called out in the next major release:

- `QueryBuilderApiError.data` and `client.request<T>()` default to `unknown` (were `any`). Pass the
  expected shape explicitly: `client.request<MyRow[]>("/rows")`. Clients returned by
  `createQueryBuilderClient` now always expose `request` (it stays optional on the
  `QueryBuilderClient` interface so custom clients/mocks keep compiling).
- `MetricFilter.value`, `GlobalFilter.value`, `CrossFilterState.value` and `HAVING` values are
  `unknown`; narrow before use.
- `QuerySpec.filters[].value` is the new exported `FilterValue`
  (`string | number | boolean | null | ReadonlyArray<string | number | boolean | null>`), so
  consumers that *read* a filter value as `string | number | boolean` must narrow out `null` /
  arrays. Writers are unaffected (strictly wider).
- `CaseWhenSpec.else_value` is `string | number | null` (was `any`).
- `getAgentToolDefinitions(format)` returns a precise provider shape per format (`OpenAiTool[]`,
  `AnthropicTool[]`, `GeminiTool[]`, `LangChainTool[]`, `McpTool[]`); `executeAgentToolCall` returns
  an `AgentToolResult` (`success`, `sql?: string`, `spec?`, ... plus an index signature for the
  tool-specific extras, which are `unknown`). All of these types are exported from the package root.
- `parseSqlToSpec` now returns `QuerySpec | null` (was `Partial<QuerySpec> | null`); assignable to
  every previous use.
- `useLiveExecution().executeQuery` accepts `string | object`; `useStreamingQuery().execute` accepts
  `object` (QuerySpec interfaces included).
- `useQueryExecution().executeQuery(sql, spec?)` and the compound `executeQuery` take
  `QuerySpec | null` instead of `Record<string, unknown>`.

### `null` specs from raw-SQL mode

`VisualQueryBuilder` in raw-SQL mode cannot always map the SQL to a `QuerySpec` (for example while
typing `SELECT`). The public types now say so instead of casting:

- `VisualQueryBuilderRef.getSpec(): QuerySpec | null`
- `onChange?: (spec: QuerySpec | null, sql: string) => void`
- `onExecuteQuery?: (sql: string, spec?: QuerySpec | null) => ...` (`ExecuteQueryHandler`, method
  bivariant)

Handlers that dereference `spec` must now handle `null`. The "A visual edit replaced your custom SQL"
notice is now semantic: it only appears when the raw SQL does not parse, contains SQL comments, or
does not recompile to what the canvas shows.

### Fixes

- `useStreamingQuery`: `execute` identity is stable (options live in a latest-ref), the hook no longer
  aborts its own in-flight request, StrictMode double-invoke restarts the auto-run, and a superseded
  run can no longer clear `isStreaming` of the active run.
- SQL parser: legal join aliases such as `final`, `sample`, `settings`, `partition`, `ignore`, `use`,
  `force` are kept; table hints (`WITH (NOLOCK)`, `FORCE|USE|IGNORE INDEX (...)`, `PARTITION (...)`)
  are recognised structurally.
- Filter combiners are resolved once (`utils/filterCombiners`), coerced to exactly `AND` / `OR`
  (case-insensitive), and the emitted per-filter combiners, `filter_join` and SQL always agree. This
  also closes a SQL-injection vector through free-form `combiner` strings, and whitelists window
  frame/direction/function tokens, paren grouping and time grains in the client compiler.
- `useQueryBuilder({ initialSpec })` now accepts a QuerySpec-shaped spec (converted exactly like
  `actions.loadSpec`); state-shaped `initialSpec` keeps working.
- `ingestLocalFile` accepts Proxy / function-target (RPC facade) engines again.
- `NlqPromptBar` / `AiAssistantWidget` / `useBringYourOwnAi` `schema` accept `TableSchema[]` and
  `DatabaseSchemaDefinition` (`ByoAiSchema`).
- `cellRenderers` callbacks are method-bivariant (`(v: number) => ...` is assignable).
