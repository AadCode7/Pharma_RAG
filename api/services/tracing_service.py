from database.client import get_service_client
from logger.logger import get_logger

logger = get_logger(__name__)

# Every query gets one row in `traces` capturing what happened at each
# stage — powers the Pipeline Trace section of the front-end. Built
# in-house (Postgres + this function) rather than a third-party tracing
# SaaS, so query content — which may include sensitive document text —
# never leaves our own infrastructure.


def log_trace(request_id: str, user_id: str, query_text: str, stage: dict, latency_breakdown: dict) -> None:
    service = get_service_client()
    try:
        service.table("traces").insert(
            {
                "request_id": request_id,
                "user_id": user_id,
                "query_text": query_text,
                "stage": stage,
                "latency_breakdown": latency_breakdown,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — tracing must never break the user-facing request
        logger.error(f"log_trace failed: {exc}")
