import React from "react";
import type { ComponentProps } from "react";
import { QueryCanvas } from "../QueryCanvas";
import { NlqPromptBar } from "../NlqPromptBar";
import { WorkspaceDock } from "./WorkspaceDock";

export type VisualPanelProps = {
  /** Props forwarded to the canvas as-is. */
  canvas: ComponentProps<typeof QueryCanvas>;
  /** Natural-language bar; omitted when disabled. */
  nlq?: ComponentProps<typeof NlqPromptBar>;
  /** Optional split-view workspace dock for results / chart / live SQL. */
  dock?: ComponentProps<typeof WorkspaceDock>;
};

/** Visual builder tab: optional NLQ bar above the query canvas, and optional docked workspace below. */
export function VisualPanel({ canvas, nlq, dock }: VisualPanelProps) {
  return (
    <div
      role="tabpanel"
      id="panel-visual"
      aria-labelledby="tab-visual"
      tabIndex={0}
      data-qb="tab-panel"
      data-qb-panel="visual"
    >
      {nlq && <NlqPromptBar {...nlq} />}
      <QueryCanvas {...canvas} />
      {dock && <WorkspaceDock {...dock} />}
    </div>
  );
}
