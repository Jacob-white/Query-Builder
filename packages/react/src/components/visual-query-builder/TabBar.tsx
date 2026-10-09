import React, { useRef } from "react";
import { cx } from "../../utils/classNames";
import type { ActiveTab, ThemedProps } from "./types";

export interface TabBarProps extends ThemedProps {
  activeTab: ActiveTab;
  /** Visible tabs in display order. */
  tabs: readonly ActiveTab[];
  resultCount: number | null;
  cteCount: number;
  onSelectTab: (tab: ActiveTab) => void;
}

const TAB_ORDER: ActiveTab[] = ["visual", "sql", "results", "chart", "pipeline", "plan"];

/** Next tab for a roving-tabindex key press, or null when the key is not a navigation key. */
export function nextTabForKey(
  key: string,
  tabs: readonly ActiveTab[],
  current: ActiveTab,
): ActiveTab | null {
  const currentIndex = tabs.indexOf(current);
  if (currentIndex === -1) return null;
  if (key === "ArrowRight") return tabs[(currentIndex + 1) % tabs.length];
  if (key === "ArrowLeft") return tabs[(currentIndex - 1 + tabs.length) % tabs.length];
  if (key === "Home") return tabs[0];
  if (key === "End") return tabs[tabs.length - 1];
  return null;
}

/** ARIA tablist with roving tabindex and arrow/Home/End keyboard navigation. */
export function TabBar({
  activeTab,
  tabs,
  resultCount,
  cteCount,
  onSelectTab,
  unstyled,
  theme,
  classNames,
}: TabBarProps) {
  const tabRefs = useRef<Partial<Record<ActiveTab, HTMLButtonElement | null>>>({});

  const labels: Record<ActiveTab, string> = {
    visual: "🎨 Visual Builder",
    sql: "📝 Raw SQL",
    results: `📊 Results ${resultCount !== null ? `(${resultCount})` : ""}`,
    chart: "📈 Visual Chart",
    pipeline: `🔀 Pipeline ${cteCount > 0 ? `(${cteCount})` : ""}`,
    plan: "⚡ Query Plan",
  };

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, tab: ActiveTab) => {
    const target = nextTabForKey(e.key, tabs, tab);
    if (target === null) return;
    e.preventDefault();
    onSelectTab(target);
    tabRefs.current[target]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label="Query builder tabs"
      data-qb="tab-list"
      className={cx(classNames?.tabs)}
      style={
        unstyled
          ? undefined
          : {
              display: "flex",
              background: theme.colors.surface,
              borderRadius: theme.radii.md,
              padding: "2px",
              border: `1px solid ${theme.colors.border}`,
            }
      }
    >
      {TAB_ORDER.filter((tab) => tabs.includes(tab)).map((tab) => (
        <button
          key={tab}
          ref={(el) => {
            tabRefs.current[tab] = el;
          }}
          role="tab"
          id={`tab-${tab}`}
          aria-controls={`panel-${tab}`}
          aria-selected={activeTab === tab}
          tabIndex={activeTab === tab ? 0 : -1}
          onKeyDown={(e) => handleTabKeyDown(e, tab)}
          type="button"
          onClick={() => onSelectTab(tab)}
          data-qb="tab"
          data-qb-tab={tab}
          className={cx(classNames?.tab, activeTab === tab && classNames?.tabActive)}
          style={
            unstyled
              ? undefined
              : {
                  background: activeTab === tab ? theme.colors.primary : "transparent",
                  color: activeTab === tab ? "#fff" : theme.colors.textMuted,
                  border: "none",
                  borderRadius: theme.radii.sm,
                  padding: "6px 12px",
                  fontSize: theme.typography.fontSizeSm,
                  fontWeight: theme.typography.fontWeightSemibold,
                  cursor: "pointer",
                }
          }
        >
          {labels[tab]}
        </button>
      ))}
    </div>
  );
}
