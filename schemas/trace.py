from pydantic import BaseModel, ConfigDict


class TraceOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    request_id: str
    query_text: str
    stage: dict
    latency_breakdown: dict
    created_at: str
