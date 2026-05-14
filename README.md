# Calendar Agent

A domain-specific AI agent for Google Calendar. Built to explore agentic patterns over structured APIs (tool use) combined with retrieval over unstructured personal context (RAG).

The goal is to move past chatbot-as-demo into chatbot-as-deployable-infrastructure: real OAuth, real API integration, real grounding, multi-provider fallback, and a prep-brief workflow that composes tool use + RAG.

**Wow extension: the Meeting Prep Assistant.** Hover any upcoming calendar event and click *Prep Brief* — the agent composes three data sources (calendar metadata + retrieved personal context from RAG + LLM synthesis) into a structured pre-meeting brief. This is the high-leverage extension that elevates the system from a chatbot into an artifact-producing agent.

## What it does

- Connects to your Google Workspace (Calendar + Gmail + Drive)
- Chat interface that reasons over your calendar with multi-step tool use
- Multi-person scheduling with timezone-aware free slot search
- Generates Gmail drafts for scheduling emails (review before send)
- Analyzes how you're spending time in meetings, with recommendations
- Indexes personal preferences and notes from Drive via RAG
- Generates pre-meeting prep briefs by composing calendar history with retrieved notes

## Architecture

```
Frontend (Next.js + React + Tailwind)
        |
        v
Backend (FastAPI)
        |
        +-- Auth (Google OAuth2 flow + token storage)
        |
        +-- Calendar tools     (list, freebusy, create, get-user)
        +-- Gmail tools        (draft creation)
        +-- Drive tools        (read files, list folder contents)
        |
        +-- Chat agent loop    (Claude primary, OpenAI fallback, tool use)
        |
        +-- RAG service        (chunk, optional embed, retrieve)
        +-- Memory service     (per-session conversation history)
        |
        +-- Prep assistant     (compose tool use + RAG into prep briefs)
```

Two grounding paradigms compose:

- **Tool use** for structured data (Google Calendar API, Gmail draft creation)
- **Retrieval-augmented generation** for unstructured personal context (Drive notes, preferences)

The agent decides which to use per query. Calendar facts come from API responses; personal context comes from retrieved chunks. The model can paraphrase and reason over both but cannot fabricate the underlying data.

## Setup

### Prerequisites

- Python 3.11+
- Node 18+
- Google Cloud project with OAuth credentials (Calendar + Gmail + Drive scopes enabled)
- Anthropic API key
- (Optional) OpenAI API key for fallback and embeddings

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in ANTHROPIC_API_KEY and GOOGLE_CLIENT_ID/SECRET in .env
python3 app.py
```

Backend serves on `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Frontend serves on `http://localhost:3000`.

### Google Cloud setup

1. Create a project at https://console.cloud.google.com
2. Enable APIs: **Calendar**, **Gmail**, **Drive**
3. OAuth consent screen: set up as External, add yourself as a test user
4. Create OAuth 2.0 client (Web application) with redirect URI:
   ```
   http://localhost:8000/auth/callback
   ```
5. Copy Client ID and Secret into `backend/.env`

**Note on test users.** While in OAuth Testing mode, only emails added under the consent screen's *Test users* list can authenticate. The app supports any Google account that's been authorized — there is no hardcoded user. Publishing for production requires Google to verify the Calendar/Gmail/Drive scopes (multi-week review), which is out of scope for this prototype.

### Optional: scoping to a non-primary calendar

By default the agent reads from and writes to the authenticated user's `primary` calendar. To point it at a secondary calendar (useful for demos or sandboxing), set `CALENDAR_ID` in `backend/.env` to the target calendar's ID (found in Google Calendar → Settings → that calendar → Integrate calendar → Calendar ID). Leave unset to use `primary`.

## Usage

1. Open `http://localhost:3000`
2. Click "Connect Google Workspace"
3. Complete OAuth consent (you'll be redirected back logged in)
4. Calendar appears on the left; chat on the middle; personal context indexing on the right
5. Try queries like:
   - "Summarize my upcoming week"
   - "Find 30 min with alice@example.com this week, mornings protected"
   - "How much time am I spending in meetings? How would you recommend I cut that down?"
6. Optional: paste a preferences note into the right panel, or index a Drive doc
7. Hover any calendar event and click "Prep brief" for an LLM-generated prep summary

## Key technical decisions

**Parser-separated-from-agent.** The model never reads raw API responses; it reasons over already-structured data fetched by tool calls. This keeps responses grounded and reduces hallucination.

**Multi-provider LLM with fallback.** Anthropic primary, OpenAI fallback. Important because providers deprecate models (Claude 3 Sonnet was decommissioned during development; the system has to fail over gracefully).

**Per-session memory + per-session RAG index.** Each authenticated user gets isolated state. Memory persists conversation across page reloads; RAG index persists indexed documents.

**RAG over CAG for personal context.** Cache-augmented generation (dumping the full personal corpus into the system prompt on every call) is more accurate for small corpora — no retrieval miss. I chose RAG anyway because (1) the corpus is user-controlled and unbounded — a user can connect a Drive folder of arbitrary size, and CAG breaks the moment the corpus exceeds the context window; (2) per-query token cost grows linearly with corpus size under CAG but stays roughly constant under top-k RAG; (3) the abstraction is multi-tenant-friendly. The RAG index exposes `all_text()` as a hook for a CAG fallback path on small corpora if needed.

**Read-only by default on action APIs.** Gmail integration creates drafts only, never sends. Calendar integration creates events only via explicit user action.

**Per-session rate limiting on expensive endpoints.** `/chat` (LLM-token cost) and `/rag/*` indexing (embedding cost) are guarded by a sliding-window limiter keyed on session id — 30 chat req/min and 10 RAG req/min. Over-budget callers get a clean `429` with `Retry-After`. In-process today; the abstraction stays the same when the bucket store moves to Redis for horizontal scaling.

## Production tradeoffs and improvements at scale

Today's implementation is demo-ready. The list below is the conscious gap between this and a production-grade system, grouped by concern. Every item is a deliberate scope choice, not an oversight.

### State and persistence

- **Sessions and RAG state are on local disk** (JSON files under `data/`). On Render's free tier the filesystem is ephemeral — restarts wipe state. Production path: encrypted Redis or Postgres for token storage with refresh-token rotation; pgvector or Qdrant for the RAG index once the corpus grows beyond what fits in JSON.
- **Rate limiter buckets are in-process memory**, scoped to a single backend instance. Multi-instance horizontal scaling needs Redis-backed bucket storage. The `SlidingWindowLimiter` abstraction stays unchanged; only the storage swaps.
- **In-memory metrics** (module-level dicts) don't survive restart. Production: ship to Prometheus or Datadog.

### Latency and cost

- **No streaming responses.** The agent thinks, then dumps the full response — fine for single-turn but the perceived latency on multi-tool flows is poor. Production: Anthropic streaming + Server-Sent Events on the frontend, stream both text and tool-use trace.
- **No Anthropic prompt caching.** ~90% of every chat prompt is invariant (system prompt + tool schemas); caching the stable prefix would meaningfully reduce per-call cost and TTFT. Not wired in this build.
- **Drive indexing is synchronous.** A 10k-document folder would block the request. Production: background job queue (Celery / ARQ) with progress reporting and retry.
- **No per-tool budget within a chat turn.** Agent loops are bounded by max-rounds but not by tool-call count per query. A runaway agent could chew tokens. Production: soft cap per query.

### Auth and multi-tenancy

- **Server-side opaque session tokens (not JWT).** After OAuth, the backend generates a UUID and stores Google credentials in a per-session JSON file; the frontend holds only the opaque session id. Chose this over JWT specifically because Google refresh tokens are long-lived secrets that shouldn't be exposed to the client — JWT-with-refresh-token-inside is an antipattern. Tradeoff: requires persistent server-side storage. On Render's free tier (ephemeral filesystem) sessions don't survive cold-start or redeploy — this is the immediate next thing to fix in production, by moving the session store to Redis or Postgres. The frontend ↔ backend contract stays the same; only the storage swaps. A hybrid pattern (signed JWT for the session id with server-side refresh token storage) is also valid and scales better across instances.
- **OAuth app in Testing mode.** Only emails added as test users in Google Cloud Console can authenticate. Publishing for general use requires Google verification of Calendar/Gmail/Drive scopes (multi-week review). Out of scope for a take-home prototype.
- **Rate limits are single-tier.** No free / enterprise tiering exists today. Production: per-tier lookup map; the limiter object is reusable, only the lookup changes.
- **One Google account per session.** No support for linking work + personal calendars. Production: cross-account merge for scheduling and analysis.

### Reliability and operations

- **No agent evaluation suite.** Smoke tests cover infrastructure (tool dispatch, RAG retrieval, memory persistence, rate limiting) but not regression-test agent behavior across prompt or model changes. Production: an eval framework (LangSmith, Promptfoo, or custom) running against fixtures on every prompt or model change.
- **CORS is whitelisted to the deployed frontend origin** but no further hardening (CSRF tokens, request signing). Defense-in-depth gaps for a prod-grade application.
- **No structured logging to a centralized backend.** Request logs go to stdout via the FastAPI middleware. Production: structured JSON logs shipped to Datadog / CloudWatch / Loki with correlation IDs threaded through tool calls.

### Product surface

- **Frontend is desktop-optimized.** Mobile responsive layout would need work. Production: responsive design, touch-friendly modals, mobile-optimized chat.
- **No conversation history UI.** Memory persists per session on the server but there's no UI to browse or search past sessions.

## Tests

```bash
cd backend
source venv/bin/activate
python3 tests/test_smoke.py
```

The smoke suite covers imports, tool schema, RAG chunking and retrieval, conversation memory persistence, and auth URL generation. No live network calls required.

## Stack

- Frontend: Next.js 16, React 19, TypeScript, Tailwind v4
- Backend: FastAPI, Python 3.13
- LLM: Anthropic Claude (primary), OpenAI (fallback)
- APIs: Google Calendar v3, Gmail v1, Drive v3
- OAuth: google-auth-oauthlib
- RAG: simple in-memory + JSON-persisted index, optional OpenAI embeddings, keyword fallback

## Project layout

```
calendar-agent/
├── backend/
│   ├── app.py             FastAPI entry + routes
│   ├── auth.py            Google OAuth flow + token storage
│   ├── calendar_tools.py  Calendar API wrappers
│   ├── gmail_tools.py     Gmail draft creation
│   ├── drive_tools.py     Drive read access
│   ├── chat_service.py    Agent loop, tool dispatch, multi-provider LLM
│   ├── memory_service.py  Per-session conversation memory
│   ├── rag_service.py     Chunking, retrieval, optional embeddings
│   ├── prep_assistant.py  Meeting prep brief composition
│   ├── config.py          Env-based config
│   ├── requirements.txt
│   └── tests/test_smoke.py
└── frontend/
    └── src/
        ├── app/page.tsx
        ├── components/
        │   ├── CalendarView.tsx
        │   ├── Chat.tsx
        │   ├── PrefsUploader.tsx
        │   ├── DrivePicker.tsx
        │   └── PrepBriefModal.tsx
        └── lib/api.ts      Type-safe API client
```
