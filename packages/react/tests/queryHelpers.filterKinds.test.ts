import { describe, it, expect } from 'vitest';
import {
  operatorHelp,
  coerceValue,
  columnKind,
  defaultOperator,
  describeFilter,
  operatorDef,
  operatorsFor,
  prettyDate,
  type ColumnKind,
} from '../src/utils/queryHelpers/filterKinds';

// The column types the V2 database actually reports through /query-builder/schema.
const REAL_TYPES: Record<string, ColumnKind> = {
  VARCHAR: 'text',
  'VARCHAR(64)': 'text',
  'VARCHAR(36)': 'text',
  TEXT: 'text',
  TIMESTAMP: 'datetime',
  UUID: 'uuid',
  BOOLEAN: 'boolean',
  JSON: 'json',
  INTEGER: 'number',
  BIGINT: 'number',
  DATE: 'date',
  'NUMERIC(26, 8)': 'number',
  'NUMERIC(38, 10)': 'number',
  'NUMERIC(5, 2)': 'number',
  'DOUBLE PRECISION': 'number',
  TIME: 'other',
};

describe('columnKind', () => {
  it.each(Object.entries(REAL_TYPES))('maps %s to %s', (type, kind) => {
    expect(columnKind(type)).toBe(kind);
  });

  it('ignores case and surrounding space, and knows the timezone and jsonb spellings', () => {
    expect(columnKind('  varchar(10) ')).toBe('text');
    expect(columnKind('TIMESTAMP WITH TIME ZONE')).toBe('datetime');
    expect(columnKind('jsonb')).toBe('json');
    expect(columnKind('character varying')).toBe('text');
  });

  it('does not mistake a type that merely starts like another (control)', () => {
    expect(columnKind('INTERVAL')).toBe('other'); // starts with INT
    expect(columnKind('TIME WITHOUT TIME ZONE')).toBe('other');
    expect(columnKind('POINT')).toBe('other');
    expect(columnKind('')).toBe('other');
  });
});

describe('operatorsFor', () => {
  const labels = (kind: ColumnKind) => operatorsFor(kind).map((o) => o.label);

  it('offers text matching for text, and an exact match for a date but not for a timestamp', () => {
    expect(labels('text')).toEqual(expect.arrayContaining(['contains', 'starts with', 'ends with', 'is one of']));
    expect(labels('date')).toContain('is');
    expect(labels('datetime')).not.toContain('is');
  });

  it('offers no free-text operators for dates, numbers, booleans, json or unknown types', () => {
    for (const kind of ['date', 'datetime', 'number', 'boolean', 'json', 'other', 'uuid'] as ColumnKind[]) {
      expect(operatorsFor(kind).map((o) => o.value)).not.toContain('CONTAINS');
    }
  });

  it('only lets json and unknown columns be tested for empty', () => {
    expect(labels('json')).toEqual(['is empty', 'is not empty']);
    expect(labels('other')).toEqual(['is empty', 'is not empty']);
  });

  it('only sends operators the server compiler accepts', () => {
    const accepted = new Set(['=', '!=', '>', '>=', '<', '<=', 'CONTAINS', 'STARTS_WITH', 'ENDS_WITH', 'IN', 'BETWEEN', 'IS NULL', 'IS NOT NULL']);
    for (const kind of Object.keys(REAL_TYPES).map(columnKind)) {
      for (const o of operatorsFor(kind)) expect(accepted.has(o.value)).toBe(true);
    }
  });

  it('starts every kind on a sensible operator, and finds an operator by value', () => {
    expect(defaultOperator('text')).toBe('=');
    expect(defaultOperator('datetime')).toBe('>');
    expect(operatorDef('number', 'BETWEEN')?.arity).toBe('two');
    expect(operatorDef('number', 'CONTAINS')).toBeUndefined();
  });
});

describe('coerceValue: numbers', () => {
  it('accepts whole, decimal and negative numbers as numbers', () => {
    expect(coerceValue('number', '=', '42')).toEqual({ ok: true, value: 42 });
    expect(coerceValue('number', '>', '-3.5')).toEqual({ ok: true, value: -3.5 });
    expect(coerceValue('number', '=', ' 7 ')).toEqual({ ok: true, value: 7 });
  });

  it('refuses text, blanks and look-alikes', () => {
    for (const bad of ['banana', '', '1e3', '12abc', '1,000', '--1', '.5']) {
      expect(coerceValue('number', '=', bad)).toEqual({ ok: false, error: 'Enter a number.' });
    }
  });

  it('checks a range has both ends in order, and a list has every item numeric', () => {
    expect(coerceValue('number', 'BETWEEN', ['1', '5'])).toEqual({ ok: true, value: [1, 5] });
    expect(coerceValue('number', 'BETWEEN', ['5', '1'])).toEqual({ ok: false, error: 'The first value must not be larger than the second.' });
    expect(coerceValue('number', 'BETWEEN', ['1', 'x']).ok).toBe(false);
    expect(coerceValue('number', 'BETWEEN', ['1'] as unknown as [string, string]).ok).toBe(false);
    expect(coerceValue('number', 'IN', ['1', '2'])).toEqual({ ok: true, value: [1, 2] });
    expect(coerceValue('number', 'IN', ['1', 'two']).ok).toBe(false);
  });
});

describe('coerceValue: dates', () => {
  it('accepts a real calendar date as an ISO string', () => {
    expect(coerceValue('date', '>=', '2026-01-31')).toEqual({ ok: true, value: '2026-01-31' });
    expect(coerceValue('date', '=', '2024-02-29')).toEqual({ ok: true, value: '2024-02-29' }); // leap day
  });

  it('refuses a date that does not exist or is not ISO (control: the real ones pass)', () => {
    for (const bad of ['2026-02-30', '2025-02-29', '2026-13-01', '01/02/2026', 'yesterday', '']) {
      expect(coerceValue('date', '=', bad)).toEqual({ ok: false, error: 'Pick a date.' });
    }
  });

  it('orders a date range', () => {
    expect(coerceValue('date', 'BETWEEN', ['2026-01-01', '2026-02-01'])).toEqual({ ok: true, value: ['2026-01-01', '2026-02-01'] });
    expect(coerceValue('date', 'BETWEEN', ['2026-02-01', '2026-01-01']).ok).toBe(false);
  });

  it('accepts a date and time with or without seconds, and refuses a bare date for a timestamp column', () => {
    expect(coerceValue('datetime', '>', '2026-01-05T14:30')).toEqual({ ok: true, value: '2026-01-05T14:30' });
    expect(coerceValue('datetime', '>', '2026-01-05T14:30:15')).toEqual({ ok: true, value: '2026-01-05T14:30:15' });
    expect(coerceValue('datetime', '>', '2026-01-05').ok).toBe(false);
    expect(coerceValue('datetime', '>', '2026-02-30T10:00').ok).toBe(false);
  });

  it('refuses "is" on a timestamp column, since that operator does not belong to it', () => {
    expect(coerceValue('datetime', '=', '2026-01-05T14:30').ok).toBe(false);
  });
});

describe('coerceValue: other kinds', () => {
  it('boolean takes only true or false', () => {
    expect(coerceValue('boolean', '=', true)).toEqual({ ok: true, value: true });
    expect(coerceValue('boolean', '=', false)).toEqual({ ok: true, value: false });
    expect(coerceValue('boolean', '=', null)).toEqual({ ok: false, error: 'Choose Yes or No.' });
    expect(coerceValue('boolean', '=', 'true').ok).toBe(false);
  });

  it('uuid must be the standard shape and is lower-cased', () => {
    const id = '123E4567-E89B-12D3-A456-426614174000';
    expect(coerceValue('uuid', '=', id)).toEqual({ ok: true, value: id.toLowerCase() });
    for (const bad of ['', 'abc', '123e4567e89b12d3a456426614174000', '123e4567-e89b-12d3-a456-42661417400g']) {
      expect(coerceValue('uuid', '=', bad).ok).toBe(false);
    }
    expect(coerceValue('uuid', 'IN', [id, 'nope']).ok).toBe(false);
  });

  it('text needs something in it, but keeps what was typed', () => {
    expect(coerceValue('text', 'CONTAINS', 'abc')).toEqual({ ok: true, value: 'abc' });
    expect(coerceValue('text', '=', ' padded ')).toEqual({ ok: true, value: ' padded ' });
    expect(coerceValue('text', '=', '   ')).toEqual({ ok: false, error: 'Enter a value.' });
    expect(coerceValue('text', 'IN', [])).toEqual({ ok: false, error: 'Add at least one value.' });
    expect(coerceValue('text', 'IN', ['a', ''])).toEqual({ ok: false, error: 'Enter a value.' });
    expect(coerceValue('text', 'IN', ['a', 'b'])).toEqual({ ok: true, value: ['a', 'b'] });
  });

  it('is empty and is not empty take no value, for every kind', () => {
    for (const kind of ['text', 'number', 'date', 'datetime', 'boolean', 'uuid', 'json', 'other'] as ColumnKind[]) {
      expect(coerceValue(kind, 'IS NULL', undefined)).toEqual({ ok: true, value: '' });
      expect(coerceValue(kind, 'IS NOT NULL', null)).toEqual({ ok: true, value: '' });
    }
  });

  it('refuses an operator left over from a different column kind', () => {
    expect(coerceValue('number', 'CONTAINS', '5')).toEqual({ ok: false, error: 'That choice does not fit this column. Pick another.' });
    expect(coerceValue('json', '=', 'x').ok).toBe(false);
  });

  it('a value that looks like SQL is just text, because it is only ever bound as a value', () => {
    expect(coerceValue('text', '=', "x'; DROP TABLE account; --")).toEqual({ ok: true, value: "x'; DROP TABLE account; --" });
    expect(coerceValue('number', '=', '1; DROP TABLE account').ok).toBe(false);
    expect(coerceValue('date', '=', "2026-01-01'; DROP TABLE account; --").ok).toBe(false);
  });
});

describe('prettyDate / describeFilter', () => {
  it('writes dates the way people say them', () => {
    expect(prettyDate('2026-01-05')).toBe('5 Jan 2026');
    expect(prettyDate('2026-12-25T09:05')).toBe('25 Dec 2026 09:05');
    expect(prettyDate('not a date')).toBe('not a date');
  });

  it('describes each shape of filter', () => {
    const f = (operator: string, value: unknown, extra = {}) => ({ column: 'created_at', tablePrefix: 'account', operator, value, ...extra });
    expect(describeFilter(f('>=', '2026-01-05'), 'date')).toBe('account.created_at is on or after 5 Jan 2026');
    expect(describeFilter(f('BETWEEN', ['2026-01-01', '2026-02-01']), 'date')).toBe('account.created_at is between 1 Jan 2026 and 1 Feb 2026');
    expect(describeFilter({ column: 'is_active', operator: '=', value: true }, 'boolean')).toBe('is_active is Yes');
    expect(describeFilter(f('IS NULL', ''), 'datetime')).toBe('account.created_at is empty');
    expect(describeFilter({ column: 'name', operator: 'CONTAINS', value: 'abc' }, 'text')).toBe('name contains abc');
  });

  it('cuts a long list after three values', () => {
    const filter = { column: 'id', operator: 'IN', value: [1, 2, 3, 4, 5] };
    expect(describeFilter(filter, 'number')).toBe('id is one of 1, 2, 3 and 2 more');
    expect(describeFilter({ ...filter, value: [1, 2, 3] }, 'number')).toBe('id is one of 1, 2, 3');
  });

  it('still reads an operator it does not know', () => {
    expect(describeFilter({ column: 'x', operator: 'LIKE', value: 'a%' }, 'text')).toBe('x like a%');
  });
});

describe('operatorHelp', () => {
  it('says in one sentence what every operator of every kind does', () => {
    for (const kind of ['text', 'number', 'date', 'datetime', 'boolean', 'uuid', 'json', 'other'] as const) {
      for (const o of operatorsFor(kind)) expect(operatorHelp(kind, o.value), `${kind} ${o.value}`).not.toBe('');
    }
  });

  it('words dates as before and after, and a text search as ignoring capital letters', () => {
    expect(operatorHelp('date', '>')).toMatch(/after this day/);
    expect(operatorHelp('number', '>')).toMatch(/above/);
    expect(operatorHelp('text', 'CONTAINS')).toMatch(/ignoring capital letters/);
  });

  it('talks about groups for a condition on a total', () => {
    expect(operatorHelp('number', '>', 'groups')).toBe('Keeps groups with a value above this one (not equal to it).');
    expect(operatorHelp('number', '>')).toMatch(/Keeps rows/); // control
  });

  it('has nothing to say about an operator it does not know', () => {
    expect(operatorHelp('text', 'LIKE')).toBe('');
  });
});
