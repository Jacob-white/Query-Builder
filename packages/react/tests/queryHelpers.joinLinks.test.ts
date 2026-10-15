import { describe, it, expect } from 'vitest';
import { describeLink, directLinks, isProvenJoin, linkedTables, type ForeignKeyEdge } from '../src/utils/queryHelpers/joinLinks';

const JOB_TO_CONFIG: ForeignKeyEdge = { table: 'apply_job', column: 'config_id', foreign_table: 'apply_configuration', foreign_column: 'id' };
const LOG_TO_JOB: ForeignKeyEdge = { table: 'apply_audit_log', column: 'job_id', foreign_table: 'apply_job', foreign_column: 'id' };
const SELF: ForeignKeyEdge = { table: 'apply_configuration', column: 'parent_config_id', foreign_table: 'apply_configuration', foreign_column: 'id' };
const FKS = [JOB_TO_CONFIG, LOG_TO_JOB, SELF];

describe('describeLink', () => {
  it('reads as from → to', () => {
    expect(describeLink(JOB_TO_CONFIG)).toBe('apply_job.config_id → apply_configuration.id');
  });
});

describe('directLinks', () => {
  it('finds a link where the candidate holds the foreign key', () => {
    expect(directLinks('apply_job', ['apply_configuration'], FKS)).toEqual([JOB_TO_CONFIG]);
  });

  it('finds a link where the candidate is the referenced table (the other direction)', () => {
    expect(directLinks('apply_configuration', ['apply_job'], FKS)).toEqual([JOB_TO_CONFIG]);
  });

  it('is empty for a table with no declared link to anything in the query (control)', () => {
    expect(directLinks('feature_flag', ['apply_job', 'apply_configuration'], FKS)).toEqual([]);
    expect(directLinks('apply_audit_log', ['apply_configuration'], FKS)).toEqual([]); // two hops away is not direct
  });

  it('is empty when nothing is in the query yet', () => {
    expect(directLinks('apply_job', [], FKS)).toEqual([]);
  });

  it('does not count a self-reference as a link to another table', () => {
    expect(directLinks('apply_configuration', ['apply_job'], [SELF])).toEqual([]);
  });

  it('lists every edge when the candidate links to several tables in the query', () => {
    expect(directLinks('apply_job', ['apply_configuration', 'apply_audit_log'], FKS)).toEqual([JOB_TO_CONFIG, LOG_TO_JOB]);
  });
});

describe('linkedTables', () => {
  it('lists neighbours in both directions, sorted, without the table itself', () => {
    expect(linkedTables('apply_job', FKS)).toEqual(['apply_audit_log', 'apply_configuration']);
    expect(linkedTables('apply_configuration', FKS)).toEqual(['apply_job']); // the self-reference adds nothing
  });

  it('is empty for an unlinked table', () => {
    expect(linkedTables('feature_flag', FKS)).toEqual([]);
  });
});

describe('isProvenJoin', () => {
  const join = { left_table: 'apply_job', left_col: 'config_id', table: 'apply_configuration', right_col: 'id' };

  it('is true when a foreign key declares the same two columns', () => {
    expect(isProvenJoin(join, FKS)).toBe(true);
  });

  it('is true with the join written the other way round', () => {
    expect(isProvenJoin({ left_table: 'apply_configuration', left_col: 'id', table: 'apply_job', right_col: 'config_id' }, FKS)).toBe(true);
  });

  it('is false for a name-matching guess between unrelated columns (control)', () => {
    expect(isProvenJoin({ left_table: 'apply_job', left_col: 'id', table: 'apply_configuration', right_col: 'id' }, FKS)).toBe(false);
  });

  it('is false when the tables are linked but through different columns', () => {
    expect(isProvenJoin({ left_table: 'apply_job', left_col: 'id', table: 'apply_audit_log', right_col: 'job_id' }, FKS)).toBe(true);
    expect(isProvenJoin({ left_table: 'apply_job', left_col: 'config_id', table: 'apply_audit_log', right_col: 'job_id' }, FKS)).toBe(false);
  });

  it('is false when the join has no left table', () => {
    expect(isProvenJoin({ left_col: 'config_id', table: 'apply_configuration', right_col: 'id' }, FKS)).toBe(false);
  });
});
