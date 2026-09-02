from dataclasses import dataclass


@dataclass
class ChunkDraft:
    """A chunk before it's been persisted — output of a chunking strategy,
    input to the DB insert in ingestion_service. Kept separate from the
    `schemas` package because this is an internal domain shape, not an
    API request/response contract."""

    chunk_index: int
    content: str
    chunk_strategy: str
    char_start: int
    char_end: int
