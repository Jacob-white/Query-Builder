import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import {
  type QueryBuilderTheme,
  type DeepPartial,
  darkTheme,
  lightTheme,
  mergeTheme,
  themeToCssVariables,
} from "./tokens";

export interface ThemeProviderProps {
  theme?: QueryBuilderTheme | DeepPartial<QueryBuilderTheme>;
  mode?: "dark" | "light";
  customTokens?: DeepPartial<QueryBuilderTheme>;
  children: React.ReactNode;
}

export interface ThemeContextValue {
  theme: QueryBuilderTheme;
  mode: "dark" | "light";
  cssVariables: Record<string, string>;
  setTheme: (theme: QueryBuilderTheme) => void;
  setMode: (mode: "dark" | "light") => void;
  toggleMode: () => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export const ThemeProvider: React.FC<ThemeProviderProps> = ({
  theme: propTheme,
  mode: propMode,
  customTokens,
  children,
}) => {
  const computeTheme = useCallback(
    (explicitTheme?: QueryBuilderTheme | DeepPartial<QueryBuilderTheme>, explicitMode?: "dark" | "light"): QueryBuilderTheme => {
      const activeMode = explicitMode || "dark";
      const fallback = activeMode === "light" ? lightTheme : darkTheme;
      const base: QueryBuilderTheme = explicitTheme
        ? mergeTheme(fallback, explicitTheme as DeepPartial<QueryBuilderTheme>)
        : fallback;
      const withTokens = customTokens ? mergeTheme(base, customTokens) : base;
      return {
        ...withTokens,
        mode: activeMode,
      };
    },
    [customTokens],
  );

  const [activeTheme, setActiveTheme] = useState<QueryBuilderTheme>(() =>
    computeTheme(propTheme, propMode),
  );

  useEffect(() => {
    setActiveTheme(computeTheme(propTheme, propMode));
  }, [propTheme, propMode, computeTheme]);

  const setMode = useCallback(
    (newMode: "dark" | "light") => {
      setActiveTheme(computeTheme(propTheme, newMode));
    },
    [computeTheme, propTheme],
  );

  const toggleMode = useCallback(() => {
    setActiveTheme((prev) => {
      const nextMode = prev.mode === "dark" ? "light" : "dark";
      return computeTheme(propTheme, nextMode);
    });
  }, [computeTheme, propTheme]);

  const setTheme = useCallback((newTheme: QueryBuilderTheme) => {
    setActiveTheme(newTheme);
  }, []);

  const cssVariables = useMemo(() => themeToCssVariables(activeTheme), [activeTheme]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: activeTheme,
      mode: activeTheme.mode,
      cssVariables,
      setTheme,
      setMode,
      toggleMode,
    }),
    [activeTheme, cssVariables, setTheme, setMode, toggleMode],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const useTheme = (): ThemeContextValue => {
  const context = useContext(ThemeContext);
  if (!context) {
    return {
      theme: darkTheme,
      mode: "dark",
      cssVariables: themeToCssVariables(darkTheme),
      setTheme: () => {},
      setMode: () => {},
      toggleMode: () => {},
    };
  }
  return context;
};
