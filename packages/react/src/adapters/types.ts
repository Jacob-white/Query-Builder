/**
 * Adapter Types and Option Interfaces for React Query Builder.
 */

import type { TableSchema } from "../types";

export interface AdapterOptions {
  /** Default database schema name, defaults to 'public' */
  defaultSchema?: string;
}

export type { TableSchema, ColumnSchema, ForeignKey } from "../types";
