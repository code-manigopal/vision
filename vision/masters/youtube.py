"""YouTube Manager (live): one Director per channel, each with its own crew.

    YouTube Manager -> <Channel> Director -> Story Scout -> Story Writer -> Screenplay Writer
        -> Keyword Generator + Voice Artist -> Footage Collector -> Footage Generator -> Editor
        -> Uploader (unlisted) -> Analytics Manager (reports to the Director) -> YOU, on YouTube

- Stories: Reddit's official API (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET, asleep until the keys exist) and .txt files in
  inbox/confessions/<channel id>/. Text files and Google Docs in the channel's Drive folder (`drive_folder`) are copied
  into that inbox first. Every story keeps its source URL. Quora is not used (no API, scraping blocked).
- A story is screened (rules, then the model), rewritten in the third person with names and places removed, and
  split into timed beats for a 1-2 minute Short that ends on the channel's subscribe line.
- Footage: Pexels / Pixabay (free stock), one clip or photo per beat; an online AI provider can fill the gaps
  (services/genmedia.py, off until a channel names one).
- The finished Short is a file in data/shorts/<channel id>/... and is uploaded as UNLISTED (Mani's choice: no approval
  before the upload). VISION sends the YouTube Studio link; making it public or deleting it is done by hand on YouTube.
  Sign-in: /auth/youtube/login?account=youtube-<channel id> (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET, YouTube Data API v3).
- The log (kv `yt_videos`) keeps source, script, screenplay, keywords, footage credits and the file for every Short.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from ..agents import AgentResult, Director, Stage, SubAgent
from ..config import ROOT
from ..services import gdrive, genmedia, oauth, reddit, stock_video
from . import shorts_edit

SEEN, LOG, DRIVE = "yt_seen", "yt_videos", "yt_drive"
WPS = 2.5                 # narration pace used for planning; the real audio sets the final timing
GAP = 0.18                # pause after each beat, seconds
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
CHANNEL = {"id": "confessions", "name": "Confessions Everywhere", "director": "Confessions Everywhere Director",
           "shorts_per_day": 1, "subreddits": ["confession", "offmychest", "TrueOffMyChest"], "seconds": [60, 120],
           "voice": "en-US-GuyNeural", "outro": "Subscribe to our channel for more interesting stories.",
           "outro_query": "city lights at night", "logo": "", "caption_font": "", "generator": {},
           "privacy": "unlisted", "category": "24", "synthetic_flag": True, "uploads_per_run": 2, "drive_folder": ""}
UNSAFE = re.compile(r"\b(suicid\w*|kill(?:ed|ing)? (?:myself|himself|herself|him|her|them)|self[- ]harm\w*|rap(?:e|ed|es|ing|ist)|molest\w*|"
                    r"sexual(?:ly)? (?:assault|abus)\w*|incest\w*|underage|pedo\w*|child abuse|overdos\w*|murder\w*)\b", re.I)
STOP = set("a an and are as at be but by for from had has have he her his i in is it its me my of on or our she so that the their them "
           "they this to was we were what when which who with you your had been not no one would could there then than into out up".split())


def channel(raw: dict | None) -> dict:
    return {**CHANNEL, **(raw or {})}


def words(text: str) -> int:
    return len(text.split())


def word_range(ch: dict) -> tuple[int, int]:
    lo, hi = ch["seconds"]
    out = words(ch["outro"])
    return int(lo * WPS) - out, int(hi * WPS) - out - 15


def screenplay(story: str, outro: str, max_words: int = 16) -> list[dict]:
    """Split a story into beats short enough for one picture each, with the time each should take; outro last."""
    parts: list[str] = []
    for sent in re.split(r"(?<=[.!?…])[\"'”’)\]]*\s+", " ".join(story.split())):
        if words(sent) <= max_words:
            parts.append(sent)
            continue
        cur = ""
        for piece in re.split(r"(?<=[,;:—–])\s+", sent):       # a long sentence breaks at its own pauses
            if cur and words(cur) + words(piece) > max_words:
                parts.append(cur)
                cur = piece
            else:
                cur = (cur + " " + piece).strip()
        parts.append(cur)
    for i in range(len(parts) - 1, -1, -1):                        # still too long with no pause to break at: halve it
        ws = parts[i].split()
        if len(ws) > max_words + 6:
            parts[i:i + 1] = [" ".join(ws[:len(ws) // 2]), " ".join(ws[len(ws) // 2:])]
    beats: list[str] = []
    for p in (p.strip() for p in parts if p.strip()):
        if beats and words(beats[-1]) < 5 and words(beats[-1]) + words(p) <= max_words:
            beats[-1] += " " + p                                  # a two-word beat is too short to show
        else:
            beats.append(p)
    out = [{"i": i, "text": t, "target_s": round(words(t) / WPS + GAP, 1), "kind": "story"} for i, t in enumerate(beats)]
    if outro:
        out.append({"i": len(out), "text": outro, "target_s": round(words(outro) / WPS + GAP, 1), "kind": "outro"})
    return out


def fallback_query(text: str) -> str:
    picks = sorted(dict.fromkeys(w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in STOP), key=len, reverse=True)[:3]
    return " ".join(picks) or "person thinking alone"


def account(ch: dict) -> str:
    return ch.get("account") or f"youtube-{ch['id']}"


def save_record(store, ch: dict, job: dict) -> None:
    """The log entry for a finished Short: where it came from and everything that went into it."""
    store.kv_put(LOG, job["id"], {
        "channel": ch["id"], "status": "ready", "made": time.time(), "title": job["title"], "hashtags": job["hashtags"],
        "source": job["source"], "script": job["script"], "keywords": job["keywords"], "seconds": job["seconds"], "file": job["file"],
        "screenplay": [{"text": b["text"], "seconds": round(b["dur"], 2), "query": b["query"], "footage": (b.get("visual") or {}).get("page", "")} for b in job["beats"]],
        "credits": sorted({b["visual"]["credit"] for b in job["beats"] if b.get("visual")})})
    store.kv_put(SEEN, job["key"], {"state": "done"})


def _midnight() -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


class Crew(SubAgent):
    """A channel's crew member. The Scout puts the job in ctx; everyone after it works on that job."""

    def __init__(self, ch: dict, **kw: Any) -> None:
        super().__init__(**kw)
        self.ch = ch

    def client(self) -> httpx.AsyncClient:
        make = self.opts.get("client_factory")
        return make() if make else httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    @staticmethod
    def idle() -> AgentResult:
        return AgentResult("idle", "IDLE", "Nothing to make this run")


class StoryScout(Crew):
    name, tier, note = "Story Scout", "API", "finds one confession worth telling"

    def _inbox(self) -> list[dict]:
        folder = ROOT / "inbox" / "confessions" / self.ch["id"]
        out = []
        for f in sorted(folder.glob("*.txt")) if folder.exists() else []:
            lines = f.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            url = lines.pop(0).strip() if lines and lines[0].strip().startswith("http") else ""   # optional first line: where it came from
            out.append({"id": f"file-{f.stem}", "title": f.stem, "text": "\n".join(lines).strip(), "url": url, "score": 10**9, "sub": "inbox", "nsfw": False})
        return out

    async def _from_drive(self, ctx: dict) -> int:
        """Copy new text files and Google Docs from the channel's Drive folder into the inbox. A problem here is
        reported as a notice and never stops the Scout: the inbox may already hold stories."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        if not ch["drive_folder"]:
            return 0
        acct, note = account(ch), f"youtube-drive-{ch['id']}"
        try:
            token = await oauth.access_token(acct, "youtube")
        except oauth.AuthNeeded:
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice(f"auth:{acct}", f"Sign in to YouTube for {ch['name']}", f"http://127.0.0.1:{port}/auth/youtube/login?account={acct}")
            return 0
        inbox = ROOT / "inbox" / "confessions" / ch["id"]
        new = 0
        try:
            async with self.client() as c:
                folder = await gdrive.folder_id(c, token, ch["drive_folder"])
                if not folder:
                    bus.notice(note, f"{ch['name']}: no folder named “{ch['drive_folder']}” in the signed-in Google Drive")
                    return 0
                for f in await gdrive.texts(c, token, folder):
                    key = f"{ch['id']}:{f['id']}"
                    if store.kv_has(DRIVE, key):
                        continue
                    text = await gdrive.read(c, token, f)
                    slug = re.sub(r"[^A-Za-z0-9]+", "-", f["name"].rsplit(".txt", 1)[0]).strip("-")[:50] or "story"
                    inbox.mkdir(parents=True, exist_ok=True)
                    (inbox / f"{slug}-{f['id'][:6]}.txt").write_text(text, encoding="utf-8")
                    store.kv_put(DRIVE, key, {"name": f["name"]})
                    new += 1
        except (gdrive.DriveError, httpx.HTTPError) as e:
            bus.notice(note, f"{ch['name']}: Google Drive could not be read ({e})")
            return new
        bus.clear_notice(note)
        return new

    async def run(self, ctx: dict) -> AgentResult:
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        made = [v for v in store.kv_list(LOG, since=_midnight()) if v.get("channel") == ch["id"]]
        if len(made) >= ch["shorts_per_day"]:
            return AgentResult("idle", "QUOTA MET", f"{len(made)} of {ch['shorts_per_day']} Shorts made today")
        await self._from_drive(ctx)
        cands = self._inbox()
        if reddit.configured():
            async with self.client() as c:
                for sub in ch["subreddits"]:
                    cands += await reddit.top(c, sub)
        elif not cands:
            bus.notice(f"youtube-source-{ch['id']}", f"{ch['name']} needs a story source: add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET to .env, "
                                                     f"or drop a .txt into inbox/confessions/{ch['id']}/" + (f" or a document into the Drive folder “{ch['drive_folder']}”" if ch["drive_folder"] else ""))
            return AgentResult("wait", "NEEDS SOURCE", "No story to work from: nothing in the Drive folder or the inbox, and no Reddit keys")
        bus.clear_notice(f"youtube-source-{ch['id']}")

        checks = 0
        for p in sorted(cands, key=lambda p: p["score"], reverse=True):
            key = f"{ch['id']}:{p['id']}"
            seen = store.kv_get(SEEN, key) or {}
            if seen.get("state") in ("done", "rejected") or seen.get("tries", 0) >= 2 or p["nsfw"] or not 500 <= len(p["text"]) <= 7000:
                continue
            if UNSAFE.search(p["title"] + " " + p["text"]):
                store.kv_put(SEEN, key, {"state": "rejected", "why": "screened out by rule"})
                continue
            if checks >= 4:
                break
            checks += 1
            verdict = await ctx["llm"].json(
                "You screen anonymous confessions before they are retold in a public video with every name and place removed. Retelling an anonymous "
                "story is fine in itself. Reject it only if it involves minors in any sexual or abusive context, self-harm, a serious crime, hate, "
                "or a person who could still be identified after names and places are removed. "
                'Answer as {"ok": true or false, "why": "a few words"}.\n\nStory:\n' + p["text"][:5000], tier="writer", max_tokens=900)
            if not isinstance(verdict, dict) or not isinstance(verdict.get("ok"), bool):    # no answer: not used now, tried once more next run
                store.kv_put(SEEN, key, {"state": "unclear", "tries": seen.get("tries", 0) + 1})
                continue
            if not verdict["ok"]:
                store.kv_put(SEEN, key, {"state": "rejected", "why": str(verdict.get("why") or "")[:200]})
                continue
            store.kv_put(SEEN, key, {"state": "picked", "tries": seen.get("tries", 0) + 1})
            slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")[:40] or p["id"]
            work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{slug}"
            work.mkdir(parents=True, exist_ok=True)
            ctx["job"] = {"id": f"{ch['id']}-{p['id']}", "key": key, "channel": ch["id"], "dir": str(work), "raw": p["text"],
                          "source": {"url": p["url"], "title": p["title"], "from": p["sub"], "score": p["score"] if p["sub"] != "inbox" else None}}
            return AgentResult("done", "FOUND", f"Picked “{p['title'][:70]}” from {p['sub']}", {"source": ctx["job"]["source"]})
        return AgentResult("idle", "NOTHING NEW", f"No usable story among {len(cands)} candidates")


class StoryWriter(Crew):
    name, tier, note = "Story Writer", "CLOUD", "retells it with a hook, names and places removed"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        lo, hi = word_range(self.ch)
        prompt = (f"Retell the confession below as a narrated story for a 1-2 minute video, {lo + 20}-{hi - 20} words.\n"
                  "- Third person, as if retelling something shared anonymously (\"a woman\", \"he\", \"they\").\n"
                  "- The first sentence is a hook that makes someone stop scrolling.\n"
                  "- Keep the real events, feelings and outcome. You may add small build-ups and pauses for suspense, but no new events or facts.\n"
                  "- No personal names at all, and no city, workplace, school or other identifying detail; use generic terms.\n"
                  "- Short spoken sentences. End on the outcome or the thought it leaves. No call to subscribe.\n"
                  'Answer as {"title": "under 70 characters, no names", "story": "...", "hashtags": ["3 to 5 words, no #"]}.\n\n'
                  f"Confession:\n{job['raw'][:6000]}")
        note = ""
        for _ in range(2):
            d = await ctx["llm"].json(prompt + note, tier="writer", max_tokens=2500)
            story = " ".join(str((d or {}).get("story") or "").split()) if isinstance(d, dict) else ""
            n = words(story)
            if lo <= n <= hi:
                job["title"] = " ".join(str(d.get("title") or job["source"]["title"]).split())[:90]
                job["script"] = story
                job["hashtags"] = ["#" + re.sub(r"\W", "", str(h)) for h in (d.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:5]
                return AgentResult("done", "WRITTEN", f"“{job['title']}” · {n} words")
            note = f"\n\nYour last answer had {n} words. It must be between {lo} and {hi} words, as JSON."
        raise RuntimeError(f"the model did not return a story of {lo}-{hi} words")


class ScreenplayWriter(Crew):
    name, tier, note = "Screenplay Writer", "QUICK", "splits the story into timed beats"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        job["beats"] = screenplay(job["script"], self.ch["outro"])
        plan = sum(b["target_s"] for b in job["beats"])
        return AgentResult("done", "TIMED", f"{len(job['beats'])} beats, about {round(plan)} s")


class KeywordGenerator(Crew):
    name, tier, note = "Keyword Generator", "CLOUD", "one footage search per beat"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        story = [b for b in job["beats"] if b["kind"] == "story"]
        listing = "\n".join(f"{b['i'] + 1}. {b['text']}" for b in story)
        got = None
        try:
            got = await ctx["llm"].json(
                "For each numbered line of this story give one stock-footage search of 2-4 words: a concrete thing a camera could film that fits the "
                "line (\"woman staring out rainy window\", not \"sadness\"). No names, no text on screen. "
                f'Answer as a JSON list of exactly {len(story)} strings, in order.\n\n{listing}', tier="writer", max_tokens=1800)
        except Exception:
            pass                                  # no model: plain keywords from the line itself
        qs = [str(q).strip() for q in got] if isinstance(got, list) and len(got) == len(story) else []
        for n, b in enumerate(story):
            b["query"] = qs[n][:60] if qs and qs[n] else fallback_query(b["text"])
        for b in job["beats"]:
            b.setdefault("query", self.ch["outro_query"])
        job["keywords"] = [b["query"] for b in job["beats"]]
        return AgentResult("done", "DONE", f"{len(job['keywords'])} searches" + ("" if qs else " (plain keywords, no model)"))


class VoiceArtist(Crew):
    name, tier, note = "Voice Artist", "API", "narrates each beat and measures it"

    async def _edge(self, text: str, stem: Path) -> tuple[Path, list | None]:
        import edge_tts
        try:
            com = edge_tts.Communicate(text, self.ch["voice"], boundary="WordBoundary")
        except TypeError:                         # older edge-tts: word timings are the default
            com = edge_tts.Communicate(text, self.ch["voice"])
        marks, raw = [], stem.with_suffix(".mp3")
        with open(raw, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    marks.append([ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7])
        return raw, marks or None

    async def _synth(self, ctx: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        if self.opts.get("synth"):
            return await self.opts["synth"](text, stem)
        try:
            return await self._edge(text, stem)
        except ImportError:
            pass
        from ..voice import TTS                   # VISION's own local voice, no word timings
        tts = TTS(ctx["cfg"].voice)
        if not tts.available():
            raise RuntimeError("no voice: .venv/bin/pip install edge-tts (or set up the local voice)")
        raw = stem.with_suffix(".src.wav")
        raw.write_bytes(await tts.synth(text))
        return raw, None

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        folder = Path(job["dir"]) / "audio"
        folder.mkdir(exist_ok=True)
        for b in job["beats"]:
            raw, marks = await self._synth(ctx, b["text"], folder / f"beat{b['i']:02d}")
            wav = folder / f"beat{b['i']:02d}.wav"
            await asyncio.to_thread(shorts_edit.run, ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", f"apad=pad_dur={GAP}",
                                                      "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
            b["audio"], b["dur"] = str(wav), await asyncio.to_thread(shorts_edit.probe, wav)
            b["speech"], b["words"] = b["dur"] - GAP, marks
        total = sum(b["dur"] for b in job["beats"])
        job["seconds"] = round(total, 1)
        return AgentResult("done", "RECORDED", f"{round(total)} s of narration over {len(job['beats'])} beats")


class FootageCollector(Crew):
    name, tier, note = "Footage Collector", "API", "free stock clips and photos, one per beat"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if not stock_video.configured():
            raise RuntimeError("PEXELS_API_KEY or PIXABAY_API_KEY missing in .env")
        folder = Path(job["dir"]) / "footage"
        folder.mkdir(exist_ok=True)
        used: set[str] = set()
        async with self.client() as c:
            for b in job["beats"]:
                b["visual"] = None
                hit = await stock_video.find(c, b["query"], used) or await stock_video.find(c, fallback_query(b["text"]), used)
                if not hit:
                    continue
                path = folder / f"beat{b['i']:02d}.{'mp4' if hit['kind'] == 'video' else 'jpg'}"
                try:
                    await stock_video.download(c, hit["url"], path)
                except httpx.HTTPError:
                    continue
                b["visual"] = {**{k: hit[k] for k in ("kind", "duration", "credit", "page", "source")}, "path": str(path)}
        have = [b["visual"] for b in job["beats"] if b["visual"]]
        clips = sum(v["kind"] == "video" for v in have)
        return AgentResult("done", "COLLECTED", f"{len(have)} of {len(job['beats'])} beats have footage ({clips} clips, {len(have) - clips} photos)")


class FootageGenerator(Crew):
    """Fills beats the stock libraries had nothing for, through an online AI provider (services/genmedia.py)."""
    name, tier, note, blocking = "Footage Generator", "CLOUD", "AI image or clip for a beat with no footage", False

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        missing = [b for b in job["beats"] if not b.get("visual")]
        spec = self.ch.get("generator") or {}
        if not genmedia.ready(spec):
            return AgentResult("off", "OFF", f"No AI provider set; {len(missing)} beats reuse the footage beside them" if missing else "No AI provider set; not needed this time")
        kind = spec.get("kind", "image")
        async with self.client() as c:
            for b in missing:
                out = Path(job["dir"]) / "footage" / f"beat{b['i']:02d}.{'mp4' if kind == 'video' else 'png'}"
                await genmedia.generate(c, spec, f"{b['query']}, cinematic, vertical 9:16, no text", out, kind=kind, seconds=b["dur"])
                b["visual"] = {"kind": "video" if kind == "video" else "photo", "duration": 0, "path": str(out),
                               "credit": f"AI generated ({spec['provider']})", "page": "", "source": spec["provider"]}
        return AgentResult("done", "GENERATED", f"{len(missing)} beats filled by {spec['provider']}")


class Editor(Crew):
    name, tier, note = "Editor", "LOCAL", "cuts, captions, watermark, subscribe animation"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if not any(b.get("visual") for b in job["beats"]):
            raise RuntimeError("no footage for any beat")
        out = await asyncio.to_thread(shorts_edit.assemble, Path(job["dir"]), job["beats"], channel=self.ch["name"],
                                      logo=self.ch["logo"] or None, font_path=self.ch["caption_font"] or None)
        job["file"], job["seconds"] = out["file"], out["seconds"]
        for part in ("build", "footage", "audio"):            # the downloads and working files are large; the log keeps their sources
            shutil.rmtree(Path(job["dir"]) / part, ignore_errors=True)
        save_record(ctx["store"], self.ch, job)
        return AgentResult("done", "CUT", f"{out['seconds']} s Short, {out['captions']} captions")


class Uploader(Crew):
    """Uploads finished Shorts as unlisted and hands Mani the link. Public or deleted is his move, on YouTube."""
    name, tier, note = "Uploader", "API", "uploads as unlisted, sends you the link"

    @staticmethod
    async def _file(path: Path):
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                yield chunk

    async def _upload(self, c: httpx.AsyncClient, token: str, rec: dict) -> dict:
        ch = self.ch
        tags = list(dict.fromkeys(rec["hashtags"] + ["#Shorts"]))
        body = {"snippet": {"title": rec["title"][:100], "categoryId": str(ch["category"]), "tags": [t.lstrip("#") for t in tags],
                            "description": " ".join(tags) + ("\n\nFootage: " + "; ".join(rec["credits"]) if rec.get("credits") else "")},
                "status": {"privacyStatus": ch["privacy"], "selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(ch["synthetic_flag"])}}
        size = Path(rec["file"]).stat().st_size
        auth = {"Authorization": f"Bearer {token}"}
        r = await c.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
                         headers={**auth, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        if r.status_code != 200 or "location" not in r.headers:
            raise RuntimeError(f"YouTube refused the upload ({r.status_code}): {_reason(r)}")
        r = await c.put(r.headers["location"], content=self._file(Path(rec["file"])), headers={**auth, "Content-Type": "video/mp4", "Content-Length": str(size)})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"YouTube upload failed ({r.status_code}): {_reason(r)}")
        return r.json()

    async def run(self, ctx: dict) -> AgentResult:
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        ready = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("status") == "ready" and Path(v.get("file") or "").exists()]
        if not ready:
            return AgentResult("idle", "IDLE", "Nothing to upload")
        acct = account(ch)
        try:
            token = await oauth.access_token(acct, "youtube")
        except oauth.AuthNeeded:
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice(f"auth:{acct}", f"Sign in to YouTube for {ch['name']}", f"http://127.0.0.1:{port}/auth/youtube/login?account={acct}")
            return AgentResult("wait", "SIGN IN", f"{len(ready)} Short{'s' if len(ready) != 1 else ''} waiting: sign in to YouTube for {ch['name']}")
        bus.clear_notice(f"auth:{acct}")
        done = []
        async with self.client() as c:
            for rec in sorted(ready, key=lambda v: v["made"])[:ch["uploads_per_run"]]:
                out = await self._upload(c, token, rec)
                key = rec.pop("_key")
                rec.pop("_ts", None)
                rec.update(status=ch["privacy"], video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time())
                store.kv_put(LOG, key, rec)
                bus.notice(f"youtube-review-{out['id']}", f"New {ch['privacy']} Short on {ch['name']}: “{rec['title']}”. Review it, then make it public or delete it.",
                           f"https://studio.youtube.com/video/{out['id']}/edit")
                done.append(rec["title"])
        return AgentResult("done", "UPLOADED", f"Uploaded as {ch['privacy']}: " + "; ".join(f"“{t}”" for t in done))


def _reason(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"][:200]
    except Exception:
        return r.text[:200]


class AnalyticsManager(Crew):
    """Follows every uploaded Short (public yet? deleted? views, likes, comments), keeps the log current and reports the
    channel to its Director. The master report it feeds goes into the 06:00 and 18:00 briefs."""
    name, tier, note = "Analytics Manager", "API", "follows each Short, reports the channel"

    async def _refresh(self, ctx: dict, log: list[dict]) -> None:
        live = [v for v in log if v.get("video_id") and v.get("status") in ("unlisted", "private", "public")]
        if not live:
            return
        try:
            token = await oauth.access_token(account(self.ch), "youtube")
        except oauth.AuthNeeded:
            return                                 # the Uploader has already asked for the sign-in
        async with self.client() as c:
            r = await c.get(VIDEOS, params={"part": "status,statistics", "id": ",".join(v["video_id"] for v in live[:50])}, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise RuntimeError(f"YouTube stats failed ({r.status_code}): {_reason(r)}")
        found = {i["id"]: i for i in r.json().get("items", [])}
        for v in live[:50]:
            item = found.get(v["video_id"])
            was = v["status"]
            v["status"] = item["status"]["privacyStatus"] if item else "deleted"
            if item:
                v["stats"] = {k: int(item.get("statistics", {}).get(f"{k}Count", 0)) for k in ("view", "like", "comment")}
                v["checked"] = time.time()
            if v["status"] in ("public", "deleted") and was != v["status"]:
                ctx["bus"].clear_notice(f"youtube-review-{v['video_id']}")
            ctx["store"].kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})

    async def run(self, ctx: dict) -> AgentResult:
        ch = self.ch
        log = [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]]
        if not log:
            return AgentResult("done", "LOGGED", f"{ch['name']}: no Shorts made yet", {"channel": ch["id"], "made": 0})
        await self._refresh(ctx, log)
        n = {s: sum(v["status"] == s for v in log) for s in ("ready", "unlisted", "private", "public", "deleted")}
        views = sum((v.get("stats") or {}).get("view", 0) for v in log if v["status"] == "public")
        parts = [f"{len(log)} made"]
        if n["ready"]:
            parts.append(f"{n['ready']} waiting for upload")
        if n["unlisted"]:
            parts.append(f"{n['unlisted']} unlisted for your review")
        if n["private"]:
            parts.append(f"{n['private']} held private by YouTube")
        if n["public"]:
            parts.append(f"{n['public']} public with {views:,} views")
        if n["deleted"]:
            parts.append(f"{n['deleted']} deleted")
        latest = log[0]
        return AgentResult("done", "LOGGED", f"{ch['name']}: {', '.join(parts)}; latest “{latest['title']}” ({round(latest['seconds'])} s)",
                           {"channel": ch["id"], "made": len(log), **n, "views": views,
                            "videos": [{k: v.get(k) for k in ("title", "status", "url", "seconds", "stats", "source")} for v in log[:20]]})


def crew(ch: dict, **opts: Any) -> list[Stage]:
    return [Stage("SOURCE", [StoryScout(ch, **opts)]), Stage("STORY", [StoryWriter(ch)]), Stage("SCREENPLAY", [ScreenplayWriter(ch)]),
            Stage("PREP", [KeywordGenerator(ch), VoiceArtist(ch, **opts)]), Stage("FOOTAGE", [FootageCollector(ch, **opts)]),
            Stage("GENERATE", [FootageGenerator(ch, **opts)]), Stage("EDIT", [Editor(ch)]), Stage("UPLOAD", [Uploader(ch, **opts)]),
            Stage("REPORT", [AnalyticsManager(ch, **opts)])]


def build_agents(options: dict, cfg) -> dict[str, SubAgent]:
    out: dict[str, SubAgent] = {}
    for raw in options.get("channels") or [{}]:
        ch = channel(raw)
        out[ch["director"]] = Director(ch["director"], crew(ch), reporter="Analytics Manager", note=f"runs {ch['name']}")
    return out
