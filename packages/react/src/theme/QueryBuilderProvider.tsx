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
  FeatureConfig,
  FeaturePreset,
  FeatureKey,
  ResolvedFeatureMap,
} from "../types";
import { resolveFeatureConfig, isFeatureVisible as checkFeatureVisible } from "../utils/featureUtils";

export interface QueryBuilderContextValue {
  mode: "styled" | "unstyled";
  customOperators?: Record<string, CustomFilterOperator>;
  fieldRenderers?: Record<string, CustomFieldRenderer>;
  cellRenderers?: Record<string, (value: any, row: any, column: string) => React.ReactNode>;
  onExecuteQuery?: (sql: string, spec?: Record<string, unknown>) => Promise<QueryResultData> | void;
  isAdvancedMode?: boolean;
  setIsAdvancedMode?: (isAdvanced: boolean) => void;
  features?: ResolvedFeatureMap;
  isFeatureVisible?: (feature: FeatureKey) => boolean;
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
  features?: FeatureConfig;
  featurePreset?: FeaturePreset;
  isAdvancedMode?: boolean;
  defaultAdvancedMode?: boolean;
  onAdvancedModeChange?: (isAdvanced: boolean) => void;
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
  features,
  featurePreset,
  isAdvancedMode: propAdvancedMode,
  defaultAdvancedMode,
  onAdvancedModeChange,
  children,
}) => {
  const parentContext = useContext(QueryBuilderContext);
  const [internalAdvanced, setInternalAdvanced] = React.useState<boolean>(() => {
    if (propAdvancedMode !== undefined) return propAdvancedMode;
    if (defaultAdvancedMode !== undefined) return defaultAdvancedMode;
    return false;
  });

  const effectiveAdvanced =
    propAdvancedMode !== undefined ? propAdvancedMode : (parentContext?.isAdvancedMode ?? internalAdvanced);

  const handleSetAdvanced = (val: boolean) => {
    setInternalAdvanced(val);
    onAdvancedModeChange?.(val);
    parentContext?.setIsAdvancedMode?.(val);
  };

  const resolvedFeatures = useMemo(() => {
    return resolveFeatureConfig(features, featurePreset, parentContext?.features as any);
  }, [features, featurePreset, parentContext?.features]);

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
      isAdvancedMode: effectiveAdvanced,
      setIsAdvancedMode: handleSetAdvanced,
      features: resolvedFeatures,
      isFeatureVisible: (feat: FeatureKey) => checkFeatureVisible(feat, resolvedFeatures, effectiveAdvanced),
    }),
    [
      mode,
      parentContext,
      customOperators,
      fieldRenderers,
      cellRenderers,
      onExecuteQuery,
      effectiveAdvanced,
      resolvedFeatures,
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
