## 2026-11-11 - [Optimization] Wrap TableCard in React.memo()
**Learning:** In complex query builder schemas, components like `TableCard` frequently receive the same props during state updates, causing unnecessary re-renders. Manually enumerating props in custom comparator functions for `React.memo()` creates a maintainability trap where newly added props are easily ignored.
**Action:** Rely on the default shallow equality comparison of `React.memo()` to optimize UI components, ensuring type annotations are preserved to avoid type compilation errors.
