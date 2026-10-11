"""CrateDB binds the main query's ``?`` before the ones inside WITH; the compiler follows."""

from query_builder.compiler import QueryCompiler

SPEC = {
    "table": "high_paid",
    "columns": ["id"],
    "ctes": [
        {
            "name": "high_paid",
            "query": {
                "table": "emp",
                "columns": ["id", "salary"],
                "filters": [{"column": "salary", "op": ">", "value": 90}],
            },
        }
    ],
    "limit": 50,
}


def test_cratedb_puts_cte_params_after_the_main_query_params():
    sql, params, _, _ = QueryCompiler(SPEC, dialect="cratedb").compile()
    assert sql.startswith("WITH")
    assert params == [50, 0, 90]  # LIMIT, OFFSET, then the CTE's salary bound


def test_other_dialects_keep_cte_params_first():
    _, params, _, _ = QueryCompiler(SPEC, dialect="postgres").compile()
    assert params == [90, 50, 0]
