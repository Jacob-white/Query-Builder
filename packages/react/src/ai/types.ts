/**
 * Bring Your Own AI (BYO-AI) Type Definitions for Query-Builder React SDK.
 */

import type { DatabaseSchemaDefinition, QuerySpec, SchemaSnapshot, TableSchema } from "../types";

/**
 * Every schema representation accepted by the AI / NLQ surface: the visual-builder schema,
 * a `SchemaSnapshot`, the `TableSchema[]` returned by the adapters (`fromPrisma`, `fromDrizzle`...),
 * or any other JSON-serializable schema object.
 */
export type ByoAiSchema =
  | DatabaseSchemaDefinition
  | SchemaSnapshot
  | TableSchema[]
  | { name?: string }[]
  | Record<string, unknown>
  | null;

export type ByoAiToolFormat = "openai" | "anthropic" | "gemini" | "langchain" | "mcp";

export interface ByoAiMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  spec?: QuerySpec;
  sql?: string;
  timestamp: number;
  healingNotes?: string[];
  confidence?: number;
}

export interface ByoAiContext {
  prompt: string;
  schema?: ByoAiSchema;
  currentSpec?: QuerySpec | null;
  dialect?: string;
  history?: ByoAiMessage[];
}

export interface ByoAiResponse {
  spec?: QuerySpec;
  sql?: string;
  explanation?: string;
  confidence?: number;
  suggestions?: string[];
  warnings?: string[];
}

export type ByoAiHandlerFn = (
  context: ByoAiContext
) => Promise<ByoAiResponse | QuerySpec | string>;

export interface ByoAiClientObject {
  generate?: (context: ByoAiContext) => Promise<ByoAiResponse | QuerySpec | string>;
  generateQuery?: (context: ByoAiContext) => Promise<ByoAiResponse | QuerySpec | string>;
  ask?: (prompt: string, context?: ByoAiContext) => Promise<ByoAiResponse | QuerySpec | string>;
}

export type ByoAiHandler = ByoAiHandlerFn | ByoAiClientObject;

export interface ByoAiConfig {
  /**
   * The host application's AI handler function or client instance.
   * Can be any async function `({ prompt, schema, dialect }) => ...`
   * or client object implementing `.generate()` or `.ask()`.
   */
  handler?: ByoAiHandler;

  /**
   * Optional REST API endpoint if delegating to a backend proxy.
   * Defaults to '/api/v1/nlq/translate'.
   */
  apiUrl?: string;

  /**
   * Target SQL dialect. Defaults to 'postgres'.
   */
  dialect?: string;

  /**
   * Whether to automatically apply the AI-generated QuerySpec to the canvas.
   * Defaults to false (shows preview with 'Apply' button in widget).
   */
  autoApply?: boolean;

  /**
   * Whether to run autonomous Dijkstra join synthesis and fuzzy column repair.
   * Defaults to true.
   */
  autoHeal?: boolean;

  /**
   * Curated quick-prompt suggestion chips displayed in the widget.
   */
  suggestions?: string[];

  /**
   * Widget placement: floating pill in corner or docked panel.
   * Defaults to 'floating-bottom-right'.
   */
  widgetPosition?: "floating-bottom-right" | "docked-right" | "header";

  /**
   * Callback fired whenever a query is successfully generated or applied.
   */
  onSpecGenerated?: (spec: QuerySpec, sql?: string) => void;

  /**
   * Callback fired on AI generation errors.
   */
  onError?: (error: Error) => void;
}
