import time
import uuid

from fastapi import APIRouter, Request

from api.services.embedding_service import embed_texts
from api.services.graph_service import fuse_rankings_rrf, retrieve_graph_candidates
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
from api.services.reranking_service import rerank_chunks
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
    graph_context: list[dict] = []
    graph_stats: dict = {}

    # GraphRAG-only uses entity linking and graph traversal without a query
    # embedding. GraphRAG hybrid additionally runs the existing dense + BM25
    # retriever, then fuses that ranking with graph-derived passages.
    if strategy_id in {"standard", "hybrid", "hyde", "mmr", "graphrag_hybrid"}:
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

    t_retrieve = time.perf_counter()
    if strategy_id == "standard":
        candidates = match_chunks(query_embedding, candidate_count, user_id)
    elif strategy_id == "bm25":
        candidates = bm25_chunks(payload.query, user_id, candidate_count)
    elif strategy_id == "tfidf":
        candidates = tfidf_chunks(payload.query, user_id, candidate_count)
    elif strategy_id == "hybrid":
        candidates = hybrid_chunks(
            payload.query, query_embedding, user_id, candidate_count, candidate_count
        )
    elif strategy_id == "hyde":
        # A hypothetical passage helps find real, authorized chunks only.
        candidates = match_chunks(query_embedding, candidate_count, user_id)
    elif strategy_id == "mmr":
        candidates = mmr_chunks(
            query_embedding, user_id, candidate_count, candidate_count
        )
    elif strategy_id == "graphrag":
        candidates, graph_context, graph_stats = retrieve_graph_candidates(
            payload.query, user_id, candidate_count
        )
    elif strategy_id == "graphrag_hybrid":
        graph_candidates, graph_context, graph_stats = retrieve_graph_candidates(
            payload.query, user_id, candidate_count
        )
        vector_candidates = hybrid_chunks(
            payload.query, query_embedding, user_id, candidate_count, candidate_count
        )
        candidates = fuse_rankings_rrf(
            [graph_candidates, vector_candidates], candidate_count
        )
        graph_stats["vector_candidates"] = len(vector_candidates)
    else:
        raise BadRequestError(f"Retrieval strategy '{strategy_id}' has no implementation.")

    latency["retrieval_ms"] = int((time.perf_counter() - t_retrieve) * 1000)

    # Reranking sees only permission-checked candidates from the selected
    # retrieval path and runs before generation.
    if reranking_config["id"] == "none":
        matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    else:
        t_rerank = time.perf_counter()
        reranked = await rerank_chunks(
            payload.query, candidates, reranking_config["id"], payload.k
        )
        latency["reranking_ms"] = int((time.perf_counter() - t_rerank) * 1000)
        matches = diversify_chunks(reranked, payload.k, max_per_document=2)

    # Show graph edges only when the supporting source chunk is actually used
    # in the final answer context.
    matched_ids = {str(row.get("chunk_id")) for row in matches}
    graph_context = [
        row for row in graph_context if str(row.get("chunk_id")) in matched_ids
    ][:12]

    if not matches:
        latency["total_ms"] = int((time.perf_counter() - t0) * 1000)
        if strategy_id == "graphrag":
            answer = (
                "No matching graph relationships or visible source passages were found. "
                "A manager can republish documents with graph indexing enabled, then retry."
            )
        else:
            answer = "I don't have any documents visible to you that address this question."
        trace_data = {
            "chunking_strategy": "document_version_metadata",
            "retrieval_strategy": strategy_id,
            "reranking_strategy": reranking_config["id"],
            "retrieved_chunks": [],
            "graph_context": graph_context,
            "graph_stats": graph_stats,
            "note": "no matches found or visible to this user",
        }
        if hypothetical_document:
            trace_data["hyde_passage"] = hypothetical_document
        log_trace(request_id, user_id, payload.query, trace_data, latency)
        return {
            "requestId": request_id,
            "answer": answer,
            "sources": [],
            "sourceDocuments": [],
            "graphContext": graph_context,
            "graphStats": graph_stats,
            "latency": latency,
        }

    # Always generate from the original question and actual source chunks, not
    # from a HyDE passage or free-form graph extraction output.
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
    if strategy_id in {"graphrag", "graphrag_hybrid"}:
        trace_data["graph_context"] = graph_context
        trace_data["graph_stats"] = graph_stats
    log_trace(request_id, user_id, payload.query, trace_data, latency)

    return {
        "requestId": request_id,
        "answer": generation["answer"],
        "sources": matches,
        "sourceDocuments": unique_source_documents(matches),
        "graphContext": graph_context,
        "graphStats": graph_stats,
        "latency": latency,
    }
