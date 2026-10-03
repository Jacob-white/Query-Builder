import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import {
  type QueryBuilderTheme,
  type DeepPartial,
  darkTheme,
  lightTheme,
  mergeTheme,
} from "./tokens";

export interface ThemeProviderProps {
  theme?: QueryBuilderTheme;
  mode?: "dark" | "light";
  customTokens?: DeepPartial<QueryBuilderTheme>;
  children: React.ReactNode;
}

export interface ThemeContextValue {
  theme: QueryBuilderTheme;
  mode: "dark" | "light";
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
    (explicitTheme?: QueryBuilderTheme, explicitMode?: "dark" | "light"): QueryBuilderTheme => {
      let base: QueryBuilderTheme;
      if (explicitTheme) {
        base = explicitTheme;
      } else {
        const activeMode = explicitMode || "dark";
        base = activeMode === "light" ? lightTheme : darkTheme;
      }
      return customTokens ? mergeTheme(base, customTokens) : base;
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
      setActiveTheme((prev) => {
        const base = newMode === "light" ? lightTheme : darkTheme;
        return customTokens ? mergeTheme(base, customTokens) : base;
      });
    },
    [customTokens],
  );

  const toggleMode = useCallback(() => {
    setActiveTheme((prev) => {
      const nextMode = prev.mode === "dark" ? "light" : "dark";
      const base = nextMode === "light" ? lightTheme : darkTheme;
      return customTokens ? mergeTheme(base, customTokens) : base;
    });
  }, [customTokens]);

  const setTheme = useCallback((newTheme: QueryBuilderTheme) => {
    setActiveTheme(newTheme);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme: activeTheme,
      mode: activeTheme.mode,
      setTheme,
      setMode,
      toggleMode,
    }),
    [activeTheme, setTheme, setMode, toggleMode],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const useTheme = (): ThemeContextValue => {
  const context = useContext(ThemeContext);
  if (!context) {
    return {
      theme: darkTheme,
      mode: "dark",
      setTheme: () => {},
      setMode: () => {},
      toggleMode: () => {},
    };
  }
  return context;
};
