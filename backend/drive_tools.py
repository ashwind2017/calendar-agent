"""Google Drive read access for the RAG layer."""
import io
from typing import List, Dict, Optional
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials


def _service(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# Mime types we can read as plain text after export
EXPORTABLE_MIMES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def list_files(
    creds: Credentials,
    query: Optional[str] = None,
    folder_id: Optional[str] = None,
    max_results: int = 50,
) -> List[Dict]:
    """List files in Drive (optionally within a folder, optionally matching query)."""
    svc = _service(creds)
    q_parts = ["trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    if query:
        q_parts.append(f"name contains '{query}'")
    q = " and ".join(q_parts)

    result = svc.files().list(
        q=q,
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
    ).execute()
    return result.get("files", [])


def read_file_text(creds: Credentials, file_id: str) -> str:
    """Read a file's content as plain text. Handles Google Docs, Sheets, Slides, plus plain text/PDF."""
    svc = _service(creds)

    meta = svc.files().get(fileId=file_id, fields="mimeType, name").execute()
    mime = meta.get("mimeType", "")

    buf = io.BytesIO()
    if mime in EXPORTABLE_MIMES:
        request = svc.files().export_media(fileId=file_id, mimeType=EXPORTABLE_MIMES[mime])
    else:
        request = svc.files().get_media(fileId=file_id)

    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)

    try:
        return buf.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def list_folder_files(creds: Credentials, folder_id: str) -> List[Dict]:
    """List all files in a specific folder."""
    return list_files(creds, folder_id=folder_id, max_results=200)
