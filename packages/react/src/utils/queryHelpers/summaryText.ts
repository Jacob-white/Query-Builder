/** Plain-words summaries of each step of a query, for the summary rows on the page. Pure. */

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

export function joinsSummary(joins: { table: string }[]): string {
  return joins.length === 0 ? 'None' : listSummary(joins.map((j) => j.table));
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
