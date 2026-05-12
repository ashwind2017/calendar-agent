# Calendar Agent

A domain-specific AI agent for Google Calendar. Built to explore agentic patterns over structured APIs (tool use) combined with retrieval over unstructured personal context (RAG).

The goal is to move past chatbot-as-demo into chatbot-as-deployable-infrastructure: real OAuth, real API integration, real grounding, multi-provider fallback, and a prep-brief workflow that composes tool use + RAG.

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

**Cache-augmented when data fits in context.** A single user's preferences and meeting history fit in context; no vector retrieval needed. If the corpus grew (e.g., entire Gmail history), the same architecture would add a retrieval step.

**Read-only by default on action APIs.** Gmail integration creates drafts only, never sends. Calendar integration creates events only via explicit user action.

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
