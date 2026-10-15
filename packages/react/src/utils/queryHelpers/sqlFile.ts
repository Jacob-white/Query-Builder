/**
 * Naming and writing the `.sql` file a host application offers for download. Pure: the host does the saving.
 *
 * The statement should be the one from `QueryCompiler.compile_runnable()` (values written in), so the file runs as it is
 * in a SQL window.
 */

/** A file-name-safe piece: letters, digits, `-` and `_`; anything else becomes `-`. Never empty. */
export function slugifyFilenamePart(value: string): string {
  return value.trim().replace(/[^a-z0-9-_]+/gi, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "export";
}

/** `query-feature_flag-2026-10-14.sql`: the first table (or "results"), today's date. */
export function sqlFilename(table: string | undefined, now: Date = new Date()): string {
  return `query-${slugifyFilenamePart(table || "results")}-${now.toISOString().slice(0, 10)}.sql`;
}

/** The file's text: a short header comment, then the statement ended once with a semicolon. */
export function sqlFileText(sql: string, table: string | undefined, now: Date = new Date()): string {
  const stamp = now.toISOString().slice(0, 19).replace("T", " ");
  const header = `-- Query Builder: ${table || "query"}, ${stamp} UTC\n-- Values are written in, so this runs as it is in a SQL window. It reads data only.\n`;
  let body = sql.trimEnd();
  while (body.endsWith(";")) body = body.slice(0, -1).trimEnd();
  return `${header}${body};\n`;
}
