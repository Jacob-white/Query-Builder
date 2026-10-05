import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { parseSqlToSpec, cleanIdentifier } from "../src/utils/sqlParser";
import { findBestJoinCondition, findJoinPath } from "../src/utils/joinUtils";
import { SchemaErdModal } from "../src/components/SchemaErdModal";
import { VisualQueryBuilder } from "../src/components/VisualQueryBuilder";
import type { SchemaSnapshot, DatabaseSchemaDefinition, VisualJoin } from "../src/types";

describe("Milestone 3 Empirical Stress & Adversarial Verification Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // =========================================================================
  // 1. Adversarial SQL Dialect Permutations in parseSqlToSpec()
  // =========================================================================
  describe("1. Adversarial SQL Dialect Permutations in parseSqlToSpec()", () => {
    it("handles arbitrary keyword casing permutations", () => {
      const sqlLower = "select id, name from users where status = 'active' order by id desc limit 25;";
      const specLower = parseSqlToSpec(sqlLower);
      expect(specLower).not.toBeNull();
      expect(specLower?.table).toBe("users");
      expect(specLower?.columns).toEqual(["id", "name"]);
      expect(specLower?.filters).toHaveLength(1);
      expect(specLower?.order_by).toHaveLength(1);
      expect(specLower?.limit).toBe(25);

      const sqlMixed = "sElEcT dIsTiNcT u.id, u.name FrOm users WhErE u.age >= 18 OrDeR bY u.name AsC lImIt 10;";
      const specMixed = parseSqlToSpec(sqlMixed);
      expect(specMixed).not.toBeNull();
      expect(specMixed?.distinct).toBe(true);
      expect(specMixed?.table).toBe("users");
      expect(specMixed?.limit).toBe(10);
    });

    it("handles unusual whitespace, tabs, carriage returns, and comments", () => {
      const sqlMessy = `
        /* multi-line comment with
           keywords: SELECT FROM WHERE */
        SELECT\t\t
          users.id\tAS\tuser_id,
          users.email\r\n,\r
          COUNT(orders.id)\tAS\tcnt\r\n
        FROM\t\t\r\nusers\r\n
        -- trailing line comment
        LEFT JOIN orders ON users.id = orders.user_id\r\n
        WHERE\t\tusers.status\t=\t'active'\r\n
        ORDER BY\tusers.id\tDESC\t\r\n
        LIMIT\t\t50;
      `;
      const spec = parseSqlToSpec(sqlMessy);
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("users");
      expect(spec?.columns).toHaveLength(3);
      expect(spec?.joins).toHaveLength(1);
      expect(spec?.joins[0]).toMatchObject({
        type: "LEFT JOIN",
        table: "orders",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
      });
      expect(spec?.filters).toHaveLength(1);
      expect(spec?.filters[0]).toMatchObject({
        column: "status",
        op: "=",
        value: "active",
      });
      expect(spec?.order_by).toHaveLength(1);
      expect(spec?.limit).toBe(50);
    });

    it("handles every supported operator in WHERE clauses", () => {
      const operatorsToTest: Array<{
        clause: string;
        expectedOp: string;
        expectedVal: string | number | boolean;
      }> = [
        { clause: "users.status = 'active'", expectedOp: "=", expectedVal: "active" },
        { clause: "users.status != 'banned'", expectedOp: "!=", expectedVal: "banned" },
        { clause: "users.status <> 'deleted'", expectedOp: "!=", expectedVal: "deleted" },
        { clause: "users.age < 30", expectedOp: "<", expectedVal: 30 },
        { clause: "users.score > 99.5", expectedOp: ">", expectedVal: 99.5 },
        { clause: "users.age <= 65", expectedOp: "<=", expectedVal: 65 },
        { clause: "users.age >= 21", expectedOp: ">=", expectedVal: 21 },
        { clause: "users.email LIKE '%@example.com'", expectedOp: "LIKE", expectedVal: "%@example.com" },
        { clause: "users.name ILIKE 'alice%'", expectedOp: "ILIKE", expectedVal: "alice%" },
        { clause: "users.role IN ('admin', 'editor')", expectedOp: "IN", expectedVal: "'admin', 'editor'" },
        { clause: "users.status NOT IN ('banned', 'suspended')", expectedOp: "NOT IN", expectedVal: "'banned', 'suspended'" },
        { clause: "users.score BETWEEN 10 AND 50", expectedOp: "BETWEEN", expectedVal: "10 AND 50" },
        { clause: "users.deleted_at IS NULL", expectedOp: "IS NULL", expectedVal: "" },
        { clause: "users.verified_at IS NOT NULL", expectedOp: "IS NOT NULL", expectedVal: "" },
        { clause: "users.tag CONTAINS 'vip'", expectedOp: "CONTAINS", expectedVal: "vip" },
        { clause: "users.code STARTS_WITH 'US-'", expectedOp: "STARTS_WITH", expectedVal: "US-" },
        { clause: "users.code ENDS_WITH '-2026'", expectedOp: "ENDS_WITH", expectedVal: "-2026" },
      ];

      for (const item of operatorsToTest) {
        const sql = `SELECT * FROM users WHERE ${item.clause};`;
        const spec = parseSqlToSpec(sql);
        expect(spec, `Failed to parse clause: ${item.clause}`).not.toBeNull();
        expect(spec?.filters, `Filters empty for: ${item.clause}`).toHaveLength(1);
        expect(spec?.filters[0].op).toBe(item.expectedOp);
        expect(spec?.filters[0].value).toBe(item.expectedVal);
      }
    });

    it("parses complex nested parentheses in WHERE clauses", () => {
      const sqlNested = `
        SELECT * FROM users
        WHERE (users.status = 'active' AND users.age >= 21)
          OR (users.role = 'admin' AND users.is_superuser = true);
      `;
      const spec = parseSqlToSpec(sqlNested);
      expect(spec).not.toBeNull();
      expect(spec?.table).toBe("users");
      expect(spec?.filter_join).toBe("OR");
      expect(spec?.filters.length).toBeGreaterThanOrEqual(1);

      const sqlBetweenWithParens = `
        SELECT * FROM users
        WHERE (age BETWEEN 18 AND 30) AND (status = 'active');
      `;
      const specBetween = parseSqlToSpec(sqlBetweenWithParens);
      expect(specBetween).not.toBeNull();
      expect(specBetween?.table).toBe("users");
      expect(specBetween?.filters.length).toBeGreaterThanOrEqual(1);
    });

    it("parses aggregates with and without aliases, wildcard projections, and qualified column names", () => {
      const sqlAggs = `
        SELECT
          COUNT(*) AS total_count,
          COUNT(DISTINCT users.email) AS unique_emails,
          SUM(orders.amount) AS total_revenue,
          AVG(orders.amount) AS avg_revenue,
          MIN(orders.amount) AS min_amount,
          MAX(orders.amount) AS max_amount,
          users.id,
          [users].[name],
          \`users\`.\`status\`,
          "orders"."created_at" AS order_date
        FROM users
        LEFT JOIN orders ON users.id = orders.user_id;
      `;
      const spec = parseSqlToSpec(sqlAggs);
      expect(spec).not.toBeNull();
      expect(spec?.columns).toHaveLength(10);

      // Verify aggregates
      expect(spec?.columns[0]).toEqual({ column: "*", agg: "COUNT", alias: "total_count" });
      expect(spec?.columns[1]).toEqual({ column: "users.email", agg: "COUNT", alias: "unique_emails" });
      expect(spec?.columns[2]).toEqual({ column: "orders.amount", agg: "SUM", alias: "total_revenue" });
      expect(spec?.columns[3]).toEqual({ column: "orders.amount", agg: "AVG", alias: "avg_revenue" });
      expect(spec?.columns[4]).toEqual({ column: "orders.amount", agg: "MIN", alias: "min_amount" });
      expect(spec?.columns[5]).toEqual({ column: "orders.amount", agg: "MAX", alias: "max_amount" });

      // Verify standard and cleaned qualified columns
      expect(spec?.columns[6]).toBe("users.id");
      expect(spec?.columns[7]).toBe("users.name");
      expect(spec?.columns[8]).toBe("users.status");
      expect(spec?.columns[9]).toEqual({ column: "orders.created_at", alias: "order_date" });
    });

    it("parses multiple joins with various ON predicate formats", () => {
      const sqlMultiJoins = `
        SELECT users.id, orders.id, items.id, categories.id
        FROM users
        LEFT JOIN orders ON users.id = orders.user_id
        INNER JOIN items ON orders.id = items.order_id
        RIGHT JOIN categories ON items.category_id = categories.id
        FULL JOIN logs ON logs.user_id = users.id;
      `;
      const spec = parseSqlToSpec(sqlMultiJoins);
      expect(spec).not.toBeNull();
      expect(spec?.joins).toHaveLength(4);

      expect(spec?.joins[0]).toMatchObject({
        type: "LEFT JOIN",
        table: "orders",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
      });
      expect(spec?.joins[1]).toMatchObject({
        type: "INNER JOIN",
        table: "items",
        left_table: "orders",
        left_col: "id",
        right_col: "order_id",
      });
      expect(spec?.joins[2]).toMatchObject({
        type: "RIGHT JOIN",
        table: "categories",
        left_table: "items",
        left_col: "category_id",
        right_col: "id",
      });
      expect(spec?.joins[3]).toMatchObject({
        type: "FULL JOIN",
        table: "logs",
        left_table: "users",
        left_col: "id",
        right_col: "user_id",
      });
    });

    it("gracefully returns null for malformed, unparsable, or malicious SQL strings without crashing", () => {
      const malformedSqlList = [
        "",
        "   ",
        null as any,
        undefined as any,
        12345 as any,
        { sql: "SELECT * FROM users" } as any,
        "SELECT",
        "SELECT FROM",
        "FROM users",
        "SELECT * FROM",
        "SELECT * FROM ;",
        "SELECT * FROM '';",
        "SELECT * FROM \"\";",
        "INSERT INTO users (id, name) VALUES (1, 'Alice');",
        "UPDATE users SET name = 'Bob' WHERE id = 1;",
        "DELETE FROM users WHERE id = 1;",
        "DROP TABLE users;",
        "ALTER TABLE users ADD COLUMN phone VARCHAR(20);",
        "TRUNCATE TABLE users;",
        "SELECT * FROM users UNION SELECT * FROM orders;",
        "SELECT * FROM users; DROP TABLE users;",
        "RANDOM JIBBERISH <<<>>> !@#$%^&*()",
      ];

      for (const badSql of malformedSqlList) {
        expect(() => {
          const res = parseSqlToSpec(badSql);
          expect(res).toBeNull();
        }, `Expected graceful null for: ${String(badSql)}`).not.toThrow();
      }
    });
  });

  // =========================================================================
  // 2. Bidirectional State Synchronization in VisualQueryBuilder.tsx
  // =========================================================================
  describe("2. Bidirectional State Synchronization in VisualQueryBuilder.tsx", () => {
    const testSchema: DatabaseSchemaDefinition = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "email", data_type: "varchar" },
            { name: "status", data_type: "varchar" },
          ],
        },
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "user_id", data_type: "int" },
            { name: "amount", data_type: "decimal" },
          ],
        },
      },
      foreign_keys: [
        {
          table: "orders",
          column: "user_id",
          foreign_table: "users",
          foreign_column: "id",
        },
      ],
    };

    it("synchronizes visual canvas changes to the compiled SQL string", () => {
      render(
        <VisualQueryBuilder
          schema={testSchema}
          initialTable="users"
        />,
      );

      // Verify initial canvas renders
      expect(screen.getByLabelText("Table users")).toBeDefined();

      // Switch to Raw SQL tab
      const rawSqlTab = screen.getByRole("tab", { name: /Raw SQL/i });
      fireEvent.click(rawSqlTab);

      // Verify the textarea has compiled initial SQL
      const sqlEditor = screen.getByRole("textbox", { name: /Raw SQL code/i }) as HTMLTextAreaElement;
      expect(sqlEditor.value).toContain("SELECT *");
      expect(sqlEditor.value).toMatch(/FROM ["`]?users["`]?/);
      expect(sqlEditor.value).toContain("LIMIT 50");

      // Switch back to Visual tab
      const visualTab = screen.getByRole("tab", { name: /Visual Builder/i });
      fireEvent.click(visualTab);

      // Toggle column selection for email
      const emailCheckbox = screen.getByLabelText("Select column users.email");
      fireEvent.click(emailCheckbox);

      // Switch to Raw SQL tab and verify updated SQL
      fireEvent.click(rawSqlTab);
      const updatedSqlEditor = screen.getByRole("textbox", { name: /Raw SQL code/i }) as HTMLTextAreaElement;
      expect(updatedSqlEditor.value).toContain("users");
      expect(updatedSqlEditor.value).toContain("email");
    });

    it("synchronizes raw SQL edits back into visual canvas state", () => {
      render(
        <VisualQueryBuilder
          schema={testSchema}
          initialTable="users"
        />,
      );

      // Go to Raw SQL tab
      const rawSqlTab = screen.getByRole("tab", { name: /Raw SQL/i });
      fireEvent.click(rawSqlTab);

      const sqlEditor = screen.getByRole("textbox", { name: /Raw SQL code/i }) as HTMLTextAreaElement;

      // Type an updated query with specific columns, WHERE filter, and LIMIT
      act(() => {
        fireEvent.change(sqlEditor, {
          target: {
            value: "SELECT users.id, users.email FROM users WHERE users.status = 'active' ORDER BY users.id DESC LIMIT 15;",
          },
        });
      });

      // Switch back to Visual tab
      const visualTab = screen.getByRole("tab", { name: /Visual Builder/i });
      fireEvent.click(visualTab);

      // Check that visual canvas has adopted the columns and table
      expect(screen.getByLabelText("Table users")).toBeDefined();
      const idCheckbox = screen.getByLabelText("Select column users.id") as HTMLInputElement;
      const emailCheckbox = screen.getByLabelText("Select column users.email") as HTMLInputElement;
      expect(idCheckbox.checked).toBe(true);
      expect(emailCheckbox.checked).toBe(true);
    });

    it("synchronizes state when clicking 'Sync with Visual Canvas' button", () => {
      render(
        <VisualQueryBuilder
          schema={testSchema}
          initialTable="users"
        />,
      );

      // Go to Raw SQL tab
      const rawSqlTab = screen.getByRole("tab", { name: /Raw SQL/i });
      fireEvent.click(rawSqlTab);

      const sqlEditor = screen.getByRole("textbox", { name: /Raw SQL code/i }) as HTMLTextAreaElement;

      act(() => {
        fireEvent.change(sqlEditor, {
          target: {
            value: "SELECT users.id FROM users WHERE users.id = 42 LIMIT 5;",
          },
        });
      });

      // Click "Sync with Visual Canvas" button
      const syncBtn = screen.getByRole("button", { name: /Sync with visual canvas/i });
      act(() => {
        fireEvent.click(syncBtn);
      });

      // Switch to Visual tab
      const visualTab = screen.getByRole("tab", { name: /Visual Builder/i });
      fireEvent.click(visualTab);

      const idCheckbox = screen.getByLabelText("Select column users.id") as HTMLInputElement;
      expect(idCheckbox.checked).toBe(true);
    });

    it("handles unparsable SQL in the SQL editor gracefully without crashing", () => {
      render(
        <VisualQueryBuilder
          schema={testSchema}
          initialTable="users"
        />,
      );

      const rawSqlTab = screen.getByRole("tab", { name: /Raw SQL/i });
      fireEvent.click(rawSqlTab);

      const sqlEditor = screen.getByRole("textbox", { name: /Raw SQL code/i }) as HTMLTextAreaElement;

      act(() => {
        fireEvent.change(sqlEditor, {
          target: {
            value: "SELECT FROM WHERE INVALID;",
          },
        });
      });

      // Custom Raw SQL badge should appear
      expect(screen.getByText("Custom Raw SQL (Visual Canvas Unsynced)")).toBeDefined();

      // Click sync button with unparsable SQL — should not crash
      const syncBtn = screen.getByRole("button", { name: /Sync with visual canvas/i });
      expect(() => {
        act(() => {
          fireEvent.click(syncBtn);
        });
      }).not.toThrow();
    });
  });

  // =========================================================================
  // 3. Foreign Key Bridge Discovery in SchemaErdModal.tsx / joinUtils.ts
  // =========================================================================
  describe("3. Foreign Key Bridge Discovery in SchemaErdModal.tsx / joinUtils.ts", () => {
    const complexGraphSchema: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "email", data_type: "varchar" },
          ],
        },
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "user_id", data_type: "int" },
            { name: "amount", data_type: "decimal" },
          ],
        },
        order_items: {
          name: "order_items",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "order_id", data_type: "int" },
            { name: "product_id", data_type: "int" },
          ],
        },
        products: {
          name: "products",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "category_id", data_type: "int" },
            { name: "name", data_type: "varchar" },
          ],
        },
        categories: {
          name: "categories",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "title", data_type: "varchar" },
          ],
        },
        audit_logs: {
          name: "audit_logs",
          columns: [
            { name: "log_id", data_type: "int", is_primary: true },
            { name: "message", data_type: "varchar" },
          ],
        },
        // 4-node cycle: A -> B -> C -> D -> A
        node_a: {
          name: "node_a",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "b_id", data_type: "int" },
          ],
        },
        node_b: {
          name: "node_b",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "c_id", data_type: "int" },
          ],
        },
        node_c: {
          name: "node_c",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "d_id", data_type: "int" },
          ],
        },
        node_d: {
          name: "node_d",
          columns: [
            { name: "id", data_type: "int", is_primary: true },
            { name: "a_id", data_type: "int" },
          ],
        },
      },
      foreign_keys: [
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
        { table: "order_items", column: "order_id", foreign_table: "orders", foreign_column: "id" },
        { table: "order_items", column: "product_id", foreign_table: "products", foreign_column: "id" },
        { table: "products", column: "category_id", foreign_table: "categories", foreign_column: "id" },
        // Cycles across 4 nodes
        { table: "node_a", column: "b_id", foreign_table: "node_b", foreign_column: "id" },
        { table: "node_b", column: "c_id", foreign_table: "node_c", foreign_column: "id" },
        { table: "node_c", column: "d_id", foreign_table: "node_d", foreign_column: "id" },
        { table: "node_d", column: "a_id", foreign_table: "node_a", foreign_column: "id" },
      ],
    };

    it("handles 0-hop (same table or already active) path requests", () => {
      // Direct joinUtils
      const sameTablePath = findJoinPath(["users"], "users", complexGraphSchema);
      expect(sameTablePath).toHaveLength(0);

      // In SchemaErdModal
      render(
        <SchemaErdModal
          isOpen={true}
          onClose={vi.fn()}
          schema={complexGraphSchema}
        />,
      );

      const srcSelect = screen.getByLabelText("Bridge source table");
      const tgtSelect = screen.getByLabelText("Bridge target table");
      fireEvent.change(srcSelect, { target: { value: "users" } });
      fireEvent.change(tgtSelect, { target: { value: "users" } });

      const findBtn = screen.getByText("Discover Bridge");
      fireEvent.click(findBtn);

      expect(screen.getByText("No bridge path found between selected tables.")).toBeDefined();
    });

    it("discovers 1-hop foreign key bridge path and handles singular hop label", () => {
      // Direct joinUtils: orders -> users
      const oneHop = findJoinPath(["orders"], "users", complexGraphSchema);
      expect(oneHop).toHaveLength(1);
      expect(oneHop[0].table).toBe("users");

      const onAddJoinsMock = vi.fn();
      const onCloseMock = vi.fn();

      render(
        <SchemaErdModal
          isOpen={true}
          onClose={onCloseMock}
          schema={complexGraphSchema}
          onAddJoins={onAddJoinsMock}
        />,
      );

      const srcSelect = screen.getByLabelText("Bridge source table");
      const tgtSelect = screen.getByLabelText("Bridge target table");
      fireEvent.change(srcSelect, { target: { value: "orders" } });
      fireEvent.change(tgtSelect, { target: { value: "users" } });

      fireEvent.click(screen.getByText("Discover Bridge"));

      // Verify singular 'hop' label
      expect(screen.getByText(/Path \(1 hop\):/i)).toBeDefined();

      // Click "Add Bridge Joins to Canvas"
      const addBtn = screen.getByText("Add Bridge Joins to Canvas");
      fireEvent.click(addBtn);

      expect(onAddJoinsMock).toHaveBeenCalled();
      const passedJoins = onAddJoinsMock.mock.calls[0][0] as VisualJoin[];
      expect(passedJoins).toHaveLength(1);
      expect(passedJoins[0]).toMatchObject({
        left_col: "user_id",
        left_table: "orders",
        right_col: "id",
        table: "users",
        type: "LEFT JOIN",
      });
      expect(onCloseMock).toHaveBeenCalled();
    });

    it("discovers 2-hop foreign key bridge path (users -> orders -> order_items)", () => {
      const twoHop = findJoinPath(["users"], "order_items", complexGraphSchema);
      expect(twoHop).toHaveLength(2);
      expect(twoHop[0].table).toBe("orders");
      expect(twoHop[1].table).toBe("order_items");

      render(
        <SchemaErdModal
          isOpen={true}
          onClose={vi.fn()}
          schema={complexGraphSchema}
        />,
      );

      const srcSelect = screen.getByLabelText("Bridge source table");
      const tgtSelect = screen.getByLabelText("Bridge target table");
      fireEvent.change(srcSelect, { target: { value: "users" } });
      fireEvent.change(tgtSelect, { target: { value: "order_items" } });

      fireEvent.click(screen.getByText("Discover Bridge"));

      expect(screen.getByText(/Path \(2 hops\):/i)).toBeDefined();
    });

    it("discovers 3-hop foreign key bridge path (users -> orders -> order_items -> products)", () => {
      const threeHop = findJoinPath(["users"], "products", complexGraphSchema);
      expect(threeHop).toHaveLength(3);
      expect(threeHop[0].table).toBe("orders");
      expect(threeHop[1].table).toBe("order_items");
      expect(threeHop[2].table).toBe("products");

      render(
        <SchemaErdModal
          isOpen={true}
          onClose={vi.fn()}
          schema={complexGraphSchema}
        />,
      );

      const srcSelect = screen.getByLabelText("Bridge source table");
      const tgtSelect = screen.getByLabelText("Bridge target table");
      fireEvent.change(srcSelect, { target: { value: "users" } });
      fireEvent.change(tgtSelect, { target: { value: "products" } });

      fireEvent.click(screen.getByText("Discover Bridge"));

      expect(screen.getByText(/Path \(3 hops\):/i)).toBeDefined();
    });

    it("handles disconnected graphs by reporting no bridge path without false positives", () => {
      // audit_logs has zero connections to users
      const disconnectedCond = findBestJoinCondition("users", "audit_logs", complexGraphSchema);
      expect(disconnectedCond.isFk).toBe(false);

      render(
        <SchemaErdModal
          isOpen={true}
          onClose={vi.fn()}
          schema={complexGraphSchema}
        />,
      );

      const srcSelect = screen.getByLabelText("Bridge source table");
      const tgtSelect = screen.getByLabelText("Bridge target table");
      fireEvent.change(srcSelect, { target: { value: "users" } });
      fireEvent.change(tgtSelect, { target: { value: "audit_logs" } });

      fireEvent.click(screen.getByText("Discover Bridge"));

      expect(screen.getByText("No bridge path found between selected tables.")).toBeDefined();
    });

    it("handles cyclic foreign key graphs without infinite loops and finds shortest path", () => {
      // node_a -> node_b -> node_c -> node_d -> node_a
      // Path from node_a to node_c is 2 hops (via node_b)
      const cyclePath = findJoinPath(["node_a"], "node_c", complexGraphSchema);
      expect(cyclePath).toHaveLength(2);
      expect(cyclePath[0].table).toBe("node_b");
      expect(cyclePath[1].table).toBe("node_c");

      // reverse direction: node_c to node_a is 2 hops (via node_b or node_d)
      const reversePath = findJoinPath(["node_c"], "node_a", complexGraphSchema);
      expect(reversePath).toHaveLength(2);
      expect(reversePath[1].table).toBe("node_a");
    });
  });

  // =========================================================================
  // 4. Focus Trapping in SchemaErdModal.tsx
  // =========================================================================
  describe("4. Focus Trapping in SchemaErdModal.tsx", () => {
    const simpleSchema: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [{ name: "id", data_type: "int", is_primary: true }],
        },
      },
    };

    it("traps focus between first and last focusable elements on Tab and Shift+Tab", () => {
      const onCloseMock = vi.fn();
      render(
        <div>
          <button id="outside-btn">Outside</button>
          <SchemaErdModal
            isOpen={true}
            onClose={onCloseMock}
            schema={simpleSchema}
          />
        </div>,
      );

      const modalDialog = screen.getByRole("dialog");
      const focusableElements = modalDialog.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      expect(focusableElements.length).toBeGreaterThan(1);

      const first = focusableElements[0];
      const last = focusableElements[focusableElements.length - 1];

      // Tab from last element wraps to first element
      last.focus();
      expect(document.activeElement).toBe(last);

      fireEvent.keyDown(window, { key: "Tab", shiftKey: false });
      expect(document.activeElement).toBe(first);

      // Shift+Tab from first element wraps to last element
      first.focus();
      expect(document.activeElement).toBe(first);

      fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
      expect(document.activeElement).toBe(last);
    });

    it("closes modal on Escape key press", () => {
      const onCloseMock = vi.fn();
      render(
        <SchemaErdModal
          isOpen={true}
          onClose={onCloseMock}
          schema={simpleSchema}
        />,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onCloseMock).toHaveBeenCalled();
    });

    it("restores focus to previous active element upon unmounting/closing", () => {
      const outsideButton = document.createElement("button");
      document.body.appendChild(outsideButton);
      outsideButton.focus();
      expect(document.activeElement).toBe(outsideButton);

      const { rerender } = render(
        <SchemaErdModal
          isOpen={true}
          onClose={vi.fn()}
          schema={simpleSchema}
        />,
      );

      // Re-render as closed
      rerender(
        <SchemaErdModal
          isOpen={false}
          onClose={vi.fn()}
          schema={simpleSchema}
        />,
      );

      // Focus should be restored to outside button
      expect(document.activeElement).toBe(outsideButton);
      document.body.removeChild(outsideButton);
    });
  });
});
