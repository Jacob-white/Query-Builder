# Query-Builder API Reference 📖

Complete, exhaustive reference documentation for the Python Engine and the React UI / Headless SDK.

---

# Table of Contents
1. [Volume 1: Python Engine Public API (`query_builder`)](#volume-1-python-engine-public-api-query_builder)
   - [1. Data Models (`query_builder.models`)](#1-data-models-query_buildermodels)
   - [2. ORM & Schema Adapters (`query_builder.adapters`)](#2-orm--schema-adapters-query_builderadapters)
   - [3. Engine Configuration & Security Profiles (`query_builder.config`)](#3-engine-configuration--security-profiles-query_builderconfig)
   - [4. Query Compiler & Custom Operators (`query_builder.compiler`)](#4-query-compiler--custom-operators-query_buildercompiler)
   - [5. Dialect Subsystem (`query_builder.dialects`)](#5-dialect-subsystem-query_builderdialects)
   - [6. Connector Subsystem (`query_builder.connectors`)](#6-connector-subsystem-query_builderconnectors)
   - [7. AST Safety Validator (`query_builder.ast_validator`)](#7-ast-safety-validator-query_builderast_validator)
   - [8. Relational Join Solver (`query_builder.join_solver`)](#8-relational-join-solver-query_builderjoin_solver)
   - [9. Native HTTP Microservice Server (`query_builder.server`)](#9-native-http-microservice-server-query_builderserver)
2. [Volume 2: React Component Library & Headless SDK (`@jacob-white/query-builder-react`)](#volume-2-react-component-library--headless-sdk-jacob-whitequery-builder-react)
   - [1. TypeScript Types & Interfaces](#1-typescript-types--interfaces)
   - [2. TypeScript ORM Adapters (`/adapters`)](#2-typescript-orm-adapters-adapters)
   - [3. Theming & Provider (`QueryBuilderProvider`, `ThemeProvider`)](#3-theming--provider-querybuilderprovider-themeprovider)
   - [4. Headless React Hooks (`/hooks`)](#4-headless-react-hooks-hooks)
   - [5. Visual UI Components (`/components`)](#5-visual-ui-components-components)
   - [6. Extension Points (Custom Operators, Custom Field Renderers)](#6-extension-points-custom-operators-custom-field-renderers)

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
    primary_keys: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    schema: str | None = None
    comment: str | None = None
    enums: dict[str, list[str]] = field(default_factory=dict)
```

**Methods**:
- `to_dict() -> dict[str, Any]`: Serializes table metadata into a JSON-compatible dictionary.
- `get_column(name: str) -> ColumnSchema | None`: Finds a column by case-insensitive name.

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
    default: Any | None = None
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
Declarative query specification representation.

```python
@dataclass
class QuerySpec:
    table: str
    columns: list[str | dict[str, Any]] = field(default_factory=list)
    joins: list[dict[str, Any]] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    filter_join: str = "AND"
    order_by: list[dict[str, Any]] = field(default_factory=list)
    having: list[dict[str, Any]] = field(default_factory=list)
    limit: int | None = 50
    offset: int | None = 0
    distinct: bool = False
    tenant_id: Any | None = None
```

---

### `SchemaSnapshot`
Complete multi-table schema catalog including tables, relationships, and categories.

```python
@dataclass
class SchemaSnapshot:
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    foreign_keys: list[dict[str, str]] = field(default_factory=list)
    relationships: list[dict[str, str]] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=dict)
```

---

## 2. ORM & Schema Adapters (`query_builder.adapters`)

All adapters convert third-party schemas into `SchemaDict` (`dict[str, TableSchema]`).

### `from_prisma(source: str | dict[str, Any]) -> SchemaDict`
Parses Prisma schema files, DSL text strings, or Prisma DMMF JSON representations.
- **Parameters**:
  - `source`: File path to `schema.prisma`, raw Prisma DSL string, or parsed DMMF dict.
- **Returns**: `SchemaDict` mapping table names to `TableSchema` instances.
- **Features**: Extracts `@id`, `@map`, `@@map`, `enum` declarations, `@relation` foreign keys, and field types.

---

### `from_drizzle(source: str | dict[str, Any]) -> SchemaDict`
Parses Drizzle ORM TypeScript schema files or code strings.
- **Parameters**:
  - `source`: File path to TypeScript schema file (`schema.ts`), TypeScript source code string, or structured table definitions.
- **Returns**: `SchemaDict`.
- **Features**: Supports PostgreSQL (`pgTable`), MySQL (`mysqlTable`), and SQLite (`sqliteTable`) declarations, `.primaryKey()`, `.references()`, `.notNull()`, and custom column names.

---

### `from_sqlalchemy(source: Any) -> SchemaDict`
Dual-mode adapter supporting live SQLAlchemy reflection and zero-dependency AST parsing of Python source code.
- **Parameters**:
  - `source`: SQLAlchemy `MetaData` instance, Declarative Model class, list of Models, or Python model file path / string.
- **Returns**: `SchemaDict`.
- **Features**: Extracts Column types, nullable constraints, primary keys, `ForeignKey` constraints, and composite keys.

---

### `from_json_schema(source: str | dict[str, Any]) -> SchemaDict`
Parses JSON Schema (Draft 4/7/2020-12) or OpenAPI 3.x specifications into `TableSchema` models.
- **Parameters**:
  - `source`: File path, JSON string, or Python dictionary. Supports OpenAPI `components.schemas`, JSON Schema `$defs` / `definitions`, and direct table maps.
- **Returns**: `SchemaDict`.
- **Features**: Resolves internal `$ref` links to foreign key relationships, maps `x-primary-keys`, and infers enum constraints.

---

### `to_schema_snapshot(tables: dict[str, TableSchema] | list[TableSchema] | TableSchema) -> SchemaSnapshot`
Synthesizes a full `SchemaSnapshot` from `TableSchema` models, normalizing foreign keys and bidirectional relationships.

---

## 3. Engine Configuration & Security Profiles (`query_builder.config`)

### `configure_query_builder(...) -> QueryBuilderConfig`
Thread-safe global configuration manager for Query-Builder.

```python
def configure_query_builder(
    config: QueryBuilderConfig | None = None,
    default_dialect: str | None = None,
    security: SecurityConfig | None = None,
    profile: str | None = None,
    dialects: dict[str, Any] | None = None,
    connectors: dict[str, Any] | None = None,
    custom_operators: dict[str, Any] | None = None,
    default_limit: int | None = None,
    **security_kwargs: Any,
) -> QueryBuilderConfig
```

**Parameters**:
- `profile`: Preset security profile name: `"development"`, `"production"`, or `"strict"`.
- `default_dialect`: Default SQL dialect (e.g. `"sqlite"`, `"postgres"`, `"snowflake"`).
- `security`: Explicit `SecurityConfig` dataclass instance.
- `default_limit`: Default row limit for queries when not specified.
- `dialects`: Custom dialect mapping to register.
- `connectors`: Custom connector mapping to register.
- `custom_operators`: Custom filter operators mapping to register.

---

### `SecurityProfile`
Factory providing standard security configuration presets.

- `SecurityProfile.development()`: Relaxed settings for local development. Allows private/loopback networks, relaxed TLS, longer timeouts (30s), permits system catalog introspection.
- `SecurityProfile.production()`: Hardened zero-trust defaults. Blocks private networks/SSRF, enforces TLS and cert verification, enforces read-only sessions, 5s statement timeout, 1000 row max limit, AST complexity governance.
- `SecurityProfile.strict()`: Hardened enterprise/financial profile. 3s statement timeout, 500 row max limit, join depth capped at 3, comprehensive audit logging.

---

## 4. Query Compiler & Custom Operators (`query_builder.compiler`)

### `QueryCompiler`
Translates declarative JSON query specs into safe, parameterized SQL with bind parameters.

```python
class QueryCompiler:
    def __init__(
        self,
        spec: dict[str, Any] | Any,
        schema: dict[str, Any] | None = None,
        user_id: Any = None,
        force_user_filter: bool = False,
        tenant_id: Any = None,
        dialect: str | BaseDialect | None = None,
        ownership_paths: dict[str, list[list[tuple[str, str, str]]]] | None = None,
        max_limit: int = 100,
        validate_spec: bool = True,
        allow_unknown_keys: bool = False,
        middleware: Any = None,
    ) -> None: ...

    def compile(
        self, context: dict[str, Any] | None = None
    ) -> tuple[str, list[Any], str, list[Any]]: ...
```

**Return Value**:
- `(main_sql, main_params, count_sql, count_params)`
  - `main_sql`: The parameterized `SELECT` SQL statement.
  - `main_params`: Positional list of bind values for `main_sql`.
  - `count_sql`: Matching `SELECT COUNT(*)` query for pagination.
  - `count_params`: Positional list of bind values for `count_sql`.

---

### Custom Filter Operators

#### `register_filter_operator(name: str, handler: Callable[..., tuple[str, list[Any]]]) -> None`
Registers a custom filter operator globally.

```python
from query_builder import register_filter_operator


def tax_exempt_handler(col_ref, value, dialect):
    # Returns (sql_expression, list_of_params)
    return f"{col_ref} IS NOT NULL AND {col_ref} = {dialect.placeholder}", [value]


register_filter_operator("tax_exempt", tax_exempt_handler)
```

- `unregister_filter_operator(name: str) -> None`: Removes a registered operator.
- `list_filter_operators() -> list[str]`: Returns list of all available operator names.

---

## 5. Dialect Subsystem (`query_builder.dialects`)

Supports 71+ database and query engine dialects.

### Core Functions
- `get_dialect(name: str) -> BaseDialect`: Resolves a dialect instance by name (case-insensitive).
- `list_dialects() -> list[str]`: Lists all registered dialect names.
- `register_dialect(name: str, dialect_cls_or_instance: Any) -> None`: Registers a custom dialect.
- `unregister_dialect(name: str) -> None`: Unregisters a custom dialect.
- `quote_identifier(ident: str, dialect: str = "postgres") -> str`: Safely quotes an identifier according to dialect rules.
- `quote_alias(alias: str, dialect: str = "postgres") -> str`: Safely quotes an alias.

---

## 6. Connector Subsystem (`query_builder.connectors`)

### `BaseConnector`
Abstract base connector for synchronous database drivers.

**Core Methods**:
- `connect() -> Any`: Returns driver connection object.
- `get_cursor() -> Generator[Any, None, None]`: Context manager yielding a cursor with deterministic cleanup.
- `execute(spec=..., schema=..., timeout_ms=...) -> dict[str, Any]`: Compiles and executes a query.
  - **Returns**:
    ```python
    {
        "columns": ["id", "name"],
        "rows": [{"id": 1, "name": "Alice"}],
        "count": 1,
        "limit": 50,
        "offset": 0,
        "page": 1,
        "latency_ms": 1.25,
        "dialect": "sqlite",
    }
    ```
- `introspect_schema(filter_sensitive: bool = True) -> dict[str, Any]`: Returns introspected catalog.
- `test_connection() -> dict[str, Any]`: Verifies connectivity.

---

### `AsyncBaseConnector`
Abstract base connector for async drivers (`asyncio`).

**Core Methods**:
- `async connect() -> Any`
- `async get_cursor() -> AsyncGenerator[Any, None]`
- `async execute(spec=..., timeout_ms=...) -> dict[str, Any]`
- `async introspect_schema(...) -> dict[str, Any]`

---

### `SQLiteConnector`
Synchronous connector using Python's standard library `sqlite3`.

```python
from query_builder import SQLiteConnector

connector = SQLiteConnector(database="app.db")
# Or in-memory:
connector = SQLiteConnector(database=":memory:")
```

---

### Connector Exceptions
- `ConnectorError`: Base exception for connector errors.
- `ConnectionFailedError`: Database unreachable or bad credentials.
- `DriverNotInstalledError`: Missing optional pip driver extra.
- `QueryExecutionError`: SQL execution runtime error or timeout.
- `IntrospectionError`: Catalog reflection failure.

---

## 7. AST Safety Validator (`query_builder.ast_validator`)

### `validate_sql_ast(sql: str, allowed_statements: set[str] | None = None) -> dict[str, Any]`
Parses SQL using AST tokens to enforce strict read-only guarantees.

**Returns**:
```python
{
    "valid": bool,
    "is_read_only": bool,
    "statement_type": str,  # e.g. "SELECT", "MULTI_STATEMENT"
    "tables": list[str],  # Referenced table names
    "injection_risk": str,  # "NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"
    "errors": list[str],  # Descriptive rejection reasons
}
```

- Rejects `DELETE`, `DROP`, `UPDATE`, `INSERT`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `COPY`, `INTO`.
- Rejects semicolon query chaining (`MULTI_STATEMENT`).
- Restricts access to sensitive system tables (`pg_shadow`, `auth_user`, `sqlite_master`).

---

## 8. Relational Join Solver (`query_builder.join_solver`)

### `find_join_path(active_tables: list[str], target_table: str, schema_data: dict[str, Any]) -> list[dict[str, Any]]`
Discovers the shortest relational join path between already active tables and a target table using BFS pathfinding.

### `find_best_join_condition(left_table: str, right_table: str, schema_data: dict[str, Any]) -> list[dict[str, str]] | None`
Finds foreign key matching conditions between two tables.

---

## 9. Native HTTP Microservice Server (`query_builder.server`)

Zero-dependency HTTP server with OpenAPI 3.1 documentation.

### `create_server(host: str = "127.0.0.1", port: int = 8000, telemetry_collector: TelemetryCollector | None = None, template_store: TemplateStore | None = None, pool: ConnectionPool | None = None) -> ThreadingHTTPServer`
Creates an HTTP server instance exposing:
- `GET /health`: Health status, dialect list, active security profile.
- `GET /openapi.json`: OpenAPI 3.1 specification.
- `GET /docs`: Interactive Swagger UI HTML documentation.
- `POST /api/v1/compile`: Compiles JSON query spec to SQL.
- `POST /api/v1/validate`: Validates raw SQL statement AST.
- `POST /api/v1/execute`: Compiles and executes query against configured connector.
- `POST /api/v1/introspect`: Introspects database schema.
- `POST /api/v1/export`: Exports query dataset to CSV / JSON / Excel.

---

# Volume 2: React Component Library & Headless SDK (`@jacob-white/query-builder-react`)

## 1. TypeScript Types & Interfaces

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

export interface ForeignKey {
  table: string;
  column: string;
  foreign_table: string;
  foreign_column: string;
  constraint_name?: string;
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
```

---

## 2. TypeScript ORM Adapters (`/adapters`)

Convert schemas directly in the browser or Node runtime:

### `fromPrisma(source: string | Record<string, any>, options?: AdapterOptions): TableSchema[]`
Parses Prisma `.prisma` schema DSL or DMMF object into `TableSchema[]`.

### `fromDrizzle(source: string | Record<string, any>, options?: AdapterOptions): TableSchema[]`
Parses Drizzle ORM TypeScript schema into `TableSchema[]`.

### `fromSqlAlchemy(source: string | Record<string, any>, options?: AdapterOptions): TableSchema[]`
Parses SQLAlchemy declarative model code or dictionary into `TableSchema[]`.

### `fromJsonSchema(source: string | Record<string, any>, options?: AdapterOptions): TableSchema[]`
Parses JSON Schema or OpenAPI 3.x schema definition into `TableSchema[]`.

### `toSchemaSnapshot(tables: TableSchema[]): SchemaSnapshot`
Converts `TableSchema[]` into normalized `SchemaSnapshot` for visual builder components and hooks.

---

## 3. Theming & Provider (`QueryBuilderProvider`, `ThemeProvider`)

### `<QueryBuilderProvider>`
Top-level provider establishing UI mode, themes, custom operators, and execution handlers.

```tsx
interface QueryBuilderProviderProps {
  mode?: "styled" | "unstyled";
  theme?: QueryBuilderTheme;
  themeMode?: "dark" | "light";
  customTokens?: DeepPartial<QueryBuilderTheme>;
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
  children: React.ReactNode;
}
```

### Container-Scoped CSS Variables
When `mode="styled"`, the provider applies scoped CSS variables:
- Colors: `--qb-color-primary`, `--qb-color-background`, `--qb-color-surface`, `--qb-color-border`, `--qb-color-text`, `--qb-color-text-muted`
- Typography: `--qb-font-family`, `--qb-font-family-mono`, `--qb-font-size-sm`, `--qb-font-size-md`
- Radii: `--qb-radius-sm`, `--qb-radius-md`, `--qb-radius-lg`
- Shadows: `--qb-shadow-sm`, `--qb-shadow-md`

---

## 4. Headless React Hooks (`/hooks`)

### `useQueryBuilder<Schema>(options?: UseQueryBuilderOptions<Schema>)`
Complete headless query builder state management hook.

**Options**:
- `schema`: `SchemaSnapshot | null`
- `initialTable`: Primary table name
- `dialect`: SQL dialect (`"postgres"`, `"sqlite"`, `"snowflake"`, `"mysql"`, `"mssql"`)
- `initialLimit`: Default query row limit
- `initialDistinct`: Boolean flag for `SELECT DISTINCT`

**Returns**:
- `state`: Active query state (`primaryTable`, `activeTableNames`, `selectedColumns`, `joins`, `filters`, `sorts`, `isDistinct`, `limit`, `dialect`, `rawSql`, `isRawMode`, `isDirty`).
- `compiled`: `{ sql, params, countSql, countParams, spec }`.
- `currentSql`: Formatted SQL string.
- `safety`: `{ isValid, isReadOnly, issues, severity, allowedActions }`.
- `actions`: Methods to mutate state (`setPrimaryTable`, `toggleColumn`, `addJoin`, `autoJoinTable`, `addFilter`, `addSort`, `setLimit`, `loadSpec`, `reset`).

---

### `useQueryExecution(options?: UseQueryExecutionOptions)`
Execution lifecycle controller with abort cancellation and latency metrics.

**Options**:
- `onExecuteQuery`: Async execution handler `(sql, spec) => Promise<QueryResultData>`.
- `apiEndpoint`: Optional REST API endpoint.
- `defaultTimeoutMs`: Timeout in milliseconds.

**Returns**:
- `results`: `QueryResultData | null`
- `isLoading`: boolean
- `error`: string | null
- `latencyMs`: number | null
- `executeQuery(sql, spec)`: Async execution trigger
- `cancelExecution()`: Aborts in-flight request
- `clearResults()`: Clears active result table

---

### `useSchemaIntrospection(options?: UseSchemaIntrospectionOptions)`
Fetches, caches, and normalizes remote database schemas.

---

## 5. Visual UI Components (`/components`)

- `<VisualQueryBuilder>`: Full-featured visual query workspace with canvas, joins, filters, raw SQL toggle, and results table.
- `<QueryCanvas>`: Interactive diagrammatic canvas with table cards and relational connector lines.
- `<TableCard>`: Individual draggable/interactive table card displaying columns and projection toggles.
- `<TableFiltersEditor>`: Dynamic filter builder supporting multi-operator criteria.
- `<TableJoinEditor>`: Relational join configurator with auto-join discovery.
- `<TableSortsEditor>`: Multi-column sorting and direction manager.
- `<SchemaErdModal>`: Entity-Relationship Diagram modal.
- `<SchemaExplorer>`: Searchable tree view of tables, columns, and foreign keys.
- `<QueryResultsTable>`: Paginated tabular result viewer with CSV export.
- `<QueryPlayground>`: Split-screen developer playground with live AST visualization.

---

## 6. Extension Points (Custom Operators, Custom Field Renderers)

### Custom Filter Operators (`customOperators`)
Extend visual query filters with domain-specific operators:

```tsx
const customOperators: Record<string, CustomFilterOperator> = {
  TAX_EXEMPT: {
    value: "TAX_EXEMPT",
    label: "Is Tax Exempt",
    hasValue: false,
    formatSql: (colRef) => `${colRef} IS NOT NULL AND ${colRef} = 0`,
  },
};
```

### Custom Cell Renderers (`cellRenderers`)
Customize table cell rendering in results:

```tsx
const cellRenderers = {
  price: (val: any) => (
    <span className="font-mono text-emerald-600 font-semibold">
      ${Number(val).toFixed(2)}
    </span>
  ),
};
```
