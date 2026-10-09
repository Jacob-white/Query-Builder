import { useEffect, useState } from "react";
import type { ActiveTab } from "./types";

export interface TabAvailability {
  hasRawSqlTab: boolean;
  hasVisualChartTab: boolean;
  hasPipelineTab: boolean;
  hasPlanTab: boolean;
}

/** Tabs in display order, filtered by feature availability. */
export function visibleTabs(a: TabAvailability): ActiveTab[] {
  const tabs: ActiveTab[] = ["visual"];
  if (a.hasRawSqlTab) tabs.push("sql");
  tabs.push("results");
  if (a.hasVisualChartTab) tabs.push("chart");
  if (a.hasPipelineTab) tabs.push("pipeline");
  if (a.hasPlanTab) tabs.push("plan");
  return tabs;
}

/** Active tab state; falls back to "visual" when the active tab's feature is hidden. */
export function useTabState(availability: TabAvailability) {
  const [activeTab, setActiveTab] = useState<ActiveTab>("visual");
  const { hasRawSqlTab, hasPipelineTab, hasPlanTab, hasVisualChartTab } = availability;

  useEffect(() => {
    if (activeTab === "sql" && !hasRawSqlTab) setActiveTab("visual");
    if (activeTab === "pipeline" && !hasPipelineTab) setActiveTab("visual");
    if (activeTab === "plan" && !hasPlanTab) setActiveTab("visual");
    if (activeTab === "chart" && !hasVisualChartTab) setActiveTab("visual");
  }, [activeTab, hasRawSqlTab, hasPipelineTab, hasPlanTab, hasVisualChartTab]);

  return [activeTab, setActiveTab] as const;
}
