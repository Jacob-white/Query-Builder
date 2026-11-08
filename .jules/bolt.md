## 2024-03-24 - [React.memo in TableCard]
**Learning:** In the React frontend, wrap UI components that frequently receive the same props during state updates (e.g., `TableCard`) in `React.memo()` to prevent unnecessary re-renders and improve performance on complex query builder schemas.
**Action:** When using `React.memo()` to optimize React components, avoid implementing custom comparator functions that manually enumerate props. Rely on the default shallow equality comparison instead to avoid maintainability traps.
