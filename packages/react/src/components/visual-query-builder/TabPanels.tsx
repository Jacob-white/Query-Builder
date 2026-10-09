import React from "react";
import type { CteSpec, QueryPlanNode, QueryResultData } from "../../types";
import type { QueryBuilderClassNames } from "../../types";
import type { CellRenderer } from "../../theme/QueryBuilderProvider";
import { QueryResultsTable } from "../QueryResultsTable";
import { QueryChartPreview } from "../QueryChartPreview";
import { QueryPlanVisualizer } from "../QueryPlanVisualizer";
import { PipelineDagCanvas } from "../PipelineDagCanvas";
import type { ActiveTab } from "./types";

function Panel({ tab, children }: { tab: ActiveTab; children: React.ReactNode }) {
  return (
    <div
      role="tabpanel"
      id={`panel-${tab}`}
      aria-labelledby={`tab-${tab}`}
      tabIndex={0}
      data-qb="tab-panel"
      data-qb-panel={tab}
    >
      {children}
    </div>
  );
}

export function ResultsPanel(props: {
  results: QueryResultData | null;
  isLoading: boolean;
  unstyled: boolean;
  cellRenderers?: Record<string, CellRenderer>;
  classNames?: QueryBuilderClassNames;
}) {
  return (
    <Panel tab="results">
      <QueryResultsTable
        results={props.results}
        isLoading={props.isLoading}
        unstyled={props.unstyled}
        cellRenderers={props.cellRenderers}
        classNames={props.classNames}
      />
    </Panel>
  );
}

export function ChartPanel(props: { results: QueryResultData | null; unstyled: boolean }) {
  return (
    <Panel tab="chart">
      <QueryChartPreview results={props.results} unstyled={props.unstyled} />
    </Panel>
  );
}

export function PlanPanel(props: { plan: QueryPlanNode; unstyled: boolean }) {
  return (
    <Panel tab="plan">
      <QueryPlanVisualizer plan={props.plan} unstyled={props.unstyled} />
    </Panel>
  );
}

export function PipelinePanel(props: {
  ctes: CteSpec[];
  onCtesChange: (ctes: CteSpec[]) => void;
  onSelectStage: (stage: string | null) => void;
  selectedStage: string | null;
  unstyled: boolean;
}) {
  return (
    <Panel tab="pipeline">
      <PipelineDagCanvas
        ctes={props.ctes}
        onCtesChange={props.onCtesChange}
        onSelectStage={props.onSelectStage}
        selectedStage={props.selectedStage}
        unstyled={props.unstyled}
      />
    </Panel>
  );
}
