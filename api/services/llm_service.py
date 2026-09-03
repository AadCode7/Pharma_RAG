import httpx

from config.settings import settings
from exception.exceptions import UpstreamServiceError
from prompt_lib.rag_prompts import SYSTEM_PROMPT, build_user_prompt
from utils.llm_response import parse_structured_llm_response


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
