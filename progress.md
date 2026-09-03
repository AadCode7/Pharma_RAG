# Progress Log — Pharma RAG Project

> Review this file at the start of every session before making changes, so decisions aren't re-litigated and nothing gets lost between sessions.

## Current Status: V1 rewritten in Python/FastAPI, now a proper multi-page app (real routes, not hidden divs) with email/password + Google auth. Not yet deployed or tested against live services.

---

## Completed

### Planning
- Defined two-phase scope (V1 baseline → V2 experimentation).
- Clarified requirements: free/cheap cloud APIs (Groq, Hugging Face); no golden eval set yet (deferred); sync = upload + optional S3 later, with a hard requirement that stale chunks are never retrievable; RBAC with department-based visibility; Supabase Auth with seamless social login.
- Wrote `architecture.md` — approved by user.

### V1 build — Node.js version (superseded)
First pass was built as Vercel serverless functions in Node.js. User asked for a full rewrite in Python, in a specific folder structure. **The Node.js code is no longer the active version** — noting it here only so nobody wonders why the decision log below mentions things that read as "Node.js reasoning."

### V1 build — Python/FastAPI version (current)
Full rewrite, same schema and governance logic, structured as:
- `database/migrations/0001_initial_schema.sql` — unchanged from the Node.js version; schema/RLS don't depend on backend language.
- `config/settings.py` — pydantic-settings, single `settings` object.
- `database/client.py` — service-role client (bypasses RLS, backend-only) + user-scoped client (RLS does the filtering).
- `exception/` — `AppError` hierarchy + FastAPI handlers, so routes raise instead of hand-rolling status codes.
- `logger/logger.py` — shared logger factory.
- `utils/text.py`, `utils/hashing.py` — fixed-size chunker (V1 baseline, tagged `fixed_size_v1`), content hashing for version tracking.
- `prompt_lib/rag_prompts.py` — system prompt + prompt builder, separated out so V2 can add a groundedness-judge prompt later without touching API-calling code.
- `api/models/chunk.py` — `ChunkDraft` domain dataclass (kept distinct from `schemas/`, which are API-facing pydantic contracts).
- `schemas/` — pydantic request/response models for query, ingest, documents, traces.
- `api/services/` — `rbac_service` (session verification + manager check), `embedding_service` (HF), `llm_service` (Groq), `retrieval_service` (calls `match_chunks` RPC), `ingestion_service` (orchestrates upload/versioning/chunking/embedding, enforces stale-chunk deactivation), `tracing_service`.
- `api/routes/` — one file per resource, thin — auth + validation + calling the right service.
- `api/main.py` — FastAPI app, mounts routers under `/api`, serves the frontend (`/` → Jinja2 template, `/static` → CSS/JS, `/config.js` → dynamically rendered public Supabase config instead of a static file that needed manual editing).
- Frontend (`api/static/styles.css`, `api/static/app.js`, `api/templates/index.html`) — carried over from the Node.js version essentially unchanged; frontend behavior doesn't depend on backend language, only the API paths matter and those stayed the same (`/api/query`, `/api/ingest`, etc.).
- `requirements.txt`, `vercel.json`, `.env.example`, `README.md`.

### Auth screen redesign (this session)
User feedback: "Continue with Apple" was a misreading — they meant the sign-in *page* should look like Apple ID's page, not that Apple should be an OAuth option; and they wanted real email/password auth (sign in + create account) instead of a magic-link-only flow.

- Removed the "Continue with Apple" OAuth button entirely.
- Removed the magic-link-only form.
- Added an email/password form (`api/templates/index.html` `#auth-form`) with a sign-in ⇄ create-account toggle (`app.js` `setAuthMode()`), driving `sb.auth.signInWithPassword()` and `sb.auth.signUp()` directly. Sign-up collects a full name and passes it as `options.data.full_name`, which the `handle_new_user()` trigger in the migration picks up for `profiles.full_name`.
- Handles the case where Supabase has email confirmation turned on (no session returned from `signUp` → show a "check your email" message and drop back to sign-in mode) vs. off (session returned → `onAuthStateChange` fires and enters the app automatically). Not able to test which path a fresh Supabase project defaults to — verify against your project's Auth settings.
- Kept "Continue with Google" as the only OAuth option, per the request.
- Restyled the auth screen specifically to resemble Apple ID's sign-in page (system font stack, black pill-shaped buttons, soft white card on light-gray page, blue focus ring) — deliberately a different visual language from the rest of the app (`architecture.md`'s clinical/lab-notebook system), the way a login screen is often visually distinct from the product behind it.
- Verified structurally (no live Supabase to test against): every element ID referenced in `app.js` exists in `index.html`, and `app.js` parses as valid JS.

### Multi-page restructure (this session)
User feedback: the whole app being one HTML file with JS-toggled `<div>` sections wasn't acceptable — wanted real separate pages with routing, plus a working sign-out that actually clears the session.

**Templates** — replaced the single `index.html` with:
- `api/templates/base.html` — shared layout (sidebar nav, script includes). Every authenticated page extends this via Jinja2 `{% extends %}` rather than duplicating the nav markup five times.
- `api/templates/login.html` — standalone (no sidebar); the only page without the auth guard.
- `api/templates/query.html`, `trace.html`, `sources.html`, `eval.html`, `admin.html` — one real route each (`/`, `/trace`, `/sources`, `/eval`, `/admin`), each just the page's own content inside `{% block content %}`.

**JS** — replaced the single `app.js` with one shared script per concern, plus one script per page:
- `api-client.js` — `apiFetch()`, `escapeHtml()`, `truncate()`, and `renderDocList()` (shared by Sources and Admin, since both render the same document/version list).
- `supabase-client.js` — creates the one `sb` client every other script uses.
- `guard.js` — the actual session enforcement. Redirects to `/login` if there's no session; populates the sidebar (name/role/admin-link visibility); dispatches an `auth-ready` event once that's done so page scripts don't race it; keeps listening for the session disappearing mid-visit (expiry/revocation) and redirects then too; wires sign-out to call `sb.auth.signOut()` (revokes the refresh token server-side, not just a local forget) before redirecting to `/login`.
- `login.js`, `query.js`, `trace.js`, `sources.js`, `admin.js` — one page's worth of logic each. `admin.js` additionally redirects non-managers away from `/admin` client-side (the API already enforces this via `require_manager`, but there's no reason to render the page for someone who can't use it). `trace.js` now reads `?requestId=` from the URL for the "view full trace" deep link from the Query page, since that's a real page navigation now, not a same-page section switch.

**Backend** — `api/main.py` now has one route per page (`/login`, `/`, `/trace`, `/sources`, `/eval`, `/admin`) instead of a single catch-all, each rendering its own template with `active_page` passed in for nav highlighting.

**Removed**: `api/templates/index.html`, `api/static/app.js` (superseded).

**Bug caught and fixed during this pass**: `schemas/ingest.py`'s `IngestRequest` expected snake_case (`department_ids`, `existing_document_id`), but the frontend has always sent camelCase (`departmentIds`, `existingDocumentId`) — this dates back to the original Python rewrite, not something this session introduced, but it was silently broken (department assignment would have always come through empty). Fixed with pydantic field aliases (`populate_by_name=True` + `Field(alias=...)`), verified with an actual parse test.

**Verification actually run this session** (not just eyeballed):
- Every one of the 6 pages (`/login`, `/`, `/trace`, `/sources`, `/eval`, `/admin`) rendered through FastAPI's real `TestClient` + Jinja2 — confirms `{% extends %}`, `url_for()`, and the nav's inline `is-active` conditionals all work, not just that the `.html` files look right.
- Cross-checked every `getElementById()` call in each page's actual loaded JS (shared + page-specific) against that page's *rendered* HTML output — not the template source, the actual rendered result. Zero missing IDs across all 5 authenticated pages + login.
- Re-parsed the fixed `IngestRequest` schema against a real camelCase JSON payload to confirm the alias fix works.

### Bug fixes (this session)
User reported two real problems: the full-name field showing on the sign-in page (not just sign-up), and sign-up failing with "Failed to fetch" and nothing in the server logs.

**1. `[hidden]` attribute silently not working — `api/static/styles.css`.**
Root cause: `.field-group { display: flex }` and `.nav-item { display: block }` are author-origin CSS rules, which always override the browser's own default `[hidden] { display: none }` rule regardless of selector order or specificity — that's how CSS's cascade origin priority works, not something you can fix by moving rules around. This meant `#fullname-group[hidden]` (the reported bug) rendered anyway, and — not yet reported, but the same bug — `#nav-admin[hidden]` would have too, meaning **employees may have been able to see the "Knowledge Base" admin nav link.** (The `/admin` page itself still redirects non-managers via `admin.js`'s role check, and the API still enforces `require_manager()` — so this was a UI leak, not a data access hole — but still needed fixing.) Fixed with one global rule: `[hidden] { display: none !important; }`. `!important` on a non-conflicting author rule always wins regardless of specificity, so this fix is robust against any future class that sets `display` on a `hidden`-toggled element, not just the two callers we currently know about.

**2. Sign-up "Failed to fetch" with nothing in server logs.**
This one needs a flag, not just a fix: **`sb.auth.signUp()` / `signInWithPassword()` call Supabase's Auth API directly from the browser — they never touch our FastAPI backend.** So "nothing in the server logs" is expected, not itself a sign of the bug; the actual error was always only ever going to be in the browser's own console/Network tab. I can't reproduce this from the sandbox (no network access to supabase.co here), so I couldn't confirm the exact root cause, but a literal "Failed to fetch" from the Fetch API specifically means the request never reached a server at all — DNS failure, connection refused, or CORS block — and by far the most common cause of that, in a fresh setup, is `SUPABASE_URL` still being the placeholder from `.env.example` (or otherwise wrong) that nothing ever validates before use. Fixed defensively, in three places:
- `api/static/js/supabase-client.js` — now checks `window.APP_CONFIG` for placeholder/missing values *before* constructing the client, and if it looks wrong, shows a loud red on-page banner plus `console.error` explaining exactly what's misconfigured, instead of silently constructing a client that's doomed to fail on every call.
- `api/static/js/login.js` — the catch block now `console.error`s the *full* error object (previously only `err.message` was shown to the user, which for a network failure is just the unhelpful string "Failed to fetch" with no context), and distinguishes a network/config failure from an actual rejected sign-in with a message that points at the right fix for each.
- `api/static/js/guard.js` — hardened the same way: the whole session check is now wrapped in try/catch (previously an unexpected error here would leave the page permanently blank, since `body` starts `hidden` and nothing would ever unhide it), the profile-fetch query now checks its own `error` instead of silently defaulting to "employee" with no explanation, and sign-out now logs+continues instead of potentially leaving someone stuck if the server-side revoke call itself fails.

**If sign-up still fails after checking `.env`**: open the browser DevTools console during the attempt — with these changes, whatever Supabase actually returned (invalid API key, project paused, CORS restriction, etc.) will be logged there in full, which it wasn't before.

**Verified this session** (not just eyeballed): re-ran the full page-rendering + ID cross-check suite after all changes (still clean across all 5 pages), re-ran the JS syntax check on every file in `api/static/js/`, and confirmed with a small standalone regex test that the placeholder-detection pattern actually matches the real strings in `.env.example`.

**Skills check**: the person mentioned uploading 3 custom skills (`design-taste-frontend`, `web-design-guidelines`, `apple-design-analysis`) — checked for them (filesystem + `search_skills`), not yet available in this environment, likely a sync delay on the catalog side. Worth checking again next session, especially `apple-design-analysis` given the login page's styling.

---

## Known Risks / Things To Verify (not yet tested)

Same sandbox network limitation as before — no access to huggingface.co, groq.com, or supabase.co from here, so nothing below has been runtime-tested:

1. **Hugging Face embeddings** (`api/services/embedding_service.py`) — still the highest risk; see README §3a for the verification curl command. Unchanged from the Node.js version's risk.
2. **`supabase-py` Storage upload signature** (`api/services/ingestion_service.py`) — **new risk introduced by this rewrite.** The Python SDK's `storage.from_(...).upload(...)` call signature (positional args, file-options dict key names) has shifted across `supabase-py` versions. Verify against whatever version actually installs — see README §3b.
3. **`supabase-py` RPC/query builder syntax** (`api/services/retrieval_service.py`, and the `.single()`/`.in_()`/`.is_()` calls throughout `ingestion_service.py`) — written against the documented v2 API; worth a smoke test since Python client method names occasionally differ subtly from the JS client's (e.g. `in_` and `is_` have trailing underscores to avoid shadowing Python keywords — easy to typo).
4. **FastAPI on Vercel's Python runtime, with static files** (`vercel.json`) — this combination (ASGI app + `StaticFiles` mount + Jinja2 templates, all bundled via `includeFiles`) is less common and less battle-tested on Vercel than the plain Node.js serverless-functions approach used in the first version. If static assets 404 after deploying, see the fallback note in README §4.
5. Everything already flagged in the Node.js version that's unrelated to language (RLS correctness, Groq model name currency) still applies — re-verify since it's a from-scratch rewrite, not a port with guarantees. (Apple OAuth setup is no longer relevant — that option was removed per the auth redesign above.)
6. **Whether your Supabase project requires email confirmation on sign-up** — determines which of the two code paths in the sign-up handler actually fires. Check Authentication → Settings → "Confirm email" in the Supabase dashboard.
7. **Auth is enforced client-side, by design, not by the server refusing the page** — `/admin`'s HTML shell is fetchable by anyone (it's just markup + a script tag), but it contains no data; `guard.js` redirects before any content is shown, and the actual document/trace data only comes back from `/api/*` routes that verify the session server-side. This is a normal pattern for a Supabase-Auth-in-localStorage app without server-side sessions — flagging it so it's a documented decision, not a discovered gap.

---

## Not Yet Started

- [ ] Running the migration against a live Supabase project
- [ ] End-to-end smoke test (sign up → promote to manager → upload a doc → query it → see it in Trace/Sources)
- [ ] Vercel deployment
- [ ] Golden eval set + eval harness — **blocked on user providing/curating the eval set**
- [ ] S3 sync job
- [ ] PDF/DOCX ingestion (V1 is plain text only)
- [ ] V2: chunking strategy comparisons, multiple embedding models, BM25/hybrid retrieval, reranking

---

## Errors / Issues Encountered

**During this rewrite, I was able to actually test the parts that don't need network access to huggingface.co/groq.com/supabase.co** (pip install works — pypi.org is reachable):

- `pip install -r requirements.txt` — hit one conflict: `PyJWT` was pre-installed by the OS and blocked reinstall. Fixed with `--ignore-installed PyJWT`. Not expected to recur in a normal deploy environment (Vercel builds fresh), but worth knowing if you hit it in a different sandbox/container.
- Imported the full FastAPI app (`from api.main import app`) with dummy env vars — **it wired up cleanly**: all 5 routers, all service imports, static mount, templates, `/config.js`, `/health`. This rules out import errors, circular imports, and wrong attribute/method names in the wiring itself.
- Ran the pure-logic pieces end to end: `chunk_fixed_size` (correct chunk boundaries and count on a ~2500-char sample), `sha256_hash` (deterministic, change-sensitive), `build_user_prompt` (correct `[1]`-style citation formatting), `normalize_embedding_output` (correctly handles both the pooled-vector and token-level-needing-mean-pooling response shapes described in the Known Risks section).

**Still not tested** (genuinely can't be, without network access to the three external services): the actual HTTP calls to Hugging Face, Groq, and Supabase (auth, table queries, RPC, storage upload). Those remain real risks — see above — but everything that was possible to verify from this sandbox has been.

---

## Key Decisions Log (do not re-litigate without reason)

| Decision | Rationale |
|---|---|
| **Rewrote V1 backend from Node.js to Python/FastAPI** | Explicit user request, with a specified folder structure (api/{models,routes,services,static,templates}, config, database, exception, logger, prompt_lib, schemas, utils) |
| `schemas/` (pydantic API contracts) kept separate from `api/models/` (internal domain shapes) | Keeps request/response validation concerns separate from internal representations — a schema can change to match a client need without forcing a change to how the pipeline represents a chunk internally |
| `services/` layer is the only place that calls external APIs or the DB directly | Routes stay thin (auth + validation + delegate); business logic is testable independent of FastAPI |
| Custom `AppError` exception hierarchy + FastAPI exception handlers, instead of routes returning error JSON manually | One place defines the error→status-code mapping; routes just `raise` |
| `/config.js` is a FastAPI route rendering settings server-side, not a static file | Removes the "remember to hand-edit config.js before every deploy" step the Node.js version had |
| JSON response keys stayed camelCase (`requestId`, `versionNumber`, etc.) instead of switching to Python-idiomatic snake_case | Frontend JS was carried over unchanged; matching its expected keys avoided touching working frontend code for a backend-only rewrite |
| Documents are versioned, never overwritten/deleted; department access enforced inside `match_chunks` before ranking; custom in-house tracing — | **unchanged from the original architecture**, since none of this is language-specific. See architecture.md §3 for the reasoning. |

---

## Next Step

1. User runs the migration on a real Supabase project.
2. Verify the two Python-specific integration points flagged above (HF embeddings call, Supabase Storage upload) before trusting them.
3. Smoke-test the full pipeline end to end locally (`uvicorn api.main:app --reload`) before deploying.
4. Deploy to Vercel; if the Python + static-files combination misbehaves, fall back per README §4.
5. Report back any errors hit during setup so they get logged here before moving on to V2 or the eval harness.
