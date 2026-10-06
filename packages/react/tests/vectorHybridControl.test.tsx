import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { VectorHybridControl } from "../src/components/VectorHybridControl";
import type { TableMeta } from "../src/types";

describe("VectorHybridControl", () => {
  const activeTables: TableMeta[] = [
    {
      name: "documents",
      columns: [
        { name: "id", data_type: "integer", is_nullable: false, is_primary: true },
        { name: "title", data_type: "text", is_nullable: false, is_primary: false },
        { name: "content", data_type: "text", is_nullable: true, is_primary: false },
        { name: "embedding", data_type: "vector", is_nullable: true, is_primary: false },
      ],
    },
  ];

  it("renders with default Off mode and toggles to Vector mode", () => {
    const handleVectorChange = vi.fn();
    const handleHybridChange = vi.fn();

    render(
      <VectorHybridControl
        activeTables={activeTables}
        onVectorChange={handleVectorChange}
        onHybridChange={handleHybridChange}
      />
    );

    expect(screen.getByText(/Semantic & Vector Retrieval/i)).toBeTruthy();
    expect(screen.queryByText(/Vector Column/i)).toBeNull();

    // Click Vector mode
    fireEvent.click(screen.getByText("Vector (KNN)"));
    expect(handleVectorChange).toHaveBeenCalled();
    const vs = handleVectorChange.mock.calls[0][0];
    expect(vs.column).toBe("embedding");
    expect(vs.metric).toBe("cosine");
    expect(vs.top_k).toBe(10);
  });

  it("switches to Hybrid mode and displays text search controls", () => {
    const handleVectorChange = vi.fn();
    const handleHybridChange = vi.fn();

    render(
      <VectorHybridControl
        activeTables={activeTables}
        onVectorChange={handleVectorChange}
        onHybridChange={handleHybridChange}
      />
    );

    // Click Hybrid mode
    fireEvent.click(screen.getByText("Hybrid (RRF)"));
    expect(handleHybridChange).toHaveBeenCalled();
    const hs = handleHybridChange.mock.calls[0][0];
    expect(hs.vector_column).toBe("embedding");
    expect(hs.fusion).toBe("rrf");
    expect(hs.rrf_k).toBe(60);

    expect(screen.getByText(/Keyword \/ Full-Text Search Configuration/i)).toBeTruthy();
  });

  it("generates mock normalized embeddings when random vector button is clicked", () => {
    const handleVectorChange = vi.fn();
    const handleHybridChange = vi.fn();

    render(
      <VectorHybridControl
        vectorSearch={{
          vector: [0.1, 0.2, 0.3],
          column: "embedding",
          metric: "cosine",
          top_k: 5,
        }}
        activeTables={activeTables}
        onVectorChange={handleVectorChange}
        onHybridChange={handleHybridChange}
      />
    );

    const mockBtn = screen.getByText(/Random Normalized Vector/i);
    fireEvent.click(mockBtn);

    expect(handleVectorChange).toHaveBeenCalled();
    const latestCall = handleVectorChange.mock.calls[handleVectorChange.mock.calls.length - 1][0];
    expect(latestCall.vector).toHaveLength(8);
  });

  it("supports unstyled rendering across off, vector, and hybrid modes (rrf and linear)", () => {
    // 1. Off mode unstyled
    const { container: c1 } = render(
      <VectorHybridControl
        activeTables={activeTables}
        onVectorChange={vi.fn()}
        onHybridChange={vi.fn()}
        unstyled={true}
      />
    );
    const root1 = c1.querySelector('[data-qb="vector-hybrid-control"]');
    expect(root1).toBeTruthy();
    expect(root1?.getAttribute("style")).toBeNull();

    // 2. Vector mode unstyled
    const { container: c2 } = render(
      <VectorHybridControl
        vectorSearch={{ vector: [0.1, 0.2], column: "embedding" }}
        activeTables={activeTables}
        onVectorChange={vi.fn()}
        onHybridChange={vi.fn()}
        unstyled={true}
      />
    );
    const root2 = c2.querySelector('[data-qb="vector-hybrid-body"]');
    expect(root2).toBeTruthy();
    expect(root2?.getAttribute("style")).toBeNull();

    // 3. Hybrid mode with RRF unstyled
    const { container: c3 } = render(
      <VectorHybridControl
        hybridSearch={{
          vector: [0.1, 0.2],
          vector_column: "embedding",
          fusion: "rrf",
          rrf_k: 60,
          query_text: "test",
          text_columns: ["title"],
        }}
        activeTables={activeTables}
        onVectorChange={vi.fn()}
        onHybridChange={vi.fn()}
        unstyled={true}
      />
    );
    const hybridSec3 = c3.querySelector('[data-qb="hybrid-section"]');
    expect(hybridSec3).toBeTruthy();
    expect(hybridSec3?.getAttribute("style")).toBeNull();

    // 4. Hybrid mode with Linear fusion unstyled
    const { container: c4 } = render(
      <VectorHybridControl
        hybridSearch={{
          vector: [0.1, 0.2],
          vector_column: "embedding",
          fusion: "linear",
          alpha: 0.7,
          query_text: "test",
          text_columns: ["title"],
        }}
        activeTables={activeTables}
        onVectorChange={vi.fn()}
        onHybridChange={vi.fn()}
        unstyled={true}
      />
    );
    const slider4 = c4.querySelector('[data-qb="alpha-slider"]');
    expect(slider4).toBeTruthy();
    expect(slider4?.getAttribute("style")).toBeNull();
  });

  it("handles switching to Off mode and clearing both vector and hybrid specs", () => {
    const onVectorChange = vi.fn();
    const onHybridChange = vi.fn();

    render(
      <VectorHybridControl
        vectorSearch={{ vector: [0.1, 0.2], column: "embedding" }}
        activeTables={activeTables}
        onVectorChange={onVectorChange}
        onHybridChange={onHybridChange}
      />
    );

    const offBtn = screen.getByText("Off");
    fireEvent.click(offBtn);

    expect(onVectorChange).toHaveBeenCalledWith(null);
    expect(onHybridChange).toHaveBeenCalledWith(null);
  });

  it("handles full lifecycle of vector inputs: column, metric, vector text, topK, includeDistances", async () => {
    const onVectorChange = vi.fn();
    const onHybridChange = vi.fn();

    render(
      <VectorHybridControl
        vectorSearch={{
          vector: [0.1, 0.2],
          column: "embedding",
          metric: "cosine",
          top_k: 10,
          include_distances: false,
          min_score: 0.85,
        }}
        activeTables={activeTables}
        onVectorChange={onVectorChange}
        onHybridChange={onHybridChange}
      />
    );

    // 1. Change vector column
    const allSelects = screen.getAllByRole("combobox");
    const vectorColSelect = allSelects[0];
    fireEvent.change(vectorColSelect, { target: { value: "title" } });

    // 2. Change metric
    const metricSelect = allSelects[1];
    fireEvent.change(metricSelect, { target: { value: "l2" } });

    // 3. Change vector input textarea (JSON and comma-separated)
    const textarea = screen.getByPlaceholderText(/\[0.1, 0.4/);
    fireEvent.change(textarea, { target: { value: "0.4, 0.8, -0.3" } });

    // 4. Change top-k input (valid number and empty fallback)
    const topKInput = screen.getByDisplayValue("10");
    fireEvent.change(topKInput, { target: { value: "25" } });
    fireEvent.change(topKInput, { target: { value: "" } }); // tests fallback Math.max(1, parseInt(...) || 10)

    // 5. Toggle include distances checkbox
    const distCheckbox = screen.getByRole("checkbox");
    fireEvent.click(distCheckbox);

    await new Promise((r) => setTimeout(r, 20));

    expect(onVectorChange).toHaveBeenCalled();
  });

  it("handles hybrid search controls: query text, column toggles, fusion switch, alpha slider, rrfK, and mock embeddings", async () => {
    const onVectorChange = vi.fn();
    const onHybridChange = vi.fn();

    render(
      <VectorHybridControl
        hybridSearch={{
          vector: [0.1, 0.2],
          vector_column: "embedding",
          query_text: "distributed",
          text_columns: ["title", "content"],
          fusion: "rrf",
          rrf_k: 60,
          alpha: 0.5,
        }}
        activeTables={activeTables}
        onVectorChange={onVectorChange}
        onHybridChange={onHybridChange}
      />
    );

    // 1. Change query text
    const queryTextInput = screen.getByPlaceholderText(/distributed vector database clustering/i);
    fireEvent.change(queryTextInput, { target: { value: "cloud native indexing" } });

    // 2. Column toggles:
    // Deselect "title" (now only "content" remains)
    const titleBtn = screen.getByRole("button", { name: "✓ documents.title" });
    fireEvent.click(titleBtn);

    // Deselect "content" (last remaining column -> should keep it)
    const contentBtn = screen.getByRole("button", { name: "✓ documents.content" });
    fireEvent.click(contentBtn);

    // Re-select "title"
    const unselectedTitleBtn = screen.getByRole("button", { name: "documents.title" });
    fireEvent.click(unselectedTitleBtn);

    // 3. Change RRF k input
    const rrfKInput = screen.getByDisplayValue("60");
    fireEvent.change(rrfKInput, { target: { value: "80" } });
    fireEvent.change(rrfKInput, { target: { value: "" } }); // tests fallback parseInt || 60

    // 4. Switch fusion to Linear Combination
    const fusionSelect = screen.getByDisplayValue("Reciprocal Rank Fusion (RRF)");
    fireEvent.change(fusionSelect, { target: { value: "linear" } });

    // 5. Change alpha slider
    const alphaSlider = screen.getByRole("slider");
    fireEvent.change(alphaSlider, { target: { value: "0.8" } });

    // 6. Generate mock embedding while in hybrid mode
    const mockBtn = screen.getByText(/Random Normalized Vector/i);
    fireEvent.click(mockBtn);

    await new Promise((r) => setTimeout(r, 20));

    expect(onHybridChange).toHaveBeenCalled();
  });

  it("handles fallback column names when tables have no embed or text columns, and handles invalid parseVector strings", () => {
    const onVectorChange = vi.fn();
    const onHybridChange = vi.fn();

    // Table with no 'embed' and no 'text' columns
    const minimalTables: TableMeta[] = [
      {
        name: "metrics",
        columns: [
          { name: "count", data_type: "bigint", is_nullable: false, is_primary: false },
        ],
      },
    ];

    render(
      <VectorHybridControl
        activeTables={minimalTables}
        onVectorChange={onVectorChange}
        onHybridChange={onHybridChange}
      />
    );

    // Switch to Vector mode: uses count as default column
    fireEvent.click(screen.getByText("Vector (KNN)"));
    expect(onVectorChange).toHaveBeenCalled();
    const vs = onVectorChange.mock.calls[0][0];
    expect(vs.column).toBe("count");

    // Test parseVector with non-array JSON e.g. "123"
    const textarea = screen.getByPlaceholderText(/\[0.1, 0.4/);
    fireEvent.change(textarea, { target: { value: "123" } });
    fireEvent.click(screen.getByText("Off"));
    fireEvent.click(screen.getByText("Vector (KNN)"));

    const latestVs = onVectorChange.mock.calls[onVectorChange.mock.calls.length - 1][0];
    expect(latestVs.vector).toEqual([0.1, 0.2, 0.3]);
  });

  it("handles empty vector strings and invalid comma lists across mode switches and column toggles", async () => {
    const onVectorChange = vi.fn();
    const onHybridChange = vi.fn();

    const { getByPlaceholderText, getByText, getByRole } = render(
      <VectorHybridControl
        hybridSearch={{
          vector: [0.1, 0.2],
          vector_column: "embedding",
          query_text: "test",
          text_columns: [], // tests textColumns.length === 0 fallback
        }}
        activeTables={activeTables}
        onVectorChange={onVectorChange}
        onHybridChange={onHybridChange}
      />
    );

    // Set vector textarea to invalid comma list resulting in empty filtered array
    const textarea = getByPlaceholderText(/\[0.1, 0.4/);
    fireEvent.change(textarea, { target: { value: "foo, bar" } });

    // Trigger an input change (e.g. checkbox) while vectorInput is invalid
    const distToggle = getByRole("checkbox");
    fireEvent.click(distToggle);
    await new Promise((r) => setTimeout(r, 20));

    // Toggle mode to vector and hybrid while vector is empty
    getByText("Vector (KNN)").click();
    expect(onVectorChange).toHaveBeenCalled();
    const lastVecCall = onVectorChange.mock.calls[onVectorChange.mock.calls.length - 1][0];
    expect(lastVecCall.vector).toEqual([0.1, 0.2, 0.3]);

    getByText("Hybrid (RRF)").click();
    expect(onHybridChange).toHaveBeenCalled();
    const lastHybCall = onHybridChange.mock.calls[onHybridChange.mock.calls.length - 1][0];
    expect(lastHybCall.vector).toEqual([0.1, 0.2, 0.3]);
    expect(lastHybCall.text_columns).toEqual(["title"]); // tested fallback from empty initial array

    // Toggle column while vector is empty
    const colBtn = getByRole("button", { name: "documents.title" });
    fireEvent.click(colBtn);
    expect(onHybridChange).toHaveBeenCalled();
  });

  it("handles zero norm mock embedding generation and empty table metadata gracefully", () => {
    const onHybridChange = vi.fn();

    // 1. Math.random spy returns 0.5 so (0.5 * 2 - 1) === 0, resulting in zero norm
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0.5);

    const { getByText } = render(
      <VectorHybridControl
        hybridSearch={{
          vector: [0.1, 0.2],
          vector_column: "embedding",
          query_text: "search",
          text_columns: [],
        }}
        activeTables={[]} // tests activeTables = []
        onVectorChange={vi.fn()}
        onHybridChange={onHybridChange}
      />
    );

    const mockBtn = getByText(/Random Normalized Vector/i);
    fireEvent.click(mockBtn);
    expect(onHybridChange).toHaveBeenCalled();
    const callArg = onHybridChange.mock.calls[0][0];
    expect(callArg.vector).toHaveLength(8);
    expect(callArg.vector[0]).toBe(0);

    randomSpy.mockRestore();
  });

  it("handles legacy/custom table column types and default fallbacks", () => {
    const customTables: any[] = [
      {
        name: "custom_tbl",
        columns: [
          { name: "legacy_col", type: "varchar" }, // missing data_type, has type
          { name: "fallback_col" }, // missing both data_type and type
        ],
      },
    ];

    const { getByText } = render(
      <VectorHybridControl
        activeTables={customTables}
        onVectorChange={vi.fn()}
        onHybridChange={vi.fn()}
      />
    );

    expect(getByText(/Semantic & Vector Retrieval/i)).toBeTruthy();
  });
});

