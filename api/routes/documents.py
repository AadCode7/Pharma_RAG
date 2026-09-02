from fastapi import APIRouter, Request

from api.services.rbac_service import require_user

router = APIRouter(tags=["documents"])

# Deliberately uses the caller's own JWT-scoped client (not the service
# client) so Postgres RLS does the department filtering for us — managers
# see every document, employees see only documents tagged to their
# department(s).


@router.get("/documents")
async def list_documents(request: Request):
    _user_id, user_client, _token = require_user(request)

    result = (
        user_client.table("documents")
        .select(
            "id, title, status, created_at, current_version_id, "
            "document_versions(id, version_number, created_at, superseded_at)"
        )
        .order("created_at", desc=True)
        .execute()
    )

    return {"documents": result.data}
