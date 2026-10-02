"""
Query Builder Engine: Universal SQL Compiler, AST Safety Validator & Join Solver.
==================================================================================
Package exports for the standalone Query Builder engine.
"""

__version__ = "1.0.0"

from query_builder.ast_validator import (
    RESTRICTED_MUTATION_KEYWORDS,
    RESTRICTED_SECURITY_TABLES,
    validate_sql_ast,
)
from query_builder.compiler import (
    AGGREGATE_MAP,
    OPERATOR_MAP,
    CompilationError,
    QueryCompiler,
)
from query_builder.dialects import (
    BaseDialect,
    MSSQLDialect,
    MySQLDialect,
    PostgresDialect,
    SnowflakeDialect,
    SQLiteDialect,
    get_dialect,
    quote_alias,
    quote_identifier,
)
from query_builder.executor import (
    execute_compiled_spec,
    execute_cursor_query,
)
from query_builder.join_solver import (
    find_best_join_condition,
    find_join_path,
)
from query_builder.models import (
    ColumnMeta,
    FilterSpec,
    ForeignKeyMeta,
    HavingSpec,
    JoinSpec,
    OrderBySpec,
    QueryResult,
    QuerySpec,
    SchemaSnapshot,
    TableMeta,
    ValidationResult,
)
from query_builder.schema import (
    normalize_schema_snapshot,
)
from query_builder.security import (
    AliasCounter,
    SecurityError,
    resolve_ownership_predicate,
)

__all__ = [
    "AGGREGATE_MAP",
    "OPERATOR_MAP",
    "RESTRICTED_MUTATION_KEYWORDS",
    "RESTRICTED_SECURITY_TABLES",
    "AliasCounter",
    "BaseDialect",
    "ColumnMeta",
    "CompilationError",
    "FilterSpec",
    "ForeignKeyMeta",
    "HavingSpec",
    "JoinSpec",
    "MSSQLDialect",
    "MySQLDialect",
    "OrderBySpec",
    "PostgresDialect",
    "QueryCompiler",
    "QueryResult",
    "QuerySpec",
    "SQLiteDialect",
    "SchemaSnapshot",
    "SecurityError",
    "SnowflakeDialect",
    "TableMeta",
    "ValidationResult",
    "__version__",
    "execute_compiled_spec",
    "execute_cursor_query",
    "find_best_join_condition",
    "find_join_path",
    "get_dialect",
    "normalize_schema_snapshot",
    "quote_alias",
    "quote_identifier",
    "resolve_ownership_predicate",
    "validate_sql_ast",
]
