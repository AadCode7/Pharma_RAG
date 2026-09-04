from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: str = Field(..., min_length=1)
    k: int = Field(default=5, ge=1, le=20)
    retrieval_strategy: str = Field(default="standard", alias="retrievalStrategy")
    reranking_strategy: str = Field(default="none", alias="rerankingStrategy")


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
    source_documents: list[dict] = Field(default_factory=list, alias="sourceDocuments")
    latency: dict

    model_config = {"populate_by_name": True}
