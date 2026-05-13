"""Google Calendar API wrappers used by the agent as tools."""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from config import config


def _service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_events(
    creds: Credentials,
    calendar_id: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """List events in a window. Defaults to next 7 days."""
    svc = _service(creds)
    now = datetime.now(timezone.utc)
    time_min = (start or now).isoformat()
    time_max = (end or (now + timedelta(days=7))).isoformat()

    result = svc.events().list(
        calendarId=calendar_id or config.CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=max_results,
    ).execute()

    events = []
    for ev in result.get("items", []):
        events.append({
            "id": ev.get("id"),
            "summary": ev.get("summary", "(no title)"),
            "description": ev.get("description", ""),
            "start": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"),
            "end": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
            "attendees": [
                {"email": a.get("email"), "responseStatus": a.get("responseStatus")}
                for a in ev.get("attendees", [])
            ],
            "organizer": ev.get("organizer", {}).get("email"),
            "location": ev.get("location"),
            "hangoutLink": ev.get("hangoutLink"),
            "html_link": ev.get("htmlLink"),
            "recurring_event_id": ev.get("recurringEventId"),
        })
    return events


def get_freebusy(
    creds: Credentials,
    emails: List[str],
    start: datetime,
    end: datetime,
) -> Dict[str, List[Dict[str, str]]]:
    """Query free/busy for multiple calendars."""
    svc = _service(creds)
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": email} for email in emails],
    }
    result = svc.freebusy().query(body=body).execute()
    out = {}
    for email, info in result.get("calendars", {}).items():
        out[email] = info.get("busy", [])
    return out


def find_free_slots(
    creds: Credentials,
    emails: List[str],
    start: datetime,
    end: datetime,
    duration_minutes: int = 30,
    working_hours: tuple = (9, 17),
    user_timezone: str = "America/New_York",
) -> List[Dict[str, str]]:
    """Find slots where all attendees are free, within working hours.

    Working hours are interpreted in user_timezone.
    Returns list of {start: iso, end: iso} dicts.
    """
    import pytz
    try:
        tz = pytz.timezone(user_timezone)
    except Exception:
        tz = pytz.UTC

    busy_by_email = get_freebusy(creds, emails, start, end)

    # Flatten all busy windows
    all_busy = []
    for email, busy_windows in busy_by_email.items():
        for w in busy_windows:
            all_busy.append((
                datetime.fromisoformat(w["start"].replace("Z", "+00:00")),
                datetime.fromisoformat(w["end"].replace("Z", "+00:00")),
            ))
    all_busy.sort()

    # Walk through the time window in increments looking for free slots
    duration = timedelta(minutes=duration_minutes)
    slot_step = timedelta(minutes=15)
    free_slots = []
    cursor = start

    while cursor + duration <= end:
        # Working hours filter in user's local timezone (not UTC)
        local_cursor = cursor.astimezone(tz) if cursor.tzinfo else tz.localize(cursor)
        local_hour = local_cursor.hour
        # Skip weekends
        if local_cursor.weekday() >= 5:
            cursor += slot_step
            continue
        if working_hours[0] <= local_hour < working_hours[1]:
            slot_end = cursor + duration
            is_free = True
            for busy_start, busy_end in all_busy:
                if cursor < busy_end and slot_end > busy_start:
                    is_free = False
                    break
            if is_free:
                free_slots.append({
                    "start": cursor.isoformat(),
                    "end": slot_end.isoformat(),
                })
                if len(free_slots) >= 10:
                    break
        cursor += slot_step

    return free_slots


def create_event(
    creds: Credentials,
    summary: str,
    start: datetime,
    end: datetime,
    attendees: List[str] = None,
    description: str = "",
    location: str = "",
    calendar_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a calendar event."""
    svc = _service(creds)
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    if location:
        body["location"] = location

    result = svc.events().insert(
        calendarId=calendar_id or config.CALENDAR_ID,
        body=body,
        sendUpdates="none",
    ).execute()
    return {
        "id": result.get("id"),
        "html_link": result.get("htmlLink"),
        "summary": result.get("summary"),
        "start": result.get("start", {}).get("dateTime"),
        "end": result.get("end", {}).get("dateTime"),
    }


def get_user_email(creds: Credentials) -> Optional[str]:
    """Get the authenticated user's email."""
    try:
        svc = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = svc.userinfo().get().execute()
        return info.get("email")
    except Exception:
        return None
