import { useCallback, useState } from "react";

function readStored(storageKey: string | null | undefined): string | null {
  if (storageKey && typeof window !== "undefined") {
    try {
      return localStorage.getItem(storageKey);
    } catch {
      return null;
    }
  }
  return null;
}

function writeStored(storageKey: string | null | undefined, value: string): void {
  if (storageKey && typeof window !== "undefined") {
    try {
      localStorage.setItem(storageKey, value);
    } catch {
      // Storage can be unavailable (private mode, quota); persistence is best-effort.
    }
  }
}

/**
 * Boolean state mirrored into localStorage (best-effort). `override` wins over the stored value
 * for the initial read; an empty/undefined `storageKey` disables persistence.
 */
export function usePersistedState(
  storageKey: string | null | undefined,
  fallback: boolean,
  override?: boolean,
): readonly [boolean, (next: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    if (override !== undefined) return override;
    const stored = readStored(storageKey);
    if (stored !== null) return stored === "true";
    return fallback;
  });
  const set = useCallback(
    (next: boolean) => {
      setValue(next);
      writeStored(storageKey, String(next));
    },
    [storageKey],
  );
  return [value, set] as const;
}
