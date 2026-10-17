/**
 * The text of one CSV cell, safe to open in a spreadsheet.
 *
 * Excel and LibreOffice run a cell as a formula when its text starts with `=`, `+`, `-`, `@`, a tab or a carriage return,
 * even when the cell is quoted. A query can return text someone else typed, and a column name can be a caller's alias, so
 * such text is given an apostrophe in front (the spreadsheet then shows it as text). Numbers, bigints and booleans are not
 * text and are written as they print, so a negative number stays a number; `null` and `undefined` are empty. Any other
 * value is read as the text `String(value)` gives, and protected the same way. The check is one character, so it is
 * linear however large the cell.
 */
export function csvCellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number" || typeof value === "bigint" || typeof value === "boolean") return String(value);
  const text = String(value);
  return /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
}
