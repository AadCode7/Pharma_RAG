-- Pharma RAG V1 — initial schema
-- Run this in the Supabase SQL editor, or via `supabase db push`.

create extension if not exists vector;
create extension if not exists pgcrypto;

-- ============================================================
-- RBAC / auth
-- ============================================================

create table departments (
  id uuid primary key default gen_random_uuid(),
  name text not null unique
);

create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('manager','employee')) default 'employee',
  full_name text,
  created_at timestamptz not null default now()
);

create table user_departments (
  user_id uuid not null references profiles(id) on delete cascade,
  department_id uuid not null references departments(id) on delete cascade,
  primary key (user_id, department_id)
);

-- auto-create a profile row whenever someone signs up via Supabase Auth.
-- everyone starts as 'employee'; an existing manager promotes them afterward.
create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id, role, full_name)
  values (new.id, 'employee', new.raw_user_meta_data->>'full_name');
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

create or replace function is_manager(uid uuid) returns boolean
language sql stable as $$
  select exists(select 1 from profiles where id = uid and role = 'manager');
$$;

-- ============================================================
-- Documents & versioning
-- ============================================================

create table documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  source_type text not null check (source_type in ('upload','s3')) default 'upload',
  source_uri text,
  current_version_id uuid,
  status text not null check (status in ('active','archived')) default 'active',
  created_at timestamptz not null default now(),
  created_by uuid references profiles(id)
);

create table document_versions (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  version_number int not null,
  content_hash text not null,
  storage_path text not null,
  created_at timestamptz not null default now(),
  superseded_at timestamptz
);

alter table documents
  add constraint fk_current_version foreign key (current_version_id) references document_versions(id);

create table document_departments (
  document_id uuid not null references documents(id) on delete cascade,
  department_id uuid not null references departments(id) on delete cascade,
  primary key (document_id, department_id)
);

-- ============================================================
-- Chunking & embeddings
-- ============================================================

create table chunks (
  id uuid primary key default gen_random_uuid(),
  document_version_id uuid not null references document_versions(id) on delete cascade,
  chunk_index int not null,
  content text not null,
  chunk_strategy text not null default 'fixed_size_v1',
  char_start int,
  char_end int,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index chunks_active_idx on chunks (document_version_id) where is_active = true;

-- dimension 384 matches BAAI/bge-small-en-v1.5. Change if you swap embedding models.
create table chunk_embeddings (
  id uuid primary key default gen_random_uuid(),
  chunk_id uuid not null references chunks(id) on delete cascade,
  model_name text not null,
  embedding vector(384),
  created_at timestamptz not null default now(),
  unique (chunk_id, model_name)
);

create index chunk_embeddings_vector_idx on chunk_embeddings
  using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ============================================================
-- Evaluation (populated once a golden set exists)
-- ============================================================

create table eval_queries (
  id uuid primary key default gen_random_uuid(),
  query_text text not null,
  expected_chunk_ids uuid[] default '{}',
  expected_document_ids uuid[] default '{}',
  category text,
  created_at timestamptz not null default now()
);

create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  config jsonb not null,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create table eval_results (
  id uuid primary key default gen_random_uuid(),
  eval_run_id uuid not null references eval_runs(id) on delete cascade,
  query_id uuid not null references eval_queries(id) on delete cascade,
  retrieved_chunk_ids uuid[],
  recall_at_k numeric,
  precision_at_k numeric,
  mrr numeric,
  groundedness_score numeric,
  latency_ms int,
  k int,
  created_at timestamptz not null default now()
);

-- ============================================================
-- Tracing & sync
-- ============================================================

create table traces (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null default gen_random_uuid(),
  user_id uuid references profiles(id),
  query_text text,
  stage jsonb,
  latency_breakdown jsonb,
  created_at timestamptz not null default now()
);

create table sync_jobs (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in ('manual','s3')),
  status text not null default 'pending',
  documents_added int default 0,
  documents_updated int default 0,
  documents_marked_stale int default 0,
  error_log text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

-- ============================================================
-- Row Level Security
-- ============================================================

alter table profiles enable row level security;
alter table departments enable row level security;
alter table user_departments enable row level security;
alter table documents enable row level security;
alter table document_versions enable row level security;
alter table document_departments enable row level security;
alter table chunks enable row level security;
alter table chunk_embeddings enable row level security;
alter table eval_queries enable row level security;
alter table eval_runs enable row level security;
alter table eval_results enable row level security;
alter table traces enable row level security;
alter table sync_jobs enable row level security;

create policy "read own profile" on profiles for select using (auth.uid() = id or is_manager(auth.uid()));
create policy "managers update profiles" on profiles for update using (is_manager(auth.uid()));

create policy "read departments" on departments for select using (auth.role() = 'authenticated');

create policy "read own departments" on user_departments for select using (user_id = auth.uid() or is_manager(auth.uid()));
create policy "managers manage user_departments" on user_departments for all using (is_manager(auth.uid()));

-- documents: employees see active docs tagged to their department(s); managers see/manage everything
create policy "read visible documents" on documents for select using (
  status = 'active' and (
    is_manager(auth.uid()) or
    exists (
      select 1 from document_departments dd
      join user_departments ud on ud.department_id = dd.department_id
      where dd.document_id = documents.id and ud.user_id = auth.uid()
    )
  )
);
create policy "managers insert documents" on documents for insert with check (is_manager(auth.uid()));
create policy "managers update documents" on documents for update using (is_manager(auth.uid()));

create policy "read versions of visible docs" on document_versions for select using (
  is_manager(auth.uid()) or
  exists (
    select 1 from document_departments dd
    join user_departments ud on ud.department_id = dd.department_id
    where dd.document_id = document_versions.document_id and ud.user_id = auth.uid()
  )
);
create policy "managers manage versions" on document_versions for insert with check (is_manager(auth.uid()));

create policy "read doc departments" on document_departments for select using (true);
create policy "managers manage doc departments" on document_departments for all using (is_manager(auth.uid()));

-- chunks: only active chunks of visible docs (this is the stale-data-safety enforcement point)
create policy "read active chunks of visible docs" on chunks for select using (
  is_active = true and exists (
    select 1 from document_versions dv
    join documents d on d.id = dv.document_id
    where dv.id = chunks.document_version_id
    and (
      is_manager(auth.uid()) or
      exists (
        select 1 from document_departments dd
        join user_departments ud on ud.department_id = dd.department_id
        where dd.document_id = d.id and ud.user_id = auth.uid()
      )
    )
  )
);
create policy "managers manage chunks" on chunks for all using (is_manager(auth.uid()));

create policy "read embeddings of visible chunks" on chunk_embeddings for select using (
  exists (select 1 from chunks c where c.id = chunk_embeddings.chunk_id and c.is_active = true)
);
create policy "managers manage embeddings" on chunk_embeddings for all using (is_manager(auth.uid()));

-- internal tooling tables: manager-only, except traces which a user can read their own
create policy "managers only eval_queries" on eval_queries for all using (is_manager(auth.uid()));
create policy "managers only eval_runs" on eval_runs for all using (is_manager(auth.uid()));
create policy "managers only eval_results" on eval_results for all using (is_manager(auth.uid()));
create policy "read own or all traces" on traces for select using (user_id = auth.uid() or is_manager(auth.uid()));
create policy "insert traces" on traces for insert with check (true);
create policy "managers only sync_jobs" on sync_jobs for all using (is_manager(auth.uid()));

-- ============================================================
-- Retrieval RPC — department filtering happens BEFORE ranking/limit,
-- not as a post-processing step. This is the core governance guarantee.
-- SECURITY DEFINER so it can be called from the service-role backend
-- while still enforcing per-user department visibility via caller_id.
-- ============================================================

create or replace function match_chunks(
  query_embedding vector(384),
  match_count int,
  caller_id uuid,
  embedding_model text default 'BAAI/bge-small-en-v1.5'
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
    c.content,
    1 - (ce.embedding <=> query_embedding) as similarity
  from chunk_embeddings ce
  join chunks c on c.id = ce.chunk_id and c.is_active = true
  join document_versions dv on dv.id = c.document_version_id
  join documents d on d.id = dv.document_id and d.status = 'active'
  where ce.model_name = embedding_model
    and (
      is_manager(caller_id) or
      exists (
        select 1 from document_departments dd
        join user_departments ud on ud.department_id = dd.department_id
        where dd.document_id = d.id and ud.user_id = caller_id
      )
    )
  order by ce.embedding <=> query_embedding
  limit match_count;
$$;

-- ============================================================
-- Storage bucket for raw document files
-- ============================================================
insert into storage.buckets (id, name, public)
values ('documents', 'documents', false)
on conflict (id) do nothing;
