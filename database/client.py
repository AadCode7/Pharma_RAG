from functools import lru_cache

from supabase import Client, create_client

from config.settings import settings


@lru_cache
def get_service_client() -> Client:
    """Bypasses RLS entirely. Backend-only — every call site using this
    client must apply its own explicit access check (see
    api/services/retrieval_service.match_chunks, which passes caller_id
    into the RPC, and api/services/rbac_service.require_manager)."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_user_client(access_token: str) -> Client:
    """Scoped to the caller's own JWT so Postgres RLS does the department
    filtering automatically. Prefer this over the service client whenever
    RLS alone is sufficient (e.g. listing documents, reading traces) —
    one less place for an access-control bug to hide."""
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
