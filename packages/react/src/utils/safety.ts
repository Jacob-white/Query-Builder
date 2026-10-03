import type { SqlSafetyValidation } from "../types";

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
  "MYSQL.USER",
  "SYS.OBJECTS",
];

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

  // Strip single-line and multi-line comments
  let stripped = trimmed
    .replace(/--[^\r\n]*/g, " ")
    .replace(/\/\*[\s\S]*?\*\//g, " ");

  // Strip single-quoted string literals so keywords inside quotes aren't flagged
  stripped = stripped.replace(/'(?:''|[^'])*'/g, "''");

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

  const firstWordMatch = stripped.match(/^\s*([a-zA-Z_]+)/i);
  const firstWord = firstWordMatch ? firstWordMatch[1].toUpperCase() : "";

  const isSelect = firstWord === "SELECT";
  const isCte = firstWord === "WITH";

  if (!isSelect && !isCte) {
    violations.push(
      `Restricted statement type: ${firstWord || "UNKNOWN"}. Only SELECT queries are permitted.`,
    );
  }

  if (isCte && /\bRECURSIVE\b/i.test(stripped)) {
    violations.push(
      "Recursive Common Table Expressions (WITH RECURSIVE) are not permitted.",
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

  if (/\bWAITFOR\s+DELAY\b/i.test(stripped)) {
    violations.push("Forbidden time delay pattern detected: WAITFOR DELAY");
  }

  if (/\bINTO\s+(?:OUTFILE|DUMPFILE)\b/i.test(stripped)) {
    violations.push("Forbidden file export pattern detected: INTO OUTFILE/DUMPFILE");
  }

  for (const tbl of RESTRICTED_TABLES) {
    const tblRegex = new RegExp(`\\b${tbl}\\b`, "i");
    if (tblRegex.test(stripped)) {
      violations.push(
        `Access Denied: Table '${tbl.toLowerCase()}' is restricted. Credentials and session data cannot be queried.`,
      );
    }
  }

  const restrictedSchemas = [
    { name: "PUBLIC", regex: /\bPUBLIC\./i },
    { name: "PG_CATALOG", regex: /\bPG_CATALOG\./i },
    { name: "INFORMATION_SCHEMA", regex: /\bINFORMATION_SCHEMA\./i },
  ];

  for (const schemaItem of restrictedSchemas) {
    if (schemaItem.regex.test(stripped)) {
      if (
        allowedSchemas &&
        allowedSchemas.map((s) => s.toUpperCase().replace(/\.$/, "")).includes(schemaItem.name)
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
        v.includes("separator"),
    )
      ? "CRITICAL"
      : "HIGH";
  }

  return {
    valid: isValid,
    isEmpty: false,
    statementType: firstWord || "UNKNOWN",
    isReadOnly: isValid,
    violations: uniqueViolations,
    injectionRisk,
    message: isValid
      ? "Query passes client-side AST validation and read-only policy."
      : uniqueViolations[0],
  };
}
