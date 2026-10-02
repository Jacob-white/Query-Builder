import type { SqlSafetyValidation } from "../types";

export function validateSqlSafety(sql: string): SqlSafetyValidation {
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

  const violations: string[] = [];

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

  const restrictedKeywords = [
    "DELETE", "DROP", "UPDATE", "INSERT", "TRUNCATE", "ALTER",
    "GRANT", "REVOKE", "CREATE", "EXECUTE", "INTO", "COPY",
    "VACUUM", "REINDEX", "CLUSTER", "LOCK", "CALL"
  ];

  for (const kw of restrictedKeywords) {
    const kwRegex = new RegExp(`\\b${kw}\\b`, "i");
    if (kwRegex.test(stripped)) {
      violations.push(`Forbidden mutation keyword detected: ${kw}`);
    }
  }

  if (/\bSET\b(?!\s+(?:TRANSACTION|LOCAL))/i.test(stripped)) {
    violations.push("Forbidden session modification keyword: SET");
  }

  const restrictedTables = [
    "AUTH_USER", "AUTH_GROUP", "AUTH_PERMISSION", "AUTHTOKEN_TOKEN",
    "DJANGO_SESSION", "DJANGO_ADMIN_LOG", "PG_SHADOW", "PG_AUTHID", "PG_USER", "PASSWORDS"
  ];

  for (const tbl of restrictedTables) {
    const tblRegex = new RegExp(`\\b${tbl}\\b`, "i");
    if (tblRegex.test(stripped)) {
      violations.push(
        `Access Denied: Table '${tbl.toLowerCase()}' is restricted. Credentials and session data cannot be queried.`,
      );
    }
  }

  const uniqueViolations = Array.from(new Set(violations));
  const isValid = uniqueViolations.length === 0;

  let injectionRisk: "NONE" | "HIGH" | "CRITICAL" = "NONE";
  if (!isValid) {
    injectionRisk = uniqueViolations.some(
      (v) => v.includes("Forbidden") || v.includes("Multiple"),
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
