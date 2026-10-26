import math
import re
import unicodedata

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
_SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?:[\"')\]]*)?(?:\s+|$)|\n+|$)", re.DOTALL)
_HEADING_RE = re.compile(
    r"(?m)^\s*(?:(?:#{1,6}\s+.+)|(?:\d+(?:\.\d+)*[.)]?\s+[^\n]{2,120})|(?:[A-Z][A-Z0-9 /&(),:'’\-]{3,100}))\s*$"
)



# Common compound modifiers that should retain their hyphen when OCR wraps
# the token at a line boundary (for example, "long-\nterm" -> "long-term").
_OCR_HYPHENATED_PREFIXES = {
    "adverse", "anti", "case", "cell", "clinical", "closed", "co", "cost",
    "cross", "data", "double", "dose", "early", "evidence", "first",
    "follow", "gene", "half", "high", "intra", "inter", "late", "life",
    "long", "low", "meta", "multi", "near", "non", "off", "on", "open",
    "out", "over", "patient", "phase", "placebo", "post", "pre", "pro",
    "protein", "real", "record", "risk", "safety", "self", "short",
    "side", "single", "site", "state", "systematic", "third", "time",
    "under", "user", "well", "world", "year",
}
_OCR_LINE_HYPHEN_RE = re.compile(r"(?m)\b([A-Za-z]{3,})[-‐‑][ \t]*\n[ \t]*([a-z]{3,})\b")
_OCR_LIST_RE = re.compile(r"^(?:[•●▪◦‣*-]\s+|\d{1,3}[.)]\s+|[A-Za-z][.)]\s+)")
_OCR_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+[A-Z][A-Za-z0-9 /&(),:'’\-]{2,90}$")
_OCR_SECTION_HEADING_RE = re.compile(r"^(?:CHAPTER|SECTION|APPENDIX|ANNEX)\s+\S+", re.IGNORECASE)


def _dehyphenate_ocr_line_wraps(text: str) -> str:
    """Join words split at a printed line end without breaking common compounds."""
    def join_match(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        if left.lower() in _OCR_HYPHENATED_PREFIXES:
            return f"{left}-{right}"
        return f"{left}{right}"

    return _OCR_LINE_HYPHEN_RE.sub(join_match, text)


def _is_ocr_heading(line: str) -> bool:
    if line.startswith("#") or _OCR_SECTION_HEADING_RE.match(line):
        return True
    if _OCR_NUMBERED_HEADING_RE.match(line) and not re.search(r"[.!?;:]$", line):
        return True
    if re.search(r"[.!?;:]$", line) or len(line) > 90:
        return False
    words = re.findall(r"[A-Za-z]+", line)
    if not words:
        return False
    if len(words) <= 12 and line.upper() == line and any(char.isalpha() for char in line):
        return True
    title_case_words = sum(word[0].isupper() for word in words)
    return len(words) >= 2 and len(words) <= 8 and title_case_words / len(words) >= 0.7


def _is_ocr_table_line(line: str) -> bool:
    return "\t" in line or "|" in line or len(re.findall(r" {2,}\S", line)) >= 2


def _normalize_ocr_layout(text: str) -> str:
    """Join wrapped prose lines while retaining headings, lists, tables and paragraphs."""
    text = _dehyphenate_ocr_line_wraps(text)
    output: list[str] = []
    prose_lines: list[str] = []

    def flush_prose() -> None:
        if prose_lines:
            joined = " ".join(re.sub(r"[ \t]+", " ", part.strip()) for part in prose_lines)
            joined = re.sub(r"[ \t]+([,.;:!?])", r"\1", joined)
            if joined:
                output.append(joined)
            prose_lines.clear()

    def blank_line() -> None:
        if output and output[-1] != "":
            output.append("")

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_prose()
            blank_line()
            continue

        line = re.sub(r"[ \t]+([,.;:!?])", r"\1", line)
        # Check table spacing before heading heuristics, which could otherwise
        # collapse aligned column labels such as "Parameter  Value  Range".
        if _is_ocr_table_line(line):
            flush_prose()
            output.append(line)
        elif _OCR_LIST_RE.match(line):
            flush_prose()
            output.append(line)
        elif _is_ocr_heading(line):
            flush_prose()
            blank_line()
            output.append(re.sub(r"[ \t]+", " ", line))
            blank_line()
        else:
            prose_lines.append(line)

    flush_prose()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()


def normalize_extracted_text(text: str, extraction_source: str = "text") -> str:
    """Normalize extraction artifacts before chunking, embedding and hashing.

    OCR layout cleanup is deliberately enabled only for image uploads. Text and
    Markdown keep their intentional line structure; PDF extraction keeps its
    page boundaries while still receiving safe Unicode/whitespace cleanup.
    """
    if not isinstance(text, str):
        return ""

    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", "")
    text = text.replace("\u00ad", "")  # soft hyphen
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    text = re.sub(r"[\u00a0\u2007\u202f]", " ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)[ \t]+$", "", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if extraction_source == "image":
        text = _normalize_ocr_layout(text)
    return text



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
        separators=["\n\n", "\n", " ", ""],
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
        similarity = cosine(vectors[index - 1], vectors[index])
        proposed_size = spans[index][1] - current[0][0]
        if similarity >= similarity_threshold and proposed_size <= chunk_size_chars:
            current.append(spans[index])
        else:
            groups.append(current)
            current = [spans[index]]
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
            boundary = text.rfind("\n\n", parent_start, parent_end)
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
