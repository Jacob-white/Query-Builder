import { describe, it, expect } from "vitest";
import * as PublicApi from "../src/index";

describe("Public Package API", () => {
  it("exports all components, hooks, theming, and utility functions correctly", () => {
    // Existing components
    expect(PublicApi.VisualQueryBuilder).toBeDefined();
    expect(PublicApi.QueryCanvas).toBeDefined();
    expect(PublicApi.TableCard).toBeDefined();
    expect(PublicApi.TableFiltersEditor).toBeDefined();
    expect(PublicApi.TableJoinEditor).toBeDefined();
    expect(PublicApi.TableSortsEditor).toBeDefined();
    expect(PublicApi.SchemaErdModal).toBeDefined();
    expect(PublicApi.QueryResultsTable).toBeDefined();
    expect(PublicApi.QueryChartPreview).toBeDefined();
    expect(PublicApi.QueryTemplateManager).toBeDefined();

    // M3 Components & Playground
    expect(PublicApi.ComponentShowcase).toBeDefined();
    expect(PublicApi.QueryPlayground).toBeDefined();

    // Headless Hooks
    expect(PublicApi.useQueryBuilder).toBeTypeOf("function");
    expect(PublicApi.useQueryState).toBeTypeOf("function");
    expect(PublicApi.useSqlCompiler).toBeTypeOf("function");
    expect(PublicApi.useQueryExecution).toBeTypeOf("function");
    expect(PublicApi.useSchemaIntrospection).toBeTypeOf("function");
    expect(PublicApi.stateToSpec).toBeTypeOf("function");
    expect(PublicApi.specToState).toBeTypeOf("function");

    // Theming System
    expect(PublicApi.darkTheme).toBeDefined();
    expect(PublicApi.lightTheme).toBeDefined();
    expect(PublicApi.mergeTheme).toBeTypeOf("function");
    expect(PublicApi.ThemeProvider).toBeDefined();
    expect(PublicApi.useTheme).toBeTypeOf("function");
    expect(PublicApi.ThemeContext).toBeDefined();

    // Utility functions
    expect(PublicApi.compileVisualState).toBeTypeOf("function");
    expect(PublicApi.validateSqlSafety).toBeTypeOf("function");
    expect(PublicApi.findBestJoinCondition).toBeTypeOf("function");
    expect(PublicApi.findJoinPath).toBeTypeOf("function");
    expect(PublicApi.isSchemaSnapshot).toBeTypeOf("function");
    expect(PublicApi.normalizeSchema).toBeTypeOf("function");
  });
});
