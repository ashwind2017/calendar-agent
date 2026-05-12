"""Gmail draft creation for scheduling emails."""
import base64
from email.mime.text import MIMEText
from typing import Dict, Optional
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def _service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def create_draft(
    creds: Credentials,
    to: str,
    subject: str,
    body: str,
    from_email: Optional[str] = None,
) -> Dict[str, str]:
    """Create a Gmail draft. Returns draft id + url."""
    svc = _service(creds)

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    if from_email:
        message["from"] = from_email

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    draft = svc.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()

    draft_id = draft.get("id")
    return {
        "id": draft_id,
        "url": f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}",
        "to": to,
        "subject": subject,
    }


def create_multiple_drafts(
    creds: Credentials,
    drafts: list,
) -> list:
    """Batch draft creation. Each entry: {to, subject, body}."""
    results = []
    for d in drafts:
        try:
            r = create_draft(
                creds,
                to=d["to"],
                subject=d["subject"],
                body=d["body"],
            )
            results.append({"ok": True, **r})
        except Exception as e:
            results.append({"ok": False, "to": d.get("to"), "error": str(e)})
    return results
