import React, { createContext, useContext, useMemo } from "react";
import { ThemeProvider } from "./ThemeProvider";
import type {
  QueryBuilderTheme,
  DeepPartial,
} from "./tokens";
import type {
  CustomFilterOperator,
  CustomFieldRenderer,
  QueryResultData,
} from "../types";

export interface QueryBuilderContextValue {
  mode: "styled" | "unstyled";
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
}

export const QueryBuilderContext = createContext<QueryBuilderContextValue | null>(null);

export const useQueryBuilderContext = (): QueryBuilderContextValue | null => {
  return useContext(QueryBuilderContext);
};

export interface QueryBuilderProviderProps {
  mode?: "styled" | "unstyled";
  theme?: QueryBuilderTheme | DeepPartial<QueryBuilderTheme>;
  themeMode?: "dark" | "light";
  customTokens?: DeepPartial<QueryBuilderTheme>;
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
  children: React.ReactNode;
}

export const QueryBuilderProvider: React.FC<QueryBuilderProviderProps> = ({
  mode = "styled",
  theme,
  themeMode,
  customTokens,
  customOperators,
  fieldRenderers,
  cellRenderers,
  onExecuteQuery,
  children,
}) => {
  const parentContext = useContext(QueryBuilderContext);

  const value = useMemo<QueryBuilderContextValue>(
    () => ({
      mode: mode ?? parentContext?.mode ?? "styled",
      customOperators: {
        ...(parentContext?.customOperators || {}),
        ...(customOperators || {}),
      },
      fieldRenderers: {
        ...(parentContext?.fieldRenderers || {}),
        ...(fieldRenderers || {}),
      },
      cellRenderers: {
        ...(parentContext?.cellRenderers || {}),
        ...(cellRenderers || {}),
      },
      onExecuteQuery: onExecuteQuery ?? parentContext?.onExecuteQuery,
    }),
    [
      mode,
      parentContext,
      customOperators,
      fieldRenderers,
      cellRenderers,
      onExecuteQuery,
    ],
  );

  const content = (
    <QueryBuilderContext.Provider value={value}>
      {children}
    </QueryBuilderContext.Provider>
  );

  if (value.mode === "styled") {
    return (
      <ThemeProvider
        theme={theme}
        mode={themeMode}
        customTokens={customTokens}
      >
        {content}
      </ThemeProvider>
    );
  }

  return content;
};
