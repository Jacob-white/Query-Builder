/**
 * Design-token theming system for @jacob-white/query-builder-react.
 */

export type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

export interface QueryBuilderThemeColors {
  background: string;
  surface: string;
  surfaceHover: string;
  surfaceActive: string;
  border: string;
  borderFocus: string;
  text: string;
  textMuted: string;
  textSecondary: string;
  primary: string;
  primaryHover: string;
  primaryLight: string;
  success: string;
  successLight: string;
  warning: string;
  warningLight: string;
  error: string;
  errorLight: string;
  accent: string;
}

export interface QueryBuilderThemeTypography {
  fontFamily: string;
  fontMono: string;
  fontSizeXs: string;
  fontSizeSm: string;
  fontSizeBase: string;
  fontSizeLg: string;
  fontSizeXl: string;
  fontWeightNormal: number;
  fontWeightMedium: number;
  fontWeightSemibold: number;
  fontWeightBold: number;
}

export interface QueryBuilderThemeRadii {
  xs: string;
  sm: string;
  md: string;
  lg: string;
  xl: string;
  full: string;
}

export interface QueryBuilderThemeShadows {
  sm: string;
  md: string;
  lg: string;
  xl: string;
}

export interface QueryBuilderTheme {
  mode: "dark" | "light";
  colors: QueryBuilderThemeColors;
  typography: QueryBuilderThemeTypography;
  radii: QueryBuilderThemeRadii;
  shadows: QueryBuilderThemeShadows;
}

export const darkTheme: QueryBuilderTheme = {
  mode: "dark",
  colors: {
    background: "#090d16",
    surface: "#10141f",
    surfaceHover: "#161b28",
    surfaceActive: "#1c2232",
    border: "rgba(255, 255, 255, 0.07)",
    borderFocus: "#3b82f6",
    text: "#e2e8f0",
    textMuted: "#64748b",
    textSecondary: "#94a3b8",
    primary: "#3b82f6",
    primaryHover: "#2563eb",
    primaryLight: "rgba(59, 130, 246, 0.1)",
    success: "#10b981",
    successLight: "rgba(16, 185, 129, 0.1)",
    warning: "#d97706",
    warningLight: "rgba(217, 119, 6, 0.1)",
    error: "#ef4444",
    errorLight: "rgba(239, 68, 68, 0.1)",
    accent: "#64748b",
  },
  typography: {
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontMono: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSizeXs: "0.8rem",
    fontSizeSm: "0.875rem",
    fontSizeBase: "0.9375rem",
    fontSizeLg: "1.0625rem",
    fontSizeXl: "1.25rem",
    fontWeightNormal: 400,
    fontWeightMedium: 500,
    fontWeightSemibold: 600,
    fontWeightBold: 700,
  },
  radii: {
    xs: "4px",
    sm: "6px",
    md: "8px",
    lg: "10px",
    xl: "12px",
    full: "9999px",
  },
  shadows: {
    sm: "0 1px 2px rgba(0, 0, 0, 0.16)",
    md: "0 2px 6px rgba(0, 0, 0, 0.22)",
    lg: "0 6px 16px rgba(0, 0, 0, 0.28)",
    xl: "0 12px 24px rgba(0, 0, 0, 0.36)",
  },
};

export const lightTheme: QueryBuilderTheme = {
  mode: "light",
  colors: {
    background: "#f8fafc",
    surface: "#ffffff",
    surfaceHover: "#f1f5f9",
    surfaceActive: "#e2e8f0",
    border: "#cbd5e1",
    borderFocus: "#2563eb",
    text: "#0f172a",
    textMuted: "#64748b",
    textSecondary: "#334155",
    primary: "#2563eb",
    primaryHover: "#1d4ed8",
    primaryLight: "rgba(37, 99, 235, 0.1)",
    success: "#059669",
    successLight: "rgba(5, 150, 105, 0.1)",
    warning: "#d97706",
    warningLight: "rgba(217, 119, 6, 0.1)",
    error: "#dc2626",
    errorLight: "rgba(220, 38, 38, 0.1)",
    accent: "#475569",
  },
  typography: {
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontMono: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSizeXs: "0.8rem",
    fontSizeSm: "0.875rem",
    fontSizeBase: "0.9375rem",
    fontSizeLg: "1.0625rem",
    fontSizeXl: "1.25rem",
    fontWeightNormal: 400,
    fontWeightMedium: 500,
    fontWeightSemibold: 600,
    fontWeightBold: 700,
  },
  radii: {
    xs: "4px",
    sm: "6px",
    md: "8px",
    lg: "10px",
    xl: "12px",
    full: "9999px",
  },
  shadows: {
    sm: "0 1px 2px rgba(0, 0, 0, 0.04)",
    md: "0 2px 6px rgba(0, 0, 0, 0.06)",
    lg: "0 6px 14px rgba(0, 0, 0, 0.08)",
    xl: "0 12px 24px rgba(0, 0, 0, 0.1)",
  },
};

/**
 * Deep merges theme overrides into a base theme and returns a new theme object.
 */
export function mergeTheme(
  base: QueryBuilderTheme,
  overrides?: DeepPartial<QueryBuilderTheme>,
): QueryBuilderTheme {
  if (!overrides) {
    return JSON.parse(JSON.stringify(base));
  }
  return {
    mode: overrides.mode ?? base.mode,
    colors: {
      ...base.colors,
      ...(overrides.colors || {}),
    },
    typography: {
      ...base.typography,
      ...(overrides.typography || {}),
    },
    radii: {
      ...base.radii,
      ...(overrides.radii || {}),
    },
    shadows: {
      ...base.shadows,
      ...(overrides.shadows || {}),
    },
  };
}

function camelToKebab(str: string): string {
  return str.replace(/([A-Z])/g, "-$1").toLowerCase();
}

/**
 * Converts a QueryBuilderTheme into scoped CSS custom properties (--qb-*).
 */
export function themeToCssVariables(theme: QueryBuilderTheme): Record<string, string> {
  const isLight = theme.mode === "light";
  const vars: Record<string, string> = {
    "--qb-mode": theme.mode,
    "--qb-color-active-text": isLight ? "#0369a1" : "#e0f2fe",
    "--qb-color-active-bg": isLight ? "rgba(2, 132, 199, 0.12)" : "rgba(56, 189, 248, 0.16)",
    "--qb-color-active-border": isLight ? "rgba(2, 132, 199, 0.42)" : "rgba(56, 189, 248, 0.45)",
    "--qb-color-confirmed-text": isLight ? "#047857" : "#6ee7b7",
    "--qb-color-confirmed-bg": isLight ? "rgba(5, 150, 105, 0.12)" : "rgba(16, 185, 129, 0.14)",
    "--qb-color-confirmed-border": isLight ? "rgba(5, 150, 105, 0.4)" : "rgba(16, 185, 129, 0.38)",
    "--qb-color-logical-text": isLight ? "#1d4ed8" : "#93c5fd",
    "--qb-color-logical-bg": isLight ? "rgba(37, 99, 235, 0.1)" : "rgba(59, 130, 246, 0.14)",
    "--qb-color-logical-border": isLight ? "rgba(37, 99, 235, 0.38)" : "rgba(59, 130, 246, 0.38)",
    "--qb-color-none-text": isLight ? "#475569" : "#94a3b8",
    "--qb-color-none-bg": isLight ? "rgba(100, 116, 139, 0.1)" : "rgba(148, 163, 184, 0.1)",
    "--qb-color-none-border": isLight ? "rgba(100, 116, 139, 0.32)" : "rgba(148, 163, 184, 0.25)",
    "--qb-color-warn-text": isLight ? "#b45309" : "#fde047",
    "--qb-color-warn-bg": isLight ? "rgba(217, 119, 6, 0.12)" : "rgba(245, 158, 11, 0.15)",
    "--qb-color-warn-border": isLight ? "rgba(217, 119, 6, 0.38)" : "rgba(245, 158, 11, 0.38)",
    "--qb-color-suggested-text": isLight ? "#b45309" : "#fde047",
    "--qb-color-suggested-bg": isLight ? "rgba(217, 119, 6, 0.12)" : "rgba(245, 158, 11, 0.15)",
    "--qb-color-suggested-border": isLight ? "rgba(217, 119, 6, 0.38)" : "rgba(245, 158, 11, 0.38)",
    "--qb-color-custom-text": isLight ? "#6d28d9" : "#d8b4fe",
    "--qb-color-custom-bg": isLight ? "rgba(124, 58, 237, 0.12)" : "rgba(168, 85, 247, 0.15)",
    "--qb-color-custom-border": isLight ? "rgba(124, 58, 237, 0.38)" : "rgba(168, 85, 247, 0.38)",
  };

  if (theme.colors) {
    for (const [key, value] of Object.entries(theme.colors)) {
      if (value !== undefined && value !== null) {
        vars[`--qb-color-${camelToKebab(key)}`] = String(value);
      }
    }
    vars["--qb-bg-surface"] = String(theme.colors.surface);
    vars["--qb-bg-canvas"] = String(theme.colors.background);
    vars["--qb-bg-primary"] = String(theme.colors.surface);
    vars["--qb-bg-secondary"] = String(theme.colors.background);
    vars["--qb-border-subtle"] = String(theme.colors.border);
    vars["--qb-border-color"] = String(theme.colors.border);
    vars["--qb-text-primary"] = String(theme.colors.text);
    vars["--qb-text-secondary"] = String(theme.colors.textSecondary);
    vars["--qb-primary"] = String(theme.colors.primary);
    vars["--qb-accent-color"] = String(theme.colors.primary);
  }

  if (theme.typography) {
    for (const [key, value] of Object.entries(theme.typography)) {
      if (value !== undefined && value !== null) {
        vars[`--qb-${camelToKebab(key)}`] = String(value);
      }
    }
  }

  if (theme.radii) {
    for (const [key, value] of Object.entries(theme.radii)) {
      if (value !== undefined && value !== null) {
        vars[`--qb-radius-${camelToKebab(key)}`] = String(value);
      }
    }
  }

  if (theme.shadows) {
    for (const [key, value] of Object.entries(theme.shadows)) {
      if (value !== undefined && value !== null) {
        vars[`--qb-shadow-${camelToKebab(key)}`] = String(value);
      }
    }
  }

  return vars;
}

