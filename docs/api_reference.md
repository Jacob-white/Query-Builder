# Query-Builder API Reference 📖

Complete, exhaustive reference documentation for the Python Engine and the React UI / Headless SDK.

---

# Table of Contents
1. [Volume 1: Python Engine Public API (`query_builder`)](#volume-1-python-engine-public-api-query_builder)
   - [1. Data Models (`query_builder.models`)](#1-data-models-query_buildermodels)
   - [2. ORM & Schema Adapters (`query_builder.adapters`)](#2-orm--schema-adapters-query_builderadapters)
   - [3. Bidirectional Schema Converters (`query_builder.schema_converters`)](#3-bidirectional-schema-converters-query_builderschema_converters)
   - [4. Enterprise Security Governor & CLAC (`query_builder.policy`)](#4-enterprise-security-governor--clac-query_builderpolicy)
   - [5. Query Compiler & Analytical Expressions (`query_builder.compiler`)](#5-query-compiler--analytical-expressions-query_buildercompiler)
   - [6. Dialect Subsystem (`query_builder.dialects`)](#6-dialect-subsystem-query_builderdialects)
   - [7. Connectors & Async Connection Pooling (`query_builder.connectors`, `query_builder.async_pool`)](#7-connectors--async-connection-pooling-query_builderconnectors-query_builderasync_pool)
   - [8. AST Safety Validator (`query_builder.ast_validator`)](#8-ast-safety-validator-query_builderast_validator)
   - [9. Turnkey Framework Integrations (`query_builder.integrations`)](#9-turnkey-framework-integrations-query_builderintegrations)
   - [10. Model Context Protocol (MCP) Server & CLI (`query_builder.mcp_server`, `query_builder.cli`)](#10-model-context-protocol-mcp-server--cli-query_buildermcp_server-query_buildercli)
2. [Volume 2: React Component Library & Headless SDK (`@jacob-white/query-builder-react`)](#volume-2-react-component-library--headless-sdk-jacob-whitequery-builder-react)
   - [1. Subpath Entry Points](#1-subpath-entry-points)
   - [2. TypeScript Types & Interfaces](#2-typescript-types--interfaces)
   - [3. First-Class Typed API Client (`/client`)](#3-first-class-typed-api-client-client)
   - [4. Composable Compound Components (`/components/compound`)](#4-composable-compound-components-componentscompound)
   - [5. Visual Query Builder (`<VisualQueryBuilder>`)](#5-visual-query-builder-visualquerybuilder)
   - [6. TypeScript ORM Adapters & Exporters (`/adapters`)](#6-typescript-orm-adapters--exporters-adapters)
   - [7. Client-Side OLAP Engine & Ingest (`/olap`)](#7-client-side-olap-engine--ingest-olap)
   - [8. Headless React Hooks (`/hooks`)](#8-headless-react-hooks-hooks)
   - [9. Theming & Provider (`QueryBuilderProvider`, `ThemeProvider`)](#9-theming--provider-querybuilderprovider-themeprovider)
   - [10. Extension Points (Custom Operators, Custom Field Renderers)](#10-extension-points-custom-operators-custom-field-renderers)

---

# Volume 1: Python Engine Public API (`query_builder`)

## 1. Data Models (`query_builder.models`)

### `TableSchema`
Represents the structural metadata of a single database table.

```python
@dataclass
class TableSchema:
    name: str
    columns: list[ColumnSchema] = field(default_factory=list)
    schema: str = "public"
    comment: str | None = None
    primary_keys: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)
```

**Methods**:
- `to_dict() -> dict[str, Any]`: Serializes table metadata into a JSON-compatible dictionary.
- `to_table_meta() -> TableMeta`: Normalizes to internal compiler `TableMeta`.

---

### `ColumnSchema`
Represents an individual column definition.

```python
@dataclass
class ColumnSchema:
    name: str
    data_type: str = "text"
    is_nullable: bool = True
    is_primary: bool = False
    default: Any = None
    comment: str | None = None
    enums: list[str] | None = None
    foreign_key: ForeignKey | None = None
```

---

### `ForeignKey`
Represents a relational foreign key constraint between two tables.

```python
@dataclass
class ForeignKey:
    table: str
    column: str
    foreign_table: str
    foreign_column: str
    constraint_name: str | None = None
```

---

### `QuerySpec`
Declarative specification for building and compiling a SQL query.

```python
@dataclass
class QuerySpec:
    table: str
    columns: list[str | dict[str, Any]] = field(default_factory=list)
    joins: list[dict[str, Any] | JoinSpec] = field(default_factory=list)
    filters: list[dict[str, Any] | FilterSpec] = field(default_factory=list)
    filter_join: str = "AND"  # "AND" | "OR"
    having: list[dict[str, Any] | HavingSpec] = field(default_factory=list)
    order_by: list[dict[str, Any] | OrderBySpec] = field(default_factory=list)
    limit: int = 50
    offset: int = 0
    distinct: bool = False
    tenant_id: Any = None
    vector_search: VectorSearchSpec | dict[str, Any] | None = None
    hybrid_search: HybridSearchSpec | dict[str, Any] | None = None
    ctes: list[CteSpec | dict[str, Any]] = field(default_factory=list)
    window_functions: list[WindowFunctionSpec | dict[str, Any]] = field(
        default_factory=list
    )
    set_operations: list[SetOperationSpec | dict[str, Any]] = field(
        default_factory=list
    )
    grouping_type: str | None = None  # "standard" | "rollup" | "cube" | "grouping_sets"
    grouping_sets: list[list[str]] | GroupingSetsSpec = field(default_factory=list)
    rollup: RollupSpec | None = None
    cube: CubeSpec | None = None
    pivot: PivotSpec | dict[str, Any] | None = None
```

**Filter combiners.** Each filter may carry `combiner: "AND" | "OR"`, the operator
joining it to the *previous* filter (the first filter's combiner is unused).
Missing or invalid values fall back to the spec's `filter_join` (itself
whitelisted to `AND`/`OR`). `parse_sql_to_spec` emits per-filter combiners once
the `WHERE` clause contains an `OR`, so `a AND b OR c` round-trips with SQL
precedence. Filters produced by `apply_security_policy` (tenant isolation and
row-level rules) are marked with the internal key `_enforced`; the compiler
emits them as standalone `AND`-ed `WHERE` predicates outside the client filter
group, and any client-supplied `_enforced` / `enforced` key is stripped.

---

### `WindowFunctionSpec` (Alias: `WindowSpec`)
Specification of an advanced window function with partition, order, and framing.

```python
@dataclass
class WindowFunctionSpec:
    function: (
        str  # e.g. "ROW_NUMBER", "RANK", "DENSE_RANK", "SUM", "AVG", "LAG", "LEAD"
    )
    arguments: list[Any] = field(default_factory=list)
    partition_by: list[str] = field(default_factory=list)
    order_by: list[dict[str, Any] | OrderBySpec] = field(default_factory=list)
    frame: WindowFrameSpec | dict[str, Any] | None = None
    alias: str | None = None
```

---

### `WindowFrameSpec`
Specification of window function frame bounds (ROWS, RANGE, GROUPS).

```python
@dataclass
class WindowFrameSpec:
    frame_type: str = "ROWS"  # "ROWS" | "RANGE" | "GROUPS"
    start: str = "UNBOUNDED PRECEDING"  # e.g. "UNBOUNDED PRECEDING", "1 PRECEDING", "CURRENT ROW"
    end: str | None = None  # e.g. "CURRENT ROW", "1 FOLLOWING", "UNBOUNDED FOLLOWING"
    exclusion: str | None = None  # e.g. "CURRENT ROW", "GROUP", "TIES", "NO OTHERS"
```

---

### `RollupSpec`, `CubeSpec`, `GroupingSetsSpec`, `PivotSpec`
Analytical grouping and cross-tabulation specifications:

```python
@dataclass
class RollupSpec:
    columns: list[str] = field(default_factory=list)


@dataclass
class CubeSpec:
    columns: list[str] = field(default_factory=list)


@dataclass
class GroupingSetsSpec:
    sets: list[list[str]] = field(default_factory=list)


@dataclass
class PivotSpec:
    aggregate: str
    column: str
    values: list[Any] = field(default_factory=list)
    alias: str | None = None
```

---

### `CaseWhenSpec` & `CaseWhenBranch`
Conditional SQL column expressions (`CASE WHEN ... THEN ... ELSE ... END`).

```python
@dataclass
class CaseWhenBranch:
    condition: FilterSpec | dict[str, Any]
    then_value: Any = None
    then_column: str | None = None


@dataclass
class CaseWhenSpec:
    branches: list[CaseWhenBranch | dict[str, Any]] = field(default_factory=list)
    else_value: Any = None
    else_column: str | None = None
    alias: str | None = None
```

---

### `SetOperationSpec`
Set operations chaining multiple queries.

```python
@dataclass
class SetOperationSpec:
    operation: str = "UNION"  # "UNION" | "UNION ALL" | "INTERSECT" | "EXCEPT" | "MINUS"
    query: QuerySpec | dict[str, Any] = field(default_factory=dict)
```

---

### `CteSpec`
Common Table Expression (WITH stage) specification in a DAG pipeline.

```python
@dataclass
class CteSpec:
    name: str
    query: QuerySpec | dict[str, Any]
```

---

## 2. ORM & Schema Adapters (`query_builder.adapters`)

All adapters convert third-party schema sources into `SchemaDict` (`dict[str, TableSchema]`).

### `from_prisma(source: str | dict[str, Any]) -> SchemaDict`
Parses Prisma schema files, DSL text strings, or Prisma DMMF JSON representations.
- **Parameters**: `source`: Path to `schema.prisma`, Prisma DSL string, or parsed DMMF dict.
- **Features**: Extracts `@id`, `@map`, `@@map`, `enum` declarations, `@relation` foreign keys, and scalar types.

### `from_drizzle(source: str | dict[str, Any]) -> SchemaDict`
Parses Drizzle ORM TypeScript schema files or code strings.
- **Parameters**: `source`: Path to TypeScript schema file (`schema.ts`), source code string, or structured table definitions.
- **Features**: Supports PostgreSQL (`pgTable`), MySQL (`mysqlTable`), and SQLite (`sqliteTable`) declarations, `.primaryKey()`, `.references()`, `.notNull()`, and custom column names.

### `from_sqlalchemy(source: Any) -> SchemaDict`
Dual-mode adapter supporting live SQLAlchemy reflection and zero-dependency AST parsing of Python source code.
- **Parameters**: `source`: SQLAlchemy `MetaData` instance, Declarative Model class, list of Models, or Python model file path / string.

### `from_json_schema(source: str | dict[str, Any]) -> SchemaDict`
Parses JSON Schema (Draft 4/7/2020-12) or OpenAPI 3.x specifications into `TableSchema` models.
- **Features**: Resolves internal `$ref` links to foreign key relationships, maps `x-primary-keys`, and infers enum constraints.

### `to_schema_snapshot(tables: dict[str, TableSchema] | list[TableSchema] | TableSchema) -> SchemaSnapshot`
Normalizes tables, foreign keys, and bidirectional relationships into a unified `SchemaSnapshot`.

---

## 3. Bidirectional Schema Converters (`query_builder.schema_converters`)

Exports `SchemaSnapshot` or `TableSchema` dictionaries into production-ready ORM definitions:

### `to_prisma_schema(tables: Any, provider: str = "postgresql") -> str`
Generates a complete, syntax-validated `.prisma` schema file with models, fields, types, and `@relation` directives.

### `to_drizzle_schema(tables: Any, dialect: str = "postgres") -> str`
Generates clean Drizzle ORM TypeScript code importing dialect-specific table and column primitives (`pgTable`, `mysqlTable`, `sqliteTable`).

### `to_sqlalchemy_models(tables: Any, base_class_name: str = "Base") -> str`
Generates production-grade SQLAlchemy Declarative Base Python code with `Column`, `ForeignKey`, and type mappings.

---

## 4. Enterprise Security Governor & CLAC (`query_builder.policy`)

### `SecurityPolicy` (Alias: `SecurityGovernor`)
Configuration for multi-tenant isolation, Column-Level Access Control (CLAC), and pre-execution AST complexity quotas:

```python
@dataclass
class SecurityPolicy:
    allowed_tables: list[str] | None = None
    restricted_tables: list[str] = field(default_factory=list)
    tenant_column: str = "tenant_id"
    enforce_tenant_isolation: bool = True
    row_level_filters: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    column_masking: dict[str, list[str]] = field(default_factory=dict)
    sensitive_column_patterns: list[str] = field(default_factory=list)
    masking_strategy: str = "redact"  # "redact" | "hash" | "partial"
    max_complexity_score: int | None = None
    column_permissions: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    table_policy: TablePolicy | None = None
    column_policies: dict[str, ColumnPolicy | dict[str, Any]] | None = None
    row_policies: dict[str, RowPolicy | list[dict[str, Any]]] | None = None
```

### Policy Specification Helpers
- `TablePolicy(allowed_tables=..., restricted_tables=...)`: Table-level authorization rules.
- `ColumnPolicy(allowed_roles=..., restricted_columns=...)`: Role-based column access control.
- `RowPolicy(filters=...)`: Dynamic attribute predicates.

### `TenantContext`
Authentication context accompanying query execution:
```python
@dataclass
class TenantContext:
    tenant_id: str
    user_id: str | None = None
    roles: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
```

### `apply_security_policy(spec, schema=None, context=None, policy=None) -> dict[str, Any]`
Validates and transforms query spec according to tenant context and security policy. Fails closed on:
- Missing or empty `tenant_id` when `enforce_tenant_isolation=True`.
- Query complexity exceeding `max_complexity_score`.
- Unauthorized table references or column references lacking required roles.
- Injects dynamic `$attr.key` predicates from `context.attributes`.

---

## 5. Query Compiler & Analytical Expressions (`query_builder.compiler`)

### `QueryCompiler` (Alias: `AnalyticalCompiler`)
Translates declarative JSON query specs into safe, parameterized SQL with bind parameters across 71+ dialects.

```python
class QueryCompiler:
    def __init__(
        self,
        spec: dict[str, Any] | QuerySpec,
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        force_user_filter: bool = False,
        tenant_id: Any = None,
        dialect: str | BaseDialect | None = None,
        max_limit: int = 100,
        validate_spec: bool = True,
    ) -> None: ...

    def compile(
        self, context: dict[str, Any] | None = None
    ) -> tuple[str, list[Any], str, list[Any]]: ...
```

**Returns**: `(main_sql, main_params, count_sql, count_params)`

### Custom Filter Operators
- `register_filter_operator(name: str, handler: Callable[..., tuple[str, list[Any]]]) -> None`
- `unregister_filter_operator(name: str) -> None`
- `list_filter_operators() -> list[str]`

---

## 6. Dialect Subsystem (`query_builder.dialects`)

Supports 71+ database and query engine dialects:
- `get_dialect(name: str) -> BaseDialect`
- `list_dialects() -> list[str]`
- `register_dialect(name: str, dialect_cls_or_instance: Any) -> None`
- `quote_identifier(ident: str, dialect: str = "postgres") -> str`
- `quote_alias(alias: str, dialect: str = "postgres") -> str`

---

## 7. Connectors & Async Connection Pooling (`query_builder.connectors`, `query_builder.async_pool`)

### `BaseConnector` & `SQLiteConnector`
Synchronous database connector executing queries with automatic AST validation and latency measurement:
- `execute(spec=..., timeout_ms=...) -> dict[str, Any]`
- `introspect_schema(filter_sensitive: bool = True) -> dict[str, Any]`
- `test_connection() -> dict[str, Any]`

### `AsyncConnectionPool` (Alias: `AsyncQueryPool`)
High-concurrency, non-blocking connection pool for asyncio applications:
```python
class AsyncConnectionPool:
    def __init__(
        self,
        factory: Callable[[], Awaitable[Any] | Any] | None = None,
        max_size: int = 10,
        min_size: int = 0,
        timeout: float = 30.0,
        max_idle_seconds: float = 300.0,
        max_lifespan_seconds: float = 3600.0,
        health_check_sql: str = "SELECT 1",
        connector_name: str | None = None,
        connector: Any = None,
        **connection_kwargs: Any,
    ) -> None: ...

    async def initialize(self) -> None: ...
    async def acquire(self, token: AsyncCancellationToken | None = None) -> Any: ...
    async def release(self, conn: Any) -> None: ...
    def connection(
        self, token: AsyncCancellationToken | None = None
    ) -> AsyncIterator[Any]: ...
    async def close(self) -> None: ...
```

### `AsyncCancellationToken`
Cooperative cancellation token to abort long-running asynchronous queries on socket level:
- `cancel() -> None`: Signals cancellation and triggers callbacks.
- `is_cancelled: bool`: Returns cancellation status.
- `throw_if_cancelled() -> None`: Raises `QueryCancelledError` if cancelled.

### `async_execute(...)` & `AsyncStreamingExecutor`
Asynchronously executes specifications against async or sync connectors with timeout cancellation:
- `AsyncStreamingExecutor.execute_stream(connector, spec, batch_size=1000, **kwargs) -> Any`: Executes query against connector asynchronously.
- `AsyncStreamingExecutor.export_stream(connector, spec, format="csv", chunk_size=1000, **kwargs) -> tuple[Iterator[bytes], str, str]`: Streams query dataset export in chunked bytes along with `(mime_type, file_extension)`.
- `stream_export_dataset(data, format="csv", columns=None, chunk_size=1000) -> tuple[Iterator[bytes], str, str]`: High-throughput chunk generator for HTTP streaming responses.

---

## 8. AST Safety Validator (`query_builder.ast_validator`)

### `validate_sql_ast(sql: str, allowed_statements: set[str] | None = None) -> dict[str, Any]`
Parses SQL using AST tokens to enforce strict read-only execution:
- Rejects mutation keywords (`RESTRICTED_MUTATION_KEYWORDS`: `DELETE`, `DROP`, `UPDATE`, `INSERT`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, etc.).
- Rejects multi-statement semicolons.
- Restricts access to sensitive system tables (`RESTRICTED_SECURITY_TABLES`: `AUTH_USER`, `PG_SHADOW`, `SQLITE_MASTER`, etc.).

### `validate_cte_dag(ctes: list[Any]) -> dict[str, Any]`
Validates CTE DAG pipelines for cyclic dependencies and self-references.

### `validate_window_function_spec(spec: Any) -> dict[str, Any]`
Validates window function frame bounds and functions.

---

## 9. Turnkey Framework Integrations (`query_builder.integrations`)

### FastAPI: `create_query_builder_router(...) -> APIRouter`
```python
def create_query_builder_router(
    connector: Any,
    security: SecurityPolicy | SecurityConfig | dict[str, Any] | None = None,
    tenant_resolver: Callable[[Request], TenantContext | Awaitable[TenantContext] | dict[str, Any] | str | None] | None = None,
    prefix: str = "",
    tags: list[str] | None = None,
) -> APIRouter
```
Exposes:
- `GET {prefix}/schema` (and alias `/introspect`)
- `POST {prefix}/compile`
- `POST {prefix}/validate`
- `POST {prefix}/execute`
- `POST {prefix}/export`

### Django Integration
- `create_django_urls(connector, security=None, tenant_resolver=None) -> list[Any]`: Standard Django URL patterns.
- `create_drf_views(connector, security=None, tenant_resolver=None) -> dict[str, type[APIView]]`: Django REST Framework APIViews (`SchemaView`, `CompileView`, `ValidateView`, `ExecuteView`, `ExportView`).
- `create_ninja_router(connector, security=None, tenant_resolver=None, tags=None) -> NinjaRouter`: Django Ninja router.

---

## 10. Model Context Protocol (MCP) Server & CLI (`query_builder.mcp_server`, `query_builder.cli`)

### MCP Server (`query-builder mcp`)
Standard JSON-RPC 2.0 stdio server providing AI agents with:
1. `query_builder_compile`: Compiles JSON QuerySpec into safe parameterized SQL.
2. `query_builder_validate`: Validates raw SQL statement AST.
3. `query_builder_explain_and_advise`: Returns query execution plan and optimization recommendations.
4. `query_builder_get_complexity`: Scores query AST complexity against governance quotas.
5. `query_builder_introspect`: Reflects database schema catalog.
6. `query_builder_execute`: Compiles and executes queries against configured connector.
7. `query_builder_join_path`: Discovers optimal multi-hop relational join paths.

### CLI Subcommands (`query-builder <command>`)
- `compile`: Compiles declarative spec JSON file to parameterized SQL.
- `validate`: AST safety check for raw SQL strings or JSON query spec files.
- `test-connection` (alias: `test`): Tests database reachability, health, and latency.
- `introspect`: Reverse-engineers database schema metadata and foreign key relationships.
- `export-schema` (alias: `export`): Converts schema snapshot into Prisma, Drizzle, or SQLAlchemy definitions.
- `join-path` (alias: `join`): Discovers shortest relational join path between tables via BFS graph solver.
- `serve`: Launches zero-dependency HTTP REST API microservice server with Swagger UI.
- `schema`: Inspects schema catalog structure and prints ASCII relationship trees.
- `mcp`: Launches the Model Context Protocol (MCP) JSON-RPC 2.0 stdio server.
- `init`: Scaffolds a turnkey Query-Builder starter project (`fullstack`, `fastapi`, `minimal`).
- `doctor`: Diagnoses environment dependencies and installed connector drivers.

---

# Volume 2: React Component Library & Headless SDK (`@jacob-white/query-builder-react`)

## 1. Subpath Entry Points

```typescript
// Core visual components, provider, and theming
import { VisualQueryBuilder, QueryBuilderProvider } from "@jacob-white/query-builder-react";

// First-class typed API client and fluent query builder
import { createQueryBuilderClient, createQuery, FluentQuery } from "@jacob-white/query-builder-react/client";

// TypeScript ORM schema adapters and bidirectional exporters
import { fromPrisma, toPrismaSchema, fromDrizzle, toDrizzleSchema } from "@jacob-white/query-builder-react/adapters";

// Unstyled headless React hooks
import { useQueryBuilder, useQueryExecution, useSchemaIntrospection } from "@jacob-white/query-builder-react/hooks";

// In-memory client OLAP SQL engine and local file ingestion
import { getClientOlapEngine, ingestLocalFile } from "@jacob-white/query-builder-react/olap";
```

---

## 2. TypeScript Types & Interfaces

```typescript
export interface TableSchema {
  name: string;
  schema?: string;
  columns: ColumnSchema[];
  primary_keys?: string[];
  foreign_keys?: ForeignKey[];
  enums?: Record<string, string[]>;
  comment?: string;
}

export interface ColumnSchema {
  name: string;
  data_type: string;
  is_nullable?: boolean;
  is_primary?: boolean;
  default?: any;
  comment?: string;
  enums?: string[];
  foreign_key?: ForeignKey;
}

export interface SchemaSnapshot {
  tables: Record<string, TableMeta>;
  foreign_keys: ForeignKeyMeta[];
  relationships: RelationshipMeta[];
  categories?: Record<string, string[]>;
}

export interface QueryResultData {
  columns: string[];
  rows: Record<string, unknown>[];
  count: number;
  limit?: number;
  offset?: number;
  page?: number;
  latency_ms?: number;
  dialect?: string;
}

export interface VisualQueryBuilderRef {
  getSpec: () => QuerySpec;
  getSql: () => string;
  setSpec: (newSpec: QuerySpec) => void;
  reset: () => void;
  execute: () => Promise<QueryResultData | void>;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
}
```

---

## 3. First-Class Typed API Client (`/client`)

### `createQueryBuilderClient(config: QueryBuilderClientConfig): QueryBuilderClient`

```typescript
export interface QueryBuilderClientConfig {
  baseUrl: string;
  headers?: Record<string, string> | (() => Promise<Record<string, string>> | Record<string, string>);
  token?: string | (() => Promise<string | null | undefined> | string | null | undefined);
  timeoutMs?: number;
  fetchFn?: typeof fetch;
}
```

**Methods**:
- `getSchema(options?: RequestOptions): Promise<SchemaSnapshot>`
- `compile(spec: QuerySpec, dialect?: SqlDialect, options?: RequestOptions): Promise<CompileResult>`
- `validate(sql: string, options?: RequestOptions): Promise<SqlSafetyValidation>`
- `execute(specOrSql: QuerySpec | { sql: string; params?: any[] }, options?: RequestOptions): Promise<QueryResultData>`
- `export(spec: QuerySpec, format: "csv" | "json" | "parquet" | "excel" | "arrow", options?: RequestOptions): Promise<Blob>`
- `query(table?: string): FluentQuery`

### `createQuery(table?: string, client?: QueryBuilderClient): FluentQuery`
Chainable builder constructing `QuerySpec` objects with `.from()`, `.select()`, `.join()`, `.where()`, `.groupBy()`, `.having()`, `.orderBy()`, `.distinct()`, `.limit()`, and `.execute()`.

---

## 4. Composable Compound Components (`/components/compound`)

Build customized layouts with slotted atomic primitives:
- `<QueryBuilderRoot schema={...} initialTable={...} dialect={...} classNames={...}>`: State and context container.
- `<QueryBuilderCanvas>`: Visual entity-relationship table card diagram.
- `<QueryBuilderColumns>`: Projection selector, aliases, and aggregations.
- `<QueryBuilderFilters>`: Multi-operator filter criteria builder.
- `<QueryBuilderJoins>`: Relational join configurator.
- `<QueryBuilderSorts>`: Column order-by manager.
- `<QueryBuilderSqlEditor>`: Live syntax-highlighted SQL viewer/editor.
- `<QueryBuilderResults>`: Tabular results viewer with pagination and export.

---

## 5. Visual Query Builder (`<VisualQueryBuilder>`)

Full-featured visual query workspace.

```tsx
interface VisualQueryBuilderProps {
  schema: DatabaseSchemaDefinition | SchemaSnapshot | TableSchema[];
  initialTable?: string;
  dialect?: SqlDialect;
  value?: QuerySpec;
  onChange?: (spec: QuerySpec) => void;
  client?: QueryBuilderClient;
  ref?: React.Ref<VisualQueryBuilderRef>;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData>;
  theme?: "dark" | "light" | "auto" | QueryBuilderTheme;
  unstyled?: boolean;
  readOnly?: boolean;
  classNames?: Partial<QueryBuilderClassNames>;
}
```

### Schema Diagnostics: `validateSchema(schema)`
```typescript
const diagnostics: SchemaValidationResult = validateSchema(schema);
// { valid: boolean, diagnostics: SchemaDiagnostic[], errors: [], warnings: [], infos: [] }
```

---

## 6. TypeScript ORM Adapters & Exporters (`/adapters`)

Convert schemas directly in the browser or Node runtime:
- `fromPrisma(source)` / `toPrismaSchema(snapshot, options)`
- `fromDrizzle(source)` / `toDrizzleSchema(snapshot, options)`
- `fromSqlAlchemy(source)` / `toSqlAlchemyModels(snapshot, options)`
- `fromJsonSchema(source)`
- `toSchemaSnapshot(tables)`
- `createSemanticModel(definition)` & `attachSemanticModelsToTables(schema, models)`

---

## 7. Client-Side OLAP Engine & Ingest (`/olap`)

### `InMemoryOlapEngine`
Pure TypeScript columnar in-memory execution engine with zero external wasm runtime dependencies:
- `query(sql: string): Promise<DuckDBQueryResult>`
- `ingestCsv(tableName: string, csvText: string, options?: DuckDBIngestOptions): Promise<DuckDBTableMeta>`
- `ingestJson(tableName: string, rows: Record<string, any>[]): Promise<DuckDBTableMeta>`
- `ingestParquet(tableName: string, buffer: ArrayBuffer): Promise<DuckDBTableMeta>`
- `getSchemaSnapshot(): SchemaSnapshot`
- `dropTable(tableName: string): Promise<void>`
- `clear(): Promise<void>`

### Helper Functions:
- `getClientOlapEngine(config?: DuckDBDriverConfig): InMemoryOlapEngine`: Global singleton accessor.
- `ingestLocalFile(file, engine, options?)` / `ingestLocalFile(engine, file, options?)`: Detects format and streams CSV/TSV/JSON/Parquet file directly into memory. Accepts either parameter order and either string table name or `{ tableName?: string }` options object.

---

## 8. Headless React Hooks (`/hooks`)

### `useQueryBuilder(options)`
Zero-CSS state machine hook managing selected columns, joins, filters, sorting, and compilation.
- Returns `{ state, compiled, currentSql, safety, actions }`.

### `useQueryExecution(options)`
Execution lifecycle controller with abort cancellation, latency tracking, and error handling.
- Returns `{ results, isLoading, error, latencyMs, executeQuery, cancelExecution, clearResults }`.

### `useSchemaIntrospection(options)`
Fetches, caches, and normalizes remote database schemas.

---

## 9. Theming & Provider (`QueryBuilderProvider`, `ThemeProvider`)

Container-scoped CSS custom properties:
- `--qb-color-primary`: Accent color.
- `--qb-color-background`: Container background.
- `--qb-color-surface`: Card and surface background.
- `--qb-color-border`: Border and divider color.
- `--qb-color-text`: Primary text.
- `--qb-color-text-muted`: Subdued label text.
- `--qb-radius-md`: Medium border radius.

---

## 10. Extension Points (Custom Operators, Custom Field Renderers)

### Custom Filter Operators
```tsx
const customOperators = {
  TAX_EXEMPT: {
    value: "TAX_EXEMPT",
    label: "Is Tax Exempt",
    hasValue: false,
    formatSql: (colRef) => `${colRef} IS NOT NULL AND ${colRef} = 0`,
  },
};
```

### Custom Cell Renderers
```tsx
const cellRenderers = {
  price: (val: any) => (
    <span className="font-mono text-emerald-500 font-bold">
      ${Number(val).toFixed(2)}
    </span>
  ),
};
```

---

## 📄 License & Ownership

Query-Builder is open-source software owned and maintained by **HobbyHabbit LLC** under the **MIT License**. For security disclosures, see **[SECURITY.md](../SECURITY.md)**.
