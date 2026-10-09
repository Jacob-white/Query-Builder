import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useQueryBuilder,
  type DatabaseSchemaDefinition,
  type SchemaSnapshot,
  type TableDefinition,
  type RelationshipDefinition,
  type ColumnDefinition,
  isSchemaSnapshot,
  normalizeSchema,
} from "../src";
import { invalid } from "./helpers";

// Type-level test schema
interface AppSchema extends DatabaseSchemaDefinition {
  tables: {
    users: {
      columns: {
        id: { dataType: "integer"; primaryKey: true };
        email: { dataType: "string" };
        role: "string";
      };
      relationships: {
        orders: { targetTable: "orders"; targetColumn: "user_id"; sourceColumn: "id" };
      };
    };
    orders: {
      columns: {
        id: { dataType: "integer"; primaryKey: true };
        user_id: { dataType: "integer" };
        total: { dataType: "decimal" };
      };
    };
  };
}

const mockAppSchema: AppSchema = {
  tables: {
    users: {
      columns: {
        id: { dataType: "integer", primaryKey: true },
        email: { dataType: "string" },
        role: "string",
      },
      relationships: {
        orders: { targetTable: "orders", targetColumn: "user_id", sourceColumn: "id" },
      },
    },
    orders: {
      columns: {
        id: { dataType: "integer", primaryKey: true },
        user_id: { dataType: "integer" },
        total: { dataType: "decimal" },
      },
    },
  },
};

const mockSnapshot: SchemaSnapshot = {
  tables: {
    products: {
      name: "products",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "title", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
  },
};

describe("useQueryBuilder<Schema> Generic Inference & Backward Compatibility", () => {
  it("initializes with generic DatabaseSchemaDefinition and provides typed actions", () => {
    const { result } = renderHook(() =>
      useQueryBuilder<AppSchema>({
        schema: mockAppSchema,
        initialTable: "users",
      }),
    );

    expect(result.current.state.primaryTable).toBe("users");
    expect(result.current.state.activeTableNames).toEqual(["users"]);
    expect(result.current.state.activeTables.length).toBe(1);
    expect(result.current.state.activeTables[0].name).toBe("users");

    // Toggle column
    act(() => {
      result.current.actions.toggleColumn("users", "email");
    });
    expect(result.current.state.selectedColumns["users.email"]).toBeDefined();
    expect(result.current.state.orderedProjectionKeys).toContain("users.email");

    // Add another table
    act(() => {
      result.current.actions.addTable("orders");
    });
    expect(result.current.state.activeTableNames).toContain("orders");

    // Add typed join
    act(() => {
      result.current.actions.addJoin({
        id: "j1",
        type: "LEFT JOIN",
        left_table: "users",
        table: "orders",
        left_col: "id",
        right_col: "user_id",
      });
    });
    expect(result.current.state.joins.length).toBe(1);

    // Add typed filter
    act(() => {
      result.current.actions.addFilter({
        id: "f1",
        tablePrefix: "orders",
        column: "total",
        operator: ">",
        value: 100,
      });
    });
    expect(result.current.state.filters.length).toBe(1);

    // Add typed sort
    act(() => {
      result.current.actions.addSort({
        id: "s1",
        tablePrefix: "orders",
        column: "total",
        direction: "DESC",
      });
    });
    expect(result.current.state.sorts.length).toBe(1);

    // Verify compiled SQL has the clauses
    expect(result.current.compiled.sql).toContain("FROM");
    expect(result.current.compiled.sql).toContain('"users"."email"');
    expect(result.current.compiled.sql).toContain("LEFT JOIN");
    expect(result.current.compiled.sql).toContain('"orders"');
    expect(result.current.compiled.sql).toContain("WHERE");
    expect(result.current.compiled.sql).toContain("ORDER BY");
  });

  it("works with backward-compatible untyped invocation and SchemaSnapshot", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        schema: mockSnapshot,
      }),
    );

    expect(result.current.state.primaryTable).toBe("products");
    expect(result.current.state.activeTableNames).toEqual(["products"]);

    act(() => {
      result.current.actions.toggleColumn("products", "title");
    });
    expect(result.current.state.selectedColumns["products.title"]).toBeDefined();

    // Toggle same column off
    act(() => {
      result.current.actions.toggleColumn("products", "title");
    });
    expect(result.current.state.selectedColumns["products.title"]).toBeUndefined();
  });

  it("handles removeTable and cleans up dependent joins, projections, and primaryTable", () => {
    const { result } = renderHook(() =>
      useQueryBuilder<AppSchema>({
        schema: mockAppSchema,
        initialTable: "users",
      }),
    );

    act(() => {
      result.current.actions.addTable("orders");
      result.current.actions.toggleColumn("users", "email");
      result.current.actions.toggleColumn("orders", "total");
      result.current.actions.addJoin({
        id: "j1",
        type: "LEFT JOIN",
        left_table: "users",
        table: "orders",
        left_col: "id",
        right_col: "user_id",
      });
    });

    expect(result.current.state.activeTableNames).toEqual(["users", "orders"]);

    // Remove primary table "users" -> primary falls back to "orders"
    act(() => {
      result.current.actions.removeTable("users");
    });

    expect(result.current.state.primaryTable).toBe("orders");
    expect(result.current.state.activeTableNames).toEqual(["orders"]);
    expect(result.current.state.joins.length).toBe(0);
    expect(result.current.state.selectedColumns["users.email"]).toBeUndefined();
    expect(result.current.state.selectedColumns["orders.total"]).toBeDefined();
  });

  it("supports all actions: update, remove, pagination, reset, markClean, loadSpec, loadTemplate", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        schema: mockSnapshot,
        initialTable: "products",
      }),
    );

    // updateColumnSelect and removeColumnProjection
    act(() => {
      result.current.actions.toggleColumn("products", "title");
    });
    act(() => {
      result.current.actions.updateColumnSelect("products.title", {
        aggregate: "COUNT",
        alias: "total_products",
      });
    });
    expect(result.current.state.selectedColumns["products.title"].aggregate).toBe("COUNT");
    expect(result.current.state.selectedColumns["products.title"].alias).toBe("total_products");

    act(() => {
      result.current.actions.removeColumnProjection("products.title");
    });
    expect(result.current.state.selectedColumns["products.title"]).toBeUndefined();

    // joins update and remove
    act(() => {
      result.current.actions.addJoin({
        id: "j1",
        type: "LEFT JOIN",
        left_col: "id",
        table: "categories",
        right_col: "cat_id",
      });
    });
    act(() => {
      result.current.actions.updateJoin("j1", { type: "INNER JOIN" });
    });
    expect(result.current.state.joins[0].type).toBe("INNER JOIN");
    act(() => {
      result.current.actions.removeJoin("j1");
    });
    expect(result.current.state.joins.length).toBe(0);

    // filters update and remove
    act(() => {
      result.current.actions.addFilter({
        id: "f1",
        column: "price",
        operator: ">",
        value: 50,
      });
    });
    act(() => {
      result.current.actions.updateFilter("f1", { value: 100 });
    });
    expect(result.current.state.filters[0].value).toBe(100);
    act(() => {
      result.current.actions.removeFilter("f1");
    });
    expect(result.current.state.filters.length).toBe(0);

    // sorts update and remove
    act(() => {
      result.current.actions.addSort({
        id: "s1",
        column: "title",
        direction: "ASC",
      });
    });
    act(() => {
      result.current.actions.updateSort("s1", { direction: "DESC" });
    });
    expect(result.current.state.sorts[0].direction).toBe("DESC");
    act(() => {
      result.current.actions.removeSort("s1");
    });
    expect(result.current.state.sorts.length).toBe(0);

    // distinct, limit, dialect, rawSql
    act(() => {
      result.current.actions.setIsDistinct(true);
      result.current.actions.setLimit(25);
      result.current.actions.setDialect("mysql");
      result.current.actions.setRawSql("SELECT 1;");
      result.current.actions.setIsRawMode(true);
    });
    expect(result.current.state.isDistinct).toBe(true);
    expect(result.current.state.limit).toBe(25);
    expect(result.current.state.dialect).toBe("mysql");
    expect(result.current.state.rawSql).toBe("SELECT 1;");
    expect(result.current.state.isRawMode).toBe(true);
    expect(result.current.currentSql).toBe("SELECT 1;");

    // markClean and reset
    expect(result.current.state.isDirty).toBe(true);
    act(() => {
      result.current.actions.markClean();
    });
    expect(result.current.state.isDirty).toBe(false);

    act(() => {
      result.current.actions.reset();
    });
    expect(result.current.state.isDistinct).toBe(false);
    expect(result.current.state.limit).toBe(50);
    expect(result.current.state.isRawMode).toBe(false);

    // loadSpec
    act(() => {
      result.current.actions.loadSpec({
        table: "products",
        columns: ["products.id"],
        distinct: true,
        limit: 10,
        order_by: [{ column: "products.id", direction: "ASC" }],
      });
    });
    expect(result.current.state.primaryTable).toBe("products");
    expect(result.current.state.isDistinct).toBe(true);
    expect(result.current.state.limit).toBe(10);
    expect(result.current.state.sorts.length).toBe(1);

    // loadTemplate with spec
    act(() => {
      result.current.actions.loadTemplate({
        id: "t1",
        title: "Test Template",
        createdAt: "2026-01-01",
        sql: "SELECT 2;",
        spec: {
          primaryTable: "products",
          activeTables: ["products"],
          limit: 5,
        },
      });
    });
    expect(result.current.state.limit).toBe(5);
    expect(result.current.state.isRawMode).toBe(false);

    // loadTemplate with sql only
    act(() => {
      result.current.actions.loadTemplate({
        id: "t2",
        title: "SQL Template",
        createdAt: "2026-01-01",
        sql: "SELECT 3;",
      });
    });
    expect(result.current.state.rawSql).toBe("SELECT 3;");
    expect(result.current.state.isRawMode).toBe(true);
  });

  it("normalizeSchema and isSchemaSnapshot handle all variations and nulls", () => {
    expect(isSchemaSnapshot(null)).toBe(false);
    expect(isSchemaSnapshot({})).toBe(false);
    expect(isSchemaSnapshot({ tables: "invalid" })).toBe(false);
    expect(isSchemaSnapshot(mockSnapshot)).toBe(true);
    expect(isSchemaSnapshot(mockAppSchema)).toBe(false);

    expect(normalizeSchema(null)).toBeNull();
    expect(normalizeSchema(undefined)).toBeNull();
    expect(normalizeSchema(mockSnapshot)).toBe(mockSnapshot);

    const normalized = normalizeSchema(mockAppSchema);
    expect(normalized).not.toBeNull();
    expect(normalized?.tables.users.columns.length).toBe(3);
    expect(normalized?.tables.users.columns[0]).toEqual({
      name: "id",
      data_type: "integer",
      is_nullable: false,
      is_primary: true,
      comment: undefined,
    });
    expect(normalized?.tables.users.columns[2]).toEqual({
      name: "role",
      data_type: "string",
      is_nullable: true,
      is_primary: false,
      comment: undefined,
    });
    expect(normalized?.foreign_keys?.length).toBe(1);
    expect(normalized?.relationships?.length).toBe(1);
    expect(normalized?.foreign_keys?.[0]).toEqual({
      table: "users",
      column: "id",
      foreign_table: "orders",
      foreign_column: "user_id",
    });

    // Empty schema tables
    const emptyNorm = normalizeSchema({ tables: {} });
    expect(emptyNorm?.tables).toEqual({});

    // Table with array columns after empty first table
    const arrayColsSchema = normalizeSchema({
      tables: {
        t0: { columns: {} },
        t1: {
          columns: [{ name: "col_a", data_type: "varchar", is_nullable: true, is_primary: false }],
        },
      },
    });
    expect(arrayColsSchema?.tables.t1.columns[0].name).toBe("col_a");

    // Table with null tableDef
    const nullTableDefSchema = normalizeSchema({
      tables: {
        t_null: invalid<TableDefinition>(null),
      },
    });
    expect(nullTableDefSchema?.tables).toEqual({});

    // Relationships with default sourceColumn and targetColumn ("id")
    const relDefaultSchema = normalizeSchema({
      tables: {
        parent: {
          columns: {
            id: { dataType: "int", primaryKey: true },
          },
          relationships: {
            child_rel: invalid<RelationshipDefinition>({ targetTable: "child" }),
            null_rel: invalid<RelationshipDefinition>(null),
            empty_rel: invalid<RelationshipDefinition>({}),
          },
        },
      },
    });
    expect(relDefaultSchema?.foreign_keys?.[0]).toEqual({
      table: "parent",
      column: "id",
      foreign_table: "child",
      foreign_column: "id",
    });

    // Column definition without dataType (defaults to string)
    const fallbackDataTypeSchema = normalizeSchema({
      tables: {
        items: {
          columns: {
            title: invalid<ColumnDefinition>({ primaryKey: false }),
          },
        },
      },
    });
    expect(fallbackDataTypeSchema?.tables.items.columns[0].data_type).toBe("string");

    // Schema without tables object
    expect(normalizeSchema(invalid<DatabaseSchemaDefinition>({}))).toBeNull();
  });

  it("initializes useQueryBuilder with initialSpec.table when initialTable and primaryTable are omitted", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        schema: mockSnapshot,
        initialSpec: {
          table: "products",
        },
      }),
    );
    expect(result.current.state.primaryTable).toBe("products");
  });
});
