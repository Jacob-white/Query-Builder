/** Plain-words summaries of each step of a query, for the summary rows on the page. Pure. */
import { toBuilderJoinType } from '../joinKind';

interface SelectedColumn {
  table: string;
  name: string;
  aggregate?: string;
  alias?: string;
}

const AGGREGATE_WORDS: Record<string, string> = { COUNT: 'Count of', SUM: 'Sum of', AVG: 'Average of', MIN: 'Lowest', MAX: 'Highest' };

/** `a, b, c and 2 more`: the first few items, then how many were left out. */
export function listSummary(items: string[], max = 3): string {
  if (items.length <= max) return items.join(', ');
  return `${items.slice(0, max).join(', ')} and ${items.length - max} more`;
}

/** One selected column as a person would say it: `name`, or `Sum of aum`, or its alias when it has one. */
export function columnLabel(column: SelectedColumn): string {
  if (!column.aggregate) return column.name;
  const alias = column.alias?.trim();
  return alias || `${AGGREGATE_WORDS[column.aggregate.toUpperCase()] ?? column.aggregate} ${column.name}`;
}

export function columnsSummary(selected: Record<string, SelectedColumn>, order: string[]): string {
  const labels = order.map((k) => selected[k]).filter((c): c is SelectedColumn => Boolean(c)).map(columnLabel);
  return labels.length === 0 ? 'No columns yet' : `${labels.length} ${labels.length === 1 ? 'column' : 'columns'}: ${listSummary(labels, 4)}`;
}

/** A join as the summary needs it: the table is required; the rest may be missing while the join is being built. */
export interface SummarizedJoin {
  table: string;
  /** `"LEFT JOIN"` (the builder's form) or `"LEFT"` (the compiler's), in any case. */
  type?: string;
  left_table?: string;
  left_col?: string;
  right_col?: string;
}

/** `Left join`, `Inner join`, ...; just `Join` when the join has no kind. */
function kindWords(type: string | undefined): string {
  if (!type || type.trim() === '') return 'Join';
  const bare = toBuilderJoinType(type).replace(/ JOIN$/i, '').toLowerCase();
  return `${bare.charAt(0).toUpperCase()}${bare.slice(1)} join`;
}

/** `Left join customers on orders.customer_id = customers.id`, or says the matching column is still to be chosen. */
function joinSentence(join: SummarizedJoin): string {
  const kind = kindWords(join.type);
  if (!join.left_table || !join.left_col || !join.right_col) return `${kind} ${join.table}: choose the matching column`;
  return `${kind} ${join.table} on ${join.left_table}.${join.left_col} = ${join.table}.${join.right_col}`;
}

/**
 * The joins as one line. Joins that carry nothing but a table (all of them, as the function used to take) are listed by
 * table name. As soon as one carries a kind or a column, every join is written as a sentence: the kind (left, inner,
 * right, full), the table and the two columns it matches on, "choose the matching column" for a half-filled one, and
 * `; and N more` after two.
 */
export function joinsSummary(joins: SummarizedJoin[]): string {
  if (joins.length === 0) return 'None';
  const detailed = joins.some((j) => j.type !== undefined || j.left_table !== undefined || j.left_col !== undefined || j.right_col !== undefined);
  if (!detailed) return listSummary(joins.map((j) => j.table));
  const sentences = joins.map(joinSentence);
  return sentences.length <= 2 ? sentences.join('; ') : `${sentences.slice(0, 2).join('; ')}; and ${sentences.length - 2} more`;
}

export function sortsSummary(sorts: { column: string | number | symbol; direction: string }[]): string {
  if (sorts.length === 0) return 'None';
  return listSummary(sorts.map((s) => `${String(s.column)} ${s.direction === 'DESC' ? 'descending' : 'ascending'}`));
}

/** The conditions as one line, or "None". `texts` are already in words (see `describeFilter`). */
export function conditionsSummary(texts: string[]): string {
  return texts.length === 0 ? 'None' : listSummary(texts, 2);
}

/** The window functions as one line: `ROW_NUMBER by key, SUM of aum`, or "None". */
export function windowSummary(functions: { function: string; arguments?: (string | number)[]; order_by?: { column: string }[] }[]): string {
  if (functions.length === 0) return 'None';
  return listSummary(
    functions.map((f) => {
      const name = f.function.toUpperCase();
      const arg = f.arguments?.[0];
      const order = f.order_by?.[0]?.column;
      return [name, arg !== undefined && arg !== '' ? `of ${arg}` : '', order ? `ordered by ${order}` : ''].filter(Boolean).join(' ');
    }),
    2,
  );
}

/** The sub-queries as one line of their names, or "None". */
export function subqueriesSummary(names: string[]): string {
  return names.length === 0 ? 'None' : listSummary(names);
}
