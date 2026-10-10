-- Parent/child chunking stores the child text for embedding and the larger
-- parent passage for answer generation. Existing rows remain valid: NULL parent
-- content means retrieval continues to return the original chunk content.
alter table public.chunks
  add column if not exists parent_content text;

create or replace function public.match_chunks(
  query_embedding vector(384),
  match_count int,
  caller_id uuid,
  embedding_model text default 'embed-english-light-v3.0'
)
returns table (
  chunk_id uuid,
  document_id uuid,
  document_title text,
  content text,
  similarity float
)
language sql stable security definer
as $$
  select
    c.id as chunk_id,
    d.id as document_id,
    d.title as document_title,
    coalesce(c.parent_content, c.content) as content,
    1 - (ce.embedding <=> query_embedding) as similarity
  from public.chunk_embeddings ce
  join public.chunks c on c.id = ce.chunk_id and c.is_active = true
  join public.document_versions dv on dv.id = c.document_version_id
  join public.documents d on d.id = dv.document_id and d.status = 'active'
  where ce.model_name = embedding_model
    and (
      public.is_manager(caller_id) or
      exists (
        select 1 from public.document_departments dd
        join public.user_departments ud on ud.department_id = dd.department_id
        where dd.document_id = d.id and ud.user_id = caller_id
      )
    )
  order by ce.embedding <=> query_embedding
  limit match_count;
$$;

comment on column public.chunks.parent_content is
  'Optional larger context passage used by parent-child chunking; NULL for other strategies.';
