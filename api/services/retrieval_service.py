from config.settings import settings
from database.client import get_service_client
from exception.exceptions import UpstreamServiceError


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
