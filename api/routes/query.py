import time
import uuid

from fastapi import APIRouter, Request

from api.services.embedding_service import embed_texts
from api.services.llm_service import generate_answer, generate_hypothetical_document
from api.services.rbac_service import require_user
from api.services.retrieval_service import (
    bm25_chunks,
    diversify_chunks,
    hybrid_chunks,
    match_chunks,
    mmr_chunks,
    tfidf_chunks,
)
from api.services.tracing_service import log_trace
from config.settings import settings
from config.strategies import get_strategy
from exception.exceptions import BadRequestError
from schemas.query import QueryRequest
from utils.llm_response import unique_source_documents

router = APIRouter(tags=["query"])


@router.post("/query")
async def run_query(payload: QueryRequest, request: Request):
    request_id = str(uuid.uuid4())
    t0 = time.perf_counter()
    latency: dict = {}

    user_id, _user_client, _token = require_user(request)

    retrieval_config = get_strategy("retrieval", payload.retrieval_strategy)
    reranking_config = get_strategy("reranking", payload.reranking_strategy)
    if not retrieval_config:
        raise BadRequestError(f"Unknown retrieval strategy: {payload.retrieval_strategy}")
    if not reranking_config:
        raise BadRequestError(f"Unknown reranking strategy: {payload.reranking_strategy}")
    if not retrieval_config["implemented"]:
        raise BadRequestError(
            f"Retrieval strategy '{retrieval_config['label']}' is not implemented yet."
        )
    if not reranking_config["implemented"]:
        raise BadRequestError(
            f"Reranking strategy '{reranking_config['label']}' is not implemented yet."
        )

    candidate_count = min(max(payload.k * 4, payload.k), 40)
    strategy_id = retrieval_config["id"]
    query_embedding = None
    hypothetical_document = None

    # Lexical-only strategies do not make an unnecessary embedding API call.
    if strategy_id in {"standard", "hybrid", "hyde", "mmr"}:
        embedding_text = payload.query
        if strategy_id == "hyde":
            t_hyde = time.perf_counter()
            hypothetical_document = await generate_hypothetical_document(payload.query)
            latency["hyde_generation_ms"] = int((time.perf_counter() - t_hyde) * 1000)
            embedding_text = hypothetical_document
        t_embed = time.perf_counter()
        [query_embedding] = await embed_texts(
            [embedding_text],
            input_type="search_query",
        )
        latency["embedding_ms"] = int((time.perf_counter() - t_embed) * 1000)

    # Each retrieval implementation returns the same source-chunk shape used by
    # the existing answer generator and UI. Authorization is enforced in SQL.
    t_retrieve = time.perf_counter()
    if strategy_id == "standard":
        candidates = match_chunks(query_embedding, candidate_count, user_id)
        matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    elif strategy_id == "bm25":
        candidates = bm25_chunks(payload.query, user_id, candidate_count)
        matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    elif strategy_id == "tfidf":
        candidates = tfidf_chunks(payload.query, user_id, candidate_count)
        matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    elif strategy_id == "hybrid":
        candidates = hybrid_chunks(
            payload.query, query_embedding, user_id, candidate_count, candidate_count
        )
        matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    elif strategy_id == "hyde":
        # The hypothetical passage is used only to find real, authorized chunks.
        candidates = match_chunks(query_embedding, candidate_count, user_id)
        matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    elif strategy_id == "mmr":
        matches = mmr_chunks(
            query_embedding, user_id, payload.k, candidate_count
        )
    else:
        # Defensive guard if the registry and dispatcher ever drift apart.
        raise BadRequestError(f"Retrieval strategy '{strategy_id}' has no implementation.")

    latency["retrieval_ms"] = int((time.perf_counter() - t_retrieve) * 1000)

    if not matches:
        latency["total_ms"] = int((time.perf_counter() - t0) * 1000)
        trace_data = {
            "chunking_strategy": "document_version_metadata",
            "retrieval_strategy": strategy_id,
            "reranking_strategy": reranking_config["id"],
            "retrieved_chunks": [],
            "note": "no matches found or visible to this user",
        }
        if hypothetical_document:
            trace_data["hyde_passage"] = hypothetical_document
        log_trace(request_id, user_id, payload.query, trace_data, latency)
        return {
            "requestId": request_id,
            "answer": "I don't have any documents visible to you that address this question.",
            "sources": [],
            "sourceDocuments": [],
            "latency": latency,
        }

    # Always generate the user-facing answer from the original question and
    # retrieved source chunks, never from the HyDE hypothetical passage.
    t_gen = time.perf_counter()
    generation = await generate_answer(payload.query, matches)
    latency["generation_ms"] = int((time.perf_counter() - t_gen) * 1000)
    latency["total_ms"] = int((time.perf_counter() - t0) * 1000)

    trace_data = {
        "chunking_strategy": "document_version_metadata",
        "retrieval_strategy": strategy_id,
        "reranking_strategy": reranking_config["id"],
        "embedding_model": settings.embedding_model if query_embedding is not None else None,
        "retrieved_chunks": matches,
        "system_prompt": generation["system_prompt"],
        "generation_prompt": generation["user_prompt"],
        "generation_output": generation["raw_output"],
        "grounded_answer": generation["answer"],
        "generation_reasoning": generation["reasoning"],
        "llm_model": generation["model"],
        "token_usage": generation["usage"],
    }
    if hypothetical_document:
        trace_data["hyde_passage"] = hypothetical_document
    log_trace(request_id, user_id, payload.query, trace_data, latency)

    return {
        "requestId": request_id,
        "answer": generation["answer"],
        "sources": matches,
        "sourceDocuments": unique_source_documents(matches),
        "latency": latency,
    }
