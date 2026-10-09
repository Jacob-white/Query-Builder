import React from "react";
import type { ComponentProps } from "react";
import { QueryCanvas } from "../QueryCanvas";
import { NlqPromptBar } from "../NlqPromptBar";

export type VisualPanelProps = {
  /** Props forwarded to the canvas as-is. */
  canvas: ComponentProps<typeof QueryCanvas>;
  /** Natural-language bar; omitted when disabled. */
  nlq?: ComponentProps<typeof NlqPromptBar>;
};

/** Visual builder tab: optional NLQ bar above the query canvas. */
export function VisualPanel({ canvas, nlq }: VisualPanelProps) {
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
    </div>
  );
}
