import { normalizeCombiner } from "./filterCombiners";
import type {
  QuerySpec,
  SchemaSnapshot,
  CteSpec,
  WindowFunctionSpec,
} from "../types";

const ALLOWED_OPERATORS = [
  "IS NOT NULL",
  "IS NULL",
  "NOT IN",
  "IN",
  "BETWEEN",
  "ILIKE",
  "LIKE",
  "STARTS_WITH",
  "ENDS_WITH",
  "CONTAINS",
  ">=",
  "<=",
  "!=",
  "<>",
  "=",
  ">",
  "<",
];

/** True for any code unit matched by the regex class `\s` (computed without a regex). */
function isWs(code: number): boolean {
  return (
    code === 32 ||
    (code >= 9 && code <= 13) ||
    code === 0xa0 ||
    code === 0x1680 ||
    (code >= 0x2000 && code <= 0x200a) ||
    code === 0x2028 ||
    code === 0x2029 ||
    code === 0x202f ||
    code === 0x205f ||
    code === 0x3000 ||
    code === 0xfeff
  );
}

/** Index of the first non-whitespace character at or after `from` (or `s.length`). */
function skipWs(s: string, from: number): number {
  let i = from;
  while (i < s.length && isWs(s.charCodeAt(i))) i++;
  return i;
}

/** ASCII case-insensitive match of the upper-case `word` at `s[i]`. */
function matchWordCI(s: string, i: number, word: string): boolean {
  for (let k = 0; k < word.length; k++) {
    let c = s.charCodeAt(i + k);
    if (c >= 97 && c <= 122) c -= 32;
    if (c !== word.charCodeAt(k)) return false;
  }
  return true;
}

/**
 * Case-insensitively matches `words` at `s[i]`, separated by one or more whitespace characters.
 * Returns the end index of the match, or -1.
 */
function matchWordsCI(s: string, i: number, words: string[]): number {
  let pos = i;
  for (let k = 0; k < words.length; k++) {
    if (!matchWordCI(s, pos, words[k])) return -1;
    pos += words[k].length;
    if (k < words.length - 1) {
      const next = skipWs(s, pos);
      if (next === pos) return -1;
      pos = next;
    }
  }
  return pos;
}

/** Index of the first case-insensitive occurrence of `word` at or after `from`, or -1. */
function findWordCI(s: string, word: string, from: number): number {
  for (let i = from; i + word.length <= s.length; i++) {
    if (matchWordCI(s, i, word)) return i;
  }
  return -1;
}

/** Removes `-- ...` line comments (up to, not including, the line terminator). */
function stripLineComments(sql: string): string {
  const parts: string[] = [];
  let i = 0;
  for (;;) {
    const j = sql.indexOf("--", i);
    if (j === -1) {
      parts.push(sql.slice(i));
      return parts.join("");
    }
    parts.push(sql.slice(i, j));
    let k = j + 2;
    while (k < sql.length) {
      const c = sql.charCodeAt(k);
      if (c === 10 || c === 13 || c === 0x2028 || c === 0x2029) break;
      k++;
    }
    i = k;
  }
}

/** Removes `/* ... *\/` block comments; an unterminated comment is left untouched. */
function stripBlockComments(sql: string): string {
  const parts: string[] = [];
  let i = 0;
  for (;;) {
    const j = sql.indexOf("/*", i);
    const end = j === -1 ? -1 : sql.indexOf("*/", j + 2);
    if (end === -1) {
      parts.push(sql.slice(i));
      return parts.join("");
    }
    parts.push(sql.slice(i, j));
    i = end + 2;
  }
}

/** Drops all trailing commas. */
function stripTrailingCommas(s: string): string {
  let end = s.length;
  while (end > 0 && s.charCodeAt(end - 1) === 44) end--;
  return s.slice(0, end);
}

/** Characters allowed in `a.b`-style column references: `[a-zA-Z0-9_".`[\]]`. */
function isColumnRefChar(code: number): boolean {
  return (
    (code >= 97 && code <= 122) ||
    (code >= 65 && code <= 90) ||
    (code >= 48 && code <= 57) ||
    code === 95 ||
    code === 34 ||
    code === 46 ||
    code === 96 ||
    code === 91 ||
    code === 93
  );
}

/** Finds the first `<columnRef> = <columnRef>` (whitespace allowed around `=`) in `s`. */
function matchColumnEquality(s: string): [string, string] | null {
  let i = 0;
  while (i < s.length) {
    if (!isColumnRefChar(s.charCodeAt(i))) {
      i++;
      continue;
    }
    let end = i;
    while (end < s.length && isColumnRefChar(s.charCodeAt(end))) end++;
    const eq = skipWs(s, end);
    if (s.charCodeAt(eq) === 61) {
      const rhs = skipWs(s, eq + 1);
      let rhsEnd = rhs;
      while (rhsEnd < s.length && isColumnRefChar(s.charCodeAt(rhsEnd))) rhsEnd++;
      if (rhsEnd > rhs) return [s.slice(i, end), s.slice(rhs, rhsEnd)];
    }
    // Every start inside this run ends at the same place, so none of them can match either.
    i = end;
  }
  return null;
}

/** Equivalent of `/PARTITION\s+BY\s+(.*?)(?=\s+ORDER\s+BY|$)/i` for text without line terminators. */
function extractPartitionBy(over: string): string | undefined {
  let from = 0;
  for (;;) {
    const at = findWordCI(over, "PARTITION", from);
    if (at === -1) return undefined;
    const afterBy = matchWordsCI(over, at, ["PARTITION", "BY"]);
    const start = afterBy === -1 ? -1 : skipWs(over, afterBy);
    if (start === -1 || start === afterBy) {
      from = at + 1;
      continue;
    }
    for (let j = start; j < over.length; j++) {
      if (isWs(over.charCodeAt(j)) && !isWs(over.charCodeAt(j - 1))) {
        const orderAt = skipWs(over, j);
        if (matchWordCI(over, orderAt, "ORDER") && matchWordsCI(over, orderAt, ["ORDER", "BY"]) !== -1) {
          return over.slice(start, j);
        }
      }
    }
    return over.slice(start);
  }
}

/** Equivalent of `/ORDER\s+BY\s+(.*?)$/i` for text without line terminators. */
function extractOrderBy(over: string): string | undefined {
  let from = 0;
  for (;;) {
    const at = findWordCI(over, "ORDER", from);
    if (at === -1) return undefined;
    const afterBy = matchWordsCI(over, at, ["ORDER", "BY"]);
    if (afterBy !== -1) {
      const start = skipWs(over, afterBy);
      if (start > afterBy) return over.slice(start);
    }
    from = at + 1;
  }
}

/**
 * Strips quotes/backticks/brackets from an identifier.
 */
export function cleanIdentifier(ident: string): string {
  if (!ident) return "";
  let clean = ident.trim();

  // If compound table.column, clean each part
  if (clean.includes(".")) {
    return clean
      .split(".")
      .map((part) => cleanIdentifier(part))
      .join(".");
  }

  // Remove surrounding quotes, backticks, or brackets
  clean = clean.replace(/^["'`\[]|["'`\]]$/g, "");
  return clean.trim();
}

/** Words that can never be an alias: clause starters and join introducers. */
const RESERVED_NON_ALIAS = new Set([
  "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "FETCH", "FOR", "UNION", "INTERSECT",
  "EXCEPT", "ON", "USING", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "OUTER",
  "WINDOW", "QUALIFY", "LATERAL", "RETURNING",
]);

/**
 * Table-hint words that are legal aliases on their own (`JOIN orders final ON ...`) and only act
 * as hints when the following token says so (`WITH (NOLOCK)`, `FORCE INDEX (...)`, ...).
 */
const HINT_WORDS = new Set([
  "WITH", "USE", "FORCE", "IGNORE", "PARTITION", "TABLESAMPLE", "INDEXED", "PIVOT", "UNPIVOT",
  "SAMPLE", "SETTINGS",
]);

/** True when `candidate` (at `tokens[idx]`) is a clause/hint keyword rather than an alias. */
function isNonAliasToken(tokens: string[], idx: number): boolean {
  const word = tokens[idx].toUpperCase();
  if (RESERVED_NON_ALIAS.has(word)) return true;
  if (!HINT_WORDS.has(word)) return false;
  const next = tokens[idx + 1];
  const nextUpper = (next || "").toUpperCase();
  switch (word) {
    case "INDEXED":
      return nextUpper === "BY";
    case "SAMPLE":
      return /^[\d(.]/.test(next || "");
    case "SETTINGS":
      return Boolean(next) && next.includes("=");
    case "WITH":
    case "USE":
    case "FORCE":
    case "IGNORE":
    case "PARTITION":
    case "TABLESAMPLE":
    case "PIVOT":
    case "UNPIVOT":
      return (
        (next || "").startsWith("(") ||
        nextUpper === "INDEX" ||
        nextUpper === "KEY" ||
        nextUpper.startsWith("INDEX(") ||
        nextUpper.startsWith("KEY(")
      );
    /* c8 ignore next 2 */
    default:
      return false;
  }
}

/** Splits a table reference into whitespace tokens, keeping quoted identifiers intact. */
function tokenizeTableRef(ref: string): string[] {
  // A token is any run of quoted segments and plain characters, so `[dbo].[users]` stays whole.
  // Hand-scanned so an unterminated quote/bracket cannot trigger a rescan for every start position.
  const tokens: string[] = [];
  let noDoubleCloser = false;
  let noBacktickCloser = false;
  let noBracketCloser = false;
  let i = 0;
  while (i < ref.length) {
    let pos = i;
    while (pos < ref.length) {
      const ch = ref[pos];
      let next = -1;
      if (ch === '"') {
        const close = noDoubleCloser ? -1 : ref.indexOf('"', pos + 1);
        if (close === -1) noDoubleCloser = true;
        else next = close + 1;
      } else if (ch === "`") {
        const close = noBacktickCloser ? -1 : ref.indexOf("`", pos + 1);
        if (close === -1) noBacktickCloser = true;
        else next = close + 1;
      } else if (ch === "[") {
        const close = noBracketCloser ? -1 : ref.indexOf("]", pos + 1);
        if (close === -1) noBracketCloser = true;
        else next = close + 1;
      } else if (ch !== "]" && !isWs(ref.charCodeAt(pos))) {
        next = pos + 1;
      }
      if (next === -1) break;
      pos = next;
    }
    if (pos > i) {
      tokens.push(ref.slice(i, pos));
      i = pos;
    } else {
      i++;
    }
  }
  return tokens;
}

/** Extracts `<table> [AS] [alias]`, ignoring trailing clause keywords and non-identifier tokens. */
function parseTableRef(ref: string): { table: string; alias: string } {
  const tokens = tokenizeTableRef(ref.trim());
  // Only the first item of a comma-joined list matters here; strip list separators.
  const table = cleanIdentifier(stripTrailingCommas(tokens[0] || ""));
  let candidateIdx = tokens[0]?.endsWith(",") ? -1 : 1;
  let explicitAs = false;
  if (candidateIdx >= 0 && tokens[candidateIdx] && tokens[candidateIdx].toUpperCase() === "AS") {
    candidateIdx = 2;
    explicitAs = true;
  }
  let candidate: string | undefined = candidateIdx >= 0 ? tokens[candidateIdx] : undefined;
  if (candidate) candidate = stripTrailingCommas(candidate);
  if (
    !candidate ||
    (explicitAs
      ? RESERVED_NON_ALIAS.has(candidate.toUpperCase())
      : isNonAliasToken(tokens, candidateIdx)) ||
    !/^(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[^\s,()=;"`\[\]]+)$/.test(candidate)
  ) {
    return { table, alias: "" };
  }
  return { table, alias: cleanIdentifier(candidate) };
}

/**
 * Parses raw literal string or number into typed JS value.
 */
function parseLiteralValue(valStr: string): string | number | boolean {
  const trimmed = valStr.trim();
  // String literal 'value'
  if (
    (trimmed.startsWith("'") && trimmed.endsWith("'")) ||
    (trimmed.startsWith('"') && trimmed.endsWith('"'))
  ) {
    return trimmed.slice(1, -1);
  }
  // Boolean
  if (trimmed.toLowerCase() === "true") return true;
  if (trimmed.toLowerCase() === "false") return false;
  // Number
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
    const num = Number(trimmed);
    if (!Number.isNaN(num)) return num;
  }
  return trimmed;
}

/**
 * Finds top-level clause keywords taking string literals and parentheses into account.
 */
interface ClauseToken {
  keyword: string;
  index: number;
  length: number;
}

function findTopLevelClauses(sql: string): ClauseToken[] {
  const tokens: ClauseToken[] = [];
  const upper = sql.toUpperCase();
  let inString = false;
  let stringChar = "";
  let parenDepth = 0;

  const KEYWORDS = [
    "SELECT",
    "FROM",
    "LEFT JOIN",
    "INNER JOIN",
    "RIGHT JOIN",
    "FULL JOIN",
    "CROSS JOIN",
    "JOIN",
    "WHERE",
    "GROUP BY",
    "ORDER BY",
    "LIMIT",
    "OFFSET",
  ];

  for (let i = 0; i < sql.length; i++) {
    const char = sql[i];

    if (inString) {
      if (char === stringChar) {
        if (sql[i + 1] === stringChar) {
          i++; // Escaped quote
        } else {
          inString = false;
        }
      }
      continue;
    }

    if (char === "'" || char === '"' || char === "`") {
      inString = true;
      stringChar = char;
      continue;
    }

    if (char === "(") {
      parenDepth++;
      continue;
    }
    if (char === ")") {
      if (parenDepth > 0) parenDepth--;
      continue;
    }

    if (parenDepth === 0) {
      // Check for keywords
      for (const kw of KEYWORDS) {
        if (upper.startsWith(kw, i)) {
          // Verify word boundary before and after
          const prevChar = i > 0 ? sql[i - 1] : " ";
          const nextChar = i + kw.length < sql.length ? sql[i + kw.length] : " ";
          if (/\s|[(),]/.test(prevChar) && /\s|[(),]/.test(nextChar)) {
            tokens.push({
              keyword: kw,
              index: i,
              length: kw.length,
            });
            i += kw.length - 1;
            break;
          }
        }
      }
    }
  }

  return tokens;
}

/**
 * Splits a clause by a delimiter outside parentheses and quotes.
 */
function splitTopLevel(text: string, delimiterRegex: RegExp): { value: string; delimiter?: string }[] {
  const parts: { value: string; delimiter?: string }[] = [];
  let inString = false;
  let stringChar = "";
  let parenDepth = 0;
  let lastIndex = 0;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (inString) {
      if (char === stringChar) {
        if (text[i + 1] === stringChar) {
          i++;
        } else {
          inString = false;
        }
      }
      continue;
    }

    if (char === "'" || char === '"' || char === "`") {
      inString = true;
      stringChar = char;
      continue;
    }

    if (char === "(") {
      parenDepth++;
      continue;
    }
    if (char === ")") {
      if (parenDepth > 0) parenDepth--;
      continue;
    }

    if (parenDepth === 0) {
      const rest = text.slice(i);
      const match = rest.match(delimiterRegex);
      if (match && match.index === 0) {
        parts.push({
          value: text.slice(lastIndex, i).trim(),
          delimiter: match[0].trim(),
        });
        i += match[0].length - 1;
        lastIndex = i + 1;
      }
    }
  }

  if (lastIndex < text.length) {
    parts.push({
      value: text.slice(lastIndex).trim(),
    });
  }

  return parts;
}

/**
 * Splits WHERE clause conditions by top-level AND/OR outside parens, strings,
 * and BETWEEN ... AND ... constructs.
 */
export function splitWhereConditions(text: string): { value: string; delimiter?: string }[] {
  const parts: { value: string; delimiter?: string }[] = [];
  let inString = false;
  let stringChar = "";
  let parenDepth = 0;
  let lastIndex = 0;
  let inBetween = false;
  let noDelimiterUntil = 0;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (inString) {
      if (char === stringChar) {
        if (text[i + 1] === stringChar) {
          i++;
        } else {
          inString = false;
        }
      }
      continue;
    }

    if (char === "'" || char === '"' || char === "`") {
      inString = true;
      stringChar = char;
      continue;
    }

    if (char === "(") {
      parenDepth++;
      continue;
    }
    if (char === ")") {
      if (parenDepth > 0) parenDepth--;
      continue;
    }

    if (parenDepth === 0) {
      if (!inBetween && matchWordCI(text, i, "BETWEEN") && isWs(text.charCodeAt(i + 7))) {
        inBetween = true;
        i += 7;
        continue;
      }

      // `\s+(AND|OR)\s+` at i. A failed attempt at i fails for the rest of the whitespace run too.
      if (i >= noDelimiterUntil && isWs(text.charCodeAt(i))) {
        const wordAt = skipWs(text, i);
        let delim = "";
        let delimEnd = -1;
        if (matchWordCI(text, wordAt, "AND") && isWs(text.charCodeAt(wordAt + 3))) {
          delim = "AND";
          delimEnd = skipWs(text, wordAt + 3);
        } else if (matchWordCI(text, wordAt, "OR") && isWs(text.charCodeAt(wordAt + 2))) {
          delim = "OR";
          delimEnd = skipWs(text, wordAt + 2);
        } else {
          noDelimiterUntil = wordAt;
        }
        if (delimEnd !== -1) {
          if (inBetween && delim === "AND") {
            inBetween = false;
            i = delimEnd - 1;
            continue;
          }

          parts.push({
            value: text.slice(lastIndex, i).trim(),
            delimiter: delim,
          });
          i = delimEnd - 1;
          lastIndex = i + 1;
          inBetween = false;
        }
      }
    }
  }

  if (lastIndex < text.length) {
    parts.push({
      value: text.slice(lastIndex).trim(),
    });
  }

  return parts.filter((p) => p.value.length > 0);
}

const OPERATOR_PATTERNS = ALLOWED_OPERATORS.map((op) => ({
  op,
  isSymbol: /^[><=!]+$/.test(op),
  words: op.split(" "),
}));

/**
 * Finds top-level operator in a WHERE condition chunk, respecting parentheses and strings.
 */
function findTopLevelOperator(
  condStr: string,
): { op: string; opIndex: number; opLength: number } | null {
  if (/^\s*(NOT\s+)?EXISTS\s*\(/i.test(condStr)) {
    return null;
  }

  let inString = false;
  let stringChar = "";
  let parenDepth = 0;

  for (let i = 0; i < condStr.length; i++) {
    const char = condStr[i];

    if (inString) {
      if (char === stringChar) {
        if (condStr[i + 1] === stringChar) {
          i++;
        } else {
          inString = false;
        }
      }
      continue;
    }

    if (char === "'" || char === '"' || char === "`") {
      inString = true;
      stringChar = char;
      continue;
    }

    if (char === "(") {
      parenDepth++;
      continue;
    }
    if (char === ")") {
      if (parenDepth > 0) parenDepth--;
      continue;
    }

    if (parenDepth === 0) {
      // Operators may be preceded by whitespace; `opStart` is where the operator text would begin.
      const opStart = skipWs(condStr, i);
      for (const { op, isSymbol, words } of OPERATOR_PATTERNS) {
        let matched = false;
        let matchLen = 0;

        if (isSymbol) {
          const after = condStr[opStart + op.length];
          if (condStr.startsWith(op, opStart) && after !== ">" && after !== "<" && after !== "=") {
            matchLen = op.length;
            matched = true;
          }
        } else if (opStart > i) {
          const end = matchWordsCI(condStr, opStart, words);
          if (end !== -1 && (end === condStr.length || isWs(condStr.charCodeAt(end)))) {
            matchLen = end - opStart;
            matched = true;
          }
        }

        if (matched) {
          const actualIndex = opStart;
          const leftPart = condStr.slice(0, actualIndex).trim();
          if (leftPart.length > 0) {
            return {
              op,
              opIndex: actualIndex,
              opLength: matchLen,
            };
          }
        }
      }
      // Every other start inside this whitespace run reaches the same `opStart`, so would fail too.
      if (opStart > i) i = opStart - 1;
    }
  }

  return null;
}

/**
 * Parses raw SQL string to a partial QuerySpec.
 * Returns null if the SQL is not a SELECT query or is invalid.
 */
export function parseSqlToSpec(
  sql: string,
  _schema?: SchemaSnapshot | null,
): QuerySpec | null {
  if (!sql || typeof sql !== "string") return null;

  // Clean SQL comments
  let cleanSql = stripBlockComments(stripLineComments(sql)).trim();

  // Strip trailing semicolons (the SQL is already trimmed, so they are the very last characters)
  let sqlEnd = cleanSql.length;
  while (sqlEnd > 0 && cleanSql.charCodeAt(sqlEnd - 1) === 59) sqlEnd--;
  cleanSql = cleanSql.slice(0, sqlEnd).trim();
  if (!cleanSql) return null;

  // Must begin with SELECT or WITH
  if (!/^(SELECT|WITH)\b/i.test(cleanSql)) {
    return null;
  }

  // Check for disallowed multi-statement or non-SELECT operations
  const disallowRegex = /\b(UNION|INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|DROP\s+|ALTER\s+|TRUNCATE\s+)\b/i;
  if (disallowRegex.test(cleanSql)) {
    return null;
  }

  let ctes: CteSpec[] | undefined = undefined;
  if (/^WITH\b/i.test(cleanSql)) {
    const isRecursive = /^WITH\s+RECURSIVE\b/i.test(cleanSql);
    const withPrefixMatch = cleanSql.match(/^WITH(?:\s+RECURSIVE)?\s+/i);
    const idx = withPrefixMatch ? withPrefixMatch[0].length : 4;

    let parenDepth = 0;
    let inString = false;
    let stringChar = "";
    let mainSelectIndex = -1;

    for (let i = idx; i < cleanSql.length; i++) {
      const ch = cleanSql[i];
      if (inString) {
        if (ch === stringChar) {
          if (cleanSql[i + 1] === stringChar) i++;
          else inString = false;
        }
        continue;
      }
      if (ch === "'" || ch === '"' || ch === "`") {
        inString = true;
        stringChar = ch;
        continue;
      }
      if (ch === "(") {
        parenDepth++;
        continue;
      }
      if (ch === ")") {
        if (parenDepth > 0) parenDepth--;
        continue;
      }
      if (parenDepth === 0) {
        if (/^SELECT\b/i.test(cleanSql.slice(i))) {
          mainSelectIndex = i;
          break;
        }
      }
    }

    if (mainSelectIndex !== -1) {
      const withPart = cleanSql.slice(idx, mainSelectIndex).trim();
      cleanSql = cleanSql.slice(mainSelectIndex).trim();

      const rawCteDefs = splitTopLevel(withPart, /^,/);
      ctes = rawCteDefs.map((def) => {
        const text = def.value.trim();
        const asMatch = text.match(
          /^([a-zA-Z0-9_"`\[\]]+)(?:\s*\(([^\)]+)\))?\s+AS\s*(?:(MATERIALIZED|NOT\s+MATERIALIZED)\s*)?\(([\s\S]*)\)$/i,
        );
        if (asMatch) {
          const name = cleanIdentifier(asMatch[1]);
          const cols = asMatch[2]
            ? asMatch[2].split(",").map((c) => cleanIdentifier(c.trim()))
            : undefined;
          const materialized = asMatch[3] ? !/NOT/i.test(asMatch[3]) : undefined;
          const querySql = asMatch[4].trim();
          return {
            name,
            recursive: isRecursive,
            columns: cols,
            materialized,
            query: { sql: querySql },
          };
        }
        return {
          name: cleanIdentifier(text.split(/\s+/)[0]),
          recursive: isRecursive,
          query: { sql: text },
        };
      });
    } else {
      return null;
    }
  }

  const tokens = findTopLevelClauses(cleanSql);
  if (tokens.length === 0) {
    return null;
  }

  const clauseMap: Record<string, string> = {};
  const joinClauses: { type: string; content: string }[] = [];

  for (let idx = 0; idx < tokens.length; idx++) {
    const curr = tokens[idx];
    const next = tokens[idx + 1];
    const start = curr.index + curr.length;
    const end = next ? next.index : cleanSql.length;
    const content = cleanSql.slice(start, end).trim();

    if (curr.keyword.endsWith("JOIN")) {
      joinClauses.push({
        type: curr.keyword === "JOIN" ? "LEFT JOIN" : curr.keyword,
        content,
      });
    } else {
      clauseMap[curr.keyword] = content;
    }
  }

  // 1. Primary Table (FROM)
  const fromContent = clauseMap["FROM"];
  if (!fromContent) {
    return null;
  }
  const { table: primaryTable, alias: primaryAlias } = parseTableRef(fromContent);
  if (!primaryTable) return null;

  // 2. Projections & DISTINCT (SELECT)
  let selectContent = clauseMap["SELECT"] || "";
  let isDistinct = false;
  if (/^DISTINCT\b/i.test(selectContent)) {
    isDistinct = true;
    selectContent = selectContent.replace(/^DISTINCT\b/i, "").trim();
  }

  const columns: (string | { column: string; agg?: string; alias?: string; raw_expression?: string; time_grain?: string; metric?: string })[] = [];
  let windowFunctions: WindowFunctionSpec[] | undefined = undefined;

  if (selectContent === "*" || selectContent === "") {
    columns.push("*");
  } else {
    const rawCols = splitTopLevel(selectContent, /^,/);
    for (const rawCol of rawCols) {
      const colExpr = rawCol.value.trim();
      if (!colExpr) continue;

      if (colExpr === "*") {
        columns.push("*");
        continue;
      }

      // Check for Window Function: e.g. ROW_NUMBER() OVER (...) [AS alias]
      const wfMatch = colExpr.match(
        /^([a-zA-Z0-9_]+)\s*\((.*?)\)\s+OVER\s*\((.*?)\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
      );
      if (wfMatch) {
        const fnName = wfMatch[1].toUpperCase();
        const argsStr = wfMatch[2].trim();
        const overClause = wfMatch[3].trim();
        const alias = wfMatch[4] ? cleanIdentifier(wfMatch[4]) : `${fnName.toLowerCase()}_wf`;

        let partitionCols: string[] | undefined = undefined;
        let orderSpecs: { column: string; direction?: "ASC" | "DESC" }[] | undefined = undefined;

        const partClause = extractPartitionBy(overClause);
        if (partClause !== undefined) {
          partitionCols = partClause.split(",").map((c) => cleanIdentifier(c.trim()));
        }

        const ordClause = extractOrderBy(overClause);
        if (ordClause !== undefined) {
          orderSpecs = ordClause.split(",").map((o) => {
            const parts = o.trim().split(/\s+/);
            const col = cleanIdentifier(parts[0]);
            const dir = parts[1] && /^DESC$/i.test(parts[1]) ? "DESC" : "ASC";
            return { column: col, direction: dir as "ASC" | "DESC" };
          });
        }

        if (!windowFunctions) windowFunctions = [];
        windowFunctions.push({
          function: fnName,
          arguments: argsStr ? argsStr.split(",").map((a) => cleanIdentifier(a.trim())) : [],
          partition_by: partitionCols,
          order_by: orderSpecs,
          alias,
        });

        columns.push({
          column: alias,
          alias,
        });
        continue;
      }

      // Check for Time Grain Truncation:
      // DATE_TRUNC('month', created_at) [AS alias]
      const dateTruncMatch = colExpr.match(
        /^DATE_TRUNC\s*\(\s*['"]?([a-zA-Z0-9_]+)['"]?\s*,([^\)]+)\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
      );
      if (dateTruncMatch) {
        const grain = dateTruncMatch[1].toLowerCase();
        const innerCol = cleanIdentifier(dateTruncMatch[2]);
        const alias = dateTruncMatch[3] ? cleanIdentifier(dateTruncMatch[3]) : `${innerCol}_${grain}`;
        columns.push({
          column: innerCol,
          time_grain: grain,
          alias,
        });
        continue;
      }

      // DATETRUNC(month, created_at) [AS alias] (MSSQL)
      const datetruncMssqlMatch = colExpr.match(
        /^DATETRUNC\s*\(\s*([a-zA-Z0-9_]+)\s*,([^\)]+)\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
      );
      if (datetruncMssqlMatch) {
        const grain = datetruncMssqlMatch[1].toLowerCase();
        const innerCol = cleanIdentifier(datetruncMssqlMatch[2]);
        const alias = datetruncMssqlMatch[3] ? cleanIdentifier(datetruncMssqlMatch[3]) : `${innerCol}_${grain}`;
        columns.push({
          column: innerCol,
          time_grain: grain,
          alias,
        });
        continue;
      }

      // Check for Aggregate with FILTER clause:
      // SUM(orders.amount) FILTER (WHERE orders.status = 'complete') [AS alias]
      const filterAggMatch = colExpr.match(
        /^(COUNT|SUM|AVG|MIN|MAX)\s*\((?:\s*DISTINCT\s)?([^\)]+)\)\s+FILTER\s*\(\s*WHERE\s([^\)]+)\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
      );
      if (filterAggMatch) {
        const aggName = filterAggMatch[1].toUpperCase();
        const innerCol = cleanIdentifier(filterAggMatch[2]);
        const alias = filterAggMatch[4] ? cleanIdentifier(filterAggMatch[4]) : `${aggName.toLowerCase()}_${innerCol}`;
        columns.push({
          column: innerCol,
          agg: aggName,
          metric: alias,
          alias,
        });
        continue;
      }

      // Check for Aggregate Function: e.g. COUNT(users.id) AS cnt or COUNT(DISTINCT users.id)
      const aggMatch = colExpr.match(
        /^(COUNT|SUM|AVG|MIN|MAX)\s*\((?:\s*DISTINCT\s)?([^\)]+)\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
      );

      if (aggMatch) {
        const aggName = aggMatch[1].toUpperCase();
        const innerCol = cleanIdentifier(aggMatch[2]);
        const alias = aggMatch[3] ? cleanIdentifier(aggMatch[3]) : undefined;
        columns.push({
          column: innerCol,
          agg: aggName,
          alias,
        });
        continue;
      }

      // Check for standard column with optional alias: e.g. users.id AS user_id or users.id
      const colAliasMatch = colExpr.match(
        /^([a-zA-Z0-9_".`\[\]]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
      );

      if (colAliasMatch && !colExpr.includes("(") && !colExpr.includes(")")) {
        const colName = cleanIdentifier(colAliasMatch[1]);
        const alias = colAliasMatch[2] ? cleanIdentifier(colAliasMatch[2]) : undefined;
        if (alias) {
          columns.push({
            column: colName,
            alias,
          });
        } else {
          columns.push(colName);
        }
        continue;
      }

      // Complex Raw Expression: e.g. CASE WHEN ... END AS status_name or a * b AS total
      const asIndex = colExpr.toUpperCase().lastIndexOf(" AS ");
      if (asIndex !== -1) {
        const expr = colExpr.slice(0, asIndex).trim();
        const alias = cleanIdentifier(colExpr.slice(asIndex + 4).trim());
        columns.push({
          column: expr,
          raw_expression: expr,
          alias,
        });
      } else {
        columns.push({
          column: colExpr,
          raw_expression: colExpr,
          alias: cleanIdentifier(colExpr),
        });
      }
    }
  }

  // 3. Joins
  const joins: QuerySpec["joins"] = [];
  const aliasToTable: Record<string, string> = {};
  if (primaryAlias) {
    aliasToTable[primaryAlias] = primaryTable;
  }
  aliasToTable[primaryTable] = primaryTable;

  for (const jc of joinClauses) {
    const onIndex = jc.content.toUpperCase().indexOf(" ON ");
    if (onIndex === -1) continue;
    const tablePart = jc.content.slice(0, onIndex).trim();
    const { table: targetTable, alias: als } = parseTableRef(tablePart);
    aliasToTable[targetTable] = targetTable;
    if (als) aliasToTable[als] = targetTable;
  }

  for (const jc of joinClauses) {
    // Expected format: <tableName> [AS <alias>] ON <left> = <right>
    const onIndex = jc.content.toUpperCase().indexOf(" ON ");
    if (onIndex === -1) continue;

    const tablePart = jc.content.slice(0, onIndex).trim();
    const onPart = jc.content.slice(onIndex + 4).trim();

    const { table: targetTable, alias: targetAlias } = parseTableRef(tablePart);

    // Parse ON: e.g. users.id = orders.user_id or u.id = o.user_id
    const onMatch = matchColumnEquality(onPart);
    let leftTable = primaryTable;
    let leftCol = "id";
    let rightCol = "id";

    if (onMatch) {
      const leftExpr = cleanIdentifier(onMatch[0]);
      const rightExpr = cleanIdentifier(onMatch[1]);

      const lParts = leftExpr.split(".");
      const rParts = rightExpr.split(".");

      const isRightTarget =
        rParts[0] === targetTable || (targetAlias !== "" && rParts[0] === targetAlias);
      const isLeftTarget =
        lParts[0] === targetTable || (targetAlias !== "" && lParts[0] === targetAlias);

      if (isRightTarget && lParts.length > 1) {
        const leftT = aliasToTable[lParts[0]] || lParts[0];
        leftTable = leftT;
        leftCol = lParts[1];
        rightCol = rParts[1];
      } else if (isLeftTarget && rParts.length > 1) {
        const leftT = aliasToTable[rParts[0]] || rParts[0];
        leftTable = leftT;
        leftCol = rParts[1];
        rightCol = lParts[1];
      } else {
        leftCol = lParts[lParts.length - 1];
        rightCol = rParts[rParts.length - 1];
      }
    }

    joins.push({
      table: targetTable,
      type: jc.type,
      left_table: leftTable,
      left_col: leftCol,
      right_col: rightCol,
      on: [{ left: `${leftTable}.${leftCol}`, right: `${targetTable}.${rightCol}` }],
    });
  }

  // 4. Filters (WHERE)
  const filters: QuerySpec["filters"] = [];
  let filterJoin: "AND" | "OR" = "AND";

  const whereContent = clauseMap["WHERE"];
  if (whereContent) {
    const conditionChunks = splitWhereConditions(whereContent);

    for (let cIdx = 0; cIdx < conditionChunks.length; cIdx++) {
      const chunk = conditionChunks[cIdx];
      const condStr = chunk.value.trim();
      const combiner = normalizeCombiner(chunk.delimiter);
      if (combiner === "OR") {
        filterJoin = "OR";
      }
      // A chunk's delimiter follows it, so the operator joining this filter to the previous one
      // is the previous chunk's delimiter.
      const joinWithPrev = cIdx > 0 ? normalizeCombiner(conditionChunks[cIdx - 1].delimiter) : "AND";

      // Match top-level operator
      const foundOp = findTopLevelOperator(condStr);

      if (foundOp) {
        const { op: matchedOp, opIndex, opLength } = foundOp;
        const colStr = cleanIdentifier(condStr.slice(0, opIndex).trim());
        const afterOp = condStr.slice(opIndex + opLength).trim();

        let val: string | number | boolean = "";
        if (matchedOp === "IS NULL" || matchedOp === "IS NOT NULL") {
          val = "";
        } else if (matchedOp === "IN" || matchedOp === "NOT IN") {
          val = afterOp.replace(/^\(|\)$/g, "").trim();
        } else if (matchedOp === "BETWEEN") {
          val = afterOp.trim();
        } else {
          val = parseLiteralValue(afterOp);
        }

        const colParts = colStr.split(".");
        let tablePrefix = primaryTable;
        let colName = colStr;

        if (colParts.length > 1) {
          tablePrefix = colParts[0];
          colName = colParts.slice(1).join(".");
        }

        filters.push({
          column: colName,
          op: matchedOp === "<>" ? "!=" : matchedOp,
          value: val,
          tablePrefix,
          combiner: joinWithPrev,
        });
      } else {
        filters.push({
          column: condStr,
          op: "RAW",
          value: "",
          tablePrefix: primaryTable,
          rawExpression: condStr,
          combiner: joinWithPrev,
        });
      }
    }
  }

  // 5. Order By
  const orderBy: QuerySpec["order_by"] = [];
  const orderContent = clauseMap["ORDER BY"];
  if (orderContent) {
    const sortChunks = splitTopLevel(orderContent, /^,/);
    for (const sc of sortChunks) {
      const parts = sc.value.trim().split(/\s+/);
      const colStr = cleanIdentifier(parts[0]);
      const dir = parts[1] && parts[1].toUpperCase() === "DESC" ? "DESC" : "ASC";

      const colParts = colStr.split(".");
      let tablePrefix = primaryTable;
      let colName = colStr;
      if (colParts.length > 1) {
        tablePrefix = colParts[0];
        colName = colParts.slice(1).join(".");
      }

      orderBy.push({
        column: colName,
        direction: dir,
        tablePrefix,
      });
    }
  }

  // 6. Limit
  let limit = 50;
  const limitContent = clauseMap["LIMIT"];
  if (limitContent) {
    const parsedLimit = parseInt(limitContent, 10);
    if (!Number.isNaN(parsedLimit) && parsedLimit >= 0) {
      limit = parsedLimit;
    }
  }

  // 7. Offset
  let offset: number | undefined = undefined;
  const offsetContent = clauseMap["OFFSET"];
  if (offsetContent) {
    const parsedOffset = parseInt(offsetContent, 10);
    if (!Number.isNaN(parsedOffset) && parsedOffset >= 0) {
      offset = parsedOffset;
    }
  }

  return {
    table: primaryTable,
    columns,
    joins,
    filters,
    filter_join: filterJoin,
    order_by: orderBy,
    distinct: isDistinct,
    limit,
    offset,
    ctes,
    window_functions: windowFunctions,
  };
}
