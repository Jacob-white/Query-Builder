import React from "react";
import type {
  CteSpec,
  QueryPlanNode,
  QueryResultData,
  QuerySpec,
  SchemaSnapshot,
  SqlDialect,
} from "../../types";
import type { QueryBuilderClassNames } from "../../types";
import type { CellRenderer } from "../../theme/QueryBuilderProvider";
import { QueryResultsTable } from "../QueryResultsTable";
import { BiChartVisualizer } from "../BiChartVisualizer";
import { QueryPlanVisualizer } from "../QueryPlanVisualizer";
import { QueryPerformanceAdvisor } from "../QueryPerformanceAdvisor";
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
  onReorderColumns?: (newColumns: string[]) => void;
  schema?: SchemaSnapshot | null;
  onFilterByCell?: (
    column: string,
    value: unknown,
    operator: "=" | "!=" | "IS NULL" | "IS NOT NULL",
  ) => void;
  onDrillDownForeignKey?: (
    column: string,
    value: unknown,
    targetTable?: string,
    targetColumn?: string,
  ) => void;
  onPinToDashboard?: () => void;
  classNames?: QueryBuilderClassNames;
}) {
  return (
    <Panel tab="results">
      <QueryResultsTable
        results={props.results}
        isLoading={props.isLoading}
        unstyled={props.unstyled}
        cellRenderers={props.cellRenderers}
        onReorderColumns={props.onReorderColumns}
        schema={props.schema}
        onFilterByCell={props.onFilterByCell}
        onDrillDownForeignKey={props.onDrillDownForeignKey}
        onPinToDashboard={props.onPinToDashboard}
        classNames={props.classNames}
      />
    </Panel>
  );
}

export function ChartPanel(props: { results: QueryResultData | null; unstyled: boolean }) {
  return (
    <Panel tab="chart">
      <BiChartVisualizer results={props.results} unstyled={props.unstyled} />
    </Panel>
  );
}

export function PlanPanel(props: {
  plan: QueryPlanNode;
  spec?: Partial<QuerySpec>;
  sql?: string;
  dialect?: SqlDialect;
  schema?: SchemaSnapshot | null;
  unstyled: boolean;
}) {
  return (
    <Panel tab="plan">
      <div
        style={
          props.unstyled
            ? undefined
            : { display: "flex", flexDirection: "column", gap: "12px" }
        }
      >
        <QueryPlanVisualizer plan={props.plan} unstyled={props.unstyled} />
        <QueryPerformanceAdvisor
          querySpec={props.spec || { table: props.plan.table }}
          sql={props.sql || ""}
          dialect={props.dialect}
          schema={props.schema}
          unstyled={props.unstyled}
        />
      </div>
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
