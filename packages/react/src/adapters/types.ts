/**
 * Adapter Types and Option Interfaces for React Query Builder.
 */

import type { TableSchema } from "../types";

export interface AdapterOptions {
  /** Default database schema name, defaults to 'public' */
  defaultSchema?: string;
}

export interface ToPrismaOptions {
  /** Prisma database provider: postgresql, mysql, sqlite, sqlserver, cockroachdb, mongodb */
  provider?: "postgresql" | "mysql" | "sqlite" | "sqlserver" | "cockroachdb" | "mongodb" | string;
}

export interface ToDrizzleOptions {
  /** Drizzle dialect: postgres, mysql, sqlite */
  dialect?: "postgres" | "mysql" | "sqlite" | string;
}

export type { TableSchema, ColumnSchema, ForeignKey } from "../types";

