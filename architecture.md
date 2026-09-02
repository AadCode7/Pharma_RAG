# Pharma RAG System — Architecture & Schema

## 1. Project Goals

Build a Retrieval-Augmented Generation system for a pharmaceutical company, where **data governance and evaluability are first-class requirements**, not add-ons. The project is delivered in two phases:

- **V1 (Baseline):** Fixed-size chunking, single embedding model, single retrieval method, no reranking. Full end-to-end pipeline with tracing and an evaluation framework wired in from day one, even before a golden eval set exists.
- **V2 (Experimentation):** Multiple chunking strategies, multiple embedding models, hybrid retrieval (dense + BM25), and reranking (RRF, Cohere Rerank, cross-encoder) — all benchmarked against the same eval harness so improvements over V1 are measurable, not assumed.

Standing requirement across both phases: the knowledge base must stay current (manual upload + S3 sync, no stale data ever served to retrieval) and access to documents must be governed by department-based RBAC enforced at the database layer.

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Vanilla HTML/CSS/JS, served via FastAPI (Jinja2 template + static mount) | As specified; no separate static host needed since the Python backend serves it directly |
| Backend | Python / FastAPI, deployed on Vercel via `@vercel/python` | Switched from the original Node.js version at the user's request — see `progress.md` decision log. All ML work is still external API calls, so this is purely a language/framework choice, not a capability change |
| Database | Supabase Postgres + `pgvector` | Vector search, relational integrity, and RLS-based access control in one place |
| Auth | Supabase Auth (social login: Apple/Google) | Seamless login as requested; issues a session Postgres can use for RLS |
| File storage | Supabase Storage (+ optional S3 as a sync source) | Raw document storage, versioned |
| Embeddings | Hugging Face Inference API (e.g. `BAAI/bge-small-en-v1.5`) | Free tier, no self-hosting |
| Generation LLM | Groq (Llama 3.3 70B) primary; Gemini as a V2 comparison point | Free/cheap, fast inference |
| Sparse retrieval (V2) | Custom BM25 in JS | Postgres `ts_rank` isn't true BM25 — needed for an honest V2 comparison |
| Reranking (V2) | RRF (computed in-app, free), Cohere Rerank (free trial tier), HF cross-encoder | Range of free/cheap options to compare |
| Tracing | Custom — logged to Postgres, surfaced in-app | No third-party tracing SaaS, keeping all pipeline data (which may include sensitive doc content) inside our own infrastructure — consistent with the governance priority |

---

## 3. Governance & RBAC Design

**Roles:** `manager`, `employee`
- Managers: full read/write — upload, edit, delete documents, trigger sync, see all data
- Employees: read-only, and only within their department(s)

**Department-based visibility:** documents are tagged to one or more departments; users belong to one or more departments; an employee only ever sees chunks from documents tagged to their department(s).

**Critical design rule:** access control is enforced **inside the retrieval SQL query itself** (via Postgres RLS / a security-definer RPC that resolves the caller's departments), not as a post-processing filter applied after the vector search returns results. If filtering happened after retrieval, a restricted chunk could still influence ranking or leak into a response before being filtered out. This is non-negotiable for a pharma governance model.

**Document versioning (stale-data safety):**
- Documents are never overwritten or deleted. A modification creates a new `document_versions` row.
- Only the new version gets chunked and embedded.
- The old version's chunks are marked `is_active = false` — kept permanently for audit purposes, but excluded from every retrieval query (`WHERE is_active = true`).
- This guarantees retrieval can never surface outdated regulatory/SOP content, while preserving a full history for compliance audits.

---

## 4. Data Model (Supabase Postgres)

```sql
-- Auth / RBAC
profiles              (id UUID PK -> auth.users.id, role TEXT ['manager'|'employee'], full_name TEXT, created_at)
departments            (id, name)
user_departments        (user_id -> profiles.id, department_id -> departments.id)

-- Documents & versioning
documents              (id, title, source_type ['upload'|'s3'], source_uri, current_version_id, status ['active'|'archived'], created_at, created_by)
document_versions       (id, document_id, version_number, content_hash, storage_path, created_at, superseded_at)
document_departments    (document_id, department_id)   -- which departments can see this doc

-- Chunking & embeddings
chunks                  (id, document_version_id, chunk_index, content, chunk_strategy, char_start, char_end, is_active, created_at)
chunk_embeddings         (id, chunk_id, model_name, embedding VECTOR, created_at)
  -- separate from `chunks` so V2 can compare multiple embedding models against the same chunk text without recomputing chunks

-- Evaluation (populated once a golden set exists)
eval_queries             (id, query_text, expected_chunk_ids UUID[], expected_document_ids UUID[], category, created_at)
eval_runs                (id, config JSONB  -- {chunking_strategy, embedding_model, retrieval_method, rerank_method}, started_at, completed_at)
eval_results              (id, eval_run_id, query_id, retrieved_chunk_ids UUID[], recall_at_k, precision_at_k, mrr, groundedness_score, latency_ms, k)

-- Tracing
traces                    (id, request_id, user_id, query_text, stage JSONB  -- chunking/retrieval/rerank/generation breakdown, latency_breakdown JSONB, created_at)

-- Sync
sync_jobs                  (id, source ['manual'|'s3'], status, documents_added, documents_updated, documents_marked_stale, error_log, started_at, completed_at)
```

---

## 5. V1 Pipeline (step by step)

1. **Ingestion:** Manager uploads a document (or a scheduled S3 sync job pulls one in) → raw file stored in Supabase Storage → `documents` + `document_versions` rows created.
2. **Chunking:** Fixed-size chunking (e.g. 512 tokens, 50-token overlap) → rows in `chunks`, tagged `chunk_strategy = 'fixed_size_v1'`.
3. **Embedding:** Each chunk sent to the HF Inference API → stored in `chunk_embeddings`, tagged with `model_name`.
4. **Retrieval:** Query embedded → `pgvector` cosine similarity search, filtered by the caller's department(s) via RLS, top-k returned.
5. **Generation:** Retrieved chunks + query → Groq LLM → answer generated with citations back to source chunks.
6. **Tracing:** Every stage's inputs, outputs, and timings logged to `traces`.
7. **Evaluation (once a golden set exists):** Each `eval_queries` row run through the full pipeline; Recall@k, Precision@k, MRR, and a groundedness score computed and stored in `eval_results`.

---

## 6. Frontend Sections

1. **Query** — ask a question, get an answer with inline citations
2. **Pipeline Trace** — for the last query: chunking method → retrieved chunks with scores → (V2: reranking) → final prompt → generated answer
3. **Sources** — which documents/versions were used, linking to the source chunk in context
4. **Evaluation Dashboard** — Recall@k/Precision@k/MRR/groundedness per run; in V2, a comparison table across strategies
5. **Knowledge Base Admin** (manager-only) — upload, trigger S3 sync, view sync job history, view document version history and staleness status

---

## 7. V2 Plan (future phase)

- **Chunking:** semantic, recursive, sentence-window, hierarchical — compared against `fixed_size_v1`
- **Embeddings:** multiple models compared via `chunk_embeddings.model_name`
- **Retrieval:** hybrid dense + BM25
- **Reranking:** RRF, Cohere Rerank, cross-encoder
- All strategies scored against the same `eval_queries` set, results stored per `eval_runs.config`, so the comparison table in the dashboard is apples-to-apples.

---

## 8. Open / Deferred Decisions

- **Golden eval set:** does not exist yet — deferred by user, to be created after V1 pipeline is functional (either curated manually or bootstrapped semi-synthetically).
- **Groundedness scoring method:** not yet decided — candidates are LLM-as-judge (Groq/Gemini scoring answer against retrieved chunks) vs. an NLI/entailment model. To be decided before eval harness is built.
- **S3 sync trigger:** scheduled poll vs. webhook — deferred until an S3 bucket/credentials are available to test against.

---

## 9. Repo Structure

```
api/
  main.py            -- FastAPI app: routers, static/template mounting, /config.js
  models/             -- internal domain shapes (e.g. ChunkDraft)
  routes/              -- one file per resource (query, ingest, documents, traces, departments)
  services/             -- business logic + external API calls (embeddings, LLM, retrieval, ingestion, tracing, RBAC)
  static/                -- styles.css, app.js
  templates/              -- index.html (Jinja2)
config/                     -- pydantic-settings
database/                     -- Supabase client factory + SQL migrations
exception/                     -- custom exceptions + FastAPI error handlers
logger/                          -- shared logger factory
prompt_lib/                       -- RAG prompt templates
schemas/                           -- pydantic request/response models
utils/                               -- pure helpers (chunking, hashing)
architecture.md
progress.md
```
