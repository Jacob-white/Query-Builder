import { useEffect, useRef, useState } from "react";
import type { QuerySpec } from "../../types";
import { createInitialState } from "../../hooks/useQueryState";
import { fastCanonicalSpec } from "../../utils/canonicalSpec";

export interface UseControlledSpecSyncOptions {
  value?: QuerySpec;
  onChange?: (spec: QuerySpec | null, sql: string) => void;
  loadSpec: (spec: QuerySpec) => void;
  getActiveSpec: () => QuerySpec | null;
  currentSql: string;
}

/**
 * Two-way sync of the query spec: a changed `value` prop is loaded into the query state (structurally
 * equal values are ignored), and real state changes are reported through `onChange` exactly once.
 */
export function useControlledSpecSync({
  value,
  onChange,
  loadSpec,
  getActiveSpec,
  currentSql,
}: UseControlledSpecSyncOptions): void {
  const [initialCanonical] = useState<string>(() =>
    value ? fastCanonicalSpec(createInitialState(value)) : "",
  );
  const lastControlledValueRef = useRef<string>(initialCanonical);
  const lastReportedSpecRef = useRef<string>(initialCanonical);
  const isFirstRenderRef = useRef<boolean>(true);

  useEffect(() => {
    if (value !== undefined) {
      const canonical = fastCanonicalSpec(createInitialState(value));
      if (canonical !== lastControlledValueRef.current) {
        lastControlledValueRef.current = canonical;
        lastReportedSpecRef.current = canonical;
        loadSpec(value);
      }
    }
  }, [value, loadSpec]);

  useEffect(() => {
    const currentActiveSpec = getActiveSpec();
    const canonicalActive = currentActiveSpec
      ? fastCanonicalSpec(createInitialState(currentActiveSpec))
      : `__unparsed_raw_sql__:${currentSql}`;

    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false;
      lastReportedSpecRef.current = canonicalActive;
      lastControlledValueRef.current = canonicalActive;
      return;
    }

    if (canonicalActive !== lastReportedSpecRef.current) {
      lastReportedSpecRef.current = canonicalActive;
      lastControlledValueRef.current = canonicalActive;
      if (onChange) {
        onChange(currentActiveSpec, currentSql);
      }
    }
  }, [onChange, getActiveSpec, currentSql]);
}
