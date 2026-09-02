# Prompt templates live here rather than inline in llm_service so V2 can add
# alternate prompts (e.g. for a groundedness-judge call) without touching
# the API-calling code.

SYSTEM_PROMPT = (
    "You are answering questions using ONLY the numbered context blocks provided "
    "below, which come from internal company documents. Cite the source of every "
    "claim using its number, e.g. [1]. If the context does not contain enough "
    "information to answer, say so plainly instead of guessing — do not use "
    "outside knowledge."
)


def build_context_block(chunks: list[dict]) -> str:
    parts = [f"[{i}] (source: {chunk['document_title']})\n{chunk['content']}" for i, chunk in enumerate(chunks, start=1)]
    return "\n\n".join(parts)


def build_user_prompt(query: str, chunks: list[dict]) -> str:
    context = build_context_block(chunks)
    return f"Context:\n{context}\n\nQuestion: {query}"
