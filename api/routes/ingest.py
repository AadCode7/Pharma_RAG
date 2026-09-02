from fastapi import APIRouter, Request

from api.services.ingestion_service import ingest_document
from api.services.rbac_service import require_manager, require_user
from schemas.ingest import IngestRequest

router = APIRouter(tags=["ingest"])


@router.post("/ingest")
async def ingest(payload: IngestRequest, request: Request):
    user_id, _user_client, _token = require_user(request)
    require_manager(user_id)

    result = await ingest_document(
        title=payload.title,
        text=payload.text,
        department_ids=payload.department_ids,
        existing_document_id=payload.existing_document_id,
        user_id=user_id,
    )

    return {
        "documentId": result["document_id"],
        "versionId": result["version_id"],
        "versionNumber": result["version_number"],
        "chunksCreated": result["chunks_created"],
    }
