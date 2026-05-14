"""LLM agent loop with tool use over Calendar/Gmail and RAG over Drive.

Primary provider: Anthropic (Claude). Fallback: OpenAI.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dateutil import parser as dtparser
import pytz

from config import config
from memory_service import memory
from rag_service import get_index, get_embed_fn
import calendar_tools
import gmail_tools

# Tool latency tracking. Imported lazily to avoid a hard dependency in case
# middleware.py is ever stripped out for a slim build.
try:
    from middleware import record_tool_call as _record_tool_call
except Exception:
    def _record_tool_call(tool_name: str, duration_ms: float) -> None:
        return None


# ---- Tool schemas (Anthropic + OpenAI shape) ----

TOOLS = [
    {
        "name": "list_events",
        "description": "List events on the user's calendar in a time window. Defaults to next 7 days. Use this to understand the user's schedule before answering questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_iso": {"type": "string", "description": "Start of window in ISO 8601 (e.g., 2026-05-12T00:00:00Z). Optional."},
                "end_iso": {"type": "string", "description": "End of window in ISO 8601. Optional."},
                "max_results": {"type": "integer", "description": "Max events to return. Default 50."},
            },
        },
    },
    {
        "name": "find_free_slots",
        "description": "Find time slots where the user (and optionally other attendees) are free. Returns up to 10 candidate slots.",
        "input_schema": {
            "type": "object",
            "properties": {
                "emails": {"type": "array", "items": {"type": "string"}, "description": "Other attendee emails (in addition to the user). Use [] for solo time."},
                "start_iso": {"type": "string", "description": "Earliest acceptable start in ISO 8601."},
                "end_iso": {"type": "string", "description": "Latest acceptable end in ISO 8601."},
                "duration_minutes": {"type": "integer", "description": "Meeting length in minutes."},
                "morning_protected": {"type": "boolean", "description": "If true, only suggest slots in the afternoon. Default false."},
                "timezone": {"type": "string", "description": "IANA timezone (e.g., America/New_York) for working hours filter. Default America/New_York."},
            },
            "required": ["start_iso", "end_iso", "duration_minutes"],
        },
    },
    {
        "name": "propose_calendar_event",
        "description": "Propose a calendar event for the user to review and confirm in the UI. This does NOT create the event. It returns a structured proposal that the frontend renders as a confirmation card. ALWAYS use this when the user wants to schedule something; never call create_calendar_event directly. The user must click Confirm in the UI before any real event is created.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start_iso": {"type": "string", "description": "Start time in ISO 8601 with timezone."},
                "end_iso": {"type": "string", "description": "End time in ISO 8601 with timezone."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails."},
                "description": {"type": "string", "description": "Event description / agenda."},
                "location": {"type": "string", "description": "Location or video link."},
            },
            "required": ["summary", "start_iso", "end_iso"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a calendar event. Only call after explicit user confirmation via propose_calendar_event flow. Do not call directly when a user asks to schedule something; use propose_calendar_event first so the UI can show a confirmation card.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start_iso": {"type": "string", "description": "Start time in ISO 8601 with timezone."},
                "end_iso": {"type": "string", "description": "End time in ISO 8601 with timezone."},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails."},
                "description": {"type": "string", "description": "Event description / agenda."},
                "location": {"type": "string", "description": "Location or video link."},
            },
            "required": ["summary", "start_iso", "end_iso"],
        },
    },
    {
        "name": "create_email_draft",
        "description": "Create a Gmail draft. Use this when the user wants to send scheduling emails. Returns draft id + URL the user can click to review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email."},
                "subject": {"type": "string", "description": "Email subject."},
                "body": {"type": "string", "description": "Email body in plain text."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "analyze_meeting_time",
        "description": "Analyze how the user is spending time in meetings over a window. Returns total meeting hours, recurring meeting count, and a breakdown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {"type": "integer", "description": "How many days of history to analyze. Default 14."},
            },
        },
    },
    {
        "name": "retrieve_personal_context",
        "description": "Retrieve relevant chunks from the user's indexed personal preferences and notes. Use this when scheduling decisions might depend on user-specific preferences or context about a person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up (e.g., 'scheduling preferences', 'notes about Sarah')."},
                "k": {"type": "integer", "description": "Number of chunks to return. Default 5."},
            },
            "required": ["query"],
        },
    },
]


def _system_prompt(user_email: Optional[str]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    return f"""You are a helpful AI agent embedded in the user's calendar. The current UTC time is {now}.

The authenticated user is {user_email or "unknown"}.

You have access to tools for the user's Google Calendar, Gmail, and a personal-context retrieval system (RAG over their Drive docs).

Behavior rules:
- Always ground answers in real data. Call tools to fetch actual calendar/email/context. Do not invent times, attendees, or facts.
- For multi-person scheduling, use find_free_slots with the attendee list, then propose options.
- When the user wants to schedule, ALWAYS use propose_calendar_event first, never create_calendar_event directly. The user must confirm via UI before any event is created. After calling propose_calendar_event, briefly tell the user what you proposed and that they can confirm it in the card.
- When drafting emails, write naturally (no boilerplate). Use the user's calendar context. Keep emails short.
- When the user asks about their time usage, call analyze_meeting_time and report concrete numbers with recommendations.
- Before scheduling decisions that depend on preferences (protected hours, meeting style, notes on a person), call retrieve_personal_context.
- If you don't have enough info, ask the user a brief clarifying question.

When NOT to call a tool:
- Skip retrieve_personal_context for purely factual calendar questions (e.g., "what's on my calendar tomorrow"). Don't burn tokens on RAG when the user just wants facts.
- Do not call create_email_draft unless the user explicitly asked for an email or notification to be sent.
- Do not call propose_calendar_event for informational questions (e.g., "when am I free next week"). Only propose when the user wants something on the calendar.
- Do not call create_calendar_event directly. Always go through propose_calendar_event first.

Date and time handling:
- The user's local timezone is America/New_York (US Eastern). Interpret ALL relative times ("morning", "afternoon", "evening", "2pm", "next Tuesday at 3") in Eastern time unless the user explicitly specifies another timezone.
- All ISO 8601 timestamps you pass to tools must include the Eastern offset: -04:00 during EDT (March–November) or -05:00 during EST (November–March). Do NOT default to Pacific or UTC offsets.
- When you describe scheduled times back to the user in plain English, use Eastern time wall-clock values (e.g., "2:00 PM" means 2 PM Eastern, not 2 PM in some other zone).
- When the user gives a relative date ("tomorrow", "next Tuesday", "this Friday"), compute the absolute date from the current UTC time above. "Next Tuesday" means the Tuesday of the following week if today is already past Tuesday; otherwise the upcoming Tuesday. Default to the soonest reasonable interpretation.
- Only ask for clarification when the reference is genuinely ambiguous (e.g., "later" with no anchor).

Example flows:

User: "Schedule a 1:1 with sarah@x.com and joe@y.com next week, mornings protected."
  1. retrieve_personal_context(query="scheduling preferences morning protected 1:1")
  2. find_free_slots(emails=["sarah@x.com","joe@y.com"], start_iso=<next Mon>, end_iso=<next Fri>, duration_minutes=30, morning_protected=true)
  3. propose_calendar_event with the best slot, summary "1:1 Sarah / Joe", attendees both.
  4. create_email_draft to each attendee only if the user asked you to notify them.

User: "How can I cut down on meetings?"
  1. analyze_meeting_time(days_back=14)
  2. Inspect the breakdown for recurring meetings and large buckets.
  3. Respond with concrete recommendations (which recurring slot to drop, which day to protect) grounded in the numbers. No tool calls beyond step 1 unless the user asks to act.

User: "What's on my calendar tomorrow?"
  1. list_events with tomorrow's start_iso and end_iso. No RAG, no proposal, no email.

Be concise. Lead with the answer, then back it up with the data you used.
"""


# ---- Tool dispatch ----

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return dtparser.isoparse(s)
    except Exception:
        return None


def execute_tool(tool_name: str, tool_input: Dict[str, Any], creds, session_id: str) -> Dict[str, Any]:
    """Run a single tool call. Returns a JSON-serializable result."""
    _tool_start = time.perf_counter()
    try:
        return _execute_tool_dispatch(tool_name, tool_input, creds, session_id)
    finally:
        _record_tool_call(tool_name, (time.perf_counter() - _tool_start) * 1000)


def _execute_tool_dispatch(tool_name: str, tool_input: Dict[str, Any], creds, session_id: str) -> Dict[str, Any]:
    try:
        if tool_name == "list_events":
            start = _parse_iso(tool_input.get("start_iso"))
            end = _parse_iso(tool_input.get("end_iso"))
            events = calendar_tools.list_events(
                creds,
                start=start,
                end=end,
                max_results=tool_input.get("max_results", 50),
            )
            return {"ok": True, "events": events, "count": len(events)}

        if tool_name == "find_free_slots":
            start = _parse_iso(tool_input.get("start_iso"))
            end = _parse_iso(tool_input.get("end_iso"))
            if not start or not end:
                return {"ok": False, "error": "Missing start_iso or end_iso"}
            duration = tool_input.get("duration_minutes", 30)
            emails = tool_input.get("emails", []) or []
            user_email = calendar_tools.get_user_email(creds)
            if user_email and user_email not in emails:
                emails = [user_email] + emails
            working_hours = (12, 18) if tool_input.get("morning_protected") else (9, 17)
            user_tz = tool_input.get("timezone") or "America/New_York"
            slots = calendar_tools.find_free_slots(
                creds,
                emails=emails,
                start=start,
                end=end,
                duration_minutes=duration,
                working_hours=working_hours,
                user_timezone=user_tz,
            )
            return {"ok": True, "slots": slots, "count": len(slots)}

        if tool_name == "propose_calendar_event":
            start = _parse_iso(tool_input.get("start_iso"))
            end = _parse_iso(tool_input.get("end_iso"))
            if not start or not end:
                return {"ok": False, "error": "Missing or invalid start_iso/end_iso"}
            proposal = {
                "summary": tool_input.get("summary", ""),
                "start_iso": tool_input.get("start_iso"),
                "end_iso": tool_input.get("end_iso"),
                "attendees": tool_input.get("attendees") or [],
                "description": tool_input.get("description") or "",
                "location": tool_input.get("location") or "",
            }
            return {"ok": True, "proposal": proposal}

        if tool_name == "create_calendar_event":
            start = _parse_iso(tool_input.get("start_iso"))
            end = _parse_iso(tool_input.get("end_iso"))
            if not start or not end:
                return {"ok": False, "error": "Missing or invalid start_iso/end_iso"}
            event = calendar_tools.create_event(
                creds,
                summary=tool_input["summary"],
                start=start,
                end=end,
                attendees=tool_input.get("attendees") or [],
                description=tool_input.get("description") or "",
                location=tool_input.get("location") or "",
            )
            return {"ok": True, "event": event}

        if tool_name == "create_email_draft":
            draft = gmail_tools.create_draft(
                creds,
                to=tool_input["to"],
                subject=tool_input["subject"],
                body=tool_input["body"],
            )
            return {"ok": True, "draft": draft}

        if tool_name == "analyze_meeting_time":
            days_back = tool_input.get("days_back", 14)
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=days_back)
            events = calendar_tools.list_events(creds, start=start, end=now, max_results=500)

            total_minutes = 0
            recurring_count = 0
            categories: Dict[str, int] = {}
            for ev in events:
                try:
                    s = dtparser.isoparse(ev["start"])
                    e = dtparser.isoparse(ev["end"])
                    minutes = max(0, int((e - s).total_seconds() / 60))
                    total_minutes += minutes
                    if ev.get("recurring_event_id"):
                        recurring_count += 1
                    title = ev.get("summary") or "(untitled)"
                    bucket = "1:1" if "1:1" in title or "/" in title else ("standup" if "standup" in title.lower() else "meeting")
                    categories[bucket] = categories.get(bucket, 0) + minutes
                except Exception:
                    continue

            return {
                "ok": True,
                "window_days": days_back,
                "total_hours": round(total_minutes / 60, 1),
                "meeting_count": len(events),
                "recurring_meeting_count": recurring_count,
                "breakdown_minutes": categories,
            }

        if tool_name == "retrieve_personal_context":
            embed_fn = get_embed_fn()
            idx = get_index(session_id)
            chunks = idx.retrieve(
                query=tool_input["query"],
                k=tool_input.get("k", 5),
                embed_fn=embed_fn,
            )
            return {"ok": True, "chunks": chunks, "count": len(chunks)}

        return {"ok": False, "error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---- Anthropic agent loop ----

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


def _build_history(session_id: str) -> List[Dict[str, Any]]:
    """Convert stored turns into the Anthropic messages shape."""
    turns = memory.get_turns(session_id, limit=30)
    messages = []
    for t in turns:
        role = t["role"]
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": t["content"]})
    return messages


def run_chat(
    session_id: str,
    user_message: str,
    creds,
) -> Dict[str, Any]:
    """Run one full chat turn with tool use. Returns final assistant message + tool trace."""
    user_email = calendar_tools.get_user_email(creds)
    memory.add_turn(session_id, "user", user_message)

    history = _build_history(session_id)
    system = _system_prompt(user_email)

    tool_trace = []
    final_text = ""

    client = _anthropic_client()
    if client:
        # Anthropic tool-use loop with fallback to OpenAI on API failure
        messages = history.copy()
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": user_message})

        anthropic_failed = False
        for _ in range(8):  # safety cap on tool-use rounds
            try:
                resp = client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=1500,
                    system=system,
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as e:
                print(f"Anthropic call failed: {type(e).__name__}: {e}")
                tool_trace.append({"tool": "_anthropic_error", "input": {}, "result_preview": str(e)[:200]})
                anthropic_failed = True
                break
            stop_reason = resp.stop_reason

            # Collect any text and tool_use blocks
            assistant_blocks = []
            tool_uses = []
            text_parts = []
            for block in resp.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": assistant_blocks})

            if not tool_uses:
                final_text = "\n".join(text_parts).strip()
                break

            # Execute tools
            tool_results_block = []
            for tu in tool_uses:
                result = execute_tool(tu.name, tu.input, creds, session_id)
                tool_trace.append({
                    "tool": tu.name,
                    "input": tu.input,
                    "result_preview": _preview(result),
                })
                tool_results_block.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result)[:8000],
                })

            messages.append({"role": "user", "content": tool_results_block})

            if stop_reason != "tool_use":
                final_text = "\n".join(text_parts).strip()
                break

        if not final_text and not anthropic_failed:
            final_text = "I worked through your request but didn't produce a final summary. Try rephrasing."

        # If Anthropic failed mid-loop, fall over to OpenAI if available
        if anthropic_failed:
            oa_client = _openai_client()
            if oa_client:
                final_text = _run_openai_loop(oa_client, system, user_message, history, creds, session_id, tool_trace)
            else:
                final_text = "Anthropic provider failed and no OpenAI fallback configured."

    else:
        # OpenAI as primary (no Anthropic key)
        client = _openai_client()
        if not client:
            final_text = "No LLM configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
        else:
            final_text = _run_openai_loop(client, system, user_message, history, creds, session_id, tool_trace)

    memory.add_turn(session_id, "assistant", final_text, tool_calls=tool_trace)
    return {
        "ok": True,
        "answer": final_text,
        "tool_trace": tool_trace,
    }


def _run_openai_loop(client, system, user_message, history, creds, session_id, tool_trace):
    """OpenAI fallback path."""
    openai_tools = [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    } for t in TOOLS]

    messages = [{"role": "system", "content": system}] + history
    if not messages or messages[-1].get("role") != "user":
        messages.append({"role": "user", "content": user_message})

    for _ in range(8):
        resp = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            tools=openai_tools,
            messages=messages,
            max_tokens=1500,
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    } for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                result = execute_tool(tc.function.name, args, creds, session_id)
                tool_trace.append({
                    "tool": tc.function.name,
                    "input": args,
                    "result_preview": _preview(result),
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result)[:8000],
                })
        else:
            return msg.content or ""
    return "I worked through your request but ran out of tool-use rounds."


def _preview(d: Dict[str, Any]) -> str:
    s = json.dumps(d, default=str)
    return s if len(s) < 400 else s[:400] + "..."
