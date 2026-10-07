import { describe, it, expect } from "vitest";
import { validateSchema } from "../src/utils/schemaUtils";
import type { SchemaSnapshot, DatabaseSchemaDefinition } from "../src/types";

describe("Schema Validator (validateSchema)", () => {
  it("flags null, undefined, or empty schema as SCHEMA_EMPTY", () => {
    const resNull = validateSchema(null);
    expect(resNull.valid).toBe(false);
    expect(resNull.errors).toHaveLength(1);
    expect(resNull.errors[0].code).toBe("SCHEMA_EMPTY");

    const resUndef = validateSchema(undefined);
    expect(resUndef.valid).toBe(false);
    expect(resUndef.errors[0].code).toBe("SCHEMA_EMPTY");
  });

  it("flags schema with no tables as SCHEMA_NO_TABLES", () => {
    const emptySchema: SchemaSnapshot = {
      tables: {},
    };
    const res = validateSchema(emptySchema);
    expect(res.valid).toBe(false);
    expect(res.errors).toHaveLength(1);
    expect(res.errors[0].code).toBe("SCHEMA_NO_TABLES");
  });

  it("flags duplicate columns within a table as DUPLICATE_COLUMN error", () => {
    const schemaWithDuplicates: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "email", data_type: "text", is_nullable: false, is_primary: false },
            { name: "email", data_type: "varchar", is_nullable: true, is_primary: false },
          ],
        },
      },
    };

    const res = validateSchema(schemaWithDuplicates);
    expect(res.valid).toBe(false);
    const dupErr = res.errors.find((e) => e.code === "DUPLICATE_COLUMN");
    expect(dupErr).toBeDefined();
    expect(dupErr?.table).toBe("users");
    expect(dupErr?.column).toBe("email");
    expect(dupErr?.message).toContain('duplicate column "email"');
  });

  it("warns when a column is missing a data type", () => {
    const schemaWithMissingDataType: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "nickname", data_type: "", is_nullable: true, is_primary: false },
          ],
        },
      },
    };

    const res = validateSchema(schemaWithMissingDataType);
    expect(res.valid).toBe(true); // Warnings do not make schema invalid
    const dtWarn = res.warnings.find((w) => w.code === "COLUMN_MISSING_DATA_TYPE");
    expect(dtWarn).toBeDefined();
    expect(dtWarn?.column).toBe("nickname");
  });

  it("reports info diagnostic when a table has no primary key designated", () => {
    const schemaNoPk: SchemaSnapshot = {
      tables: {
        logs: {
          name: "logs",
          columns: [
            { name: "created_at", data_type: "timestamp", is_nullable: false, is_primary: false },
            { name: "message", data_type: "text", is_nullable: false, is_primary: false },
          ],
        },
      },
    };

    const res = validateSchema(schemaNoPk);
    expect(res.valid).toBe(true);
    const pkInfo = res.infos.find((i) => i.code === "TABLE_NO_PRIMARY_KEY");
    expect(pkInfo).toBeDefined();
    expect(pkInfo?.table).toBe("logs");
  });

  it("validates foreign keys and flags broken source table, source column, target table, and target column", () => {
    const brokenFkSchema: SchemaSnapshot = {
      tables: {
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
          ],
        },
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          ],
        },
      },
      foreign_keys: [
        // 1. Missing source table
        { table: "non_existent_table", column: "foo", foreign_table: "users", foreign_column: "id" },
        // 2. Missing source column
        { table: "orders", column: "missing_col", foreign_table: "users", foreign_column: "id" },
        // 3. Missing target table
        { table: "orders", column: "user_id", foreign_table: "missing_target_table", foreign_column: "id" },
        // 4. Missing target column
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "missing_id_col" },
      ],
    };

    const res = validateSchema(brokenFkSchema);
    expect(res.valid).toBe(false);

    expect(res.errors.some((e) => e.code === "FK_SOURCE_TABLE_MISSING")).toBe(true);
    expect(res.errors.some((e) => e.code === "FK_SOURCE_COLUMN_MISSING")).toBe(true);
    expect(res.errors.some((e) => e.code === "FK_TARGET_TABLE_MISSING")).toBe(true);
    expect(res.errors.some((e) => e.code === "FK_TARGET_COLUMN_MISSING")).toBe(true);
  });

  it("passes validation with zero errors and zero warnings for a clean schema snapshot", () => {
    const cleanSchema: SchemaSnapshot = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "email", data_type: "varchar", is_nullable: false, is_primary: false },
          ],
        },
        orders: {
          name: "orders",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "user_id", data_type: "integer", is_nullable: false, is_primary: false },
            { name: "amount", data_type: "numeric", is_nullable: false, is_primary: false },
          ],
        },
      },
      foreign_keys: [
        { table: "orders", column: "user_id", foreign_table: "users", foreign_column: "id" },
      ],
    };

    const res = validateSchema(cleanSchema);
    expect(res.valid).toBe(true);
    expect(res.errors).toHaveLength(0);
    expect(res.warnings).toHaveLength(0);
    expect(res.infos).toHaveLength(0);
  });

  it("normalizes and validates a TableSchema[] format", () => {
    const tableSchemas = [
      {
        name: "customers",
        columns: [
          { name: "id", dataType: "integer", isPrimary: true },
          { name: "company", dataType: "varchar" },
        ],
      },
    ];

    const res = validateSchema(tableSchemas);
    expect(res.valid).toBe(true);
    expect(res.errors).toHaveLength(0);
  });

  it("validates relationships and detects broken target column in relationships", () => {
    const schemaWithRelationships: SchemaSnapshot = {
      tables: {
        posts: {
          name: "posts",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
            { name: "author_id", data_type: "integer", is_nullable: false, is_primary: false },
          ],
        },
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          ],
        },
      },
      relationships: [
        {
          source_table: "posts",
          source_column: "author_id",
          target_table: "users",
          target_column: "non_existent_user_col",
        },
      ],
    };

    const res = validateSchema(schemaWithRelationships);
    expect(res.valid).toBe(false);
    const targetColErr = res.errors.find((e) => e.code === "FK_TARGET_COLUMN_MISSING");
    expect(targetColErr).toBeDefined();
    expect(targetColErr?.table).toBe("users");
    expect(targetColErr?.column).toBe("non_existent_user_col");
  });
});
