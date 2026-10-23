-- GraphRAG storage and permission-filtered graph retrieval.
-- Every relationship is grounded in a source chunk. Reads filter by visibility
-- and current document version before graph results reach the LLM.
create table if not exists public.graph_entities (
  id uuid primary key default gen_random_uuid(),
  canonical_name text not null check (char_length(trim(canonical_name)) between 1 and 200),
  normalized_name text not null,
  entity_type text not null default 'concept',
  created_at timestamptz not null default now(),
  constraint graph_entities_normalized_type_unique unique (normalized_name, entity_type)
);
create table if not exists public.graph_relationships (
  id uuid primary key default gen_random_uuid(),
  subject_entity_id uuid not null references public.graph_entities(id) on delete cascade,
  predicate text not null check (char_length(trim(predicate)) between 1 and 100),
  object_entity_id uuid not null references public.graph_entities(id) on delete cascade,
  chunk_id uuid not null references public.chunks(id) on delete cascade,
  confidence double precision not null default 0.7 check (confidence >= 0 and confidence <= 1),
  created_at timestamptz not null default now(),
  constraint graph_relationships_chunk_triple_unique
    unique (chunk_id, subject_entity_id, predicate, object_entity_id),
  constraint graph_relationships_distinct_entities check (subject_entity_id <> object_entity_id)
);
create index if not exists graph_entities_normalized_name_idx on public.graph_entities (normalized_name);
create index if not exists graph_relationships_subject_idx on public.graph_relationships (subject_entity_id);
create index if not exists graph_relationships_object_idx on public.graph_relationships (object_entity_id);
create index if not exists graph_relationships_chunk_idx on public.graph_relationships (chunk_id);
alter table public.graph_entities enable row level security;
alter table public.graph_relationships enable row level security;
-- Browser clients cannot enumerate graph rows; server-side graph reads use the
-- RPC below and inserts require the backend service role.
grant select, insert, update, delete on public.graph_entities to service_role;
grant select, insert, update, delete on public.graph_relationships to service_role;

drop function if exists public.visible_graph_relationships(uuid, integer);
drop function if exists public.visible_graph_relationships(uuid, text, integer);

create function public.visible_graph_relationships(
  p_caller_id uuid,
  p_query text,
  p_limit integer default 2000
)
returns table (
  relationship_id uuid, subject_entity_id uuid, subject_name text, subject_type text,
  predicate text, object_entity_id uuid, object_name text, object_type text,
  chunk_id uuid, document_id uuid, document_title text, content text, confidence double precision
)
language sql stable security definer set search_path = public
as $$
  with visible_edges as materialized (
    select gr.id as relationship_id,
           se.id as subject_entity_id,
           se.canonical_name as subject_name,
           se.entity_type as subject_type,
           se.normalized_name as subject_norm,
           gr.predicate,
           oe.id as object_entity_id,
           oe.canonical_name as object_name,
           oe.entity_type as object_type,
           oe.normalized_name as object_norm,
           c.id as chunk_id,
           d.id as document_id,
           d.title as document_title,
           c.content,
           regexp_replace(lower(c.content), '[^a-z0-9]+', ' ', 'g') as content_norm,
           gr.confidence,
           gr.created_at
    from public.graph_relationships gr
    join public.graph_entities se on se.id = gr.subject_entity_id
    join public.graph_entities oe on oe.id = gr.object_entity_id
    join public.chunks c on c.id = gr.chunk_id and c.is_active = true
    join public.document_versions dv on dv.id = c.document_version_id
    join public.documents d on d.id = dv.document_id
      and d.status = 'active' and d.current_version_id = dv.id
    where p_caller_id is not null and (
      public.is_manager(p_caller_id) or exists (
        select 1 from public.document_departments dd
        join public.user_departments ud on ud.department_id = dd.department_id
        where dd.document_id = d.id and ud.user_id = p_caller_id
      )
    )
  ),
  normalized_query as (
    select trim(regexp_replace(lower(coalesce(p_query, '')), '[^a-z0-9]+', ' ', 'g')) as value
  ),
  query_terms as (
    select distinct term
    from normalized_query q
    cross join lateral unnest(string_to_array(q.value, ' ')) as terms(term)
    where length(term) >= 4
      and term not in ('what','when','where','which','that','this','with','from','does','have','will','would','could','should','tell','about','into','your','their','them','then','than')
  ),
  seed_entities as (
    select distinct v.subject_entity_id as entity_id
    from visible_edges v cross join normalized_query q
    where q.value <> '' and (
      (length(v.subject_norm) > 0 and position(' ' || v.subject_norm || ' ' in ' ' || q.value || ' ') > 0)
      or exists (
        select 1 from query_terms t
        where position(' ' || t.term || ' ' in ' ' || v.subject_norm || ' ') > 0
      )
    )
    union
    select distinct v.object_entity_id as entity_id
    from visible_edges v cross join normalized_query q
    where q.value <> '' and (
      (length(v.object_norm) > 0 and position(' ' || v.object_norm || ' ' in ' ' || q.value || ' ') > 0)
      or exists (
        select 1 from query_terms t
        where position(' ' || t.term || ' ' in ' ' || v.object_norm || ' ') > 0
      )
    )
  ),
  one_hop_nodes as (
    select v.subject_entity_id as entity_id from visible_edges v
      where v.subject_entity_id in (select entity_id from seed_entities)
         or v.object_entity_id in (select entity_id from seed_entities)
    union
    select v.object_entity_id as entity_id from visible_edges v
      where v.subject_entity_id in (select entity_id from seed_entities)
         or v.object_entity_id in (select entity_id from seed_entities)
  ),
  two_hop_nodes as (
    select v.subject_entity_id as entity_id from visible_edges v
      where v.subject_entity_id in (select entity_id from one_hop_nodes)
         or v.object_entity_id in (select entity_id from one_hop_nodes)
    union
    select v.object_entity_id as entity_id from visible_edges v
      where v.subject_entity_id in (select entity_id from one_hop_nodes)
         or v.object_entity_id in (select entity_id from one_hop_nodes)
  ),
  relevant_edges as (
    select v.* from visible_edges v
    where v.subject_entity_id in (select entity_id from two_hop_nodes)
       or v.object_entity_id in (select entity_id from two_hop_nodes)
  ),
  lexical_fallback as (
    select v.* from visible_edges v
    where not exists (select 1 from seed_entities)
      and exists (
        select 1 from query_terms t
        where position(' ' || t.term || ' ' in ' ' || v.subject_norm || ' ') > 0
           or position(' ' || t.term || ' ' in ' ' || v.object_norm || ' ') > 0
           or position(' ' || t.term || ' ' in ' ' || v.content_norm || ' ') > 0
      )
    order by v.created_at desc
    limit least(greatest(coalesce(p_limit, 2000), 1), 5000)
  )
  select v.relationship_id, v.subject_entity_id, v.subject_name, v.subject_type,
         v.predicate, v.object_entity_id, v.object_name, v.object_type,
         v.chunk_id, v.document_id, v.document_title, v.content, v.confidence
  from (
    select * from relevant_edges
    union all
    select * from lexical_fallback
    where not exists (select 1 from seed_entities)
  ) v
  order by v.created_at desc
  limit least(greatest(coalesce(p_limit, 2000), 1), 5000);
$$;

revoke all on function public.visible_graph_relationships(uuid, text, integer) from public;
revoke all on function public.visible_graph_relationships(uuid, text, integer) from anon;
revoke all on function public.visible_graph_relationships(uuid, text, integer) from authenticated;
grant execute on function public.visible_graph_relationships(uuid, text, integer) to service_role;
