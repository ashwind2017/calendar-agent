"""Google OAuth flow + token storage."""
import os
import json
import uuid
from typing import Optional
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from config import config


def _ensure_token_dir():
    os.makedirs(config.TOKEN_DIR, exist_ok=True)


def _token_path(session_id: str) -> str:
    return os.path.join(config.TOKEN_DIR, f"{session_id}.json")


def _state_path(state: str) -> str:
    """Where we stash transient OAuth state (code_verifier) between auth URL gen and token exchange."""
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, f"oauth_state_{state}.json")


def build_flow(state: Optional[str] = None) -> Flow:
    """Build a Flow with our client config and scopes."""
    client_config = {
        "web": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [config.GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=config.GOOGLE_SCOPES,
        state=state,
    )
    flow.redirect_uri = config.GOOGLE_REDIRECT_URI
    return flow


def get_auth_url() -> tuple[str, str]:
    """Return (auth_url, state) for the front end to redirect to."""
    state = str(uuid.uuid4())
    flow = build_flow(state=state)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    # PKCE: if the flow auto-generated a code_verifier, persist it so we can
    # send it back to Google during the token exchange. Otherwise Google
    # rejects the exchange with "invalid_grant: Missing code verifier."
    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        with open(_state_path(state), "w") as f:
            json.dump({"code_verifier": code_verifier}, f)
    return auth_url, state


def exchange_code(code: str, state: str) -> str:
    """Exchange auth code for tokens, store them, return session_id."""
    flow = build_flow(state=state)

    # Restore the code_verifier from the auth-URL step (PKCE round-trip)
    state_file = _state_path(state)
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                saved = json.load(f)
            verifier = saved.get("code_verifier")
            if verifier:
                flow.code_verifier = verifier
        finally:
            try:
                os.remove(state_file)
            except OSError:
                pass

    flow.fetch_token(code=code)
    creds = flow.credentials

    session_id = str(uuid.uuid4())
    _ensure_token_dir()
    with open(_token_path(session_id), "w") as f:
        json.dump(
            {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": creds.scopes,
            },
            f,
        )
    return session_id


def load_credentials(session_id: str) -> Optional[Credentials]:
    """Load creds from disk for a session, refreshing if needed."""
    path = _token_path(session_id)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)

    creds = Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(path, "w") as f:
            json.dump(
                {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": creds.scopes,
                },
                f,
            )
    return creds


def delete_session(session_id: str):
    path = _token_path(session_id)
    if os.path.exists(path):
        os.remove(path)
