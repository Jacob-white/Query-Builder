import { useMemo } from "react";
import type React from "react";
import { useTheme } from "../../theme/ThemeProvider";
import {
  darkTheme,
  lightTheme,
  themeToCssVariables,
  type QueryBuilderTheme,
} from "../../theme/tokens";

export type ThemeProp = "dark" | "light" | "auto" | QueryBuilderTheme | undefined;

/** Resolves the effective theme (prop, else context) and its CSS custom properties. */
export function useBuilderTheme(propTheme: ThemeProp, unstyled: boolean) {
  const { theme: contextTheme } = useTheme();

  const activeTheme: QueryBuilderTheme = useMemo(() => {
    if (propTheme && typeof propTheme === "object" && "colors" in propTheme) {
      return propTheme as QueryBuilderTheme;
    }
    if (propTheme === "light") return lightTheme;
    if (propTheme === "dark") return darkTheme;
    return contextTheme;
  }, [propTheme, contextTheme]);

  const cssVars = useMemo<Record<string, string>>(
    () => (unstyled ? {} : themeToCssVariables(activeTheme)),
    [activeTheme, unstyled],
  );

  return { activeTheme, cssVars };
}

/** Inline style of the builder root (undefined when unstyled). */
export function rootStyle(
  theme: QueryBuilderTheme,
  cssVars: Record<string, string>,
  unstyled: boolean,
): React.CSSProperties | undefined {
  if (unstyled) return undefined;
  return {
    ...(cssVars as unknown as React.CSSProperties),
    display: "flex",
    flexDirection: "column",
    gap: "14px",
    background: theme.colors.background,
    color: theme.colors.text,
    borderRadius: theme.radii.xl,
    border: `1px solid ${theme.colors.border}`,
    padding: "16px",
    fontFamily: theme.typography.fontFamily,
  };
}
