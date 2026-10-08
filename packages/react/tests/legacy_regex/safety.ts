import type { SqlSafetyValidation } from "../../src/types";

export const MAX_SQL_LENGTH = 100_000;

export const RESTRICTED_KEYWORDS = [
  "DELETE",
  "DROP",
  "UPDATE",
  "INSERT",
  "TRUNCATE",
  "ALTER",
  "GRANT",
  "REVOKE",
  "CREATE",
  "EXECUTE",
  "EXEC",
  "INTO",
  "COPY",
  "VACUUM",
  "REINDEX",
  "CLUSTER",
  "LOCK",
  "CALL",
  "MERGE",
  "DO",
  "ATTACH",
  "DETACH",
  "PRAGMA",
  "SHUTDOWN",
  "KILL",
  "LOAD_FILE",
  "OUTFILE",
  "DUMPFILE",
  "XP_CMDSHELL",
  "SP_EXECUTESQL",
  "OPENROWSET",
  "OPENDATASOURCE",
  "PG_SLEEP",
  "SLEEP",
  "BENCHMARK",
  "WAITFOR",
];

export const RESTRICTED_TABLES = [
  "AUTH_USER",
  "AUTH_GROUP",
  "AUTH_PERMISSION",
  "AUTH_USER_GROUPS",
  "AUTH_USER_USER_PERMISSIONS",
  "AUTHTOKEN_TOKEN",
  "DJANGO_SESSION",
  "DJANGO_ADMIN_LOG",
  "DJANGO_CONTENT_TYPE",
  "DJANGO_MIGRATIONS",
  "PG_SHADOW",
  "PG_AUTHID",
  "PG_USER",
  "PG_DATABASE",
  "PG_TABLES",
  "PG_STAT_ACTIVITY",
  "PG_ROLES",
  "PG_SETTINGS",
  "PG_CONFIG",
  "PG_CLASS",
  "PG_PROC",
  "PG_TYPE",
  "PG_STATISTIC",
  "PG_STAT_STATEMENTS",
  "PASSWORDS",
  "CREDENTIALS",
  "CRM_CONNECTION",
  "CRM_FIELD_MAPPING",
  "DJANGO_CACHE_TABLE",
  "API_AUDITLOG",
  "USER_PROFILE",
  "SQLITE_MASTER",
  "SQLITE_SCHEMA",
  "SQLITE_TEMP_MASTER",
  "SQLITE_TEMP_SCHEMA",
  "SQLITE_SEQUENCE",
  "SQLITE_STAT1",
  "MYSQL.USER",
  "MYSQL.DB",
  "MYSQL.TABLES_PRIV",
  "MYSQL.COLUMNS_PRIV",
  "SYS.OBJECTS",
  "SYS.TABLES",
  "SYS.SCHEMAS",
  "SYS.DATABASE_PRINCIPALS",
  "SYS.SQL_LOGINS",
  "SYS.SYSLOGINS",
  "INFORMATION_SCHEMA.TABLES",
  "INFORMATION_SCHEMA.COLUMNS",
];

export const RESTRICTED_SCHEMAS = [
  "PUBLIC",
  "PG_CATALOG",
  "INFORMATION_SCHEMA",
  "MYSQL",
  "PERFORMANCE_SCHEMA",
  "SYS",
  "MSDB",
  "MASTER",
  "SNOWFLAKE",
];

export function stripSqlCommentsAndStrings(sql: string): string {
  let out = "";
  let i = 0;
  const n = sql.length;
  let inString = false;
  let inDollar = false;
  let dollarTag = "";
  let inBlockComment = 0;
  let inLineComment = false;

  while (i < n) {
    const ch = sql[i];
    const next = i + 1 < n ? sql[i + 1] : "";

    if (inString) {
      if (ch === "'" && next === "'") {
        i += 2;
        continue;
      }
      if (ch === "'") {
        inString = false;
        out += "''";
        i++;
        continue;
      }
      i++;
      continue;
    }

    if (inDollar) {
      if (sql.startsWith(dollarTag, i)) {
        inDollar = false;
        i += dollarTag.length;
        out += "''";
        continue;
      }
      i++;
      continue;
    }

    if (inBlockComment > 0) {
      if (ch === "/" && next === "*") {
        inBlockComment++;
        i += 2;
        continue;
      }
      if (ch === "*" && next === "/") {
        inBlockComment--;
        i += 2;
        if (inBlockComment === 0) out += " ";
        continue;
      }
      i++;
      continue;
    }

    if (inLineComment) {
      if (ch === "\n" || ch === "\r") {
        inLineComment = false;
        out += ch;
      }
      i++;
      continue;
    }

    // Block comments
    if (ch === "/" && next === "*") {
      inBlockComment = 1;
      i += 2;
      continue;
    }

    // Line comments (-- and #)
    if ((ch === "-" && next === "-") || ch === "#") {
      inLineComment = true;
      i += ch === "#" ? 1 : 2;
      continue;
    }

    // Single quote string literals
    if (ch === "'") {
      inString = true;
      i++;
      continue;
    }

    // PostgreSQL dollar-quote strings ($$ or $tag$)
    if (ch === "$") {
      const match = sql.slice(i).match(/^\$[a-zA-Z0-9_]*\$/);
      if (match) {
        inDollar = true;
        dollarTag = match[0];
        i += dollarTag.length;
        continue;
      }
    }

    out += ch;
    i++;
  }

  return out;
}

export function extractCteRootWord(cleanSql: string): string {
  let depth = 0;
  let sawAs = false;
  let lastCteEnd = -1;
  const withMatch = cleanSql.match(/^\s*WITH(?:\s+RECURSIVE)?\b/i);
  if (!withMatch) return "";

  let i = withMatch[0].length;
  while (i < cleanSql.length) {
    const ch = cleanSql[i];
    if (ch === "(") {
      depth++;
    } else if (ch === ")") {
      depth--;
      if (depth === 0 && sawAs) {
        lastCteEnd = i + 1;
        sawAs = false;
        const rest = cleanSql.slice(i + 1).trimStart();
        if (!rest.startsWith(",")) {
          break;
        }
      }
    } else if (depth === 0) {
      const rest = cleanSql.slice(i);
      const asMatch = rest.match(/^\bAS\b/i);
      if (asMatch) {
        sawAs = true;
        i += asMatch[0].length - 1;
      }
    }
    i++;
  }

  if (lastCteEnd > 0) {
    const rootPart = cleanSql.slice(lastCteEnd).trim();
    const wordMatch = rootPart.replace(/^[(),\s]+/, "").match(/^[a-zA-Z_]+/);
    return wordMatch ? wordMatch[0].toUpperCase() : "UNKNOWN";
  }
  return "UNKNOWN";
}

export function validateSqlSafety(
  sql: string,
  allowedSchemas?: string[],
): SqlSafetyValidation {
  const trimmed = (sql || "").trim();
  if (!trimmed) {
    return {
      valid: false,
      isEmpty: true,
      statementType: "NONE",
      isReadOnly: true,
      violations: [],
      injectionRisk: "NONE",
      message: "Ready to validate. Awaiting query input.",
    };
  }

  if (trimmed.length > MAX_SQL_LENGTH) {
    return {
      valid: false,
      isEmpty: false,
      statementType: "NONE",
      isReadOnly: false,
      violations: [
        `Query length (${trimmed.length}) exceeds maximum limit of ${MAX_SQL_LENGTH} characters.`,
      ],
      injectionRisk: "HIGH",
      message: "Query length exceeds maximum allowed limit.",
    };
  }

  if (trimmed.includes("\0")) {
    return {
      valid: false,
      isEmpty: false,
      statementType: "NONE",
      isReadOnly: false,
      violations: ["Null byte detected in query string."],
      injectionRisk: "CRITICAL",
      message: "Null byte injection blocked.",
    };
  }

  const violations: string[] = [];

  if (trimmed.includes("/*!")) {
    violations.push("Forbidden executable comment syntax ('/*!... */') detected.");
  }

  if (/[\uff1b\u037e\u2044]/.test(trimmed)) {
    violations.push("Obfuscated statement separator detected.");
  }

  for (let i = 0; i < trimmed.length; i++) {
    const code = trimmed.charCodeAt(i);
    if (code < 32 && code !== 9 && code !== 10 && code !== 13) {
      violations.push("Disallowed control character detected in query string.");
      break;
    }
  }

  // Lexically strip comments and string literal contents
  const stripped = stripSqlCommentsAndStrings(trimmed);

  const cleanStatements = stripped
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);

  if (cleanStatements.length > 1) {
    violations.push("Multiple statements detected (semicolon query chaining is blocked)");
    return {
      valid: false,
      isEmpty: false,
      statementType: "MULTI_STATEMENT",
      isReadOnly: false,
      violations,
      injectionRisk: "CRITICAL",
      message: "Multiple statements detected. Query chaining is blocked.",
    };
  }

  // Handle parenthesized queries like ((SELECT 1))
  const unwrapped = stripped.replace(/^[()\s]+/, "");
  const firstWordMatch = unwrapped.match(/^[a-zA-Z_]+/i);
  const firstWord = firstWordMatch ? firstWordMatch[0].toUpperCase() : "";

  let stmtType = firstWord || "UNKNOWN";
  const isCte = firstWord === "WITH";
  if (isCte) {
    const cteRoot = extractCteRootWord(stripped);
    if (/\bRECURSIVE\b/i.test(stripped)) {
      violations.push(
        "Recursive Common Table Expressions (WITH RECURSIVE) are not permitted.",
      );
    }
    if (cteRoot !== "SELECT") {
      violations.push(
        `Restricted statement type: ${cteRoot}. Only SELECT queries are permitted.`,
      );
      stmtType = cteRoot;
    } else {
      stmtType = "WITH";
    }
  } else if (firstWord !== "SELECT") {
    violations.push(
      `Restricted statement type: ${firstWord || "UNKNOWN"}. Only SELECT queries are permitted.`,
    );
  }

  for (const kw of RESTRICTED_KEYWORDS) {
    const kwRegex = new RegExp(`\\b${kw}\\b`, "i");
    if (kwRegex.test(stripped)) {
      violations.push(`Forbidden mutation keyword detected: ${kw}`);
    }
  }

  if (/\bSET\b(?!\s+(?:TRANSACTION|LOCAL))/i.test(stripped)) {
    violations.push("Forbidden session modification keyword: SET");
  }

  if (/\bWAITFOR(?:\s+|\/\*.*?\*\/)+DELAY\b/i.test(trimmed)) {
    violations.push("Forbidden time delay pattern detected: WAITFOR DELAY");
  }

  if (/\bINTO\s+(?:OUTFILE|DUMPFILE)\b/i.test(stripped)) {
    violations.push("Forbidden file export pattern detected: INTO OUTFILE/DUMPFILE");
  }

  if (/\bREPLACE\s+INTO\b/i.test(stripped)) {
    violations.push("Forbidden mutation keyword detected: REPLACE INTO");
  }

  for (const tbl of RESTRICTED_TABLES) {
    const tblRegex = new RegExp(`\\b${tbl.replace(".", "\\.")}\\b`, "i");
    if (tblRegex.test(stripped)) {
      violations.push(
        `Access Denied: Table '${tbl.toLowerCase()}' is restricted. Credentials and session data cannot be queried.`,
      );
    }
  }

  // Schema matching anti-evasion (quotes, brackets, backticks, spaces)
  const schemaRegex = /(?:^|[^\w$])(?:["`\[]?)([a-zA-Z0-9_]+)(?:["`\]]?)\s*\.\s*(?:["`\[]?)([a-zA-Z0-9_]+)(?:["`\]]?)/gi;
  let match: RegExpExecArray | null;
  while ((match = schemaRegex.exec(stripped)) !== null) {
    const schemaName = match[1].toUpperCase();
    const tableName = match[2].toUpperCase();
    const fullTable = `${schemaName}.${tableName}`;

    if (RESTRICTED_TABLES.includes(fullTable) || RESTRICTED_TABLES.includes(tableName)) {
      violations.push(
        `Access Denied: Table '${fullTable.toLowerCase()}' is restricted. Credentials and session data cannot be queried.`,
      );
    }

    if (RESTRICTED_SCHEMAS.includes(schemaName)) {
      if (
        allowedSchemas &&
        allowedSchemas.map((s) => s.toUpperCase().replace(/\.$/, "").replace(/["`\[\]]/g, "")).includes(schemaName)
      ) {
        continue;
      }
      violations.push("Access Denied: Queries may only target allowed analytical datasets.");
      break;
    }
  }

  const uniqueViolations = Array.from(new Set(violations));
  const isValid = uniqueViolations.length === 0;

  let injectionRisk: "NONE" | "HIGH" | "CRITICAL" = "NONE";
  if (!isValid) {
    injectionRisk = uniqueViolations.some(
      (v) =>
        v.includes("Forbidden") ||
        v.includes("Multiple") ||
        v.includes("Null byte") ||
        v.includes("separator") ||
        v.includes("Restricted statement type"),
    )
      ? "CRITICAL"
      : "HIGH";
  }

  return {
    valid: isValid,
    isEmpty: false,
    statementType: stmtType,
    isReadOnly: isValid,
    violations: uniqueViolations,
    injectionRisk,
    message: isValid
      ? "Query passes client-side AST validation and read-only policy."
      : uniqueViolations[0],
  };
}
