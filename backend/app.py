"""FastAPI entry point for the Calendar Agent backend."""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from config import config
from auth import get_auth_url, exchange_code, load_credentials, delete_session


app = FastAPI(title="Calendar Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "calendar-agent"}


@app.get("/auth/start")
def auth_start():
    """Kick off OAuth flow. Returns the URL the client should redirect to."""
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth credentials not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env",
        )
    url, state = get_auth_url()
    return {"auth_url": url, "state": state}


@app.get("/auth/callback")
def auth_callback(code: str = Query(...), state: str = Query(...)):
    """Google redirects here after consent. Exchange code, then redirect to frontend."""
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
    """Verify a session is still valid."""
    creds = load_credentials(session_id)
    if not creds:
        raise HTTPException(status_code=401, detail="Session not found or expired")
    return {"ok": True, "valid": True}


@app.post("/auth/logout")
def auth_logout(session_id: str = Query(...)):
    delete_session(session_id)
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=config.DEBUG,
    )
