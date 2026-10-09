import time
import uuid

from fastapi import APIRouter, Request

from api.services.embedding_service import embed_texts
from api.services.llm_service import generate_answer
from api.services.rbac_service import require_user
from api.services.retrieval_service import diversify_chunks, match_chunks
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

    # Configuration is deliberately wired before implementation. At this
    # milestone only standard dense retrieval + no reranking execute. Future
    # strategies get their own implementation without changing QueryRequest.
    if not retrieval_config["implemented"]:
        raise BadRequestError(
            f"Retrieval strategy '{retrieval_config['label']}' is not implemented yet. "
            "The selector is ready for its implementation in the next milestone."
        )
    if not reranking_config["implemented"]:
        raise BadRequestError(
            f"Reranking strategy '{reranking_config['label']}' is not implemented yet. "
            "The selector is ready for its implementation in the next milestone."
        )

    # 1. Embed the query
    t_embed = time.perf_counter()
    [query_embedding] = await embed_texts(
        [payload.query],
        input_type="search_query",
    )
    latency["embedding_ms"] = int((time.perf_counter() - t_embed) * 1000)

    # 2. Retrieve — department filtering happens inside match_chunks itself,
    # before ranking. See database/migrations/0001 for the RPC. Fetch extra
    # candidates, then diversify so one large document can't monopolize every
    # slot and hide other documents from the LLM context.
    t_retrieve = time.perf_counter()
    candidate_count = min(max(payload.k * 4, payload.k), 40)
    candidates = match_chunks(query_embedding, candidate_count, user_id)
    matches = diversify_chunks(candidates, payload.k, max_per_document=2)
    latency["retrieval_ms"] = int((time.perf_counter() - t_retrieve) * 1000)

    if not matches:
        latency["total_ms"] = int((time.perf_counter() - t0) * 1000)
        log_trace(
            request_id,
            user_id,
            payload.query,
            {
                "chunking_strategy": "fixed_size_v1",
                "retrieval_strategy": retrieval_config["id"],
                "reranking_strategy": reranking_config["id"],
                "retrieved_chunks": [],
                "note": "no matches found or visible to this user",
            },
            latency,
        )
        return {
            "requestId": request_id,
            "answer": "I don't have any documents visible to you that address this question.",
            "sources": [],
            "latency": latency,
        }

    # 3. Generate
    t_gen = time.perf_counter()
    generation = await generate_answer(payload.query, matches)
    latency["generation_ms"] = int((time.perf_counter() - t_gen) * 1000)
    latency["total_ms"] = int((time.perf_counter() - t0) * 1000)

    # 4. Trace — full pipeline record for the front-end's Pipeline Trace panel
    log_trace(
        request_id,
        user_id,
        payload.query,
        {
            "chunking_strategy": "fixed_size_v1",
            "retrieval_strategy": retrieval_config["id"],
            "reranking_strategy": reranking_config["id"],
            "embedding_model": settings.embedding_model,
            "retrieved_chunks": matches,
            "system_prompt": generation["system_prompt"],
            "generation_prompt": generation["user_prompt"],
            "generation_output": generation["raw_output"],
            "grounded_answer": generation["answer"],
            "generation_reasoning": generation["reasoning"],
            "llm_model": generation["model"],
            "token_usage": generation["usage"],
        },
        latency,
    )

    return {
        "requestId": request_id,
        "answer": generation["answer"],
        "sources": matches,
        "sourceDocuments": unique_source_documents(matches),
        "latency": latency,
    }
