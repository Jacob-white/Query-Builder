import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import {
  darkTheme,
  lightTheme,
  themeToCssVariables,
  ThemeProvider,
  useTheme,
  VisualQueryBuilder,
  type SchemaSnapshot,
} from "../src";

const sampleSchema: SchemaSnapshot = {
  tables: {
    users: {
      name: "users",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "name", data_type: "text", is_nullable: false, is_primary: false },
      ],
    },
  },
};

const ThemeInspector: React.FC = () => {
  const { cssVariables, mode } = useTheme();
  return (
    <div>
      <span data-testid="active-mode">{mode}</span>
      <span data-testid="var-bg">{cssVariables["--qb-color-background"]}</span>
      <span data-testid="var-primary">{cssVariables["--qb-color-primary"]}</span>
      <span data-testid="var-font">{cssVariables["--qb-font-family"]}</span>
      <span data-testid="var-radius">{cssVariables["--qb-radius-md"]}</span>
      <span data-testid="var-shadow">{cssVariables["--qb-shadow-sm"]}</span>
    </div>
  );
};

describe("ThemeProvider CSS Variables & Theme Isolation", () => {
  it("themeToCssVariables converts darkTheme tokens into valid --qb-* custom properties", () => {
    const vars = themeToCssVariables(darkTheme);

    expect(vars["--qb-mode"]).toBe("dark");
    expect(vars["--qb-color-background"]).toBe(darkTheme.colors.background);
    expect(vars["--qb-color-primary"]).toBe(darkTheme.colors.primary);
    expect(vars["--qb-color-surface"]).toBe(darkTheme.colors.surface);
    expect(vars["--qb-color-text"]).toBe(darkTheme.colors.text);
    expect(vars["--qb-font-family"]).toBe(darkTheme.typography.fontFamily);
    expect(vars["--qb-font-mono"]).toBe(darkTheme.typography.fontMono);
    expect(vars["--qb-font-size-base"]).toBe(darkTheme.typography.fontSizeBase);
    expect(vars["--qb-radius-md"]).toBe(darkTheme.radii.md);
    expect(vars["--qb-shadow-sm"]).toBe(darkTheme.shadows.sm);
  });

  it("themeToCssVariables converts lightTheme tokens properly", () => {
    const vars = themeToCssVariables(lightTheme);

    expect(vars["--qb-mode"]).toBe("light");
    expect(vars["--qb-color-background"]).toBe(lightTheme.colors.background);
    expect(vars["--qb-color-primary"]).toBe(lightTheme.colors.primary);
  });

  it("ThemeProvider exposes cssVariables in ThemeContextValue", () => {
    render(
      <ThemeProvider mode="dark">
        <ThemeInspector />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("active-mode").textContent).toBe("dark");
    expect(screen.getByTestId("var-bg").textContent).toBe(darkTheme.colors.background);
    expect(screen.getByTestId("var-primary").textContent).toBe(darkTheme.colors.primary);
    expect(screen.getByTestId("var-font").textContent).toBe(darkTheme.typography.fontFamily);
    expect(screen.getByTestId("var-radius").textContent).toBe(darkTheme.radii.md);
  });

  it("customTokens dynamically updates cssVariables in ThemeProvider", () => {
    render(
      <ThemeProvider
        customTokens={{
          colors: {
            primary: "#ff007f",
            background: "#120024",
          },
          radii: {
            md: "18px",
          },
        }}
      >
        <ThemeInspector />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("var-primary").textContent).toBe("#ff007f");
    expect(screen.getByTestId("var-bg").textContent).toBe("#120024");
    expect(screen.getByTestId("var-radius").textContent).toBe("18px");
  });

  it("scopes CSS variables to container [data-qb='root'] without polluting global documentElement", () => {
    const rootStyleBefore = document.documentElement.style.getPropertyValue("--qb-color-primary");

    const { container } = render(
      <ThemeProvider mode="dark">
        <VisualQueryBuilder schema={sampleSchema} initialTable="users" />
      </ThemeProvider>,
    );

    const root = container.querySelector('[data-qb="root"]');
    expect(root).not.toBeNull();

    // Verify container has scoped CSS variable
    const inlineStyle = root?.getAttribute("style");
    expect(inlineStyle).toContain("--qb-color-primary");
    expect(inlineStyle).toContain("--qb-color-background");

    // Verify global document root is not polluted
    const rootStyleAfter = document.documentElement.style.getPropertyValue("--qb-color-primary");
    expect(rootStyleAfter).toBe(rootStyleBefore);
    expect(rootStyleAfter).toBe("");
  });
});
