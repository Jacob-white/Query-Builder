"""
Unit Tests for Query Builder SQL to QuerySpec Parser.
=====================================================
Covers 100% of statements, branches, and functions in query_builder/parser.py.
"""

from __future__ import annotations

import pytest

from query_builder.models import QuerySpec
from query_builder.parser import (
    clean_identifier,
    find_top_level_clauses,
    find_top_level_operator,
    parse_literal_value,
    parse_sql_to_dict,
    parse_sql_to_spec,
    split_top_level,
    split_where_conditions,
)


class TestParserHelpers:
    """Tests for individual parsing helper functions."""

    def test_clean_identifier(self) -> None:
        assert clean_identifier("") == ""
        assert clean_identifier("users") == "users"
        assert clean_identifier('"users"') == "users"
        assert clean_identifier("`users`") == "users"
        assert clean_identifier("[users]") == "users"
        assert clean_identifier("'users'") == "users"
        assert clean_identifier("public.users.id") == "public.users.id"
        assert clean_identifier('"public"."[users]"."id"') == "public.users.id"

    def test_parse_literal_value(self) -> None:
        assert parse_literal_value("'hello'") == "hello"
        assert parse_literal_value("'O''Connor'") == "O'Connor"
        assert parse_literal_value('"world"') == "world"
        assert parse_literal_value("true") is True
        assert parse_literal_value("TRUE") is True
        assert parse_literal_value("false") is False
        assert parse_literal_value("FALSE") is False
        assert parse_literal_value("42") == 42
        assert parse_literal_value("-15") == -15
        assert parse_literal_value("3.1415") == 3.1415
        assert parse_literal_value("-0.5") == -0.5
        assert parse_literal_value("some_bare_string") == "some_bare_string"

    def test_find_top_level_clauses_with_strings_and_parens(self) -> None:
        sql = "SELECT 'FROM inside string', (SELECT 1 FROM sub) AS val FROM real_table"
        tokens = find_top_level_clauses(sql)
        keywords = [t.keyword for t in tokens]
        assert "SELECT" in keywords
        assert "FROM" in keywords
        # Only the outer real_table FROM should be captured as top-level clause
        from_tokens = [t for t in tokens if t.keyword == "FROM"]
        assert len(from_tokens) == 1

    def test_split_top_level_with_quotes_and_escapes(self) -> None:
        text = "a, 'b, c', 'escaped''quote', (d, e)"
        parts = split_top_level(text, r"^,")
        values = [p["value"] for p in parts]
        assert len(values) == 4
        assert values[0] == "a"
        assert values[1] == "'b, c'"
        assert values[2] == "'escaped''quote'"
        assert values[3] == "(d, e)"

    def test_split_where_conditions(self) -> None:
        text = "a = 1 AND b BETWEEN 10 AND 20 OR c = 'AND text' AND d = 4"
        parts = split_where_conditions(text)
        assert len(parts) == 4
        assert parts[0]["value"] == "a = 1"
        assert parts[0]["delimiter"] == "AND"
        assert parts[1]["value"] == "b BETWEEN 10 AND 20"
        assert parts[1]["delimiter"] == "OR"
        assert parts[2]["value"] == "c = 'AND text'"
        assert parts[2]["delimiter"] == "AND"
        assert parts[3]["value"] == "d = 4"

    def test_find_top_level_operator_symbols_and_keywords(self) -> None:
        op1 = find_top_level_operator("users.age >= 18")
        assert op1 is not None
        assert op1[0] == ">="

        op2 = find_top_level_operator("status <> 'inactive'")
        assert op2 is not None
        assert op2[0] == "!="

        op3 = find_top_level_operator("deleted_at IS NULL")
        assert op3 is not None
        assert op3[0] == "IS NULL"

        op4 = find_top_level_operator("EXISTS (SELECT 1 FROM orders WHERE orders.id = 1)")
        assert op4 is None

        op5 = find_top_level_operator("'a''b' = col")
        assert op5 is not None
        assert op5[0] == "="


class TestSqlParser:
    """Full end-to-end tests for parse_sql_to_spec and parse_sql_to_dict."""

    def test_invalid_and_disallowed_inputs(self) -> None:
        assert parse_sql_to_spec("") is None
        assert parse_sql_to_spec(None) is None  # type: ignore[arg-type]
        assert parse_sql_to_spec(123) is None  # type: ignore[arg-type]
        assert parse_sql_to_spec("-- only comment") is None
        assert parse_sql_to_spec("/* comment */") is None
        assert parse_sql_to_spec("INSERT INTO users VALUES (1);") is None
        assert parse_sql_to_spec("UPDATE users SET name = 'foo';") is None
        assert parse_sql_to_spec("DELETE FROM users WHERE id = 1;") is None
        assert parse_sql_to_spec("DROP TABLE users;") is None
        assert parse_sql_to_spec("ALTER TABLE users ADD COLUMN age INT;") is None
        assert parse_sql_to_spec("TRUNCATE TABLE users;") is None
        assert parse_sql_to_spec("SELECT * FROM u1 UNION SELECT * FROM u2;") is None
        assert parse_sql_to_spec('SELECT * FROM "";') is None
        assert parse_sql_to_spec("SELECT * FROM '';") is None
        assert parse_sql_to_spec("SELECT 1;") is None

    def test_basic_select_and_distinct(self) -> None:
        spec = parse_sql_to_spec("SELECT * FROM users;")
        assert spec is not None
        assert spec.table == "users"
        assert spec.columns == ["*"]
        assert not spec.distinct
        assert spec.limit == 50
        assert spec.offset == 0

        spec_dist = parse_sql_to_spec("SELECT DISTINCT id, email AS user_email FROM users;")
        assert spec_dist is not None
        assert spec_dist.table == "users"
        assert spec_dist.distinct is True
        assert spec_dist.columns == ["id", {"column": "email", "alias": "user_email"}]

        # Empty SELECT projection content defaults to wildcard
        spec_empty_col = parse_sql_to_spec("SELECT FROM users;")
        assert spec_empty_col is not None
        assert spec_empty_col.columns == ["*"]

    def test_aggregates_time_grains_and_filtered_aggregates(self) -> None:
        sql = """
            SELECT
                COUNT(id) AS user_count,
                COUNT(DISTINCT email) AS unique_emails,
                SUM(salary) AS total_salary,
                AVG(score) AS avg_score,
                MIN(created_at) AS earliest,
                MAX(created_at) AS latest,
                DATE_TRUNC('month', created_at) AS signup_month,
                DATETRUNC(day, last_login) AS login_day,
                SUM(amount) FILTER (WHERE status = 'paid') AS paid_revenue
            FROM analytics
        """
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert spec.table == "analytics"
        assert len(spec.columns) == 9

        assert spec.columns[0] == {"column": "id", "agg": "COUNT", "alias": "user_count"}
        assert spec.columns[1] == {"column": "email", "agg": "COUNT", "alias": "unique_emails"}
        assert spec.columns[2] == {"column": "salary", "agg": "SUM", "alias": "total_salary"}
        assert spec.columns[3] == {"column": "score", "agg": "AVG", "alias": "avg_score"}
        assert spec.columns[4] == {"column": "created_at", "agg": "MIN", "alias": "earliest"}
        assert spec.columns[5] == {"column": "created_at", "agg": "MAX", "alias": "latest"}
        assert spec.columns[6] == {"column": "created_at", "time_grain": "month", "alias": "signup_month"}
        assert spec.columns[7] == {"column": "last_login", "time_grain": "day", "alias": "login_day"}
        assert spec.columns[8] == {"column": "amount", "agg": "SUM", "metric": "paid_revenue", "alias": "paid_revenue"}

    def test_aggregate_without_alias(self) -> None:
        spec = parse_sql_to_spec("SELECT COUNT(id) FROM users;")
        assert spec is not None
        assert spec.columns == [{"column": "id", "agg": "COUNT"}]

    def test_window_functions(self) -> None:
        sql = """
            SELECT
                id,
                ROW_NUMBER() OVER (PARTITION BY dept_id ORDER BY hire_date DESC) AS rank_in_dept,
                COUNT(*) OVER () AS total_count
            FROM employees;
        """
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert spec.table == "employees"
        assert len(spec.window_functions) == 2

        wf1 = spec.window_functions[0]
        assert wf1.function == "ROW_NUMBER"
        assert wf1.partition_by == ["dept_id"]
        assert len(wf1.order_by) == 1
        assert wf1.order_by[0].column == "hire_date"
        assert wf1.order_by[0].direction == "desc"
        assert wf1.alias == "rank_in_dept"

        wf2 = spec.window_functions[1]
        assert wf2.function == "COUNT"
        assert wf2.arguments == ["*"]
        assert wf2.partition_by == []
        assert wf2.order_by == []
        assert wf2.alias == "total_count"

    def test_raw_expressions(self) -> None:
        sql = """
            SELECT
                CASE WHEN age >= 18 THEN 'Adult' ELSE 'Minor' END AS age_group,
                price * quantity AS subtotal,
                raw_func_without_alias(x)
            FROM orders;
        """
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert len(spec.columns) == 3
        assert spec.columns[0]["alias"] == "age_group"
        assert spec.columns[0]["raw_expression"] == "CASE WHEN age >= 18 THEN 'Adult' ELSE 'Minor' END"
        assert spec.columns[1]["alias"] == "subtotal"
        assert spec.columns[1]["raw_expression"] == "price * quantity"
        assert spec.columns[2]["alias"] == "raw_func_without_alias(x)"

    def test_cte_parsing(self) -> None:
        sql = """
            WITH RECURSIVE subordinates AS (
                SELECT id, manager_id FROM employees WHERE id = 1
            ),
            summary (dept, total) AS MATERIALIZED (
                SELECT dept, SUM(salary) FROM employees GROUP BY dept
            ),
            cte_escaped AS (
                SELECT 'hel''lo' AS str FROM dual
            ),
            cte_plain AS NOT_A_PAREN
            SELECT * FROM subordinates;
        """
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert spec.table == "subordinates"
        assert len(spec.ctes) == 4

        cte1 = spec.ctes[0]
        assert cte1.name == "subordinates"
        assert cte1.recursive is True
        assert isinstance(cte1.query, QuerySpec)
        assert cte1.query.table == "employees"

        cte2 = spec.ctes[1]
        assert cte2.name == "summary"
        assert cte2.columns == ["dept", "total"]
        assert cte2.materialized is True

        cte3 = spec.ctes[2]
        assert cte3.name == "cte_escaped"

        cte4 = spec.ctes[3]
        assert cte4.name == "cte_plain"

        # Edge cases: no main SELECT or malformed CTE
        assert parse_sql_to_spec("WITH cte AS (SELECT 1)") is None
        assert parse_sql_to_spec("WITH cte AS (SELECT 1) VALUES (1, 2);") is None

    def test_joins_parsing(self) -> None:
        sql = """
            SELECT * FROM orders
            INNER JOIN customers ON orders.customer_id = customers.id
            LEFT JOIN order_items ON item_id = order_items.id
            RIGHT JOIN shipping ON shipping.order_id = orders.id
            CROSS JOIN standalone
            WHERE orders.id > 10;
        """
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert spec.table == "orders"
        # CROSS JOIN has no ON condition and is gracefully skipped
        assert len(spec.joins) == 3

        j1 = spec.joins[0]
        assert j1.table == "customers"
        assert j1.type == "INNER"
        assert j1.left_table == "orders"
        assert j1.left_col == "customer_id"
        assert j1.right_col == "id"

        j2 = spec.joins[1]
        assert j2.table == "order_items"
        assert j2.type == "LEFT"

        j3 = spec.joins[2]
        assert j3.table == "shipping"
        assert j3.type == "RIGHT"
        assert j3.left_table == "orders"
        assert j3.left_col == "id"
        assert j3.right_col == "order_id"

    def test_where_filters_and_operators(self) -> None:
        sql = """
            SELECT * FROM users
            WHERE users.age >= 18
              AND status = 'active'
              AND name != 'root'
              AND score < 100.5
              AND score > 0
              AND deleted_at IS NULL
              AND role IS NOT NULL
              AND category IN ('admin', 'staff')
              AND tag NOT IN ('guest')
              AND level BETWEEN 1 AND 10
              AND name LIKE '%John%'
              AND email ILIKE '%@example.com'
              AND is_verified = true
              AND is_banned = false
              AND 'constant' = code
              AND EXISTS (SELECT 1 FROM logs WHERE logs.user_id = users.id);
        """
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert len(spec.filters) == 16
        assert spec.filter_join == "AND"

        # Check values
        f_map = {(f.column, f.op): f for f in spec.filters}
        assert f_map[("age", ">=")].value == 18
        assert f_map[("age", ">=")].table_prefix == "users"

        assert f_map[("status", "=")].value == "active"

        assert f_map[("name", "!=")].value == "root"
        assert f_map[("name", "LIKE")].value == "%John%"

        assert f_map[("deleted_at", "IS NULL")].value is None

        assert f_map[("category", "IN")].value == ["admin", "staff"]

        assert f_map[("level", "BETWEEN")].value == "1 AND 10"

        # EXISTS condition fell back to RAW
        raw_filters = [f for f in spec.filters if f.op == "RAW"]
        assert len(raw_filters) == 1
        assert "EXISTS" in raw_filters[0].column

    def test_where_or_join_and_bare_conditions(self) -> None:
        sql = "SELECT * FROM users WHERE status = 'pending' OR age < 21 OR ) OR just_col;"
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert spec.filter_join == "OR"
        assert len(spec.filters) == 4
        assert spec.filters[0].op == "="
        assert spec.filters[1].op == "<"
        assert spec.filters[2].op == "RAW"
        assert spec.filters[3].op == "RAW"

    def test_order_by_limit_offset(self) -> None:
        sql = "SELECT * FROM products ORDER BY category ASC, products.price DESC, id LIMIT 25 OFFSET 100;"
        spec = parse_sql_to_spec(sql)
        assert spec is not None
        assert len(spec.order_by) == 3

        assert spec.order_by[0].column == "category"
        assert spec.order_by[0].direction == "asc"

        assert spec.order_by[1].column == "price"
        assert spec.order_by[1].direction == "desc"
        assert spec.order_by[1].table_prefix == "products"

        assert spec.order_by[2].column == "id"
        assert spec.order_by[2].direction == "asc"

        assert spec.limit == 25
        assert spec.offset == 100

    def test_parse_sql_to_dict(self) -> None:
        sql = "SELECT id, name FROM users WHERE id = 10 LIMIT 5;"
        d = parse_sql_to_dict(sql)
        assert d is not None
        assert isinstance(d, dict)
        assert d["table"] == "users"
        assert d["columns"] == ["id", "name"]
        assert d["limit"] == 5
        assert len(d["filters"]) == 1
        assert d["filters"][0]["value"] == 10

        assert parse_sql_to_dict("INVALID SQL") is None

    def test_uncovered_branches_and_edge_cases(self) -> None:
        # SELECT+1 fails tokenization boundary
        assert parse_sql_to_spec("SELECT+1") is None

        # Double comma in projection list
        spec = parse_sql_to_spec("SELECT id, , name FROM users;")
        assert spec is not None
        assert spec.columns == ["id", "name"]

        # Escaped quote in WHERE and paren-wrapped left side operand
        spec_escaped = parse_sql_to_spec("SELECT * FROM users WHERE name = 'O''Connor' AND (age + 5) >= 25;")
        assert spec_escaped is not None
        assert len(spec_escaped.filters) == 2
        assert spec_escaped.filters[0].value == "O'Connor"
        assert spec_escaped.filters[1].op == ">="
        assert spec_escaped.filters[1].value == 25

    def test_all_remaining_branches(self) -> None:
        from query_builder.parser import (
            find_top_level_operator,
            split_top_level,
            split_where_conditions,
        )

        # 1. split_top_level: unmatched closing paren, trailing delimiter, whitespace after delimiter
        res = split_top_level("a, b), c,", r",")
        assert len(res) >= 2

        res2 = split_top_level("a,   ", r",")
        assert len(res2) == 1

        # 2. split_where_conditions: trailing AND or trailing whitespace
        w_res = split_where_conditions("x = 1 AND  ")
        assert len(w_res) == 1

        # 3. find_top_level_operator: operator at start (empty left part)
        op_res = find_top_level_operator("= 10")
        assert op_res is None

        # 4. CTE scanner: unmatched closing paren in WITH clause
        parse_sql_to_spec("WITH cte AS (SELECT 1)) SELECT * FROM cte;")

        # 5. Join without simple a = b condition
        spec_join_non_match = parse_sql_to_spec("SELECT * FROM users JOIN orders ON TRUE WHERE users.id = 1;")
        assert spec_join_non_match is not None
        assert len(spec_join_non_match.joins) == 1

        # 6. LIMIT / OFFSET non-digits
        spec_lim = parse_sql_to_spec("SELECT * FROM users LIMIT ALL OFFSET NONE;")
        assert spec_lim is not None
        assert spec_lim.limit == 50
        assert spec_lim.offset == 0

