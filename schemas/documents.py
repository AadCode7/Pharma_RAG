from pydantic import BaseModel, ConfigDict


class DocumentVersionOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    version_number: int
    created_at: str
    superseded_at: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    status: str
    created_at: str
    current_version_id: str | None = None
    document_versions: list[DocumentVersionOut] = []
