import asyncio

import httpx

from config.settings import settings
from exception.exceptions import UpstreamServiceError

# KNOWN RISK (see progress.md): HF's free serverless inference routing has
# changed more than once, and not every model is guaranteed to be served on
# the free feature-extraction endpoint at any given time. Verify this works
# for your chosen model before relying on it — see the curl check in
# README.md. Documented fallback: run the model in-process with
# sentence-transformers (still free, no API dependency, larger deploy size).

MAX_ATTEMPTS = 3


async def embed_texts(texts: list[str], model_name: str | None = None) -> list[list[float]]:
    selected_model = model_name or settings.embedding_model
    api_url = f"https://router.huggingface.co/hf-inference/models/{selected_model}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = await client.post(
                        api_url,
                        headers={"Authorization": f"Bearer {settings.hf_api_token}"},
                        json={"inputs": texts, "options": {"wait_for_model": True}},
                    )
                    break
                except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                    if attempt == MAX_ATTEMPTS - 1:
                        raise UpstreamServiceError(
                            "Hugging Face embedding service could not be reached. "
                            "Please try publishing again."
                        ) from exc
                    await asyncio.sleep(2**attempt)
    except httpx.RequestError as exc:
        raise UpstreamServiceError("Hugging Face embedding request failed.") from exc

    if response.status_code != 200:
        raise UpstreamServiceError(f"HF embedding request failed ({response.status_code}): {response.text}")

    return normalize_embedding_output(response.json())


def normalize_embedding_output(raw: list) -> list[list[float]]:
    """The feature-extraction pipeline's output shape depends on the
    model/pooling config: some models return one already-pooled [hidden]
    vector per input, others return [seq_len][hidden] per input and need
    mean pooling ourselves. This normalizes either case to a flat [hidden]
    vector per input."""
    if not raw:
        raise UpstreamServiceError("Unexpected embedding response shape (empty)")

    is_token_level = isinstance(raw[0][0], list)
    if not is_token_level:
        return raw

    pooled_all: list[list[float]] = []
    for token_vectors in raw:
        hidden = len(token_vectors[0])
        pooled = [0.0] * hidden
        for vector in token_vectors:
            for i, value in enumerate(vector):
                pooled[i] += value
        pooled_all.append([v / len(token_vectors) for v in pooled])
    return pooled_all
