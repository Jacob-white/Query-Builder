/**
 * Join criteria, filled from a schema's declared links before a spec is loaded into the builder.
 *
 * A loaded join that names no columns becomes `id = id` (the builder's default), which looks finished and matches unrelated
 * rows. A spec from a saved query or an AI helper can carry such a join, so it can be passed through here first: a missing
 * column pair is filled from the one declared link between the joined table and a table already in the query. When there is
 * not exactly one such link nothing is guessed; the join is reported, and `loadCompleted` blanks it in the builder so it
 * shows as still to be chosen. Pure apart from the two builder actions `loadCompleted` is given.
 */
import type { ForeignKeyEdge } from './joinLinks';

export type JoinLink = ForeignKeyEdge;

export interface UnresolvedJoin {
  /** The id the builder gives the join: its own, else `join_<position>`. */
  id: string;
  table: string;
  /** `none`: no declared link to a table in the query. `several`: more than one, and the join does not say which. */
  reason: 'none' | 'several';
}

interface Criteria {
  left_table: string;
  left_col: string;
  right_col: string;
}

const isName = (value: unknown): value is string => typeof value === 'string' && value !== '';

/** Every way the declared links join `table` to a table in the query, each written as the join's three fields. */
function candidatesFor(table: string, inQuery: Set<string>, links: JoinLink[]): Criteria[] {
  const found = new Map<string, Criteria>();
  for (const l of links) {
    if (inQuery.has(l.table) && l.foreign_table === table) {
      found.set(`${l.table}|${l.column}|${l.foreign_column}`, { left_table: l.table, left_col: l.column, right_col: l.foreign_column });
    }
    if (l.table === table && inQuery.has(l.foreign_table)) {
      found.set(`${l.foreign_table}|${l.foreign_column}|${l.column}`, { left_table: l.foreign_table, left_col: l.foreign_column, right_col: l.column });
    }
  }
  return [...found.values()];
}

/**
 * `spec` with each join's missing criteria filled from the one declared link, and the joins that could not be completed.
 * A join that already names its columns, or has an `on` condition, is left as it is; one that names some of them is
 * completed only where the link agrees with what it says. The spec given is not changed.
 */
export function completeJoins(
  spec: Record<string, unknown>,
  links: JoinLink[],
): { spec: Record<string, unknown>; unresolved: UnresolvedJoin[] } {
  const joins = spec?.joins;
  if (!Array.isArray(joins)) return { spec, unresolved: [] };

  const inQuery = new Set<string>(isName(spec.table) ? [spec.table] : []);
  const unresolved: UnresolvedJoin[] = [];
  const completed = joins.map((raw, index) => {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw) || !isName((raw as { table?: unknown }).table)) return raw;
    const join = raw as Record<string, unknown> & { table: string };
    const named = { left_table: join.left_table, left_col: join.left_col, right_col: join.right_col };
    const written = Array.isArray(join.on) && join.on.length > 0;
    const complete = written || (isName(named.left_table) && isName(named.left_col) && isName(named.right_col));
    let result: Record<string, unknown> = join;
    if (!complete) {
      const fits = candidatesFor(join.table, inQuery, links).filter(
        (c) =>
          (!isName(named.left_table) || c.left_table === named.left_table) &&
          (!isName(named.left_col) || c.left_col === named.left_col) &&
          (!isName(named.right_col) || c.right_col === named.right_col),
      );
      if (fits.length === 1) {
        result = { ...join, left_table: fits[0].left_table, left_col: fits[0].left_col, right_col: fits[0].right_col };
      } else {
        unresolved.push({ id: isName(join.id) ? join.id : `join_${index + 1}`, table: join.table, reason: fits.length === 0 ? 'none' : 'several' });
      }
    }
    inQuery.add(join.table);
    return result;
  });
  return { spec: { ...spec, joins: completed }, unresolved };
}

/** The two builder actions a load needs. `updateJoin` is optional so a builder without it still loads. */
export interface JoinLoadActions {
  loadSpec: (spec: never) => void;
  updateJoin?: (id: string, patch: { left_table?: string; left_col?: string; right_col?: string }) => void;
}

/**
 * Load a spec into the builder with its join criteria completed. A join that could not be completed is then blanked,
 * because the builder defaults it to `id = id`, which reads as finished and joins the wrong rows; blank, it shows as still
 * to be chosen. Returns the spec as loaded and the joins that could not be completed, so the caller can say so.
 */
export function loadCompleted(
  actions: JoinLoadActions,
  spec: Record<string, unknown>,
  links: JoinLink[],
): { spec: Record<string, unknown>; unresolved: UnresolvedJoin[] } {
  const completed = completeJoins(spec, links);
  actions.loadSpec(completed.spec as never);
  for (const join of completed.unresolved) actions.updateJoin?.(join.id, { left_table: undefined, left_col: '', right_col: '' });
  return completed;
}
