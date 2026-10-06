import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { LiveExecutionBar } from "../src/components/LiveExecutionBar";

describe("LiveExecutionBar Component", () => {
  it("renders with default props and idle status", () => {
    render(<LiveExecutionBar />);

    expect(screen.getByTestId("live-execution-bar")).toBeTruthy();
    expect(screen.getByText("Database Idle")).toBeTruthy();
    expect(screen.getByText("▶ Execute Query")).toBeTruthy();
  });

  it("renders connectionId when status is idle and connectionId is provided", () => {
    render(<LiveExecutionBar connectionId="postgres_prod" />);
    expect(screen.getByText("DB: postgres_prod")).toBeTruthy();
  });

  it("renders connected status with latency badge and green dot", () => {
    render(
      <LiveExecutionBar
        connectionStatus="connected"
        connectionLatencyMs={24}
      />
    );

    expect(screen.getByText("Connected (24ms)")).toBeTruthy();
    const dot = screen.getByTestId("status-indicator-dot");
    expect(dot.style.backgroundColor).toBe("rgb(16, 185, 129)"); // #10b981
  });

  it("renders connected status without latency when latencyMs is null", () => {
    render(<LiveExecutionBar connectionStatus="connected" connectionLatencyMs={null} />);
    expect(screen.getByText("Connected")).toBeTruthy();
    const dot = screen.getByTestId("status-indicator-dot");
    expect(dot.style.backgroundColor).toBe("rgb(16, 185, 129)");
  });

  it("renders testing status with amber dot", () => {
    render(<LiveExecutionBar connectionStatus="testing" />);

    expect(screen.getByText("Testing...")).toBeTruthy();
    const dot = screen.getByTestId("status-indicator-dot");
    expect(dot.style.backgroundColor).toBe("rgb(245, 158, 11)"); // #f59e0b
  });

  it("renders error status with red dot", () => {
    render(<LiveExecutionBar connectionStatus="error" />);

    expect(screen.getByText("Connection Error")).toBeTruthy();
    const dot = screen.getByTestId("status-indicator-dot");
    expect(dot.style.backgroundColor).toBe("rgb(239, 68, 68)"); // #ef4444
  });

  it("renders disconnected status with red dot", () => {
    render(<LiveExecutionBar connectionStatus="disconnected" />);

    expect(screen.getByText("Disconnected")).toBeTruthy();
    const dot = screen.getByTestId("status-indicator-dot");
    expect(dot.style.backgroundColor).toBe("rgb(239, 68, 68)"); // #ef4444
  });

  it("handles onTestConnection click", () => {
    const onTestConnection = vi.fn();
    render(<LiveExecutionBar onTestConnection={onTestConnection} />);

    const pingBtn = screen.getByRole("button", { name: "Test database connection" });
    expect(pingBtn).toBeTruthy();
    expect(pingBtn.textContent).toBe("Ping");

    fireEvent.click(pingBtn);
    expect(onTestConnection).toHaveBeenCalledTimes(1);
  });

  it("disables test button while connectionStatus is testing", () => {
    const onTestConnection = vi.fn();
    render(
      <LiveExecutionBar
        connectionStatus="testing"
        onTestConnection={onTestConnection}
      />
    );

    const pingBtn = screen.getByRole("button", { name: "Test database connection" });
    expect(pingBtn.hasAttribute("disabled")).toBe(true);
    expect(pingBtn.textContent).toBe("...");
  });

  it("hides connection pill when showConnectionPill is false", () => {
    render(<LiveExecutionBar showConnectionPill={false} />);
    expect(screen.queryByTestId("status-indicator-dot")).toBeNull();
  });

  it("handles onExecute click", () => {
    const onExecute = vi.fn();
    render(<LiveExecutionBar onExecute={onExecute} />);

    const runBtn = screen.getByRole("button", { name: "Execute live query" });
    fireEvent.click(runBtn);
    expect(onExecute).toHaveBeenCalledTimes(1);
  });

  it("shows executing state and cancel button when isExecuting is true", () => {
    const onCancel = vi.fn();
    render(
      <LiveExecutionBar
        isExecuting={true}
        onCancel={onCancel}
      />
    );

    const runBtn = screen.getByRole("button", { name: "Execute live query" });
    expect(runBtn.hasAttribute("disabled")).toBe(true);
    expect(runBtn.textContent).toContain("⏳ Running...");

    const cancelBtn = screen.getByRole("button", { name: "Cancel live query execution" });
    expect(cancelBtn).toBeTruthy();

    fireEvent.click(cancelBtn);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("formats execution time under 1000ms in ms", () => {
    render(<LiveExecutionBar executionTimeMs={350} />);
    expect(screen.getByTestId("execution-time-badge").textContent).toBe("⏱️ 350ms");
  });

  it("formats execution time 1000ms or over in seconds", () => {
    render(<LiveExecutionBar executionTimeMs={2450} />);
    expect(screen.getByTestId("execution-time-badge").textContent).toBe("⏱️ 2.45s");
  });

  it("displays row count formatted with locale commas", () => {
    render(<LiveExecutionBar rowCount={12500} />);
    expect(screen.getByTestId("row-count-badge").textContent).toBe("📊 12,500 rows");
  });

  it("displays error message and handles dismissal", () => {
    const onDismissError = vi.fn();
    render(
      <LiveExecutionBar
        error="Fatal database timeout"
        onDismissError={onDismissError}
      />
    );

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Fatal database timeout");

    const dismissBtn = screen.getByRole("button", { name: "Dismiss execution error" });
    fireEvent.click(dismissBtn);
    expect(onDismissError).toHaveBeenCalledTimes(1);
  });

  it("renders error message without dismiss button if onDismissError is omitted", () => {
    render(<LiveExecutionBar error="Some unrecoverable error" />);
    expect(screen.getByRole("alert").textContent).toContain("Some unrecoverable error");
    expect(
      screen.queryByRole("button", { name: "Dismiss execution error" })
    ).toBeNull();
  });

  it("supports unstyled mode", () => {
    const { container } = render(
      <LiveExecutionBar
        unstyled={true}
        className="my-custom-bar"
        isExecuting={true}
        executionTimeMs={120}
        rowCount={5}
        error="Warning"
        onDismissError={vi.fn()}
        onCancel={vi.fn()}
        onTestConnection={vi.fn()}
      />
    );

    const bar = container.querySelector(".my-custom-bar");
    expect(bar).toBeTruthy();
    // In unstyled mode, style attribute is not populated by the inline style object
    expect(bar?.getAttribute("style")).toBeNull();
  });
});
