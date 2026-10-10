"""Retrieval algorithms for the Pharma RAG query pipeline.

All lexical corpus reads go through a service-role-only SQL RPC that applies
caller department permissions inside PostgreSQL. Dense retrieval continues to
use the existing access-controlled match_chunks RPC.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from config.settings import settings
from database.client import get_service_client
from exception.exceptions import UpstreamServiceError

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*", re.IGNORECASE)
_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60
_MMR_LAMBDA = 0.7


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def diversify_chunks(
    matches: list[dict],
    k: int,
    max_per_document: int = 2,
) -> list[dict]:
    """Pick up to k chunks while capping how many come from any one document."""
    if not matches or k <= 0:
        return []

    selected: list[dict] = []
    per_doc: dict[str, int] = {}

    for match in matches:
        doc_id = str(match["document_id"])
        if per_doc.get(doc_id, 0) >= max_per_document:
            continue
        selected.append(match)
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        if len(selected) >= k:
            return selected

    seen = {str(match["chunk_id"]) for match in selected}
    for match in matches:
        if str(match["chunk_id"]) in seen:
            continue
        selected.append(match)
        if len(selected) >= k:
            break

    return selected


def match_chunks(query_embedding: list[float], match_count: int, caller_id: str) -> list[dict]:
    """Use the existing dense-vector RPC; SQL enforces department access."""
    service = get_service_client()
    result = service.rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "match_count": match_count,
            "caller_id": caller_id,
            "embedding_model": settings.embedding_model,
        },
    ).execute()

    if result.data is None:
        raise UpstreamServiceError("Retrieval RPC returned no data")
    return result.data


def visible_chunks(caller_id: str) -> list[dict]:
    """Load only this user's active, authorized chunks for lexical ranking.

    This deliberately delegates access filtering to a restricted SQL function.
    Lexical algorithms need corpus-level document frequencies; for very large
    corpora this can later be moved into indexed PostgreSQL full-text search.
    """
    service = get_service_client()
    page_size = 500
    offset = 0
    rows: list[dict] = []
    while True:
        result = service.rpc(
            "visible_chunks_for_retrieval",
            {
                "p_caller_id": caller_id,
                "p_offset": offset,
                "p_limit": page_size,
            },
        ).execute()
        if result.data is None:
            raise UpstreamServiceError("Visible-chunk retrieval RPC returned no data")
        page = result.data
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _normalise_scores(matches: list[dict], raw_scores: dict[str, float]) -> list[dict]:
    maximum = max(raw_scores.values(), default=0.0)
    output = []
    for match in matches:
        item = dict(match)
        score = raw_scores.get(str(match["chunk_id"]), 0.0)
        item["similarity"] = float(score / maximum) if maximum > 0 else 0.0
        output.append(item)
    output.sort(key=lambda item: item["similarity"], reverse=True)
    return output


def bm25_chunks(query: str, caller_id: str, match_count: int) -> list[dict]:
    """Rank authorized chunks with Okapi BM25 (k1=1.5, b=0.75)."""
    query_terms = _tokens(query)
    if not query_terms or match_count <= 0:
        return []

    corpus = visible_chunks(caller_id)
    if not corpus:
        return []

    tokenized = [_tokens(row.get("content", "")) for row in corpus]
    doc_count = len(corpus)
    average_length = sum(map(len, tokenized)) / max(doc_count, 1)
    document_frequency: Counter[str] = Counter()
    for terms in tokenized:
        document_frequency.update(set(terms))

    query_frequency = Counter(query_terms)
    raw_scores: dict[str, float] = {}
    for row, terms in zip(corpus, tokenized):
        term_frequency = Counter(terms)
        length_norm = _BM25_K1 * (
            1.0 - _BM25_B + _BM25_B * len(terms) / max(average_length, 1e-9)
        )
        score = 0.0
        for term, qtf in query_frequency.items():
            tf = term_frequency.get(term, 0)
            if not tf:
                continue
            df = document_frequency.get(term, 0)
            idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            score += qtf * idf * (tf * (_BM25_K1 + 1.0)) / (tf + length_norm)
        raw_scores[str(row["chunk_id"])] = score

    ranked = _normalise_scores(corpus, raw_scores)
    return [row for row in ranked if row["similarity"] > 0][:match_count]


def _tfidf_vectors(documents: list[list[str]]) -> list[dict[str, float]]:
    """Build sparse, L2-normalized TF-IDF vectors without a new dependency."""
    count = len(documents)
    document_frequency: Counter[str] = Counter()
    for terms in documents:
        document_frequency.update(set(terms))
    idf = {
        term: math.log((1 + count) / (1 + frequency)) + 1.0
        for term, frequency in document_frequency.items()
    }
    vectors: list[dict[str, float]] = []
    for terms in documents:
        frequencies = Counter(terms)
        vector = {term: float(freq) * idf[term] for term, freq in frequencies.items()}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        vectors.append(
            {term: value / norm for term, value in vector.items()} if norm else {}
        )
    return vectors


def _sparse_cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def tfidf_chunks(query: str, caller_id: str, match_count: int) -> list[dict]:
    """Rank authorized chunks using cosine similarity over TF-IDF vectors."""
    query_terms = _tokens(query)
    if not query_terms or match_count <= 0:
        return []
    corpus = visible_chunks(caller_id)
    if not corpus:
        return []

    document_terms = [_tokens(row.get("content", "")) for row in corpus]
    vectors = _tfidf_vectors(document_terms)

    # Fit IDF on the document corpus only, then transform the query with the
    # same weights so query terms do not alter corpus document frequencies.
    document_frequency: Counter[str] = Counter()
    for terms in document_terms:
        document_frequency.update(set(terms))
    idf = {
        term: math.log((1 + len(corpus)) / (1 + frequency)) + 1.0
        for term, frequency in document_frequency.items()
    }
    query_frequency = Counter(query_terms)
    query_vector = {
        term: float(freq) * idf[term]
        for term, freq in query_frequency.items()
        if term in idf
    }
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    if query_norm:
        query_vector = {term: value / query_norm for term, value in query_vector.items()}
    else:
        return []

    scores = {
        str(row["chunk_id"]): _sparse_cosine(vector, query_vector)
        for row, vector in zip(corpus, vectors)
    }
    ranked = []
    for row in corpus:
        item = dict(row)
        item["similarity"] = max(0.0, min(1.0, scores.get(str(row["chunk_id"]), 0.0)))
        ranked.append(item)
    ranked.sort(key=lambda item: item["similarity"], reverse=True)
    return [row for row in ranked if row["similarity"] > 0][:match_count]


def hybrid_chunks(
    query: str,
    query_embedding: list[float],
    caller_id: str,
    match_count: int,
    candidate_count: int,
) -> list[dict]:
    """Fuse dense and BM25 rankings with Reciprocal Rank Fusion."""
    dense = match_chunks(query_embedding, candidate_count, caller_id)
    lexical = bm25_chunks(query, caller_id, candidate_count)
    fused: dict[str, dict] = {}
    raw_scores: dict[str, float] = {}

    for ranking in (dense, lexical):
        for rank, row in enumerate(ranking, start=1):
            chunk_id = str(row["chunk_id"])
            fused.setdefault(chunk_id, dict(row))
            raw_scores[chunk_id] = raw_scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)

    maximum = max(raw_scores.values(), default=0.0)
    for chunk_id, row in fused.items():
        row["similarity"] = raw_scores[chunk_id] / maximum if maximum else 0.0
    return sorted(fused.values(), key=lambda row: row["similarity"], reverse=True)[:match_count]


def mmr_chunks(
    query: str,
    query_embedding: list[float],
    caller_id: str,
    match_count: int,
    candidate_count: int,
) -> list[dict]:
    """Select dense candidates with MMR, using TF-IDF cosine for redundancy."""
    candidates = match_chunks(query_embedding, candidate_count, caller_id)
    if not candidates or match_count <= 0:
        return []

    content_terms = [_tokens(row.get("content", "")) for row in candidates]
    vectors = _tfidf_vectors(content_terms)
    dense_scores = [max(0.0, float(row.get("similarity", 0.0))) for row in candidates]
    low, high = min(dense_scores), max(dense_scores)
    relevance = [
        (score - low) / (high - low) if high > low else 1.0
        for score in dense_scores
    ]

    remaining = list(range(len(candidates)))
    selected: list[int] = []
    while remaining and len(selected) < match_count:
        best_index = remaining[0]
        best_score = float("-inf")
        for index in remaining:
            redundancy = max(
                (_sparse_cosine(vectors[index], vectors[chosen]) for chosen in selected),
                default=0.0,
            )
            mmr_score = _MMR_LAMBDA * relevance[index] - (1.0 - _MMR_LAMBDA) * redundancy
            if mmr_score > best_score:
                best_score = mmr_score
                best_index = index
        selected.append(best_index)
        remaining.remove(best_index)

    output = []
    for index in selected:
        row = dict(candidates[index])
        # Preserve the original dense similarity for source display; the
        # min-max normalized relevance is used only for MMR selection.
        row["similarity"] = dense_scores[index]
        output.append(row)
    return output
