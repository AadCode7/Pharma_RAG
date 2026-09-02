from fastapi import APIRouter, Request

from api.services.rbac_service import require_user

router = APIRouter(tags=["departments"])


@router.get("/departments")
async def list_departments(request: Request):
    _user_id, user_client, _token = require_user(request)
    result = user_client.table("departments").select("id, name").order("name").execute()
    return {"departments": result.data}
