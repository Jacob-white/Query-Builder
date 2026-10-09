import type { SchemaSnapshot, SqlDialect } from "../types";
import { compileSpecToSql } from "./compiler";
import { parseSqlToSpec } from "./sqlParser";

/**
 * Formatting-insensitive form of SQL (case, whitespace, identifier quotes, trailing `;`).
 * String literals are kept verbatim so edits inside them still count as changes.
 */
function normalizeSqlForCompare(sql: string): string {
  const joined = sql
    .split(/('(?:[^']|'')*')/)
    .map((seg, i) =>
      i % 2 === 1
        ? seg
        : seg
            .replace(/["`]/g, "")
            .replace(/\[([A-Za-z_][\w ]*)\]/g, "$1")
            .replace(/\s+/g, " ")
            // Whitespace was collapsed to single spaces just above, so " ?" covers "\s*".
            .replace(/ ?([(),=]) ?/g, "$1")
            .toLowerCase(),
    )
    .join("");
  return stripTrailingSemicolons(joined).trim();
}

// Linear-time equivalent of `.replace(/;+\s*$/, "")`.
function stripTrailingSemicolons(text: string): string {
  const trimmed = text.trimEnd();
  let end = trimmed.length;
  while (end > 0 && trimmed[end - 1] === ";") end--;
  return end === trimmed.length ? text : trimmed.slice(0, end);
}

/** True when the SQL carries line or block comments (outside string literals) that the visual model cannot represent. */
function hasSqlComments(sql: string): boolean {
  return /--|\/\*/.test(sql.replace(/'(?:[^']|'')*'/g, "''"));
}

export interface RawSqlSnapshot {
  isRawMode: boolean;
  rawSql: string;
  compiledSql: string;
  dialect: SqlDialect;
  schema: SchemaSnapshot | null | undefined;
}

/**
 * Whether leaving raw-SQL mode would silently discard the user's SQL.
 * Loss detection is semantic: nothing is lost when the raw SQL maps onto the visual model
 * (parses, has no comments the model cannot hold, and recompiles to what the canvas shows).
 */
export function wouldLoseRawSql(snap: RawSqlSnapshot): boolean {
  if (!snap.isRawMode || !snap.rawSql.trim()) return false;
  if (hasSqlComments(snap.rawSql)) return true;
  const parsed = parseSqlToSpec(snap.rawSql, snap.schema);
  return (
    !parsed ||
    normalizeSqlForCompare(compileSpecToSql(parsed, snap.dialect, snap.schema)) !==
      normalizeSqlForCompare(snap.compiledSql)
  );
}

export { normalizeSqlForCompare, hasSqlComments };
