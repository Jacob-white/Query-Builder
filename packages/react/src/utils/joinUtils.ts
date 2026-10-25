import type { SchemaSnapshot, VisualJoin } from "../types";

export type JoinTier = "confirmed" | "logical" | "none";
export type JoinTierLabel = "Confirmed Join" | "Logical Join" | "No Dedicated Join";

export interface JoinConditionMatch {
  leftTable: string;
  leftCol: string;
  rightTable: string;
  rightCol: string;
  isFk: boolean;
  joinTier?: JoinTier;
  joinLabel?: JoinTierLabel;
  reason?: string;
}

const CANONICAL_IDS = [
  "id",
  "user_id",
  "customer_id",
  "order_id",
  "account_id",
  "organization_id",
  "company_id",
  "project_id",
  "goal_id",
  "task_id",
  "session_id",
  "customer_master_id",
  "contact_master_id",
  "contact_id",
  "address_master_id",
  "address_id",
  "product_id",
  "category_id",
  "account_number",
  "registration_number",
];

const LOGICAL_KEY_SUFFIXES = ["_id", "_number", "_uuid", "_code", "_key"];

export const MAX_JOIN_DEPTH = 10;
export const MAX_BFS_ITERATIONS = 2000;
export const MAX_ACTIVE_TABLES = 50;

export function findBestJoinCondition(
  leftTable: string,
  rightTable: string,
  schemaData?: SchemaSnapshot | null,
): JoinConditionMatch {
  const cleanLeft = (leftTable || "").replace(/^(\w+\.)/, "");
  const cleanRight = (rightTable || "").replace(/^(\w+\.)/, "");

  if (!cleanLeft || !cleanRight) {
    return {
      leftTable: cleanLeft || "t1",
      leftCol: "id",
      rightTable: cleanRight || "t2",
      rightCol: "id",
      isFk: false,
      joinTier: "none",
      joinLabel: "No Dedicated Join",
      reason: "Fallback condition for empty/invalid table name",
    };
  }

  const leftCols = schemaData?.tables?.[cleanLeft]?.columns || [];
  const rightCols = schemaData?.tables?.[cleanRight]?.columns || [];
  const leftColNames = new Set(
    leftCols.map((c) => c?.name).filter((n): n is string => typeof n === "string"),
  );
  const rightColNames = new Set(
    rightCols.map((c) => c?.name).filter((n): n is string => typeof n === "string"),
  );

  // 1. Explicit Schema Foreign Keys -> Confirmed Join
  if (schemaData?.foreign_keys && Array.isArray(schemaData.foreign_keys)) {
    const directFk = schemaData.foreign_keys.find(
      (fk) => fk.table === cleanRight && fk.foreign_table === cleanLeft,
    );
    if (
      directFk &&
      leftColNames.has(directFk.foreign_column) &&
      rightColNames.has(directFk.column)
    ) {
      return {
        leftTable: cleanLeft,
        leftCol: directFk.foreign_column,
        rightTable: cleanRight,
        rightCol: directFk.column,
        isFk: true,
        joinTier: "confirmed",
        joinLabel: "Confirmed Join",
        reason: "Schema foreign key constraint",
      };
    }

    const reverseFk = schemaData.foreign_keys.find(
      (fk) => fk.table === cleanLeft && fk.foreign_table === cleanRight,
    );
    if (
      reverseFk &&
      leftColNames.has(reverseFk.column) &&
      rightColNames.has(reverseFk.foreign_column)
    ) {
      return {
        leftTable: cleanLeft,
        leftCol: reverseFk.column,
        rightTable: cleanRight,
        rightCol: reverseFk.foreign_column,
        isFk: true,
        joinTier: "confirmed",
        joinLabel: "Confirmed Join",
        reason: "Schema foreign key constraint",
      };
    }
  }

  // 1b. Explicit Schema Relationships -> Confirmed Join
  if (schemaData?.relationships && Array.isArray(schemaData.relationships)) {
    const directRel = schemaData.relationships.find(
      (rel) => rel.source_table === cleanRight && rel.target_table === cleanLeft,
    );
    if (
      directRel &&
      (leftColNames.size === 0 || leftColNames.has(directRel.target_column)) &&
      (rightColNames.size === 0 || rightColNames.has(directRel.source_column))
    ) {
      return {
        leftTable: cleanLeft,
        leftCol: directRel.target_column,
        rightTable: cleanRight,
        rightCol: directRel.source_column,
        isFk: true,
        joinTier: "confirmed",
        joinLabel: "Confirmed Join",
        reason: "Schema foreign key constraint",
      };
    }

    const reverseRel = schemaData.relationships.find(
      (rel) => rel.source_table === cleanLeft && rel.target_table === cleanRight,
    );
    if (
      reverseRel &&
      (leftColNames.size === 0 || leftColNames.has(reverseRel.source_column)) &&
      (rightColNames.size === 0 || rightColNames.has(reverseRel.target_column))
    ) {
      return {
        leftTable: cleanLeft,
        leftCol: reverseRel.source_column,
        rightTable: cleanRight,
        rightCol: reverseRel.target_column,
        isFk: true,
        joinTier: "confirmed",
        joinLabel: "Confirmed Join",
        reason: "Schema foreign key constraint",
      };
    }
  }

  // 2. Canonical Identifier Match -> Logical Join
  for (const col of CANONICAL_IDS) {
    if (col !== "id" && leftColNames.has(col) && rightColNames.has(col)) {
      return {
        leftTable: cleanLeft,
        leftCol: col,
        rightTable: cleanRight,
        rightCol: col,
        isFk: false,
        joinTier: "logical",
        joinLabel: "Logical Join",
        reason: `Canonical identifier match (${col})`,
      };
    }
  }

  // 3. Named Entity Foreign Key (e.g. users -> orders with users_id or user_id) -> Logical Join
  const rightFk = `${cleanLeft}_id`;
  if (rightColNames.has(rightFk) && leftColNames.has("id")) {
    return {
      leftTable: cleanLeft,
      leftCol: "id",
      rightTable: cleanRight,
      rightCol: rightFk,
      isFk: true,
      joinTier: "logical",
      joinLabel: "Logical Join",
      reason: `Inferred foreign key (${cleanRight}.${rightFk} -> ${cleanLeft}.id)`,
    };
  }

  const leftFk = `${cleanRight}_id`;
  if (leftColNames.has(leftFk) && rightColNames.has("id")) {
    return {
      leftTable: cleanLeft,
      leftCol: leftFk,
      rightTable: cleanRight,
      rightCol: "id",
      isFk: true,
      joinTier: "logical",
      joinLabel: "Logical Join",
      reason: `Inferred foreign key (${cleanLeft}.${leftFk} -> ${cleanRight}.id)`,
    };
  }

  const getSingularVariants = (tbl: string): string[] => {
    const variants: string[] = [];
    if (tbl.endsWith("ies") && tbl.length > 3) {
      variants.push(`${tbl.slice(0, -3)}y`);
    }
    if (tbl.endsWith("es") && tbl.length > 2) {
      variants.push(tbl.slice(0, -2));
    }
    if (tbl.endsWith("s") && tbl.length > 1) {
      variants.push(tbl.slice(0, -1));
    }
    return variants;
  };

  for (const singularLeft of getSingularVariants(cleanLeft)) {
    if (rightColNames.has(`${singularLeft}_id`) && leftColNames.has("id")) {
      return {
        leftTable: cleanLeft,
        leftCol: "id",
        rightTable: cleanRight,
        rightCol: `${singularLeft}_id`,
        isFk: false,
        joinTier: "logical",
        joinLabel: "Logical Join",
        reason: `Logical foreign key (${cleanRight}.${singularLeft}_id -> ${cleanLeft}.id)`,
      };
    }
  }

  for (const singularRight of getSingularVariants(cleanRight)) {
    if (leftColNames.has(`${singularRight}_id`) && rightColNames.has("id")) {
      return {
        leftTable: cleanLeft,
        leftCol: `${singularRight}_id`,
        rightTable: cleanRight,
        rightCol: "id",
        isFk: false,
        joinTier: "logical",
        joinLabel: "Logical Join",
        reason: `Logical foreign key (${cleanLeft}.${singularRight}_id -> ${cleanRight}.id)`,
      };
    }
  }

  // Shared domain key column (e.g. both tables share *_id, *_number, *_uuid, *_code)
  for (const col of leftColNames) {
    const lower = col.toLowerCase();
    if (
      lower !== "id" &&
      rightColNames.has(col) &&
      LOGICAL_KEY_SUFFIXES.some((sfx) => lower.endsWith(sfx))
    ) {
      return {
        leftTable: cleanLeft,
        leftCol: col,
        rightTable: cleanRight,
        rightCol: col,
        isFk: false,
        joinTier: "logical",
        joinLabel: "Logical Join",
        reason: `Shared logical key (${col})`,
      };
    }
  }

  // 4. Primary Key Fallback -> No Dedicated Join
  const leftFallback =
    leftCols.find((c) => c.is_primary)?.name || leftCols[0]?.name || "id";
  const rightFallback =
    rightCols.find((c) => c.is_primary)?.name || rightCols[0]?.name || "id";

  return {
    leftTable: cleanLeft,
    leftCol: leftFallback,
    rightTable: cleanRight,
    rightCol: rightFallback,
    isFk: false,
    joinTier: "none",
    joinLabel: "No Dedicated Join",
    reason: "Primary key fallback",
  };
}

export function classifyJoinCondition(
  leftTable: string,
  leftCol: string,
  rightTable: string,
  rightCol: string,
  schemaData?: SchemaSnapshot | null,
): { joinTier: JoinTier; joinLabel: JoinTierLabel; reason: string } {
  const cleanLeft = (leftTable || "").replace(/^(\w+\.)/, "");
  const cleanRight = (rightTable || "").replace(/^(\w+\.)/, "");
  const lCol = (leftCol || "").trim();
  const rCol = (rightCol || "").trim();

  // 1. Check explicit schema foreign keys
  if (schemaData?.foreign_keys && Array.isArray(schemaData.foreign_keys)) {
    const isDirectFk = schemaData.foreign_keys.some(
      (fk) =>
        (fk.table === cleanLeft &&
          fk.column === lCol &&
          fk.foreign_table === cleanRight &&
          fk.foreign_column === rCol) ||
        (fk.table === cleanRight &&
          fk.column === rCol &&
          fk.foreign_table === cleanLeft &&
          fk.foreign_column === lCol),
    );
    if (isDirectFk) {
      return {
        joinTier: "confirmed",
        joinLabel: "Confirmed Join",
        reason: `Confirmed foreign key (${cleanLeft}.${lCol} = ${cleanRight}.${rCol})`,
      };
    }
  }

  const pairKey = `${cleanLeft}.${lCol}=${cleanRight}.${rCol}`;
  if (
    schemaData?.relationships?.some(
      (rel) =>
        `${rel.source_table}.${rel.source_column}=${rel.target_table}.${rel.target_column}` ===
          pairKey ||
        `${rel.target_table}.${rel.target_column}=${rel.source_table}.${rel.source_column}` ===
          pairKey,
    )
  ) {
    return {
      joinTier: "confirmed",
      joinLabel: "Confirmed Join",
      reason: `Confirmed foreign key (${cleanLeft}.${lCol} = ${cleanRight}.${rCol})`,
    };
  }

  // 2. Check logical join patterns on the selected columns
  const lowerL = lCol.toLowerCase();
  const lowerR = rCol.toLowerCase();
  const singularLeft = cleanLeft.endsWith("ies")
    ? `${cleanLeft.slice(0, -3).toLowerCase()}y`
    : cleanLeft.endsWith("s")
      ? cleanLeft.slice(0, -1).toLowerCase()
      : cleanLeft.toLowerCase();
  const singularRight = cleanRight.endsWith("ies")
    ? `${cleanRight.slice(0, -3).toLowerCase()}y`
    : cleanRight.endsWith("s")
      ? cleanRight.slice(0, -1).toLowerCase()
      : cleanRight.toLowerCase();

  const isNamedEntityMatch =
    (lowerL === "id" && (lowerR === `${cleanLeft.toLowerCase()}_id` || lowerR === `${singularLeft}_id`)) ||
    (lowerR === "id" && (lowerL === `${cleanRight.toLowerCase()}_id` || lowerL === `${singularRight}_id`));

  const isSharedKeyMatch =
    lowerL &&
    lowerL === lowerR &&
    lowerL !== "id" &&
    (CANONICAL_IDS.includes(lowerL) || LOGICAL_KEY_SUFFIXES.some((sfx) => lowerL.endsWith(sfx)));

  const isCrossAliasMatch =
    (lowerL.endsWith("_master_id") && lowerL.replace("_master_id", "_id") === lowerR) ||
    (lowerR.endsWith("_master_id") && lowerR.replace("_master_id", "_id") === lowerL) ||
    (lowerR.endsWith("_number") && lowerL.endsWith(`_${lowerR}`)) ||
    (lowerL.endsWith("_number") && lowerR.endsWith(`_${lowerL}`));

  if (isNamedEntityMatch || isSharedKeyMatch || isCrossAliasMatch) {
    return {
      joinTier: "logical",
      joinLabel: "Logical Join",
      reason: `Logical identifier match (${cleanLeft}.${lCol} = ${cleanRight}.${rCol})`,
    };
  }

  return {
    joinTier: "none",
    joinLabel: "No Dedicated Join",
    reason: `No dedicated join key (${cleanLeft}.${lCol} = ${cleanRight}.${rCol})`,
  };
}

export interface MultiHopJoinPathResult {
  joins: VisualJoin[];
  bridgeTables: string[];
  isConnected: boolean;
}

export function findMultiHopJoinPath(
  activeTables: string[],
  targetTable: string,
  schemaData?: SchemaSnapshot | null,
): MultiHopJoinPathResult {
  if (!targetTable || typeof targetTable !== "string") {
    return { joins: [], bridgeTables: [], isConnected: false };
  }
  if (!Array.isArray(activeTables) || activeTables.length === 0) {
    return { joins: [], bridgeTables: [], isConnected: false };
  }

  const cleanTarget = targetTable.replace(/^(\w+\.)/, "");
  let cleanActive = activeTables.map((t) => (t || "").replace(/^(\w+\.)/, "")).filter(Boolean);

  if (cleanActive.includes(cleanTarget) || cleanActive.length === 0) {
    return { joins: [], bridgeTables: [], isConnected: false };
  }

  if (cleanActive.length > MAX_ACTIVE_TABLES) {
    cleanActive = cleanActive.slice(0, MAX_ACTIVE_TABLES);
  }

  const adj = new Map<string, Set<string>>();
  const getAdj = (t: string) => {
    if (!adj.has(t)) adj.set(t, new Set());
    return adj.get(t)!;
  };

  // Build Adjacency Graph from Schema FKs
  if (schemaData?.foreign_keys && Array.isArray(schemaData.foreign_keys)) {
    for (const fk of schemaData.foreign_keys) {
      if (fk.table && fk.foreign_table) {
        getAdj(fk.table).add(fk.foreign_table);
        getAdj(fk.foreign_table).add(fk.table);
      }
    }
  }

  // Also include explicit schema relationships if present
  if (schemaData?.relationships && Array.isArray(schemaData.relationships)) {
    for (const rel of schemaData.relationships) {
      if (rel.source_table && rel.target_table) {
        getAdj(rel.source_table).add(rel.target_table);
        getAdj(rel.target_table).add(rel.source_table);
      }
    }
  }

  // Entity Bridges (singular and plural table variants)
  if (schemaData?.tables) {
    for (const [tblName, meta] of Object.entries(schemaData.tables)) {
      if (!meta || !Array.isArray(meta.columns)) continue;
      const colNames = meta.columns
        .map((c) => c?.name)
        .filter((n): n is string => typeof n === "string");
      for (const col of colNames) {
        if (col.endsWith("_id") && col.length > 3) {
          const base = col.replace(/_id$/, "");
          const candidates = [
            base,
            `${base}s`,
            `${base}es`,
            base.endsWith("y") ? `${base.slice(0, -1)}ies` : "",
          ].filter(Boolean);
          for (const cand of candidates) {
            if (cand !== tblName && schemaData.tables[cand]) {
              getAdj(cand).add(tblName);
              getAdj(tblName).add(cand);
            }
          }
        }
      }
    }
  }

  // Breadth-First Search (BFS) prioritizing confirmed FK/relationship paths over inferred bridges of equal length
  const queue: { table: string; path: VisualJoin[]; score: number }[] = [];
  const bestScore = new Map<string, number>();

  for (const startTable of cleanActive) {
    bestScore.set(startTable, 0);
    queue.push({ table: startTable, path: [], score: 0 });
  }

  let iterations = 0;
  while (queue.length > 0 && iterations < MAX_BFS_ITERATIONS) {
    iterations++;
    let minIdx = 0;
    for (let i = 1; i < queue.length; i++) {
      if (queue[i].score < queue[minIdx].score) {
        minIdx = i;
      }
    }
    const { table: current, path, score } = queue.splice(minIdx, 1)[0];
    if (current === cleanTarget) {
      const bridgeTables = path.slice(0, -1).map((j) => j.table);
      return { joins: path, bridgeTables, isConnected: true };
    }

    if (path.length >= MAX_JOIN_DEPTH) {
      continue;
    }

    const neighbors = adj.get(current);
    if (neighbors) {
      for (const neighbor of neighbors) {
        const cond = findBestJoinCondition(current, neighbor, schemaData);
        const stepCost = cond.joinTier === "confirmed" ? 99 : 100;
        const nextScore = score + stepCost;
        const prevBest = bestScore.get(neighbor);
        if (prevBest === undefined || nextScore < prevBest) {
          bestScore.set(neighbor, nextScore);
          const nextJoin: VisualJoin = {
            id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
            type: "LEFT JOIN",
            left_table: cond.leftTable,
            left_col: cond.leftCol,
            table: cond.rightTable,
            right_col: cond.rightCol,
          };
          queue.push({ table: neighbor, path: [...path, nextJoin], score: nextScore });
        }
      }
    }
  }

  // Fallback direct join
  const start = cleanActive[0];
  const cond = findBestJoinCondition(start, cleanTarget, schemaData);
  return {
    joins: [
      {
        id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
        type: "LEFT JOIN",
        left_table: cond.leftTable,
        left_col: cond.leftCol,
        table: cond.rightTable,
        right_col: cond.rightCol,
      },
    ],
    bridgeTables: [],
    isConnected: cond.joinTier !== "none",
  };
}

export function findJoinPath(
  activeTables: string[],
  targetTable: string,
  schemaData?: SchemaSnapshot | null,
): VisualJoin[] {
  return findMultiHopJoinPath(activeTables, targetTable, schemaData).joins;
}

