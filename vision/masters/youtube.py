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
import calendar
import difflib
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from ..agents import AgentResult, Director, Stage, SubAgent
from ..config import ROOT
from ..services import bgm, gdrive, genmedia, gutenberg, oauth, reddit, stock_video
from . import shorts_edit

SEEN, LOG, DRIVE, STATE, PREMISES, CLASSICS = "yt_seen", "yt_videos", "yt_drive", "yt_state", "yt_premises", "yt_classics"
WPS = 2.5                 # narration pace used for planning; the real audio sets the final timing
GAP = 0.18                # pause after each beat, seconds
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
VIDEOS = API + "/videos"
CHANNEL = {"id": "confessions", "name": "Confessions Everywhere", "director": "Confessions Everywhere Director",
           "shorts_per_day": 1, "subreddits": ["confession", "offmychest", "TrueOffMyChest"], "seconds": [60, 120],
           "voice_engine": "edge", "voice": "en-US-GuyNeural", "voice_speed": 0.95, "pause": 0.32, "outro": "Subscribe to our channel for more interesting stories.",
           "outro_query": "city lights at night", "logo": "", "caption_font": "", "generator": {},
           "privacy": "unlisted", "category": "24", "synthetic_flag": True, "uploads_per_run": 4, "drive_folder": "", "voices": {}, "music": True, "music_volume": 0.12, "ending": "hopeful", "originals": False, "original_genres": ["confession"],
           "publish_times": ["06:00", "12:00", "18:00", "00:00"], "create_after": "",
           "classics": [], "classics_per_day": 1, "playlists": {}, "viewer_comments": False, "cta": ""}
# Original stories: a premise is built from one of each, so no two start from the same place (20 x 12 x 10 x 10 combinations).
THEMES = ["a family secret", "a betrayal by a close friend", "a lie that grew too big", "a second chance that felt undeserved", "a debt never repaid",
          "an inheritance dispute", "a workplace mistake hidden for years", "a kindness kept secret", "a marriage on autopilot", "jealousy of a sibling",
          "a promise made to a dying parent", "taking credit for someone else's work", "walking away from a wedding", "a friendship ended over money",
          "an apology never sent", "pretending to be successful", "a chance meeting with an ex", "a neighbour badly misjudged",
          "quitting a job without telling the family", "a small act of revenge, regretted"]
SETTINGS = ["a small town", "a big-city apartment block", "a family business", "a hospital night shift", "a long-distance bus ride", "a university residence",
            "a wedding reception", "a gathering after a funeral", "an office after hours", "a village festival", "a first job abroad", "a shared taxi home"]
TELLERS = ["a woman in her thirties", "a man in his forties", "a young man just out of college", "a grandmother", "a single father", "a newly married woman",
           "a retired teacher", "a night-shift nurse", "a delivery driver", "an eldest daughter"]
STRUGGLES = ["starting over at fifty after losing a job", "failing the same exam twice", "a small shop a month from closing", "an injury that ended a sport",
             "learning to read as an adult", "the first lonely year in a new country", "a stammer and a job that needs speaking", "a manuscript rejected thirty times",
             "caring for a sick parent while studying at night", "paying off a debt that felt endless", "going back to school with teenagers", "a business partner who walked away",
             "stage fright before a first performance", "training for a race after years of illness", "raising two children on one small wage", "a farm after a ruined harvest"]
LIFTS = ["one sentence from a teacher", "a small habit kept every single day", "a second attempt nobody expected", "help from a stranger", "a letter kept in a wallet",
         "a promise made to a child", "the worst day turning out to be the start", "watching someone older try again", "a plain notebook of small wins", "a neighbour's quiet example"]
SCIENCE = {
    "space": ["how a star is born and how it dies", "why the Moon always shows us the same face", "the journey of the Voyager probes", "what a black hole's edge is",
              "why Mars is red", "what Saturn's rings are made of", "why a day on Venus is longer than its year", "how sunlight reaches Earth", "what causes the auroras",
              "where comets come from and why they grow tails", "how astronauts sleep and eat in orbit", "why we only ever see the past when we look at the stars"],
    "earth": ["how mountains rise", "why volcanoes erupt", "the journey of a single raindrop", "what causes earthquakes", "why the sky is blue and sunsets are red",
              "how lightning forms", "how a river carves a canyon", "how fossils form", "why we have seasons", "how Earth's magnetic field shields us",
              "how deserts form", "what the ice ages left behind"],
    "forests": ["how trees share food through fungi underground", "how a tree lifts water to its top", "why leaves change colour in autumn", "how a forest returns after fire",
                "the journey of a seed", "the layers of a rainforest", "how tree rings record the years", "how bees and flowers depend on each other",
                "what happens to a fallen log", "how mangroves live in salt water", "why old forests store so much carbon", "how a single fig tree feeds a forest"],
    "oceans": ["what happens when a whale dies and sinks", "life around deep-sea vents", "how coral reefs are built", "the great ocean currents", "why some sea creatures glow",
               "what causes the tides", "why the sea is salty", "the midnight zone of the deep sea", "how sea turtles find their way home", "how tiny plankton make the air we breathe",
               "the hidden forests of kelp", "how an octopus thinks and hides"]}
ANGLES = ["as a journey followed from start to finish", "as a mystery that people slowly solved", "as a day in the life of one creature or thing",
          "as the answer to a question a child might ask", "as a story of something happening right now, unseen"]
GENRE_ASK = {
    "confession": ("Invent premises for short confession-style stories: an ordinary adult did or hid something, and it comes into the open. One premise per numbered "
                   "line below, using that line's ingredients. Believable everyday life; adults only; no names or real places; nothing sexual, no self-harm, no "
                   "violent crime.", "2-3 sentences: who, what they did or hid, what forces it out, what is at stake"),
    "motivational": ("Invent premises for short motivational stories: an ordinary adult faces a real difficulty and gets through it by their own effort, a step at a "
                     "time, with no luck, miracle or sudden riches. One premise per numbered line below, using that line's ingredients. Believable everyday life; "
                     "no names or real places; no self-harm.", "2-3 sentences: who, what they are up against, the low point, what they do about it"),
    "science": ("Plan short science stories that teach one thing well. One plan per numbered line below, on that line's subject and told the way it says. Use only "
                "well-established facts of the kind found in a school textbook or an encyclopedia; no numbers or dates unless they are famous and certain; nothing "
                "speculative.", "the question it answers, then the 3-4 established facts it will tell, in order")}
GENRE_WRITE = {
    "confession": ("Write an original, fictional confession-style story from the premise below",
                   "- Third person, told like something a person carried for years and finally admitted (\"she\", \"he\", \"they\"). Do not claim it is real "
                   "and do not say anyone shared or sent it.\n"
                   "- Believable, specific, everyday detail; build the tension step by step to the moment it comes out.\n"
                   "- Adults only. No personal names at all, and no real city, company or school. Nothing sexual, no self-harm, no violent crime.\n"),
    "motivational": ("Write an original, fictional motivational story from the premise below",
                     "- Third person (\"she\", \"he\", \"they\"). Do not claim it is real.\n"
                     "- Show the difficulty honestly, then the small, concrete steps that got them through; earned by effort, never by luck.\n"
                     "- No personal names, no real city, company or school. No self-harm. No preaching and no list of tips: the story carries the lesson.\n"),
    "science": ("Write a true science story from the plan below",
                "- Every statement must be established science, as a good encyclopedia would give it. If you are not certain of a number or a date, leave it out. "
                "Nothing speculative, no myths presented as fact.\n"
                "- Tell it as a story with a beginning, a turn and an end, in plain words a twelve-year-old follows; explain any term you use.\n"
                "- No invented people or dialogue.\n")}
TURNS = ["a message sent to the wrong person", "an old letter found by accident", "an overheard phone call", "a stranger who knew the truth",
         "a photograph that should not exist", "a bank statement left open", "a child's innocent question", "a confession at the worst possible moment",
         "a reunion after ten years", "a diary returned by mistake"]
MOODS = ("dark", "sad", "warm", "light", "dramatic")
ENDINGS = {"plain": "End on the outcome or the thought it leaves.",
           "hopeful": "However heavy the story, end on a hopeful, motivating note: what the person learned, or how they found the strength to move "
                      "forward. You may add one or two closing sentences of reflection for that, but no new events."}
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
    """Split a story into beats short enough for one picture each, with the time each should take; outro last.
    `end` marks the beat that closes a sentence: the voice speaks sentence by sentence, never fragment by fragment."""
    parts: list[list] = []                                          # [text, closes a sentence]
    # a full stop after an initial or a title ("O. Henry", "Mrs. Dale") does not end a sentence
    for sent in re.split(r"(?<!\b[A-Z]\.)(?<!\bMr\.)(?<!\bMrs\.)(?<!\bDr\.)(?<!\bSt\.)(?<=[.!?…])[\"'”’)\]]*\s+", " ".join(story.split())):
        if words(sent) <= max_words:
            parts.append([sent, True])
            continue
        cur = ""
        for piece in re.split(r"(?<=[,;:—–])\s+", sent):       # a long sentence breaks at its own pauses
            if cur and words(cur) + words(piece) > max_words:
                parts.append([cur, False])
                cur = piece
            else:
                cur = (cur + " " + piece).strip()
        parts.append([cur, True])
    for i in range(len(parts) - 1, -1, -1):                        # still too long with no pause to break at: halve it
        ws = parts[i][0].split()
        if len(ws) > max_words + 6:
            parts[i:i + 1] = [[" ".join(ws[:len(ws) // 2]), False], [" ".join(ws[len(ws) // 2:]), parts[i][1]]]
    beats: list[list] = []
    for text, end in ([t.strip(), e] for t, e in parts if t.strip()):
        if beats and words(beats[-1][0]) < 5 and words(beats[-1][0]) + words(text) <= max_words:
            beats[-1] = [beats[-1][0] + " " + text, end]            # a two-word beat is too short to show
        else:
            beats.append([text, end])
    if beats:
        beats[-1][1] = True
    out = [{"i": i, "text": t, "target_s": round(words(t) / WPS + GAP, 1), "kind": "story", "end": e} for i, (t, e) in enumerate(beats)]
    if outro:
        out.append({"i": len(out), "text": outro, "target_s": round(words(outro) / WPS + GAP, 1), "kind": "outro", "end": True})
    return out


def split_times(texts: list[str], total: float, marks: list | None) -> tuple[list[float], list]:
    """Where one spoken sentence divides between its beats: (seconds per beat, word timings per beat).
    With the voice's word timings the cut falls between two words; without them it follows the length of the text."""
    counts = [len(t.split()) for t in texts]
    if marks and len(marks) == sum(counts):
        cuts, at = [0.0], 0
        for n in counts[:-1]:
            at += n
            cuts.append((marks[at - 1][2] + marks[at][1]) / 2)
        cuts.append(total)
        per, at = [], 0
        for k, n in enumerate(counts):
            per.append([[w, a - cuts[k], z - cuts[k]] for w, a, z in marks[at:at + n]])
            at += n
        return [cuts[k + 1] - cuts[k] for k in range(len(texts))], per
    chars = [len(t) + 1 for t in texts]
    return [total * c / sum(chars) for c in chars], [None] * len(texts)


def align(text: str, heard: list | None, total: float) -> list | None:
    """Timings for every word of the script, from the words a voice engine or the listener reported:
    [[word, start, end]]. Words that match in order take their heard time; a word in between that was heard
    differently (a number, a name) shares the gap between its neighbours. Too little in common -> None."""
    mine = text.split()
    if not heard or not mine:
        return None
    norm = lambda w: re.sub(r"[^a-z0-9]", "", str(w).lower())
    times: list = [None] * len(mine)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [norm(w) for w in mine], [norm(h[0]) for h in heard], autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (float(heard[j1 + k][1]), float(heard[j1 + k][2]))
    if sum(t is not None for t in times) < len(mine) * 0.6:
        return None
    i = 0
    while i < len(mine):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(mine) and times[j] is None:
            j += 1
        a = times[i - 1][1] if i else 0.0
        z = times[j][0] if j < len(mine) else total
        size = [len(w) + 1 for w in mine[i:j]]
        at = a
        for k in range(i, j):
            d = max(z - a, 0.0) * size[k - i] / sum(size)
            times[k] = (at, at + d)
            at += d
        i = j
    return [[w, t[0], t[1]] for w, t in zip(mine, times)]


def fallback_query(text: str) -> str:
    picks = sorted(dict.fromkeys(w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in STOP), key=len, reverse=True)[:3]
    return " ".join(picks) or "person thinking alone"


def account(ch: dict) -> str:
    return ch.get("account") or f"youtube-{ch['id']}"


def can_manage(ctx: dict, ch: dict) -> bool:
    """Playlists and comments need a wider permission than uploading. Without it, ask for one more sign-in and carry on."""
    if "youtube.force-ssl" in oauth.granted(account(ch)):
        ctx["bus"].clear_notice(f"youtube-scope-{ch['id']}")
        return True
    port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
    ctx["bus"].notice(f"youtube-scope-{ch['id']}", f"Sign in to YouTube again for {ch['name']}: playlists and viewer comments need a wider permission",
                      f"http://127.0.0.1:{port}/auth/youtube/login?account={account(ch)}")
    return False


def kind(job: dict) -> str:
    """classic (a public-domain story), original / motivational / science (written from a premise), viewer (a comment on the channel) or real."""
    if job.get("original"):
        return job["genre"] if job.get("genre") in ("motivational", "science") else "original"
    return "classic" if job.get("classic") else "viewer" if job["source"].get("from") == "viewer comment" else "real"


def save_record(store, ch: dict, job: dict) -> None:
    """The log entry for a finished Short: where it came from and everything that went into it."""
    store.kv_put(LOG, job["id"], {
        "channel": ch["id"], "status": "ready", "made": time.time(), "title": job["title"], "hashtags": job["hashtags"],
        "source": job["source"], "script": job["script"], "keywords": job["keywords"], "seconds": job["seconds"], "file": job["file"],
        "mood": job.get("mood", ""), "voice": job.get("voice", ""), "music": job.get("music", ""), "original": bool(job.get("original")), "kind": kind(job),
        "classic": job.get("classic"),
        "screenplay": [{"text": b["text"], "seconds": round(b["dur"], 2), "query": b["query"], "footage": (b.get("visual") or {}).get("page", "")} for b in job["beats"]],
        "credits": sorted({b["visual"]["credit"] for b in job["beats"] if b.get("visual")})})
    store.kv_put(SEEN, job["key"], {"state": "done"})


def next_slot(store, ch: dict, now: float | None = None) -> float:
    """The publishing time for the next Short: the first of the channel's publish_times after the last one already
    scheduled (the releases form one queue, in upload order), and at least half an hour away."""
    now = now or time.time()
    taken = [v["publish_at"] for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("publish_at") and v.get("status") != "deleted"]
    after = max([now + 1800] + [t + 60 for t in taken])
    lt = time.localtime(after)
    for day in range(3):
        for hm in sorted(ch["publish_times"]):
            h, m = (int(x) for x in str(hm).split(":"))
            ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + day, h, m, 0, 0, 0, -1))
            if ts > after:
                return ts
    return after + 86400


def made_today(store, ch: dict) -> int:
    # by the day it was made (a later status or stats update re-saves the record); a reset starts the day's count again
    start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
    return sum(v.get("channel") == ch["id"] and (v.get("made") or 0) >= start for v in store.kv_list(LOG))


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
        made = made_today(store, ch)
        if made >= ch["shorts_per_day"]:
            return AgentResult("idle", "QUOTA MET", f"{made} of {ch['shorts_per_day']} Shorts made today")
        waiting = sum(v.get("channel") == ch["id"] and v.get("status") == "ready" for v in store.kv_list(LOG))
        if waiting >= ch["shorts_per_day"]:          # finished Shorts are piling up unsent (YouTube's upload limit): make no more until they go
            return AgentResult("idle", "BACKLOG", f"{waiting} finished Shorts are waiting to upload; no new ones until they go")
        if ch["create_after"] and time.strftime("%H:%M") < ch["create_after"]:      # the day's Shorts are not started before this hour
            return AgentResult("idle", "NOT YET", f"Today's Shorts start at {ch['create_after']}")
        await self._from_drive(ctx)
        cands = self._inbox() + await self._from_comments(ctx)
        if reddit.configured():
            async with self.client() as c:
                for sub in ch["subreddits"]:
                    cands += await reddit.top(c, sub)
        elif not cands and not ch["originals"] and not ch["classics"]:
            bus.notice(f"youtube-source-{ch['id']}", f"{ch['name']} needs a story source: add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET to .env, "
                                                     f"or drop a .txt into inbox/confessions/{ch['id']}/" + (f" or a document into the Drive folder “{ch['drive_folder']}”" if ch["drive_folder"] else ""))
            return AgentResult("wait", "NEEDS SOURCE", "No story to work from: nothing in the Drive folder or the inbox, and no Reddit keys")
        bus.clear_notice(f"youtube-source-{ch['id']}")

        checks = 0
        for p in sorted(cands, key=lambda p: p["score"], reverse=True):
            key = f"{ch['id']}:{p['id']}"
            seen = store.kv_get(SEEN, key) or {}
            if seen.get("state") in ("done", "rejected") or seen.get("tries", 0) >= 2 or p["nsfw"] or not 300 <= len(p["text"]) <= 7000:
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
        c = await self._classic(ctx)                # then a classic for the playlist, up to the day's number
        if c:
            return AgentResult("done", "CLASSIC", f"“{c['title']}” by {c['author']}", {"source": ctx["job"]["source"]})
        if ch["originals"]:                         # no real story to tell today: an original one, from a premise never used before
            p = await self._original(ctx)
            if p:
                return AgentResult("done", "INVENTED", f"An original {ctx['job']['genre']} story: “{p['title'][:70]}”", {"source": ctx["job"]["source"]})
        return AgentResult("idle", "NOTHING NEW", f"No usable story among {len(cands)} candidates")

    async def _from_comments(self, ctx: dict) -> list[dict]:
        """Confessions viewers left under the channel's own Shorts: the stories every video asks for."""
        ch, store = self.ch, ctx["store"]
        vids = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("video_id") and v.get("status") in ("public", "unlisted")][:20]
        if not ch["viewer_comments"] or not vids or not can_manage(ctx, ch):
            return []
        try:
            token = await oauth.access_token(account(ch), "youtube")
        except oauth.AuthNeeded:
            return []
        out = []
        async with self.client() as c:
            for v in vids:
                r = await c.get(API + "/commentThreads", headers={"Authorization": f"Bearer {token}"},
                                params={"part": "snippet", "videoId": v["video_id"], "maxResults": 50, "order": "time", "textFormat": "plainText"})
                if r.status_code != 200:              # comments switched off, or the video has gone
                    continue
                for item in r.json().get("items", []):
                    top = item["snippet"]["topLevelComment"]
                    text = (top["snippet"].get("textOriginal") or top["snippet"].get("textDisplay") or "").strip()
                    out.append({"id": f"comment-{top['id']}", "title": " ".join(text.split())[:60], "text": text, "score": 2 * 10**9, "nsfw": False,
                                "sub": "viewer comment", "url": f"https://www.youtube.com/watch?v={v['video_id']}&lc={top['id']}"})
        return out

    async def _classic(self, ctx: dict) -> dict | None:
        """The next unused story from the shelf of public-domain books (taking from the least-used book), at most classics_per_day."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
        today = sum(v.get("channel") == ch["id"] and v.get("kind") == "classic" and (v.get("made") or 0) >= start for v in store.kv_list(LOG))
        if not ch["classics"] or today >= ch["classics_per_day"]:
            return None
        used = {v["_key"] for v in store.kv_list(CLASSICS, limit=5000)}
        for _ in range(6):                            # a story the rules screen out is marked and the next one is tried
            best = None
            for bid in ch["classics"]:
                try:
                    rows = await gutenberg.shelve(int(bid), self.client() if self.opts.get("client_factory") else None)
                except (RuntimeError, httpx.HTTPError) as e:
                    bus.say(f"⚠ {ch['name']} · book {bid} could not be fetched: {e}")
                    continue
                free = [r for r in rows if f"{ch['id']}:{bid}:{r['n']}" not in used]
                if free and (best is None or len(rows) - len(free) < best[0]):
                    best = (len(rows) - len(free), int(bid), free[0])
            if not best:
                return None
            _, bid, row = best
            key = f"{ch['id']}:{bid}:{row['n']}"
            text = gutenberg.read(bid, row["n"])
            safe = not UNSAFE.search(text)
            store.kv_put(CLASSICS, key, {"title": row["title"], "used": safe})
            used.add(key)
            if not safe:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", row["title"].lower()).strip("-")[:40] or f"{bid}-{row['n']}"
            work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{slug}"
            work.mkdir(parents=True, exist_ok=True)
            cite = {"title": row["title"], "author": row["author"], "book": row["book"], "url": gutenberg.page(bid)}
            ctx["job"] = {"id": f"{ch['id']}-classic-{bid}-{row['n']}", "key": f"{ch['id']}:classic-{bid}-{row['n']}", "channel": ch["id"], "dir": str(work),
                          "raw": text, "classic": cite, "source": {"url": cite["url"], "title": row["title"], "from": "classic", "score": None}}
            return cite
        return None

    def _mixes(self, genre: str, bank: list[dict], rng) -> list[tuple[str, str]]:
        """Eight (seed, ingredient line) pairs for a genre. A science subject is not taken twice while others are still unused."""
        if genre == "science":
            taken = {p.get("seed") for p in bank}
            subjects = [(d, t) for d, ts in SCIENCE.items() for t in ts]
            pool = [x for x in subjects if f"{x[0]}: {x[1]}" not in taken] or subjects
            return [(f"{d}: {t}", f"{d}: {t}; told {rng.choice(ANGLES)}") for d, t in rng.sample(pool, min(8, len(pool)))]
        if genre == "motivational":
            return [("", f"{rng.choice(STRUGGLES)}; about {rng.choice(TELLERS)}; in {rng.choice(SETTINGS)}; it turns on {rng.choice(LIFTS)}") for _ in range(8)]
        return [("", f"{rng.choice(THEMES)}; set in {rng.choice(SETTINGS)}; told about {rng.choice(TELLERS)}; it comes out through {rng.choice(TURNS)}") for _ in range(8)]

    async def _premises(self, ctx: dict, bank: list[dict], genre: str) -> list[dict]:
        """Ask the model for a batch of new premises, each from its own mix of ingredients; keep the ones unlike any before."""
        ch, store = self.ch, ctx["store"]
        mixes = self._mixes(genre, bank, self.opts.get("rng") or random)
        ask, shape = GENRE_ASK[genre]
        listing = "\n".join(f"{n + 1}. {line}" for n, (_, line) in enumerate(mixes))
        got = None
        for _ in range(2):                            # the model now and then returns a broken list: ask once more
            got = await ctx["llm"].json(
                f"{ask} Each must be clearly different from the others and from these already used: " + "; ".join(p["title"] for p in bank[:40]) + ".\n"
                f'Answer as a JSON list of {len(mixes)} objects: {{"title": "under 60 characters", "premise": "{shape}"}}.\n\n{listing}', tier="writer", max_tokens=3000)
            if isinstance(got, list) and got:
                break
        old = [p["premise"].lower() for p in bank]
        fresh = []
        for n, d in enumerate(got if isinstance(got, list) else []):
            text = " ".join(str((d or {}).get("premise") or "").split()) if isinstance(d, dict) else ""
            if not 60 <= len(text) <= 900 or UNSAFE.search(text) or any(difflib.SequenceMatcher(None, text.lower(), o).ratio() > 0.75 for o in old):
                continue
            rec = {"channel": ch["id"], "genre": genre, "seed": mixes[n][0] if n < len(mixes) else "", "used": False,
                   "title": " ".join(str(d.get("title") or text[:50]).split())[:80], "premise": text}
            key = f"{ch['id']}:{time.time_ns()}-{n}"
            store.kv_put(PREMISES, key, rec)
            old.append(text.lower())
            fresh.append({**rec, "_key": key})
        return fresh

    async def _original(self, ctx: dict) -> dict | None:
        ch, store = self.ch, ctx["store"]
        everything = [p for p in store.kv_list(PREMISES, limit=5000) if p.get("channel") == ch["id"]]
        genres = [g for g in ch["original_genres"] if g in GENRE_ASK] or ["confession"]
        told = {g: sum(p.get("used") and p.get("genre", "confession") == g for p in everything) for g in genres}
        genre = min(genres, key=lambda g: told[g])                 # the kind told least so far, so the kinds take turns
        bank = [p for p in everything if p.get("genre", "confession") == genre]
        fresh = [p for p in bank if not p.get("used")] or await self._premises(ctx, bank, genre)
        if not fresh:
            return None
        p = fresh[-1]
        store.kv_put(PREMISES, p["_key"], {k: v for k, v in p.items() if not k.startswith("_")} | {"used": True})
        tail = p["_key"].split(":", 1)[1]
        slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")[:40] or tail
        work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{slug}"
        work.mkdir(parents=True, exist_ok=True)
        ctx["job"] = {"id": f"{ch['id']}-orig-{tail}", "key": f"{ch['id']}:orig-{tail}", "channel": ch["id"], "dir": str(work), "raw": p["premise"],
                      "original": True, "genre": genre, "source": {"url": "", "title": p["title"], "from": f"original ({genre})", "score": None}}
        return p


class StoryWriter(Crew):
    name, tier, note = "Story Writer", "CLOUD", "retells it with a hook, names and places removed"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        lo, hi = word_range(self.ch)
        ending = ENDINGS.get(self.ch["ending"], ENDINGS["plain"])
        head, rules = GENRE_WRITE.get(job.get("genre") or "confession", GENRE_WRITE["confession"])
        science = job.get("genre") == "science"
        prompt = (f"{head}, narrated for a 1-2 minute video, {lo + 20}-{hi - 20} words.\n"
                  "- The first sentence is a hook that makes someone stop scrolling.\n" + rules +
                  "- Short spoken sentences. " + ("End on what it means for us, or the wonder of it." if science else ending) + " No call to subscribe.\n"
                  'Answer as {"title": "under 70 characters, no names", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"Premise:\n{job['raw']}") if job.get("original") else (
                  f"Retell the classic short story below for a 1-2 minute video, {lo + 20}-{hi - 20} words.\n"
                  "- Stay faithful: the same characters, events and the author's own ending. Do not modernise it or add a moral of your own.\n"
                  "- Third person, in your own plain spoken sentences; do not copy the author's sentences. Character names from the story may stay.\n"
                  "- The first sentence is a hook that makes someone stop scrolling. No call to subscribe.\n"
                  f'Answer as {{"title": "under 70 characters, built around the story\'s own title", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"“{job['classic']['title']}” by {job['classic']['author']}:\n{job['raw'][:40000]}") if job.get("classic") else (
                  f"Retell the confession below as a narrated story for a 1-2 minute video, {lo + 20}-{hi - 20} words.\n"
                  "- Third person, as if retelling something shared anonymously (\"a woman\", \"he\", \"they\").\n"
                  "- The first sentence is a hook that makes someone stop scrolling.\n"
                  "- Keep the real events, feelings and outcome. You may add small build-ups and pauses for suspense, but no new events or facts.\n"
                  "- No personal names at all, and no city, workplace, school or other identifying detail; use generic terms.\n"
                  "- Short spoken sentences. " + ENDINGS.get(self.ch["ending"], ENDINGS["plain"]) + " No call to subscribe.\n"
                  'Answer as {"title": "under 70 characters, no names", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"Confession:\n{job['raw'][:6000]}")
        note = ""
        for _ in range(2):
            d = await ctx["llm"].json(prompt + note, tier="writer", max_tokens=2500)
            story = " ".join(str((d or {}).get("story") or "").split()) if isinstance(d, dict) else ""
            n = words(story)
            if job.get("original") and UNSAFE.search(story):
                note = "\n\nYour last story touched something it must not (sexual content, self-harm or violent crime). Write it again without that, as JSON."
                continue
            if lo <= n <= hi:
                job["title"] = " ".join(str(d.get("title") or job["source"]["title"]).split())[:90]
                job["script"] = story
                mood = re.sub(r"[^a-z]", "", str(d.get("mood") or "").lower())
                job["mood"] = mood if mood in MOODS else ""
                job["hashtags"] = ["#" + re.sub(r"\W", "", str(h)) for h in (d.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:5]
                return AgentResult("done", "WRITTEN", f"“{job['title']}” · {n} words" + (f" · {job['mood']}" if job["mood"] else ""))
            note = f"\n\nYour last answer had {n} words. It must be between {lo} and {hi} words, as JSON."
        raise RuntimeError(f"the model did not return a story of {lo}-{hi} words")


class ScreenplayWriter(Crew):
    name, tier, note = "Screenplay Writer", "QUICK", "splits the story into timed beats"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        told = job["script"]
        if job.get("classic"):                      # the citation is spoken, as the story's last line
            told += f" A retelling of “{job['classic']['title']}”, by {job['classic']['author']}."
        job["beats"] = screenplay(told, self.ch["outro"])
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
    """Narrates sentence by sentence (a whole sentence keeps its intonation), then divides each sentence's audio
    between its beats. The voice follows the story's mood (channel option `voices`), else the channel's own voice.
    Engines: edge (online, reports its word timings) and kokoro (VISION's local voices; a local Whisper model then
    listens to each sentence to time its words, so captions never drift)."""
    name, tier, note = "Voice Artist", "API", "a voice for the mood, sentence by sentence"

    def voice_for(self, mood: str) -> dict:
        ch = self.ch
        return {"engine": ch["voice_engine"], "voice": ch["voice"], "speed": ch["voice_speed"], "pause": ch["pause"], **((ch.get("voices") or {}).get(mood) or {})}

    async def _edge(self, v: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        import edge_tts
        kw = {"rate": f"{round((float(v['speed']) - 1) * 100):+d}%"}
        try:
            com = edge_tts.Communicate(text, v["voice"], boundary="WordBoundary", **kw)
        except TypeError:                         # older edge-tts: word timings are the default
            com = edge_tts.Communicate(text, v["voice"], **kw)
        marks, raw = [], stem.with_suffix(".mp3")
        with open(raw, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    marks.append([ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7])
        return raw, marks or None

    def _kokoro(self, ctx: dict, v: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        import soundfile
        from kokoro_onnx import Kokoro
        vc = ctx["cfg"].voice
        if self._model is None:
            self._model = Kokoro(str(ROOT / vc.get("kokoro_model", "models/kokoro-v1.0.onnx")), str(ROOT / vc.get("kokoro_voices", "models/voices-v1.0.bin")))
        if v["voice"] not in self._model.get_voices():
            raise RuntimeError(f"Kokoro has no voice named {v['voice']}")
        samples, rate = self._model.create(text, voice=v["voice"], speed=float(v["speed"]), lang="en-gb" if v["voice"].startswith("b") else "en-us")
        raw = stem.with_suffix(".src.wav")
        soundfile.write(raw, samples, rate)
        try:
            import mlx_whisper
        except ImportError:
            return raw, None                       # no listener: captions are spread over the beat instead
        heard = mlx_whisper.transcribe(str(raw), path_or_hf_repo=vc.get("whisper_model", "mlx-community/whisper-small-mlx"), language="en",
                                       word_timestamps=True, initial_prompt=text)
        return raw, [[w["word"], w["start"], w["end"]] for seg in heard.get("segments", []) for w in seg.get("words", [])] or None

    async def _synth(self, ctx: dict, v: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        if self.opts.get("synth"):
            return await self.opts["synth"](text, stem)
        if v["engine"] == "kokoro":
            return await asyncio.to_thread(self._kokoro, ctx, v, text, stem)
        return await self._edge(v, text, stem)

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        folder = Path(job["dir"]) / "audio"
        folder.mkdir(exist_ok=True)
        v = self.voice_for(job.get("mood", ""))
        job["voice"] = f"{v['engine']} {v['voice']}"
        pause = float(v["pause"])
        self._model = None
        group: list[dict] = []
        timed = total_lines = 0
        try:
            for b in job["beats"]:
                group.append(b)
                if not b.get("end", True):
                    continue
                stem = folder / f"line{group[0]['i']:02d}"
                text = " ".join(x["text"] for x in group)
                raw, heard = await self._synth(ctx, v, text, stem)
                wav = stem.with_suffix(".wav")
                await asyncio.to_thread(shorts_edit.run, ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", f"apad=pad_dur={pause}",
                                                          "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
                total = await asyncio.to_thread(shorts_edit.probe, wav)
                marks = align(text, heard, total - pause)
                timed, total_lines = timed + bool(marks), total_lines + 1
                durs, per = split_times([x["text"] for x in group], total - pause, marks)
                durs[-1] += pause                                   # the pause after the sentence stays on its last beat
                for x, d, m in zip(group, durs, per):
                    x["audio"], x["dur"], x["words"] = str(wav), d, m
                    x["speech"] = d - (pause if x is group[-1] else 0)
                group = []
        finally:
            self._model = None                                      # the local voice model is large: let it go after the run
        total = sum(b["dur"] for b in job["beats"])
        job["seconds"] = round(total, 1)
        note = "" if timed == total_lines else f"; captions estimated on {total_lines - timed} of {total_lines} sentences"
        return AgentResult("done", "RECORDED", f"{round(total)} s in {v['voice']}" + (f" for a {job['mood']} story" if job.get("mood") else "") + note)


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
        track = None
        if self.ch["music"] and job.get("mood"):       # a track from the mood's folder, moving on one each time the mood comes up
            used = sum(v.get("mood") == job["mood"] and v.get("channel") == self.ch["id"] for v in ctx["store"].kv_list(LOG))
            track = bgm.pick(job["mood"], used)
        job["music"] = (bgm.line(track[1]) or track[0].name) if track else ""
        out = await asyncio.to_thread(shorts_edit.assemble, Path(job["dir"]), job["beats"], channel=self.ch["name"],
                                      logo=self.ch["logo"] or None, font_path=self.ch["caption_font"] or None,
                                      music=str(track[0]) if track else None, music_volume=float(self.ch["music_volume"]))
        job["file"], job["seconds"] = out["file"], out["seconds"]
        for part in ("build", "footage", "audio"):            # the downloads and working files are large; the log keeps their sources
            shutil.rmtree(Path(job["dir"]) / part, ignore_errors=True)
        save_record(ctx["store"], self.ch, job)
        return AgentResult("done", "CUT", f"{out['seconds']} s Short, {out['captions']} captions" + (", with music" if track else ", no music"))


class UploadLimit(Exception):
    pass


class Uploader(Crew):
    """Uploads finished Shorts as unlisted and hands Mani the link. Public or deleted is his move, on YouTube."""
    name, tier, note = "Uploader", "API", "uploads as unlisted, sends you the link"

    @staticmethod
    async def _file(path: Path):
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                yield chunk

    async def _upload(self, ctx: dict, c: httpx.AsyncClient, token: str, rec: dict) -> dict:
        ch = self.ch
        tags = list(dict.fromkeys(rec["hashtags"] + ["#Shorts"]))
        when = next_slot(ctx["store"], ch) if ch["privacy"] == "scheduled" else None     # scheduled = private now, public by itself at its slot
        body = {"snippet": {"title": rec["title"][:100], "categoryId": str(ch["category"]), "tags": [t.lstrip("#") for t in tags],
                            "description": " ".join(tags) + (f"\n\n{ch['cta']}" if ch["cta"] else "") + _about(rec)
                            + ("\n\nFootage: " + "; ".join(rec["credits"]) if rec.get("credits") else "")
                            + (f"\nMusic: {rec['music']}" if rec.get("music") else "")},
                "status": {"privacyStatus": "private" if when else ch["privacy"], "selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(ch["synthetic_flag"]),
                           **({"publishAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))} if when else {})}}
        size = Path(rec["file"]).stat().st_size
        auth = {"Authorization": f"Bearer {token}"}
        r = await c.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
                         headers={**auth, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        if r.status_code != 200 or "location" not in r.headers:
            if "uploadLimitExceeded" in r.text or "exceeded the number of videos" in r.text:
                raise UploadLimit()
            raise RuntimeError(f"YouTube refused the upload ({r.status_code}): {_reason(r)}")
        r = await c.put(r.headers["location"], content=self._file(Path(rec["file"])), headers={**auth, "Content-Type": "video/mp4", "Content-Length": str(size)})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"YouTube upload failed ({r.status_code}): {_reason(r)}")
        return {**r.json(), "publish_at": when}

    async def _extras(self, ctx: dict, c: httpx.AsyncClient, token: str, rec: dict) -> str:
        """After the upload: the Short joins its playlist and gets the channel's invitation as a comment. Neither can fail the upload."""
        ch, store = self.ch, ctx["store"]
        name = (ch["playlists"] or {}).get(rec.get("kind") or "")
        if not (name or ch["cta"]) or not can_manage(ctx, ch):
            return ""
        auth, notes = {"Authorization": f"Bearer {token}"}, []
        try:
            if name:
                slot = f"{ch['id']}:playlist:{name}"
                pid = (store.kv_get(STATE, slot) or {}).get("id")
                if not pid:
                    r = await c.get(API + "/playlists", params={"part": "snippet", "mine": "true", "maxResults": 50}, headers=auth)
                    pid = next((p["id"] for p in r.json().get("items", []) if p["snippet"]["title"] == name), None) if r.status_code == 200 else None
                if not pid:
                    r = await c.post(API + "/playlists", params={"part": "snippet,status"}, headers=auth,
                                     json={"snippet": {"title": name}, "status": {"privacyStatus": "public"}})
                    pid = r.json().get("id") if r.status_code == 200 else None
                if pid:
                    store.kv_put(STATE, slot, {"id": pid})
                    r = await c.post(API + "/playlistItems", params={"part": "snippet"}, headers=auth,
                                     json={"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": rec["video_id"]}}})
                notes.append(f"in “{name}”" if pid and r.status_code == 200 else f"playlist failed: {_reason(r)}")
            if ch["cta"]:
                r = await c.post(API + "/commentThreads", params={"part": "snippet"}, headers=auth,
                                 json={"snippet": {"videoId": rec["video_id"], "topLevelComment": {"snippet": {"textOriginal": ch["cta"]}}}})
                if r.status_code != 200:
                    notes.append(f"comment failed: {_reason(r)}")
        except httpx.HTTPError as e:
            notes.append(f"extras failed: {e}")
        return f" ({', '.join(notes)})" if notes else ""

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
        if ch["privacy"] == "scheduled":           # know every release already set, Mani's own included, before choosing the next time
            await AnalyticsManager(ch, **self.opts)._refresh(ctx, [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"]])
        done = []
        async with self.client() as c:
            for rec in sorted(ready, key=lambda v: v["made"])[:ch["uploads_per_run"]]:
                try:
                    out = await self._upload(ctx, c, token, rec)
                except UploadLimit:                # YouTube's own cap on uploads per channel per day: not a fault, the Shorts wait
                    left = len(ready) - len(done)
                    bus.notice(f"youtube-limit-{ch['id']}", f"{ch['name']}: YouTube's daily upload limit for the channel is reached. "
                                                            f"{left} finished Short{'s' if left != 1 else ''} will upload on a later run.")
                    return AgentResult("wait", "UPLOAD LIMIT", (f"Uploaded as {ch['privacy']}: " + "; ".join(done) + ". " if done else "")
                                       + f"YouTube's daily upload limit reached; {left} waiting")
                bus.clear_notice(f"youtube-limit-{ch['id']}")
                key = rec.pop("_key")
                rec.pop("_ts", None)
                rec.update(status=ch["privacy"], video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time(), publish_at=out["publish_at"])
                store.kv_put(LOG, key, rec)
                when = time.strftime(" for %a %H:%M", time.localtime(out["publish_at"])) if out["publish_at"] else ""
                if when:                                   # no review step: it goes public by itself
                    bus.say(f"{ch['name']} · “{rec['title']}” goes public{when.replace(' for', '')}")
                else:
                    review_notice(bus, ch, rec)
                done.append(rec["title"] + when + await self._extras(ctx, c, token, rec))
        return AgentResult("done", "UPLOADED", f"Uploaded as {ch['privacy']}: " + "; ".join(f"“{t}”" if " for " not in t else t for t in done))


def _about(rec: dict) -> str:
    """One line on where the story comes from, for the description."""
    c = rec.get("classic")
    if c:
        return f"\n\nRetold from “{c['title']}” by {c['author']}, in “{c['book']}” (public domain): {c['url']}"
    return {"original": "\n\nThis story is fiction.", "motivational": "\n\nThis story is fiction.",
            "viewer": "\n\nRetold from a viewer's comment."}.get(rec.get("kind"), "")


def review_notice(bus, ch: dict, rec: dict) -> None:
    bus.notice(f"youtube-review-{rec['video_id']}", f"New {rec['status']} Short on {ch['name']}: “{rec['title']}”. Review it, then make it public or delete it.",
               f"https://studio.youtube.com/video/{rec['video_id']}/edit")


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
        live = [v for v in log if v.get("video_id") and v.get("status") in ("unlisted", "private", "public", "scheduled")]
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
            due = (item or {}).get("status", {}).get("publishAt")
            if due:                                # private with a publishing time = scheduled, whether VISION or Mani set it
                v["publish_at"] = calendar.timegm(time.strptime(due[:19], "%Y-%m-%dT%H:%M:%S"))
            if v["status"] == "private" and (due or (v.get("publish_at") or 0) > time.time() - 3600):
                v["status"] = "scheduled"
            if item:
                v["stats"] = {k: int(item.get("statistics", {}).get(f"{k}Count", 0)) for k in ("view", "like", "comment")}
                v["checked"] = time.time()
            if v["status"] in ("public", "deleted", "scheduled") and was != v["status"]:
                ctx["bus"].clear_notice(f"youtube-review-{v['video_id']}")
            ctx["store"].kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})

    async def run(self, ctx: dict) -> AgentResult:
        ch = self.ch
        log = [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]]
        if not log:
            return AgentResult("done", "LOGGED", f"{ch['name']}: no Shorts made yet", {"channel": ch["id"], "made": 0})
        await self._refresh(ctx, log)
        for v in log:                              # notices live in memory: put the reminder back after a restart
            if v["status"] == "unlisted" and v.get("video_id"):
                review_notice(ctx["bus"], ch, v)
        n = {s: sum(v["status"] == s for v in log) for s in ("ready", "unlisted", "scheduled", "private", "public", "deleted")}
        views = sum((v.get("stats") or {}).get("view", 0) for v in log if v["status"] == "public")
        parts = [f"{len(log)} made"]
        if n["ready"]:
            parts.append(f"{n['ready']} waiting for upload")
        if n["unlisted"]:
            parts.append(f"{n['unlisted']} unlisted for your review")
        if n["scheduled"]:
            parts.append(f"{n['scheduled']} scheduled")
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


def reset_today(store, channel_id: str) -> None:
    """Start today's count for a channel again: Shorts made before this moment no longer count toward shorts_per_day."""
    store.kv_put(STATE, f"{channel_id}:quota_reset", {"at": time.time()})


def more_today(ch: dict):
    """One pass of the crew makes one Short. Go round again while the last pass made one and the day's number isn't reached."""
    return lambda ctx: bool((ctx.get("job") or {}).get("file")) and made_today(ctx["store"], ch) < ch["shorts_per_day"]


def build_agents(options: dict, cfg) -> dict[str, SubAgent]:
    out: dict[str, SubAgent] = {}
    for raw in options.get("channels") or [{}]:
        ch = channel(raw)
        out[ch["director"]] = Director(ch["director"], crew(ch), reporter="Analytics Manager", again=more_today(ch), note=f"runs {ch['name']}")
    return out
