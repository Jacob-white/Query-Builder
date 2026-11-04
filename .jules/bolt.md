## 2024-11-04 - TableCard memoization
**Learning:** In the React frontend, `TableCard` component was re-rendering unnecessarily and can be optimized using `React.memo()` to prevent re-renders when props have not changed.
**Action:** Apply `React.memo()` to UI components like `TableCard` that often receive same props during a query builder state change.
