const JOIN_KINDS = new Set(["INNER", "LEFT", "RIGHT", "FULL"]);

/**
 * A join kind in the form the visual builder matches (`"INNER JOIN"`, `"LEFT JOIN"`, ...). The compiler and the
 * server write the bare kind (`"INNER"`), in any case and optionally with `OUTER` or `JOIN`; a kind that is none of
 * the four is returned as written, and a missing one is a left join. Read word by word, not with a pattern, so no
 * input can make it slow.
 */
export function toBuilderJoinType(type: string | undefined): string {
  if (type === undefined || type.trim() === "") return "LEFT JOIN";
  const words = type.trim().toUpperCase().split(/\s+/);
  if (words[words.length - 1] === "JOIN") words.pop();
  if (words[words.length - 1] === "OUTER") words.pop();
  return words.length === 1 && JOIN_KINDS.has(words[0]) ? `${words[0]} JOIN` : type;
}
