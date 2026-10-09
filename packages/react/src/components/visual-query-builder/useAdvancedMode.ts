import { useCallback } from "react";
import { usePersistedState } from "./usePersistedState";

export interface UseAdvancedModeOptions {
  advancedMode?: boolean;
  defaultAdvancedMode: boolean;
  storageKey: string | null;
  onAdvancedModeChange?: (value: boolean) => void;
  onContextChange?: (value: boolean) => void;
}

/** Advanced/simple mode: controlled via `advancedMode`, otherwise persisted in localStorage. */
export function useAdvancedMode({
  advancedMode,
  defaultAdvancedMode,
  storageKey,
  onAdvancedModeChange,
  onContextChange,
}: UseAdvancedModeOptions) {
  const [internal, setInternal] = usePersistedState(storageKey, defaultAdvancedMode, advancedMode);
  const isAdvancedMode = advancedMode !== undefined ? advancedMode : internal;

  const toggleAdvanced = useCallback(
    (nextVal?: boolean) => {
      const val = nextVal !== undefined ? nextVal : !isAdvancedMode;
      setInternal(val);
      onAdvancedModeChange?.(val);
      onContextChange?.(val);
    },
    [isAdvancedMode, setInternal, onAdvancedModeChange, onContextChange],
  );

  return { isAdvancedMode, toggleAdvanced };
}
