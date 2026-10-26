# Pharma RAG System — Architecture & Schema

## 1. Project Goals

Build a Retrieval-Augmented Generation system for a pharmaceutical company, where **data governance and evaluability are first-class requirements**, not add-ons. The project is delivered in two phases:

- **V1 (Baseline):** Fixed-size chunking, single embedding model, single retrieval method, no reranking. Full end-to-end pipeline with tracing and an evaluation framework wired in from day one, even before a golden eval set exists.
- **V2 (Experimentation):** Multiple chunking strategies, dense/BM25 hybrid retrieval, Cohere reranking, Groq LLM reranking, and GraphRAG with optional hybrid vector search — benchmarked against a common evaluation set so improvements are measured, not assumed.

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
| Embeddings | Cohere Embed API (`embed-english-light-v3.0`, 384 dimensions) | Hosted embedding API used by the active implementation |
| Generation LLM | Groq (Llama 3.3 70B) primary; Gemini as a V2 comparison point | Free/cheap, fast inference |
| Sparse retrieval | Custom BM25 in Python | Provides BM25 ranking over authorized chunks without another service |
| Reranking | In-app Reciprocal Rank Fusion, Cohere Rerank, and Groq LLM reranking | Selectable second-stage ranking methods; provider limits apply |
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
3. **Embedding:** Each chunk is sent to Cohere Embed with `input_type=search_document` → stored in `chunk_embeddings`, tagged with `model_name`.
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


---

## 10. GraphRAG extension (feature/graphrag-hybrid-search)

### Ingestion and schema

Graph extraction runs after chunks and embeddings for a new version have been stored and the version published. It uses the configured Groq chat model to extract explicit subject–predicate–object triples in small chunk batches. A grounding validator discards relationships whose endpoints do not appear in the cited source chunk. Each relationship references its supporting `chunk_id`, so the generated graph can be traced back to real text.

- `graph_entities`: shared, normalized entity nodes and entity types.
- `graph_relationships`: typed subject/predicate/object edges, confidence, and supporting chunk.
- `visible_graph_relationships(p_caller_id, p_limit)`: server-only, security-definer SQL function. It returns only edges sourced from active chunks of the current document version that the caller is allowed to read by department (or all departments for a manager).
- `database/migrations/0004_graph_rag.sql`: creates the graph schema, indexes, RLS, grants, and permission-filtered RPC.

Graph indexing is enabled by default on the Knowledge Base upload form and can be disabled per version. A graph-extraction failure is reported separately and does not invalidate the successfully stored vector version. Existing documents must be republished to populate graph relationships.

### Query strategies

1. **GraphRAG**: resolve entities mentioned in the question, perform bounded graph-neighbor expansion (up to two hops), rank relationships by graph distance and lexical overlap, and use only their cited source chunks as answer context.
2. **GraphRAG + Hybrid Vector Search**: run the same graph retrieval and the existing dense + BM25 hybrid retriever, then fuse the two candidate lists with Reciprocal Rank Fusion. The existing reranking selector is still applied afterward.

The query UI displays graph triples only when their supporting source chunks are among the final answer context. Pipeline traces include graph counts and the relationships used. The graph contains extracted hypotheses that are validated against entity mentions; it is still an aid to retrieval, not a source of standalone medical truth.


### GraphRAG data handling

Graph indexing sends bounded source passages to the configured Groq API for relation extraction. This is a hosted inference call, not local inference; organizations must approve it under their pharmaceutical-data and vendor policies before enabling graph indexing on confidential material.

## GraphRAG quality and token efficiency

Graph extraction groups identical `parent_content` passages so Parent/Child indexing does not spend separate model calls on every overlapping child. Large contexts are divided into bounded, overlapping windows. Each extracted edge is linked to a real child chunk; the permission-filtered graph RPC returns that chunk's parent passage as evidence when available.

Extraction uses a strict evidence quote and validates the subject, object, and quote against the exact extraction unit. A small deterministic relation-pattern extractor handles explicit statements without API tokens; when it finds at least three relationships in a unit, the model call is skipped for that unit. If Groq is rate-limited, locally extracted and source-validated relations can be retained instead of failing the entire graph job.

The `graph_extraction_cache` table stores candidate triples by source SHA-256, model, and prompt version. Cached candidates are revalidated before persistence. Cache read/write failures are non-fatal. Apply `database/migrations/0005_graph_rag_quality.sql` after migration 0004.

The query selector recommends GraphRAG + Hybrid Vector Search: graph traversal helps discover connected evidence, while dense and BM25 retrieval remain available when the graph is incomplete. Graph edges are retrieval hints only; final answers must remain grounded in the original retrieved passage.


---

## 11. Image OCR ingestion

The manager Knowledge Base upload form supports JPG/JPEG, PNG and WebP image uploads in addition to the existing text, Markdown and selectable-text PDF paths. Images are processed by a lazily loaded Tesseract.js 5 worker in the browser; the worker is reused while the page stays open so repeated uploads do not repeatedly initialize the OCR engine. Browser-side preprocessing draws the image onto a white canvas, applies grayscale and mild contrast, modestly upscales small images, and caps the longest dimension at 2,600 pixels to limit memory use.

The image bytes are processed locally and are not sent to an OCR API. Tesseract.js and its English recognition data are downloaded from their configured CDNs on first use. The extracted text, rather than the original image, is sent to /api/ingest and then follows the existing selected chunking, Cohere embedding, optional GraphRAG indexing, versioning, and RBAC path. Image versions use an .ocr.txt storage suffix; no database migration is required.

Before chunking, normalize_extracted_text() normalizes Unicode and whitespace, removes NUL/zero-width/soft-hyphen artifacts, and conservatively repairs words split by hyphenated line wraps while retaining common true hyphenated compounds. OCR-only layout cleanup joins ordinary wrapped prose lines but preserves paragraph boundaries, recognizable headings, list items and table-like rows. This ensures chunk offsets and content refer to the same normalized text written to storage. Low-confidence OCR results are allowed to be reviewed and published, but the UI displays a warning when Tesseract reports confidence below 55.

Current OCR language is English (eng). PDF handling remains unchanged: a PDF with no selectable text still needs its pages uploaded as images or its text supplied manually; OCR for scanned PDFs is not part of this change.
