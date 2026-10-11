import httpx

from config.settings import settings
from exception.exceptions import UpstreamServiceError
from prompt_lib.rag_prompts import SYSTEM_PROMPT, build_user_prompt
from utils.llm_response import parse_structured_llm_response


GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


async def generate_hypothetical_document(query: str) -> str:
    """Generate a hypothetical passage for HyDE retrieval, not a user-facing answer."""
    prompt = (
        "Write a concise hypothetical passage from a pharmaceutical knowledge document "
        "that would directly answer the question below. Include likely technical terms, "
        "synonyms, and relevant terminology. Do not add a preamble, disclaimers, or a "
        "claim that you searched a real document. The passage is only a retrieval aid; "
        "it is not evidence and must not be shown as the final answer.\n\n"
        f"Question: {query}\n\nHypothetical passage:"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={
                    "model": settings.groq_model,
                    "messages": [
                        {"role": "system", "content": "You create concise hypothetical retrieval passages."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
            )
    except httpx.RequestError as exc:
        raise UpstreamServiceError(
            "HyDE could not reach the language model service. Please try again."
        ) from exc

    if response.status_code != 200:
        raise UpstreamServiceError(
            f"HyDE language-model request failed ({response.status_code}): {response.text[:500]}"
        )
    try:
        passage = response.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise UpstreamServiceError("HyDE received an unexpected language-model response") from exc
    if not passage:
        raise UpstreamServiceError("HyDE received an empty hypothetical passage")
    return passage


async def generate_answer(query: str, context_chunks: list[dict]) -> dict:
    user_prompt = build_user_prompt(query, context_chunks)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
            },
        )

    if response.status_code != 200:
        raise UpstreamServiceError(f"Groq request failed ({response.status_code}): {response.text}")

    data = response.json()
    raw_output = data["choices"][0]["message"]["content"]
    parsed = parse_structured_llm_response(raw_output)

    return {
        "answer": parsed["answer"],
        "reasoning": parsed["reasoning"],
        "raw_output": parsed["raw"],
        "usage": data.get("usage"),
        "model": settings.groq_model,
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }
