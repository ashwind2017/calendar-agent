"""LLM agent loop with tool use over Calendar/Gmail and RAG over Drive.

Primary provider: Anthropic (Claude). Fallback: OpenAI.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dateutil import parser as dtparser
import pytz

from config import config
from memory_service import memory
from rag_service import get_index, get_embed_fn
import calendar_tools
import gmail_tools


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
- When drafting emails, write naturally (no boilerplate). Use the user's calendar context. Keep emails short.
- When the user asks about their time usage, call analyze_meeting_time and report concrete numbers with recommendations.
- Before scheduling decisions, call retrieve_personal_context to check if the user has stated preferences.
- If you don't have enough info, ask the user a brief clarifying question.

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
