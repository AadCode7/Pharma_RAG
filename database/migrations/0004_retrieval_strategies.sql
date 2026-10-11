-- Retrieval strategy support.
-- Lexical strategies rank only chunks visible to the authenticated caller.
-- The service-role-only RPC keeps department filtering inside PostgreSQL rather
-- than fetching global chunks and filtering them in application code.

create or replace function public.visible_chunks_for_retrieval(
  p_caller_id uuid,
  p_offset integer,
  p_limit integer
)
returns table (
  chunk_id uuid,
  document_id uuid,
  document_title text,
  content text
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select
    c.id as chunk_id,
    d.id as document_id,
    d.title as document_title,
    c.content
  from public.chunks c
  join public.document_versions dv on dv.id = c.document_version_id
  join public.documents d on d.id = dv.document_id
  where c.is_active = true
    and d.status = 'active'
    and (
      public.is_manager(p_caller_id)
      or exists (
        select 1
        from public.document_departments dd
        join public.user_departments ud on ud.department_id = dd.department_id
        where dd.document_id = d.id
          and ud.user_id = p_caller_id
      )
    )
  order by c.id
  limit greatest(1, least(p_limit, 500))
  offset greatest(p_offset, 0);
$$;

-- This function accepts a caller ID, so only the trusted backend service role
-- may invoke it. Never expose it directly to browser/authenticated clients.
revoke all on function public.visible_chunks_for_retrieval(uuid, integer, integer) from public;
revoke all on function public.visible_chunks_for_retrieval(uuid, integer, integer) from anon;
revoke all on function public.visible_chunks_for_retrieval(uuid, integer, integer) from authenticated;
grant execute on function public.visible_chunks_for_retrieval(uuid, integer, integer) to service_role;
