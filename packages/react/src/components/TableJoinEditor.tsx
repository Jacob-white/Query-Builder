import React from "react";
import type { VisualJoin, TableMeta, SchemaSnapshot, QueryBuilderClassNames } from "../types";
import {
  findBestJoinCondition,
  classifyJoinCondition,
  findMultiHopJoinPath,
  type JoinTier,
} from "../utils/joinUtils";
import { isProvenJoin } from "../utils/queryHelpers/joinLinks";
import { cx } from "../utils/classNames";

export interface TableJoinEditorProps {
  joins: VisualJoin[];
  activeTables: TableMeta[];
  allTables: TableMeta[];
  schema?: SchemaSnapshot | null;
  onChange: (joins: VisualJoin[]) => void;
  unstyled?: boolean;
  className?: string;
  classNames?: QueryBuilderClassNames;
}

const SR_ONLY_STYLE: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

const JOIN_TYPE_PILLS: {
  value: VisualJoin["type"];
  label: string;
  friendlyLabel: string;
  tooltip: string;
}[] = [
  {
    value: "LEFT JOIN",
    label: "LEFT",
    friendlyLabel: "Keep all rows (LEFT)",
    tooltip: "LEFT JOIN: Keep all rows from the primary table, even when there is no match",
  },
  {
    value: "INNER JOIN",
    label: "INNER",
    friendlyLabel: "Matches only (INNER)",
    tooltip: "INNER JOIN: Only include rows that match in both tables",
  },
  {
    value: "RIGHT JOIN",
    label: "RIGHT",
    friendlyLabel: "All joined (RIGHT)",
    tooltip: "RIGHT JOIN: Keep all rows from the joined table",
  },
  {
    value: "FULL JOIN",
    label: "FULL",
    friendlyLabel: "All both (FULL)",
    tooltip: "FULL JOIN: Keep all rows from both tables",
  },
];

export const TableJoinEditor: React.FC<TableJoinEditorProps> = ({
  joins,
  activeTables,
  allTables,
  schema,
  onChange,
  unstyled = false,
  className,
  classNames,
}) => {
  const [joinSearch, setJoinSearch] = React.useState("");
  const [joinTierFilter, setJoinTierFilter] = React.useState<"all" | JoinTier>("all");
  const [expandedColRowId, setExpandedColRowId] = React.useState<string | null>(null);
  const effectiveAllTables =
    allTables.length > 0 ? allTables : Object.values(schema?.tables || {});

  const effectiveSchema: SchemaSnapshot = schema || {
    tables: Object.fromEntries(effectiveAllTables.map((t) => [t.name, t])),
  };

  const getBestCandidateJoin = (targetTable: string) => {
    if (!targetTable || activeTables.length === 0) {
      return findBestJoinCondition("", targetTable, effectiveSchema);
    }
    const rank = (tier?: JoinTier) => (tier === "confirmed" ? 3 : tier === "logical" ? 2 : 1);
    let bestCond = findBestJoinCondition(activeTables[0].name, targetTable, effectiveSchema);
    for (let i = 1; i < activeTables.length; i++) {
      const candidate = findBestJoinCondition(activeTables[i].name, targetTable, effectiveSchema);
      if (rank(candidate.joinTier) > rank(bestCond.joinTier)) {
        bestCond = candidate;
      }
    }
    return bestCond;
  };

  const handleAddJoin = (targetTable: string) => {
    if (!targetTable || activeTables.length === 0) return;
    const bestCond = getBestCandidateJoin(targetTable);

    const newJoin: VisualJoin = {
      id: `join-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      type: "LEFT JOIN",
      left_table: bestCond.leftTable,
      left_col: bestCond.leftCol,
      table: bestCond.rightTable,
      right_col: bestCond.rightCol,
    };
    onChange([...joins, newJoin]);
  };

  const activeTableNames = React.useMemo(() => {
    const names = activeTables.map((a) => a.name);
    for (const j of joins) {
      if (j.table && !names.includes(j.table)) {
        names.push(j.table);
      }
    }
    return names;
  }, [activeTables, joins]);

  const handleAddMultiHopJoin = (targetTable: string) => {
    const multiHop = findMultiHopJoinPath(activeTableNames, targetTable, effectiveSchema);
    const existingTables = new Set(joins.map((j) => j.table));
    const newJoins = multiHop.joins.filter((j) => !existingTables.has(j.table));
    if (newJoins.length > 0) {
      onChange([...joins, ...newJoins]);
    }
  };

  const handleUpdate = (id: string, updates: Partial<VisualJoin>) => {
    onChange(joins.map((j) => (j.id === id ? { ...j, ...updates } : j)));
  };

  const handleRemove = (id: string) => {
    onChange(joins.filter((j) => j.id !== id));
  };

  // Tables in schema not yet joined (excluding primary table)
  const primaryTableName = activeTables[0]?.name;
  const joinedTableNames = new Set(joins.map((j) => j.table));
  const unjoinedTables = effectiveAllTables.filter(
    (t) =>
      t.name !== primaryTableName &&
      (!activeTables.some((a) => a.name === t.name) || !joinedTableNames.has(t.name)),
  );

  const leftColumnSuggestions = activeTables.flatMap((t) =>
    t.columns.map((c) => `${t.name}.${c.name}`),
  );

  const unjoinedWithMatch = unjoinedTables.map((t) => {
    const match = getBestCandidateJoin(t.name);
    const tier: JoinTier = match.joinTier || (match.isFk ? "confirmed" : "none");
    const multiHop =
      tier === "none" && activeTableNames.length > 0
        ? findMultiHopJoinPath(activeTableNames, t.name, effectiveSchema)
        : undefined;
    return { table: t, match, tier, multiHop };
  });

  const tierCounts = {
    all: unjoinedWithMatch.length,
    confirmed: unjoinedWithMatch.filter((u) => u.tier === "confirmed").length,
    logical: unjoinedWithMatch.filter((u) => u.tier === "logical").length,
    none: unjoinedWithMatch.filter((u) => u.tier === "none").length,
  };

  const tierRank = (tier: JoinTier) => (tier === "confirmed" ? 0 : tier === "logical" ? 1 : 2);

  const filteredUnjoinedTables = [...unjoinedWithMatch]
    .filter((u) => {
      if (joinTierFilter !== "all" && u.tier !== joinTierFilter) return false;
      if (joinSearch.trim()) {
        return u.table.name.toLowerCase().includes(joinSearch.trim().toLowerCase());
      }
      return true;
    })
    .sort((a, b) => {
      const rDiff = tierRank(a.tier) - tierRank(b.tier);
      if (rDiff !== 0) return rDiff;
      return 0;
    })
    .slice(0, 40);

  return (
    <div
      data-qb="joins-editor"
      className={cx(className, classNames?.joins)}
      style={
        unstyled
          ? undefined
          : {
              background: "var(--qb-color-surface, #10141f)",
              borderRadius: "var(--qb-radius-md, 8px)",
              border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
              padding: "12px 14px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              color: "var(--qb-color-text, #e2e8f0)",
            }
      }
    >
      <div
        data-qb="joins-header"
        style={
          unstyled
            ? undefined
            : {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "8px",
                flexWrap: "wrap",
              }
        }
      >
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", alignItems: "center", gap: "8px", minWidth: 0, flex: 1 }
          }
        >
          <span
            className={cx(classNames?.title)}
            style={
              unstyled
                ? undefined
                : {
                    fontSize: "0.875rem",
                    fontWeight: 600,
                    color: "var(--qb-color-text, #f8fafc)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }
            }
          >
            {unstyled ? (
              `🔗 Table Relationships & Joins (${joins.length})`
            ) : (
              <>
                <span style={SR_ONLY_STYLE}>{`🔗 Table Relationships & Joins (${joins.length})`}</span>
                <span aria-hidden="true">
                  {joins.length > 0 ? `Joins (${joins.length})` : "Joins"}
                </span>
              </>
            )}
          </span>
          {joins.length === 0 && (
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontSize: "0.78rem",
                      color: "var(--qb-color-text-muted, #64748b)",
                    }
              }
            >
              Single table query. Add another table to configure relational joins.
            </span>
          )}
        </div>

        {unjoinedTables.length > 0 && (
          <div
            style={
              unstyled
                ? undefined
                : { position: "relative", display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }
            }
          >
            <select
              defaultValue=""
              aria-label="Join table"
              data-qb="select-add-join"
              onChange={(e) => {
                if (e.target.value) {
                  handleAddJoin(e.target.value);
                  e.target.value = "";
                }
              }}
              style={unstyled ? undefined : SR_ONLY_STYLE}
            >
              <option value="" disabled>
                + Join Table...
              </option>
              {unjoinedTables.map((t) => (
                <option key={t.name} value={t.name}>
                  + {t.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Direct-Click Unjoined Table Pill Strip (Zero Dropdowns, 3-Tier Join Classification) */}
      {!unstyled && unjoinedTables.length > 0 && (
        <div
          data-qb="join-table-pills"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            padding: "10px 12px",
            background: "var(--qb-color-background, #090d16)",
            borderRadius: "6px",
            border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--qb-color-text-secondary, #94a3b8)" }}>
                Available tables ({unjoinedTables.length}):
              </span>
              <div
                role="group"
                aria-label="Filter candidate tables by join classification"
                data-qb="join-tier-filter-bar"
                style={{ display: "inline-flex", alignItems: "center", gap: "4px", flexWrap: "wrap" }}
              >
                {(
                  [
                    { id: "all", label: `All (${tierCounts.all})` },
                    { id: "confirmed", label: `✓ Confirmed Join (${tierCounts.confirmed})` },
                    { id: "logical", label: `⇄ Logical Join (${tierCounts.logical})` },
                    { id: "none", label: `○ No Dedicated Join (${tierCounts.none})` },
                  ] as const
                ).map((tab) => {
                  const active = joinTierFilter === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      data-qb="join-tier-filter-pill"
                      data-qb-tier-filter={tab.id}
                      aria-pressed={active}
                      onClick={() => setJoinTierFilter(tab.id)}
                      style={{
                        padding: "2px 8px",
                        borderRadius: "999px",
                        fontSize: "0.71rem",
                        fontWeight: active ? 700 : 500,
                        border: active
                          ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                          : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                        background: active
                          ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.16))"
                          : "var(--qb-color-surface, #10141f)",
                        color: active
                          ? "var(--qb-color-active-text, #e0f2fe)"
                          : "var(--qb-color-text-secondary, #94a3b8)",
                        cursor: "pointer",
                      }}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>
            </div>
            {unjoinedTables.length > 6 && (
              <input
                type="text"
                value={joinSearch}
                onChange={(e) => setJoinSearch(e.target.value)}
                placeholder="Filter tables..."
                aria-label="Filter tables to join"
                data-qb="join-table-search"
                style={{
                  background: "var(--qb-color-surface, #10141f)",
                  border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                  borderRadius: "5px",
                  padding: "4px 8px",
                  color: "var(--qb-color-text, #e2e8f0)",
                  fontSize: "0.76rem",
                  outline: "none",
                  width: "160px",
                }}
              />
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", maxHeight: "125px", overflowY: "auto" }}>
            {filteredUnjoinedTables.map(({ table: t, match, tier }) => {
              const isConfirmed = tier === "confirmed";
              const isLogical = tier === "logical";
              const badgeText = isConfirmed
                ? "✓ Confirmed Join"
                : isLogical
                  ? "⇄ Logical Join"
                  : "○ No Dedicated Join";
              const pillBg = isConfirmed
                ? "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.14))"
                : isLogical
                  ? "var(--qb-color-logical-bg, rgba(59, 130, 246, 0.14))"
                  : "var(--qb-color-surface-hover, #161b28)";
              const pillColor = isConfirmed
                ? "var(--qb-color-confirmed-text, #6ee7b7)"
                : isLogical
                  ? "var(--qb-color-logical-text, #93c5fd)"
                  : "var(--qb-color-text-secondary, #94a3b8)";
              const pillBorder = isConfirmed
                ? "1px solid var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.38))"
                : isLogical
                  ? "1px solid var(--qb-color-logical-border, rgba(59, 130, 246, 0.38))"
                  : "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.09))";

              return (
                <button
                  key={t.name}
                  type="button"
                  data-qb="join-table-pill"
                  data-qb-table={t.name}
                  data-qb-join-tier={tier}
                  title={`${t.name} — ${badgeText}${tier !== "none" ? ` (${match.leftTable}.${match.leftCol} = ${match.rightTable}.${match.rightCol})` : " (manual column selection)"}`}
                  onClick={() => handleAddJoin(t.name)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    background: pillBg,
                    color: "var(--qb-color-text, #e2e8f0)",
                    border: pillBorder,
                    borderRadius: "999px",
                    padding: "4px 10px",
                    fontSize: "0.78rem",
                    fontWeight: isConfirmed || isLogical ? 600 : 500,
                    fontFamily: "var(--qb-font-mono, monospace)",
                    cursor: "pointer",
                  }}
                >
                  <span>{`Join ${t.name}`}</span>
                  <span
                    data-qb="candidate-join-tier-badge"
                    style={{
                      fontSize: "0.68rem",
                      fontFamily: "var(--qb-font-family, system-ui, sans-serif)",
                      fontWeight: 700,
                      color: pillColor,
                      padding: "1px 6px",
                      borderRadius: "999px",
                      background: "var(--qb-color-surface, rgba(15, 23, 42, 0.45))",
                    }}
                  >
                    {badgeText}
                  </span>
                </button>
              );
            })}
          </div>
          {filteredUnjoinedTables.some(
            (u) => u.multiHop?.isConnected && u.multiHop.joins.length > 1,
          ) && (
            <div
              data-qb="multihop-join-strip"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                flexWrap: "wrap",
                paddingTop: "6px",
                borderTop: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.06))",
              }}
            >
              <span
                style={{
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  color: "var(--qb-color-primary, #38bdf8)",
                }}
              >
                🌉 Multi-Hop Auto-Join:
              </span>
              {filteredUnjoinedTables
                .filter((u) => u.multiHop?.isConnected && u.multiHop.joins.length > 1)
                .map(({ table: t, multiHop }) => {
                  const bridges = multiHop!.bridgeTables.join(" → ");
                  return (
                    <button
                      key={`mh-${t.name}`}
                      type="button"
                      data-qb="btn-auto-join-multihop"
                      data-qb-target-table={t.name}
                      data-qb-bridge-path={multiHop!.bridgeTables.join(",")}
                      onClick={() => handleAddMultiHopJoin(t.name)}
                      title={`Automatically join ${t.name} across bridge table(s): ${bridges}`}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "5px",
                        background: "rgba(139, 92, 246, 0.14)",
                        color: "#ddd6fe",
                        border: "1px solid rgba(139, 92, 246, 0.4)",
                        borderRadius: "999px",
                        padding: "3px 9px",
                        fontSize: "0.74rem",
                        fontWeight: 600,
                        fontFamily: "var(--qb-font-mono, monospace)",
                        cursor: "pointer",
                      }}
                    >
                      <span>{`+ ${t.name}`}</span>
                      <span
                        style={{
                          fontSize: "0.68rem",
                          fontFamily: "var(--qb-font-family, system-ui, sans-serif)",
                          color: "#c4b5fd",
                        }}
                      >
                        {`via ${bridges}`}
                      </span>
                    </button>
                  );
                })}
            </div>
          )}
        </div>
      )}

      {joins.length > 0 && (
        <div
          style={
            unstyled
              ? undefined
              : { display: "flex", flexDirection: "column", gap: "8px" }
          }
        >
          {joins.map((j) => {
            const leftTableName = j.left_table || activeTables[0]?.name || "";
            const leftValue = `${leftTableName}.${j.left_col}`;
            const rightValue = `${j.table}.${j.right_col}`;
            const rightTableMeta =
              effectiveAllTables.find((t) => t.name === j.table) ||
              effectiveSchema.tables?.[j.table];
            const rightColumnSuggestions = (rightTableMeta?.columns || []).map(
              (c) => `${j.table}.${c.name}`,
            );
            const isProven = isProvenJoin(
              {
                left_table: j.left_table,
                left_col: j.left_col || "",
                table: j.table,
                right_col: j.right_col || "",
              },
              effectiveSchema.foreign_keys || [],
            );
            const activeClassification = classifyJoinCondition(
              leftTableName,
              j.left_col || "",
              j.table,
              j.right_col || "",
              effectiveSchema,
            );
            const effectiveJoinTier: JoinTier = isProven
              ? "confirmed"
              : activeClassification.joinTier;

            const isRowExpanded = expandedColRowId === j.id;
            const leftTableCandidates = activeTables.filter((t) => t.name !== j.table);
            const effectiveLeftTables =
              leftTableCandidates.length > 0 ? leftTableCandidates : activeTables;
            const isSingleLeftTable = effectiveLeftTables.length <= 1;
            const allLeftCols = effectiveLeftTables.flatMap((t) =>
              t.columns.map((c) => ({
                table: t.name,
                col: c.name,
                full: `${t.name}.${c.name}`,
                isKey: Boolean(
                  c.is_primary ||
                    c.is_foreign_key ||
                    c.name === "id" ||
                    c.name.endsWith("_id") ||
                    c.name === j.left_col,
                ),
              })),
            );
            const visibleLeftCols = isRowExpanded
              ? allLeftCols.slice(0, 12)
              : allLeftCols.filter((c) => c.isKey).slice(0, 12);
            const finalLeftCols =
              visibleLeftCols.length > 0 ? visibleLeftCols : allLeftCols.slice(0, 12);

            const allRightCols = (rightTableMeta?.columns || []).map((c) => ({
              col: c.name,
              full: `${j.table}.${c.name}`,
              isKey: Boolean(
                c.is_primary ||
                  c.is_foreign_key ||
                  c.name === "id" ||
                  c.name.endsWith("_id") ||
                  c.name === j.right_col,
              ),
            }));
            const visibleRightCols = isRowExpanded
              ? allRightCols.slice(0, 12)
              : allRightCols.filter((c) => c.isKey).slice(0, 12);
            const finalRightCols =
              visibleRightCols.length > 0 ? visibleRightCols : allRightCols.slice(0, 12);

            return (
              <div
                key={j.id}
                data-qb="join-row"
                data-qb-join-id={j.id}
                className={cx(classNames?.joinItem)}
                style={
                  unstyled
                    ? undefined
                    : {
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        flexWrap: "wrap",
                        background: "var(--qb-color-surface-hover, #161b28)",
                        border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.07))",
                        padding: "8px 12px",
                        borderRadius: "var(--qb-radius-sm, 6px)",
                      }
                }
              >
                {/* Join type (SR_ONLY select for test compatibility) */}
                <select
                  value={j.type}
                  aria-label="Join type"
                  data-qb="join-type"
                  onChange={(e) =>
                    handleUpdate(j.id, {
                      type: e.target.value as VisualJoin["type"],
                    })
                  }
                  style={unstyled ? undefined : SR_ONLY_STYLE}
                >
                  <option value="LEFT JOIN">LEFT JOIN</option>
                  <option value="INNER JOIN">INNER JOIN</option>
                  <option value="RIGHT JOIN">RIGHT JOIN</option>
                  <option value="FULL JOIN">FULL JOIN</option>
                </select>
                {!unstyled && (
                  <div
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "2px",
                      background: "var(--qb-color-background, #090d16)",
                      padding: "3px",
                      borderRadius: "6px",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                    }}
                    role="group"
                    aria-label="Join type pills"
                  >
                    {JOIN_TYPE_PILLS.map((jp) => {
                      const active = j.type === jp.value;
                      return (
                        <button
                          key={jp.value}
                          type="button"
                          data-qb="join-type-pill"
                          data-qb-join-type={jp.value}
                          aria-pressed={active}
                          title={jp.tooltip}
                          onClick={() => handleUpdate(j.id, { type: jp.value })}
                          style={{
                            padding: "4px 9px",
                            fontSize: "0.76rem",
                            fontWeight: active ? 700 : 500,
                            borderRadius: "4px",
                            border: "none",
                            background: active
                              ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.18))"
                              : "transparent",
                            color: active
                              ? "var(--qb-color-active-text, #e0f2fe)"
                              : "var(--qb-color-text-muted, #64748b)",
                            cursor: "pointer",
                          }}
                        >
                          <span style={SR_ONLY_STYLE}>{jp.label}</span>
                          <span aria-hidden="true">{jp.friendlyLabel}</span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {effectiveJoinTier === "confirmed" ? (
                  <span
                    data-qb="badge-fk-verified"
                    data-qb-join-tier="confirmed"
                    title="Confirmed Join — Foreign key constraint verified in database schema"
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "var(--qb-color-confirmed-bg, rgba(16, 185, 129, 0.14))",
                            color: "var(--qb-color-confirmed-text, #6ee7b7)",
                            border: "1px solid var(--qb-color-confirmed-border, rgba(16, 185, 129, 0.38))",
                            borderRadius: "4px",
                            padding: "2px 8px",
                            fontSize: "0.75rem",
                            fontWeight: 700,
                          }
                    }
                  >
                    {unstyled ? (
                      "✓ FK Verified"
                    ) : (
                      <>
                        <span style={SR_ONLY_STYLE}>✓ FK Verified</span>
                        <span aria-hidden="true">✓ Confirmed Join</span>
                      </>
                    )}
                  </span>
                ) : effectiveJoinTier === "logical" ? (
                  <span
                    data-qb="badge-join-tier"
                    data-qb-join-tier="logical"
                    title={`Logical Join — ${activeClassification.reason}`}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "var(--qb-color-logical-bg, rgba(59, 130, 246, 0.14))",
                            color: "var(--qb-color-logical-text, #93c5fd)",
                            border: "1px solid var(--qb-color-logical-border, rgba(59, 130, 246, 0.38))",
                            borderRadius: "4px",
                            padding: "2px 8px",
                            fontSize: "0.75rem",
                            fontWeight: 700,
                          }
                    }
                  >
                    ⇄ Logical Join
                  </span>
                ) : (
                  <span
                    data-qb="badge-join-tier"
                    data-qb-join-tier="none"
                    title={`No Dedicated Join — ${activeClassification.reason}`}
                    style={
                      unstyled
                        ? undefined
                        : {
                            background: "var(--qb-color-warn-bg, rgba(245, 158, 11, 0.15))",
                            color: "var(--qb-color-warn-text, #fde047)",
                            border: "1px solid var(--qb-color-warn-border, rgba(245, 158, 11, 0.38))",
                            borderRadius: "4px",
                            padding: "2px 8px",
                            fontSize: "0.75rem",
                            fontWeight: 700,
                          }
                    }
                  >
                    ○ No Dedicated Join
                  </span>
                )}

                <span
                  data-qb="join-target-table"
                  style={
                    unstyled
                      ? undefined
                      : { fontWeight: 700, color: "var(--qb-color-text, #f8fafc)", fontSize: "0.875rem", fontFamily: "var(--qb-font-mono, monospace)" }
                  }
                >
                  {j.table}
                </span>

                <span style={unstyled ? undefined : { fontSize: "0.78rem", fontWeight: 600, color: "var(--qb-color-text-muted, #64748b)" }}>
                  {unstyled ? (
                    "ON"
                  ) : (
                    <>
                      <span style={SR_ONLY_STYLE}>ON</span>
                      <span aria-hidden="true">matched where</span>
                    </>
                  )}
                </span>

                {/* Left col (SR_ONLY input preserved for test compatibility) */}
                <input
                  type="text"
                  aria-label="Join left column"
                  data-qb="join-left-col"
                  list={`join-left-cols-${j.id}`}
                  value={leftValue}
                  onChange={(e) => {
                    const val = e.target.value;
                    const lastDot = val.lastIndexOf(".");
                    if (lastDot !== -1) {
                      handleUpdate(j.id, {
                        left_table: val.substring(0, lastDot),
                        left_col: val.substring(lastDot + 1),
                      });
                    }
                  }}
                  style={unstyled ? undefined : SR_ONLY_STYLE}
                />
                <datalist id={`join-left-cols-${j.id}`}>
                  {leftColumnSuggestions.map((opt) => (
                    <option key={opt} value={opt} />
                  ))}
                </datalist>

                {/* Direct Left Join Key Pill Strip */}
                {!unstyled && (
                  <div
                    data-qb="join-left-col-pills"
                    style={{
                      display: "inline-flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: "3px",
                      background: "var(--qb-color-background, #090d16)",
                      padding: "3px 5px",
                      borderRadius: "6px",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                    }}
                  >
                    {finalLeftCols.map((item) => {
                      const active = leftValue === item.full;
                      return (
                        <button
                          key={item.full}
                          type="button"
                          data-qb="join-left-col-pill"
                          aria-pressed={active}
                          onClick={() =>
                            handleUpdate(j.id, {
                              left_table: item.table,
                              left_col: item.col,
                            })
                          }
                          style={{
                            padding: "2px 7px",
                            fontSize: "0.74rem",
                            fontFamily: "var(--qb-font-mono, monospace)",
                            fontWeight: active ? 700 : 500,
                            borderRadius: "4px",
                            border: active
                              ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                              : "1px solid transparent",
                            background: active
                              ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.16))"
                              : "transparent",
                            color: active
                              ? "var(--qb-color-active-text, #e0f2fe)"
                              : "var(--qb-color-text-secondary, #94a3b8)",
                            cursor: "pointer",
                          }}
                        >
                          {isSingleLeftTable ? item.col : `${item.table}.${item.col}`}
                        </button>
                      );
                    })}
                  </div>
                )}

                <span style={unstyled ? undefined : { fontSize: "0.84rem", fontWeight: 700, color: "var(--qb-color-text-muted, #64748b)" }}>
                  =
                </span>

                {/* Right col (SR_ONLY input preserved for test compatibility) */}
                <input
                  type="text"
                  aria-label="Join right column"
                  data-qb="join-right-col"
                  list={`join-right-cols-${j.id}`}
                  value={rightValue}
                  onChange={(e) => {
                    const val = e.target.value;
                    const lastDot = val.lastIndexOf(".");
                    if (lastDot !== -1) {
                      handleUpdate(j.id, { right_col: val.substring(lastDot + 1) });
                    }
                  }}
                  style={unstyled ? undefined : SR_ONLY_STYLE}
                />
                <datalist id={`join-right-cols-${j.id}`}>
                  {rightColumnSuggestions.map((opt) => (
                    <option key={opt} value={opt} />
                  ))}
                </datalist>

                {/* Direct Right Join Key Pill Strip */}
                {!unstyled && (
                  <div
                    data-qb="join-right-col-pills"
                    style={{
                      display: "inline-flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: "3px",
                      background: "var(--qb-color-background, #090d16)",
                      padding: "3px 5px",
                      borderRadius: "6px",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.08))",
                    }}
                  >
                    {finalRightCols.map((item) => {
                      const active = j.right_col === item.col;
                      return (
                        <button
                          key={item.full}
                          type="button"
                          data-qb="join-right-col-pill"
                          aria-pressed={active}
                          onClick={() => handleUpdate(j.id, { right_col: item.col })}
                          style={{
                            padding: "2px 7px",
                            fontSize: "0.74rem",
                            fontFamily: "var(--qb-font-mono, monospace)",
                            fontWeight: active ? 700 : 500,
                            borderRadius: "4px",
                            border: active
                              ? "1px solid var(--qb-color-active-border, rgba(56, 189, 248, 0.45))"
                              : "1px solid transparent",
                            background: active
                              ? "var(--qb-color-active-bg, rgba(56, 189, 248, 0.16))"
                              : "transparent",
                            color: active
                              ? "var(--qb-color-active-text, #e0f2fe)"
                              : "var(--qb-color-text-secondary, #94a3b8)",
                            cursor: "pointer",
                          }}
                        >
                          {item.col}
                        </button>
                      );
                    })}
                  </div>
                )}

                {!unstyled && (allLeftCols.length > finalLeftCols.length || allRightCols.length > finalRightCols.length || isRowExpanded) && (
                  <button
                    type="button"
                    data-qb="join-expand-cols"
                    onClick={() => setExpandedColRowId((prev) => (prev === j.id ? null : j.id))}
                    style={{
                      background: "transparent",
                      border: "1px solid var(--qb-color-border, rgba(255, 255, 255, 0.1))",
                      borderRadius: "999px",
                      color: "var(--qb-color-text-secondary, #94a3b8)",
                      fontSize: "0.72rem",
                      padding: "2px 8px",
                      cursor: "pointer",
                    }}
                  >
                    {isRowExpanded ? "Key cols only" : "All cols"}
                  </button>
                )}

                <button
                  type="button"
                  aria-label="Remove join"
                  onClick={() => handleRemove(j.id)}
                  data-qb="btn-remove-join"
                  style={
                    unstyled
                      ? undefined
                      : {
                          background: "transparent",
                          border: "none",
                          color: "var(--qb-color-text-muted, #64748b)",
                          cursor: "pointer",
                          fontSize: "0.875rem",
                          padding: "4px 8px",
                          marginLeft: "auto",
                        }
                  }
                  title="Remove join"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
