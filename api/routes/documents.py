from fastapi import APIRouter, Request

from api.services.ingestion_service import delete_document, repair_document_embeddings
from api.services.rbac_service import require_manager, require_user

router = APIRouter(tags=["documents"])

# Deliberately uses the caller's own JWT-scoped client (not the service
# client) so Postgres RLS does the department filtering for us — managers
# see every document, employees see only documents tagged to their
# department(s).


@router.get("/documents")
async def list_documents(request: Request):
    _user_id, user_client, _token = require_user(request)

    # documents <-> document_versions has two FKs (document_id and
    # current_version_id), so PostgREST can't infer which relationship to
    # embed — that ambiguity surfaces as a 500. Fetch in two queries instead.
    docs_result = (
        user_client.table("documents")
        .select("id, title, status, created_at, current_version_id")
        .order("created_at", desc=True)
        .execute()
    )
    documents = docs_result.data or []
    if not documents:
        return {"documents": []}

    doc_ids = [doc["id"] for doc in documents]
    versions_result = (
        user_client.table("document_versions")
        .select("id, document_id, version_number, created_at, superseded_at")
        .in_("document_id", doc_ids)
        .execute()
    )

    versions_by_doc: dict[str, list] = {}
    for version in versions_result.data or []:
        versions_by_doc.setdefault(version["document_id"], []).append(version)

    for doc in documents:
        doc["document_versions"] = sorted(
            versions_by_doc.get(doc["id"], []),
            key=lambda v: v["version_number"],
            reverse=True,
        )

    return {"documents": documents}


@router.delete("/documents/{document_id}")
async def remove_document(document_id: str, request: Request):
    user_id, _user_client, _token = require_user(request)
    require_manager(user_id)

    await delete_document(document_id)

    return {"deleted": True, "documentId": document_id}


@router.post("/documents/{document_id}/reembed")
async def reembed_document(document_id: str, request: Request):
    user_id, _user_client, _token = require_user(request)
    require_manager(user_id)

    result = await repair_document_embeddings(document_id)
    return {
        "documentId": document_id,
        "repaired": result["repaired"],
        "chunksTotal": result["chunksTotal"],
    }
