/**
 * What a column's data type means for filtering: which operators make sense, what a valid value looks like, and how to
 * read a filter back in words.
 *
 * Pure, so the form and the summary share one definition and it is tested without rendering anything. The server
 * remains the authority (it checks identifiers, binds every value and applies the table allowlist); this only stops
 * a person typing "banana" into a date or "yes" into a number, and offers the operators that fit.
 */

export type ColumnKind = 'text' | 'number' | 'date' | 'datetime' | 'boolean' | 'uuid' | 'json' | 'other';

/** The kind of a column from the data type string the server reports (`VARCHAR(64)`, `NUMERIC(26, 8)`, `TIMESTAMP`...). */
export function columnKind(dataType: string): ColumnKind {
  const type = dataType.trim().toUpperCase();
  if (type === 'BOOLEAN' || type === 'BOOL') return 'boolean';
  if (type === 'UUID') return 'uuid';
  if (type.startsWith('JSON')) return 'json';
  if (type === 'DATE') return 'date';
  // TIME has no date part and an ISO timestamp is the wrong shape for it, so it gets no value input (see 'other').
  if (type === 'TIME' || type.startsWith('TIME ')) return 'other';
  if (type.startsWith('TIMESTAMP') || type.startsWith('DATETIME')) return 'datetime';
  if (/^(SMALLINT|INTEGER|INT|BIGINT|NUMERIC|DECIMAL|REAL|FLOAT|DOUBLE PRECISION|MONEY)\b/.test(type)) return 'number';
  if (/^(VARCHAR|CHARACTER VARYING|CHAR|CHARACTER|TEXT|CITEXT|NAME)\b/.test(type)) return 'text';
  return 'other';
}

/** How many values an operator takes. */
export type Arity = 'none' | 'one' | 'two' | 'list';

export interface OperatorDef {
  /** What is sent as the filter's operator: one the server compiler already accepts. */
  value: string;
  /** What the person reads. */
  label: string;
  arity: Arity;
}

const op = (value: string, label: string, arity: Arity = 'one'): OperatorDef => ({ value, label, arity });
const EMPTY = [op('IS NULL', 'is empty', 'none'), op('IS NOT NULL', 'is not empty', 'none')];

const OPERATORS: Record<ColumnKind, OperatorDef[]> = {
  text: [
    op('=', 'is'),
    op('!=', 'is not'),
    op('CONTAINS', 'contains'),
    op('STARTS_WITH', 'starts with'),
    op('ENDS_WITH', 'ends with'),
    op('IN', 'is one of', 'list'),
    ...EMPTY,
  ],
  number: [
    op('=', 'is'),
    op('!=', 'is not'),
    op('>', 'is greater than'),
    op('>=', 'is at least'),
    op('<', 'is less than'),
    op('<=', 'is at most'),
    op('BETWEEN', 'is between', 'two'),
    op('IN', 'is one of', 'list'),
    ...EMPTY,
  ],
  date: [
    op('=', 'is'),
    op('!=', 'is not'),
    op('>', 'is after'),
    op('>=', 'is on or after'),
    op('<', 'is before'),
    op('<=', 'is on or before'),
    op('BETWEEN', 'is between', 'two'),
    ...EMPTY,
  ],
  // No "is": a timestamp equals one exact instant, which is almost never what "is this day" means.
  datetime: [
    op('>', 'is after'),
    op('>=', 'is at or after'),
    op('<', 'is before'),
    op('<=', 'is at or before'),
    op('BETWEEN', 'is between', 'two'),
    ...EMPTY,
  ],
  boolean: [op('=', 'is'), op('!=', 'is not'), ...EMPTY],
  uuid: [op('=', 'is'), op('!=', 'is not'), op('IN', 'is one of', 'list'), ...EMPTY],
  // Free text against JSON or an unknown type is a guess, so only whether it is set.
  json: EMPTY,
  other: EMPTY,
};

export function operatorsFor(kind: ColumnKind): OperatorDef[] {
  return OPERATORS[kind];
}

export function operatorDef(kind: ColumnKind, value: string): OperatorDef | undefined {
  return OPERATORS[kind].find((o) => o.value === value);
}

const HELP: Record<string, string> = {
  '=': 'Keeps rows whose value is exactly this.',
  '!=': 'Keeps rows whose value is anything but this. Rows with no value are left out too.',
  '>': 'Keeps rows with a value above this one (not equal to it).',
  '>=': 'Keeps rows with a value equal to this or above it.',
  '<': 'Keeps rows with a value below this one (not equal to it).',
  '<=': 'Keeps rows with a value equal to this or below it.',
  BETWEEN: 'Keeps rows with a value from the first to the second, both ends included.',
  IN: 'Keeps rows whose value is any one of several. Type each value and press Enter.',
  CONTAINS: 'Keeps rows where this text appears anywhere in the value, ignoring capital letters.',
  STARTS_WITH: 'Keeps rows whose value begins with this text, ignoring capital letters.',
  ENDS_WITH: 'Keeps rows whose value ends with this text, ignoring capital letters.',
  'IS NULL': 'Keeps rows where nothing has been recorded for this column.',
  'IS NOT NULL': 'Keeps rows where something has been recorded for this column.',
};

// Dates read better as before and after than as below and above, and a day is not a single instant.
const DATE_HELP: Record<string, string> = {
  '=': 'Keeps rows dated exactly this day.',
  '!=': 'Keeps rows dated any day but this one. Rows with no date are left out too.',
  '>': 'Keeps rows dated after this day (not on it).',
  '>=': 'Keeps rows dated on this day or later.',
  '<': 'Keeps rows dated before this day (not on it).',
  '<=': 'Keeps rows dated on this day or earlier.',
  BETWEEN: 'Keeps rows dated from the first day to the second, both days included.',
};

/** One plain sentence saying what an operator does for a kind of column, for the line under the operator choices. */
export function operatorHelp(kind: ColumnKind, value: string, subject: 'rows' | 'groups' = 'rows'): string {
  const text = kind === 'date' || kind === 'datetime' ? DATE_HELP[value] ?? HELP[value] ?? '' : HELP[value] ?? '';
  return subject === 'rows' ? text : text.replace(/\brows\b/g, subject).replace(/\bRows\b/g, 'Groups');
}

/** The operator a new filter starts on for this kind of column. */
export function defaultOperator(kind: ColumnKind): string {
  return OPERATORS[kind][0].value;
}

/** What a form hands over before it is checked. */
export type RawValue = string | boolean | null | undefined | [string, string] | string[];

/** What is sent as the filter's value. Lists and ranges go as arrays, which the compiler binds one by one. */
export type ConditionValue = string | number | boolean | (string | number)[];

export type Coerced = { ok: true; value: ConditionValue } | { ok: false; error: string };

const fail = (error: string): Coerced => ({ ok: false, error });
const good = (value: ConditionValue): Coerced => ({ ok: true, value });

const NUMBER = /^-?\d+(\.\d+)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

function isRealDate(text: string): boolean {
  const m = DATE.exec(text);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d;
}

/** One value of this kind as it is sent, or why it is not valid. */
function one(kind: ColumnKind, text: string): Coerced {
  switch (kind) {
    case 'number':
      return NUMBER.test(text.trim()) ? good(Number(text.trim())) : fail('Enter a number.');
    case 'date':
      return isRealDate(text) ? good(text) : fail('Pick a date.');
    case 'datetime':
      return DATETIME.test(text) && isRealDate(text.slice(0, 10)) ? good(text) : fail('Pick a date and time.');
    case 'uuid':
      return UUID.test(text.trim()) ? good(text.trim().toLowerCase()) : fail('Enter a UUID, such as 123e4567-e89b-12d3-a456-426614174000.');
    case 'text':
      return text.trim() === '' ? fail('Enter a value.') : good(text);
    default:
      /* v8 ignore next 2 -- no operator of the remaining kinds takes one value, so `coerceValue` never gets here */
      return fail('This column cannot be filtered by a value.');
  }
}

/**
 * Check what the form holds against the column kind and operator, and turn it into the value to send.
 * An operator that does not belong to the kind (left over from a previous column) is refused, not guessed at.
 */
export function coerceValue(kind: ColumnKind, operator: string, raw: RawValue): Coerced {
  const def = operatorDef(kind, operator);
  if (!def) return fail('That choice does not fit this column. Pick another.');

  if (def.arity === 'none') return good('');

  if (kind === 'boolean') {
    return typeof raw === 'boolean' ? good(raw) : fail('Choose Yes or No.');
  }

  if (def.arity === 'one') {
    return typeof raw === 'string' ? one(kind, raw) : fail('Enter a value.');
  }

  if (def.arity === 'list') {
    const items = Array.isArray(raw) ? raw : [];
    if (items.length === 0) return fail('Add at least one value.');
    const out: (string | number)[] = [];
    for (const item of items) {
      const c = one(kind, item);
      if (!c.ok) return c;
      out.push(c.value as string | number);
    }
    return good(out);
  }

  // two: a range
  if (!Array.isArray(raw) || raw.length !== 2) return fail('Enter both ends of the range.');
  const low = one(kind, raw[0]);
  if (!low.ok) return low;
  const high = one(kind, raw[1]);
  if (!high.ok) return high;
  if ((low.value as string | number) > (high.value as string | number)) {
    return fail('The first value must not be larger than the second.');
  }
  return good([low.value as string | number, high.value as string | number]);
}

// --------------------------------------------------------------------------
// Reading a filter back in words
// --------------------------------------------------------------------------

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `2026-01-05` -> `5 Jan 2026`, `2026-01-05T14:30` -> `5 Jan 2026 14:30`. Anything else is returned as it came. */
export function prettyDate(text: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}:\d{2}))?/.exec(text);
  if (!m) return text;
  const base = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  return m[4] ? `${base} ${m[4]}` : base;
}

function show(kind: ColumnKind, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (kind === 'date' || kind === 'datetime') return prettyDate(String(value));
  return String(value);
}

export interface DescribableFilter {
  column: string;
  tablePrefix?: string;
  operator: string;
  value: unknown;
}

/** A filter in words: `created_at is on or after 5 Jan 2026`. Lists are cut after three values. */
export function describeFilter(filter: DescribableFilter, kind: ColumnKind): string {
  const name = filter.tablePrefix ? `${filter.tablePrefix}.${filter.column}` : filter.column;
  const def = operatorDef(kind, filter.operator);
  const label = def?.label ?? filter.operator.toLowerCase();
  // An operator the kind does not list (say LIKE, from a saved query) still shows its value: only a known "no value"
  // operator drops it.
  if (def && def.arity === 'none') return `${name} ${label}`;
  if (Array.isArray(filter.value)) {
    const items = filter.value.map((v) => show(kind, v));
    if (def?.arity === 'two') return `${name} ${label} ${items[0]} and ${items[1]}`;
    const shown = items.slice(0, 3).join(', ');
    return `${name} ${label} ${shown}${items.length > 3 ? ` and ${items.length - 3} more` : ''}`;
  }
  return `${name} ${label} ${show(kind, filter.value)}`;
}
