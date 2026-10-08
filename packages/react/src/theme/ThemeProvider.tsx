import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from "react";
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
  // Latest props live in refs so inline `theme` / `customTokens` objects (new identity every
  // render) neither churn callbacks nor revert a mode picked via setMode/toggleMode.
  const propsRef = useRef({ propTheme, customTokens });
  useEffect(() => {
    propsRef.current = { propTheme, customTokens };
  });
  // Mode picked through setMode/toggleMode; survives theme/token prop changes until `mode` prop changes.
  const userModeRef = useRef<"dark" | "light" | undefined>(undefined);
  const currentModeRef = useRef<"dark" | "light">("dark");

  const computeTheme = useCallback(
    (explicitMode?: "dark" | "light"): QueryBuilderTheme => {
      const { propTheme: explicitTheme, customTokens: tokens } = propsRef.current;
      const activeMode =
        explicitMode || (explicitTheme as Partial<QueryBuilderTheme> | undefined)?.mode || "dark";
      const fallback = activeMode === "light" ? lightTheme : darkTheme;
      const base: QueryBuilderTheme = explicitTheme
        ? mergeTheme(fallback, explicitTheme as DeepPartial<QueryBuilderTheme>)
        : fallback;
      const withTokens = tokens ? mergeTheme(base, tokens) : base;
      return {
        ...withTokens,
        mode: activeMode,
      };
    },
    [],
  );

  const [activeTheme, setActiveTheme] = useState<QueryBuilderTheme>(() => computeTheme(propMode));

  // Re-sync when theme/tokens/mode props change by value (JSON key). If a prop can't be
  // serialized, fall back to comparing identities so changes are still picked up.
  const propsKey = useMemo(() => {
    try {
      // Replacer keeps functions, undefined and non-finite numbers distinguishable.
      return JSON.stringify([propTheme ?? null, customTokens ?? null, propMode ?? null], (_k, v) =>
        typeof v === "function"
          ? `fn:${v.toString()}`
          : v === undefined
            ? "__undefined__"
            : typeof v === "number" && !Number.isFinite(v)
              ? `num:${String(v)}`
              : v,
      );
    } catch {
      return null;
    }
  }, [propTheme, customTokens, propMode]);
  const lastSyncRef = useRef({ key: propsKey, propTheme, customTokens, propMode });
  useEffect(() => {
    const last = lastSyncRef.current;
    const unchanged =
      propsKey !== null && last.key !== null
        ? propsKey === last.key
        : last.propTheme === propTheme &&
          last.customTokens === customTokens &&
          last.propMode === propMode;
    if (unchanged) return;
    if (last.propMode !== propMode) userModeRef.current = undefined;
    lastSyncRef.current = { key: propsKey, propTheme, customTokens, propMode };
    propsRef.current = { propTheme, customTokens };
    setActiveTheme(computeTheme(userModeRef.current ?? propMode));
  }, [propsKey, propTheme, customTokens, propMode, computeTheme]);

  const setMode = useCallback(
    (newMode: "dark" | "light") => {
      userModeRef.current = newMode;
      setActiveTheme(computeTheme(newMode));
    },
    [computeTheme],
  );

  const toggleMode = useCallback(() => {
    // Read the committed mode instead of mutating refs inside a state updater (updaters
    // must be pure; React may invoke them twice in StrictMode).
    const next = currentModeRef.current === "dark" ? "light" : "dark";
    userModeRef.current = next;
    setActiveTheme(computeTheme(next));
  }, [computeTheme]);

  const setTheme = useCallback((newTheme: QueryBuilderTheme) => {
    userModeRef.current = newTheme.mode;
    setActiveTheme(newTheme);
  }, []);

  useEffect(() => {
    currentModeRef.current = activeTheme.mode;
  }, [activeTheme.mode]);

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
