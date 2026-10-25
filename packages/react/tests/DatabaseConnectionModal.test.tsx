import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import {
  DatabaseConnectionModal,
  parseDatabaseUri,
  VisualQueryBuilder,
  darkTheme,
  type DatabaseConnectionInfo,
} from "../src";

const MOCK_DATABASES: DatabaseConnectionInfo[] = [
  {
    id: "starter_pg",
    name: "Analytics Production",
    group: "PostgreSQL",
    dialect: "postgres",
    description: "Core application database",
    icon: "🐘",
    available: true,
    is_custom: false,
    table_count: 52,
  },
  {
    id: "custom_sales",
    name: "Custom Sales SQLite",
    group: "Custom Connections",
    dialect: "sqlite",
    description: "Uploaded sales dataset",
    available: true,
    is_custom: true,
    table_count: 4,
  },
  {
    id: "offline_pg",
    name: "Offline Warehouse",
    group: "PostgreSQL",
    dialect: "postgres",
    available: false,
    is_custom: false,
  },
];

describe("parseDatabaseUri", () => {
  it("parses postgresql:// and postgres:// URIs with credentials, port, database, and schema", () => {
    const parsed = parseDatabaseUri(
      "postgresql://alice:secret123@db.example.com:5433/analytics?schema=reporting&sslmode=require",
    );
    expect(parsed).toEqual({
      dialect: "postgres",
      host: "db.example.com",
      port: 5433,
      database: "analytics",
      user: "alice",
      password: "secret123",
      schema_name: "reporting",
      sslmode: "require",
    });

    const parsedDefault = parseDatabaseUri("postgres://localhost/mydb");
    expect(parsedDefault?.dialect).toBe("postgres");
    expect(parsedDefault?.port).toBe(5432);
    expect(parsedDefault?.database).toBe("mydb");
    expect(parsedDefault?.schema_name).toBe("public");
    expect(parsedDefault?.user).toBeUndefined();
  });

  it("parses mysql:// and mariadb:// URIs", () => {
    const parsed = parseDatabaseUri("mysql://root:pw@127.0.0.1:3307/shop_db");
    expect(parsed).toEqual({
      dialect: "mysql",
      host: "127.0.0.1",
      port: 3307,
      database: "shop_db",
      user: "root",
      password: "pw",
      schema_name: undefined,
      sslmode: undefined,
    });

    const mariaDefault = parseDatabaseUri("mariadb://localhost/catalog");
    expect(mariaDefault?.dialect).toBe("mysql");
    expect(mariaDefault?.port).toBe(3306);
  });

  it("parses sqlite:/// and duckdb:/// URIs including Windows drive letters, UNC paths, and query params", () => {
    const sq = parseDatabaseUri("sqlite:////var/data/app.db");
    expect(sq?.dialect).toBe("sqlite");
    expect(sq?.file_path).toBe("/var/data/app.db");
    expect(sq?.database).toBe("app.db");

    const sqWin4 = parseDatabaseUri("sqlite:////C:\\Users\\demo\\crm.sqlite");
    expect(sqWin4?.file_path).toBe("C:\\Users\\demo\\crm.sqlite");
    expect(sqWin4?.database).toBe("crm.sqlite");

    const sqWinQuery = parseDatabaseUri("sqlite:///C:/Users/demo/crm.sqlite?mode=ro");
    expect(sqWinQuery?.file_path).toBe("C:/Users/demo/crm.sqlite");
    expect(sqWinQuery?.database).toBe("crm.sqlite");

    const sqUnc = parseDatabaseUri("sqlite:////\\\\server\\share\\crm.sqlite");
    expect(sqUnc?.file_path).toBe("\\\\server\\share\\crm.sqlite");
    expect(sqUnc?.database).toBe("crm.sqlite");

    const sqEmpty = parseDatabaseUri("sqlite:///");
    expect(sqEmpty?.file_path).toBe(":memory:");

    const dk = parseDatabaseUri("duckdb:///tmp/olap.duckdb?access_mode=read_only");
    expect(dk?.dialect).toBe("duckdb");
    expect(dk?.file_path).toBe("tmp/olap.duckdb");
    expect(dk?.database).toBe("olap.duckdb");

    const dkWin = parseDatabaseUri("duckdb:////C:\\Users\\demo\\wh.duckdb");
    expect(dkWin?.file_path).toBe("C:\\Users\\demo\\wh.duckdb");
    expect(dkWin?.database).toBe("wh.duckdb");

    const dkEmpty = parseDatabaseUri("duckdb:///");
    expect(dkEmpty?.file_path).toBe(":memory:");
  });

  it("returns null for empty, unsupported, or malformed URIs", () => {
    expect(parseDatabaseUri("")).toBeNull();
    expect(parseDatabaseUri("   ")).toBeNull();
    expect(parseDatabaseUri("http://example.com")).toBeNull();
    expect(parseDatabaseUri("postgresql://[::1:bad")).toBeNull();
  });
});

describe("DatabaseConnectionModal", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(
      <DatabaseConnectionModal isOpen={false} onClose={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders engine options, validates fields, edits inputs, tests connection, and connects a PostgreSQL database", async () => {
    const onTestConnection = vi.fn().mockResolvedValue({
      ok: true,
      status: "connected",
      dialect: "postgres",
      latency_ms: 6.2,
      table_count: 12,
      foreign_key_count: 8,
      sample_tables: ["users", "orders"],
      message: "Connected! Found 12 tables (6.2 ms)",
    });
    const onConnectDatabase = vi.fn().mockResolvedValue({
      database: {
        id: "custom_analytics",
        name: "Analytics DB",
        dialect: "postgres",
        is_custom: true,
        table_count: 12,
      },
      schema: { tables: { users: { name: "users", columns: [] } }, foreign_keys: [] },
    });
    const onDatabaseConnected = vi.fn();
    const onClose = vi.fn();

    render(
      <DatabaseConnectionModal
        isOpen={true}
        onClose={onClose}
        databases={MOCK_DATABASES}
        activeDatabaseId="starter_pg"
        onTestConnection={onTestConnection}
        onConnectDatabase={onConnectDatabase}
        onDatabaseConnected={onDatabaseConnected}
        theme="light"
      />,
    );

    // Click Test Connection and Connect Database before entering database name -> shows validation error
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain(
      "Please enter the database name",
    );
    fireEvent.click(screen.getByTestId("btn-save-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain(
      "Please enter the database name",
    );

    // Type invalid URI into quick URI autofill and click Auto-Fill
    fireEvent.change(screen.getByTestId("input-db-uri-autofill"), {
      target: { value: "invalid-uri" },
    });
    fireEvent.click(screen.getByTestId("btn-parse-uri"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain(
      "Could not parse connection URL",
    );

    // Paste a quick connection URI to auto-fill Postgres fields
    fireEvent.change(screen.getByTestId("input-db-uri-autofill"), {
      target: { value: "postgresql://analyst:pass99@pg.internal:5435/warehouse?schema=bi" },
    });

    expect((screen.getByTestId("input-db-host") as HTMLInputElement).value).toBe("pg.internal");
    expect((screen.getByTestId("input-db-port") as HTMLInputElement).value).toBe("5435");
    expect((screen.getByTestId("input-db-database") as HTMLInputElement).value).toBe("warehouse");
    expect((screen.getByTestId("input-db-schema") as HTMLInputElement).value).toBe("bi");
    expect((screen.getByTestId("input-db-user") as HTMLInputElement).value).toBe("analyst");

    // Directly edit fields as well
    fireEvent.change(screen.getByTestId("input-db-name"), { target: { value: "Analytics DB" } });
    fireEvent.change(screen.getByTestId("input-db-host"), { target: { value: "pg2.internal" } });
    fireEvent.change(screen.getByTestId("input-db-port"), { target: { value: "5436" } });
    fireEvent.change(screen.getByTestId("input-db-schema"), { target: { value: "core" } });
    fireEvent.change(screen.getByTestId("input-db-user"), { target: { value: "admin" } });
    fireEvent.change(screen.getByTestId("input-db-password"), { target: { value: "pw123" } });

    // Test Connection
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(onTestConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Analytics DB",
          dialect: "postgres",
          host: "pg2.internal",
          port: 5436,
          database: "warehouse",
          user: "admin",
          password: "pw123",
          schema_name: "core",
        }),
      );
      expect(screen.getByTestId("db-connection-success").textContent).toContain(
        "Connected! Found 12 tables",
      );
    });

    // Save & Connect
    fireEvent.click(screen.getByTestId("btn-save-db-connection"));
    await waitFor(() => {
      expect(onConnectDatabase).toHaveBeenCalled();
      expect(onDatabaseConnected).toHaveBeenCalledWith(
        expect.objectContaining({ id: "custom_analytics" }),
        expect.any(Object),
      );
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("supports SQLite, DuckDB, MySQL, and Connection URL modes", async () => {
    const onTestConnection = vi.fn().mockResolvedValue({
      ok: true,
      status: "connected",
      dialect: "sqlite",
      table_count: 5,
      foreign_key_count: 2,
    });

    render(
      <DatabaseConnectionModal
        isOpen={true}
        onClose={vi.fn()}
        onTestConnection={onTestConnection}
        theme="dark"
      />,
    );

    // Quick-URI auto-fill with sqlite:/// switches to sqlite mode
    fireEvent.change(screen.getByTestId("input-db-uri-autofill"), {
      target: { value: "sqlite:///tmp/quick.db" },
    });
    expect((screen.getByTestId("input-db-filepath") as HTMLInputElement).value).toBe("tmp/quick.db");

    // Switch to MySQL -> port updates to 3306, auto-fill mysql://localhost/shop, and test connection
    fireEvent.click(screen.getByTestId("engine-option-mysql"));
    expect((screen.getByTestId("input-db-port") as HTMLInputElement).value).toBe("3306");
    fireEvent.change(screen.getByTestId("input-db-uri-autofill"), {
      target: { value: "mysql://localhost/shop" },
    });
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(onTestConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          dialect: "mysql",
          database: "shop",
          schema_name: "shop",
        }),
      );
    });
    fireEvent.keyDown(window, { key: "Enter" });

    // Switch back to PostgreSQL -> port updates to 5432
    fireEvent.click(screen.getByTestId("engine-option-postgres"));
    expect((screen.getByTestId("input-db-port") as HTMLInputElement).value).toBe("5432");

    // Switch to SQLite -> clear path, validate empty path error, then enter path
    fireEvent.click(screen.getByTestId("engine-option-sqlite"));
    fireEvent.change(screen.getByTestId("input-db-filepath"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain("SQLite");

    fireEvent.change(screen.getByTestId("input-db-filepath"), {
      target: { value: "/tmp/test.sqlite" },
    });
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(onTestConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          dialect: "sqlite",
          file_path: "/tmp/test.sqlite",
        }),
      );
    });

    // Switch to DuckDB, validate empty error, click Use :memory:, then click upload shortcut
    fireEvent.click(screen.getByTestId("engine-option-duckdb"));
    fireEvent.change(screen.getByTestId("input-db-filepath"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain("DuckDB");

    fireEvent.click(screen.getByText("Use :memory:"));
    expect((screen.getByTestId("input-db-filepath") as HTMLInputElement).value).toBe(":memory:");
    fireEvent.click(screen.getByText(/Or upload a file from your computer/i));
    expect(screen.getByTestId("db-upload-dropzone")).toBeTruthy();

    expect(
      screen.getByTestId("database-connection-modal").style.getPropertyValue("--qb-color-confirmed-text"),
    ).toBe("#6ee7b7");

    // Switch to URI tab, test empty and invalid URI validation, then verify live parsed preview and test connection
    fireEvent.click(screen.getByTestId("engine-option-uri"));
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain(
      "Please paste a database connection URL",
    );

    fireEvent.change(screen.getByTestId("input-db-uri"), {
      target: { value: "invalid://not-a-db" },
    });
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain(
      "Could not parse connection URL",
    );

    fireEvent.change(screen.getByTestId("input-db-uri"), {
      target: { value: "postgresql://u:p@db.host:5432/prod_db" },
    });
    expect(screen.getByTestId("uri-parsed-preview").textContent).toContain("prod_db");
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(onTestConnection).toHaveBeenCalledWith(
        expect.objectContaining({
          connection_uri: "postgresql://u:p@db.host:5432/prod_db",
          database: "prod_db",
        }),
      );
    });
  });

  it("supports file upload drag-and-drop and manage/disconnect tab with group filters", async () => {
    const onSelectDatabase = vi.fn();
    const onDisconnectDatabase = vi.fn().mockResolvedValue(undefined);
    const onDatabaseDisconnected = vi.fn();
    const onClose = vi.fn();

    render(
      <DatabaseConnectionModal
        isOpen={true}
        onClose={onClose}
        databases={MOCK_DATABASES}
        activeDatabaseId="starter_pg"
        onSelectDatabase={onSelectDatabase}
        onDisconnectDatabase={onDisconnectDatabase}
        onDatabaseDisconnected={onDatabaseDisconnected}
        theme={darkTheme}
      />,
    );

    // Switch to Upload File engine
    fireEvent.click(screen.getByTestId("engine-option-upload"));
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-error").textContent).toContain(
      "Please select a .sqlite, .db, .csv, or .json file",
    );

    const dropzone = screen.getByTestId("db-upload-dropzone");
    fireEvent.dragOver(dropzone);
    fireEvent.dragLeave(dropzone);
    fireEvent.click(dropzone);

    const file = new File(["id,name\n1,Alice\n"], "customers.csv", { type: "text/csv" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    await waitFor(() => {
      expect((screen.getByTestId("input-db-name") as HTMLInputElement).value).toBe("Customers");
    });

    // Also test file input change when name is already populated
    const secondFile = new File(["id\n1\n"], "orders.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("db-upload-input"), {
      target: { files: [secondFile] },
    });

    await waitFor(() => {
      expect(dropzone.textContent).toContain("orders.csv");
    });

    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    expect(screen.getByTestId("db-connection-success").textContent).toContain("orders.csv");

    // Switch to Connected Databases tab and test group filters
    fireEvent.click(screen.getByTestId("tab-manage-dbs"));
    fireEvent.click(screen.getByTestId("filter-group-CUSTOM"));
    expect(screen.getByTestId("manage-db-row-custom_sales")).toBeTruthy();

    fireEvent.click(screen.getByTestId("filter-group-POSTGRES"));
    expect(screen.getByTestId("manage-db-row-starter_pg")).toBeTruthy();

    fireEvent.click(screen.getByTestId("filter-group-MYSQL"));
    expect(screen.getByTestId("manage-db-empty")).toBeTruthy();

    fireEvent.click(screen.getByTestId("filter-group-SQLITE"));
    expect(screen.getByTestId("manage-db-row-custom_sales")).toBeTruthy();

    fireEvent.click(screen.getByTestId("filter-group-ALL"));
    fireEvent.change(screen.getByTestId("input-search-dbs"), {
      target: { value: "Sales" },
    });
    expect(screen.getByTestId("manage-db-row-custom_sales")).toBeTruthy();

    // Switch back to connect tab and back to manage tab
    fireEvent.click(screen.getByTestId("tab-connect-new"));
    fireEvent.click(screen.getByTestId("tab-manage-dbs"));

    // Disconnect custom_sales
    fireEvent.click(screen.getByTestId("btn-disconnect-db-custom_sales"));
    await waitFor(() => {
      expect(onDisconnectDatabase).toHaveBeenCalledWith("custom_sales");
      expect(onDatabaseDisconnected).toHaveBeenCalledWith("custom_sales");
    });

    // Switch to custom_sales
    fireEvent.click(screen.getByTestId("btn-switch-db-custom_sales"));
    expect(onSelectDatabase).toHaveBeenCalledWith("custom_sales");
    expect(onClose).toHaveBeenCalled();
  });

  it("handles callback failure and fetch fallback error/success paths plus unstyled mode", async () => {
    const failingTest = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: "error",
        dialect: "postgres",
        table_count: 0,
        foreign_key_count: 0,
        detail: "Authentication failed for user",
      })
      .mockRejectedValueOnce(new Error("Network timeout"));

    const { unmount } = render(
      <DatabaseConnectionModal
        isOpen={true}
        onClose={vi.fn()}
        onTestConnection={failingTest}
        unstyled={true}
      />,
    );

    fireEvent.change(screen.getByTestId("input-db-database"), {
      target: { value: "analytics" },
    });
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(screen.getByTestId("db-connection-error").textContent).toContain(
        "Authentication failed for user",
      );
    });

    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(screen.getByTestId("db-connection-error").textContent).toContain(
        "Network timeout",
      );
    });
    unmount();

    // Now test fetch fallback for both error and success responses
    let shouldFail = true;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (shouldFail) {
        return new Response(JSON.stringify({ ok: false, detail: "Backend error" }), { status: 400 });
      }
      if (url.endsWith("/test")) {
        return new Response(
          JSON.stringify({
            ok: true,
            status: "connected",
            dialect: "postgres",
            table_count: 3,
            foreign_key_count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/connect") || url.endsWith("/upload")) {
        return new Response(
          JSON.stringify({
            ok: true,
            database: { id: "custom_pg", name: "PG", dialect: "postgres", is_custom: true },
            schema: { tables: {}, foreign_keys: [] },
          }),
          { status: 200 },
        );
      }
      if (init?.method === "DELETE") {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "Bad request" }), { status: 400 });
    });

    const onSelectDatabase = vi.fn();
    const onClose = vi.fn();

    render(
      <DatabaseConnectionModal
        isOpen={true}
        onClose={onClose}
        databases={MOCK_DATABASES}
        activeDatabaseId="starter_pg"
        onSelectDatabase={onSelectDatabase}
        apiBaseUrl="/api/databases"
      />,
    );

    // Toggle password visibility
    const pwInput = screen.getByTestId("input-db-password") as HTMLInputElement;
    expect(pwInput.type).toBe("password");
    fireEvent.click(screen.getByText("Show"));
    expect(pwInput.type).toBe("text");

    fireEvent.change(screen.getByTestId("input-db-database"), {
      target: { value: "analytics" },
    });

    // Test failure via fetch
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(screen.getByTestId("db-connection-error").textContent).toContain("Backend error");
    });

    // Connect failure via fetch
    fireEvent.click(screen.getByTestId("btn-save-db-connection"));
    await waitFor(() => {
      expect(screen.getByTestId("db-connection-error").textContent).toContain("Backend error");
    });

    // Disconnect failure via fetch renders visible error alert in manage tab
    fireEvent.click(screen.getByTestId("tab-manage-dbs"));
    fireEvent.click(screen.getByTestId("btn-disconnect-db-custom_sales"));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
      expect(screen.getByTestId("db-connection-error").textContent).toContain("Backend error");
    });

    // Empty search in manage tab renders empty state
    fireEvent.change(screen.getByTestId("input-search-dbs"), {
      target: { value: "zzz_no_matching_db" },
    });
    expect(screen.getByTestId("manage-db-empty")).toBeTruthy();
    fireEvent.change(screen.getByTestId("input-search-dbs"), {
      target: { value: "" },
    });

    // Now switch fetch to succeed
    shouldFail = false;
    fireEvent.click(screen.getByTestId("btn-disconnect-db-custom_sales"));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/databases/custom_sales",
        expect.objectContaining({ method: "DELETE" }),
      );
    });

    fireEvent.click(screen.getByTestId("tab-connect-new"));
    fireEvent.click(screen.getByTestId("btn-test-db-connection"));
    await waitFor(() => {
      expect(screen.getByTestId("db-connection-success")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("btn-save-db-connection"));
    await waitFor(() => {
      expect(onSelectDatabase).toHaveBeenCalledWith("custom_pg");
    });

    // Also test upload endpoint via fetch (including empty file drop/change guard)
    fireEvent.click(screen.getByTestId("engine-option-upload"));
    fireEvent.drop(screen.getByTestId("db-upload-dropzone"), { dataTransfer: { files: [] } });
    fireEvent.change(screen.getByTestId("db-upload-input"), { target: { files: [] } });
    const csvFile = new File(["a,b\n1,2\n"], "upload.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("db-upload-input"), { target: { files: [csvFile] } });
    await waitFor(() => {
      expect(screen.getByTestId("db-upload-dropzone").textContent).toContain("upload.csv");
    });
    fireEvent.click(screen.getByTestId("btn-save-db-connection"));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/databases/upload",
        expect.objectContaining({ method: "POST" }),
      );
    });

    // Escape key closes modal
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("integrates into VisualQueryBuilder toolbar when showConnectDatabaseButton is true", () => {
    const schema = {
      tables: {
        users: {
          name: "users",
          columns: [
            { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
          ],
        },
      },
      foreign_keys: [],
    };
    render(
      <VisualQueryBuilder
        schema={schema}
        showConnectDatabaseButton={true}
        databases={MOCK_DATABASES}
        activeDatabaseId="starter_pg"
      />,
    );

    const connectBtn = screen.getByTestId("btn-open-connect-database");
    fireEvent.click(connectBtn);
    expect(screen.getByTestId("database-connection-modal")).toBeTruthy();
  });
});

