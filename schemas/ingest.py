from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    text: str
    department_ids: list[str] = Field(default_factory=list, alias="departmentIds")
    existing_document_id: str | None = Field(default=None, alias="existingDocumentId")
    chunking_strategy: str = Field(default="fixed_size_v1", alias="chunkingStrategy")
    embedding_strategy: str = Field(default="bge_small", alias="embeddingStrategy")


class IngestResponse(BaseModel):
    document_id: str
    version_id: str
    version_number: int
    chunks_created: int
    chunking_strategy: str = Field(alias="chunkingStrategy")
    embedding_strategy: str = Field(alias="embeddingStrategy")
    embedding_model: str = Field(alias="embeddingModel")
