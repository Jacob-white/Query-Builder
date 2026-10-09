import { useCallback, useEffect, useRef, useState } from "react";
import type { QuerySpec, SchemaSnapshot, SqlDialect } from "../../types";
import { parseSqlToSpec } from "../../utils/sqlParser";
import { wouldLoseRawSql, type RawSqlSnapshot } from "../../utils/rawSql";

export interface UseRawSqlModeOptions {
  /** Compiled output of the visual model. */
  compiled: { sql: string; spec: QuerySpec | null };
  dialect: SqlDialect;
  /** Schema used to compile (includes virtual CTE tables). */
  compileSchema: SchemaSnapshot | null | undefined;
  /** Schema used to parse raw SQL. */
  parseSchema: SchemaSnapshot | null | undefined;
  loadSpec: (spec: QuerySpec) => void;
}

/**
 * Raw-SQL editing mode: tracks the raw text, whether it is authoritative, and the notice shown
 * when a visual edit replaces SQL the visual model could not represent.
 */
export function useRawSqlMode({
  compiled,
  dialect,
  compileSchema,
  parseSchema,
  loadSpec,
}: UseRawSqlModeOptions) {
  const [rawSql, setRawSql] = useState<string>("");
  const [isRawMode, setIsRawMode] = useState<boolean>(false);
  // Raw SQL that a visual edit replaced; offered back to the user instead of being lost silently.
  const [discardedRawSql, setDiscardedRawSql] = useState<string | null>(null);
  const snapshotRef = useRef<RawSqlSnapshot>({
    isRawMode: false,
    rawSql: "",
    compiledSql: "",
    dialect: "postgres",
    schema: null,
  });

  const leaveRawMode = useCallback(() => {
    if (wouldLoseRawSql(snapshotRef.current)) setDiscardedRawSql(snapshotRef.current.rawSql);
    setIsRawMode(false);
  }, []);

  useEffect(() => {
    snapshotRef.current = {
      isRawMode,
      rawSql,
      compiledSql: compiled.sql,
      dialect,
      schema: compileSchema,
    };
  }, [isRawMode, rawSql, compiled.sql, dialect, compileSchema]);

  const currentSql = isRawMode ? rawSql : compiled.sql;

  /** `null` while raw-SQL mode holds SQL that cannot be mapped to a spec (for example `SELECT`). */
  const getActiveSpec = useCallback((): QuerySpec | null => {
    if (isRawMode) {
      const parsed = parseSqlToSpec(currentSql, parseSchema);
      return parsed && parsed.table ? parsed : null;
    }
    return compiled.spec;
  }, [isRawMode, currentSql, parseSchema, compiled.spec]);

  /** Switch to raw mode holding `sql` (no sync into the visual model). */
  const enterRawSql = (sql: string) => {
    setDiscardedRawSql(null);
    setRawSql(sql);
    setIsRawMode(true);
  };

  /** Raw SQL input change with bidirectional sync. */
  const handleRawSqlChange = (newSql: string) => {
    setDiscardedRawSql(null);
    setIsRawMode(true);
    setRawSql(newSql);

    const parsed = parseSqlToSpec(newSql, parseSchema);
    if (parsed && parsed.table) loadSpec(parsed);
  };

  const handleSyncWithVisualCanvas = () => {
    const parsed = parseSqlToSpec(rawSql, parseSchema);
    if (parsed && parsed.table) loadSpec(parsed);
    setRawSql(compiled.sql);
    setIsRawMode(false);
  };

  /** Called when the SQL tab is opened outside raw mode so the editor shows the compiled SQL. */
  const seedFromCompiled = () => {
    if (!isRawMode) setRawSql(compiled.sql);
  };

  return {
    rawSql,
    isRawMode,
    discardedRawSql,
    setDiscardedRawSql,
    currentSql,
    getActiveSpec,
    leaveRawMode,
    enterRawSql,
    handleRawSqlChange,
    handleSyncWithVisualCanvas,
    seedFromCompiled,
  };
}
