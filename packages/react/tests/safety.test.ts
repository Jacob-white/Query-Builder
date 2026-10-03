import { describe, it, expect } from "vitest";
import { validateSqlSafety } from "../src/utils/safety";

describe("validateSqlSafety", () => {
  it("validates empty query as invalid with appropriate message", () => {
    const res = validateSqlSafety("");
    expect(res.valid).toBe(false);
    expect(res.isEmpty).toBe(true);
    expect(res.injectionRisk).toBe("NONE");

    const whitespaceRes = validateSqlSafety("   \n\t  ");
    expect(whitespaceRes.valid).toBe(false);
    expect(whitespaceRes.isEmpty).toBe(true);
  });

  it("permits standard SELECT queries", () => {
    const res = validateSqlSafety("SELECT id, name FROM users WHERE id > 10;");
    expect(res.valid).toBe(true);
    expect(res.statementType).toBe("SELECT");
    expect(res.isReadOnly).toBe(true);
    expect(res.violations).toHaveLength(0);
  });

  it("permits Common Table Expressions (WITH)", () => {
    const res = validateSqlSafety("WITH summary AS (SELECT id, COUNT(*) FROM orders GROUP BY id) SELECT * FROM summary;");
    expect(res.valid).toBe(true);
    expect(res.statementType).toBe("WITH");
  });

  it("permits keywords when embedded inside string literals", () => {
    const res = validateSqlSafety("SELECT id, 'This is not a DELETE operation' AS note FROM logs;");
    expect(res.valid).toBe(true);
  });

  it("strips comments before validation", () => {
    const res = validateSqlSafety(`
      -- Single line comment
      /* Multi-line
         comment */
      SELECT id FROM users;
    `);
    expect(res.valid).toBe(true);
    expect(res.statementType).toBe("SELECT");
  });

  it("strictly blocks semicolon multi-statement query chaining", () => {
    const res = validateSqlSafety("SELECT * FROM users; DROP TABLE users;");
    expect(res.valid).toBe(false);
    expect(res.statementType).toBe("MULTI_STATEMENT");
    expect(res.injectionRisk).toBe("CRITICAL");
  });

  it("strictly blocks mutation operations like DELETE, UPDATE, TRUNCATE, INSERT, ALTER", () => {
    expect(validateSqlSafety("DELETE FROM users WHERE id = 1;").valid).toBe(false);
    expect(validateSqlSafety("UPDATE users SET name = 'hacked';").valid).toBe(false);
    expect(validateSqlSafety("TRUNCATE users;").valid).toBe(false);
    expect(validateSqlSafety("INSERT INTO users (id) VALUES (1);").valid).toBe(false);
    expect(validateSqlSafety("ALTER TABLE users ADD COLUMN hack TEXT;").valid).toBe(false);
  });

  it("blocks SET session modification statements", () => {
    const res = validateSqlSafety("SET statement_timeout = 0;");
    expect(res.valid).toBe(false);
    expect(res.violations.some((v) => v.includes("SET"))).toBe(true);
  });

  it("blocks queries targeting sensitive tables", () => {
    const resAuth = validateSqlSafety("SELECT * FROM auth_user;");
    expect(resAuth.valid).toBe(false);
    expect(resAuth.violations.some((v) => v.includes("auth_user"))).toBe(true);

    const resShadow = validateSqlSafety("SELECT * FROM pg_shadow;");
    expect(resShadow.valid).toBe(false);
    expect(resShadow.violations.some((v) => v.includes("pg_shadow"))).toBe(true);

    const resSession = validateSqlSafety("SELECT * FROM django_session;");
    expect(resSession.valid).toBe(false);
    expect(resSession.violations.some((v) => v.includes("django_session"))).toBe(true);
  });

  it("identifies unknown/restricted non-SELECT starting keywords", () => {
    const res = validateSqlSafety("EXPLAIN ANALYZE SELECT 1;");
    expect(res.valid).toBe(false);
    expect(res.statementType).toBe("EXPLAIN");
  });

  it("blocks queries exceeding maximum length", () => {
    const res = validateSqlSafety("SELECT " + "a".repeat(100_001));
    expect(res.valid).toBe(false);
    expect(res.violations[0]).toContain("exceeds maximum limit");
    expect(res.injectionRisk).toBe("HIGH");
  });

  it("blocks null byte injection", () => {
    const res = validateSqlSafety("SELECT 1\0; DROP TABLE users;");
    expect(res.valid).toBe(false);
    expect(res.violations[0]).toContain("Null byte detected");
    expect(res.injectionRisk).toBe("CRITICAL");
  });

  it("blocks executable comment syntax (/*!... */)", () => {
    const res = validateSqlSafety("SELECT 1 /*!50000 , (SELECT * FROM users) */");
    expect(res.valid).toBe(false);
    expect(res.violations.some((v) => v.includes("executable comment syntax"))).toBe(true);
    expect(res.injectionRisk).toBe("CRITICAL");
  });

  it("blocks obfuscated statement separators", () => {
    const res = validateSqlSafety("SELECT 1\uff1bDROP TABLE users;");
    expect(res.valid).toBe(false);
    expect(res.violations.some((v) => v.includes("separator"))).toBe(true);
  });

  it("blocks disallowed control characters", () => {
    const res = validateSqlSafety("SELECT 1 \x07 FROM users;");
    expect(res.valid).toBe(false);
    expect(res.violations.some((v) => v.includes("control character"))).toBe(true);
  });

  it("blocks recursive CTEs to prevent DoS", () => {
    const res = validateSqlSafety(
      "WITH RECURSIVE bomb AS (SELECT 1 UNION ALL SELECT n+1 FROM bomb) SELECT * FROM bomb;",
    );
    expect(res.valid).toBe(false);
    expect(res.violations.some((v) => v.includes("WITH RECURSIVE"))).toBe(true);
  });

  it("blocks WAITFOR DELAY and INTO OUTFILE", () => {
    const resWait = validateSqlSafety("SELECT 1 WAITFOR DELAY '00:00:05';");
    expect(resWait.valid).toBe(false);
    expect(resWait.violations.some((v) => v.includes("WAITFOR DELAY"))).toBe(true);

    const resOut = validateSqlSafety("SELECT * INTO OUTFILE '/tmp/dump' FROM users;");
    expect(resOut.valid).toBe(false);
    expect(resOut.violations.some((v) => v.includes("INTO OUTFILE"))).toBe(true);
  });

  it("enforces schema restrictions and respects allowedSchemas exception", () => {
    const resPublic = validateSqlSafety("SELECT * FROM public.orders;");
    expect(resPublic.valid).toBe(false);
    expect(resPublic.violations.some((v) => v.includes("allowed analytical datasets"))).toBe(true);

    const resAllowed = validateSqlSafety("SELECT * FROM public.orders;", ["public"]);
    expect(resAllowed.valid).toBe(true);

    const resMixed = validateSqlSafety(
      "SELECT * FROM public.orders JOIN pg_catalog.pg_shadow ON 1=1;",
      ["public"],
    );
    expect(resMixed.valid).toBe(false);
    expect(resMixed.violations.some((v) => v.includes("allowed analytical datasets"))).toBe(true);
  });

  it("handles CTEs with non-SELECT root operations and parenthesized queries", () => {
    const resDo = validateSqlSafety("WITH t AS (SELECT 1) DO $$ BEGIN NULL; END $$;");
    expect(resDo.valid).toBe(false);
    expect(resDo.statementType).toBe("DO");

    const resDel = validateSqlSafety("WITH t AS (SELECT 1) DELETE FROM users;");
    expect(resDel.valid).toBe(false);
    expect(resDel.statementType).toBe("DELETE");

    const resReplace = validateSqlSafety("REPLACE INTO users (id) VALUES (1);");
    expect(resReplace.valid).toBe(false);
    expect(resReplace.violations.some((v) => v.includes("REPLACE INTO"))).toBe(true);

    const resParenSel = validateSqlSafety("((SELECT 1));");
    expect(resParenSel.valid).toBe(true);
    expect(resParenSel.statementType).toBe("SELECT");

    const resParenDel = validateSqlSafety("((DELETE FROM users));");
    expect(resParenDel.valid).toBe(false);

    const resWaitComment = validateSqlSafety("SELECT 1; WAITFOR/**/DELAY '00:00:05';");
    expect(resWaitComment.valid).toBe(false);

    expect(validateSqlSafety("SELECT * FROM [sys].[objects];").valid).toBe(false);
    expect(validateSqlSafety("SELECT * FROM `mysql`.`user`;").valid).toBe(false);
    expect(validateSqlSafety("SELECT * FROM pg_catalog . pg_class;").valid).toBe(false);
    expect(validateSqlSafety("SELECT * FROM mysql.user;").valid).toBe(false);

    expect(validateSqlSafety("/* outer /* inner */ */ SELECT 1;").valid).toBe(true);
    expect(validateSqlSafety("# MySQL comment\nSELECT 1;").valid).toBe(true);
    expect(validateSqlSafety("-- Line comment\r\nSELECT 1;").valid).toBe(true);
    expect(validateSqlSafety("SELECT $$dollar string$$ AS val;").valid).toBe(true);
    expect(validateSqlSafety("SELECT $tag$dollar tag$tag$ AS val;").valid).toBe(true);
    expect(validateSqlSafety("SELECT 'O''Reilly' AS author;").valid).toBe(true);
    expect(validateSqlSafety("WITH malformed_cte").valid).toBe(false);
  });
});
