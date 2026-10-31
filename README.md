# ReguLens AI

ReguLens AI is a regulatory intelligence and change impact assessment prototype. It helps compliance teams discover publications, understand obligations, compare regulatory clauses and assess potential business impact.

## Architecture

- **Frontend:** React + TypeScript + Vite in frontend/
- **Backend:** FastAPI in backend/
- **Database:** PostgreSQL in production; local SQLite fallback for development
- **Migrations:** Alembic in backend/migrations/
- **API contract:** JSON REST endpoints under /api/v1
- **Deployment:** Render Blueprint with a static frontend and Python API service

The browser communicates with the backend over HTTP. The backend owns application data and business logic; the frontend handles presentation and user interactions.

## Current iteration

- Overview dashboard with summary metrics and regional coverage
- Searchable regulatory publication feed with region and status filters
- Change analysis with previous/updated clause panels and review actions (currently synthetic examples)
- Settings view showing four target regional source groups
- Manual PDF, DOCX and TXT upload with chunked Gemini document intelligence and rule-based fallback
- Structured clause extraction, obligation typing, affected entities / departments, deadlines and explicit references to older instruments
- Repository-wide historical matching for each newly uploaded document, using explicit reference matches plus regulator, jurisdiction, title, business-area and content signals
- Clause alignment and evidence-backed comparison findings using the six required change categories
- Rule-based comparison fallback when Gemini is unavailable; findings remain flagged for human review
- PostgreSQL persistence for authorities, instruments, publications, document versions, extracted sections, clauses, obligations, references, relationships, comparisons, findings and analysis jobs
- SHA-256 duplicate detection; identical uploads reuse the existing document version
- Google Identity Services sign-in with server-side Google ID-token verification and secure, HTTP-only API session cookies
- Per-user document ownership, duplicate detection and repository-wide comparisons isolated to the signed-in user's documents
- Protected document upload, saved-document listing, document details and comparison APIs; public demo feed remains available without sign-in
- Alembic migrations for persistence, document intelligence and user ownership; authentication and authorization regression tests

**All bundled publications and clause examples are synthetic demo data. They are not official regulatory publications and must not be used to make compliance decisions.** Live source monitoring and original-file object storage are not enabled yet.

## Requirements

- Python 3.11+
- Node.js 20.19+ (or compatible newer LTS release)
- npm
- PostgreSQL for shared / production persistence (SQLite is used automatically for local development if DATABASE_URL is empty)

## Run locally

### 1. Configure the backend

Create a repository-root .env file (it is Git-ignored):

    cp .env.example .env

Set GEMINI_API_KEY if you want LLM extraction. Set DATABASE_URL to a PostgreSQL URL to use PostgreSQL locally; otherwise the backend creates backend/.local/regulens.db using SQLite.

Install dependencies and apply the schema:

    cd backend
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate
    pip install -r requirements-dev.txt
    alembic upgrade head
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

- API health: http://127.0.0.1:8000/api/v1/health
- Storage diagnostics: http://127.0.0.1:8000/api/v1/diagnostics/storage
- Interactive API docs: http://127.0.0.1:8000/docs

### 2. Start the frontend

In a second terminal, from the repository root:

    cd frontend
    npm install
    npm run dev

Open http://localhost:5173. Vite proxies local /api requests to FastAPI on port 8000.

### 3. Run backend tests

From the repository root:

    cd backend
    pip install -r requirements-dev.txt
    python -m pytest -q

Tests use isolated SQLite databases and mock Gemini requests. CI applies all Alembic migrations against SQLite and runs the backend tests plus frontend build.

## Persistence behaviour

- POST /api/v1/documents uploads, analyzes and persists a PDF, DOCX or TXT document. The existing POST /api/v1/documents/analyze route remains as a compatibility alias.
- GET /api/v1/documents lists persisted document versions with search, jurisdiction filter and pagination.
- GET /api/v1/documents/{document_version_id} returns the stored extraction result, source-section references and historical comparison summary.
- GET /api/v1/documents/{document_version_id}/comparisons returns repository matches and findings.
- GET /api/v1/comparisons/{comparison_id} returns an individual historical comparison.
- GET /api/v1/changes includes persisted findings alongside synthetic demo examples.
- GET /api/v1/publications includes persisted uploads alongside synthetic demo records in local development.
- SHA-256 hashes prevent the same file content from being analyzed and stored repeatedly.
- Every new upload is scored against all previously saved document versions (the synthetic dashboard examples are not treated as source documents). Explicit amendment/repeal references take precedence; regulator, jurisdiction, title, business-area and content signals identify additional relevant candidates. The highest-scoring 20 relevant documents are compared to bound processing cost.
- Saved Milestone A documents that do not have clause records are reconstructed from their persisted source sections and obligations on first comparison. These baselines are labelled as reconstructed rule-based clauses, not as newly Gemini-extracted content.
- Aligned clauses are compared using deterministic text similarity and optional Gemini interpretation. Findings retain previous/updated wording, source references, classification, possible impact and review status.
- An unmatched old clause is not automatically labelled withdrawn. Repeal/supersession findings require explicit relationship language in the new document.

The database stores extracted text, metadata, source sections, obligations and the structured extraction result. **The original uploaded binary is not retained in this milestone**; object storage and download/retention policies are a later step. Do not upload confidential customer or production documents.

## Regulatory source monitoring

- The signed-in **Sources** workspace can add the RBI Notifications page and additional public HTTP(S) source URLs.
- RBI uses the official Notifications listing at `https://www.rbi.org.in/Scripts/NotificationUser.aspx`. The crawler follows notification detail pages, downloads linked PDF/DOCX/TXT files, detects new or changed file bytes by SHA-256, and submits changed documents to the same extraction and historical-comparison pipeline as manual uploads.
- Custom sources can be configured independently per user. Polling intervals are configurable from 15 minutes to 24 hours; sources can be paused, checked on demand or removed.
- The API scheduler runs when `SOURCE_CRAWLER_ENABLED=true` (enabled in the Render Blueprint) and checks sources according to each saved interval. For deployments with multiple API replicas, run a single crawler-enabled replica until a distributed scheduler/lock is introduced.
- Source URLs are validated as public HTTP(S) addresses; local, private, reserved IP addresses and non-standard ports are rejected. Crawl frequency and document size are bounded.
- A first crawl ingests up to 12 linked documents per source to seed the per-user repository. Subsequent crawls ingest changed files only. Findings are decision support and require human review.

## Render deployment

The repository is now consolidated on `main`. Use that branch as the deployment source.

1. Connect your GitHub account to Render if it is not connected already.
2. In the Render Dashboard, choose **New → Blueprint**, connect `pancholi-deep/ReguLensAI`, and select the `main` branch. Render reads the root `render.yaml` and creates the FastAPI service (`regulens-ai-api`) and React static site (`regulens-ai-frontend`).
3. Provision a managed PostgreSQL database in Render (or use another reachable PostgreSQL provider). Keep it in the same Render region as the API when using Render Postgres.
4. In the API service, set:
   - `DATABASE_URL`: the database's **Internal Database URL** when using Render Postgres in the same region.
   - `APP_ENV=production`.
   - `ALLOWED_ORIGINS`: the exact frontend origin, e.g. `https://regulens-ai-frontend.onrender.com` (no trailing slash).
5. In the API service, set `GOOGLE_CLIENT_ID` to the OAuth 2.0 Web client ID from Google Cloud Console. Set `SESSION_SECRET` to a cryptographically random secret of at least 32 characters (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Do not commit either value.
6. In the frontend static site, set `VITE_API_BASE_URL` to the API origin, e.g. `https://regulens-ai-api.onrender.com`, and `VITE_GOOGLE_CLIENT_ID` to the same Google OAuth Web client ID. Redeploy the frontend after changing these values because Vite embeds them at build time.
7. In Google Cloud Console, configure the OAuth consent screen and add the exact frontend origin (for example, `https://regulens-ai-frontend.onrender.com`) under **Authorized JavaScript origins**. Add local development origins such as `http://localhost:5173` only when needed. This app uses Google Identity Services ID-token credentials; it does not require a Google client secret.
8. The API start command runs `alembic upgrade head` when `DATABASE_URL` is configured, then starts FastAPI. Migration `0003_user_ownership_auth` creates the users table and adds nullable ownership to document versions. Existing pre-authentication records remain unowned and are intentionally not exposed to new accounts.
9. Set `SOURCE_CRAWLER_ENABLED=true` on one API instance to enable scheduled source polling. The Render Blueprint sets this for the single API service. Keep `APP_ENV=production`. FastAPI verifies the Google ID token, creates an application session in a Secure, HttpOnly cookie, and requires that session for document APIs. Document listing, duplicate detection and historical comparison are scoped to the authenticated user's ID. Public demo data remains readable without sign-in.

The Blueprint intentionally does not create a database automatically, so you choose the database provider and pricing. Render's Free Postgres currently expires 30 days after creation and is limited to 1 GB; use it only for disposable testing, not durable project data. See [Render's Free instance limitations](https://render.com/docs/free).

**Security notes:** The Google client ID is public configuration and is used by the browser and API for audience validation. `SESSION_SECRET` is private and must exist only on the API service. Sessions expire after 12 hours. Keep HTTPS enabled so production session cookies remain Secure. Never put the Gemini key or session secret in frontend environment variables or commit them to GitHub. Rate limiting and production abuse controls should be added before opening unrestricted public sign-ups.

Verify:
- API health: `https://<api-service>.onrender.com/api/v1/health`
- Storage diagnostics: `https://<api-service>.onrender.com/api/v1/diagnostics/storage`
- API docs: `https://<api-service>.onrender.com/docs`

Render can automatically redeploy services when changes are merged or pushed to their linked branch. With the Blueprint linked to `main`, future merges to `main` become the deployment source.

## Development principles

- Keep API routes versioned under /api/v1.
- Keep regulatory connectors, document processing and AI orchestration in backend modules.
- Keep deterministic comparison and evidence extraction separate from LLM-generated interpretation.
- Treat PostgreSQL as the system of record; use Alembic migrations for schema changes.
- Keep original document wording immutable and retain source-section references for every extracted obligation.

## Disclaimer

This prototype is not certified for regulatory compliance. Regulatory interpretations and AI-generated recommendations require qualified human review.
