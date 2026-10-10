import math
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from api.models.chunk import ChunkDraft

# V1 baseline is deliberately retained as the default/control group.
DEFAULT_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 50
CHARS_PER_TOKEN = 4
DEFAULT_RECURSIVE_CHUNK_SIZE_CHARS = 2048
DEFAULT_RECURSIVE_OVERLAP_CHARS = 200
DEFAULT_SENTENCE_CHUNK_SIZE_CHARS = 1800
DEFAULT_PARENT_SIZE_CHARS = 1400
DEFAULT_CHILD_SIZE_CHARS = 450
DEFAULT_CHILD_OVERLAP_CHARS = 60

# Split on common sentence terminators while retaining punctuation and source offsets.
_SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?:[\"')\]]*)?(?:\\s+|$)|\\n+|$)", re.DOTALL)
_HEADING_RE = re.compile(
    r"(?m)^\\s*(?:(?:#{1,6}\\s+.+)|(?:\\d+(?:\\.\\d+)*[.)]?\\s+[^\\n]{2,120})|(?:[A-Z][A-Z0-9 /&(),:'’\\-]{3,100}))\\s*$"
)


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    for match in _SENTENCE_RE.finditer(text):
        start, end = match.span()
        raw = match.group()
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        start += left
        end = match.start() + right
        value = text[start:end]
        if value.strip():
            spans.append((start, end, value.strip()))
    return spans


def _group_spans(
    text: str,
    spans: list[tuple[int, int, str]],
    strategy: str,
    max_chars: int,
    overlap_items: int = 0,
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    i = 0
    while i < len(spans):
        j = i
        while j < len(spans):
            proposed_end = spans[j][1]
            if j > i and proposed_end - spans[i][0] > max_chars:
                break
            j += 1
            if spans[j - 1][1] - spans[i][0] >= max_chars:
                break
        group = spans[i:j]
        if not group:
            i += 1
            continue
        start, end = group[0][0], group[-1][1]
        content = text[start:end].strip()
        if content:
            chunks.append(ChunkDraft(len(chunks), content, strategy, start, end))
        if j >= len(spans):
            break
        i = max(i + 1, j - overlap_items)
    return chunks


def chunk_fixed_size(
    text: str,
    chunk_size_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[ChunkDraft]:
    chunk_size_chars = chunk_size_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    chunks: list[ChunkDraft] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size_chars, len(text))
        if end < len(text):
            next_space = text.find(" ", end)
            if next_space != -1 and next_space - end < 100:
                end = next_space
        content = text[start:end].strip()
        if content:
            chunks.append(ChunkDraft(len(chunks), content, "fixed_size_v1", start, end))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def chunk_recursive_character(
    text: str,
    chunk_size_chars: int = DEFAULT_RECURSIVE_CHUNK_SIZE_CHARS,
    overlap_chars: int = DEFAULT_RECURSIVE_OVERLAP_CHARS,
) -> list[ChunkDraft]:
    """Split at paragraph, line, word, then character boundaries."""
    if not text or not text.strip():
        return []
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be greater than zero")
    if overlap_chars < 0 or overlap_chars >= chunk_size_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than chunk_size_chars")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size_chars,
        chunk_overlap=overlap_chars,
        length_function=len,
        separators=["\\n\\n", "\\n", " ", ""],
        keep_separator=True,
        strip_whitespace=True,
        add_start_index=True,
    )
    documents = splitter.create_documents([text])
    chunks: list[ChunkDraft] = []
    search_from = 0
    for document in documents:
        content = document.page_content
        if not content:
            continue
        start = document.metadata.get("start_index")
        if not isinstance(start, int) or start < 0:
            start = text.find(content, max(0, search_from - overlap_chars))
        if start < 0:
            start = max(0, search_from)
        end = min(len(text), start + len(content))
        chunks.append(ChunkDraft(len(chunks), content, "recursive", start, end))
        search_from = end
    return chunks


def chunk_sentence_based(
    text: str,
    chunk_size_chars: int = DEFAULT_SENTENCE_CHUNK_SIZE_CHARS,
    overlap_sentences: int = 1,
) -> list[ChunkDraft]:
    """Group complete sentences into bounded chunks, overlapping one sentence by default."""
    if not text or not text.strip():
        return []
    if chunk_size_chars <= 0 or overlap_sentences < 0:
        raise ValueError("Chunk size must be positive and overlap non-negative")
    return _group_spans(text, _sentence_spans(text), "sentence", chunk_size_chars, overlap_sentences)


async def chunk_semantic(
    text: str,
    model_name: str,
    chunk_size_chars: int = DEFAULT_RECURSIVE_CHUNK_SIZE_CHARS,
    similarity_threshold: float = 0.68,
) -> list[ChunkDraft]:
    """Group adjacent sentences using cosine similarity of their Cohere embeddings."""
    if not text or not text.strip():
        return []
    spans = _sentence_spans(text)
    if len(spans) <= 1:
        return [ChunkDraft(0, spans[0][2], "semantic", spans[0][0], spans[0][1])] if spans else []

    # Local import avoids coupling the basic, synchronous chunkers to the API client.
    from api.services.embedding_service import embed_texts

    vectors = await embed_texts([span[2] for span in spans], model_name=model_name, input_type="search_document")

    def cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    groups: list[list[tuple[int, int, str]]] = []
    current = [spans[0]]
    for index in range(1, len(spans)):
        current_text_len = current[-1][1] - current[0][0]
        similarity = cosine(vectors[index - 1], vectors[index])
        if similarity >= similarity_threshold and spans[index][1] - current[0][0] <= chunk_size_chars:
            current.append(spans[index])
        else:
            groups.append(current)
            current = [spans[index]]
        # Hard upper bound prevents a long semantic run becoming one huge chunk.
        if current_text_len >= chunk_size_chars and len(current) > 1:
            groups.append(current[:-1])
            current = [current[-1]]
    if current:
        groups.append(current)

    result = []
    for group in groups:
        start, end = group[0][0], group[-1][1]
        result.append(ChunkDraft(len(result), text[start:end].strip(), "semantic", start, end))
    return result


def chunk_section_aware(text: str, chunk_size_chars: int = DEFAULT_RECURSIVE_CHUNK_SIZE_CHARS) -> list[ChunkDraft]:
    """Keep detected headings attached to their section and split oversized sections safely."""
    if not text or not text.strip():
        return []
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        # Documents without detectable headings still get safe natural-boundary chunks.
        return [
            ChunkDraft(c.chunk_index, c.content, "section_aware", c.char_start, c.char_end)
            for c in chunk_recursive_character(text, chunk_size_chars, DEFAULT_RECURSIVE_OVERLAP_CHARS)
        ]

    boundaries = [0] + [m.start() for m in matches[1:]] + [len(text)]
    sections = []
    for index, heading_match in enumerate(matches):
        start = heading_match.start()
        end = boundaries[index + 1]
        sections.append((start, end))
    # Preserve any preamble before the first heading as its own section.
    if matches[0].start() > 0 and text[:matches[0].start()].strip():
        sections.insert(0, (0, matches[0].start()))

    chunks: list[ChunkDraft] = []
    for section_start, section_end in sections:
        section_text = text[section_start:section_end]
        if len(section_text) <= chunk_size_chars:
            pieces = [(section_start, section_end, section_text.strip())]
        else:
            relative_chunks = chunk_recursive_character(section_text, chunk_size_chars, DEFAULT_RECURSIVE_OVERLAP_CHARS)
            pieces = [(section_start + c.char_start, section_start + c.char_end, c.content) for c in relative_chunks]
        for start, end, content in pieces:
            if content:
                chunks.append(ChunkDraft(len(chunks), content, "section_aware", start, end))
    return chunks


def chunk_parent_child(
    text: str,
    parent_size_chars: int = DEFAULT_PARENT_SIZE_CHARS,
    child_size_chars: int = DEFAULT_CHILD_SIZE_CHARS,
    child_overlap_chars: int = DEFAULT_CHILD_OVERLAP_CHARS,
) -> list[ChunkDraft]:
    """Embed small child chunks while retaining the larger parent passage as generation context."""
    if not text or not text.strip():
        return []
    if parent_size_chars <= 0 or child_size_chars <= 0 or child_overlap_chars < 0 or child_overlap_chars >= child_size_chars:
        raise ValueError("Invalid parent/child chunk sizes or overlap")

    chunks: list[ChunkDraft] = []
    parent_start = 0
    while parent_start < len(text):
        parent_end = min(parent_start + parent_size_chars, len(text))
        if parent_end < len(text):
            boundary = text.rfind("\\n\\n", parent_start, parent_end)
            if boundary > parent_start + parent_size_chars // 2:
                parent_end = boundary
        parent_content = text[parent_start:parent_end].strip()
        if parent_content:
            child_start = 0
            while child_start < len(parent_content):
                child_end = min(child_start + child_size_chars, len(parent_content))
                if child_end < len(parent_content):
                    space = parent_content.rfind(" ", child_start, child_end)
                    if space > child_start + child_size_chars // 2:
                        child_end = space
                child_content = parent_content[child_start:child_end].strip()
                if child_content:
                    absolute_start = parent_start + child_start
                    absolute_end = min(parent_end, absolute_start + len(child_content))
                    chunks.append(
                        ChunkDraft(
                            len(chunks), child_content, "parent_child",
                            absolute_start, absolute_end, parent_content,
                        )
                    )
                if child_end >= len(parent_content):
                    break
                child_start = max(child_start + 1, child_end - child_overlap_chars)
        if parent_end >= len(text):
            break
        parent_start = max(parent_start + 1, parent_end)
    return chunks
