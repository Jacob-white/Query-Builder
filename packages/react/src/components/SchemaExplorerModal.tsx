import React, { useEffect, useRef } from "react";
import { SchemaExplorer, type SchemaExplorerProps } from "./SchemaExplorer";
import { useTheme } from "../theme/ThemeProvider";
import { darkTheme, lightTheme, type QueryBuilderTheme } from "../theme/tokens";

export interface SchemaExplorerModalProps extends SchemaExplorerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SchemaExplorerModal: React.FC<SchemaExplorerModalProps> = ({
  isOpen,
  onClose,
  schema,
  selectedTable,
  onSelectTable,
  onAddToCanvas,
  onOpenErd,
  onQuickQuery,
  theme: propTheme,
  unstyled = false,
  className,
}) => {
  const { theme: contextTheme } = useTheme();

  const activeTheme: QueryBuilderTheme = React.useMemo(() => {
    if (propTheme && typeof propTheme === "object" && "colors" in propTheme) {
      return propTheme as QueryBuilderTheme;
    }
    if (propTheme === "light") return lightTheme;
    if (propTheme === "dark") return darkTheme;
    return contextTheme;
  }, [propTheme, contextTheme]);

  const modalRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="presentation"
      data-qb="schema-explorer-backdrop"
      style={
        unstyled
          ? undefined
          : {
              position: "fixed",
              inset: 0,
              zIndex: 9999,
              background: "rgba(0, 0, 0, 0.75)",
              backdropFilter: "blur(6px)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "24px",
            }
      }
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label="Database Schema Explorer"
        data-qb="schema-explorer-modal"
        style={
          unstyled
            ? undefined
            : {
                background: activeTheme.colors.surface,
                border: `1px solid ${activeTheme.colors.border}`,
                borderRadius: activeTheme.radii.xl,
                width: "92vw",
                maxWidth: "1150px",
                maxHeight: "88vh",
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
                boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7)",
                color: activeTheme.colors.text,
              }
        }
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={
            unstyled
              ? undefined
              : {
                  padding: "12px 18px",
                  borderBottom: `1px solid ${activeTheme.colors.border}`,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  background: "rgba(0, 0, 0, 0.2)",
                }
          }
        >
          <div style={unstyled ? undefined : { display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={unstyled ? undefined : { fontSize: "1.2rem" }}>🗄️</span>
            <span
              style={
                unstyled
                  ? undefined
                  : {
                      fontWeight: activeTheme.typography.fontWeightBold,
                      fontSize: activeTheme.typography.fontSizeBase,
                    }
              }
            >
              Database Schema Explorer
            </span>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close Schema Explorer"
            data-qb="btn-close-modal"
            style={
              unstyled
                ? undefined
                : {
                    background: "transparent",
                    border: "none",
                    color: activeTheme.colors.textMuted,
                    fontSize: "1.2rem",
                    cursor: "pointer",
                    padding: "4px 8px",
                    borderRadius: activeTheme.radii.sm,
                  }
            }
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div
          style={
            unstyled
              ? undefined
              : {
                  padding: "16px",
                  overflowY: "auto",
                  flex: "1 1 auto",
                }
          }
        >
          <SchemaExplorer
            schema={schema}
            selectedTable={selectedTable}
            onSelectTable={onSelectTable}
            onAddToCanvas={onAddToCanvas}
            onOpenErd={onOpenErd}
            onQuickQuery={onQuickQuery}
            theme={activeTheme}
            unstyled={unstyled}
            className={className}
          />
        </div>
      </div>
    </div>
  );
};
