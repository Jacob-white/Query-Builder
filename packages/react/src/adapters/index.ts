/**
 * Schema Interoperability & ORM Adapters for React Query Builder.
 * ==============================================================
 * Exports declarative 1-line schema adapters converting Prisma, Drizzle ORM,
 * SQLAlchemy, and JSON Schema / OpenAPI into TableSchema[] for VisualQueryBuilder.
 */

export * from "./types";
export * from "./utils";
export { fromPrisma, toPrisma, toPrismaSchema } from "./prisma";
export { fromDrizzle, toDrizzle, toDrizzleSchema } from "./drizzle";
export { fromSqlAlchemy, toSqlAlchemy, toSqlAlchemyModels } from "./sqlalchemy";
export { fromJsonSchema } from "./jsonSchema";
export * from "./semantic";

