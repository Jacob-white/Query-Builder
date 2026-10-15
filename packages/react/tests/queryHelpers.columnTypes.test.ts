import { describe, it, expect } from "vitest";
import type { SchemaSnapshot } from "../src/types";
import {
  aggregatesFor,
  columnKey,
  columnsOf,
  kindLabel,
  typeLabel,
  typeLookup,
} from "../src/utils/queryHelpers/columnTypes";

const col = (name: string, data_type: string) => ({ name, data_type, is_nullable: true, is_primary: false });
const SCHEMA: SchemaSnapshot = {
  tables: {
    account: { name: "account", columns: [col("id", "UUID"), col("balance", "NUMERIC(12, 2)"), col("opened", "DATE")] },
    note: { name: "note", columns: [col("body", "TEXT")] },
  },
};

describe("columnTypes", () => {
  it("names a type the way a person would", () => {
    expect(typeLabel("NUMERIC(26, 8)")).toBe("Number");
    expect(typeLabel("TIMESTAMP")).toBe("Date and time");
    expect(typeLabel("UUID")).toBe("ID");
    expect(typeLabel("BOOLEAN")).toBe("Yes/No");
    expect(kindLabel("json")).toBe("JSON");
    expect(typeLabel("BYTEA")).toBe("Other");
  });

  it("keys a column as table.column and lists the columns of the tables given in order", () => {
    expect(columnKey("account", "id")).toBe("account.id");
    expect(columnsOf(Object.values(SCHEMA.tables)).map((c) => `${c.table}.${c.name}:${c.type}`)).toEqual([
      "account.id:UUID",
      "account.balance:NUMERIC(12, 2)",
      "account.opened:DATE",
      "note.body:TEXT",
    ]);
  });

  it("finds a column's type, or nothing for an unknown table, column or schema", () => {
    const typeOf = typeLookup(SCHEMA);
    expect(typeOf("account", "balance")).toBe("NUMERIC(12, 2)");
    expect(typeOf("account", "nope")).toBeUndefined();
    expect(typeOf("nope", "id")).toBeUndefined();
    expect(typeLookup(null)("account", "id")).toBeUndefined();
    expect(typeLookup(undefined)("account", "id")).toBeUndefined();
  });

  it("offers only the aggregates that make sense for the type, and every one when the type is unknown", () => {
    expect(aggregatesFor("NUMERIC(12, 2)")).toEqual(["COUNT", "SUM", "AVG", "MIN", "MAX"]);
    expect(aggregatesFor("VARCHAR")).toEqual(["COUNT", "MIN", "MAX"]);
    expect(aggregatesFor("DATE")).toEqual(["COUNT", "MIN", "MAX"]);
    expect(aggregatesFor("TIMESTAMP")).toEqual(["COUNT", "MIN", "MAX"]);
    expect(aggregatesFor("UUID")).toEqual(["COUNT"]);
    expect(aggregatesFor("BOOLEAN")).toEqual(["COUNT"]);
    expect(aggregatesFor(undefined)).toEqual(["COUNT", "SUM", "AVG", "MIN", "MAX"]);
  });
});
