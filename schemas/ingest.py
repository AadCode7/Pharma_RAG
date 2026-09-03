from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    # Accepts the camelCase keys the frontend actually sends
    # (departmentIds, existingDocumentId) via alias, while the rest of the
    # backend still works with normal snake_case attribute names.
    model_config = ConfigDict(populate_by_name=True)

    title: str
    text: str
    department_ids: list[str] = Field(default_factory=list, alias="departmentIds")
    existing_document_id: str | None = Field(default=None, alias="existingDocumentId")


class IngestResponse(BaseModel):
    document_id: str
    version_id: str
    version_number: int
    chunks_created: int
