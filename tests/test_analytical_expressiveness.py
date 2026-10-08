"""
Tests for Analytical SQL Expressiveness:
- CASE WHEN conditional expressions & calculated columns
- Set operations (UNION, UNION ALL, INTERSECT, EXCEPT, MINUS)
- Grouping Sets, ROLLUP, and CUBE
"""

import pytest

from query_builder import (
    CaseWhenBranch,
    CaseWhenSpec,
    FilterSpec,
    QueryCompiler,
    QuerySpec,
    SetOperationSpec,
)
from query_builder.exceptions import ValidationError
from query_builder.security import calculate_ast_complexity


class TestAnalyticalExpressiveness:
    def test_case_when_single_branch_literal_values(self):
        spec = {
            "table": "users",
            "columns": [
                "id",
                "name",
                {
                    "case_when": {
                        "branches": [
                            {
                                "condition": {
                                    "column": "status",
                                    "op": "eq",
                                    "value": "active",
                                },
                                "then_value": "Active User",
                            }
                        ],
                        "else_value": "Inactive",
                    },
                    "alias": "status_label",
                },
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, count_sql, _ = compiler.compile()

        assert (
            'CASE WHEN "t1"."status" = %s THEN %s ELSE %s END AS "status_label"' in sql
        )
        assert params == ["active", "Active User", "Inactive", 50, 0]
        assert "COUNT(*)" in count_sql

    def test_case_when_multiple_branches_and_dataclasses(self):
        cw = CaseWhenSpec(
            branches=[
                CaseWhenBranch(
                    condition=FilterSpec(column="score", op="gte", value=90),
                    then_value="A",
                ),
                CaseWhenBranch(
                    condition=FilterSpec(column="score", op="gte", value=80),
                    then_value="B",
                ),
            ],
            else_value="F",
            alias="grade",
        )
        spec = QuerySpec(
            table="students",
            columns=[
                "id",
                {"case_when": cw, "alias": "final_grade"},
            ],
        )
        compiler = QueryCompiler(spec, dialect="sqlite")
        sql, params, _, _ = compiler.compile()

        assert (
            'CASE WHEN "t1"."score" >= ? THEN ? WHEN "t1"."score" >= ? THEN ? ELSE ? END AS "final_grade"'
            in sql
        )
        assert params == [90, "A", 80, "B", "F", 50, 0]

    def test_case_when_column_references(self):
        spec = {
            "table": "orders",
            "columns": [
                "id",
                {
                    "case_when": {
                        "branches": [
                            {
                                "condition": {
                                    "column": "is_discounted",
                                    "op": "eq",
                                    "value": True,
                                },
                                "then_column": "sale_price",
                            }
                        ],
                        "else_column": "retail_price",
                    },
                    "alias": "effective_price",
                },
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()

        assert (
            'CASE WHEN "t1"."is_discounted" = %s THEN "t1"."sale_price" ELSE "t1"."retail_price" END AS "effective_price"'
            in sql
        )
        assert params == [True, 50, 0]

    def test_case_when_in_and_between_operators(self):
        spec = {
            "table": "products",
            "columns": [
                {
                    "case_when": {
                        "branches": [
                            {
                                "condition": {
                                    "column": "category",
                                    "op": "in",
                                    "value": ["electronics", "gaming"],
                                },
                                "then_value": "High Tech",
                            },
                            {
                                "condition": {
                                    "column": "price",
                                    "op": "between",
                                    "value": [10, 50],
                                },
                                "then_value": "Budget",
                            },
                        ],
                        "else_value": "Standard",
                    },
                    "alias": "category_tier",
                }
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, params, _, _ = compiler.compile()

        assert 'WHEN "t1"."category" IN (%s, %s) THEN %s' in sql
        assert 'WHEN "t1"."price" BETWEEN %s AND %s THEN %s' in sql
        assert params == [
            "electronics",
            "gaming",
            "High Tech",
            10,
            50,
            "Budget",
            "Standard",
            50,
            0,
        ]

    def test_case_when_validation_error_missing_condition(self):
        spec = {
            "table": "users",
            "columns": [
                {
                    "case_when": {
                        "branches": [{"then_value": "Val"}],
                    }
                }
            ],
        }
        with pytest.raises(
            ValidationError, match="Each branch in 'case_when' must have a 'condition'"
        ):
            QueryCompiler(spec)

    def test_set_operation_union(self):
        spec_north = {
            "table": "sales_north",
            "columns": ["id", "amount", "created_at"],
            "limit": 10,
        }
        spec_south = {
            "table": "sales_south",
            "columns": ["id", "amount", "created_at"],
            "limit": 10,
        }
        spec_main = {
            **spec_north,
            "set_operations": [
                {"operation": "UNION", "query": spec_south},
            ],
        }

        compiler = QueryCompiler(spec_main, dialect="postgres")
        sql, params, count_sql, count_params = compiler.compile()

        assert 'FROM "sales_north"' in sql
        assert "\nUNION\n" in sql
        assert 'FROM "sales_south"' in sql
        assert "SELECT COUNT(*) FROM (" in count_sql
        assert "AS set_op_count" in count_sql
        # 10, 0 from north, 10, 0 from south
        assert params == [10, 0, 10, 0]
        assert count_params == params

    def test_set_operation_chain_union_all_and_intersect(self):
        q1 = {"table": "t1", "columns": ["id"]}
        q2 = {"table": "t2", "columns": ["id"]}
        q3 = {"table": "t3", "columns": ["id"]}
        spec = {
            **q1,
            "set_operations": [
                SetOperationSpec(operation="UNION ALL", query=q2),
                SetOperationSpec(operation="INTERSECT", query=q3),
            ],
        }
        compiler = QueryCompiler(spec, dialect="snowflake")
        sql, _, _, _ = compiler.compile()

        assert "\nUNION ALL\n" in sql
        assert "\nINTERSECT\n" in sql

    def test_set_operation_validation_invalid_op(self):
        spec = {
            "table": "t1",
            "columns": ["id"],
            "set_operations": [
                {"operation": "INVALID_OP", "query": {"table": "t2", "columns": ["id"]}}
            ],
        }
        with pytest.raises(ValidationError, match="Invalid set operation"):
            QueryCompiler(spec)

    def test_grouping_rollup(self):
        spec = {
            "table": "sales",
            "columns": [
                {"column": "region"},
                {"column": "category"},
                {"column": "amount", "agg": "sum", "alias": "total"},
            ],
            "grouping_type": "rollup",
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, _, _, _ = compiler.compile()

        assert 'GROUP BY ROLLUP("t1"."region", "t1"."category")' in sql

    def test_grouping_cube(self):
        spec = {
            "table": "sales",
            "columns": [
                {"column": "year"},
                {"column": "quarter"},
                {"column": "revenue", "agg": "avg", "alias": "avg_rev"},
            ],
            "grouping_type": "cube",
        }
        compiler = QueryCompiler(spec, dialect="snowflake")
        sql, _, _, _ = compiler.compile()

        assert 'GROUP BY CUBE("t1"."year", "t1"."quarter")' in sql

    def test_grouping_sets_explicit(self):
        spec = {
            "table": "sales",
            "columns": [
                {"column": "dept"},
                {"column": "role"},
                {"column": "salary", "agg": "avg", "alias": "avg_sal"},
            ],
            "grouping_type": "grouping_sets",
            "grouping_sets": [
                ["dept", "role"],
                ["dept"],
            ],
        }
        compiler = QueryCompiler(spec, dialect="postgres")
        sql, _, _, _ = compiler.compile()

        assert (
            'GROUP BY GROUPING SETS(("t1"."dept", "t1"."role"), ("t1"."dept"))' in sql
        )

    def test_ast_complexity_with_analytical_constructs(self):
        base_spec = {"table": "sales", "columns": ["id"]}
        base_score = calculate_ast_complexity(base_spec)

        # with case_when
        cw_spec = {
            "table": "sales",
            "columns": [
                "id",
                {
                    "case_when": {
                        "branches": [
                            {
                                "condition": {"column": "x", "op": "eq", "value": 1},
                                "then_value": "A",
                            },
                            {
                                "condition": {"column": "x", "op": "eq", "value": 2},
                                "then_value": "B",
                            },
                        ]
                    }
                },
            ],
        }
        cw_score = calculate_ast_complexity(cw_spec)
        assert cw_score > base_score

        # with set_operations
        so_spec = {
            "table": "sales",
            "columns": ["id"],
            "set_operations": [
                {
                    "operation": "UNION",
                    "query": {"table": "sales_backup", "columns": ["id"]},
                }
            ],
        }
        so_score = calculate_ast_complexity(so_spec)
        assert so_score >= base_score + 10
