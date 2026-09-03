import re


def parse_structured_llm_response(raw: str) -> dict[str, str]:
    """Split a model response into a user-facing answer and trace-only reasoning.

    Expects the model to follow the ## Answer / ## Reasoning headers from
    rag_prompts.py. If it doesn't, the full text is treated as the answer so
    the query page still shows something useful.
    """
    text = (raw or "").strip()
    if not text:
        return {"answer": "", "reasoning": "", "raw": ""}

    answer_match = re.search(
        r"##\s*Answer\s*\n(.*?)(?=\n##\s*Reasoning\b|\Z)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    reasoning_match = re.search(
        r"##\s*Reasoning\s*\n(.*)\Z",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if answer_match:
        answer = answer_match.group(1).strip()
        reasoning = reasoning_match.group(1).strip() if reasoning_match else ""
        return {"answer": answer, "reasoning": reasoning, "raw": text}

    return {"answer": text, "reasoning": "", "raw": text}


def unique_source_documents(chunks: list[dict]) -> list[dict]:
    """Collapse retrieved chunks into one row per source document."""
    by_doc: dict[str, dict] = {}
    for chunk in chunks:
        doc_id = chunk.get("document_id")
        if not doc_id:
            continue
        similarity = float(chunk.get("similarity") or 0)
        existing = by_doc.get(doc_id)
        if not existing:
            by_doc[doc_id] = {
                "documentId": doc_id,
                "documentTitle": chunk.get("document_title") or "Untitled",
                "bestSimilarity": similarity,
                "chunkCount": 1,
            }
            continue
        existing["chunkCount"] += 1
        existing["bestSimilarity"] = max(existing["bestSimilarity"], similarity)

    return sorted(by_doc.values(), key=lambda doc: doc["bestSimilarity"], reverse=True)
