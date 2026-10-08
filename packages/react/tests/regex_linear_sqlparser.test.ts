import { describe, expect, it } from "vitest";
import { parseSqlToSpec, splitWhereConditions } from "../src/utils/sqlParser";

// Regex hardening for src/utils/sqlParser.ts (CodeQL js/polynomial-redos).
//
// 1. Differential tests: the expected values below were captured from the ORIGINAL regex-based
//    implementation, so any behavior drift in the linear-time rewrite fails here.
// 2. Linear-time tests: adversarial inputs that took seconds to minutes with the old regexes.

const PARSE_CASES: [string, unknown][] = [
  ["SELECT * FROM users", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["select id, name from users u where u.age >= 18 and u.name like 'A%' or u.id in (1,2,3) order by u.id desc limit 10 offset 5;", {"table":"users","columns":["id","name"],"joins":[],"filters":[{"column":"age","op":">=","value":18,"tablePrefix":"u","combiner":"AND"},{"column":"name","op":"LIKE","value":"A%","tablePrefix":"u","combiner":"AND"},{"column":"id","op":"IN","value":"1,2,3","tablePrefix":"u","combiner":"OR"}],"filter_join":"OR","order_by":[{"column":"id","direction":"DESC","tablePrefix":"u"}],"distinct":false,"limit":10,"offset":5}],
  ["SELECT id FROM t -- trailing comment\nWHERE a = 1 /* block */ AND b <> 2;;  ", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"=","value":1,"tablePrefix":"t","combiner":"AND"},{"column":"b","op":"!=","value":2,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a = 1 /* unclosed AND b = 2", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"=","value":"1 /* unclosed","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"=","value":2,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a BETWEEN 1 AND 5 AND b IS NOT NULL OR c IS NULL", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"BETWEEN","value":"1 AND 5","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"IS NOT NULL","value":"","tablePrefix":"t","combiner":"AND"},{"column":"c","op":"IS NULL","value":"","tablePrefix":"t","combiner":"OR"}],"filter_join":"OR","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a   NOT   IN (1,2) AND  b  ILIKE  'x' AND c STARTS_WITH 'q'", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"NOT IN","value":"1,2","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"ILIKE","value":"x","tablePrefix":"t","combiner":"AND"},{"column":"c","op":"STARTS_WITH","value":"q","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE NOT EXISTS (SELECT 1 FROM x) AND a=1", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"NOT EXISTS (SELECT 1 FROM x)","op":"RAW","value":"","tablePrefix":"t","rawExpression":"NOT EXISTS (SELECT 1 FROM x)","combiner":"AND"},{"column":"a","op":"=","value":1,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a=1 AND b>=2 AND c<=3 AND d!=4 AND e>5 AND f<6 AND g==7", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"=","value":1,"tablePrefix":"t","combiner":"AND"},{"column":"b","op":">=","value":2,"tablePrefix":"t","combiner":"AND"},{"column":"c","op":"<=","value":3,"tablePrefix":"t","combiner":"AND"},{"column":"d","op":"!=","value":4,"tablePrefix":"t","combiner":"AND"},{"column":"e","op":">","value":5,"tablePrefix":"t","combiner":"AND"},{"column":"f","op":"<","value":6,"tablePrefix":"t","combiner":"AND"},{"column":"g=","op":"=","value":7,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a IN(1,2) AND b = 'x AND y' AND \"c d\" = 3", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a IN(1,2)","op":"RAW","value":"","tablePrefix":"t","rawExpression":"a IN(1,2)","combiner":"AND"},{"column":"b","op":"=","value":"x AND y","tablePrefix":"t","combiner":"AND"},{"column":"c d","op":"=","value":3,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a = 1\n  AND\tb = 2\n OR c = 3", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"=","value":1,"tablePrefix":"t","combiner":"AND"},{"column":"b","op":"=","value":2,"tablePrefix":"t","combiner":"AND"},{"column":"c","op":"=","value":3,"tablePrefix":"t","combiner":"OR"}],"filter_join":"OR","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE  = 5 AND x IS NULL", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"= 5","op":"RAW","value":"","tablePrefix":"t","rawExpression":"= 5","combiner":"AND"},{"column":"x","op":"IS NULL","value":"","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT id FROM t WHERE a CONTAINS 'x' AND b ENDS_WITH 'y' AND c = true AND d = false AND e = -3.5", {"table":"t","columns":["id"],"joins":[],"filters":[{"column":"a","op":"CONTAINS","value":"x","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"ENDS_WITH","value":"y","tablePrefix":"t","combiner":"AND"},{"column":"c","op":"=","value":true,"tablePrefix":"t","combiner":"AND"},{"column":"d","op":"=","value":false,"tablePrefix":"t","combiner":"AND"},{"column":"e","op":"=","value":-3.5,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT ROW_NUMBER() OVER (PARTITION BY a, b ORDER BY c DESC, d) AS rn FROM t", {"table":"t","columns":[{"column":"rn","alias":"rn"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"ROW_NUMBER","arguments":[],"partition_by":["a","b"],"order_by":[{"column":"c","direction":"DESC"},{"column":"d","direction":"ASC"}],"alias":"rn"}]}],
  ["SELECT RANK() OVER (ORDER BY c) FROM t", {"table":"t","columns":[{"column":"rank_wf","alias":"rank_wf"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"RANK","arguments":[],"order_by":[{"column":"c","direction":"ASC"}],"alias":"rank_wf"}]}],
  ["SELECT SUM(x) OVER (PARTITION BY a) total FROM t", {"table":"t","columns":[{"column":"total","alias":"total"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"SUM","arguments":["x"],"partition_by":["a"],"alias":"total"}]}],
  ["SELECT ROW_number() over (partition   by a,b   order   by c desc) AS rn FROM t", {"table":"t","columns":[{"column":"rn","alias":"rn"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"ROW_NUMBER","arguments":[],"partition_by":["a","b"],"order_by":[{"column":"c","direction":"DESC"}],"alias":"rn"}]}],
  ["SELECT ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) FROM t", {"table":"t","columns":[{"column":"row_number_wf","alias":"row_number_wf"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"ROW_NUMBER","arguments":[],"partition_by":["a"],"order_by":[{"column":"b","direction":"ASC"}],"alias":"row_number_wf"}]}],
  ["SELECT LAG(x, 1) OVER (PARTITION BY ORDER BY x) AS l FROM t", {"table":"t","columns":[{"column":"l","alias":"l"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"LAG","arguments":["x","1"],"partition_by":["ORDER BY x"],"order_by":[{"column":"x","direction":"ASC"}],"alias":"l"}]}],
  ["SELECT ROW_NUMBER() OVER (PARTITION BY) AS l FROM t", {"table":"t","columns":[{"column":"l","alias":"l"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"ROW_NUMBER","arguments":[],"alias":"l"}]}],
  ["SELECT ROW_NUMBER() OVER (ORDER BY) AS l FROM t", {"table":"t","columns":[{"column":"l","alias":"l"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"ROW_NUMBER","arguments":[],"alias":"l"}]}],
  ["SELECT ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) AS rn, COUNT(*) FROM t", {"table":"t","columns":[{"column":"rn","alias":"rn"},{"column":"*","agg":"COUNT"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"window_functions":[{"function":"ROW_NUMBER","arguments":[],"partition_by":["a"],"order_by":[{"column":"b","direction":"ASC"}],"alias":"rn"}]}],
  ["SELECT DATE_TRUNC('month', created_at) AS m FROM t", {"table":"t","columns":[{"column":"created_at","time_grain":"month","alias":"m"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT DATE_TRUNC( month , created_at ) m, DATE_TRUNC(\"day\",  x.y  ) FROM t", {"table":"t","columns":[{"column":"created_at","time_grain":"month","alias":"m"},{"column":"x.y","time_grain":"day","alias":"x.y_day"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT DATE_TRUNC('month', ) AS m FROM t", {"table":"t","columns":[{"column":"","time_grain":"month","alias":"m"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT DATETRUNC(month, created_at) AS m FROM t", {"table":"t","columns":[{"column":"created_at","time_grain":"month","alias":"m"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT DATETRUNC( year ,   created_at   ) FROM t", {"table":"t","columns":[{"column":"created_at","time_grain":"year","alias":"created_at_year"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT DATETRUNC(year,  ) FROM t", {"table":"t","columns":[{"column":"","time_grain":"year","alias":"_year"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT COUNT(*) AS c, SUM(DISTINCT x) s, AVG( y ) FROM t", {"table":"t","columns":[{"column":"*","agg":"COUNT","alias":"c"},{"column":"x","agg":"SUM","alias":"s"},{"column":"y","agg":"AVG"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT COUNT( DISTINCT  u.id ) AS c FROM t", {"table":"t","columns":[{"column":"u.id","agg":"COUNT","alias":"c"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT COUNT(DISTINCT  ) AS c FROM t", {"table":"t","columns":[{"column":"","agg":"COUNT","alias":"c"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT COUNT(  DISTINCT ) AS c FROM t", {"table":"t","columns":[{"column":"DISTINCT","agg":"COUNT","alias":"c"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT COUNT(DISTINCTx) AS c FROM t", {"table":"t","columns":[{"column":"DISTINCTx","agg":"COUNT","alias":"c"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT MAX( ) FROM t", {"table":"t","columns":[{"column":"","agg":"MAX"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT SUM(a) FILTER (WHERE a > 1) AS s FROM t", {"table":"t","columns":[{"column":"a","agg":"SUM","metric":"s","alias":"s"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT COUNT(DISTINCT a) FILTER ( WHERE b = 'x' )  c FROM t", {"table":"t","columns":[{"column":"a","agg":"COUNT","metric":"c","alias":"c"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT SUM( a ) FILTER (WHERE  ) FROM t", {"table":"t","columns":[{"column":"a","agg":"SUM","metric":"sum_a","alias":"sum_a"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT SUM(a) FILTER (WHERE b = 1) FROM t", {"table":"t","columns":[{"column":"a","agg":"SUM","metric":"sum_a","alias":"sum_a"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a AS x, b y, c, \"d\".\"e\" AS f, [g] FROM t", {"table":"t","columns":[{"column":"a","alias":"x"},{"column":"b","alias":"y"},"c",{"column":"d.e","alias":"f"},"g"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT CASE WHEN a=1 THEN 2 END AS z, a*b AS total, a+b FROM t", {"table":"t","columns":[{"column":"CASE WHEN a=1 THEN 2 END","raw_expression":"CASE WHEN a=1 THEN 2 END","alias":"z"},{"column":"a*b","raw_expression":"a*b","alias":"total"},{"column":"a+b","raw_expression":"a+b","alias":"a+b"}],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT DISTINCT a FROM t", {"table":"t","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":true,"limit":50}],
  ["SELECT distinct   a, b FROM t", {"table":"t","columns":["a","b"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":true,"limit":50}],
  ["WITH c AS (SELECT a FROM t) SELECT a FROM c", {"table":"c","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"ctes":[{"name":"c","recursive":false,"query":{"sql":"SELECT a FROM t"}}]}],
  ["WITH RECURSIVE c(a, b) AS MATERIALIZED (SELECT a FROM t), d AS NOT MATERIALIZED ( SELECT 1 FROM t ) SELECT a FROM c", {"table":"c","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"ctes":[{"name":"c","recursive":true,"columns":["a","b"],"materialized":true,"query":{"sql":"SELECT a FROM t"}},{"name":"d","recursive":true,"materialized":false,"query":{"sql":"SELECT 1 FROM t"}}]}],
  ["WITH c   (a)   AS   (  SELECT a FROM t  )   SELECT a FROM c", {"table":"c","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"ctes":[{"name":"c","recursive":false,"columns":["a"],"query":{"sql":"SELECT a FROM t"}}]}],
  ["WITH c AS (SELECT a FROM t) , bad SELECT a FROM c", {"table":"c","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"ctes":[{"name":"c","recursive":false,"query":{"sql":"SELECT a FROM t"}},{"name":"bad","recursive":false,"query":{"sql":"bad"}}]}],
  ["WITH c AS (SELECT a FROM t) x SELECT a FROM c", {"table":"c","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"ctes":[{"name":"c","recursive":false,"query":{"sql":"c AS (SELECT a FROM t) x"}}]}],
  ["WITH \"my cte\" AS (SELECT a FROM t) SELECT a FROM c", {"table":"c","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50,"ctes":[{"name":"my","recursive":false,"query":{"sql":"\"my cte\" AS (SELECT a FROM t)"}}]}],
  ["WITH c AS (SELECT a FROM t)", null],
  ["SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id", {"table":"users","columns":["u.id","o.total"],"joins":[{"table":"orders","type":"LEFT JOIN","left_table":"users","left_col":"id","right_col":"user_id","on":[{"left":"users.id","right":"orders.user_id"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u INNER JOIN orders AS o ON o.user_id=u.id LEFT JOIN items i ON i.order_id = o.id", {"table":"users","columns":["*"],"joins":[{"table":"orders","type":"INNER JOIN","left_table":"users","left_col":"id","right_col":"user_id","on":[{"left":"users.id","right":"orders.user_id"}]},{"table":"items","type":"LEFT JOIN","left_table":"orders","left_col":"id","right_col":"order_id","on":[{"left":"orders.id","right":"items.order_id"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u RIGHT JOIN orders o ON  (u.id)  =  (o.uid)", {"table":"users","columns":["*"],"joins":[{"table":"orders","type":"RIGHT JOIN","left_table":"users","left_col":"id","right_col":"id","on":[{"left":"users.id","right":"orders.id"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u FULL JOIN orders o ON u.id == o.uid", {"table":"users","columns":["*"],"joins":[{"table":"orders","type":"FULL JOIN","left_table":"users","left_col":"id","right_col":"id","on":[{"left":"users.id","right":"orders.id"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u CROSS JOIN orders o ON a.b = c.d", {"table":"users","columns":["*"],"joins":[{"table":"orders","type":"CROSS JOIN","left_table":"users","left_col":"b","right_col":"d","on":[{"left":"users.b","right":"orders.d"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u JOIN orders o ON x = y", {"table":"users","columns":["*"],"joins":[{"table":"orders","type":"LEFT JOIN","left_table":"users","left_col":"x","right_col":"y","on":[{"left":"users.x","right":"orders.y"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u JOIN orders o ON \"a\".[b] = `c`.d", {"table":"users","columns":["*"],"joins":[{"table":"orders","type":"LEFT JOIN","left_table":"users","left_col":"b","right_col":"d","on":[{"left":"users.b","right":"orders.d"}]}],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u JOIN orders o USING (id)", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM [dbo].[users] AS u WHERE u.id = 1", {"table":"dbo.users","columns":["*"],"joins":[],"filters":[{"column":"id","op":"=","value":1,"tablePrefix":"u","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM \"my schema\".\"users\" u", {"table":"my schema.users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM `db`.`users` `u`", {"table":"db.users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users, orders WHERE users.id = orders.uid", {"table":"users","columns":["*"],"joins":[],"filters":[{"column":"id","op":"=","value":"orders.uid","tablePrefix":"users","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u, orders o", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users AS", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users WITH (NOLOCK)", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users final", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users [unclosed", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users \"unclosed x", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM users u1 ]stray", {"table":"users","columns":["*"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT * FROM", null],
  ["SELECT", null],
  ["SELECT a", null],
  ["UPDATE t SET a = 1", null],
  ["SELECT a FROM t UNION SELECT b FROM u", null],
  ["INSERT INTO t VALUES (1)", null],
  ["", null],
  ["   ", null],
  ["SELECT a FROM t ORDER BY a, b DESC, c.d asc LIMIT 5", {"table":"t","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[{"column":"a","direction":"ASC","tablePrefix":"t"},{"column":"b","direction":"DESC","tablePrefix":"t"},{"column":"d","direction":"ASC","tablePrefix":"c"}],"distinct":false,"limit":5}],
  ["SELECT a FROM t ORDER BY   a   desc   LIMIT   abc", {"table":"t","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[{"column":"a","direction":"DESC","tablePrefix":"t"}],"distinct":false,"limit":50}],
  ["SELECT a FROM t LIMIT 10 OFFSET -1", {"table":"t","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":10}],
  ["SELECT a FROM t GROUP BY a ORDER BY a", {"table":"t","columns":["a"],"joins":[],"filters":[],"filter_join":"AND","order_by":[{"column":"a","direction":"ASC","tablePrefix":"t"}],"distinct":false,"limit":50}],
  ["SELECT f(a, 'x,y'), g(b,c) FROM t WHERE (a = 1 AND b = 2) OR c = 3", {"table":"t","columns":[{"column":"f(a, 'x,y')","raw_expression":"f(a, 'x,y')","alias":"f(a, 'x,y')"},{"column":"g(b,c)","raw_expression":"g(b,c)","alias":"g(b,c)"}],"joins":[],"filters":[{"column":"(a = 1 AND b = 2)","op":"RAW","value":"","tablePrefix":"t","rawExpression":"(a = 1 AND b = 2)","combiner":"AND"},{"column":"c","op":"=","value":3,"tablePrefix":"t","combiner":"OR"}],"filter_join":"OR","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE x = 'it''s' AND y = \"a\"\"b\"", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"x","op":"=","value":"it''s","tablePrefix":"t","combiner":"AND"},{"column":"y","op":"=","value":"a\"\"b","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE x = `a AND b`", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"x","op":"=","value":"`a AND b`","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a--c\n, b FROM t", {"table":"t","columns":["a","b"],"joins":[],"filters":[],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a =1\r\nAND b= 2\u00a0AND c=3\u2003OR d=4", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"=","value":1,"tablePrefix":"t","combiner":"AND"},{"column":"b","op":"=","value":2,"tablePrefix":"t","combiner":"AND"},{"column":"c","op":"=","value":3,"tablePrefix":"t","combiner":"AND"},{"column":"d","op":"=","value":4,"tablePrefix":"t","combiner":"OR"}],"filter_join":"OR","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a IS NOT   NULL AND b IS   NULL", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"IS NOT NULL","value":"","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"IS NULL","value":"","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a not   in (1)", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"NOT IN","value":"1","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a LIKE", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"LIKE","value":"","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a =", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"=","value":"","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a ==", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a =","op":"=","value":"","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE (a = 1) AND (b = 2 OR c = 3)", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"(a = 1)","op":"RAW","value":"","tablePrefix":"t","rawExpression":"(a = 1)","combiner":"AND"},{"column":"(b = 2 OR c = 3)","op":"RAW","value":"","tablePrefix":"t","rawExpression":"(b = 2 OR c = 3)","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a between 1 and 2 and b = 3", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"BETWEEN","value":"1 and 2","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"=","value":3,"tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE xBETWEEN 1 AND 2 OR z=1", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"xBETWEEN 1 AND 2","op":"RAW","value":"","tablePrefix":"t","rawExpression":"xBETWEEN 1 AND 2","combiner":"AND"},{"column":"z","op":"=","value":1,"tablePrefix":"t","combiner":"OR"}],"filter_join":"OR","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a BETWEEN  1  AND  2  AND  b  =  3  OR c BETWEEN 4 AND 5", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"BETWEEN","value":"1  AND  2","tablePrefix":"t","combiner":"AND"},{"column":"b","op":"=","value":3,"tablePrefix":"t","combiner":"AND"},{"column":"c","op":"BETWEEN","value":"4 AND 5","tablePrefix":"t","combiner":"OR"}],"filter_join":"OR","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a ANDREW b", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a ANDREW b","op":"RAW","value":"","tablePrefix":"t","rawExpression":"a ANDREW b","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a  ORDER b", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a  ORDER b","op":"RAW","value":"","tablePrefix":"t","rawExpression":"a  ORDER b","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
  ["SELECT a FROM t WHERE a = 1 ANDx", {"table":"t","columns":["a"],"joins":[],"filters":[{"column":"a","op":"=","value":"1 ANDx","tablePrefix":"t","combiner":"AND"}],"filter_join":"AND","order_by":[],"distinct":false,"limit":50}],
];

const SPLIT_CASES: [string, unknown][] = [
  ["a = 1 AND b = 2 or c = 3", [{"value": "a = 1", "delimiter": "AND"}, {"value": "b = 2", "delimiter": "OR"}, {"value": "c = 3"}]],
  ["a BETWEEN 1 AND 5 AND b = 2", [{"value": "a BETWEEN 1 AND 5", "delimiter": "AND"}, {"value": "b = 2"}]],
  ["a  \n AND\t(b OR c) and 'x AND y'", [{"value": "a", "delimiter": "AND"}, {"value": "(b OR c)", "delimiter": "AND"}, {"value": "'x AND y'"}]],
  ["xBETWEEN 1 AND 2 OR z", [{"value": "xBETWEEN 1 AND 2", "delimiter": "OR"}, {"value": "z"}]],
  ["a ANDx b", [{"value": "a ANDx b"}]],
  ["a OR", [{"value": "a OR"}]],
  ["a\u00a0OR\u00a0b", [{"value": "a", "delimiter": "OR"}, {"value": "b"}]],
  ["a between 1 and 2 or c between 3 and 4", [{"value": "a between 1 and 2", "delimiter": "OR"}, {"value": "c between 3 and 4"}]],
  ["", []],
];

describe("sqlParser regex rewrite: behavior identical to the original", () => {
  it.each(PARSE_CASES)("parseSqlToSpec %j", (sql, expected) => {
    expect(parseSqlToSpec(sql)).toEqual(expected);
  });

  it.each(SPLIT_CASES)("splitWhereConditions %j", (text, expected) => {
    expect(splitWhereConditions(text)).toEqual(expected);
  });
});

const N = 50000;
const SPACES = " ".repeat(N);
const BUDGET_MS = 1000;

const ADVERSARIAL: [string, string][] = [
  ["SELECT + spaces", "SELECT" + SPACES],
  ["WHERE + spaces", "SELECT a FROM t WHERE " + SPACES],
  ["spaces inside a WHERE condition", "SELECT a FROM t WHERE a" + SPACES + "b"],
  ["spaces before an operator", "SELECT a FROM t WHERE a" + SPACES + "= 1"],
  ["spaces around IS NOT NULL", "SELECT a FROM t WHERE a" + SPACES + "IS" + SPACES + "NOT" + SPACES + "NULL"],
  ["spaces around NOT EXISTS", "SELECT a FROM t WHERE " + SPACES + "NOT" + SPACES + "x"],
  ["spaces around AND", "SELECT a FROM t WHERE a = 1" + SPACES + "AND" + SPACES + "b = 2"],
  ["many AND/OR delimiters", "SELECT a FROM t WHERE a" + " AND b".repeat(N / 6) + " OR c".repeat(N / 5)],
  ["many BETWEEN keywords", "SELECT a FROM t WHERE a " + "BETWEEN ".repeat(N / 8)],
  ["long run of commas", "SELECT " + ",".repeat(N) + " FROM t"],
  ["trailing commas on the table", "SELECT a FROM t" + ",".repeat(N) + " x"],
  ["comma-separated tables", "SELECT a FROM " + "t,".repeat(N / 2)],
  ["opening parentheses", "SELECT a FROM t WHERE " + "(".repeat(N)],
  ["closing parentheses", "SELECT " + ")".repeat(N) + " FROM t"],
  ["unterminated single quotes", "SELECT a FROM t WHERE a = " + "'".repeat(N)],
  ["unterminated double quotes", "SELECT a FROM " + '"'.repeat(N)],
  ["unterminated brackets", "SELECT a FROM " + "[".repeat(N)],
  ["unterminated backticks", "SELECT a FROM " + "`".repeat(N)],
  ["dots in an ON clause", "SELECT a FROM t JOIN u ON " + ".".repeat(N)],
  ["dotted identifiers in an ON clause", "SELECT a FROM t JOIN u ON " + "a.".repeat(N / 2)],
  ["long identifiers in ON", "SELECT a FROM t JOIN u ON " + "a".repeat(N)],
  ["dashes", "SELECT a FROM t " + "-".repeat(N)],
  ["many line comments", "SELECT a FROM t " + "--\n".repeat(N / 3)],
  ["unterminated block comments", "SELECT a FROM t " + "/*".repeat(N / 2)],
  ["trailing semicolons", "SELECT a FROM t" + ";".repeat(N) + " x"],
  ["CTE with long whitespace", "WITH c AS (SELECT a FROM t" + SPACES + ") x SELECT a FROM c"],
  ["window function PARTITION BY spaces", "SELECT f(x) OVER (PARTITION BY a" + SPACES + "b) FROM t"],
  ["repeated PARTITION BY / ORDER BY", "SELECT f(x) OVER (" + "PARTITION BY ".repeat(N / 13) + "ORDER ".repeat(N / 6) + ") FROM t"],
  ["unterminated DATE_TRUNC", "SELECT DATE_TRUNC(month, x" + SPACES + " FROM t"],
  ["unterminated DATETRUNC", "SELECT DATETRUNC(month, x" + SPACES + " FROM t"],
  ["unterminated COUNT(DISTINCT", "SELECT COUNT(DISTINCT" + SPACES + " FROM t"],
  ["unterminated FILTER (WHERE", "SELECT SUM(a) FILTER (WHERE x" + SPACES + " FROM t"],
];

describe("sqlParser regex rewrite: linear time on adversarial input", () => {
  it.each(ADVERSARIAL)("%s", (_name, sql) => {
    const start = performance.now();
    parseSqlToSpec(sql);
    expect(performance.now() - start).toBeLessThan(BUDGET_MS);
  });

  it("splitWhereConditions handles a long whitespace run quickly", () => {
    const start = performance.now();
    splitWhereConditions("a" + SPACES + "b");
    expect(performance.now() - start).toBeLessThan(BUDGET_MS);
  });
});
