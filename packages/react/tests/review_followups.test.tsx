import { StrictMode, createRef, type ReactNode } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, renderHook, act, waitFor } from "@testing-library/react";
import { useStreamingQuery } from "../src/hooks/useStreamingQuery";
import { useQueryBuilder } from "../src/hooks/useQueryBuilder";
import { stateToSpec, specToState } from "../src/hooks/useQueryState";
import { parseSqlToSpec } from "../src/utils/sqlParser";
import { compileSpecToSql, compileVisualState } from "../src/utils/compiler";
import { normalizeCombiner, resolveFilterCombiners } from "../src/utils/filterCombiners";
import { executeAgentToolCall } from "../src/ai/tools";
import { ingestLocalFile } from "../src/utils/localDataIngest";
import type { VisualFilter, VisualQueryBuilderRef } from "../src/types";

/** Fetch mock that streams one batch after `latencyMs` and honours AbortSignal. */
function installDelayedFetch(latencyMs: number, rowId: (call: number) => number = (c) => c) {
  const signals: AbortSignal[] = [];
  const mock = vi.fn((_url: unknown, init?: RequestInit) => {
    const call = signals.length + 1;
    const signal = init?.signal as AbortSignal;
    signals.push(signal);
    return new Promise<Response>((resolve, reject) => {
      const onAbort = () => reject(new DOMException("aborted", "AbortError"));
      if (signal.aborted) return onAbort();
      signal.addEventListener("abort", onAbort, { once: true });
      setTimeout(() => {
        signal.removeEventListener("abort", onAbort);
        const enc = new TextEncoder();
        const body = new ReadableStream({
          start(c) {
            c.enqueue(
              enc.encode(
                `event: batch\ndata: {"rows":[{"id":${rowId(call)}}]}\n\nevent: done\ndata: {}\n\n`
              )
            );
            c.close();
          },
        });
        resolve(new Response(body, { status: 200 }));
      }, latencyMs);
    });
  });
  globalThis.fetch = mock as unknown as typeof fetch;
  return { mock, signals };
}

describe("A) useStreamingQuery does not abort itself", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("default options + execute(payload) completes (stable execute identity)", async () => {
    const { signals } = installDelayedFetch(60);
    const onComplete = vi.fn();
    const { result } = renderHook(() => useStreamingQuery(undefined, { onComplete }));
    const first = result.current.execute;
    await act(async () => {
      void result.current.execute({ table: "t" });
    });
    expect(result.current.isStreaming).toBe(true);
    await waitFor(() => expect(result.current.rows).toHaveLength(1), { timeout: 2000 });
    expect(signals[0].aborted).toBe(false);
    expect(result.current.isStreaming).toBe(false);
    expect(onComplete).toHaveBeenCalledWith(1);
    expect(result.current.execute).toBe(first);
  });

  it("uses the latest headers/callbacks without changing execute identity", async () => {
    const { mock } = installDelayedFetch(5);
    const { result, rerender } = renderHook(
      ({ token }: { token: string }) =>
        useStreamingQuery(undefined, { headers: { Authorization: token } }),
      { initialProps: { token: "a" } }
    );
    rerender({ token: "b" });
    await act(async () => {
      await result.current.execute({ table: "t" });
    });
    const init = mock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("b");
  });

  it("StrictMode + autoExecute still completes the auto-run", async () => {
    const { mock } = installDelayedFetch(40);
    const onComplete = vi.fn();
    const options = { autoExecute: true, onComplete };
    const payload = { table: "users" };
    const wrapper = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;
    const { result } = renderHook(() => useStreamingQuery(payload, options), { wrapper });
    await waitFor(() => expect(result.current.rows.length).toBeGreaterThan(0), { timeout: 2000 });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));
    expect(mock).toHaveBeenCalled();
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
  });

  it("overlapping executes: superseded abort does not clear active isStreaming", async () => {
    const { signals } = installDelayedFetch(80);
    const options = {};
    const { result } = renderHook(() => useStreamingQuery(undefined, options));
    await act(async () => {
      void result.current.execute({ table: "a" });
    });
    await act(async () => {
      void result.current.execute({ table: "b" });
    });
    // let the aborted run's rejection settle
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(signals[0].aborted).toBe(true);
    expect(result.current.isStreaming).toBe(true);
    await waitFor(() => expect(result.current.rows).toEqual([{ id: 2 }]), { timeout: 2000 });
    expect(result.current.isStreaming).toBe(false);
  });

  it("aborts the in-flight request on real unmount", async () => {
    const { signals } = installDelayedFetch(200);
    const { result, unmount } = renderHook(() => useStreamingQuery());
    await act(async () => {
      void result.current.execute({ table: "t" });
    });
    unmount();
    expect(signals[0].aborted).toBe(true);
  });
});

describe("C) sqlParser keeps legal join aliases", () => {
  const joinOf = (sql: string) => {
    const spec = parseSqlToSpec(sql, { tables: {} } as never);
    return spec?.joins?.[0];
  };

  it.each(["final", "sample", "settings", "partition", "ignore", "use", "force", "with"])(
    "alias %s resolves the join columns in the right direction",
    (alias) => {
      const j = joinOf(`SELECT u.id FROM users u JOIN orders ${alias} ON ${alias}.user_id = u.id`);
      expect(j?.table).toBe("orders");
      expect(j?.left_table).toBe("users");
      expect(j?.left_col).toBe("id");
      expect(j?.right_col).toBe("user_id");
    },
  );

  it("accepts an explicit AS final alias", () => {
    const j = joinOf("SELECT u.id FROM users u JOIN orders AS final ON final.user_id = u.id");
    expect(j?.left_col).toBe("id");
    expect(j?.right_col).toBe("user_id");
  });

  it.each([
    "WITH (NOLOCK)",
    "FORCE INDEX (idx_a)",
    "USE INDEX (idx_a)",
    "IGNORE INDEX (idx_a)",
    "PARTITION (p0)",
    "USE KEY (k)",
  ])("treats the table hint %s as a hint, not an alias", (hint) => {
    const j = joinOf(`SELECT u.id FROM users u JOIN orders o ${hint} ON o.user_id = u.id`);
    expect(j?.left_col).toBe("id");
    expect(j?.right_col).toBe("user_id");
    const spec = parseSqlToSpec(`SELECT u.id FROM users u ${hint} WHERE u.id = 1`, { tables: {} } as never);
    expect(spec?.table).toBe("users");
    expect(spec?.filters[0].column).toBe("id");
  });

  it("does not take clause keywords as aliases", () => {
    const j = joinOf("SELECT u.id FROM users u LEFT JOIN orders ON orders.user_id = u.id");
    expect(j?.table).toBe("orders");
    expect(j?.left_col).toBe("id");
    expect(j?.right_col).toBe("user_id");
  });
});

const f = (column: string, combiner?: unknown, value: unknown = 1): VisualFilter =>
  ({ id: column, tablePrefix: "users", column, operator: "=", value, combiner }) as VisualFilter;

const compile = (filters: VisualFilter[], filterJoin: "AND" | "OR" = "AND") =>
  compileVisualState("users", {}, [], [], filters, [], false, 10, null, "postgres", filterJoin);

describe("D) combiners are resolved once and agree between SQL and spec", () => {
  it("normalizer + resolver basics", () => {
    expect(normalizeCombiner("or")).toBe("OR");
    expect(normalizeCombiner(" And ")).toBe("AND");
    expect(normalizeCombiner("xor", "OR")).toBe("OR");
    expect(normalizeCombiner(undefined)).toBe("AND");
    expect(resolveFilterCombiners([{}, { combiner: "or" }], "and")).toEqual({
      combiners: ["AND", "OR"],
      filterJoin: "OR",
      hasOr: true,
    });
    expect(resolveFilterCombiners([], "OR").filterJoin).toBe("OR");
  });

  it("an inactive OR filter does not make the spec OR", () => {
    const out = compile([f("a", "AND"), f("b", "AND"), f("", "OR")]);
    expect(out.sql).toContain('WHERE "users"."a" = 1 AND "users"."b" = 1');
    expect(out.spec.filter_join).toBe("AND");
    expect(out.spec.filters.every((x) => x.combiner === undefined)).toBe(true);
  });

  it("an OR on an emitted filter is stated on every filter and in filter_join", () => {
    const out = compile([f("a"), f("b", "or"), f("c", "AND")]);
    expect(out.sql).toContain('"users"."a" = 1 OR "users"."b" = 1 AND "users"."c" = 1');
    expect(out.spec.filter_join).toBe("OR");
    expect(out.spec.filters.map((x) => x.combiner)).toEqual(["AND", "OR", "AND"]);
  });

  it("lowercase filterJoin is honoured consistently", () => {
    const out = compile([f("a"), f("b")], "or" as "OR");
    expect(out.sql).toContain(" OR ");
    expect(out.spec.filter_join).toBe("OR");
    expect(out.spec.filters.map((x) => x.combiner)).toEqual(["OR", "OR"]);
    const and = compile([f("a"), f("b")], "and" as "AND");
    expect(and.sql).toContain(" AND ");
    expect(and.spec.filter_join).toBe("AND");
  });

  it("filters that yield no SQL do not feed the aggregate", () => {
    const empty = { ...f("c", "OR"), operator: "BETWEEN", value: "1" } as VisualFilter;
    const out = compile([f("a", "AND"), f("b", "AND"), empty]);
    expect(out.sql).not.toContain("BETWEEN");
    expect(out.spec.filter_join).toBe("AND");
    expect(out.spec.filters).toHaveLength(2);
  });

  it("stateToSpec uses the same resolution", () => {
    const state = specToState({
      table: "users",
      filters: [
        { column: "a", op: "=", value: 1 },
        { column: "b", op: "=", value: 2, combiner: "or" },
      ],
    });
    const spec = stateToSpec({
      primaryTable: "users",
      selectedColumns: {},
      orderedProjectionKeys: [],
      joins: [],
      sorts: [],
      isDistinct: false,
      limit: 10,
      ...state,
    } as never);
    expect(spec.filter_join).toBe("OR");
    expect(spec.filters.map((x) => x.combiner)).toEqual(["AND", "OR"]);
  });

  it("useQueryBuilder: stale filterJoin OR + loadSpec without filter_join stays consistent", () => {
    const { result } = renderHook(() => useQueryBuilder({ filterJoin: "OR" }));
    act(() => {
      result.current.actions.loadSpec({
        table: "users",
        columns: ["id"],
        filters: [
          { column: "a", op: "=", value: 1 },
          { column: "b", op: "=", value: 2 },
        ],
      });
    });
    expect(result.current.currentSql).toContain('"a" = 1 AND "users"."b" = 2');
    expect(result.current.compiled.spec.filter_join).toBe("AND");
    expect(result.current.state.filterJoin).toBe("AND");
  });

  it("loadSpec normalizes a lowercase filter_join", () => {
    const { result } = renderHook(() => useQueryBuilder());
    act(() => {
      result.current.actions.loadSpec({
        table: "users",
        filters: [
          { column: "a", op: "=", value: 1 },
          { column: "b", op: "=", value: 2 },
        ],
        filter_join: "or",
      });
    });
    expect(result.current.state.filterJoin).toBe("OR");
    expect(result.current.currentSql).toContain(" OR ");
    expect(result.current.compiled.spec.filter_join).toBe("OR");
  });
});

describe("E) combiners and other spec strings can not inject SQL", () => {
  it.each(["OR 1=1 OR", "OR 1=1 --", "AND 1=1; DROP TABLE users; --", "", "xor"])(
    "combiner %j yields only AND/OR",
    (evil) => {
      const sql = compileSpecToSql({
        table: "users",
        columns: ["id"],
        filters: [
          { column: "tenant_id", op: "=", value: 7 },
          { column: "id", op: "=", value: 1, combiner: evil },
        ],
      } as never);
      expect(sql).not.toMatch(/1=1|DROP|--/);
      expect(sql).toMatch(/"tenant_id" = 7 (AND|OR) "users"\."id" = 1/);
    },
  );

  it("per-filter combiner injection through the VisualFilter compiler", () => {
    const out = compile([f("a"), f("b", "OR 1=1 OR")]);
    expect(out.sql).not.toContain("1=1");
    expect(out.spec.filters.every((x) => x.combiner === undefined || /^(AND|OR)$/.test(x.combiner))).toBe(true);
  });

  it("parenOpen / parenClose only emit parentheses", () => {
    const out = compile([{ ...f("a"), parenOpen: "1=1 OR (", parenClose: ") OR 1=1" } as VisualFilter, f("b")]);
    expect(out.sql).not.toContain("1=1");
    expect(out.sql).toContain('("users"."a" = 1) AND');
  });

  it("agent tool validate_and_compile_query reports only AND/OR", () => {
    const result = executeAgentToolCall("validate_and_compile_query", {
      spec: {
        table: "users",
        columns: ["id"],
        joins: [],
        filters: [
          { column: "tenant_id", op: "=", value: 7 },
          { column: "id", op: "=", value: 1, combiner: "OR 1=1 --" },
        ],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit: 5,
      },
    });
    expect(result.sql ?? "").not.toMatch(/1=1|--/);
  });

  it("whitelists window function direction, frame, function name and time grain", () => {
    const sql = compileSpecToSql({
      table: "t",
      columns: [{ column: "t.ts", time_grain: "day') ; DROP TABLE x; --" }],
      window_functions: [
        {
          function: "ROW_NUMBER() OVER () ; DROP TABLE x; --",
          order_by: [{ column: "a", direction: "ASC; DROP TABLE x" }],
          frame: { frame_type: "ROWS; DROP", start: "1; DROP", end: "CURRENT ROW; --", exclusion: "x; DROP" },
          alias: "rn",
        },
      ],
    } as never);
    expect(sql).not.toMatch(/DROP|;\s*\S/);
  });

  it("whitelists join type and sort direction", () => {
    const sql = compileSpecToSql({
      table: "users",
      columns: ["id"],
      joins: [{ table: "orders", type: "INNER JOIN x; DROP TABLE y; --", left_col: "id", right_col: "user_id" }],
      order_by: [{ column: "id", direction: "DESC; DROP TABLE y" }],
    } as never);
    expect(sql).not.toMatch(/DROP|--|;\s*\S/);
  });
});

describe("F) initialSpec accepts a QuerySpec", () => {
  const spec = {
    table: "users",
    columns: ["id", "a"],
    filters: [
      { column: "a", op: "=", value: 1 },
      { column: "b", op: "=", value: 2 },
    ],
    filter_join: "OR",
    joins: [{ table: "orders", left_col: "id", right_col: "user_id" }],
    order_by: [{ column: "id", direction: "DESC" }],
    limit: 7,
  };

  it("matches loadSpec output exactly", () => {
    const a = renderHook(() => useQueryBuilder({ initialSpec: spec }));
    const b = renderHook(() => useQueryBuilder());
    act(() => b.result.current.actions.loadSpec(spec));
    expect(a.result.current.currentSql).toBe(b.result.current.currentSql);
    expect(a.result.current.currentSql).toContain("ORDER BY");
    expect(a.result.current.currentSql).toContain(" OR ");
    expect(a.result.current.currentSql).toContain("JOIN");
    expect(a.result.current.currentSql).toContain("LIMIT 7");
    expect(a.result.current.currentSql).not.toContain("SELECT *");
    expect(a.result.current.compiled.spec).toEqual(b.result.current.compiled.spec);
  });

  it("reset() restores the converted values", () => {
    const { result } = renderHook(() => useQueryBuilder({ initialSpec: spec }));
    const original = result.current.currentSql;
    act(() => result.current.actions.setLimit(99));
    expect(result.current.currentSql).not.toBe(original);
    act(() => result.current.actions.reset());
    expect(result.current.currentSql).toBe(original);
  });

  it("still supports state-shaped initialSpec", () => {
    const { result } = renderHook(() =>
      useQueryBuilder({
        initialSpec: {
          primaryTable: "users",
          selectedColumns: { "users.id": { table: "users", name: "id" } },
          orderedProjectionKeys: ["users.id"],
          limit: 5,
        },
      }),
    );
    expect(result.current.currentSql).toContain('"users"."id"');
    expect(result.current.currentSql).toContain("LIMIT 5");
  });
});

describe("G) VisualQueryBuilder raw SQL honesty and semantic loss detection", () => {
  const schema = {
    tables: {
      users: {
        name: "users",
        columns: [
          { name: "id", type: "integer" },
          { name: "name", type: "text" },
        ],
      },
    },
  } as never;

  const setup = async (extra: Record<string, unknown> = {}) => {
    const ref = createRef<VisualQueryBuilderRef>();
    const { fireEvent, screen } = await import("@testing-library/react");
    const { VisualQueryBuilder } = await import("../src/index");
    render(<VisualQueryBuilder ref={ref} schema={schema} {...extra} />);
    fireEvent.click(document.getElementById("tab-sql")!);
    const type = (sql: string) =>
      fireEvent.change(screen.getByLabelText("Raw SQL code"), { target: { value: sql } });
    return { ref, screen, type };
  };

  it("typing SELECT yields a null spec (no throw) for getSpec / onChange / onExecuteQuery", async () => {
    const onChange = vi.fn();
    const onExecuteQuery = vi.fn().mockResolvedValue({ columns: [], rows: [], count: 0, durationMs: 1 });
    const { ref, type } = await setup({ onChange, onExecuteQuery });
    expect(() => type("SELECT")).not.toThrow();
    expect(ref.current!.getSpec()).toBeNull();
    expect(onChange).toHaveBeenLastCalledWith(null, "SELECT");
    await act(async () => {
      await ref.current!.execute();
    });
    expect(onExecuteQuery).toHaveBeenCalledWith("SELECT", null);
  });

  it("plain raw SQL still yields a real spec", async () => {
    const { ref, type } = await setup();
    type("select id from users");
    expect(ref.current!.getSpec()?.table).toBe("users");
  });

  it("does not show the lost-SQL notice for plain SQL the visual model represents", async () => {
    const { ref, screen, type } = await setup();
    type("select id from users");
    act(() => ref.current!.setSpec({ table: "users", columns: ["name"] } as never));
    expect(screen.queryByText(/replaced your custom SQL/)).toBeNull();
  });

  it("shows the notice for unparseable SQL and for SQL with comments", async () => {
    const first = await setup();
    first.type("SELECT");
    act(() => first.ref.current!.setSpec({ table: "users", columns: ["name"] } as never));
    expect(await first.screen.findByText(/replaced your custom SQL/)).toBeTruthy();
    cleanup();
    const second = await setup();
    second.type("select id -- note\nfrom users");
    act(() => second.ref.current!.setSpec({ table: "users", columns: ["name"] } as never));
    expect(await second.screen.findByText(/replaced your custom SQL/)).toBeTruthy();
  });
});

describe("H) ingestLocalFile accepts Proxy / function-target engines", () => {
  const file = () => new File(["a,b\n1,2\n"], "t.csv", { type: "text/csv" });
  const meta = { name: "t", rowCount: 1, columns: [] };

  it("recognises a Proxy that traps only get", async () => {
    const ingestCsv = vi.fn().mockResolvedValue({ ...meta });
    const target: Record<string, unknown> = {};
    const engine = new Proxy(target, {
      get: (_t, prop) => (prop === "query" || prop === "ingestCsv" ? (prop === "ingestCsv" ? ingestCsv : vi.fn()) : undefined),
    });
    const out = await ingestLocalFile(engine as never, file());
    expect(ingestCsv).toHaveBeenCalledWith("t", expect.any(String), expect.anything());
    expect(out.fileSource).toBe("t.csv");
  });

  it("recognises a function-target proxy (Comlink style)", async () => {
    const ingestCsv = vi.fn().mockResolvedValue({ ...meta });
    const engine = new Proxy(function remote() {}, {
      get: (_t, prop) => (prop === "ingestCsv" ? ingestCsv : prop === "query" ? vi.fn() : undefined),
    });
    await ingestLocalFile(engine as never, file());
    expect(ingestCsv).toHaveBeenCalledTimes(1);
  });

  it("still accepts (file, engine) order and plain objects", async () => {
    const ingestCsv = vi.fn().mockResolvedValue({ ...meta });
    await ingestLocalFile(file(), { query: vi.fn(), ingestCsv } as never);
    await ingestLocalFile({ query: vi.fn(), ingestCsv } as never, file());
    expect(ingestCsv).toHaveBeenCalledTimes(2);
  });
});

describe("B) public type compatibility (runtime parts)", () => {
  it("fluent where() carries list and null filter values", async () => {
    const { createQuery } = await import("../src/client");
    const spec = createQuery("t").where("id", "IN", [1, 2, 3]).where("deleted_at", "IS", null).toSpec();
    expect(spec.filters.map((x) => x.value)).toEqual([[1, 2, 3], null]);
  });

  it("agent tool definitions and results expose typed shapes", async () => {
    const { getAgentToolDefinitions } = await import("../src/ai/tools");
    const tools = getAgentToolDefinitions("openai");
    expect(tools[0].type).toBe("function");
    expect(tools[0].function.name).toBeTruthy();
    expect(getAgentToolDefinitions("anthropic")[0].input_schema).toBeTruthy();
    const res = executeAgentToolCall("build_query", { intent: "show users" });
    expect(res.success).toBe(true);
    expect(typeof res.sql).toBe("string");
  });

  it("NlqPromptBar renders table pills for adapter-style TableSchema[] schemas", async () => {
    const { NlqPromptBar } = await import("../src/index");
    const { screen } = await import("@testing-library/react");
    render(<NlqPromptBar schema={[{ name: "orders", columns: [] }]} />);
    expect(screen.getByText("orders")).toBeTruthy();
  });
});
