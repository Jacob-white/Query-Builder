/**
 * Class name composition utility.
 * Merges string class names, ignoring undefined, null, and falsey values.
 */
export function cx(...classes: (string | undefined | null | false)[]): string | undefined {
  const filtered = classes.filter(Boolean);
  return filtered.length > 0 ? filtered.join(" ") : undefined;
}
