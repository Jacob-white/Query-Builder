/**
 * Which tables can be joined with evidence, not a guess.
 *
 * A join is "proven" when a link declares the two columns (either direction): a foreign key in the database, or a
 * relationship V2 itself defines for its tables (the server merges both into one list). The package's automatic join
 * falls back to matching column names (id, user_id, ...) when neither exists, which can join unrelated tables.
 * These helpers let the UI tell the two apart. They are pure, so they are tested without rendering anything.
 */
import type { ForeignKeyMeta } from '../../types';

export type ForeignKeyEdge = ForeignKeyMeta;

/** The columns a join links, as the package stores them. */
export interface JoinColumns {
  left_table?: string;
  left_col: string;
  table: string;
  right_col: string;
}

/** `table.column → foreign_table.foreign_column`, for tooltips and secondary text. */
export function describeLink(fk: ForeignKeyEdge): string {
  return `${fk.table}.${fk.column} → ${fk.foreign_table}.${fk.foreign_column}`;
}

/**
 * The foreign keys that link `candidate` to a table already in the query, in either direction. Empty when the
 * candidate has no declared link to any of them. A table is never linked to itself here: `candidate` is by
 * definition not yet in the query.
 */
export function directLinks(candidate: string, activeTables: string[], fks: ForeignKeyEdge[]): ForeignKeyEdge[] {
  const active = new Set(activeTables);
  return fks.filter(
    (fk) =>
      (fk.table === candidate && active.has(fk.foreign_table) && fk.foreign_table !== candidate) ||
      (fk.foreign_table === candidate && active.has(fk.table) && fk.table !== candidate),
  );
}

/** Tables that have a declared link to `table` (either direction), excluding itself. */
export function linkedTables(table: string, fks: ForeignKeyEdge[]): string[] {
  const out = new Set<string>();
  for (const fk of fks) {
    if (fk.table === table && fk.foreign_table !== table) out.add(fk.foreign_table);
    if (fk.foreign_table === table && fk.table !== table) out.add(fk.table);
  }
  return [...out].sort();
}

/** True when a foreign key declares exactly this join's two columns, in either direction. */
export function isProvenJoin(join: JoinColumns, fks: ForeignKeyEdge[]): boolean {
  const left = join.left_table;
  if (!left) return false;
  return fks.some(
    (fk) =>
      (fk.table === left && fk.column === join.left_col && fk.foreign_table === join.table && fk.foreign_column === join.right_col) ||
      (fk.table === join.table && fk.column === join.right_col && fk.foreign_table === left && fk.foreign_column === join.left_col),
  );
}
