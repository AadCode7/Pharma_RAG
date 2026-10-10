from dataclasses import dataclass


@dataclass
class ChunkDraft:
    """A chunk before persistence, including optional parent context."""

    chunk_index: int
    content: str
    chunk_strategy: str
    char_start: int
    char_end: int
    parent_content: str | None = None
