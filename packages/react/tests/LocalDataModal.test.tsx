import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LocalDataModal } from "../src/components/LocalDataModal";
import { resetClientOlapEngine, getClientOlapEngine } from "../src/drivers/duckdbDriver";

describe("LocalDataModal Component", () => {
  beforeEach(() => {
    resetClientOlapEngine();
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(<LocalDataModal isOpen={false} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders modal header, dropzone, and empty state when isOpen is true", () => {
    render(<LocalDataModal isOpen={true} onClose={vi.fn()} />);

    expect(screen.getByText("Client-Side OLAP & File Intake")).toBeDefined();
    expect(screen.getByTestId("local-data-dropzone")).toBeDefined();
    expect(screen.getByText(/No client tables loaded/)).toBeDefined();
  });

  it("calls onClose when close button or overlay is clicked", () => {
    const onClose = vi.fn();
    render(<LocalDataModal isOpen={true} onClose={onClose} />);

    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("local-data-modal-overlay"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("handles drag over and drag leave on the dropzone", () => {
    render(<LocalDataModal isOpen={true} onClose={vi.fn()} />);
    const dropzone = screen.getByTestId("local-data-dropzone");

    fireEvent.dragOver(dropzone);
    fireEvent.dragLeave(dropzone);
  });

  it("ingests file via file input change", async () => {
    const onTableSelected = vi.fn();
    render(<LocalDataModal isOpen={true} onClose={vi.fn()} onTableSelected={onTableSelected} />);

    const file = new File(["id,name\n1,Alpha\n2,Beta"], "clients.csv", { type: "text/csv" });
    const input = screen.getByTestId("local-data-file-input");

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByTestId("local-data-success")).toBeDefined();
    });

    expect(screen.getByText("clients")).toBeDefined();
    expect(onTableSelected).toHaveBeenCalledWith("clients");
  });

  it("ingests file via drop event", async () => {
    const onTableSelected = vi.fn();
    render(<LocalDataModal isOpen={true} onClose={vi.fn()} onTableSelected={onTableSelected} />);

    const file = new File(["id,score\n1,100"], "scores.csv", { type: "text/csv" });
    const dropzone = screen.getByTestId("local-data-dropzone");

    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [file],
      },
    });

    await waitFor(() => {
      expect(screen.getByText("scores")).toBeDefined();
    });
  });

  it("allows selecting a table and dropping a table", async () => {
    const engine = getClientOlapEngine();
    await engine.ingestCsv("table_a", "id\n1");
    await engine.ingestCsv("table_b", "id\n2");

    const onTableSelected = vi.fn();
    render(<LocalDataModal isOpen={true} onClose={vi.fn()} onTableSelected={onTableSelected} />);

    expect(screen.getByText("table_a")).toBeDefined();
    expect(screen.getByText("table_b")).toBeDefined();

    // Click select table_a
    const selectBtn = screen.getByTestId("local-table-select-table_a");
    fireEvent.click(selectBtn);
    expect(onTableSelected).toHaveBeenCalledWith("table_a");

    // Click drop table_b
    const dropBtn = screen.getByTestId("local-table-drop-table_b");
    fireEvent.click(dropBtn);

    await waitFor(() => {
      expect(screen.queryByText("table_b")).toBeNull();
    });

    // Click clear all
    const clearBtn = screen.getByTestId("local-data-clear-all");
    fireEvent.click(clearBtn);

    await waitFor(() => {
      expect(screen.queryByText("table_a")).toBeNull();
    });
  });
});
