import { describe, it, expect } from "vitest";
import { validateSqlSafety } from "../src/utils/safety";

describe("validateSqlSafety", () => {
  it("validates empty query as invalid with appropriate message", () => {
    const res = validateSqlSafety("");
    expect(res.valid).toBe(false);
    expect(res.isEmpty).toBe(true);
  });

  it("permits standard SELECT queries", () => {
    const res = validateSqlSafety("SELECT id, name FROM users WHERE id > 10;");
    expect(res.valid).toBe(true);
    expect(res.statementType).toBe("SELECT");
    expect(res.isReadOnly).toBe(true);
  });

  it("permits Common Table Expressions (WITH)", () => {
    const res = validateSqlSafety("WITH summary AS (SELECT id, COUNT(*) FROM orders GROUP BY id) SELECT * FROM summary;");
    expect(res.valid).toBe(true);
    expect(res.statementType).toBe("WITH");
  });

  it("strictly blocks semicolon multi-statement query chaining", () => {
    const res = validateSqlSafety("SELECT * FROM users; DROP TABLE users;");
    expect(res.valid).toBe(false);
    expect(res.statementType).toBe("MULTI_STATEMENT");
    expect(res.injectionRisk).toBe("CRITICAL");
  });

  it("strictly blocks mutation operations like DELETE and UPDATE", () => {
    expect(validateSqlSafety("DELETE FROM users WHERE id = 1;").valid).toBe(false);
    expect(validateSqlSafety("UPDATE users SET name = 'hacked';").valid).toBe(false);
    expect(validateSqlSafety("TRUNCATE users;").valid).toBe(false);
  });

  it("blocks queries targeting sensitive tables", () => {
    const res = validateSqlSafety("SELECT * FROM auth_user;");
    expect(res.valid).toBe(false);
    expect(res.violations.some((v) => v.includes("restricted"))).toBe(true);
  });
});
