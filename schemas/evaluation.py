from pydantic import BaseModel, Field


class TraceEvaluationInput(BaseModel):
    trace_id: str
    reference_answer: str | None = Field(default=None, max_length=12000)
    relevant_document_ids: list[str] = Field(default_factory=list, max_length=100)


class EvaluationRunRequest(BaseModel):
    items: list[TraceEvaluationInput] = Field(..., min_length=1, max_length=100)
    k: int = Field(default=5, ge=1, le=20)


class EvaluationRunResponse(BaseModel):
    run_id: str
    count: int
    summary: dict
    results: list[dict]
