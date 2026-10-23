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
2. In the Supabase SQL editor, apply migrations in order: `database/migrations/0001_initial_schema.sql`, then `database/migrations/0003_rag_strategy_configuration.sql`, then `database/migrations/0004_graph_rag.sql`, then `database/migrations/0005_graph_rag_quality.sql`. On an existing deployment, apply `0005_graph_rag_quality.sql` after 0004; it adds the graph extraction cache and updates Parent/Child graph evidence retrieval. GraphRAG requests require 0004, and the new cache/context improvements require 0005.
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

## 3. Before you deploy — verify the integrations

The Cohere Embed API and Supabase Storage upload call should be verified
against your own credentials and deployed environment before production use.

**a) Cohere embeddings.** Create an API key in the
[Cohere dashboard](https://dashboard.cohere.com/api-keys), then set
`COHERE_API_KEY` in your local `.env` file and in your deployment's
environment variables. The default embedding model is
`embed-english-light-v3.0` (384 dimensions). The embedding service sends
document chunks with `input_type="search_document"` and user questions with
`input_type="search_query"`. Requests are batched at a maximum of 96 texts.
Never commit your actual API key.

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


## GraphRAG and GraphRAG + Hybrid Vector Search

This branch adds two selectable query strategies:

- **GraphRAG**: extracts source-grounded subject–predicate–object relationships during upload, matches query entities, explores the visible graph to two hops, and uses the supporting document chunks as LLM context.
- **GraphRAG + Hybrid Vector Search**: fuses graph-derived passages with the existing dense semantic + BM25 retrieval using Reciprocal Rank Fusion (RRF).

### Setup and use

1. Apply `database/migrations/0004_graph_rag.sql` in Supabase SQL Editor.
2. Set `GROQ_API_KEY` and `COHERE_API_KEY` in the backend environment. Groq is used for graph extraction; Cohere remains the embedding provider.
3. Deploy this branch. In Knowledge Base, keep **Build knowledge graph during upload** checked when publishing or republishing a document version. The upload response reports graph indexing status and relationship counts.
4. Ask a question on the Query page and select either graph strategy. The response shows the graph relationships tied to the source chunks actually passed to answer generation. Those triples are also sent as untrusted retrieval hints in the answer prompt, mapped to the numbered source block that supports each relationship; source passages remain the evidence used for factual claims.

Existing documents are not backfilled automatically. Republish each version that should become available to GraphRAG. If graph extraction fails, the successfully published vector index remains available and the manager UI reports the failure; check backend logs and republish to retry. Graph extraction adds Groq calls and can increase upload latency, especially for long documents.

**Data handling note:** enabling graph indexing sends selected document passages (up to 2,600 characters per chunk, in small batches) to the configured Groq API for relationship extraction. Cohere is already used for embeddings, and selecting Cohere reranking sends retrieved query/passages to Cohere. Check your pharmaceutical-data, privacy, and vendor policies before sending confidential content to any hosted provider.

Graph rows are attached to chunk IDs. The graph retrieval SQL function applies department-based visibility, active chunk checks, and the current document-version pointer before returning edges. Do not query graph tables directly from browser code.
