import re
from collections import Counter
from typing import Any


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(text: str | None) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def _lcs_length(left: list[str], right: list[str]) -> int:
    """Memory-efficient longest common subsequence length."""
    if len(left) < len(right):
        left, right = right, left
    previous = [0] * (len(right) + 1)
    for token in left:
        current = [0]
        for index, other in enumerate(right, start=1):
            if token == other:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def _text_scores(prediction: str, reference: str) -> dict[str, float | None]:
    pred_tokens = _tokens(prediction)
    ref_tokens = _tokens(reference)
    if not pred_tokens or not ref_tokens:
        return {"answer_token_f1": None, "answer_rouge_l": None}
    pred_counts, ref_counts = Counter(pred_tokens), Counter(ref_tokens)
    overlap = sum((pred_counts & ref_counts).values())
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    token_f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    lcs = _lcs_length(pred_tokens, ref_tokens)
    rouge_precision = lcs / len(pred_tokens)
    rouge_recall = lcs / len(ref_tokens)
    rouge_l = (
        2 * rouge_precision * rouge_recall / (rouge_precision + rouge_recall)
        if rouge_precision + rouge_recall
        else 0.0
    )
    return {"answer_token_f1": round(token_f1, 4), "answer_rouge_l": round(rouge_l, 4)}


def evaluate_trace(trace: dict[str, Any], item: dict[str, Any], k: int) -> dict[str, Any]:
    stage = trace.get("stage") or {}
    latency = trace.get("latency_breakdown") or {}
    chunks = stage.get("retrieved_chunks") or []
    retrieved_document_ids: list[str] = []
    contexts: list[str] = []
    for chunk in chunks:
        document_id = chunk.get("document_id") or chunk.get("documentId")
        if document_id is not None:
            normalized = str(document_id)
            if normalized not in retrieved_document_ids:
                retrieved_document_ids.append(normalized)
        content = chunk.get("content")
        if content:
            contexts.append(str(content))

    top_k_ids = retrieved_document_ids[:k]
    relevant_ids = list(dict.fromkeys(str(value) for value in item.get("relevant_document_ids", []) if value))
    relevant_set = set(relevant_ids)
    hits = [index + 1 for index, doc_id in enumerate(top_k_ids) if doc_id in relevant_set]
    relevant_retrieved = len(set(top_k_ids) & relevant_set)

    recall_at_k = relevant_retrieved / len(relevant_set) if relevant_set else None
    precision_at_k = relevant_retrieved / k if relevant_set else None
    mrr_at_k = 1 / hits[0] if hits else (0.0 if relevant_set else None)

    reference_answer = (item.get("reference_answer") or "").strip()
    answer = str(stage.get("grounded_answer") or "")
    context_text = "\n".join(contexts)
    reference_tokens = set(_tokens(reference_answer))
    context_tokens = set(_tokens(context_text))
    context_token_recall = (
        round(len(reference_tokens & context_tokens) / len(reference_tokens), 4)
        if reference_tokens
        else None
    )
    text_scores = _text_scores(answer, reference_answer) if reference_answer else {
        "answer_token_f1": None,
        "answer_rouge_l": None,
    }

    return {
        "trace_id": str(trace.get("id")),
        "request_id": str(trace.get("request_id") or ""),
        "query_text": trace.get("query_text") or "",
        "created_at": trace.get("created_at"),
        "retrieval_strategy": stage.get("retrieval_strategy") or "unknown",
        "reranking_strategy": stage.get("reranking_strategy") or "unknown",
        "retrieved_chunk_count": len(chunks),
        "retrieved_document_ids": retrieved_document_ids,
        "expected_document_ids": relevant_ids,
        "reference_answer_provided": bool(reference_answer),
        "recall_at_k": round(recall_at_k, 4) if recall_at_k is not None else None,
        "precision_at_k": round(precision_at_k, 4) if precision_at_k is not None else None,
        "mrr_at_k": round(mrr_at_k, 4) if mrr_at_k is not None else None,
        "context_token_recall": context_token_recall,
        **text_scores,
        "latency_ms": latency.get("total_ms"),
        "k": k,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = (
        "recall_at_k",
        "precision_at_k",
        "mrr_at_k",
        "context_token_recall",
        "answer_token_f1",
        "answer_rouge_l",
        "latency_ms",
    )
    summary: dict[str, Any] = {"evaluated_queries": len(results)}
    for metric in metric_names:
        values = [row[metric] for row in results if isinstance(row.get(metric), (int, float))]
        summary[metric] = round(sum(values) / len(values), 4) if values else None
        summary[f"{metric}_coverage"] = len(values)
    summary["queries_with_reference_answers"] = sum(
        bool(row.get("reference_answer_provided")) for row in results
    )
    summary["queries_with_relevant_documents"] = sum(
        bool(row.get("expected_document_ids")) for row in results
    )
    return summary
