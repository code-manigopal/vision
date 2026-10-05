"""Google Drive, read-only: the text files and Google Docs in one folder.

Uses the channel's Google sign-in (oauth provider "youtube", which carries the drive.readonly scope); the Google app
needs "Google Drive API" enabled.
"""

from __future__ import annotations

import httpx

API = "https://www.googleapis.com/drive/v3/files"
DOC, FOLDER = "application/vnd.google-apps.document", "application/vnd.google-apps.folder"


class DriveError(Exception):
    pass


async def _get(c: httpx.AsyncClient, token: str, url: str, **params) -> httpx.Response:
    r = await c.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, follow_redirects=True)
    if r.status_code != 200:
        try:
            why = r.json()["error"]["message"]
        except Exception:
            why = r.text
        raise DriveError(f"Google Drive said {r.status_code}: {why[:160]}")
    return r


async def folder_id(c: httpx.AsyncClient, token: str, name: str) -> str | None:
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    r = await _get(c, token, API, q=f"name = '{safe}' and mimeType = '{FOLDER}' and trashed = false", fields="files(id)", pageSize=1)
    files = r.json().get("files", [])
    return files[0]["id"] if files else None


async def texts(c: httpx.AsyncClient, token: str, folder: str) -> list[dict]:
    """[{id, name, mimeType}] for the Google Docs and plain-text files directly inside the folder."""
    r = await _get(c, token, API, q=f"'{folder}' in parents and trashed = false and (mimeType = '{DOC}' or mimeType = 'text/plain')",
                   fields="files(id,name,mimeType)", pageSize=100, orderBy="createdTime")
    return r.json().get("files", [])


async def read(c: httpx.AsyncClient, token: str, f: dict) -> str:
    if f["mimeType"] == DOC:
        r = await _get(c, token, f"{API}/{f['id']}/export", mimeType="text/plain")
    else:
        r = await _get(c, token, f"{API}/{f['id']}", alt="media")
    return r.content.decode("utf-8", errors="ignore").lstrip("\ufeff").replace("\r\n", "\n").strip()
