import React from "react";
import type { QueryBuilderTheme } from "../../theme/tokens";

interface ToolButtonProps {
  label: string;
  onClick: () => void;
  unstyled: boolean;
  theme: QueryBuilderTheme;
  color: string;
  borderColor: string;
  dataQb: string;
  dataTestId?: string;
  children: React.ReactNode;
}

function ToolButton({
  label,
  onClick,
  unstyled,
  theme,
  color,
  borderColor,
  dataQb,
  dataTestId,
  children,
}: ToolButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      data-qb={dataQb}
      data-testid={dataTestId}
      style={
        unstyled
          ? undefined
          : {
              background: "rgba(30, 41, 59, 0.5)",
              color,
              border: `1px solid ${borderColor}`,
              borderRadius: theme.radii.sm,
              padding: "6px 12px",
              fontSize: theme.typography.fontSizeSm,
              fontWeight: theme.typography.fontWeightSemibold,
              cursor: "pointer",
            }
      }
    >
      {children}
    </button>
  );
}

export interface ToolButtonsProps {
  unstyled: boolean;
  theme: QueryBuilderTheme;
  showWindowFunctions: boolean;
  windowFunctionCount: number;
  onOpenWindowFunctions: () => void;
  showSchemaTools: boolean;
  onOpenSchemaExplorer: () => void;
  onOpenErd: () => void;
}

/** Buttons that open the window-function builder, schema explorer and ERD modals. */
export function ToolButtons({
  unstyled,
  theme,
  showWindowFunctions,
  windowFunctionCount,
  onOpenWindowFunctions,
  showSchemaTools,
  onOpenSchemaExplorer,
  onOpenErd,
}: ToolButtonsProps) {
  return (
    <>
      {showWindowFunctions && (
        <ToolButton
          label="Open window functions builder"
          onClick={onOpenWindowFunctions}
          unstyled={unstyled}
          theme={theme}
          color="#a855f7"
          borderColor="rgba(168, 85, 247, 0.3)"
          dataQb="btn-window-functions"
          dataTestId="btn-open-wf-builder"
        >
          🪟 Window Functions {windowFunctionCount > 0 ? `(${windowFunctionCount})` : ""}
        </ToolButton>
      )}
      {showSchemaTools && (
        <ToolButton
          label="Open schema explorer"
          onClick={onOpenSchemaExplorer}
          unstyled={unstyled}
          theme={theme}
          color="#38bdf8"
          borderColor="rgba(56, 189, 248, 0.3)"
          dataQb="btn-schema-explorer"
        >
          🗄️ Schema Explorer
        </ToolButton>
      )}
      {showSchemaTools && (
        <ToolButton
          label="Open schema ERD modal"
          onClick={onOpenErd}
          unstyled={unstyled}
          theme={theme}
          color="#38bdf8"
          borderColor="rgba(56, 189, 248, 0.3)"
          dataQb="btn-erd"
        >
          🗺️ Schema ERD
        </ToolButton>
      )}
    </>
  );
}
