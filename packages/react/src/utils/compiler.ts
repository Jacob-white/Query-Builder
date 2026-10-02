import type {
  VisualColumnSelect,
  VisualFilter,
  VisualJoin,
  VisualSort,
  SchemaSnapshot,
} from "../types";

export interface CompiledVisualQuery {
  sql: string;
  spec: {
    table: string;
    columns: (string | { column: string; agg?: string; alias?: string })[];
    joins: {
      table: string;
      type: string;
      on?: { left: string; right: string }[];
      left_table?: string;
      left_col?: string;
      right_col?: string;
    }[];
    filters: {
      column: string;
      op: string;
      value: string | number | boolean;
      tablePrefix?: string;
    }[];
    filter_join: "AND" | "OR";
    order_by: { column: string; direction: "ASC" | "DESC" }[];
    distinct: boolean;
    limit: number;
  };
}

export function compileVisualState(
  primaryTable: string,
  selectedColumns: Record<string, VisualColumnSelect>,
  orderedProjectionKeys: string[],
  joins: VisualJoin[],
  filters: VisualFilter[],
  sorts: VisualSort[],
  isDistinct: boolean = false,
  limit: number = 50,
  schemaData?: SchemaSnapshot | null,
): CompiledVisualQuery {
  if (!primaryTable) {
    return {
      sql: "",
      spec: {
        table: "",
        columns: [],
        joins: [],
        filters: [],
        filter_join: "AND",
        order_by: [],
        distinct: false,
        limit,
      },
    };
  }

  const cleanPrimary = primaryTable.replace(/^(\w+\.)/, "");
  const hasAggregates = orderedProjectionKeys.some(
    (k) => selectedColumns[k]?.aggregate,
  );

  // Projections
  let selectClause = "*";
  const specColumns: (string | { column: string; agg?: string; alias?: string })[] = [];

  if (orderedProjectionKeys.length > 0) {
    selectClause = orderedProjectionKeys
      .map((compositeKey) => {
        const item = selectedColumns[compositeKey];
        if (!item) return "";
        const tableAlias = item.table || cleanPrimary;
        const colRef = `"${tableAlias}"."${item.name}"`;

        if (item.aggregate) {
          const alias = item.alias || `${item.aggregate.toLowerCase()}_${item.name}`;
          specColumns.push({
            column: `${tableAlias}.${item.name}`,
            agg: item.aggregate.toLowerCase(),
            alias,
          });
          return `${item.aggregate}(${colRef}) AS "${alias}"`;
        }

        if (item.alias) {
          specColumns.push({
            column: `${tableAlias}.${item.name}`,
            alias: item.alias,
          });
          return `${colRef} AS "${item.alias}"`;
        }

        specColumns.push(`${tableAlias}.${item.name}`);
        return colRef;
      })
      .filter(Boolean)
      .join(", ");
  } else {
    specColumns.push("*");
  }

  if (isDistinct && !hasAggregates) {
    selectClause = `DISTINCT ${selectClause}`;
  }

  const fromClause = `FROM "${cleanPrimary}"`;

  // Joins
  const specJoins: CompiledVisualQuery["spec"]["joins"] = [];
  const joinClauses = joins.map((j) => {
    const leftTbl = (j.left_table || cleanPrimary).replace(/^(\w+\.)/, "");
    const rightTbl = j.table.replace(/^(\w+\.)/, "");
    const joinType = j.type || "LEFT JOIN";

    specJoins.push({
      table: rightTbl,
      type: joinType.replace(" JOIN", ""),
      left_table: leftTbl,
      left_col: j.left_col,
      right_col: j.right_col,
      on: [{ left: `${leftTbl}.${j.left_col}`, right: `${rightTbl}.${j.right_col}` }],
    });

    return `${joinType} "${rightTbl}" ON "${leftTbl}"."${j.left_col}" = "${rightTbl}"."${j.right_col}"`;
  });

  // Filters
  const activeFilters = filters.filter((f) => f.column && f.operator);
  const specFilters: CompiledVisualQuery["spec"]["filters"] = [];
  let whereClause = "";

  if (activeFilters.length > 0) {
    const parts: string[] = [];
    activeFilters.forEach((f) => {
      const tbl = (f.tablePrefix || cleanPrimary).replace(/^(\w+\.)/, "");
      const colRef = `"${tbl}"."${f.column}"`;
      let expr = "";

      specFilters.push({
        column: f.column,
        op: f.operator.toLowerCase().replace(" ", "_"),
        value: f.value,
        tablePrefix: tbl,
      });

      if (f.operator === "IS NULL" || f.operator === "IS NOT NULL") {
        expr = `${colRef} ${f.operator}`;
      } else if (f.operator === "STARTS_WITH") {
        const clean = f.value.replace(/'/g, "''");
        expr = `${colRef} ILIKE '${clean}%'`;
      } else if (f.operator === "ENDS_WITH") {
        const clean = f.value.replace(/'/g, "''");
        expr = `${colRef} ILIKE '%${clean}'`;
      } else if (f.operator === "CONTAINS") {
        const clean = f.value.replace(/'/g, "''");
        expr = `${colRef} ILIKE '%${clean}%'`;
      } else if (f.operator === "LIKE" || f.operator === "ILIKE") {
        const clean = f.value.replace(/'/g, "''");
        expr = `${colRef} ${f.operator} '${clean}'`;
      } else if (f.operator === "IN" || f.operator === "NOT IN") {
        const items = f.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .map((s) => (isNaN(Number(s)) ? `'${s.replace(/'/g, "''")}'` : s));
        expr = `${colRef} ${f.operator} (${items.join(", ") || "NULL"})`;
      } else if (f.operator === "BETWEEN") {
        const bounds = f.value.includes(" AND ") ? f.value.split(" AND ") : f.value.split(",");
        if (bounds.length === 2) {
          const v0 = isNaN(Number(bounds[0])) ? `'${bounds[0].trim().replace(/'/g, "''")}'` : bounds[0].trim();
          const v1 = isNaN(Number(bounds[1])) ? `'${bounds[1].trim().replace(/'/g, "''")}'` : bounds[1].trim();
          expr = `${colRef} BETWEEN ${v0} AND ${v1}`;
        }
      } else {
        const isNum = !isNaN(Number(f.value)) && f.value.trim() !== "";
        const valEscaped = isNum ? f.value : `'${f.value.replace(/'/g, "''")}'`;
        expr = `${colRef} ${f.operator} ${valEscaped}`;
      }

      if (expr) {
        parts.push(expr);
      }
    });

    if (parts.length > 0) {
      whereClause = `WHERE ${parts.join(" AND ")}`;
    }
  }

  // Sorts
  const activeSorts = sorts.filter((s) => s.column);
  const specSorts: CompiledVisualQuery["spec"]["order_by"] = [];
  let orderClause = "";

  if (activeSorts.length > 0) {
    const sortParts = activeSorts.map((s) => {
      const tbl = (s.tablePrefix || cleanPrimary).replace(/^(\w+\.)/, "");
      specSorts.push({ column: `${tbl}.${s.column}`, direction: s.direction });
      return `"${tbl}"."${s.column}" ${s.direction}`;
    });
    orderClause = `ORDER BY ${sortParts.join(", ")}`;
  }

  const queryParts = [`SELECT ${selectClause}`, fromClause];
  if (joinClauses.length > 0) queryParts.push(...joinClauses);
  if (whereClause) queryParts.push(whereClause);
  if (orderClause) queryParts.push(orderClause);
  queryParts.push(`LIMIT ${limit};`);

  return {
    sql: queryParts.join("\n"),
    spec: {
      table: cleanPrimary,
      columns: specColumns,
      joins: specJoins,
      filters: specFilters,
      filter_join: "AND",
      order_by: specSorts,
      distinct: isDistinct,
      limit,
    },
  };
}
