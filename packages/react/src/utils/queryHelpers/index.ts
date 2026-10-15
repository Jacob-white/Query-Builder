/**
 * Pure helpers for building a query UI on top of this package: what a column's type means for filtering (operators, value
 * checks, readable conditions), filters on aggregated values (HAVING), which joins are proven by a declared link, plain-words
 * summaries of a query, and the `.sql` file helpers. No React and no DOM, so they work anywhere and are tested alone.
 */
export * from "./columnTypes";
export * from "./filterKinds";
export * from "./havingFilters";
export * from "./joinLinks";
export * from "./sqlFile";
export * from "./summaryText";
