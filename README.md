# Pharma RAG — V1 (Python / FastAPI)

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

Set the env vars from `.env` in the Vercel project settings. The repository
pins Python via `.python-version` so the builder doesn't have to select a
default runtime.

### Website URL crawling on Vercel

Use the hosted Crawl4AI API for website ingestion on Vercel so the deployment
does not need to package or launch Chromium:

1. Create a key at [Crawl4AI](https://crawl4ai.com/).
2. In **Vercel Dashboard → Pharma_RAG → Settings → Environment Variables**, set
   `CRAWL4AI_API_KEY` for Preview and Production (and Development if used).
   Keep it server-side; do not put it in frontend JavaScript.
3. Redeploy the website-ingestion branch and test with a public page such as
   `https://quotes.toscrape.com/`.

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

## GraphRAG and GraphRAG + Hybrid Vector Search

This branch adds two selectable query strategies:

- **GraphRAG**: extracts source-grounded subject–predicate–object relationships during upload, matches query entities, explores the visible graph to two hops, and uses the supporting document chunks as LLM context.
- **GraphRAG + Hybrid Vector Search**: fuses graph-derived passages with the existing dense semantic + BM25 retrieval using Reciprocal Rank Fusion (RRF).



## Free RAG evaluation

The /eval page evaluates recent saved pipeline traces without calling an LLM judge or any extra paid API. Users can select traces, optionally supply known-relevant document UUIDs and verified reference answers, and calculate deterministic retrieval and text-overlap metrics.

Before using it, apply database/migrations/0004_trace_evaluation.sql in the Supabase SQL editor. The first version calculates Recall@K, Precision@K and MRR@K when relevant-document labels exist; context token recall, answer token F1 and ROUGE-L when a reference answer exists; and recorded latency for all selected traces. Missing labels are reported as unavailable rather than treated as zero. Text-overlap metrics are not a factuality or faithfulness judge.

The implementation adds no runtime dependency and makes no paid evaluation calls. Run the unit tests with python -m unittest discover -s tests -p test_evaluation_service.py.
