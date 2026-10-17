# Building an AI query helper on Query-Builder: patterns that worked

A helper that turns a plain-English request into a query spec (`QuerySpec`) is only as good as what it is told about the
data and how its answer is checked. These patterns came from building one on top of this library. They are advice, not a
required design; each says which part of the library backs it.

The rule underneath all of them: **the model proposes, the library disposes.** Every answer goes through the same
validation as a hand-written spec (`QueryCompiler`, `validate_sql_ast`, your table allowlist) before anything runs, and the
model is never sent row values, only names, links, descriptions and counts.

## 1. Show the model the right tables, not all of them

A large schema does not fit a prompt usefully. Shortlist by the words in the request: tables whose names match, then the
tables that **connect** them. A request such as "orders by customer region" names tables that are several links apart, and a
model shown only the two ends cannot write the join between them, so it invents one. Find the shortest route over *declared*
links (`find_join_path` in `query_builder.join_solver` does this) and show every table on it.

- **Do not bridge through staging or plumbing tables.** A table of unprocessed incoming rows, or one that everything links to
  for bookkeeping (which file or run a row came from), makes a short route that joins by where rows were loaded from, not by
  what they mean. Prefer a longer route through meaningful tables, and use the short one only when nothing else connects the
  two.
- **List every other table with a one-line description**, capped by a budget, so the model can find one your keyword match
  missed.

## 2. Say what the words mean, as data

"Customer", "fund" or "territory" is rarely a table name. Keep a small reviewed file (a glossary) mapping a word to the
tables that hold it and one or two sentences on how to use them. Feed the matching entries into both the shortlist and the
prompt. Check the file in a test against the real schema, so an entry naming a renamed column fails the build.

Add worked examples the same way: a few verified request-and-spec pairs, shown when a new request resembles one, each
compiled in a test so a stale one fails the build.

## 3. Tell it about history and staging from the schema itself

If a table keeps history (an end-date column whose live value is a sentinel), say so for every such table, generated from the
columns, rather than writing one rule per table. Do the same for staging tables. A rule written once for one table is missed
on the next.

## 4. Refuse before the database does

- **Unknown columns:** `check_columns(spec, schema)` raises `SpecColumnError` naming the column, suggesting the likeliest real
  one and listing the table's columns. Send that message back to the model for one repair attempt.
- **Joins:** require each join to name its kind and its columns, and to follow a declared link. The compiler reads a join with
  no kind as a left join and one with no columns as `id = id`, which are the two silent ways to get a wrong result.
- **Sorting:** a total or a count is sorted by its alias (`order_by` `{"column": "n"}` with no table prefix).

## 5. Find out when a valid answer is empty, with counts only

A valid query can match nothing (a join through a column nobody fills, a value in the wrong format). Run a read-only count
with a short timeout. If it is zero, work out why **using counts only**: the count without the filters, then the count after
each join in turn, and send the model the reason ("without its filters it returns N rows" or "the join to X leaves no rows").
Rule out the route that matched nothing and show the next best one. Never send rows. A count that fails or times out must
never block an answer.

## 6. Ask for the model's reading, and for alternatives when it is ambiguous

Have the model return, beside the spec, one plain sentence saying how it read the request and what each filter value means,
and show it. For a request with more than one sensible reading, let it offer up to three alternatives as short sentences the
person can pick; picking one re-asks with the reading added.

## 7. Prefer readable columns and a steady order

Tell the model to select names, codes, numbers and dates, not ids, unless ids were asked for. Add a sort if the answer has
none (the first readable column), so pages come back in a steady order. Show headers without the table prefix where the short
names are unique.

## 8. Measure it

Keep a fixed set of real questions with what each answer must use, must avoid and whether it must return rows. Check offline
(in CI) that the tables each question needs reach the prompt, and run the set against the real model by hand before and after
a prompt or model change. Include reworded versions of questions that have worked examples, or the examples will be
what passes. Mark a request the helper cannot yet handle as a known limit, so it stays visible. Run `query-builder schema
--audit` to find id columns with no declared link and tables and columns with no description before a user does.

## 9. Record what happens

One structured log line per request: the request (cut short), who answered, the tables used, whether it fell back to a keyword
matcher or came back empty, and the time. No filter values and no rows.
