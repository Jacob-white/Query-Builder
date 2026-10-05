import { describe, it, expect } from "vitest";
import React, { useState } from "react";
import { render, screen, act } from "@testing-library/react";
import {
  QueryBuilderProvider,
  useQueryBuilderContext,
  VisualQueryBuilder,
  type SchemaSnapshot,
} from "../src";

const sampleSchema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "username", data_type: "varchar", is_nullable: false, is_primary: false },
      ],
    },
  },
};

const ContextConsumer: React.FC = () => {
  const ctx = useQueryBuilderContext();
  return (
    <div>
      <span data-testid="ctx-mode">{ctx?.mode}</span>
      <span data-testid="ctx-has-custom-op">
        {ctx?.customOperators ? Object.keys(ctx.customOperators).join(",") : "none"}
      </span>
    </div>
  );
};

describe("QueryBuilderProvider Styled/Unstyled Modes & Context Inheritance", () => {
  it("renders VisualQueryBuilder in styled mode by default with scoped CSS variables", () => {
    const { container } = render(
      <QueryBuilderProvider mode="styled">
        <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
      </QueryBuilderProvider>,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBeNull();

    const styleAttr = root?.getAttribute("style");
    expect(styleAttr).toBeDefined();
    expect(styleAttr).toContain("--qb-color-primary");
    expect(styleAttr).toContain("background");
  });

  it("automatically configures descendant VisualQueryBuilder into unstyled mode when mode='unstyled'", () => {
    const { container } = render(
      <QueryBuilderProvider mode="unstyled">
        <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
      </QueryBuilderProvider>,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();
    expect(root?.getAttribute("data-qb-unstyled")).toBe("true");

    // All inline styles stripped
    expect(root?.getAttribute("style")).toBeNull();

    const topBar = container.querySelector('[data-qb="top-bar"]');
    expect(topBar?.getAttribute("style")).toBeNull();
  });

  it("supports dynamic mode toggling via state", () => {
    const DynamicModeWrapper: React.FC = () => {
      const [mode, setMode] = useState<"styled" | "unstyled">("styled");
      return (
        <div>
          <button onClick={() => setMode((m) => (m === "styled" ? "unstyled" : "styled"))}>
            Toggle Mode
          </button>
          <QueryBuilderProvider mode={mode}>
            <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
          </QueryBuilderProvider>
        </div>
      );
    };

    const { container } = render(<DynamicModeWrapper />);
    const root = container.querySelector('[data-qb="root"]');
    expect(root?.getAttribute("data-qb-unstyled")).toBeNull();
    expect(root?.getAttribute("style")).toContain("--qb-color-primary");

    // Toggle to unstyled
    act(() => {
      screen.getByText("Toggle Mode").click();
    });

    const rootAfter = container.querySelector('[data-qb="root"]');
    expect(rootAfter?.getAttribute("data-qb-unstyled")).toBe("true");
    expect(rootAfter?.getAttribute("style")).toBeNull();
  });

  it("nested QueryBuilderProviders inherit parent options and allow overrides", () => {
    render(
      <QueryBuilderProvider
        mode="styled"
        customOperators={{
          parent_op: { label: "Parent Op", value: "PARENT_OP" },
        }}
      >
        <QueryBuilderProvider
          customOperators={{
            child_op: { label: "Child Op", value: "CHILD_OP" },
          }}
        >
          <ContextConsumer />
        </QueryBuilderProvider>
      </QueryBuilderProvider>,
    );

    expect(screen.getByTestId("ctx-mode").textContent).toBe("styled");
    const ops = screen.getByTestId("ctx-has-custom-op").textContent;
    expect(ops).toContain("parent_op");
    expect(ops).toContain("child_op");
  });
});
