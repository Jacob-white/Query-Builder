# Dialect guide

A **dialect** is the part of Query-Builder that knows how one SQL engine wants its SQL written. The
compiler (`query_builder/compiler.py`) turns a query spec into SQL and asks the dialect every
engine-specific question: how to quote an identifier, which bind marker to use, how to paginate,
how to match case-insensitively, how to spell `AVG`.

Use this guide when you add a dialect (see also [ADDING_A_CONNECTOR.md](ADDING_A_CONNECTOR.md)) or
when a live run shows an engine rejecting or mis-answering compiled SQL. The last section is a
catalogue of quirks that real engines have already shown, with the knob that fixed each.

## 1. Adding a dialect

1. **Subclass `BaseDialect`** in `query_builder/dialects/<module>.py` (pick the module of the
   closest family, e.g. `relational.py`, `warehouse.py`, `nosql.py`). Set only what differs from the
   ANSI defaults in `query_builder/dialects/base.py`.
2. **Register it** in the `DIALECTS` dict in `query_builder/dialects/registry.py`. Aliases are just
   more keys pointing at the same instance. Export the class from `query_builder/dialects/__init__.py`
   and `query_builder/__init__.py` (and their `__all__`).
   - `get_dialect()` **silently falls back to PostgreSQL** for a name it does not know. A typo in a
     dialect name therefore compiles Postgres SQL instead of failing.
3. **Map it for the SQL safety validator** in `DIALECT_MAP` in `query_builder/sql_ast.py` (Query-Builder
   name -> the sqlglot dialect that parses it best, e.g. `"oceanbase": "mysql"`). A name that is not in
   the map is analysed under every dialect in `FALLBACK_DIALECTS`, which is stricter and produces more
   false positives. Syntax the parser cannot read is **rejected (fail closed)**, so an engine with
   unusual syntax (Informix `SELECT SKIP n FIRST m DISTINCT`) needs a normalisation step in
   `_normalize_placeholders`.
4. **Regenerate the golden snapshots and review the diff** (section 4).
5. **Run it against the real engine** ([TESTING_LIVE.md](TESTING_LIVE.md)). Mocks cannot tell you what
   an engine rejects; every dialect defect in the table below was invisible until a live run.

## 2. The settings (class attributes)

All of these live on `BaseDialect`; override only what the engine needs.

| Setting | Default | Set it when | Seen on |
| :--- | :--- | :--- | :--- |
| `placeholder` | `%s` | the driver binds another marker (`?`, `:1`, `$1`) | `?`: Db2, Informix, Presto/Trino, CrateDB, H2, Derby |
| `pagination_placement` | `suffix` | pagination goes before the select list | `prefix`: Informix (`SKIP n FIRST m`) |
| `requires_order_by_for_pagination` | `False` | the engine rejects `OFFSET` without `ORDER BY` | SQL Server (the compiler adds `ORDER BY (SELECT NULL)`) |
| `supports_cte` / `supports_recursive_cte` / `supports_materialized_cte` | `True` / `True` / `False` | the engine lacks `WITH` | see the Derby note in section 5 |
| `supports_window_functions` / `supports_window_groups_frame` | `True` / `False` | window support differs | |
| `supports_table_aliases` | `True` | the engine cannot resolve `alias.column` or `FROM t alias`: the compiler then emits bare columns and refuses joins | MongoDB (pymongosql), Bigtable |
| `dotted_column_names` | `False` | a dotted name is **one** column, not `table.column` | Bigtable (`family.qualifier`) |
| `distinct_order_by_alias` | `False` | `SELECT DISTINCT ... ORDER BY` must order by the select alias | RisingWave |
| `window_partition_null_rows_dropped` | `False` | an aggregate window with `PARTITION BY` and no `ORDER BY` silently drops NULL-key rows | RisingWave |
| `cte_params_after_main` | `False` | the engine numbers the main query's bind parameters **before** those inside `WITH` | CrateDB |
| `avg_template` | `AVG({})` | `AVG` over an integer column does integer division | Db2, Derby, Firebird, SQL Server (a `CAST` to a floating type) |
| `count_distinct_template` | `COUNT(DISTINCT {})` | spelled differently | |
| `subquery_alias_keyword` | `AS ` | the engine rejects `AS` before a derived-table alias | Oracle |
| `neq_operator` | `!=` | the engine rejects `!=` | Drill (`<>`) |
| `ilike_template` | `{col} ILIKE {ph}` | the engine has no `ILIKE` operator | `LOWER({col}) LIKE LOWER({ph})` on most non-PostgreSQL engines; found live on Doris, StarRocks, Db2, Informix, Derby |
| `like_escape_char` / `like_escape_clause` / `like_special_chars` | `None` / `False` / `%_` | a literal `%` or `_` in a user value must not act as a wildcard; set the escape character, and `like_escape_clause = True` when the engine needs `ESCAPE '\'` declared | Db2, Informix, Vertica, Derby, H2 (declared); Doris, StarRocks (`\` is the default) |
| `introspects_keys` | `True` | the engine has no primary/foreign key catalog | Bigtable, Firestore, Chroma, Milvus, Qdrant, Prometheus |

## 3. The methods

Override these when a flag is not enough:

- `quote_identifier(ident)` / `quote_alias(alias)`: always call the module's identifier validation
  first; never interpolate unvalidated text. Some engines need bare identifiers (MongoDB) or a session
  flag to accept quoting at all (Informix needs `DELIMIDENT=y`, added by its connector).
- `format_limit_offset(limit, offset)` -> `(sql, params)`: **return the values inline (int-coerced) when
  the engine cannot bind them**: Presto, Informix, Materialize, RisingWave, TDengine, OpenSearch,
  QuestDB and MongoDB inline both values (Elasticsearch inlines `LIMIT` and has no `OFFSET`). Presto
  also rejects `OFFSET 0` unless the server sets `offset-clause-enabled`, so a zero offset is omitted.
- `format_having_placeholder(value)`: type the marker when `HAVING SUM(x) > ?` cannot be bound
  (Informix emits `CAST(? AS BIGINT)` / `CAST(? AS FLOAT)`).
- `format_ilike`, `format_like`, `format_substring_match`, `escape_like`, `substring_param`: the
  case-insensitive and substring matching helpers (they use the settings above).
- `format_text_search`, `format_vector_distance`, `format_vector_param`: text and vector search.
- `inspect_*_query`: the catalog queries behind introspection (most connectors implement introspection
  in `query_builder/connectors/introspection.py` instead).

## 4. Golden snapshots and tests

Compiled SQL for every dialect is pinned by golden files, so an intended change shows up as a diff:

```bash
QB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden_compiler.py   # tests/golden/compiler_golden.json
PYTHONPATH=. python tests/test_golden_dialects.py --update          # tests/golden/dialects.json
git diff tests/golden                                               # review EVERY changed entry
```

Review the diff: only the dialects you touched should change, and only in the way you intended. A
change to `BaseDialect` moves every dialect.

Put a regression test for each live-found defect in `tests/test_live_defect_regressions.py`: compile
the spec with `QueryCompiler(spec, dialect=get_dialect("name")).compile()` and assert the SQL and
parameters. Older tests sometimes pin behaviour that a live run later disproved (for example a `%s`
placeholder on an engine that binds `?`); when a live-verified fix contradicts one, update the test and
say why in the commit.

## 5. Quirks real engines have shown

Every row was found by running the live suite against the engine; none was predictable from the docs.

| Symptom | Engine(s) | Fix |
| :--- | :--- | :--- |
| `LIMIT ?` / `OFFSET ?` rejected | Presto, Informix, Materialize, RisingWave, TDengine, OpenSearch (Elasticsearch: `LIMIT` only) | inline int-coerced values in `format_limit_offset` |
| `Offset support is not enabled` | Presto | omit `OFFSET 0`; the test container sets `offset-clause-enabled=true` |
| `ILIKE` is a syntax error | Doris, StarRocks, Db2, Informix, Derby | `ilike_template = LOWER({col}) LIKE LOWER({ph})` |
| a literal `%` / `_` in a value matches everything | Db2, Informix, Vertica, Derby, H2, CrateDB, StarRocks | set `like_escape_char` (and `like_escape_clause` where the engine requires `ESCAPE`) |
| every bound query fails with a syntax / "illegal character" error | CrateDB (`%s`), Informix (`%s`) | use the marker the driver binds (`?`) |
| `AVG` of an integer column returns an integer | Db2, Derby | `avg_template` casting to `DOUBLE` |
| `SUM(x) > ?` fails to bind ("invalid precision") | Informix | `format_having_placeholder` casts the marker |
| bound parameters mis-ordered around a `WITH` clause | Informix (`SKIP ? FIRST ?`), CrateDB | inline the pagination; `cte_params_after_main` |
| a CTE's filter silently ignored | Informix | same cause: do not bind `SKIP`/`FIRST` |
| quoted identifiers are string literals | Informix | the connector adds `DELIMIDENT=y` to the DSN |
| no `information_schema` | Vertica | read `v_catalog` |
| primary-key query also returns foreign-key columns | Db2 | join `SYSCAT.TABCONST` and keep `TYPE = 'P'` |
| key column lists are blank-padded `CHAR` values | Db2 | split and trim |
| key columns stored as index part numbers, not names | Informix | resolve `sysindexes.part1..16` through `syscolumns` |
| no key column names in the SQL catalog | Derby | `DatabaseMetaData.getImportedKeys` over JDBC |
| foreign keys come back empty, error swallowed | OceanBase (MySQL mode has no `constraint_column_usage`) | `fk_style="mysql"` |
| aliased columns come back under the underlying name | H2, Derby (JayDeBeApi uses `getColumnName`) | report `getColumnLabel` |
| a trailing `;` is a syntax error | Derby, Trino, Presto | send statements without it |
| statement timeout never fires | Db2, Informix (a connection-level setting is ignored) | set the CLI query timeout on the **prepared statement** |
| unqualified or quoted names silently return no rows | MongoDB (pymongosql) | `supports_table_aliases = False`, bare identifiers |
| every value comes back NULL | Bigtable (`cf.name` read as table `cf`) | `dotted_column_names = True` |
| `ORDER BY` rejected with `DISTINCT` | RisingWave | `distinct_order_by_alias = True` |
| NULL-partition rows silently dropped | RisingWave | `window_partition_null_rows_dropped = True` |
| column names must be ASCII | Doris | declared limitation (the test dataset uses an ASCII stand-in) |
| no `WITH` support | Derby | declared limitation with a probe (the dialect still compiles CTEs; the engine rejects them) |

If an engine cannot do something, do not hide it: declare it as a limitation **with a probe** that
proves the engine rejects the feature ([TESTING_LIVE.md](TESTING_LIVE.md), "Limitations must prove
themselves"). A bare skip can hide a real gap.
