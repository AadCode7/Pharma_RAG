# Pharma RAG — V1 (Python / FastAPI)

Baseline RAG system: fixed-size chunking, dense retrieval, Groq generation,
full pipeline tracing, department-scoped RBAC. See `architecture.md` for the
full design and `progress.md` for build status and known risks.

This is a rewrite of the original Node.js/Vercel-functions version into a
single FastAPI app — same schema, same governance model, same frontend
behavior, different backend language. See `progress.md` for what changed
in the process.

## Project structure

```
api/
  main.py            # FastAPI app: routers, static/template mounting, /config.js
  models/             # internal domain shapes (e.g. ChunkDraft)
  routes/              # one file per resource — query, ingest, documents, traces, departments
  services/             # business logic + external API calls (embeddings, LLM, retrieval, ingestion, tracing, RBAC)
  static/                # styles.css, app.js — served at /static
  templates/              # index.html — rendered via Jinja2
config/                    # pydantic-settings, reads .env
database/                    # Supabase client factory + SQL migrations
exception/                    # custom exceptions + FastAPI error handlers
logger/                        # shared logger factory
prompt_lib/                     # RAG prompt templates
schemas/                         # pydantic request/response models
utils/                             # pure helpers (chunking, hashing)
```

## 1. Supabase setup

1. Create a project at supabase.com.
2. In the SQL editor, run `database/migrations/0001_initial_schema.sql`.
3. In **Authentication → Providers**, enable Google (and Apple, if you have
   an Apple Developer account configured — it needs more setup than Google).
   Email OTP (magic link) is enabled by default, so you can test the whole
   app with just that while OAuth is being set up.
4. Add a few rows to `departments` (e.g. "Regulatory Affairs", "Clinical
   Ops", "Manufacturing") — the admin upload form reads from this table.
5. Promote your own user to manager once you've signed in once:
   ```sql
   update profiles set role = 'manager' where id = 'f5f0156c-6283-424c-9e4d-d23edbb8b307';
   ```


## 2. Local setup

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # then fill in your keys
uvicorn api.main:app --reload
```

Visit `http://localhost:8000`.

## 3. Before you deploy — verify two things I couldn't test

This was built in a sandbox with no network access to huggingface.co,
groq.com, or supabase.co, so these two integrations are written against each
service's documented API/SDK shape but not runtime-verified:

**a) The Hugging Face embedding call.** Their free serverless inference
routing for feature-extraction has changed more than once.
```bash
curl https://api-inference.huggingface.co/pipeline/feature-extraction/BAAI/bge-small-en-v1.5 \
  -H "Authorization: Bearer $HF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"inputs": ["test sentence"]}'
```
You should get back a numeric array. If not, see the fallback note in
`api/services/embedding_service.py`.

**b) The Supabase Storage upload call** in `api/services/ingestion_service.py`.
`supabase-py`'s `storage.from_(...).upload(...)` signature (positional args,
file-options dict keys) has changed across SDK versions — check it against
whatever version `pip install` resolves for `supabase==2.7.4`, or pin to a
version you've confirmed works.

## 4. Deploy to Vercel

```bash
npm install -g vercel
cd pharma-rag-py
vercel
```

Set the env vars from `.env` in the Vercel project settings. `vercel.json`
routes everything through `api/main.py` and bundles `api/static` +
`api/templates` alongside it — **this Python + static-files + FastAPI-on-Vercel
combination is less battle-tested than the plain Node.js version and I
couldn't verify it end-to-end.** If static assets 404 after deploying, the
likely fix is serving `/static` as a separate Vercel static route instead of
through the FastAPI app, or moving to a platform with native long-running
Python support (Render, Fly.io, Railway) if Vercel's Python runtime proves
too constrained for this app's needs.

## 5. What's implemented in V1

- Fixed-size chunking (`utils/text.py`), tagged `fixed_size_v1` so V2
  strategies can be compared against it later.
- Dense retrieval only, via the `match_chunks` Postgres RPC — department
  access is filtered inside the query itself, before ranking.
- Generation via Groq, grounded strictly in retrieved chunks.
- Full per-query tracing (`traces` table), surfaced in the Pipeline Trace tab.
- Document versioning: publishing a new version immediately deactivates the
  old version's chunks (`is_active = false`) so retrieval never mixes stale
  and current content — old versions stay in the DB for audit, just excluded
  from retrieval.
- RBAC: `manager` (upload/edit) vs `employee` (query-only), with
  department-based document visibility enforced via Postgres RLS.

## 6. What's deliberately out of scope for V1

- Evaluation numbers — schema and empty-state UI are in place, but no golden
  query set exists yet, so Recall@k/Precision@k have nothing to compute
  against yet (next milestone — see `progress.md`).
- PDF/DOCX parsing — V1 ingestion accepts plain text (`.txt`/`.md` file or
  pasted text) only.
- S3 sync — the schema (`sync_jobs`) anticipates it, the job itself isn't built.
- Everything in the V2 plan: chunking strategy comparisons, multiple
  embedding models, BM25/hybrid retrieval, reranking.
