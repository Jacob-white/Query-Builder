import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CalculatedFieldEditor } from "../src/components/CalculatedFieldEditor";
import type { TableMeta, CalculatedFieldSpec } from "../src/types";
import { makeColumn } from "./helpers";

describe("CalculatedFieldEditor", () => {
  const dummyTables: TableMeta[] = [
    {
      name: "customers",
      columns: [
        makeColumn("id", { data_type: "integer", is_nullable: false }),
        makeColumn("status", { data_type: "varchar", is_nullable: true }),
        makeColumn("spend", { data_type: "decimal", is_nullable: false }),
      ],
    },
    {
      name: "orders",
      columns: [
        makeColumn("order_id", { data_type: "integer", is_nullable: false }),
        makeColumn("amount", { data_type: "decimal", is_nullable: false }),
      ],
    },
  ];

  it("returns null when isOpen is false", () => {
    const { container } = render(
      <CalculatedFieldEditor
        isOpen={false}
        onClose={vi.fn()}
        onSave={vi.fn()}
        tables={dummyTables}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders modal with default state and closes on cancel or close button", () => {
    const onClose = vi.fn();
    const onSave = vi.fn();

    render(
      <CalculatedFieldEditor
        isOpen={true}
        onClose={onClose}
        onSave={onSave}
        tables={dummyTables}
      />
    );

    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("✨ Calculated Column Editor")).toBeTruthy();

    // Close button
    const closeBtn = screen.getByLabelText("Close calculated column editor");
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);

    // Cancel button
    const cancelBtn = screen.getByText("Cancel");
    fireEvent.click(cancelBtn);
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("allows adding, configuring, removing branches, and saving CASE WHEN spec", () => {
    const onSave = vi.fn();
    const onClose = vi.fn();

    render(
      <CalculatedFieldEditor
        isOpen={true}
        onClose={onClose}
        onSave={onSave}
        tables={dummyTables}
      />
    );

    // Change alias
    const aliasInput = screen.getByLabelText("Calculated column alias");
    fireEvent.change(aliasInput, { target: { value: "tier_label" } });

    // First branch configuration
    const colSelect1 = screen.getByLabelText("Branch 1 column");
    fireEvent.change(colSelect1, { target: { value: "spend" } });

    const opSelect1 = screen.getByLabelText("Branch 1 operator");
    fireEvent.change(opSelect1, { target: { value: "gt" } });

    const valInput1 = screen.getByLabelText("Branch 1 condition value");
    fireEvent.change(valInput1, { target: { value: "1000" } });

    const thenInput1 = screen.getByLabelText("Branch 1 then value");
    fireEvent.change(thenInput1, { target: { value: "'VIP'" } });

    // Add branch
    const addBranchBtn = screen.getByText("+ Add Branch");
    fireEvent.click(addBranchBtn);

    // Second branch configuration
    const colSelect2 = screen.getByLabelText("Branch 2 column");
    fireEvent.change(colSelect2, { target: { value: "status" } });

    const opSelect2 = screen.getByLabelText("Branch 2 operator");
    fireEvent.change(opSelect2, { target: { value: "eq" } });

    const valInput2 = screen.getByLabelText("Branch 2 condition value");
    fireEvent.change(valInput2, { target: { value: "'active'" } });

    const thenInput2 = screen.getByLabelText("Branch 2 then value");
    fireEvent.change(thenInput2, { target: { value: "'Regular'" } });

    // Else value
    const elseInput = screen.getByLabelText("Else fallback value");
    fireEvent.change(elseInput, { target: { value: "'Standard'" } });

    // Save
    const saveBtn = screen.getByText("Save Column");
    fireEvent.click(saveBtn);

    expect(onSave).toHaveBeenCalledOnce();
    const savedArg: CalculatedFieldSpec = onSave.mock.calls[0][0];
    expect(savedArg.alias).toBe("tier_label");
    expect(savedArg.type).toBe("case_when");
    expect(savedArg.case_when?.branches).toHaveLength(2);
    expect(savedArg.case_when?.branches[0]).toEqual({
      condition: { column: "spend", op: "gt", value: "1000" },
      then_value: "'VIP'",
    });
    expect(savedArg.case_when?.else_value).toBe("'Standard'");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("removes a branch when multiple exist", () => {
    render(
      <CalculatedFieldEditor
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        tables={dummyTables}
      />
    );

    // Initially 1 branch, no remove button
    expect(screen.queryByLabelText("Remove branch 1")).toBeNull();

    // Add a branch
    fireEvent.click(screen.getByText("+ Add Branch"));
    expect(screen.getByLabelText("Remove branch 1")).toBeTruthy();
    expect(screen.getByLabelText("Remove branch 2")).toBeTruthy();

    // Remove branch 2
    fireEvent.click(screen.getByLabelText("Remove branch 2"));
    expect(screen.queryByLabelText("Remove branch 2")).toBeNull();
  });

  it("switches to SQL Formula Expression mode and saves formula", () => {
    const onSave = vi.fn();
    const onClose = vi.fn();

    render(
      <CalculatedFieldEditor
        isOpen={true}
        onClose={onClose}
        onSave={onSave}
        tables={dummyTables}
      />
    );

    // Switch radio to SQL Formula Expression
    const formulaRadio = screen.getByLabelText(/SQL Formula Expression/i);
    fireEvent.click(formulaRadio);

    // Check textarea exists
    const formulaTextarea = screen.getByLabelText("Formula expression");
    fireEvent.change(formulaTextarea, {
      target: { value: "orders.amount * 1.08" },
    });

    // Change alias
    const aliasInput = screen.getByLabelText("Calculated column alias");
    fireEvent.change(aliasInput, { target: { value: "amount_with_tax" } });

    // Save
    fireEvent.click(screen.getByText("Save Column"));

    expect(onSave).toHaveBeenCalledOnce();
    const savedArg: CalculatedFieldSpec = onSave.mock.calls[0][0];
    expect(savedArg.alias).toBe("amount_with_tax");
    expect(savedArg.type).toBe("expression");
    expect(savedArg.expression).toBe("orders.amount * 1.08");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("populates initialField when editing existing calculated field", () => {
    const initialField: CalculatedFieldSpec = {
      id: "calc_existing_1",
      name: "custom_status",
      alias: "custom_status",
      type: "case_when",
      case_when: {
        branches: [
          {
            condition: { column: "status", op: "is_null", value: "" },
            then_value: "'unknown'",
          },
        ],
        else_value: "'known'",
      },
    };

    render(
      <CalculatedFieldEditor
        isOpen={true}
        onClose={vi.fn()}
        onSave={vi.fn()}
        tables={dummyTables}
        initialField={initialField}
      />
    );

    const aliasInput = screen.getByLabelText("Calculated column alias") as HTMLInputElement;
    expect(aliasInput.value).toBe("custom_status");

    const thenInput = screen.getByLabelText("Branch 1 then value") as HTMLInputElement;
    expect(thenInput.value).toBe("'unknown'");

    const elseInput = screen.getByLabelText("Else fallback value") as HTMLInputElement;
    expect(elseInput.value).toBe("'known'");
  });
});
