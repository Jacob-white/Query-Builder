/**
 * Filters on aggregated values (HAVING): "only groups whose total is over 100".
 *
 * The builder package has no field for these, so the page keeps them and merges them into the spec it sends and the
 * spec it saves. Everything here is pure. The server remains the authority: it refuses a HAVING with no aggregated
 * column or with a column outside the query, and binds the value as a parameter.
 */
import { columnKind, describeFilter, operatorsFor, type ColumnKind, type ConditionValue, type OperatorDef } from './filterKinds';

export type HavingAggregate = 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX';
export type HavingOperator = '=' | '!=' | '>' | '>=' | '<' | '<=';

export interface HavingFilter {
  id: string;
  /** `*` (every row, only with COUNT) or `table.column`. */
  column: string;
  agg: HavingAggregate;
  operator: HavingOperator;
  value: ConditionValue;
}

/** One thing a filter on aggregated values can be about: an aggregated column in the query, or the row count. */
export interface HavingTarget {
  column: string;
  agg: HavingAggregate;
  label: string;
  /** The data type of the column the aggregate is over, when there is one. */
  baseType?: string;
}

const COMPARISONS: HavingOperator[] = ['=', '!=', '>', '>=', '<', '<='];
const AGGREGATES: HavingAggregate[] = ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX'];

/** The server accepts these by name or by symbol; names are mapped back to symbols when a saved query is read. */
const OPERATOR_FROM_NAME: Record<string, HavingOperator> = { eq: '=', neq: '!=', gt: '>', gte: '>=', lt: '<', lte: '<=' };

export const ROWS_TARGET: HavingTarget = { column: '*', agg: 'COUNT', label: 'Number of rows' };

interface SelectedColumn {
  table: string;
  name: string;
  aggregate?: string;
  alias?: string;
}

/**
 * What a filter on aggregated values can be about right now: the row count, plus each column the query aggregates.
 * `typeOf` gives a column's data type. MIN and MAX of a column with no sensible ordering (a UUID, JSON, a boolean) are
 * left out, because comparing them would only fail in the database.
 */
export function havingTargets(
  selected: Record<string, SelectedColumn>,
  order: string[],
  typeOf: (table: string, column: string) => string | undefined,
): HavingTarget[] {
  const targets: HavingTarget[] = [];
  const seen = new Set<string>();
  const add = (target: HavingTarget) => {
    const key = `${target.column}|${target.agg}`;
    if (!seen.has(key)) {
      seen.add(key);
      targets.push(target);
    }
  };
  const aggregated = order.map((k) => selected[k]).filter((c): c is SelectedColumn => Boolean(c?.aggregate));
  if (aggregated.length === 0) return [];
  add(ROWS_TARGET);
  for (const c of aggregated) {
    const agg = c.aggregate!.toUpperCase() as HavingAggregate;
    if (!AGGREGATES.includes(agg)) continue;
    const baseType = typeOf(c.table, c.name);
    if ((agg === 'MIN' || agg === 'MAX') && !['number', 'date', 'datetime', 'text'].includes(columnKind(baseType ?? ''))) continue;
    add({ column: `${c.table}.${c.name}`, agg, label: c.alias?.trim() || `${agg}(${c.table}.${c.name})`, baseType });
  }
  return targets;
}

/** What kind of value a filter on this target takes: counts, sums and averages are numbers; MIN and MAX follow the column. */
export function havingKind(target: HavingTarget): ColumnKind {
  if (target.agg === 'MIN' || target.agg === 'MAX') return columnKind(target.baseType ?? '');
  return 'number';
}

/** The comparisons that fit a target's kind (a timestamp has no "is", for example). */
export function havingOperators(target: HavingTarget): OperatorDef[] {
  return operatorsFor(havingKind(target)).filter((o) => (COMPARISONS as string[]).includes(o.value));
}

/** The target a filter is about, if the query still has it. */
export function targetFor(filter: HavingFilter, targets: HavingTarget[]): HavingTarget | undefined {
  return targets.find((t) => t.column === filter.column && t.agg === filter.agg);
}

/** A filter in words, using the aggregate's alias when it has one: `Total is greater than 100`. */
export function describeHaving(filter: HavingFilter, targets: HavingTarget[]): string {
  const target = targetFor(filter, targets) ?? { column: filter.column, agg: filter.agg, label: filter.column === '*' ? 'Number of rows' : `${filter.agg}(${filter.column})` };
  return describeFilter({ column: target.label, operator: filter.operator, value: filter.value }, havingKind(target));
}

/**
 * The filters to send with a query, as spec items, keeping only those whose aggregate is still in the spec's columns.
 * A filter left over from a column that has since lost its aggregate would make the server refuse the whole query.
 */
export function havingForSpec(having: HavingFilter[], specColumns: unknown): { column: string; agg: string; op: string; value: ConditionValue }[] {
  const columns = Array.isArray(specColumns) ? specColumns : [];
  const aggregates = columns
    .filter((c): c is Record<string, unknown> => typeof c === 'object' && c !== null)
    .map((c) => ({ column: String(c.column ?? ''), agg: String(c.agg ?? c.aggregate ?? '').toUpperCase() }))
    .filter((c) => c.agg !== '');
  return having
    .filter((h) => (h.column === '*' ? aggregates.length > 0 : aggregates.some((a) => a.column === h.column && a.agg === h.agg)))
    .map((h) => ({ column: h.column, agg: h.agg.toLowerCase(), op: h.operator, value: h.value }));
}

/** Read filters back from a saved spec's `having`. Tolerant: anything that is not a usable filter is skipped. */
export function parseHaving(raw: unknown): HavingFilter[] {
  if (!Array.isArray(raw)) return [];
  const out: HavingFilter[] = [];
  raw.forEach((item, i) => {
    if (typeof item !== 'object' || item === null) return;
    const r = item as Record<string, unknown>;
    const agg = String(r.agg ?? r.aggregate ?? 'count').toUpperCase() as HavingAggregate;
    const rawOp = String(r.op ?? r.operator ?? '').toLowerCase();
    const operator = (COMPARISONS as string[]).includes(rawOp) ? (rawOp as HavingOperator) : OPERATOR_FROM_NAME[rawOp];
    const column = typeof r.column === 'string' ? r.column : '';
    if (!AGGREGATES.includes(agg) || !operator || !column) return;
    const value = r.value as ConditionValue;
    if (value === undefined || value === null) return;
    out.push({ id: `having-${i}-${column}-${agg}`, column, agg, operator, value });
  });
  return out;
}
