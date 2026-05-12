"""FastAPI entry point for the Calendar Agent backend."""
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

from config import config
from auth import get_auth_url, exchange_code, load_credentials, delete_session
import calendar_tools
from chat_service import run_chat
from rag_service import get_index, get_embed_fn
from prep_assistant import generate_prep_brief
import drive_tools


app = FastAPI(title="Calendar Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_session(session_id: str):
    creds = load_credentials(session_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Session not found. Reconnect Google.")
    return creds


# ---- Root + Auth ----

@app.get("/")
def root():
    return {"status": "ok", "service": "calendar-agent"}


@app.get("/auth/start")
def auth_start():
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env",
        )
    url, state = get_auth_url()
    return {"auth_url": url, "state": state}


@app.get("/auth/callback")
def auth_callback(code: str = Query(...), state: str = Query(...)):
    try:
        session_id = exchange_code(code, state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth exchange failed: {e}")
    return RedirectResponse(
        url=f"{config.FRONTEND_URL}/?session={session_id}",
        status_code=302,
    )


@app.get("/auth/check")
def auth_check(session_id: str = Query(...)):
    creds = _require_session(session_id)
    email = calendar_tools.get_user_email(creds)
    return {"ok": True, "email": email}


@app.post("/auth/logout")
def auth_logout(session_id: str = Query(...)):
    delete_session(session_id)
    return {"ok": True}


# ---- Calendar ----

@app.get("/calendar/upcoming")
def calendar_upcoming(
    session_id: str = Query(...),
    days_ahead: int = Query(7),
):
    creds = _require_session(session_id)
    now = datetime.now(timezone.utc)
    events = calendar_tools.list_events(
        creds,
        start=now,
        end=now + timedelta(days=days_ahead),
        max_results=100,
    )
    return {"ok": True, "events": events, "count": len(events)}


# ---- Chat ----

class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
def chat(req: ChatRequest):
    creds = _require_session(req.session_id)
    result = run_chat(req.session_id, req.message, creds)
    return result


# ---- RAG (preferences/notes upload) ----

class TextDocPayload(BaseModel):
    session_id: str
    source: str
    content: str


@app.post("/rag/upload-text")
def rag_upload_text(payload: TextDocPayload):
    """Index a piece of text as a personal note / preferences doc."""
    idx = get_index(payload.session_id)
    embed_fn = get_embed_fn()
    idx.add_document(source=payload.source, text=payload.content, embed_fn=embed_fn)
    return {"ok": True, "entries": len(idx.entries)}


@app.post("/rag/index-drive-file")
def rag_index_drive_file(session_id: str = Query(...), file_id: str = Query(...)):
    """Pull a Drive file by id and index it."""
    creds = _require_session(session_id)
    text = drive_tools.read_file_text(creds, file_id)
    if not text:
        raise HTTPException(status_code=400, detail="Could not read file content.")
    idx = get_index(session_id)
    embed_fn = get_embed_fn()
    idx.add_document(source=f"drive:{file_id}", text=text, embed_fn=embed_fn)
    return {"ok": True, "entries": len(idx.entries), "chars": len(text)}


@app.get("/rag/list")
def rag_list(session_id: str = Query(...)):
    idx = get_index(session_id)
    sources: dict = {}
    for e in idx.entries:
        sources[e["source"]] = sources.get(e["source"], 0) + 1
    return {"ok": True, "sources": sources, "total_chunks": len(idx.entries)}


@app.post("/rag/clear")
def rag_clear(session_id: str = Query(...)):
    idx = get_index(session_id)
    idx.clear()
    return {"ok": True}


# ---- Drive browse (for the user to pick docs to index) ----

@app.get("/drive/search")
def drive_search(session_id: str = Query(...), q: Optional[str] = Query(None)):
    creds = _require_session(session_id)
    files = drive_tools.list_files(creds, query=q)
    return {"ok": True, "files": files}


# ---- Meeting Prep Assistant ----

@app.get("/prep/{event_id}")
def prep_brief(event_id: str, session_id: str = Query(...)):
    creds = _require_session(session_id)
    result = generate_prep_brief(creds, session_id, event_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    return result


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=config.DEBUG,
    )
