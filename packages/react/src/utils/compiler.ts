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

const ALLOWED_OPERATORS = new Set([
  "=",
  "!=",
  ">",
  "<",
  ">=",
  "<=",
  "STARTS_WITH",
  "ENDS_WITH",
  "CONTAINS",
  "LIKE",
  "ILIKE",
  "IN",
  "NOT IN",
  "BETWEEN",
  "IS NULL",
  "IS NOT NULL",
]);

const ALLOWED_AGGREGATES = new Set(["COUNT", "SUM", "AVG", "MIN", "MAX"]);

const sanitizeIdent = (s: string) =>
  (s || "").replace(/[\x00-\x1f\x7f]/g, "").replace(/"/g, '""');

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
  if (!primaryTable || typeof primaryTable !== "string") {
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

  const cleanPrimary = sanitizeIdent(primaryTable.replace(/^(\w+\.)/, ""));
  const hasAggregates = orderedProjectionKeys.some(
    (k) => selectedColumns[k]?.aggregate && ALLOWED_AGGREGATES.has(selectedColumns[k]?.aggregate || ""),
  );

  // Projections
  let selectClause = "*";
  const specColumns: (string | { column: string; agg?: string; alias?: string })[] = [];

  const safeProjectionKeys = (orderedProjectionKeys || []).slice(0, 100);

  if (safeProjectionKeys.length > 0) {
    selectClause = safeProjectionKeys
      .map((compositeKey) => {
        const item = selectedColumns[compositeKey];
        if (!item) return "";
        const tableAlias = sanitizeIdent(item.table || cleanPrimary);
        const colName = sanitizeIdent(item.name);
        const colRef = `"${tableAlias}"."${colName}"`;

        const aggUpper = (item.aggregate || "").toUpperCase();
        if (aggUpper && ALLOWED_AGGREGATES.has(aggUpper)) {
          const alias = sanitizeIdent(item.alias || `${aggUpper.toLowerCase()}_${item.name}`);
          specColumns.push({
            column: `${tableAlias}.${colName}`,
            agg: aggUpper.toLowerCase(),
            alias,
          });
          return `${aggUpper}(${colRef}) AS "${alias}"`;
        }

        if (item.alias) {
          const alias = sanitizeIdent(item.alias);
          specColumns.push({
            column: `${tableAlias}.${colName}`,
            alias,
          });
          return `${colRef} AS "${alias}"`;
        }

        specColumns.push(`${tableAlias}.${colName}`);
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
  const validJoinTypes = new Set(["LEFT JOIN", "INNER JOIN", "RIGHT JOIN", "FULL JOIN"]);
  const specJoins: CompiledVisualQuery["spec"]["joins"] = [];
  const safeJoins = (joins || []).slice(0, 20);
  const joinClauses = safeJoins.map((j) => {
    const leftTbl = sanitizeIdent((j.left_table || cleanPrimary).replace(/^(\w+\.)/, ""));
    const rightTbl = sanitizeIdent(j.table.replace(/^(\w+\.)/, ""));
    const leftCol = sanitizeIdent(j.left_col);
    const rightCol = sanitizeIdent(j.right_col);
    const joinType = validJoinTypes.has(j.type) ? j.type : "LEFT JOIN";

    specJoins.push({
      table: rightTbl,
      type: joinType.replace(" JOIN", ""),
      left_table: leftTbl,
      left_col: leftCol,
      right_col: rightCol,
      on: [{ left: `${leftTbl}.${leftCol}`, right: `${rightTbl}.${rightCol}` }],
    });

    return `${joinType} "${rightTbl}" ON "${leftTbl}"."${leftCol}" = "${rightTbl}"."${rightCol}"`;
  });

  // Filters
  const activeFilters = (filters || [])
    .slice(0, 50)
    .filter((f) => f.column && f.operator && ALLOWED_OPERATORS.has(f.operator));
  const specFilters: CompiledVisualQuery["spec"]["filters"] = [];
  let whereClause = "";

  if (activeFilters.length > 0) {
    const parts: string[] = [];
    activeFilters.forEach((f) => {
      const tbl = sanitizeIdent((f.tablePrefix || cleanPrimary).replace(/^(\w+\.)/, ""));
      const colName = sanitizeIdent(f.column);
      const colRef = `"${tbl}"."${colName}"`;
      const valStr = String(f.value ?? "");
      let expr = "";

      specFilters.push({
        column: colName,
        op: f.operator.toLowerCase().replace(" ", "_"),
        value: f.value,
        tablePrefix: tbl,
      });

      if (f.operator === "IS NULL" || f.operator === "IS NOT NULL") {
        expr = `${colRef} ${f.operator}`;
      } else if (f.operator === "STARTS_WITH") {
        const clean = valStr.replace(/'/g, "''");
        expr = `${colRef} ILIKE '${clean}%'`;
      } else if (f.operator === "ENDS_WITH") {
        const clean = valStr.replace(/'/g, "''");
        expr = `${colRef} ILIKE '%${clean}'`;
      } else if (f.operator === "CONTAINS") {
        const clean = valStr.replace(/'/g, "''");
        expr = `${colRef} ILIKE '%${clean}%'`;
      } else if (f.operator === "LIKE" || f.operator === "ILIKE") {
        const clean = valStr.replace(/'/g, "''");
        expr = `${colRef} ${f.operator} '${clean}'`;
      } else if (f.operator === "IN" || f.operator === "NOT IN") {
        const items = valStr
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 500)
          .map((s) => (!isNaN(Number(s)) && isFinite(Number(s)) && s !== "" ? s : `'${s.replace(/'/g, "''")}'`));
        expr = `${colRef} ${f.operator} (${items.join(", ") || "NULL"})`;
      } else if (f.operator === "BETWEEN") {
        const bounds = valStr.includes(" AND ")
          ? valStr.split(" AND ")
          : valStr.split(",");
        if (bounds.length === 2) {
          const b0 = bounds[0].trim();
          const b1 = bounds[1].trim();
          const v0 = !isNaN(Number(b0)) && isFinite(Number(b0)) && b0 !== ""
            ? b0
            : `'${b0.replace(/'/g, "''")}'`;
          const v1 = !isNaN(Number(b1)) && isFinite(Number(b1)) && b1 !== ""
            ? b1
            : `'${b1.replace(/'/g, "''")}'`;
          expr = `${colRef} BETWEEN ${v0} AND ${v1}`;
        }
      } else {
        const isNum = typeof f.value === "number"
          ? isFinite(f.value)
          : !isNaN(Number(f.value)) && isFinite(Number(f.value)) && valStr.trim() !== "";
        const valEscaped = isNum ? String(f.value) : `'${valStr.replace(/'/g, "''")}'`;
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
  const activeSorts = (sorts || []).slice(0, 20).filter((s) => s.column);
  const specSorts: CompiledVisualQuery["spec"]["order_by"] = [];
  let orderClause = "";

  if (activeSorts.length > 0) {
    const sortParts = activeSorts.map((s) => {
      const tbl = sanitizeIdent((s.tablePrefix || cleanPrimary).replace(/^(\w+\.)/, ""));
      const colName = sanitizeIdent(s.column);
      const direction = s.direction === "DESC" ? "DESC" : "ASC";
      specSorts.push({ column: `${tbl}.${colName}`, direction });
      return `"${tbl}"."${colName}" ${direction}`;
    });
    orderClause = `ORDER BY ${sortParts.join(", ")}`;
  }

  // Group By
  let groupClause = "";
  if (hasAggregates) {
    const nonAggCols = safeProjectionKeys
      .map((k) => selectedColumns[k])
      .filter((item): item is VisualColumnSelect => Boolean(item && !item.aggregate))
      .map((item) => {
        const tbl = sanitizeIdent(item.table || cleanPrimary);
        const colName = sanitizeIdent(item.name);
        return `"${tbl}"."${colName}"`;
      });
    if (nonAggCols.length > 0) {
      groupClause = `GROUP BY ${nonAggCols.join(", ")}`;
    }
  }

  const queryParts = [`SELECT ${selectClause}`, fromClause];
  if (joinClauses.length > 0) queryParts.push(...joinClauses);
  if (whereClause) queryParts.push(whereClause);
  if (groupClause) queryParts.push(groupClause);
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
