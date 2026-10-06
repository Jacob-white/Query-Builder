"""
Reciprocal Rank Fusion (RRF) and Hybrid Search Fusion Algorithms.
==================================================================
Pure-Python implementations of Reciprocal Rank Fusion (RRF) and linear
score combination for multi-modal and hybrid search retrieval.
Zero external dependencies.
"""

from __future__ import annotations

from typing import Any


def reciprocal_rank_fusion(
    dense_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    key: str = "id",
    rrf_k: int = 60,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Merges two ranked lists using the Reciprocal Rank Fusion (RRF) algorithm.

    Score formula:
        RRF_Score(doc) = sum_{m in {dense, sparse}} 1 / (rrf_k + rank_m(doc))
    where rank is 1-indexed.

    Args:
        dense_results: Ranked list of items from dense vector KNN retrieval.
        sparse_results: Ranked list of items from sparse/keyword retrieval.
        key: Unique document identifier field in result dictionaries.
        rrf_k: Smoothing constant (standard default is 60).
        top_k: Maximum number of fused results to return.

    Returns:
        Fused list of result dictionaries with an added '_score' field,
        sorted in descending order of score.
    """
    if rrf_k <= 0:
        rrf_k = 60

    scores: dict[Any, float] = {}
    doc_map: dict[Any, dict[str, Any]] = {}

    # Dense ranking pass (1-indexed)
    for rank, item in enumerate(dense_results, start=1):
        doc_id = item.get(key)
        if doc_id is None:
            # Fallback to id(item) if key not present
            doc_id = id(item)
        if doc_id not in doc_map:
            doc_map[doc_id] = dict(item)
        else:
            doc_map[doc_id].update({k: v for k, v in item.items() if k not in doc_map[doc_id]})
        scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))

    # Sparse ranking pass (1-indexed)
    for rank, item in enumerate(sparse_results, start=1):
        doc_id = item.get(key)
        if doc_id is None:
            doc_id = id(item)
        if doc_id not in doc_map:
            doc_map[doc_id] = dict(item)
        else:
            doc_map[doc_id].update({k: v for k, v in item.items() if k not in doc_map[doc_id]})
        scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (rrf_k + rank))

    # Sort documents by descending RRF score
    sorted_ids = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)

    results: list[dict[str, Any]] = []
    for doc_id in sorted_ids[:top_k]:
        record = dict(doc_map[doc_id])
        record["_score"] = round(scores[doc_id], 6)
        results.append(record)

    return results


def linear_combination_fusion(
    dense_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    key: str = "id",
    alpha: float = 0.5,
    dense_score_key: str = "_score",
    sparse_score_key: str = "_score",
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Merges dense and sparse search results using normalized linear combination.

    Formula:
        Score(doc) = alpha * norm(dense_score) + (1 - alpha) * norm(sparse_score)

    Args:
        dense_results: List of items from dense vector search with score.
        sparse_results: List of items from text search with score.
        key: Unique document identifier field in result dictionaries.
        alpha: Weight for dense vector search (0.0 to 1.0).
        dense_score_key: Key name containing dense similarity/distance score.
        sparse_score_key: Key name containing sparse BM25/keyword score.
        top_k: Maximum number of fused results to return.

    Returns:
        Fused list of result dictionaries with an added '_score' field,
        sorted in descending order.
    """
    alpha = max(0.0, min(1.0, float(alpha)))

    def _normalize_scores(items: list[dict[str, Any]], score_key: str) -> dict[Any, float]:
        raw: dict[Any, float] = {}
        for item in items:
            doc_id = item.get(key, id(item))
            score_val = item.get(score_key, 0.0)
            try:
                raw[doc_id] = float(score_val)
            except (ValueError, TypeError):
                raw[doc_id] = 0.0

        if not raw:
            return {}

        vals = list(raw.values())
        min_v, max_v = min(vals), max(vals)
        if max_v == min_v:
            return {d: 1.0 for d in raw}
        return {d: (val - min_v) / (max_v - min_v) for d, val in raw.items()}

    norm_dense = _normalize_scores(dense_results, dense_score_key)
    norm_sparse = _normalize_scores(sparse_results, sparse_score_key)

    all_ids = set(norm_dense.keys()) | set(norm_sparse.keys())
    doc_map: dict[Any, dict[str, Any]] = {}

    for item in dense_results:
        doc_id = item.get(key, id(item))
        if doc_id not in doc_map:
            doc_map[doc_id] = dict(item)

    for item in sparse_results:
        doc_id = item.get(key, id(item))
        if doc_id not in doc_map:
            doc_map[doc_id] = dict(item)
        else:
            doc_map[doc_id].update({k: v for k, v in item.items() if k not in doc_map[doc_id]})

    final_scores: dict[Any, float] = {}
    for doc_id in all_ids:
        d_val = norm_dense.get(doc_id, 0.0)
        s_val = norm_sparse.get(doc_id, 0.0)
        final_scores[doc_id] = alpha * d_val + (1.0 - alpha) * s_val

    sorted_ids = sorted(all_ids, key=lambda d: final_scores[d], reverse=True)

    results: list[dict[str, Any]] = []
    for doc_id in sorted_ids[:top_k]:
        record = dict(doc_map[doc_id])
        record["_score"] = round(final_scores[doc_id], 6)
        results.append(record)

    return results
