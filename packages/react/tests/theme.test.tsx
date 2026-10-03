import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import {
  darkTheme,
  lightTheme,
  mergeTheme,
  ThemeProvider,
  useTheme,
  VisualQueryBuilder,
  type QueryBuilderTheme,
} from "../src/index";

describe("Theme Tokens & Utilities", () => {
  it("provides valid darkTheme and lightTheme specifications", () => {
    expect(darkTheme.mode).toBe("dark");
    expect(darkTheme.colors.background).toBe("#090d16");
    expect(darkTheme.colors.primary).toBe("#3b82f6");
    expect(darkTheme.typography.fontFamily).toContain("system-ui");
    expect(darkTheme.radii.md).toBe("8px");
    expect(darkTheme.shadows.md).toBeDefined();

    expect(lightTheme.mode).toBe("light");
    expect(lightTheme.colors.background).toBe("#f8fafc");
    expect(lightTheme.colors.primary).toBe("#2563eb");
    expect(lightTheme.typography.fontFamily).toContain("system-ui");
    expect(lightTheme.radii.md).toBe("8px");
    expect(lightTheme.shadows.md).toBeDefined();
  });

  it("mergeTheme creates deep clone when overrides are omitted or empty", () => {
    const cloned = mergeTheme(darkTheme);
    expect(cloned).toEqual(darkTheme);
    expect(cloned).not.toBe(darkTheme);

    const emptyOverrides = mergeTheme(darkTheme, {});
    expect(emptyOverrides.colors.primary).toBe(darkTheme.colors.primary);
  });

  it("mergeTheme properly applies partial color, typography, radii, and shadow overrides", () => {
    const custom = mergeTheme(darkTheme, {
      mode: "light",
      colors: {
        primary: "#10b981",
        surface: "#112233",
      },
      typography: {
        fontSizeBase: "1rem",
      },
      radii: {
        md: "12px",
      },
      shadows: {
        lg: "0 10px 20px rgba(0,0,0,0.5)",
      },
    });

    expect(custom.mode).toBe("light");
    expect(custom.colors.primary).toBe("#10b981");
    expect(custom.colors.surface).toBe("#112233");
    expect(custom.colors.background).toBe(darkTheme.colors.background);
    expect(custom.typography.fontSizeBase).toBe("1rem");
    expect(custom.radii.md).toBe("12px");
    expect(custom.shadows.lg).toBe("0 10px 20px rgba(0,0,0,0.5)");
  });
});

describe("ThemeProvider & useTheme Hook", () => {
  const ThemeConsumer: React.FC = () => {
    const { theme, mode, setMode, toggleMode, setTheme } = useTheme();

    return (
      <div>
        <span data-testid="mode">{mode}</span>
        <span data-testid="bg">{theme.colors.background}</span>
        <span data-testid="primary">{theme.colors.primary}</span>
        <button type="button" onClick={() => setMode("light")}>
          Set Light
        </button>
        <button type="button" onClick={() => setMode("dark")}>
          Set Dark
        </button>
        <button type="button" onClick={toggleMode}>
          Toggle
        </button>
        <button
          type="button"
          onClick={() =>
            setTheme({
              ...theme,
              colors: { ...theme.colors, primary: "#ff0077" },
            })
          }
        >
          Set Custom
        </button>
      </div>
    );
  };

  it("falls back to default darkTheme when used outside ThemeProvider", () => {
    render(<ThemeConsumer />);
    expect(screen.getByTestId("mode").textContent).toBe("dark");
    expect(screen.getByTestId("bg").textContent).toBe(darkTheme.colors.background);

    // Invoking fallback no-op functions does not crash
    act(() => {
      screen.getByText("Set Light").click();
      screen.getByText("Toggle").click();
      screen.getByText("Set Custom").click();
    });
    expect(screen.getByTestId("mode").textContent).toBe("dark");
  });

  it("provides darkTheme by default inside ThemeProvider", () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("mode").textContent).toBe("dark");
    expect(screen.getByTestId("bg").textContent).toBe(darkTheme.colors.background);
  });

  it("supports mode='light' prop and dynamic toggling", () => {
    render(
      <ThemeProvider mode="light">
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("mode").textContent).toBe("light");
    expect(screen.getByTestId("bg").textContent).toBe(lightTheme.colors.background);

    // Toggle to dark
    act(() => {
      screen.getByText("Toggle").click();
    });
    expect(screen.getByTestId("mode").textContent).toBe("dark");

    // Toggle back to light
    act(() => {
      screen.getByText("Toggle").click();
    });
    expect(screen.getByTestId("mode").textContent).toBe("light");

    // Set to dark
    act(() => {
      screen.getByText("Set Dark").click();
    });
    expect(screen.getByTestId("mode").textContent).toBe("dark");

    // Set to light
    act(() => {
      screen.getByText("Set Light").click();
    });
    expect(screen.getByTestId("mode").textContent).toBe("light");
  });

  it("merges customTokens prop onto active theme", () => {
    render(
      <ThemeProvider customTokens={{ colors: { primary: "#abcdef" } }}>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("primary").textContent).toBe("#abcdef");

    // Toggling mode preserves custom tokens
    act(() => {
      screen.getByText("Toggle").click();
    });
    expect(screen.getByTestId("primary").textContent).toBe("#abcdef");
    expect(screen.getByTestId("mode").textContent).toBe("light");

    act(() => {
      screen.getByText("Set Dark").click();
    });
    expect(screen.getByTestId("primary").textContent).toBe("#abcdef");
  });

  it("supports explicit custom theme prop and setTheme action", () => {
    const customTheme: QueryBuilderTheme = {
      ...darkTheme,
      colors: { ...darkTheme.colors, background: "#123456", primary: "#654321" },
    };

    const { rerender } = render(
      <ThemeProvider theme={customTheme}>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("bg").textContent).toBe("#123456");
    expect(screen.getByTestId("primary").textContent).toBe("#654321");

    // Dynamic setTheme
    act(() => {
      screen.getByText("Set Custom").click();
    });
    expect(screen.getByTestId("primary").textContent).toBe("#ff0077");

    // Rerender with customTokens and theme
    rerender(
      <ThemeProvider theme={customTheme} customTokens={{ colors: { primary: "#999999" } }}>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("primary").textContent).toBe("#999999");
  });

  it("updates when mode prop changes dynamically", () => {
    const { rerender } = render(
      <ThemeProvider mode="dark">
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("mode").textContent).toBe("dark");

    rerender(
      <ThemeProvider mode="light">
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("mode").textContent).toBe("light");
  });

  it("VisualQueryBuilder applies theme prop as string ('light' or 'dark') and as theme object", () => {
    const { rerender } = render(<VisualQueryBuilder theme="light" />);
    expect(screen.getByRole("tablist")).toBeDefined();

    rerender(<VisualQueryBuilder theme="dark" />);
    expect(screen.getByRole("tablist")).toBeDefined();

    const customThemeObj: QueryBuilderTheme = {
      ...darkTheme,
      colors: { ...darkTheme.colors, background: "#223344" },
    };
    rerender(<VisualQueryBuilder theme={customThemeObj} />);
    expect(screen.getByRole("tablist")).toBeDefined();
  });
});
