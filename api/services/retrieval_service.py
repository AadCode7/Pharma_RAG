from config.settings import settings
from database.client import get_service_client
from exception.exceptions import UpstreamServiceError


def diversify_chunks(
    matches: list[dict],
    k: int,
    max_per_document: int = 2,
) -> list[dict]:
    """Pick up to k chunks while capping how many come from any one document.

    Without this, a large or semantically broad first document can fill every
    retrieval slot and block chunks from other documents from reaching the LLM.
    """
    if not matches or k <= 0:
        return []

    selected: list[dict] = []
    per_doc: dict[str, int] = {}

    for match in matches:
        doc_id = match["document_id"]
        if per_doc.get(doc_id, 0) >= max_per_document:
            continue
        selected.append(match)
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        if len(selected) >= k:
            return selected

    seen = {match["chunk_id"] for match in selected}
    for match in matches:
        if match["chunk_id"] in seen:
            continue
        selected.append(match)
        if len(selected) >= k:
            break

    return selected


def match_chunks(query_embedding: list[float], match_count: int, caller_id: str) -> list[dict]:
    """Calls the `match_chunks` Postgres RPC (see database/migrations/0001).
    Department access is filtered inside that SQL function itself, before
    ranking — not applied as a post-processing step here. caller_id is
    passed straight from the verified session in rbac_service."""
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
