from fastapi import Request
from supabase import Client

from database.client import get_service_client, get_user_client
from exception.exceptions import ForbiddenError, UnauthorizedError


def _get_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise UnauthorizedError("Missing auth token")
    return auth_header.removeprefix("Bearer ")


def require_user(request: Request) -> tuple[str, Client, str]:
    """Verifies the caller's Supabase session and returns
    (user_id, user_scoped_client, raw_token). The user-scoped client should
    be preferred downstream wherever RLS alone can do the access control."""
    token = _get_bearer_token(request)
    user_client = get_user_client(token)

    try:
        response = user_client.auth.get_user(token)
    except Exception as exc:  # noqa: BLE001 — any auth SDK failure means "not authenticated"
        raise UnauthorizedError("Invalid session") from exc

    if not response or not response.user:
        raise UnauthorizedError("Invalid session")

    return response.user.id, user_client, token


def require_manager(user_id: str) -> None:
    """Raises unless the caller's profile role is 'manager'. Uses the
    service client deliberately — this check has to succeed even though
    the manager-only tables aren't readable via the user's own RLS grant
    for insert/update actions."""
    service = get_service_client()
    result = service.table("profiles").select("role").eq("id", user_id).single().execute()
    role = (result.data or {}).get("role")
    if role != "manager":
        raise ForbiddenError("Only managers can upload or modify documents")
