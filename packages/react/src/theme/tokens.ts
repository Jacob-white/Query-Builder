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
    surface: "#1e293b",
    surfaceHover: "#334155",
    surfaceActive: "#475569",
    border: "rgba(255, 255, 255, 0.1)",
    borderFocus: "#3b82f6",
    text: "#f8fafc",
    textMuted: "#94a3b8",
    textSecondary: "#cbd5e1",
    primary: "#3b82f6",
    primaryHover: "#2563eb",
    primaryLight: "rgba(59, 130, 246, 0.15)",
    success: "#10b981",
    successLight: "rgba(16, 185, 129, 0.15)",
    warning: "#f59e0b",
    warningLight: "rgba(245, 158, 11, 0.15)",
    error: "#ef4444",
    errorLight: "rgba(239, 68, 68, 0.15)",
    accent: "#8b5cf6",
  },
  typography: {
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontMono: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSizeXs: "0.75rem",
    fontSizeSm: "0.82rem",
    fontSizeBase: "0.88rem",
    fontSizeLg: "1rem",
    fontSizeXl: "1.2rem",
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
    xl: "14px",
    full: "9999px",
  },
  shadows: {
    sm: "0 1px 2px rgba(0, 0, 0, 0.2)",
    md: "0 4px 6px rgba(0, 0, 0, 0.3)",
    lg: "0 10px 15px rgba(0, 0, 0, 0.4)",
    xl: "0 20px 25px rgba(0, 0, 0, 0.5)",
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
    accent: "#7c3aed",
  },
  typography: {
    fontFamily: "system-ui, -apple-system, sans-serif",
    fontMono: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSizeXs: "0.75rem",
    fontSizeSm: "0.82rem",
    fontSizeBase: "0.88rem",
    fontSizeLg: "1rem",
    fontSizeXl: "1.2rem",
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
    xl: "14px",
    full: "9999px",
  },
  shadows: {
    sm: "0 1px 2px rgba(0, 0, 0, 0.05)",
    md: "0 4px 6px rgba(0, 0, 0, 0.08)",
    lg: "0 10px 15px rgba(0, 0, 0, 0.1)",
    xl: "0 20px 25px rgba(0, 0, 0, 0.12)",
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
  const vars: Record<string, string> = {
    "--qb-mode": theme.mode,
  };

  if (theme.colors) {
    for (const [key, value] of Object.entries(theme.colors)) {
      if (value !== undefined && value !== null) {
        vars[`--qb-color-${camelToKebab(key)}`] = String(value);
      }
    }
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

