# Project: Query-Builder Full-Stack Expansion

## Architecture
Query-Builder is a full-stack data query and visualization platform consisting of:
1. **Python Engine & Backend Microservice (`query_builder`)**:
   - Universal query compiler supporting 35 database dialects.
   - Relational BFS shortest-path join graph solver.
   - AST validation, SQL injection risk analysis, and mutation blocking.
   - Multi-tenant isolation engine and fail-closed row-level security (RLS) policies (`policy.py`).
   - Thread-safe connection pooling for database connectors (`pool.py`).
   - Execution telemetry collector tracking query metrics and latency percentiles (`telemetry.py`).
   - Multi-format tabular data export engine supporting CSV, JSON, Parquet, and Excel (`export.py`).
   - Persistent query template store (`templates.py`).
   - Standalone HTTP microservice with OpenAPI 3.1 schema and Swagger UI documentation at `/docs` (`server.py`).
   - Extended CLI with `serve` subcommand (`cli.py`).
2. **React Visual Query Builder (`@jacob-white/query-builder-react`)**:
   - Headless React hooks for custom UI integration: `useQueryBuilder`, `useQueryExecution`, `useSchemaIntrospection` (`hooks/`).
   - Design-token theming system (`QueryBuilderTheme`) with dark/light themes and `ThemeProvider` (`theme/`).
   - Analyst visual querying canvas with interactive multi-table joining, filtering, and sorting (`components/`).
   - Visual chart and graph previews supporting accessible Bar, Line, and Pie charts with interactive field mapping (`QueryChartPreview.tsx`).
   - Query template manager supporting saving, searching, and loading templates (`QueryTemplateManager.tsx`).
   - Tabular results grid with verified CSV and JSON export downloads (`QueryResultsTable.tsx`).
   - Full keyboard navigation (Tab, Arrow keys, Enter, Escape) and ARIA attributes meeting WCAG 2.1 AA standards.
   - Interactive documentation showcase and component catalog (`ComponentShowcase.tsx`).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Standalone HTTP Microservice | Native HTTP server exposing OpenAPI 3.1 & Swagger UI at `/docs`, healthcheck at `/health` | M1 | ORIGINAL_REQUEST §R3 |
| 2 | Introspection, Compile, Validate & Execute APIs | REST API endpoints for schema introspection, query compilation, AST validation, and execution | M1 | ORIGINAL_REQUEST §R3 |
| 3 | Multi-Tenant & Fail-Closed RLS Policies | TenantContext, SecurityPolicy, tenant filter injection, table allow/denylists, fail-closed enforcement | M1 | ORIGINAL_REQUEST §R3 |
| 4 | Execution Telemetry & Connection Pooling | Query metrics ring buffer, latency percentiles, thread-safe DB-API connection pool | M1 | ORIGINAL_REQUEST §R3 |
| 5 | Multi-Format Data Export (Backend) | Python export engine supporting CSV, JSON, Parquet, and Excel formats | M1 | ORIGINAL_REQUEST §R1 |
| 6 | Query Template Store (Backend) | Backend query template CRUD persistence | M1 | ORIGINAL_REQUEST §R1 |
| 7 | Query Template Management UI | Template save dialog, search, category filter, load/delete UI in React studio | M2 | ORIGINAL_REQUEST §R1 |
| 8 | Multi-Format Tabular Data Export (Frontend) | CSV and JSON file export downloads with verified anchor creation and cleanup | M2 | ORIGINAL_REQUEST §R1 |
| 9 | Visual Chart & Graph Previews | Pure SVG Bar, Line, and Pie charts with interactive field mapping (X category, Y metric, agg) | M2 | ORIGINAL_REQUEST §R1 |
| 10 | Headless React Hooks | `useQueryBuilder`, `useQueryExecution`, `useSchemaIntrospection` exported from library | M3 | ORIGINAL_REQUEST §R2 |
| 11 | Design-Token Theming System | `QueryBuilderTheme`, `darkTheme`, `lightTheme`, `ThemeProvider`, `useTheme` | M3 | ORIGINAL_REQUEST §R2 |
| 12 | WCAG 2.1 AA Accessibility | Full keyboard navigation (Tab, Arrow keys, Enter, Escape), ARIA semantics, automated a11y tests | M3 | ORIGINAL_REQUEST §R2 |
| 13 | Interactive Component Showcase | Interactive documentation showcase / Storybook-style component catalog (`ComponentShowcase`) | M3 | ORIGINAL_REQUEST §R2 |
| 14 | 100% Quality & Verification | 100% statement/branch coverage in Python (`pytest`) and React (`vitest`), zero lint errors (`ruff`, `tsc`) | M4 | ORIGINAL_REQUEST §R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Microservice, Security & Export Engine | `query_builder/server.py`, `policy.py`, `pool.py`, `telemetry.py`, `export.py`, `templates.py`, `cli.py`, and Python tests | None | DONE |
| M2 | Frontend Visualization, Templates & Export UI | `QueryChartPreview.tsx`, `QueryTemplateManager.tsx`, `QueryResultsTable.tsx` JSON export, `VisualQueryBuilder.tsx` integration, and React tests | None | DONE |
| M3 | Frontend Hooks, Theming, Accessibility & Showcase | `useQueryBuilder.ts`, `useQueryExecution.ts`, `useSchemaIntrospection.ts`, `tokens.ts`, `ThemeProvider.tsx`, WCAG 2.1 AA navigation, `ComponentShowcase.tsx`, and React tests | M2 | DONE |
| M4 | Full-Stack E2E Verification & 100% Coverage Assurance | End-to-end verification, test suite execution (sequential), 100% statement/branch coverage check, ruff/tsc linters | M1, M2, M3 | DONE |

## Interface Contracts
### HTTP API (`query_builder/server.py`)
- `POST /api/v1/introspect`: Body `{ connector: str, config: dict }` -> Returns `SchemaSnapshot`.
- `POST /api/v1/compile`: Body `{ spec: QuerySpec, dialect?: str, tenant_id?: str, policy?: dict }` -> Returns `{ sql: str, params: list, count_sql: str, count_params: list, dialect: str }`.
- `POST /api/v1/validate`: Body `{ sql: str, allowed_schemas?: list }` -> Returns `ValidationResult`.
- `POST /api/v1/execute`: Body `{ sql?: str, spec?: QuerySpec, connector?: str, config?: dict, tenant_id?: str, timeout_ms?: int }` -> Returns `QueryResult`.
- `POST /api/v1/export`: Body `{ format: "csv" | "json" | "parquet" | "excel", rows?: list, spec?: QuerySpec }` -> Returns binary/text with appropriate `Content-Type`.
- `GET/POST /api/v1/templates`, `DELETE /api/v1/templates/{id}`: Template CRUD.
- `GET /api/v1/telemetry`: Metrics summary (total queries, p50/p95/p99 latency, error rate).
- `GET /docs`: Swagger UI HTML.
- `GET /openapi.json`: OpenAPI 3.1 specification.
- `GET /health`: Health status.

### Security & RLS (`query_builder/policy.py`)
- `TenantContext(tenant_id: str, user_id: str | None, roles: list[str], attributes: dict)`
- `SecurityPolicy(allowed_tables: list[str] | None, restricted_tables: list[str], tenant_column: str, enforce_tenant_isolation: bool, row_level_filters: dict, column_masking: dict)`
- `apply_security_policy(spec: dict, schema: dict | None, context: TenantContext, policy: SecurityPolicy) -> dict`

### React Hooks (`packages/react/src/hooks/`)
- `useQueryBuilder(options?: UseQueryBuilderOptions) => { state, compiled, safety, actions }`
- `useQueryExecution(options?: UseQueryExecutionOptions) => { results, isLoading, error, latencyMs, executeQuery, clearResults }`
- `useSchemaIntrospection(options?: UseSchemaIntrospectionOptions) => { schema, isLoading, error, refreshSchema }`

### React Theme (`packages/react/src/theme/`)
- `QueryBuilderTheme`: `colors`, `typography`, `radii`, `shadows`
- `ThemeProvider`: Context provider with default `darkTheme` and `lightTheme`
- `useTheme`: Hook returning current theme and toggle/set methods

## Code Layout
- Python Backend:
  - `query_builder/export.py`: Tabular export routines
  - `query_builder/policy.py`: Multi-tenant isolation & RLS policies
  - `query_builder/pool.py`: Connection pooling
  - `query_builder/telemetry.py`: Query telemetry and latency metrics
  - `query_builder/templates.py`: Template persistence
  - `query_builder/server.py`: HTTP server, OpenAPI 3.1 & Swagger UI
  - `query_builder/cli.py`: Extended CLI with `serve` command
  - `tests/test_server.py`, `tests/test_policy.py`, `tests/test_export.py`, `tests/test_telemetry.py`, `tests/test_pool.py`, `tests/test_templates.py`
- React Frontend:
  - `packages/react/src/hooks/useQueryBuilder.ts`
  - `packages/react/src/hooks/useQueryExecution.ts`
  - `packages/react/src/hooks/useSchemaIntrospection.ts`
  - `packages/react/src/theme/tokens.ts`
  - `packages/react/src/theme/ThemeProvider.tsx`
  - `packages/react/src/components/QueryChartPreview.tsx`
  - `packages/react/src/components/QueryTemplateManager.tsx`
  - `packages/react/src/components/ComponentShowcase.tsx`
  - `packages/react/src/components/QueryResultsTable.tsx` (enhanced with JSON export & ARIA)
  - `packages/react/src/components/VisualQueryBuilder.tsx` (enhanced with chart tab, templates, a11y, theming)
  - `packages/react/tests/hooks.test.tsx`
  - `packages/react/tests/theme.test.tsx`
  - `packages/react/tests/charts.test.tsx`
  - `packages/react/tests/templates.test.tsx`
  - `packages/react/tests/showcase.test.tsx`
  - `packages/react/tests/accessibility.test.tsx`
