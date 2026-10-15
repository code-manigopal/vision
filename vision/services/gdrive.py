"""Google Drive: reading the text files and Google Docs in one folder, and backing up finished videos.

Reading uses the channel's Google sign-in (oauth provider "youtube", which carries the drive.readonly scope). The backups
use their own sign-in (provider "gdrive", scope drive.file: only files and folders VISION created are visible to it).
The Google app needs "Google Drive API" enabled.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DOC, FOLDER = "application/vnd.google-apps.document", "application/vnd.google-apps.folder"


class DriveError(Exception):
    pass


class DriveFull(DriveError):
    """The Drive's storage is used up: nothing more can be backed up until space is freed."""


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


def _why(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"]
    except Exception:
        return r.text[:160]


async def ensure_folder(c: httpx.AsyncClient, token: str, name: str, parent: str | None = None) -> str:
    """The id of folder `name` (inside `parent`), made if it isn't there."""
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = f"name = '{safe}' and mimeType = '{FOLDER}' and trashed = false" + (f" and '{parent}' in parents" if parent else "")
    found = (await _get(c, token, API, q=q, fields="files(id)", pageSize=1)).json().get("files", [])
    if found:
        return found[0]["id"]
    r = await c.post(API, json={"name": name, "mimeType": FOLDER, **({"parents": [parent]} if parent else {})},
                     params={"fields": "id"}, headers={"Authorization": f"Bearer {token}"})
    if r.status_code not in (200, 201):
        raise DriveError(f"Google Drive said {r.status_code}: {_why(r)}")
    return r.json()["id"]


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


async def _stream(path: Path):
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            yield chunk


async def upload(c: httpx.AsyncClient, token: str, path: Path, name: str, parent: str, mime: str) -> dict:
    """Uploads `path` as `name` into `parent` (resumable, streamed) and checks Drive's copy has the same size and MD5.
    A file of that name with the same MD5 already there is reused. Returns {id, name, size}."""
    want, size = md5(path), path.stat().st_size
    h = {"Authorization": f"Bearer {token}"}
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    same = (await _get(c, token, API, q=f"name = '{safe}' and '{parent}' in parents and trashed = false",
                       fields="files(id,size,md5Checksum)", pageSize=5)).json().get("files", [])
    for f in same:
        if f.get("md5Checksum") == want:
            return {"id": f["id"], "name": name, "size": size}
    r = await c.post(UPLOAD, params={"uploadType": "resumable"}, content=json.dumps({"name": name, "parents": [parent]}),
                     headers={**h, "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)})
    if r.status_code == 403 and "storageQuotaExceeded" in r.text:
        raise DriveFull("the Drive's storage is full")
    if r.status_code != 200 or "location" not in r.headers:
        raise DriveError(f"Google Drive said {r.status_code}: {_why(r)}")
    r = await c.put(r.headers["location"], content=_stream(path), headers={"Content-Length": str(size), "Content-Type": mime}, timeout=None)
    if r.status_code == 403 and "storageQuotaExceeded" in r.text:
        raise DriveFull("the Drive's storage is full")
    if r.status_code not in (200, 201):
        raise DriveError(f"Google Drive said {r.status_code} to the upload: {_why(r)}")
    fid = r.json()["id"]
    got = (await _get(c, token, f"{API}/{fid}", fields="size,md5Checksum")).json()
    if int(got.get("size") or -1) != size or got.get("md5Checksum") != want:
        raise DriveError(f"the Drive copy of {name} does not match the file ({got.get('size')} bytes)")
    return {"id": fid, "name": name, "size": size}


async def trash(c: httpx.AsyncClient, token: str, fid: str) -> bool:
    """Moves a file VISION made to the Drive's trash (Drive empties it after 30 days). False when it is already gone."""
    r = await c.patch(f"{API}/{fid}", json={"trashed": True}, params={"fields": "id"}, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 404:
        return False
    if r.status_code != 200:
        raise DriveError(f"Google Drive said {r.status_code}: {_why(r)}")
    return True
