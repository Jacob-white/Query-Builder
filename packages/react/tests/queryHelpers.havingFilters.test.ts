import { describe, it, expect } from 'vitest';
import {
  describeHaving,
  havingForSpec,
  havingKind,
  havingOperators,
  havingTargets,
  parseHaving,
  ROWS_TARGET,
  targetFor,
  type HavingFilter,
  type HavingTarget,
} from '../src/utils/queryHelpers/havingFilters';

const TYPES: Record<string, string> = {
  'account.id': 'UUID',
  'account.aum': 'NUMERIC(26, 8)',
  'account.opened': 'DATE',
  'account.updated_at': 'TIMESTAMP',
  'account.name': 'VARCHAR',
  'account.active': 'BOOLEAN',
  'account.data': 'JSON',
};
const typeOf = (table: string, column: string) => TYPES[`${table}.${column}`];
const col = (name: string, aggregate?: string, alias?: string) => ({ table: 'account', name, aggregate, alias });
const selected = (...cols: ReturnType<typeof col>[]) => Object.fromEntries(cols.map((c) => [`account.${c.name}`, c]));
const orderOf = (...cols: ReturnType<typeof col>[]) => cols.map((c) => `account.${c.name}`);

describe('havingTargets', () => {
  it('offers nothing while no column is aggregated', () => {
    const cols = [col('name'), col('aum')];
    expect(havingTargets(selected(...cols), orderOf(...cols), typeOf)).toEqual([]);
  });

  it('offers the row count and each aggregated column, using the alias as the label', () => {
    const cols = [col('name'), col('aum', 'SUM', 'Total AUM'), col('id', 'COUNT')];
    const targets = havingTargets(selected(...cols), orderOf(...cols), typeOf);
    expect(targets.map((t) => t.label)).toEqual(['Number of rows', 'Total AUM', 'COUNT(account.id)']);
    expect(targets[0]).toBe(ROWS_TARGET);
  });

  it('follows the order of the columns and lists a repeated aggregate once', () => {
    const cols = [col('aum', 'SUM'), col('aum', 'SUM')];
    const targets = havingTargets(selected(...cols), ['account.aum', 'account.aum'], typeOf);
    expect(targets.map((t) => t.label)).toEqual(['Number of rows', 'SUM(account.aum)']);
  });

  it('leaves out MIN and MAX over a column that cannot be compared, but not over dates, numbers or text (control)', () => {
    for (const bad of ['id', 'data', 'active']) {
      const cols = [col(bad, 'MAX')];
      expect(havingTargets(selected(...cols), orderOf(...cols), typeOf).map((t) => t.agg)).toEqual(['COUNT']);
    }
    for (const fine of ['aum', 'opened', 'updated_at', 'name']) {
      const cols = [col(fine, 'MIN')];
      expect(havingTargets(selected(...cols), orderOf(...cols), typeOf).map((t) => t.agg)).toEqual(['COUNT', 'MIN']);
    }
  });

  it('ignores a column that is selected but not in the order, and an aggregate it does not know', () => {
    const cols = [col('aum', 'SUM'), col('name', 'MEDIAN')];
    expect(havingTargets(selected(...cols), ['account.aum', 'account.name'], typeOf).map((t) => t.label)).toEqual(['Number of rows', 'SUM(account.aum)']);
  });
});

describe('havingKind / havingOperators', () => {
  const target = (agg: HavingTarget['agg'], baseType?: string): HavingTarget => ({ column: 'account.x', agg, label: 'x', baseType });

  it('treats a count, sum or average as a number whatever the column is', () => {
    expect(havingKind(target('COUNT', 'VARCHAR'))).toBe('number');
    expect(havingKind(target('SUM', 'NUMERIC(26, 8)'))).toBe('number');
    expect(havingKind(target('AVG', 'INTEGER'))).toBe('number');
    expect(havingKind(ROWS_TARGET)).toBe('number');
  });

  it('lets a MIN or MAX follow the column, so a date picker is offered for a date', () => {
    expect(havingKind(target('MIN', 'DATE'))).toBe('date');
    expect(havingKind(target('MAX', 'TIMESTAMP'))).toBe('datetime');
    expect(havingKind(target('MAX', 'VARCHAR'))).toBe('text');
  });

  it('offers only the six comparisons, never contains, between, one-of or empty checks', () => {
    expect(havingOperators(ROWS_TARGET).map((o) => o.value)).toEqual(['=', '!=', '>', '>=', '<', '<=']);
  });

  it('drops "is" for a timestamp, as in an ordinary filter', () => {
    expect(havingOperators(target('MAX', 'TIMESTAMP')).map((o) => o.value)).toEqual(['>', '>=', '<', '<=']);
  });
});

describe('havingForSpec', () => {
  const rows: HavingFilter = { id: 'a', column: '*', agg: 'COUNT', operator: '>=', value: 3 };
  const sum: HavingFilter = { id: 'b', column: 'account.aum', agg: 'SUM', operator: '>', value: 100 };
  const specColumns = ['account.name', { column: 'account.aum', agg: 'SUM', alias: 'Total' }];

  it('sends each filter as a spec item with a lower-case aggregate and the operator symbol', () => {
    expect(havingForSpec([rows, sum], specColumns)).toEqual([
      { column: '*', agg: 'count', op: '>=', value: 3 },
      { column: 'account.aum', agg: 'sum', op: '>', value: 100 },
    ]);
  });

  it('drops a filter whose aggregate is no longer in the columns, and keeps the rest', () => {
    const stale: HavingFilter = { id: 'c', column: 'account.aum', agg: 'AVG', operator: '>', value: 1 };
    expect(havingForSpec([stale, rows], specColumns)).toEqual([{ column: '*', agg: 'count', op: '>=', value: 3 }]);
  });

  it('drops every filter once nothing is aggregated (the server would refuse the query)', () => {
    expect(havingForSpec([rows, sum], ['account.name', 'account.aum'])).toEqual([]);
    expect(havingForSpec([rows], [])).toEqual([]);
    expect(havingForSpec([rows], undefined)).toEqual([]);
  });

  it('reads an aggregate written as `aggregate` as well as `agg`', () => {
    expect(havingForSpec([sum], [{ column: 'account.aum', aggregate: 'sum' }])).toHaveLength(1);
  });

  it('passes a list or range value through untouched', () => {
    const range: HavingFilter = { id: 'd', column: '*', agg: 'COUNT', operator: '=', value: [1, 2] };
    expect(havingForSpec([range], specColumns)[0].value).toEqual([1, 2]);
  });
});

describe('parseHaving', () => {
  it('reads what havingForSpec wrote, so a saved query comes back as it was', () => {
    const saved = [{ column: 'account.aum', agg: 'sum', op: '>', value: 100 }, { column: '*', agg: 'count', op: '<=', value: 9 }];
    expect(parseHaving(saved).map((f) => ({ column: f.column, agg: f.agg, operator: f.operator, value: f.value }))).toEqual([
      { column: 'account.aum', agg: 'SUM', operator: '>', value: 100 },
      { column: '*', agg: 'COUNT', operator: '<=', value: 9 },
    ]);
  });

  it('understands the server’s operator names as well as symbols', () => {
    const out = parseHaving([{ column: '*', agg: 'count', op: 'gte', value: 2 }, { column: '*', agg: 'count', operator: 'lt', value: 5 }]);
    expect(out.map((f) => f.operator)).toEqual(['>=', '<']);
  });

  it('skips anything that is not a usable filter, and tolerates a non-list', () => {
    expect(parseHaving(undefined)).toEqual([]);
    expect(parseHaving('x')).toEqual([]);
    expect(parseHaving([null, 5, {}, { column: '*', agg: 'median', op: '>', value: 1 }, { column: '*', agg: 'count', op: 'like', value: 1 }, { column: '', agg: 'count', op: '>', value: 1 }, { column: '*', agg: 'count', op: '>' }])).toEqual([]);
  });

  it('gives each filter its own id', () => {
    const out = parseHaving([{ column: '*', agg: 'count', op: '>', value: 1 }, { column: 'account.aum', agg: 'sum', op: '>', value: 1 }]);
    expect(new Set(out.map((f) => f.id)).size).toBe(2);
  });
});

describe('describeHaving / targetFor', () => {
  const targets: HavingTarget[] = [ROWS_TARGET, { column: 'account.aum', agg: 'SUM', label: 'Total AUM', baseType: 'NUMERIC(26, 8)' }];

  it('uses the aggregate’s label', () => {
    expect(describeHaving({ id: 'a', column: 'account.aum', agg: 'SUM', operator: '>', value: 100 }, targets)).toBe('Total AUM is greater than 100');
    expect(describeHaving({ id: 'b', column: '*', agg: 'COUNT', operator: '>=', value: 3 }, targets)).toBe('Number of rows is at least 3');
  });

  it('writes a date value the way people say it, for a MIN or MAX over a date', () => {
    const dates: HavingTarget[] = [ROWS_TARGET, { column: 'account.opened', agg: 'MIN', label: 'MIN(account.opened)', baseType: 'DATE' }];
    expect(describeHaving({ id: 'c', column: 'account.opened', agg: 'MIN', operator: '<', value: '2026-01-05' }, dates)).toBe('MIN(account.opened) is before 5 Jan 2026');
  });

  it('still describes a filter whose aggregate has gone, and finds the target only when it is there (control)', () => {
    const gone: HavingFilter = { id: 'd', column: 'account.aum', agg: 'AVG', operator: '>', value: 1 };
    expect(targetFor(gone, targets)).toBeUndefined();
    expect(describeHaving(gone, targets)).toBe('AVG(account.aum) is greater than 1');
    expect(targetFor({ ...gone, agg: 'SUM' }, targets)).toBe(targets[1]);
  });
});
