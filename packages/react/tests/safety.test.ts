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
});
