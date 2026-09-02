from pydantic import BaseModel


class IngestRequest(BaseModel):
    title: str
    text: str
    department_ids: list[str] = []
    existing_document_id: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    version_id: str
    version_number: int
    chunks_created: int
