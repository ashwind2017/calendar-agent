"""Meeting Prep Assistant: the wow extension.

For each upcoming meeting, compose:
 - Tool use: pull attendees + past meetings with those attendees
 - RAG: retrieve relevant notes about each attendee / meeting topic
 - Agent synthesis: structured prep brief
"""
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from dateutil import parser as dtparser

from config import config
import calendar_tools
from rag_service import get_index, get_embed_fn


def _anthropic_client():
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception:
        return None


def _openai_client():
    if not config.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=config.OPENAI_API_KEY)
    except Exception:
        return None


def _past_meetings_with(creds, attendees: List[str], days_back: int = 90) -> List[Dict]:
    """Find past meetings where any of these attendees were present."""
    now = datetime.now(timezone.utc)
    events = calendar_tools.list_events(
        creds,
        start=now - timedelta(days=days_back),
        end=now,
        max_results=500,
    )
    target = set(a.lower() for a in attendees)
    past = []
    for ev in events:
        ev_emails = {a["email"].lower() for a in ev.get("attendees", []) if a.get("email")}
        if ev_emails & target:
            past.append(ev)
    return past


def _summarize_brief_llm(meeting: Dict, past: List[Dict], rag_chunks: List[Dict]) -> str:
    """Ask the LLM to synthesize the prep brief."""
    system = (
        "You are a meeting prep assistant for a busy professional. Given an upcoming meeting, "
        "its attendees, recent past meetings with those attendees, and personal notes retrieved from "
        "the user's documents, produce a concise actionable prep brief.\n\n"
        "Format with these markdown headers:\n"
        "## Who is in this meeting\n"
        "## What's the context\n"
        "## What I should know going in\n"
        "## Suggested agenda points\n"
        "## Open questions to consider\n\n"
        "Rules:\n"
        "- Be specific. Reference real past meeting titles, dates, and any personal notes by source.\n"
        "- Skip sections that have no real content rather than padding (omit the header entirely).\n"
        "- Quote snippets from personal notes inline when relevant: 'per your notes, ...'.\n"
        "- If there are no past meetings with these attendees and no notes, say so plainly and "
        "suggest a discovery-oriented agenda.\n"
        "- Keep the whole brief under ~300 words.\n"
        "- Write naturally, like a smart colleague handed you context before your meeting."
    )

    user_payload = {
        "upcoming_meeting": {
            "title": meeting.get("summary"),
            "start": meeting.get("start"),
            "end": meeting.get("end"),
            "attendees": [a.get("email") for a in meeting.get("attendees", [])],
            "description": meeting.get("description", ""),
            "location": meeting.get("location"),
        },
        "past_meetings": [
            {
                "title": p.get("summary"),
                "start": p.get("start"),
                "attendees": [a.get("email") for a in p.get("attendees", [])],
            } for p in past[:10]
        ],
        "personal_notes": [
            {"source": c.get("source"), "text": c.get("chunk")[:500]}
            for c in rag_chunks[:5]
        ],
    }

    client = _anthropic_client()
    if client:
        resp = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=900,
            system=system,
            messages=[{"role": "user", "content": json.dumps(user_payload, default=str)}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

    client = _openai_client()
    if client:
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            max_tokens=900,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
        )
        return resp.choices[0].message.content.strip()

    return "(No LLM configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.)"


def list_upcoming_with_prep_readiness(
    creds,
    days_ahead: int = 7,
) -> List[Dict[str, Any]]:
    """List upcoming meetings with a readiness indicator for prep briefs.

    A meeting is 'prep-eligible' if it has attendees beyond the user. Solo events
    (focus blocks, all-day events) generally don't need a prep brief.
    """
    now = datetime.now(timezone.utc)
    upcoming = calendar_tools.list_events(
        creds,
        start=now,
        end=now + timedelta(days=days_ahead),
        max_results=100,
    )
    user_email = calendar_tools.get_user_email(creds) or ""
    out = []
    for ev in upcoming:
        attendees = [a.get("email") for a in ev.get("attendees", []) if a.get("email") and a.get("email") != user_email]
        out.append({
            "id": ev.get("id"),
            "summary": ev.get("summary"),
            "start": ev.get("start"),
            "end": ev.get("end"),
            "attendee_count": len(attendees),
            "prep_eligible": len(attendees) > 0,
        })
    return out


def generate_prep_brief(
    creds,
    session_id: str,
    event_id: str,
) -> Dict[str, Any]:
    """Build a prep brief for a specific upcoming meeting."""
    # Find the event
    now = datetime.now(timezone.utc)
    upcoming = calendar_tools.list_events(
        creds,
        start=now - timedelta(days=1),
        end=now + timedelta(days=14),
        max_results=100,
    )
    meeting = next((e for e in upcoming if e["id"] == event_id), None)
    if not meeting:
        return {"ok": False, "error": "Event not found in the upcoming window."}

    attendees = [a["email"] for a in meeting.get("attendees", []) if a.get("email")]

    past = _past_meetings_with(creds, attendees)

    # RAG retrieval keyed by meeting context
    idx = get_index(session_id)
    rag_query = " ".join([
        meeting.get("summary") or "",
        " ".join(attendees),
        meeting.get("description") or "",
    ]).strip()
    rag_chunks = idx.retrieve(rag_query, k=5, embed_fn=get_embed_fn()) if rag_query else []

    brief_text = _summarize_brief_llm(meeting, past, rag_chunks)

    return {
        "ok": True,
        "meeting": {
            "id": meeting["id"],
            "summary": meeting.get("summary"),
            "start": meeting.get("start"),
            "end": meeting.get("end"),
            "attendees": attendees,
            "html_link": meeting.get("html_link"),
        },
        "brief_markdown": brief_text,
        "data_sources": {
            "past_meetings_count": len(past),
            "rag_chunks_used": len(rag_chunks),
            "attendees_resolved": len(attendees),
        },
    }
