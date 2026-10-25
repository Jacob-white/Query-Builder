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

function ToolButton({
  label,
  onClick,
  unstyled,
  theme,
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
              background: "transparent",
              color: theme.colors.textSecondary,
              border: `1px solid ${theme.colors.border}`,
              borderRadius: "6px",
              padding: "5px 11px",
              fontSize: "0.84rem",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.12s ease",
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
  showConnectDatabase?: boolean;
  onOpenConnectDatabase?: () => void;
}

/** Buttons that open the window-function builder, schema explorer, ERD, and database connection modals. */
export function ToolButtons({
  unstyled,
  theme,
  showWindowFunctions,
  windowFunctionCount,
  onOpenWindowFunctions,
  showSchemaTools,
  onOpenSchemaExplorer,
  onOpenErd,
  showConnectDatabase = false,
  onOpenConnectDatabase,
}: ToolButtonsProps) {
  return (
    <>
      {showConnectDatabase && onOpenConnectDatabase && (
        <ToolButton
          label="Connect or switch database"
          onClick={onOpenConnectDatabase}
          unstyled={unstyled}
          theme={theme}
          color="#38bdf8"
          borderColor="rgba(56, 189, 248, 0.3)"
          dataQb="btn-connect-database"
          dataTestId="btn-open-connect-database"
        >
          <span style={SR_ONLY_STYLE}>🔌 Connect Database</span>
          <span aria-hidden="true">+ Connect Database</span>
        </ToolButton>
      )}
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
          {unstyled ? (
            `🪟 Window Functions ${windowFunctionCount > 0 ? `(${windowFunctionCount})` : ""}`
          ) : (
            <>
              <span style={SR_ONLY_STYLE}>
                🪟 Window Functions {windowFunctionCount > 0 ? `(${windowFunctionCount})` : ""}
              </span>
              <span aria-hidden="true">
                Window Functions {windowFunctionCount > 0 ? `(${windowFunctionCount})` : ""}
              </span>
            </>
          )}
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
          {unstyled ? (
            "🗄️ Schema Explorer"
          ) : (
            <>
              <span style={SR_ONLY_STYLE}>🗄️ Schema Explorer</span>
              <span aria-hidden="true">Schema Explorer</span>
            </>
          )}
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
          {unstyled ? (
            "🗺️ Schema ERD"
          ) : (
            <>
              <span style={SR_ONLY_STYLE}>🗺️ Schema ERD</span>
              <span aria-hidden="true">Schema ERD</span>
            </>
          )}
        </ToolButton>
      )}
    </>
  );
}
