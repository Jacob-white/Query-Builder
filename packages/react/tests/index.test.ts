import { describe, it, expect } from "vitest";
import * as PublicApi from "../src/index";

describe("Public Package API", () => {
  it("exports all components and utility functions correctly", () => {
    expect(PublicApi.VisualQueryBuilder).toBeDefined();
    expect(PublicApi.QueryCanvas).toBeDefined();
    expect(PublicApi.TableCard).toBeDefined();
    expect(PublicApi.TableFiltersEditor).toBeDefined();
    expect(PublicApi.TableJoinEditor).toBeDefined();
    expect(PublicApi.TableSortsEditor).toBeDefined();
    expect(PublicApi.SchemaErdModal).toBeDefined();
    expect(PublicApi.QueryResultsTable).toBeDefined();

    expect(PublicApi.compileVisualState).toBeTypeOf("function");
    expect(PublicApi.validateSqlSafety).toBeTypeOf("function");
    expect(PublicApi.findBestJoinCondition).toBeTypeOf("function");
    expect(PublicApi.findJoinPath).toBeTypeOf("function");
  });
});
