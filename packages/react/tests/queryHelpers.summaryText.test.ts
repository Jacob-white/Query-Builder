import { describe, it, expect } from 'vitest';
import { columnLabel, columnsSummary, conditionsSummary, joinsSummary, listSummary, sortsSummary, subqueriesSummary, windowSummary } from '../src/utils/queryHelpers/summaryText';

const col = (name: string, aggregate?: string, alias?: string) => ({ table: 't', name, aggregate, alias });

describe('listSummary', () => {
  it('lists up to the limit, then says how many were left out', () => {
    expect(listSummary(['a', 'b'])).toBe('a, b');
    expect(listSummary(['a', 'b', 'c'])).toBe('a, b, c');
    expect(listSummary(['a', 'b', 'c', 'd', 'e'])).toBe('a, b, c and 2 more');
    expect(listSummary(['a', 'b', 'c', 'd', 'e'], 2)).toBe('a, b and 3 more');
    expect(listSummary([])).toBe('');
  });
});

describe('columnLabel', () => {
  it('uses the plain name, the alias when aggregated and aliased, or words for the aggregate', () => {
    expect(columnLabel(col('aum'))).toBe('aum');
    expect(columnLabel(col('aum', 'SUM'))).toBe('Sum of aum');
    expect(columnLabel(col('aum', 'SUM', ' Total '))).toBe('Total');
    expect(columnLabel(col('id', 'count'))).toBe('Count of id');
    expect(columnLabel(col('d', 'MAX'))).toBe('Highest d');
  });

  it('ignores an alias on a column that is not aggregated, since it is not shown that way (control)', () => {
    expect(columnLabel(col('aum', undefined, 'Total'))).toBe('aum');
  });
});

describe('columnsSummary', () => {
  const selected = { 't.a': col('a'), 't.b': col('b', 'SUM') };

  it('says there are none yet', () => {
    expect(columnsSummary({}, [])).toBe('No columns yet');
  });

  it('counts and names the columns in order, singular and plural', () => {
    expect(columnsSummary(selected, ['t.b', 't.a'])).toBe('2 columns: Sum of b, a');
    expect(columnsSummary(selected, ['t.a'])).toBe('1 column: a');
  });

  it('cuts a long list after four, and skips an order entry with no selection', () => {
    const many = Object.fromEntries(['a', 'b', 'c', 'd', 'e', 'f'].map((n) => [`t.${n}`, col(n)]));
    expect(columnsSummary(many, Object.keys(many))).toBe('6 columns: a, b, c, d and 2 more');
    expect(columnsSummary(selected, ['t.ghost', 't.a'])).toBe('1 column: a');
  });
});

describe('joinsSummary / sortsSummary / conditionsSummary', () => {
  it('say None when there is nothing', () => {
    expect(joinsSummary([])).toBe('None');
    expect(sortsSummary([])).toBe('None');
    expect(conditionsSummary([])).toBe('None');
  });

  it('name the joined tables', () => {
    expect(joinsSummary([{ table: 'account_client' }, { table: 'profile' }])).toBe('account_client, profile');
  });

  it('write each sort with its direction in words', () => {
    expect(sortsSummary([{ column: 'created_at', direction: 'DESC' }, { column: 'name', direction: 'ASC' }])).toBe('created_at descending, name ascending');
  });

  it('show two conditions and then a count, since they are long', () => {
    expect(conditionsSummary(['a is 1', 'b is 2'])).toBe('a is 1, b is 2');
    expect(conditionsSummary(['a is 1', 'b is 2', 'c is 3', 'd is 4'])).toBe('a is 1, b is 2 and 2 more');
  });
});

describe('windowSummary and subqueriesSummary', () => {
  it('reads window functions in words, with their column and order, and None when there are none', () => {
    expect(windowSummary([])).toBe('None');
    expect(windowSummary([{ function: 'row_number' }])).toBe('ROW_NUMBER');
    expect(windowSummary([{ function: 'SUM', arguments: ['a.b'], order_by: [{ column: 'a.c' }] }])).toBe('SUM of a.b ordered by a.c');
    expect(windowSummary([{ function: 'RANK' }, { function: 'LAG', arguments: ['a.b'] }, { function: 'NTILE', arguments: [4] }])).toBe('RANK, LAG of a.b and 1 more');
  });

  it('lists sub-query names, or None', () => {
    expect(subqueriesSummary([])).toBe('None');
    expect(subqueriesSummary(['recent', 'big'])).toBe('recent, big');
  });
});
