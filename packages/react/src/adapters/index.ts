/**
 * Schema Interoperability & ORM Adapters for React Query Builder.
 * ==============================================================
 * Exports declarative 1-line schema adapters converting Prisma, Drizzle ORM,
 * SQLAlchemy, and JSON Schema / OpenAPI into TableSchema[] for VisualQueryBuilder.
 */

export * from "./types";
export * from "./utils";
export { fromPrisma } from "./prisma";
export { fromDrizzle } from "./drizzle";
export { fromSqlAlchemy } from "./sqlalchemy";
export { fromJsonSchema } from "./jsonSchema";
export * from "./semantic";
