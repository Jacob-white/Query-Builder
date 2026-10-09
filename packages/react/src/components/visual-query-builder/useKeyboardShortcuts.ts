import { useEffect } from "react";

export interface KeyboardShortcutOptions {
  /** Open modals; Escape closes each of them. */
  modals: ReadonlyArray<{ isOpen: boolean; close: () => void }>;
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
}

/**
 * Window-level shortcuts: Escape closes open modals; Cmd/Ctrl+Z undoes, Cmd/Ctrl+Shift+Z and
 * Cmd/Ctrl+Y redo (ignored while typing in inputs, textareas and contenteditable elements).
 */
export function useKeyboardShortcuts({
  modals,
  canUndo,
  canRedo,
  undo,
  redo,
}: KeyboardShortcutOptions): void {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        for (const modal of modals) {
          if (modal.isOpen) modal.close();
        }
      }

      const target = e.target;
      const isTargetInput =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        Boolean((target as HTMLElement | null)?.isContentEditable);

      if (!isTargetInput) {
        const isModifier = e.metaKey || e.ctrlKey;
        const key = e.key.toLowerCase();
        if (isModifier && key === "z") {
          e.preventDefault();
          if (e.shiftKey) {
            if (canRedo) redo();
          } else if (canUndo) {
            undo();
          }
        } else if (isModifier && key === "y") {
          e.preventDefault();
          if (canRedo) redo();
        }
      }
    };
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [modals, canUndo, canRedo, undo, redo]);
}
