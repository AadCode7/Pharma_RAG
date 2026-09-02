from api.models.chunk import ChunkDraft

# V1 baseline chunker: fixed-size with overlap. Deliberately simple — this
# is the control group every V2 chunking strategy gets compared against.
# Tagged 'fixed_size_v1' so eval results can be grouped by strategy later.

DEFAULT_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 50
CHARS_PER_TOKEN = 4  # rough heuristic, good enough for fixed-size chunking


def chunk_fixed_size(
    text: str,
    chunk_size_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[ChunkDraft]:
    chunk_size_chars = chunk_size_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    chunks: list[ChunkDraft] = []
    start = 0
    index = 0

    while start < len(text):
        end = min(start + chunk_size_chars, len(text))

        # don't split mid-word: extend to the next whitespace if it's close by
        if end < len(text):
            next_space = text.find(" ", end)
            if next_space != -1 and next_space - end < 100:
                end = next_space

        content = text[start:end].strip()
        if content:
            chunks.append(ChunkDraft(index, content, "fixed_size_v1", start, end))
            index += 1

        if end >= len(text):
            break
        start = max(0, end - overlap_chars)

    return chunks
