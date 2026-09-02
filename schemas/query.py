from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    k: int = Field(default=5, ge=1, le=20)


class SourceChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    similarity: float


class QueryResponse(BaseModel):
    request_id: str
    answer: str
    sources: list[SourceChunk]
    latency: dict
