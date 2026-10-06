/**
 * Agent Tool Calling Definitions & Universal Execution for React / Browser / Node AI agents.
 */

import type { ByoAiToolFormat } from "./types";
import type { QuerySpec } from "../types";
import { parseSqlToSpec } from "../utils/sqlParser";
import { compileSpecToSql } from "../utils/compiler";
import { autoHealClientQuerySpec } from "./selfHealing";

export const REACT_AGENT_TOOL_SCHEMAS = [
  {
    name: "build_query",
    description:
      "Translates a natural language data request into a validated visual QuerySpec AST and SQL query.",
    parameters: {
      type: "object",
      properties: {
        intent: {
          type: "string",
          description: "The plain-English query request (e.g. 'Show top 10 users by order count').",
        },
        dialect: {
          type: "string",
          description: "Target SQL dialect. Defaults to 'postgres'.",
        },
        limit: {
          type: "integer",
          description: "Max rows to return (default: 50).",
        },
      },
      required: ["intent"],
    },
  },
  {
    name: "validate_and_compile_query",
    description: "Validates a QuerySpec AST or SQL query and compiles it into target dialect SQL.",
    parameters: {
      type: "object",
      properties: {
        spec: {
          type: "object",
          description: "QuerySpec AST dictionary.",
        },
        sql: {
          type: "string",
          description: "Raw SQL query string.",
        },
        dialect: {
          type: "string",
          description: "Target SQL dialect.",
        },
      },
    },
  },
  {
    name: "get_schema_catalog",
    description: "Retrieves the active database schema catalog formatted for LLM prompts.",
    parameters: {
      type: "object",
      properties: {
        tables: {
          type: "array",
          items: { type: "string" },
          description: "Optional list of tables to filter.",
        },
        format: {
          type: "string",
          enum: ["markdown", "json"],
          description: "Output format ('markdown' or 'json').",
        },
      },
    },
  },
  {
    name: "explain_query",
    description: "Generates a plain-English explanation of a QuerySpec or SQL query.",
    parameters: {
      type: "object",
      properties: {
        spec: { type: "object", description: "QuerySpec AST." },
        sql: { type: "string", description: "Raw SQL query string." },
      },
    },
  },
];

export function getAgentToolDefinitions(
  format: ByoAiToolFormat = "openai",
  _schema?: any
): any[] {
  const fmt = format.toLowerCase().trim();
  const tools = REACT_AGENT_TOOL_SCHEMAS;

  switch (fmt) {
    case "openai":
      return tools.map((t) => ({
        type: "function",
        function: {
          name: t.name,
          description: t.description,
          parameters: t.parameters,
        },
      }));
    case "anthropic":
      return tools.map((t) => ({
        name: t.name,
        description: t.description,
        input_schema: t.parameters,
      }));
    case "gemini":
      return tools.map((t) => ({
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      }));
    case "langchain":
      return tools.map((t) => ({
        name: t.name,
        description: t.description,
        args_schema: t.parameters,
      }));
    case "mcp":
      return tools.map((t) => ({
        name: t.name,
        description: t.description,
        inputSchema: t.parameters,
      }));
    default:
      throw new Error(
        `Unsupported agent tool format '${format}'. Supported: 'openai', 'anthropic', 'gemini', 'langchain', 'mcp'.`
      );
  }
}

export interface ExecuteAgentToolOptions {
  schema?: any;
  dialect?: string;
  onCompile?: (spec: QuerySpec, dialect: string) => string;
}

export function executeAgentToolCall(
  toolName: string,
  args: Record<string, any> | string,
  options: ExecuteAgentToolOptions = {}
): Record<string, any> {
  const parsedArgs = typeof args === "string" ? JSON.parse(args) : args;
  const dialect = options.dialect || "postgres";
  const schema = options.schema;

  if (toolName === "build_query") {
    const intent = parsedArgs.intent;
    if (!intent) {
      return { success: false, error: "Missing required argument 'intent'." };
    }
    const targetDialect = parsedArgs.dialect || dialect;
    const limit = parsedArgs.limit || 50;

    // Build default query spec from intent
    const words = intent.toLowerCase().replace(/[^a-z0-9_\s]/g, "").split(/\s+/);
    let matchedTable = "users";
    if (schema) {
      const tableNames = Array.isArray(schema)
        ? schema.map((t: any) => t.name)
        : schema.tables
        ? Object.keys(schema.tables)
        : Object.keys(schema);

      const found = tableNames.find((t: string) => words.includes(t.toLowerCase()));
      if (found) matchedTable = found;
    }

    const spec: QuerySpec = {
      table: matchedTable,
      columns: ["*"],
      joins: [],
      filters: [],
      filter_join: "AND",
      order_by: [],
      distinct: false,
      limit,
    };

    const sql = options.onCompile
      ? options.onCompile(spec, targetDialect)
      : compileSpecToSql(spec, targetDialect as any);

    return {
      success: true,
      tool: "build_query",
      sql,
      spec,
      explanation: `Queries table '${matchedTable}' based on intent: "${intent}".`,
      dialect: targetDialect,
    };
  }

  if (toolName === "validate_and_compile_query") {
    let spec = parsedArgs.spec as Partial<QuerySpec> | undefined;
    const rawSql = parsedArgs.sql as string | undefined;
    const targetDialect = parsedArgs.dialect || dialect;

    if (!spec && !rawSql) {
      return {
        success: false,
        error: "Either 'spec' (QuerySpec AST) or 'sql' (SQL query string) must be provided.",
      };
    }

    if (rawSql && !spec) {
      const parsed = parseSqlToSpec(rawSql);
      if (!parsed) {
        return {
          success: false,
          valid: false,
          error: `Failed to parse SQL query: ${rawSql}`,
        };
      }
      spec = parsed;
    }

    const healed = autoHealClientQuerySpec(spec!, schema);
    const finalSpec = healed.healedSpec;

    const compiled = options.onCompile
      ? options.onCompile(finalSpec, targetDialect)
      : compileSpecToSql(finalSpec, targetDialect as any);

    return {
      success: true,
      valid: true,
      tool: "validate_and_compile_query",
      sql: compiled,
      spec: finalSpec,
      dialect: targetDialect,
      warnings: healed.notes.length > 0 ? healed.notes : undefined,
    };
  }

  if (toolName === "get_schema_catalog") {
    const format = (parsedArgs.format || "markdown").toLowerCase();
    const filterTables = parsedArgs.tables as string[] | undefined;

    let tables: string[] = [];
    if (schema) {
      tables = Array.isArray(schema)
        ? schema.map((t: any) => t.name)
        : schema.tables
        ? Object.keys(schema.tables)
        : Object.keys(schema);
    }

    if (filterTables && Array.isArray(filterTables)) {
      tables = tables.filter((t) => filterTables.includes(t));
    }

    if (format === "json") {
      return {
        success: true,
        tool: "get_schema_catalog",
        format: "json",
        tables,
        schema,
      };
    }

    const catalogMd = tables.length > 0
      ? `Database Schema:\n${tables.map((t) => `- Table \`${t}\``).join("\n")}`
      : "Database Schema: No explicit schema provided.";

    return {
      success: true,
      tool: "get_schema_catalog",
      format: "markdown",
      catalog: catalogMd,
    };
  }

  if (toolName === "explain_query") {
    let spec = parsedArgs.spec as Partial<QuerySpec> | undefined;
    const rawSql = parsedArgs.sql as string | undefined;

    if (rawSql && !spec) {
      spec = parseSqlToSpec(rawSql) || undefined;
    }

    if (!spec) {
      return { success: false, error: "Query or spec to explain was not provided or could not be parsed." };
    }

    const healed = autoHealClientQuerySpec(spec, schema);
    const finalSpec = healed.healedSpec;

    const colCount = finalSpec.columns ? finalSpec.columns.length : 1;
    const joinCount = finalSpec.joins ? finalSpec.joins.length : 0;
    const filterCount = finalSpec.filters ? finalSpec.filters.length : 0;

    return {
      success: true,
      tool: "explain_query",
      summary: `Queries from table '${finalSpec.table}' selecting ${colCount} projection(s), joined with ${joinCount} table(s), filtered by ${filterCount} predicate(s).`,
      table: finalSpec.table,
      joinsCount: joinCount,
      filtersCount: filterCount,
      limit: finalSpec.limit,
    };
  }

  return {
    success: false,
    error: `Unknown tool '${toolName}'. Available: ${REACT_AGENT_TOOL_SCHEMAS.map((t) => t.name).join(", ")}`,
  };
}
