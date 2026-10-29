-- Free, deterministic evaluation over existing pipeline traces.
-- Apply this migration in the Supabase SQL editor before using /eval.

create table if not exists eval_trace_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  config jsonb not null default '{}'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists eval_trace_results (
  id uuid primary key default gen_random_uuid(),
  eval_run_id uuid not null references eval_trace_runs(id) on delete cascade,
  user_id uuid not null references profiles(id) on delete cascade,
  trace_id uuid references traces(id) on delete set null,
  query_text text not null,
  metrics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists eval_trace_runs_user_started_idx
  on eval_trace_runs (user_id, started_at desc);
create index if not exists eval_trace_results_run_idx
  on eval_trace_results (eval_run_id, created_at);

alter table eval_trace_runs enable row level security;
alter table eval_trace_results enable row level security;

drop policy if exists "users read own eval trace runs" on eval_trace_runs;
create policy "users read own eval trace runs" on eval_trace_runs
  for select using (user_id = auth.uid());

drop policy if exists "users read own eval trace results" on eval_trace_results;
create policy "users read own eval trace results" on eval_trace_results
  for select using (user_id = auth.uid());

-- Inserts are performed by the backend service role after it verifies the
-- authenticated user and selected trace visibility.
