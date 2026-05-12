# Calendar Agent

A domain-specific AI agent for Google Calendar. Built to explore agentic patterns over structured APIs (tool use) combined with retrieval over unstructured personal context (RAG).

## What it does

- Connects to your Google Workspace (Calendar + Drive)
- Chat interface to your calendar with multi-step agent reasoning
- Multi-person scheduling with personalized email drafts
- Time analysis with concrete recommendations
- Retrieves personal preferences and meeting notes from Drive to inform decisions
- Generates pre-meeting prep briefs by composing calendar history with note retrieval

## Architecture

```
Frontend (Next.js)
        |
        v
Backend (FastAPI)
        |
        +--> Calendar tools (Google Calendar API)
        |
        +--> Gmail tools (draft creation)
        |
        +--> Chat agent (Claude with multi-provider fallback)
        |
        +--> RAG service (Drive doc indexing + retrieval)
        |
        +--> Memory service (per-session conversation context)
```

The agent composes two grounding paradigms:
- **Tool use** for structured data (calendar events, email drafts)
- **Retrieval-augmented generation** for unstructured personal context (notes, preferences)

## Setup

### Prerequisites

- Python 3.11+
- Node 18+
- Google Cloud project with OAuth credentials (Calendar + Gmail + Drive scopes)
- Anthropic API key

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in ANTHROPIC_API_KEY and GOOGLE_CLIENT_ID/SECRET
python3 app.py
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
# fill in NEXT_PUBLIC_API_URL
npm run dev
```

## Google Cloud setup

1. Create a project at https://console.cloud.google.com
2. Enable Calendar API, Gmail API, Drive API
3. Create OAuth 2.0 credentials (Web application type)
4. Add `http://localhost:8000/auth/callback` as authorized redirect URI
5. Add your gmail as a test user
6. Copy client ID and secret to `backend/.env`

## Stack

- Frontend: Next.js, React, TypeScript, Tailwind, shadcn/ui
- Backend: FastAPI, Python
- LLM: Claude (Anthropic) with OpenAI fallback
- APIs: Google Calendar, Gmail, Drive
