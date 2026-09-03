# Prompt templates live here rather than inline in llm_service so V2 can add
# alternate prompts (e.g. for a groundedness-judge call) without touching
# the API-calling code.

SYSTEM_PROMPT = (
    "You are a pharmaceutical knowledge assistant. You may use ONLY the numbered "
    "context blocks provided in the user message — never outside knowledge, "
    "assumptions, or guesses.\n\n"
    "Respond using exactly these two markdown sections and nothing else:\n\n"
    "## Answer\n"
    "Write the direct answer here. Keep it concise and factual. Cite every claim "
    "with the context block number in square brackets, e.g. [1]. If the context "
    "does not contain enough information, write one sentence saying so — do not "
    "speculate or fill gaps.\n\n"
    "## Reasoning\n"
    "Explain step by step which context blocks you relied on, how they support "
    "the answer, and note any gaps, conflicts, or low-confidence areas. This "
    "section is for internal pipeline review only."
)


def build_context_block(chunks: list[dict]) -> str:
    parts = [f"[{i}] (source: {chunk['document_title']})\n{chunk['content']}" for i, chunk in enumerate(chunks, start=1)]
    return "\n\n".join(parts)


def build_user_prompt(query: str, chunks: list[dict]) -> str:
    context = build_context_block(chunks)
    return (
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        "Provide your ## Answer and ## Reasoning sections now."
    )
