import asyncio
from typing import Literal

import httpx

from config.settings import settings
from exception.exceptions import UpstreamServiceError

COHERE_EMBED_URL = "https://api.cohere.com/v2/embed"
MAX_ATTEMPTS = 3
MAX_TEXTS_PER_REQUEST = 96
InputType = Literal["search_document", "search_query"]


async def embed_texts(
    texts: list[str],
    model_name: str | None = None,
    input_type: InputType = "search_document",
) -> list[list[float]]:
    """Embed text with Cohere's v2 Embed API.

    Cohere's v3 embedding models use different input types for indexed
    documents and search queries. Keep those roles consistent throughout RAG.
    The API accepts at most 96 texts per request, so larger inputs are batched.
    """
    if not texts:
        return []

    selected_model = model_name or settings.embedding_model
    if input_type not in ("search_document", "search_query"):
        raise ValueError("input_type must be 'search_document' or 'search_query'")

    all_embeddings: list[list[float]] = []
    headers = {
        "Authorization": f"Bearer {settings.cohere_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for offset in range(0, len(texts), MAX_TEXTS_PER_REQUEST):
                batch = texts[offset : offset + MAX_TEXTS_PER_REQUEST]
                response = None

                for attempt in range(MAX_ATTEMPTS):
                    try:
                        response = await client.post(
                            COHERE_EMBED_URL,
                            headers=headers,
                            json={
                                "model": selected_model,
                                "texts": batch,
                                "input_type": input_type,
                                "embedding_types": ["float"],
                            },
                        )
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < MAX_ATTEMPTS - 1:
                                await asyncio.sleep(2**attempt)
                                continue
                        break
                    except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                        if attempt == MAX_ATTEMPTS - 1:
                            raise UpstreamServiceError(
                                "Cohere embedding service could not be reached. "
                                "Please try again shortly."
                            ) from exc
                        await asyncio.sleep(2**attempt)

                if response is None:
                    raise UpstreamServiceError("Cohere embedding request returned no response")

                if response.status_code != 200:
                    detail = response.text[:1000]
                    raise UpstreamServiceError(
                        f"Cohere embedding request failed ({response.status_code}): {detail}"
                    )

                payload = response.json()
                batch_embeddings = payload.get("embeddings", {}).get("float")
                if not isinstance(batch_embeddings, list) or len(batch_embeddings) != len(batch):
                    raise UpstreamServiceError(
                        "Unexpected Cohere embedding response shape or embedding count"
                    )

                for vector in batch_embeddings:
                    if not isinstance(vector, list) or len(vector) != settings.embedding_dim:
                        actual_dim = len(vector) if isinstance(vector, list) else "unknown"
                        raise UpstreamServiceError(
                            f"Cohere returned an unexpected embedding dimension: {actual_dim}; "
                            f"expected {settings.embedding_dim}"
                        )
                all_embeddings.extend(batch_embeddings)

    except httpx.RequestError as exc:
        raise UpstreamServiceError("Cohere embedding request failed due to a network error.") from exc

    return all_embeddings
