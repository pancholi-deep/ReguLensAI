# ReguLens AI

ReguLens AI is a regulatory intelligence and change impact assessment prototype. It helps compliance teams discover regulatory publications, understand obligations, compare regulatory changes with internal policies and assess potential business impact.

## Architecture

- **Frontend:** React + TypeScript + Vite in `frontend/`
- **Backend:** FastAPI in `backend/`
- **Database:** PostgreSQL in production; local SQLite fallback for development
- **Migrations:** Alembic in `backend/migrations/`
- **API contract:** JSON REST endpoints under `/api/v1`
- **Authentication:** Google Identity Services with server-side ID-token verification and application sessions
- **AI/document intelligence:** Gemini-assisted extraction and interpretation with deterministic/rule-based fallbacks
- **Deployment:** Render Blueprint with a static frontend and Python API service

The browser communicates with the backend over HTTP. The backend owns application data and business logic; the frontend handles presentation and user interactions.

## Current product workflow

1. A signed-in user uploads internal policies and procedures to the **Internal Policy Repository**.
2. The source monitor polls configured regulatory RSS feeds or public HTTP(S) sources.
3. When a new or changed regulatory document is discovered, it is downloaded, deduplicated by SHA-256, extracted and persisted.
4. The new regulatory document is automatically compared with the user's uploaded internal policies and relevant historical regulatory publications.
5. Evidence-backed findings appear in the existing **Actions to review** workflow. A person must review the findings; the system does not make a compliance decision.

The Internal Policy Repository reuses the existing document upload and persistence flow. It is not a separate asset-management module. Matching uses meaningful shared terms, title similarity and regulatory relationship signals; it is intended for triage, not as a definitive compliance determination.

## Current capabilities

- Overview dashboard with summary metrics and regional coverage
- Searchable regulatory publication feed with region and status filters
- Change analysis with previous/updated clause panels and review actions; some bundled examples are synthetic
- Settings view showing target regional source groups
- Internal Policy Repository for PDF, DOCX and TXT policies/procedures
- Chunked document extraction with Gemini-assisted intelligence and rule-based fallback
- Structured clause extraction, obligation typing, affected entities/departments, deadlines and explicit references to older instruments
- Automatic impact check for each newly fetched regulatory document against uploaded internal policies
- Historical regulatory matching using explicit references, regulator, jurisdiction, title, business-area and content signals
- Clause alignment and evidence-backed comparison findings using the supported change categories
- Human review of findings through Actions to review
- PostgreSQL persistence for authorities, instruments, publications, document versions, extracted sections, clauses, obligations, references, relationships, comparisons, findings and analysis jobs
- SHA-256 duplicate detection; identical uploads reuse the existing document version
- Google sign-in with server-side Google ID-token verification and secure, HTTP-only API session cookies
- Per-user document ownership, duplicate detection and repository comparisons isolated to the signed-in user's documents
- Protected document upload, saved-document listing, document details and comparison APIs; public demo feed remains available without sign-in
- Alembic migrations for persistence, document intelligence, source monitoring and user ownership, with regression tests

**Demo-data notice:** Bundled publications and clause examples may be synthetic demo data. They are not official regulatory publications and must not be used to make compliance decisions.

**Document-retention limitation:** The database stores extracted text, metadata, source sections, obligations and structured extraction results. The original uploaded binary is not retained in this milestone; object storage and download/retention policies are future work. Do not upload confidential customer or production documents.

## Requirements

- Python 3.11+
- Node.js 20.19+ (or compatible newer LTS release)
- npm
- PostgreSQL for shared / production persistence (SQLite is used automatically for local development if `DATABASE_URL` is empty)

## Run locally

### 1. Configure the backend

Create a repository-root `.env` file (it is Git-ignored):

```bash
cp .env.example .env
```

Set `GEMINI_API_KEY` if you want LLM-assisted extraction. Set `DATABASE_URL` to a PostgreSQL URL to use PostgreSQL locally; otherwise the backend creates `backend/.local/regulens.db` using SQLite.

Install dependencies, apply the schema and start the API:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- API health: http://127.0.0.1:8000/api/v1/health
- Storage diagnostics: http://127.0.0.1:8000/api/v1/diagnostics/storage
- Interactive API docs: http://127.0.0.1:8000/docs

### 2. Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies local `/api` requests to FastAPI on port 8000.

### 3. Run backend tests

From the repository root:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use isolated SQLite databases and mock external Gemini requests. CI applies Alembic migrations against SQLite and runs backend tests plus the frontend build.

## Persistence and comparison behaviour

- `POST /api/v1/documents` uploads, analyzes and persists a PDF, DOCX or TXT document. The existing `POST /api/v1/documents/analyze` route remains as a compatibility alias.
- `GET /api/v1/documents` lists persisted document versions with search, jurisdiction filter and pagination.
- `GET /api/v1/documents/{document_version_id}` returns the stored extraction result, source-section references and historical comparison summary.
- `GET /api/v1/documents/{document_version_id}/comparisons` returns repository matches and findings.
- `GET /api/v1/comparisons/{comparison_id}` returns an individual historical comparison.
- `GET /api/v1/changes` includes persisted findings alongside synthetic demo examples.
- `GET /api/v1/publications` includes persisted uploads alongside synthetic demo records in local development.
- SHA-256 hashes prevent the same file content from being analyzed and stored repeatedly.
- Every newly ingested document is checked against previously saved documents. Documents uploaded without a source URL are treated as internal policies and matched using meaningful shared terms and title similarity. Fetched regulatory publications are additionally matched to historical publications using explicit amendment/repeal references, regulator, jurisdiction, title, business-area and content signals. The highest-scoring 20 relevant documents are compared to bound processing cost.
- Saved documents without clause records are reconstructed from persisted source sections and obligations on first comparison. These baselines are labelled as reconstructed rule-based clauses, not as newly Gemini-extracted content.
- Aligned clauses are compared using deterministic text similarity and optional Gemini interpretation. Findings retain previous/updated wording, source references, classification, possible impact and review status.
- An unmatched old clause is not automatically labelled withdrawn. Repeal/supersession findings require explicit relationship language in the new document.

Matching is a triage signal. Findings require qualified human review and must not be treated as legal or compliance advice.

## Regulatory source monitoring

- The signed-in **Sources** workspace can add RBI Notifications using the RBI notifications RSS endpoint, `https://www.rbi.org.in/notifications_rss.xml`, and additional public HTTP(S) source URLs.
- The RBI notifications listing is also available at `https://www.rbi.org.in/Scripts/NotificationUser.aspx`. The crawler follows feed/listing links to notification detail pages, discovers linked PDF/DOCX/TXT files, and detects new or changed file bytes using SHA-256.
- Each newly ingested regulatory document is extracted and automatically compared with the signed-in user's uploaded internal policies and relevant historical publications. Resulting findings are surfaced in **Actions to review**.
- Custom sources are configured independently per user. Polling intervals are configurable from 15 minutes to 24 hours; sources can be paused, checked on demand or removed.
- The API scheduler runs when `SOURCE_CRAWLER_ENABLED=true`. The Render Blueprint sets this flag to true for the API service. For deployments with multiple API replicas, run the crawler on only one replica until a distributed scheduler/lock is introduced.
- Source URLs are validated as public HTTP(S) addresses; local, private, reserved IP addresses and non-standard ports are rejected. Crawl frequency, page size and document size are bounded.
- A first crawl ingests up to 12 linked documents per source to seed the per-user repository. Subsequent crawls ingest changed files only.
- A regulator or hosting provider may reject automated requests (for example, with HTTP 403). Check the source's last error and test reachability from the deployed environment; successful access from a developer laptop does not guarantee access from Render. Use another official feed or a supported public source URL when a regulator blocks automated access.

## Render deployment

The personal fork's `main` branch is the deployment source. The Render Blueprint defines a FastAPI service (`regulens-ai-api`) and React static site (`regulens-ai-frontend`).

1. Connect your GitHub account to Render if it is not connected already.
2. In the Render Dashboard, choose **New → Blueprint**, connect `pancholi-deep/ReguLensAI`, and select the `main` branch. Render reads the root `render.yaml`.
3. Provision a managed PostgreSQL database in Render (or use another reachable PostgreSQL provider). Keep it in the same Render region as the API when using Render Postgres.
4. In the API service, set:
   - `DATABASE_URL`: the database's **Internal Database URL** when using Render Postgres in the same region.
   - `APP_ENV=production`.
   - `ALLOWED_ORIGINS`: the exact frontend origin, e.g. `https://regulens-ai-frontend.onrender.com` (no trailing slash).
5. In the API service, set `GOOGLE_CLIENT_ID` to the OAuth 2.0 Web client ID from Google Cloud Console. Set `SESSION_SECRET` to a cryptographically random secret of at least 32 characters (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Do not commit either value.
6. In the frontend static site, set `VITE_API_BASE_URL` to the API origin, e.g. `https://regulens-ai-api.onrender.com`, and `VITE_GOOGLE_CLIENT_ID` to the same Google OAuth Web client ID. Redeploy the frontend after changing these values because Vite embeds them at build time.
7. In Google Cloud Console, configure the OAuth consent screen and add the exact frontend origin under **Authorized JavaScript origins**. Add local development origins such as `http://localhost:5173` only when needed. This app uses Google Identity Services ID-token credentials; it does not require a Google client secret.
8. **Apply database migrations explicitly.** The current API start command only starts Uvicorn; it does not run Alembic automatically. After configuring `DATABASE_URL`, run `alembic upgrade head` as a one-off command in the API service environment (from the backend working directory) before first use and whenever new migrations are introduced. Do not assume a service restart applies migrations.
9. Set `SOURCE_CRAWLER_ENABLED=true` on one API instance to enable scheduled source polling. The Render Blueprint sets this for its single API service. Keep `APP_ENV=production`. FastAPI verifies the Google ID token, creates an application session in a Secure, HttpOnly cookie, and requires that session for document APIs. Document listing, duplicate detection and historical comparison are scoped to the authenticated user's ID. Public demo data remains readable without sign-in.

The Blueprint intentionally does not create a database automatically, so you choose the database provider and pricing. Render's Free Postgres currently expires 30 days after creation and is limited to 1 GB; use it only for disposable testing, not durable project data. See [Render's Free instance limitations](https://render.com/docs/free).

**Security notes:** The Google client ID is public configuration and is used by the browser and API for audience validation. `SESSION_SECRET` is private and must exist only on the API service. Sessions expire after 12 hours. Keep HTTPS enabled so production session cookies remain Secure. Never put the Gemini key or session secret in frontend environment variables or commit them to GitHub. Rate limiting and production abuse controls should be added before opening unrestricted public sign-ups.

Verify:
- API health: `https://<api-service>.onrender.com/api/v1/health`
- Storage diagnostics: `https://<api-service>.onrender.com/api/v1/diagnostics/storage`
- API docs: `https://<api-service>.onrender.com/docs`

Render can automatically redeploy services when changes are merged or pushed to their linked branch. With the Blueprint linked to `main`, future merges to `main` become the deployment source.

## GitHub collaboration workflow

This repository uses the standard GitHub fork workflow:

| Remote | Repository | Purpose |
|---|---|---|
| `origin` | `pancholi-deep/ReguLensAI` | Personal fork; default push/pull remote |
| `upstream` | `Jinal7599/ReguLensAI` | Original repository; source of upstream updates and target for contribution PRs |

The Azentio hackathon starter repository is not configured as a remote in this local development setup.

Recommended branch conventions:

- `main` is the stable integration branch and tracks `origin/main`.
- Develop new work on short-lived branches such as `feature/<name>`, `fix/<name>` or `docs/<name>`.
- Push feature branches to `origin` and open pull requests into `origin/main`.
- After a feature is merged, update local `main` with `git switch main && git pull`.
- To bring changes from Jinal's original repository into your fork, run `git fetch upstream`, review the changes, merge `upstream/main` into local `main`, and push the result to `origin`.
- To contribute changes back to Jinal's repository, push a feature branch to your fork and open a pull request from `pancholi-deep/ReguLensAI:<branch>` to `Jinal7599/ReguLensAI:main`.

Useful commands:

```bash
# Start a feature from the latest personal-fork main
git switch main
git pull
git switch -c feature/my-change

# Commit and publish the feature branch
git add .
git commit -m "Describe the change"
git push -u origin feature/my-change

# Refresh upstream references without changing the working branch
git fetch upstream

# Integrate reviewed upstream changes into your fork
git switch main
git merge upstream/main
git push origin main
```

Avoid working directly on `main`. Do not force-push shared branches unless the team has explicitly agreed to rewrite their history.

## Development principles

- Keep API routes versioned under `/api/v1`.
- Keep regulatory connectors, document processing and AI orchestration in backend modules.
- Keep deterministic comparison and evidence extraction separate from LLM-generated interpretation.
- Treat PostgreSQL as the system of record; use Alembic migrations for schema changes.
- Keep original document wording immutable and retain source-section references for every extracted obligation.
- Keep findings explainable and subject to human review.

## Disclaimer

This prototype is not certified for regulatory compliance. Regulatory interpretations and AI-generated recommendations require qualified human review.
