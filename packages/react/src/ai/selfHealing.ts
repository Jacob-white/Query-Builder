/**
 * Client-Side Self-Healing Engine for AI-Generated QuerySpecs.
 */

import type { QuerySpec } from "../types";

function extractTableAndColumn(ref: string, defaultTable: string): [string, string] {
  const clean = ref.trim().replace(/["`\[\]]/g, "");
  if (clean.includes(".")) {
    const parts = clean.split(".");
    return [parts[0], parts.slice(1).join(".")];
  }
  return [defaultTable, clean];
}

export function autoHealClientQuerySpec(
  spec: Partial<QuerySpec>,
  schema?: any
): { healedSpec: QuerySpec; notes: string[] } {
  const notes: string[] = [];

  // 1. Primary Table Inference
  let primaryTable = (spec.table || "").trim();

  if (!primaryTable) {
    if (spec.columns && spec.columns.length > 0) {
      const firstCol = spec.columns[0];
      const colStr = typeof firstCol === "string" ? firstCol : firstCol.column;
      if (colStr && colStr.includes(".")) {
        primaryTable = colStr.split(".")[0];
        notes.push(`Inferred primary table '${primaryTable}' from column '${colStr}'.`);
      }
    }

    if (!primaryTable && spec.filters && spec.filters.length > 0) {
      const f = spec.filters[0];
      if (f.tablePrefix) {
        primaryTable = f.tablePrefix;
        notes.push(`Inferred primary table '${primaryTable}' from filter prefix.`);
      } else if (f.column && f.column.includes(".")) {
        primaryTable = f.column.split(".")[0];
        notes.push(`Inferred primary table '${primaryTable}' from filter column '${f.column}'.`);
      }
    }

    if (!primaryTable) {
      primaryTable = "data";
      notes.push("Assigned default primary table 'data'.");
    }
  }

  const activeTables: string[] = [primaryTable];
  const joins = spec.joins ? [...spec.joins] : [];

  for (const j of joins) {
    if (j.table && !activeTables.includes(j.table)) {
      activeTables.push(j.table);
    }
  }

  const referencedTables = new Set<string>();

  // Collect from columns
  if (spec.columns) {
    for (const c of spec.columns) {
      const ref = typeof c === "string" ? c : c.column;
      if (ref && ref !== "*") {
        const [tbl] = extractTableAndColumn(ref, primaryTable);
        referencedTables.add(tbl);
      }
    }
  }

  // Collect from filters
  if (spec.filters) {
    for (const f of spec.filters) {
      if (f.tablePrefix) {
        referencedTables.add(f.tablePrefix);
      } else if (f.column && f.column.includes(".")) {
        const [tbl] = extractTableAndColumn(f.column, primaryTable);
        referencedTables.add(tbl);
      }
    }
  }

  // Collect from order_by
  if (spec.order_by) {
    for (const o of spec.order_by) {
      if (o.tablePrefix) {
        referencedTables.add(o.tablePrefix);
      } else if (o.column && o.column.includes(".")) {
        const [tbl] = extractTableAndColumn(o.column, primaryTable);
        referencedTables.add(tbl);
      }
    }
  }

  // 2. Synthesize Missing Joins
  for (const targetTable of referencedTables) {
    if (targetTable && targetTable !== primaryTable && !activeTables.includes(targetTable)) {
      // Find foreign key relationship in schema if present
      let leftCol = "id";
      let rightCol = `${primaryTable}_id`;

      if (schema && schema.tables && schema.tables[targetTable]) {
        const targetMeta = schema.tables[targetTable];
        const fks = targetMeta.foreign_keys || targetMeta.foreignKeys || [];
        const matchingFk = fks.find((fk: any) => fk.target_table === primaryTable || fk.targetTable === primaryTable);
        if (matchingFk) {
          leftCol = matchingFk.target_column || matchingFk.targetColumn || "id";
          rightCol = matchingFk.column || matchingFk.foreign_column || "id";
        }
      }

      joins.push({
        type: "LEFT JOIN",
        table: targetTable,
        left_table: primaryTable,
        left_col: leftCol,
        right_col: rightCol,
      });
      activeTables.push(targetTable);
      notes.push(`Auto-synthesized join: LEFT JOIN \`${targetTable}\` ON ${primaryTable}.${leftCol} = ${targetTable}.${rightCol}.`);
    }
  }

  const healedSpec: QuerySpec = {
    table: primaryTable,
    columns: spec.columns && spec.columns.length > 0 ? spec.columns : ["*"],
    joins,
    filters: spec.filters || [],
    filter_join: spec.filter_join || "AND",
    order_by: spec.order_by || [],
    distinct: spec.distinct || false,
    limit: spec.limit || 50,
    offset: spec.offset,
  };

  return { healedSpec, notes };
}
