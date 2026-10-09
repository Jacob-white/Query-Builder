import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, renderHook, act, waitFor } from "@testing-library/react";
import { ThemeProvider, useTheme, lightTheme, useQueryBuilder, useStreamingQuery, useSqlCompiler } from "../src/index";
import { parseSqlToSpec } from "../src/utils/sqlParser";
import type { CteSpec, VisualQueryBuilderRef } from "../src/types";
import type { ThemeProviderProps } from "../src/theme/ThemeProvider";
import { invalid, makeColumn, makeSnapshot, makeSpec, makeTable } from "./helpers";

const emptySchema = () => makeSnapshot({});
/** Single-table schema from [column, data_type] pairs. */
const usersSchema = (cols: [string, string][]) =>
  makeSnapshot({
    users: makeTable("users", cols.map(([n, t]) => makeColumn(n, { data_type: t }))),
  });

describe("ThemeProvider (review regressions)", () => {
  it("honours the mode carried by an explicit theme when no mode prop is given", () => {
    let seen: ReturnType<typeof useTheme> | null = null;
    const Probe = () => {
      seen = useTheme();
      return null;
    };
    render(
      <ThemeProvider theme={lightTheme}>
        <Probe />
      </ThemeProvider>,
    );
    expect(seen!.mode).toBe("light");
    expect(seen!.theme.mode).toBe("light");
  });

  it("keeps a toggled mode when the parent re-renders with an inline theme object", () => {
    let seen: ReturnType<typeof useTheme> | null = null;
    const Probe = () => {
      seen = useTheme();
      return null;
    };
    const Wrapper = ({ tick }: { tick: number }) => (
      <ThemeProvider theme={{ colors: { primary: "#123456" } }} data-tick={tick}>
        <Probe />
      </ThemeProvider>
    );
    const { rerender } = render(<Wrapper tick={0} />);
    expect(seen!.mode).toBe("dark");
    act(() => seen!.toggleMode());
    expect(seen!.mode).toBe("light");
    rerender(<Wrapper tick={1} />);
    rerender(<Wrapper tick={2} />);
    expect(seen!.mode).toBe("light");
    expect(seen!.theme.colors.primary).toBe("#123456");
  });
});

describe("useQueryBuilder reset (review regressions)", () => {
  it("keeps a stable reset identity when options contain inline arrays", () => {
    const { result, rerender } = renderHook(() =>
      useQueryBuilder({ schema: emptySchema(), ctes: [invalid<CteSpec>({ name: "c", spec: {} })] }),
    );
    const first = result.current.actions.reset;
    rerender();
    rerender();
    expect(result.current.actions.reset).toBe(first);
  });
});

describe("parseSqlToSpec aliases (review regressions)", () => {
  it("does not treat trailing clause keywords as the table alias", () => {
    const spec = parseSqlToSpec("SELECT id FROM users WHERE id = 1", emptySchema());
    expect(spec?.table).toBe("users");
  });

  it("still resolves explicit and implicit aliases in joins", () => {
    const spec = parseSqlToSpec(
      "SELECT u.id FROM users AS u LEFT JOIN orders o ON u.id = o.user_id",
      emptySchema(),
    );
    expect(spec?.table).toBe("users");
    expect(spec?.joins?.[0]?.table).toBe("orders");
    expect(spec?.joins?.[0]?.left_table).toBe("users");
  });
});

describe("useStreamingQuery terminal events (review regressions)", () => {
  afterEach(() => vi.unstubAllGlobals());

  const sse = (chunks: string[], failAfter = false) => {
    const enc = new TextEncoder();
    let i = 0;
    return new ReadableStream({
      pull(controller) {
        if (i < chunks.length) {
          controller.enqueue(enc.encode(chunks[i++]));
        } else if (failAfter) {
          controller.error(new Error("socket reset"));
        } else {
          controller.close();
        }
      },
    });
  };

  it("fires only onComplete when the transport fails after a done event", async () => {
    const body = sse(['event: batch\ndata: {"rows":[{"a":1}]}\n\n', "event: done\ndata: {}\n\n"], true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));
    const onComplete = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useStreamingQuery(undefined, { endpoint: "/s", onComplete, onError }),
    );
    await act(async () => {
      await result.current.execute({ sql: "select 1" });
    });
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(onError).not.toHaveBeenCalled();
  });

  it("fires only onError when done follows an error event", async () => {
    const body = sse(['event: error\ndata: {"message":"boom"}\n\n', "event: done\ndata: {}\n\n"]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, body }));
    const onComplete = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useStreamingQuery(undefined, { endpoint: "/s", onComplete, onError }),
    );
    await act(async () => {
      await result.current.execute({ sql: "select 1" });
    });
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onComplete).not.toHaveBeenCalled();
  });
});

describe("VisualQueryBuilder raw SQL safeguard (review regressions)", () => {
  const schema = usersSchema([
    ["id", "integer"],
    ["name", "text"],
  ]);

  it("offers to restore custom SQL replaced by a visual edit", async () => {
    const store: Record<string, string> = {};
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store[k] ?? null,
      setItem: (k: string, v: string) => void (store[k] = v),
      removeItem: (k: string) => void delete store[k],
      clear: () => Object.keys(store).forEach((k) => delete store[k]),
    });
    const ref = React.createRef<VisualQueryBuilderRef>();
    const { fireEvent, screen } = await import("@testing-library/react");
    const { VisualQueryBuilder } = await import("../src/index");
    render(<VisualQueryBuilder ref={ref} schema={schema} />);

    fireEvent.click(document.getElementById("tab-sql")!);
    const custom = "SELECT id /* hand written */ FROM users";
    fireEvent.change(screen.getByLabelText("Raw SQL code"), { target: { value: custom } });
    expect(screen.queryByText(/replaced your custom SQL/)).toBeNull();

    act(() => ref.current!.setSpec(makeSpec({ table: "users", columns: ["name"] })));
    expect(await screen.findByText(/replaced your custom SQL/)).toBeTruthy();

    fireEvent.click(screen.getByText("Restore my SQL"));
    expect((screen.getByLabelText("Raw SQL code") as HTMLTextAreaElement).value).toBe(custom);
    expect(screen.queryByText(/replaced your custom SQL/)).toBeNull();
    vi.unstubAllGlobals();
  });
});

describe("follow-up review regressions", () => {
  it("keeps aliases in comma-joined FROM lists", () => {
    const spec = parseSqlToSpec(
      "SELECT u.id FROM users u, orders o LEFT JOIN items i ON i.order_id = o.id",
      emptySchema(),
    );
    expect(spec?.table).toBe("users");
  });

  it("keeps a toggled mode when only an unrelated theme token changes", () => {
    let seen: ReturnType<typeof useTheme> | null = null;
    const Probe = () => {
      seen = useTheme();
      return null;
    };
    const view = (primary: string) => (
      <ThemeProvider theme={{ colors: { primary } }}>
        <Probe />
      </ThemeProvider>
    );
    const { rerender } = render(view("#111111"));
    act(() => seen!.toggleMode());
    rerender(view("#222222"));
    expect(seen!.mode).toBe("light");
    expect(seen!.theme.colors.primary).toBe("#222222");
  });

  it("normalizes filter_join casing/whitespace and warns on unsupported values", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const schema = usersSchema([["id", "integer"]]);
    const spec = (fj: string) => ({
      table: "users",
      columns: ["id"],
      filters: [
        { column: "id", operator: "=", value: 1 },
        { column: "id", operator: "=", value: 2 },
      ],
      filter_join: fj,
    });
    const or = renderHook(() => useSqlCompiler(spec(" or "), { schema }));
    expect(or.result.current.sql).toMatch(/\sOR\s/);
    expect(warn).not.toHaveBeenCalled();
    renderHook(() => useSqlCompiler(spec("xor"), { schema }));
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe("second follow-up review regressions", () => {
  it("keeps bracket/backtick qualified table names and their aliases whole", () => {
    const a = parseSqlToSpec("SELECT u.id FROM [dbo].[users] u WHERE u.id = 1", emptySchema());
    expect(a?.table).toBe("dbo.users");
    const b = parseSqlToSpec("SELECT o.id FROM `db`.`orders` AS o", emptySchema());
    expect(b?.table).toBe("db.orders");
  });

  it("does not treat table hints as aliases", () => {
    const spec = parseSqlToSpec("SELECT id FROM users WITH (NOLOCK) WHERE id = 1", emptySchema());
    expect(spec?.table).toBe("users");
  });

  it("round-trips mixed AND/OR precedence through per-filter combiners", () => {
    const spec = parseSqlToSpec("SELECT id FROM users WHERE a = 1 AND b = 2 OR c = 3", emptySchema());
    expect(spec?.filters.map((f) => f.combiner)).toEqual(["AND", "AND", "OR"]);
  });

  it("lets a user-picked mode win over a controlled mode prop on token changes", () => {
    let seen: ReturnType<typeof useTheme> | null = null;
    const Probe = () => {
      seen = useTheme();
      return null;
    };
    const view = (primary: string) => (
      <ThemeProvider mode="dark" customTokens={{ colors: { primary } }}>
        <Probe />
      </ThemeProvider>
    );
    const { rerender } = render(view("#111111"));
    act(() => seen!.toggleMode());
    rerender(view("#222222"));
    expect(seen!.mode).toBe("light");
    expect(seen!.theme.colors.primary).toBe("#222222");
  });

  it("detects theme changes confined to function values", () => {
    let seen: ReturnType<typeof useTheme> | null = null;
    const Probe = () => {
      seen = useTheme();
      return null;
    };
    const view = (fn: () => number) => (
      <ThemeProvider customTokens={invalid<ThemeProviderProps["customTokens"]>({ extra: fn })}>
        <Probe />
      </ThemeProvider>
    );
    const { rerender } = render(view(() => 1));
    const before = seen!.theme;
    rerender(view(() => 2));
    expect(seen!.theme).not.toBe(before);
  });

  it("restores a clean (non-dirty) state after reset when init values changed post-mount", () => {
    const schema = (cols: string[]) => usersSchema(cols.map((name): [string, string] => [name, "text"]));
    const { result, rerender } = renderHook(
      ({ initialSql }: { initialSql: string }) => useQueryBuilder({ schema: schema(["id"]), initialSql }),
      { initialProps: { initialSql: "SELECT 1" } },
    );
    rerender({ initialSql: "SELECT 2" });
    act(() => result.current.actions.reset());
    expect(result.current.state.isDirty).toBe(false);
  });
});

describe("per-filter combiners reach the emitted spec", () => {
  const schema = usersSchema(["a", "b", "c"].map((name): [string, string] => [name, "integer"]));

  it("emits mixed AND/OR combiners instead of collapsing them to one filter_join", () => {
    const { result } = renderHook(() =>
      useSqlCompiler(
        {
          table: "users",
          columns: ["a"],
          filters: [
            { column: "a", operator: "=", value: 1, combiner: "AND" },
            { column: "b", operator: "=", value: 2, combiner: "AND" },
            { column: "c", operator: "=", value: 3, combiner: "OR" },
          ],
        },
        { schema },
      ),
    );
    expect(result.current.sql).toMatch(/"a" = 1 AND .*"b" = 2 OR .*"c" = 3/);
    const combiners = result.current.ast?.filters.map((f) => f.combiner);
    // Every filter states its combiner once any OR is present, so a backend cannot reinterpret
    // the explicit ANDs through filter_join.
    expect(combiners).toEqual(["AND", "AND", "OR"]);
    expect(result.current.ast?.filter_join).toBe("OR");
  });

  it("keeps AND-only specs free of per-filter combiners (exact round-trip)", () => {
    const { result } = renderHook(() =>
      useSqlCompiler(
        {
          table: "users",
          columns: ["a"],
          filters: [
            { column: "a", operator: "=", value: 1 },
            { column: "b", operator: "=", value: 2 },
          ],
        },
        { schema },
      ),
    );
    expect(result.current.ast?.filters.every((f) => f.combiner === undefined)).toBe(true);
  });

  it("loadSpec applies a spec-level filter_join to filters without their own combiner", () => {
    const { result } = renderHook(() => useQueryBuilder({ schema }));
    act(() =>
      result.current.actions.loadSpec({
        table: "users",
        columns: ["a"],
        filters: [
          { column: "a", operator: "=", value: 1 },
          { column: "b", operator: "=", value: 2 },
        ],
        filter_join: "OR",
      }),
    );
    expect(result.current.state.filters.map((f) => f.combiner)).toEqual(["OR", "OR"]);
    expect(result.current.compiled.sql).toMatch(/\sOR\s/);
  });
});
