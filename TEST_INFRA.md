# E2E Test Infra: Query-Builder

## Test Philosophy
- Requirement-driven, opaque-box and contract testing.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Combinatorial + Real-World Workload Testing.
- Strict constraint adherence: Sequential execution only (never run pytest and vitest concurrently); vitest worker limit capped at 2 (`VITEST_MAX_WORKERS=2`).
- 100% statement, function, and branch coverage for both Python and React codebases.
- Zero linting/formatting/type errors (`ruff check`, `ruff format --check`, `tsc`).

## Feature Inventory
| # | Feature | Source | Tier 1 (Coverage) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (Real-World) |
|---|---------|--------|:-----------------:|:-----------------:|:----------------------:|:-------------------:|
| 1 | HTTP Server & OpenAPI/Docs | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 2 | Introspection / Compile / Validate / Execute API | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 3 | Multi-Tenant Isolation & RLS Policies | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 4 | Telemetry & Connection Pooling | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 5 | Multi-Format Data Export (CSV/JSON/Parquet/Excel) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 6 | Query Templates (Backend Store & Frontend UI) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 7 | Visual Chart Previews (Bar, Line, Pie) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 8 | Headless Hooks (`useQueryBuilder`, etc.) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 9 | Design-Token Theming (`QueryBuilderTheme`) | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 10 | WCAG 2.1 AA Keyboard & ARIA Accessibility | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 11 | Interactive Component Showcase | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **Python Test Harness**:
  - Framework: `pytest`, `pytest-cov`
  - Command: `/home/jwhite/Query-Builder/.venv/bin/pytest --cov=query_builder --cov-branch --cov-report=term-missing`
  - Targets: `tests/test_server.py`, `tests/test_policy.py`, `tests/test_export.py`, `tests/test_telemetry.py`, `tests/test_pool.py`, `tests/test_templates.py`, plus existing test suite.
- **React Test Harness**:
  - Framework: `vitest` with JSDOM environment, `@testing-library/react`
  - Command: `cd /home/jwhite/Query-Builder/packages/react && VITEST_MAX_WORKERS=2 pnpm exec vitest run --coverage`
  - Typecheck: `cd /home/jwhite/Query-Builder/packages/react && pnpm exec tsc --noEmit`
  - Linter: `/home/jwhite/Query-Builder/.venv/bin/ruff check query_builder tests && /home/jwhite/Query-Builder/.venv/bin/ruff format --check query_builder tests`
- **Execution Sequencing**:
  1. Python tests run to completion.
  2. React tests run only AFTER Python tests finish.
  3. No concurrent test runners.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Target |
|---|----------|--------------------|--------|
| 1 | Analyst builds multi-table join, filters data, visualizes trends in bar/line charts, and exports to CSV & JSON | Chart Previews, Query Execution, Templates, Tabular Export | E2E React |
| 2 | Multi-tenant SaaS user executes query with tenant context, verifies RLS fail-closed blocks unauthorized cross-tenant data | RLS Policy, Compiler, HTTP Server, Executor | E2E Python |
| 3 | Frontend engineer builds custom headless query interface using `useQueryBuilder` and `useQueryExecution` with custom theme | Headless Hooks, Theming, AST Validation | E2E React |
| 4 | Enterprise batch pipeline exports query results to Parquet & Excel, records telemetry metrics, and queries `/api/v1/telemetry` | Export Engine, Telemetry, OpenAPI, Server | E2E Python |
| 5 | Keyboard-only user navigates visual canvas, opens template modal, selects template, navigates results grid, and dismisses modals with Escape | Keyboard Nav, ARIA attributes, Focus Trapping | E2E React A11y |

## Coverage Thresholds
- Python: 100% statement, 100% branch coverage (`pytest --cov=query_builder --cov-branch`).
- React: 100% statement, branch, function, and line coverage (`vitest run --coverage`).
- Zero linting or formatting errors across all source files.
