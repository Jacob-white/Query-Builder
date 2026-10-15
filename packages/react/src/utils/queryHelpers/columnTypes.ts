/** Small helpers for naming and looking up columns and their types. Pure. */
import type { SchemaSnapshot, TableMeta } from '../../types';
import { columnKind, type ColumnKind } from './filterKinds';

/** A column as the pickers show it. */
export interface PickerColumn {
  table: string;
  name: string;
  /** The data type string the server reports, such as `VARCHAR(64)` or `TIMESTAMP`. */
  type: string;
}

const KIND_LABELS: Record<ColumnKind, string> = {
  text: 'Text',
  number: 'Number',
  date: 'Date',
  datetime: 'Date and time',
  boolean: 'Yes/No',
  uuid: 'ID',
  json: 'JSON',
  other: 'Other',
};

/** What a person calls a column's type: `NUMERIC(26, 8)` is "Number", `TIMESTAMP` is "Date and time". */
export function kindLabel(kind: ColumnKind): string {
  return KIND_LABELS[kind];
}

export function typeLabel(dataType: string): string {
  return kindLabel(columnKind(dataType));
}

/** `table.column`, the key the builder uses for a selected column. */
export const columnKey = (table: string, name: string) => `${table}.${name}`;

/** Every column of the tables given, in table then column order. */
export function columnsOf(tables: TableMeta[]): PickerColumn[] {
  return tables.flatMap((t) => t.columns.map((c) => ({ table: t.name, name: c.name, type: c.data_type })));
}

/** A function that finds a column's data type in the schema, or undefined when the table or column is unknown. */
export function typeLookup(schema: SchemaSnapshot | null | undefined): (table: string, column: string) => string | undefined {
  return (table, column) => schema?.tables?.[table]?.columns.find((c) => c.name === column)?.data_type;
}

/**
 * The aggregates that make sense for a column of a given type, so the list does not offer a sum of names. COUNT fits
 * anything; MIN and MAX need an ordering (numbers, dates, text); SUM and AVG need numbers. An unknown type allows all of
 * them: the database is the judge there.
 */
export function aggregatesFor(dataType: string | undefined): string[] {
  if (dataType === undefined) return ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX'];
  const kind = columnKind(dataType);
  if (kind === 'number') return ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX'];
  if (kind === 'date' || kind === 'datetime' || kind === 'text') return ['COUNT', 'MIN', 'MAX'];
  return ['COUNT'];
}
