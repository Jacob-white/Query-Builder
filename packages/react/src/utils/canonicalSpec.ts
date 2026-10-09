/**
 * Serializes a QuerySpec or object canonically, sorting all keys recursively
 * so equivalent specifications compare identically regardless of key ordering.
 */
export function fastCanonicalSpec(obj: unknown): string {
  if (obj === null || obj === undefined) return "";
  if (typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return "[" + obj.map(fastCanonicalSpec).join(",") + "]";
  }
  const rec = obj as Record<string, unknown>;
  const keys = Object.keys(rec).sort().filter((k) => rec[k] !== undefined);
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + fastCanonicalSpec(rec[k])).join(",") + "}";
}
