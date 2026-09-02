import httpx

from config.settings import settings
from exception.exceptions import UpstreamServiceError
from prompt_lib.rag_prompts import SYSTEM_PROMPT, build_user_prompt


async def generate_answer(query: str, context_chunks: list[dict]) -> dict:
    user_prompt = build_user_prompt(query, context_chunks)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            },
        )

    if response.status_code != 200:
        raise UpstreamServiceError(f"Groq request failed ({response.status_code}): {response.text}")

    data = response.json()
    return {
        "answer": data["choices"][0]["message"]["content"],
        "usage": data.get("usage"),
        "model": settings.groq_model,
        "prompt_preview": user_prompt,
    }
