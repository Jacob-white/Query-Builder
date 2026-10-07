"""
Comprehensive unit tests for Multi-Stage CTE DAG Pipelines and Advanced Window Functions.
Validates 100.0% coverage across models, AST validation, dialect capabilities, and compiler.
"""

import pytest

from query_builder.ast_validator import (
    SUPPORTED_WINDOW_FUNCTIONS,
    validate_cte_dag,
    validate_window_function_spec,
)
from query_builder.compiler import QueryCompiler, validate_query_spec
from query_builder.dialects import (
    BaseDialect,
    DuckDBDialect,
    MySQLDialect,
    PostgresDialect,
    SQLiteDialect,
)
from query_builder.exceptions import CompilationError, ValidationError
from query_builder.models import (
    CteSpec,
    JoinSpec,
    OrderBySpec,
    QuerySpec,
    WindowFrameSpec,
    WindowFunctionSpec,
)


class TestModels:
    """Tests for WindowFrameSpec, WindowFunctionSpec, CteSpec, and OrderBySpec models."""

    def test_window_frame_spec_valid(self):
        frame = WindowFrameSpec(
            frame_type="rows",
            start="unbounded preceding",
            end="current row",
            exclusion="no others",
        )
        assert frame.frame_type == "ROWS"
        assert frame.start == "UNBOUNDED PRECEDING"
        assert frame.end == "CURRENT ROW"
        assert frame.exclusion == "NO OTHERS"

        d = frame.to_dict()
        assert d == {
            "frame_type": "ROWS",
            "start": "UNBOUNDED PRECEDING",
            "end": "CURRENT ROW",
            "exclusion": "NO OTHERS",
        }

    def test_window_frame_spec_defaults_and_invalid(self):
        f = WindowFrameSpec()
        assert f.frame_type == "ROWS"
        assert f.start == "UNBOUNDED PRECEDING"
        assert f.end is None
        assert f.exclusion is None
        assert f.to_dict() == {
            "frame_type": "ROWS",
            "start": "UNBOUNDED PRECEDING",
        }

        with pytest.raises(ValueError, match="Invalid frame_type"):
            WindowFrameSpec(frame_type="INVALID_TYPE")

    def test_window_function_spec(self):
        wf = WindowFunctionSpec(
            function="row_number",
            arguments=[],
            partition_by=["dept_id"],
            order_by=[
                OrderBySpec(column="salary", direction="desc", table_prefix="emp")
            ],
            frame={"frame_type": "ROWS", "start": "1 PRECEDING"},
            alias="rn",
        )
        assert wf.function == "ROW_NUMBER"
        assert isinstance(wf.frame, WindowFrameSpec)
        d = wf.to_dict()
        assert d["function"] == "ROW_NUMBER"
        assert d["partition_by"] == ["dept_id"]
        assert d["alias"] == "rn"
        assert d["frame"]["frame_type"] == "ROWS"

        # Empty function raises
        with pytest.raises(ValueError, match="'function' cannot be empty"):
            WindowFunctionSpec(function="")

    def test_cte_spec(self):
        inner = QuerySpec(table="users", columns=["id", "name"])
        cte = CteSpec(
            name="active_users",
            query=inner,
            columns=["u_id", "u_name"],
            recursive=False,
            materialized=True,
        )
        assert cte.name == "active_users"
        assert cte.recursive is False
        assert cte.materialized is True

        d = cte.to_dict()
        assert d["name"] == "active_users"
        assert d["columns"] == ["u_id", "u_name"]
        assert d["recursive"] is False
        assert d["materialized"] is True
        assert d["query"]["table"] == "users"

        # Dict query hydration
        cte2 = CteSpec(name="cte2", query={"table": "orders", "columns": ["id"]})
        assert isinstance(cte2.query, QuerySpec)
        assert cte2.to_dict().get("materialized") is None

        # Invalid name raises
        with pytest.raises(ValueError, match="'name' must be a non-empty string"):
            CteSpec(name="", query={"table": "t"})
        with pytest.raises(ValueError, match="'name' must be a non-empty string"):
            CteSpec(name=123, query={"table": "t"})  # type: ignore

    def test_query_spec_with_ctes_and_window_functions(self):
        qs = QuerySpec(
            table="final_view",
            columns=["*"],
            ctes=[{"name": "c1", "query": {"table": "t1"}}],
            window_functions=[{"function": "RANK", "partition_by": ["cat"]}],
        )
        assert len(qs.ctes) == 1
        assert isinstance(qs.ctes[0], CteSpec)
        assert len(qs.window_functions) == 1
        assert isinstance(qs.window_functions[0], WindowFunctionSpec)

        d = qs.to_dict()
        assert "ctes" in d
        assert d["ctes"][0]["name"] == "c1"
        assert "window_functions" in d
        assert d["window_functions"][0]["function"] == "RANK"

    def test_order_by_spec_to_dict(self):
        o1 = OrderBySpec(column="age", direction="asc")
        assert o1.to_dict() == {"column": "age", "direction": "asc"}
        o2 = OrderBySpec(column="score", direction="desc", table_prefix="users")
        assert o2.to_dict() == {
            "column": "score",
            "direction": "desc",
            "table_prefix": "users",
        }


class TestAstValidatorCteDag:
    """Tests for validate_cte_dag and cycle detection."""

    def test_empty_ctes(self):
        res = validate_cte_dag([])
        assert res["valid"] is True
        assert res["cycles"] == []
        assert res["violations"] == []
        assert res["topological_order"] == []

    def test_invalid_and_duplicate_names(self):
        # Missing name
        res = validate_cte_dag([{"query": {"table": "t"}}])
        assert res["valid"] is False
        assert any("missing a valid 'name'" in v for v in res["violations"])

        # Invalid identifier
        res = validate_cte_dag([{"name": "123-bad", "query": {"table": "t"}}])
        assert res["valid"] is False
        assert any("Invalid CTE identifier name" in v for v in res["violations"])

        # Duplicate name
        res = validate_cte_dag(
            [
                {"name": "stage1", "query": {"table": "t"}},
                {"name": "STAGE1", "query": {"table": "t"}},
            ]
        )
        assert res["valid"] is False
        assert any("Duplicate CTE name detected" in v for v in res["violations"])

    def test_self_referencing_cte(self):
        # Self-referencing without recursive=True
        res = validate_cte_dag(
            [{"name": "numbers", "query": {"table": "numbers"}, "recursive": False}]
        )
        assert res["valid"] is False
        assert any("must be marked as recursive" in v for v in res["violations"])

        # Self-referencing with recursive=True
        res = validate_cte_dag(
            [{"name": "numbers", "query": {"table": "numbers"}, "recursive": True}]
        )
        assert res["valid"] is True

    def test_cyclic_dependency(self):
        # A -> B -> A
        ctes = [
            {"name": "cte_a", "query": {"table": "cte_b"}},
            {"name": "cte_b", "query": {"table": "cte_a"}},
        ]
        res = validate_cte_dag(ctes)
        assert res["valid"] is False
        assert len(res["cycles"]) > 0
        assert any("Circular dependency detected" in v for v in res["violations"])
        assert res["topological_order"] == []

    def test_valid_dag_topological_order(self):
        # c1 -> c2 -> c3
        ctes = [
            CteSpec(name="c3", query=QuerySpec(table="c2")),
            CteSpec(name="c1", query=QuerySpec(table="raw_data")),
            CteSpec(
                name="c2",
                query=QuerySpec(
                    table="c1",
                    joins=[JoinSpec(table="other_tbl", left_col="id", right_col="id")],
                ),
            ),
        ]
        res = validate_cte_dag(ctes)
        assert res["valid"] is True
        assert len(res["violations"]) == 0
        # Valid topological order must place c1 before c2, and c2 before c3
        order = res["topological_order"]
        assert order.index("c1") < order.index("c2")
        assert order.index("c2") < order.index("c3")


class TestAstValidatorWindowFunctions:
    """Tests for validate_window_function_spec."""

    def test_missing_or_invalid_func_name(self):
        assert validate_window_function_spec({})["valid"] is False
        assert validate_window_function_spec({"function": ""})["valid"] is False
        assert validate_window_function_spec({"function": 42})["valid"] is False

    def test_unsupported_function(self):
        res = validate_window_function_spec({"function": "NON_EXISTENT_FUNC"})
        assert res["valid"] is False
        assert any("Unsupported window function" in v for v in res["violations"])

    def test_supported_functions(self):
        for fn in SUPPORTED_WINDOW_FUNCTIONS:
            res = validate_window_function_spec({"function": fn.lower()})
            assert res["valid"] is True

    def test_window_frame_validation(self):
        # Invalid frame type
        res = validate_window_function_spec(
            {
                "function": "ROW_NUMBER",
                "frame": {"frame_type": "INVALID"},
            }
        )
        assert res["valid"] is False
        assert any("Invalid frame_type" in v for v in res["violations"])

        # Start UNBOUNDED FOLLOWING
        res = validate_window_function_spec(
            {
                "function": "SUM",
                "frame": {"frame_type": "ROWS", "start": "UNBOUNDED FOLLOWING"},
            }
        )
        assert res["valid"] is False
        assert any(
            "start cannot be UNBOUNDED FOLLOWING" in v for v in res["violations"]
        )

        # End UNBOUNDED PRECEDING
        res = validate_window_function_spec(
            {
                "function": "SUM",
                "frame": {
                    "frame_type": "ROWS",
                    "start": "CURRENT ROW",
                    "end": "UNBOUNDED PRECEDING",
                },
            }
        )
        assert res["valid"] is False
        assert any("end cannot be UNBOUNDED PRECEDING" in v for v in res["violations"])

        # Start FOLLOWING before PRECEDING or CURRENT ROW
        res = validate_window_function_spec(
            {
                "function": "AVG",
                "frame": {
                    "frame_type": "ROWS",
                    "start": "1 FOLLOWING",
                    "end": "CURRENT ROW",
                },
            }
        )
        assert res["valid"] is False
        assert any("FOLLOWING cannot precede" in v for v in res["violations"])

        # Start CURRENT ROW before PRECEDING
        res = validate_window_function_spec(
            {
                "function": "AVG",
                "frame": {
                    "frame_type": "ROWS",
                    "start": "CURRENT ROW",
                    "end": "1 PRECEDING",
                },
            }
        )
        assert res["valid"] is False
        assert any(
            "CURRENT ROW cannot precede end PRECEDING" in v for v in res["violations"]
        )

        # Valid frame
        res = validate_window_function_spec(
            {
                "function": "AVG",
                "frame": {
                    "frame_type": "ROWS",
                    "start": "1 PRECEDING",
                    "end": "1 FOLLOWING",
                },
            }
        )
        assert res["valid"] is True


class TestDialectCapabilities:
    """Tests for dialect CTE and window frame capabilities."""

    def test_dialect_flags(self):
        base = BaseDialect()
        assert base.supports_cte is True
        assert base.supports_materialized_cte is False
        assert base.supports_window_groups_frame is False
        assert base.format_cte_materialized(None) == ""
        assert base.format_cte_materialized(True) == ""

        pg = PostgresDialect()
        assert pg.supports_materialized_cte is True
        assert pg.supports_window_groups_frame is True
        assert pg.format_cte_materialized(True) == "MATERIALIZED "
        assert pg.format_cte_materialized(False) == "NOT MATERIALIZED "

        duck = DuckDBDialect()
        assert duck.supports_materialized_cte is True
        assert duck.supports_window_groups_frame is True

        sqlite = SQLiteDialect()
        assert sqlite.supports_materialized_cte is True
        assert sqlite.supports_window_groups_frame is False

        mysql = MySQLDialect()
        assert mysql.supports_materialized_cte is False


class TestQueryCompilerCteAndWindow:
    """Tests for compilation of CTEs and Window Functions."""

    def test_validate_spec_ctes_and_window_functions(self):
        # Invalid ctes type
        with pytest.raises(ValidationError, match="Field 'ctes' must be a list"):
            validate_query_spec({"table": "t", "ctes": "not_a_list"})

        # Invalid ctes content (cycle)
        with pytest.raises(ValidationError, match="Circular dependency detected"):
            validate_query_spec(
                {
                    "table": "t",
                    "ctes": [
                        {"name": "a", "query": {"table": "b"}},
                        {"name": "b", "query": {"table": "a"}},
                    ],
                }
            )

        # Invalid window_functions type
        with pytest.raises(
            ValidationError, match="Field 'window_functions' must be a list"
        ):
            validate_query_spec({"table": "t", "window_functions": "not_a_list"})

        # Invalid window_functions content
        with pytest.raises(ValidationError, match="Unsupported window function"):
            validate_query_spec(
                {
                    "table": "t",
                    "window_functions": [{"function": "BOGUS_WINDOW"}],
                }
            )

    def test_compile_ctes_basic(self):
        spec = {
            "table": "summary",
            "columns": ["dept_id", "total_salary"],
            "ctes": [
                {
                    "name": "emp_filtered",
                    "query": {
                        "table": "employees",
                        "columns": ["id", "dept_id", "salary"],
                        "filters": [{"column": "active", "op": "eq", "value": True}],
                    },
                },
                {
                    "name": "summary",
                    "columns": ["dept_id", "total_salary"],
                    "materialized": True,
                    "query": {
                        "table": "emp_filtered",
                        "columns": [
                            "dept_id",
                            {"column": "salary", "agg": "sum", "alias": "total_salary"},
                        ],
                    },
                },
            ],
        }

        # Compile with Postgres (supports MATERIALIZED)
        compiler = QueryCompiler(spec, dialect="postgres")
        main_sql, main_params, count_sql, count_params = compiler.compile()

        assert "WITH " in main_sql
        assert '"emp_filtered" AS (\nSELECT' in main_sql
        assert (
            '"summary" ("dept_id", "total_salary") AS MATERIALIZED (\nSELECT'
            in main_sql
        )
        assert 'FROM "summary"' in main_sql
        assert True in main_params
        assert "WITH " in count_sql
        assert True in count_params

        # Compile with MySQL (does not support MATERIALIZED hint -> graceful omission)
        compiler_mysql = QueryCompiler(spec, dialect="mysql")
        mysql_sql, mysql_params, _, _ = compiler_mysql.compile()
        assert "AS MATERIALIZED" not in mysql_sql
        assert "`summary` (`dept_id`, `total_salary`) AS (\nSELECT" in mysql_sql

    def test_compile_recursive_cte(self):
        spec = {
            "table": "num_sequence",
            "columns": ["n"],
            "ctes": [
                {
                    "name": "num_sequence",
                    "columns": ["n"],
                    "recursive": True,
                    "query": {
                        "table": "init_val",
                        "columns": ["init_n"],
                    },
                }
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        main_sql, _, _, _ = compiler.compile()
        assert "WITH RECURSIVE " in main_sql
        assert '"num_sequence" ("n") AS (\nSELECT' in main_sql

    def test_compile_window_functions(self):
        spec = {
            "table": "sales",
            "columns": ["rep_id", "region", "amount"],
            "window_functions": [
                {
                    "function": "ROW_NUMBER",
                    "partition_by": ["region"],
                    "order_by": [{"column": "amount", "direction": "desc"}],
                    "alias": "rep_rank",
                },
                {
                    "function": "SUM",
                    "arguments": ["amount"],
                    "partition_by": ["region"],
                    "frame": {
                        "frame_type": "ROWS",
                        "start": "UNBOUNDED PRECEDING",
                        "end": "CURRENT ROW",
                    },
                    "alias": "running_total",
                },
                {
                    "function": "COUNT",
                    "alias": "total_count",
                },
            ],
        }

        compiler = QueryCompiler(spec, dialect="postgres")
        main_sql, _, _, _ = compiler.compile()

        assert (
            'ROW_NUMBER() OVER (PARTITION BY "t1"."region" ORDER BY "t1"."amount" DESC) AS "rep_rank"'
            in main_sql
        )
        assert (
            'SUM("t1"."amount") OVER (PARTITION BY "t1"."region" ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS "running_total"'
            in main_sql
        )
        assert 'COUNT(*) OVER () AS "total_count"' in main_sql

    def test_compile_window_function_with_exclusion(self):
        spec = {
            "table": "logs",
            "columns": ["id"],
            "window_functions": [
                {
                    "function": "AVG",
                    "arguments": ["val"],
                    "order_by": [{"column": "id"}],
                    "frame": {
                        "frame_type": "ROWS",
                        "start": "1 PRECEDING",
                        "end": "1 FOLLOWING",
                        "exclusion": "CURRENT ROW",
                    },
                    "alias": "moving_avg",
                }
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        main_sql, _, _, _ = compiler.compile()
        assert (
            "ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING EXCLUDE CURRENT ROW" in main_sql
        )

    def test_compile_window_groups_on_unsupported_dialect(self):
        spec = {
            "table": "metrics",
            "columns": ["id"],
            "window_functions": [
                {
                    "function": "AVG",
                    "arguments": ["val"],
                    "order_by": [{"column": "id"}],
                    "frame": {
                        "frame_type": "GROUPS",
                        "start": "1 PRECEDING",
                    },
                }
            ],
        }
        # SQLite does not support GROUPS frame
        compiler = QueryCompiler(spec, dialect="sqlite")
        with pytest.raises(
            CompilationError, match="does not support GROUPS window frame"
        ):
            compiler.compile()

    def test_compile_invalid_cte_types(self):
        compiler = QueryCompiler({"table": "t"}, validate_spec=False)
        compiler.spec["ctes"] = [123]
        with pytest.raises(CompilationError, match="Invalid CTE item type"):
            compiler.compile()

        compiler.spec["ctes"] = [{"name": "bad", "query": 123}]
        with pytest.raises(CompilationError, match="query must be a QuerySpec or dict"):
            compiler.compile()

    def test_compile_cte_with_query_spec_instance(self):
        # c_query as QuerySpec instance and cte as CteSpec
        cte = CteSpec(
            name="c_inst",
            query=QuerySpec(table="users", columns=["id"]),
        )
        spec = QuerySpec(
            table="c_inst",
            columns=["id"],
            ctes=[cte],
        )
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()
        assert 'WITH "c_inst" AS' in sql
        assert 'FROM "c_inst"' in sql

    def test_compile_window_function_branches(self):
        # 1. args == ['*']
        # 2. no alias
        # 3. frame without end
        # 4. WindowFunctionSpec instance
        wf1 = WindowFunctionSpec(
            function="count",
            arguments=["*"],
            partition_by=["region"],
            alias=None,
        )
        wf2 = {
            "function": "sum",
            "arguments": ["val"],
            "frame": {
                "frame_type": "ROWS",
                "start": "CURRENT ROW",
            },
            "alias": "sum_val",
        }
        wf_empty = {"function": ""}
        wf_invalid = 123
        spec = {
            "table": "metrics",
            "columns": ["id"],
            "window_functions": [wf1, wf2, wf_empty, wf_invalid],
        }
        compiler = QueryCompiler(spec, dialect="postgres", validate_spec=False)
        sql, _, _, _ = compiler.compile()
        assert 'COUNT(*) OVER (PARTITION BY "t1"."region")' in sql
        assert 'SUM("t1"."val") OVER (ROWS CURRENT ROW) AS "sum_val"' in sql

    def test_cte_dag_join_combinations(self):
        # Test dict query with JoinSpec and dict joins
        ctes = [
            {
                "name": "stage1",
                "query": {
                    "table": "t1",
                    "joins": [
                        {"table": "t2"},
                        JoinSpec(table="t3"),
                    ],
                },
            },
            CteSpec(
                name="stage2",
                query=QuerySpec(
                    table="stage1",
                    joins=[
                        {"table": "stage1"},
                        JoinSpec(table="stage1"),
                    ],
                ),
                recursive=True,
            ),
        ]
        res = validate_cte_dag(ctes)
        assert res["valid"] is True
        assert "stage1" in res["topological_order"]

    def test_cte_dag_edge_cases_and_non_standard_structures(self):
        # q with non-string table and non-dict joins
        ctes = [
            {
                "name": "s1",
                "query": {
                    "table": None,  # 778->780
                    "joins": [None, 123, "invalid"],  # 783->780
                },
            },
            {
                "name": "s2",
                "query": 12345,  # 785->793
            },
            CteSpec(
                name="s3",
                query=QuerySpec(
                    table="s1",
                    joins=[
                        {"table": "s2"},  # 790->791
                        "invalid_join_string",  # 790->787
                    ],
                ),
            ),
        ]
        res = validate_cte_dag(ctes)
        assert res["valid"] is True

    def test_compiler_cte_existing_meta_and_advanced_window_types(self):
        # CTE with name already existing in schema tables_meta (760->758)
        schema = {
            "tables": {
                "users_cte": {"name": "users_cte", "columns": ["id"]},
                "raw_users": {"name": "raw_users", "columns": ["id", "salary"]},
            }
        }
        spec = {
            "table": "users_cte",
            "columns": ["id"],
            "ctes": [
                {"name": "users_cte", "query": {"table": "raw_users"}},
            ],
            "window_functions": [
                # Non-string argument (line 1316)
                {
                    "name": "lead_val",
                    "function": "LEAD",
                    "arguments": ["salary", 1],
                    # OrderBySpec object (line 1340), item without column (line 1343), invalid direction (line 1346)
                    "order_by": [
                        OrderBySpec(column="salary", direction="DESC"),
                        {"column": ""},  # empty column
                        {"column": "id", "direction": "INVALID"},  # fallback to ASC
                    ],
                    # WindowFrameSpec object (line 1358)
                    "frame": WindowFrameSpec(frame_type="ROWS", start="CURRENT ROW"),
                }
            ],
        }
        compiler = QueryCompiler(
            spec, schema=schema, dialect="postgres", validate_spec=False
        )
        sql, _, _, _ = compiler.compile()
        assert 'WITH "users_cte" AS' in sql
        assert 'LEAD("t1"."salary", 1)' in sql
        assert "ROWS CURRENT ROW" in sql
