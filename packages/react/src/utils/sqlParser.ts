import type { QuerySpec, SchemaSnapshot, VisualJoin, VisualFilter, VisualSort } from "../types";

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

const AGGREGATE_FUNCTIONS = ["COUNT", "SUM", "AVG", "MIN", "MAX"];

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
function splitWhereConditions(text: string): { value: string; delimiter?: string }[] {
  const parts: { value: string; delimiter?: string }[] = [];
  let inString = false;
  let stringChar = "";
  let parenDepth = 0;
  let lastIndex = 0;
  let inBetween = false;

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
      if (!inBetween && /^\bBETWEEN\s+/i.test(rest)) {
        inBetween = true;
        i += 7;
        continue;
      }

      const match = rest.match(/^\s+(AND|OR)\s+/i);
      if (match && match.index === 0) {
        const delim = match[1].toUpperCase();
        if (inBetween && delim === "AND") {
          inBetween = false;
          i += match[0].length - 1;
          continue;
        }

        parts.push({
          value: text.slice(lastIndex, i).trim(),
          delimiter: delim,
        });
        i += match[0].length - 1;
        lastIndex = i + 1;
        inBetween = false;
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

/**
 * Parses raw SQL string to a partial QuerySpec.
 * Returns null if the SQL is not a SELECT query or is invalid.
 */
export function parseSqlToSpec(
  sql: string,
  schema?: SchemaSnapshot | null,
): Partial<QuerySpec> | null {
  if (!sql || typeof sql !== "string") return null;

  // Clean SQL comments
  let cleanSql = sql
    .replace(/--.*$/gm, "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .trim();

  // Strip trailing semicolons
  cleanSql = cleanSql.replace(/;+\s*$/, "").trim();
  if (!cleanSql) return null;

  // Must begin with SELECT
  if (!/^SELECT\b/i.test(cleanSql)) {
    return null;
  }

  // Check for disallowed multi-statement or non-SELECT operations
  const disallowRegex = /\b(UNION|INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|DROP\s+|ALTER\s+|TRUNCATE\s+)\b/i;
  if (disallowRegex.test(cleanSql)) {
    return null;
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
  const fromTokens = fromContent.split(/\s+/);
  const primaryTable = cleanIdentifier(fromTokens[0]);
  if (!primaryTable) return null;

  // 2. Projections & DISTINCT (SELECT)
  let selectContent = clauseMap["SELECT"] || "";
  let isDistinct = false;
  if (/^DISTINCT\b/i.test(selectContent)) {
    isDistinct = true;
    selectContent = selectContent.replace(/^DISTINCT\b/i, "").trim();
  }

  const columns: (string | { column: string; agg?: string; alias?: string })[] = [];
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

      // Check for Aggregate Function: e.g. COUNT(users.id) AS cnt or COUNT(DISTINCT users.id)
      const aggMatch = colExpr.match(
        /^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(?:DISTINCT\s+)?([^\)]+)\s*\)(?:\s+(?:AS\s+)?([a-zA-Z0-9_"`\[\]]+))?$/i,
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

      if (colAliasMatch) {
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
      } else {
        // Fallback for expression
        columns.push(cleanIdentifier(colExpr));
      }
    }
  }

  // 3. Joins
  const joins: QuerySpec["joins"] = [];
  for (const jc of joinClauses) {
    // Expected format: <tableName> [AS <alias>] ON <left> = <right>
    const onIndex = jc.content.toUpperCase().indexOf(" ON ");
    if (onIndex === -1) continue;

    const tablePart = jc.content.slice(0, onIndex).trim();
    const onPart = jc.content.slice(onIndex + 4).trim();

    const targetTableTokens = tablePart.split(/\s+/);
    const targetTable = cleanIdentifier(targetTableTokens[0]);

    // Parse ON: e.g. users.id = orders.user_id
    const onMatch = onPart.match(/([a-zA-Z0-9_".`\[\]]+)\s*=\s*([a-zA-Z0-9_".`\[\]]+)/);
    let leftTable = primaryTable;
    let leftCol = "id";
    let rightCol = "id";

    if (onMatch) {
      const leftExpr = cleanIdentifier(onMatch[1]);
      const rightExpr = cleanIdentifier(onMatch[2]);

      const lParts = leftExpr.split(".");
      const rParts = rightExpr.split(".");

      if (rParts[0] === targetTable && lParts.length > 1) {
        leftTable = lParts[0];
        leftCol = lParts[1];
        rightCol = rParts[1];
      } else if (lParts[0] === targetTable && rParts.length > 1) {
        leftTable = rParts[0];
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
      const combiner = (chunk.delimiter?.toUpperCase() as "AND" | "OR") || "AND";
      if (combiner === "OR") {
        filterJoin = "OR";
      }

      // Match operator
      let matchedOp = "";
      let opIndex = -1;

      for (const op of ALLOWED_OPERATORS) {
        const regex = new RegExp(`\\s+${op}(\\s+|$)`, "i");
        const match = condStr.match(regex);
        if (match && match.index !== undefined) {
          matchedOp = op;
          opIndex = match.index;
          break;
        }
      }

      if (opIndex !== -1 && matchedOp) {
        const colStr = cleanIdentifier(condStr.slice(0, opIndex).trim());
        const afterOp = condStr.slice(opIndex + matchedOp.length + 1).trim();

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

  return {
    table: primaryTable,
    columns,
    joins,
    filters,
    filter_join: filterJoin,
    order_by: orderBy,
    distinct: isDistinct,
    limit,
  };
}
