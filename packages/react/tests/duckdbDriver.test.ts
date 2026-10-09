import { describe, it, expect, beforeEach } from "vitest";
import {
  InMemoryOlapEngine,
  getClientOlapEngine,
  resetClientOlapEngine,
} from "../src/drivers/duckdbDriver";

describe("InMemoryOlapEngine & DuckDB Driver", () => {
  let engine: InMemoryOlapEngine;

  beforeEach(() => {
    resetClientOlapEngine();
    engine = new InMemoryOlapEngine();
  });

  describe("CSV and TSV Ingestion", () => {
    it("ingests standard CSV with headers and type inference", async () => {
      const csv = `id,name,age,score,is_active\n1,Alice,30,95.5,true\n2,Bob,25,88.0,false\n3,Charlie,35,92.3,true`;
      const meta = await engine.ingestCsv("users", csv);

      expect(meta.name).toBe("users");
      expect(meta.rowCount).toBe(3);
      expect(meta.sourceType).toBe("csv");
      expect(meta.columns).toEqual([
        { name: "id", type: "INTEGER" },
        { name: "name", type: "VARCHAR" },
        { name: "age", type: "INTEGER" },
        { name: "score", type: "DOUBLE" },
        { name: "is_active", type: "BOOLEAN" },
      ]);

      expect(engine.tables["users"]).toBeDefined();
      expect(engine.activeTable).toBe("users");
    });

    it("ingests tab-separated TSV files", async () => {
      const tsv = `dept\temployees\tsalary\nEngineering\t15\t120000\nMarketing\t8\t85000`;
      const meta = await engine.ingestCsv("departments", tsv);

      expect(meta.sourceType).toBe("tsv");
      expect(meta.rowCount).toBe(2);
      expect(meta.columns).toHaveLength(3);
    });

    it("throws an error on empty CSV content", async () => {
      await expect(engine.ingestCsv("empty", "")).rejects.toThrow(
        "CSV content for table 'empty' is empty.",
      );
    });

    it("handles inferTypes=false flag", async () => {
      const csv = `code,num\nA,123`;
      const meta = await engine.ingestCsv("raw_data", csv, { inferTypes: false });
      expect(meta.columns[1].type).toBe("VARCHAR");
    });
  });

  describe("JSON Ingestion", () => {
    it("ingests JSON records with nested object type detection", async () => {
      const rows = [
        { id: 1, name: "Widget A", price: 19.99, in_stock: true, metadata: { tags: ["tool"] } },
        { id: 2, name: "Widget B", price: 29.99, in_stock: false, metadata: { tags: ["app"] } },
      ];
      const meta = await engine.ingestJson("products", rows);

      expect(meta.name).toBe("products");
      expect(meta.rowCount).toBe(2);
      expect(meta.sourceType).toBe("json");
      expect(meta.columns.find((c) => c.name === "price")?.type).toBe("DOUBLE");
      expect(meta.columns.find((c) => c.name === "in_stock")?.type).toBe("BOOLEAN");
      expect(meta.columns.find((c) => c.name === "metadata")?.type).toBe("JSON");
    });

    it("throws an error when JSON rows are empty or not an array", async () => {
      await expect(engine.ingestJson("invalid", [])).rejects.toThrow(
        "JSON content for table 'invalid' must be a non-empty array of objects.",
      );
    });
  });

  describe("Parquet Ingestion", () => {
    it("validates PAR1 magic bytes and parses mock Parquet file", async () => {
      const validBuffer = new Uint8Array([0x50, 0x41, 0x52, 0x31, 0x00, 0x00]);
      const meta = await engine.ingestParquet("logs", validBuffer);

      expect(meta.name).toBe("logs");
      expect(meta.sourceType).toBe("parquet");
      expect(meta.rowCount).toBe(2);
      expect(meta.columns).toHaveLength(3);
    });

    it("throws an error when Parquet header magic is missing", async () => {
      const invalidBuffer = new Uint8Array([0x00, 0x01, 0x02, 0x03]);
      await expect(engine.ingestParquet("corrupt", invalidBuffer)).rejects.toThrow(
        "Invalid Parquet binary format for table 'corrupt': missing PAR1 header magic.",
      );
    });
  });

  describe("Backend Query Result Caching", () => {
    it("registers backend results into local query cache", async () => {
      const rows = [{ metric: "MRR", value: 50000 }];
      const meta = await engine.registerBackendResults("mrr_cache", rows);

      expect(meta.name).toBe("mrr_cache");
      expect(meta.sourceType).toBe("query_cache");
      expect(meta.rowCount).toBe(1);
    });
  });

  describe("Query Execution", () => {
    beforeEach(async () => {
      const csv = `id,dept,salary,status\n1,Sales,50000,active\n2,Sales,60000,active\n3,Eng,90000,active\n4,Eng,100000,inactive\n5,HR,45000,`;
      await engine.ingestCsv("employees", csv);
    });

    it("executes SHOW TABLES query", async () => {
      const res = await engine.query("SHOW TABLES;");
      expect(res.columns).toEqual(["table_name"]);
      expect(res.rows).toEqual([{ table_name: "employees" }]);
      expect(res.rowCount).toBe(1);
      expect(res.executionTimeMs).toBeGreaterThanOrEqual(0);
    });

    it("throws error when query has no FROM clause", async () => {
      await expect(engine.query("SELECT 1;")).rejects.toThrow("In-Memory OLAP query must contain a valid FROM clause.");
    });

    it("throws error when table is not in catalog", async () => {
      await expect(engine.query("SELECT * FROM non_existent;")).rejects.toThrow(
        "Table 'non_existent' not found in in-memory OLAP catalog.",
      );
    });

    it("executes basic SELECT * FROM table", async () => {
      const res = await engine.query("SELECT * FROM employees;");
      expect(res.columns).toEqual(["id", "dept", "salary", "status"]);
      expect(res.rowCount).toBe(5);
    });

    it("executes projections with aliases", async () => {
      const res = await engine.query("SELECT id, dept AS department FROM employees;");
      expect(res.columns).toEqual(["id", "department"]);
      expect(res.rows[0]).toEqual({ id: 1, department: "Sales" });
    });

    it("evaluates WHERE conditions with various operators", async () => {
      // Equals
      let res = await engine.query("SELECT * FROM employees WHERE dept = 'Sales';");
      expect(res.rowCount).toBe(2);

      // Not equals
      res = await engine.query("SELECT * FROM employees WHERE dept != 'Sales';");
      expect(res.rowCount).toBe(3);

      // Greater than / Greater equal
      res = await engine.query("SELECT * FROM employees WHERE salary >= 90000;");
      expect(res.rowCount).toBe(2);

      // Less than
      res = await engine.query("SELECT * FROM employees WHERE salary < 60000;");
      expect(res.rowCount).toBe(2);

      // Less than or equal
      res = await engine.query("SELECT * FROM employees WHERE salary <= 50000;");
      expect(res.rowCount).toBe(2);

      // IS NULL and IS NOT NULL
      res = await engine.query("SELECT * FROM employees WHERE status IS NULL;");
      expect(res.rowCount).toBe(1);
      expect(res.rows[0].id).toBe(5);

      res = await engine.query("SELECT * FROM employees WHERE status IS NOT NULL;");
      expect(res.rowCount).toBe(4);

      // LIKE / ILIKE
      res = await engine.query("SELECT * FROM employees WHERE dept LIKE 'sa%';");
      expect(res.rowCount).toBe(2);

      res = await engine.query("SELECT * FROM employees WHERE dept ILIKE 'en%';");
      expect(res.rowCount).toBe(2);

      // IN / NOT IN
      res = await engine.query("SELECT * FROM employees WHERE dept IN ('Sales', 'HR');");
      expect(res.rowCount).toBe(3);

      res = await engine.query("SELECT * FROM employees WHERE dept NOT IN ('Sales', 'HR');");
      expect(res.rowCount).toBe(2);

      // BETWEEN
      res = await engine.query("SELECT * FROM employees WHERE salary BETWEEN 55000 AND 95000;");
      expect(res.rowCount).toBe(2);
    });

    it("executes GROUP BY with COUNT, SUM, AVG, MIN, MAX aggregations", async () => {
      const sql = `
        SELECT
          dept,
          COUNT(*) AS emp_count,
          SUM(salary) AS total_sal,
          AVG(salary) AS avg_sal,
          MIN(salary) AS min_sal,
          MAX(salary) AS max_sal
        FROM employees
        GROUP BY dept;
      `;
      const res = await engine.query(sql);

      expect(res.columns).toEqual(["dept", "emp_count", "total_sal", "avg_sal", "min_sal", "max_sal"]);
      expect(res.rowCount).toBe(3);

      const sales = res.rows.find((r) => r.dept === "Sales");
      expect(sales).toMatchObject({
        emp_count: 2,
        total_sal: 110000,
        avg_sal: 55000,
        min_sal: 50000,
        max_sal: 60000,
      });

      const eng = res.rows.find((r) => r.dept === "Eng");
      expect(eng).toMatchObject({
        emp_count: 2,
        total_sal: 190000,
        avg_sal: 95000,
        min_sal: 90000,
        max_sal: 100000,
      });
    });

    it("executes global aggregations without GROUP BY", async () => {
      const res = await engine.query("SELECT COUNT(*) AS total, SUM(salary) AS sum_sal FROM employees;");
      expect(res.rowCount).toBe(1);
      expect(res.rows[0]).toEqual({ total: 5, sum_sal: 345000 });
    });

    it("executes ORDER BY with ASC/DESC and LIMIT/OFFSET", async () => {
      const res = await engine.query("SELECT id, salary FROM employees ORDER BY salary DESC LIMIT 2 OFFSET 1;");
      expect(res.rowCount).toBe(2);
      expect(res.rows[0].id).toBe(3); // 90000
      expect(res.rows[1].id).toBe(2); // 60000
    });
  });

  describe("Catalog Management & Schema Snapshot", () => {
    it("generates SchemaSnapshot compatible with VisualQueryBuilder", async () => {
      await engine.ingestCsv("t1", "id,val\n1,10");
      await engine.ingestCsv("t2", "id,code\n1,ABC");

      const snapshot = engine.getSchemaSnapshot();
      expect(snapshot.tables["t1"]).toBeDefined();
      expect(snapshot.tables["t2"]).toBeDefined();
      expect(snapshot.tables["t1"].columns[0]).toEqual({
        name: "id",
        data_type: "integer",
        is_nullable: true,
        is_primary: true,
      });
      expect(snapshot.categories?.["Client Tables"]).toEqual(["t1", "t2"]);
    });

    it("drops a table and clears the catalog", async () => {
      await engine.ingestCsv("t1", "id\n1");
      await engine.ingestCsv("t2", "id\n2");

      await engine.dropTable("t1");
      expect(engine.tables["t1"]).toBeUndefined();
      expect(engine.activeTable).toBe("t2");

      await engine.clear();
      expect(Object.keys(engine.tables)).toHaveLength(0);
      expect(engine.activeTable).toBeUndefined();
    });

    it("manages singleton getClientOlapEngine and resetClientOlapEngine", () => {
      const e1 = getClientOlapEngine();
      const e2 = getClientOlapEngine();
      expect(e1).toBe(e2);

      resetClientOlapEngine();
      const e3 = getClientOlapEngine();
      expect(e3).not.toBe(e1);
    });
  });
});
