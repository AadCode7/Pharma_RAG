from fastapi import APIRouter, Request

from api.services.rbac_service import require_user

router = APIRouter(tags=["traces"])


@router.get("/traces")
async def list_traces(request: Request, requestId: str | None = None):
    _user_id, user_client, _token = require_user(request)

    query = user_client.table("traces").select("*")
    query = query.eq("request_id", requestId) if requestId else query.order("created_at", desc=True).limit(10)

    result = query.execute()
    return {"traces": result.data}
