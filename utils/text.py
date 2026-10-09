from api.models.chunk import ChunkDraft
from langchain_text_splitters import RecursiveCharacterTextSplitter


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

DEFAULT_RECURSIVE_CHUNK_SIZE_CHARS = 2048
DEFAULT_RECURSIVE_OVERLAP_CHARS = 200

def chunk_recursive_character(
        text:str,
        chunk_size_chars:int = DEFAULT_RECURSIVE_CHUNK_SIZE_CHARS,
        overlap_chars:int = DEFAULT_RECURSIVE_OVERLAP_CHARS,
        ) -> list[ChunkDraft]:

    if not text or not text.strip():
        return []

    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be greater than 0")

    if overlap_chars < 0 or overlap_chars >= chunk_size_chars:
        raise ValueError("overlap_chars must be non-negative and less than chunk_size_chars")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size = chunk_size_chars,
        chunk_overlap = overlap_chars,
        length_function = len,
        separators = ["\\n\\n", "\\n", " ", ""],
        keep_separator = True,
        strip_whitespace = True,
        add_start_index = True,
    )

    documents = splitter.create_documents([text])
    chunks: list[ChunkDraft] = []
    search_from = 0

    for index, document in enumerate(documents):
        content = document.page_content
        if not content:
            continue

        start = document.metadata.get("start_index")
        if not isinstance(start, int) or start < 0:
            start = text.find(content, max(0, search_from - overlap_chars))
        if start < 0:
            start = max(0, search_from)
            
        end = min(len(text), start + len(content))

        chunks.append(ChunkDraft(index, content, "recursive", start, end))
        search_from = end

    return chunks

