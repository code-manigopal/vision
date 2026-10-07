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
from ..services import bgm, fonts, gdrive, genmedia, gutenberg, oauth, reddit, sfx, stock_video, yt_suggest
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
           "classics": [], "classics_per_day": 1, "playlists": {}, "viewer_comments": False, "cta": "", "long": {},
           "motion": True, "caption_styles": True, "sfx": True, "sfx_volume": 0.35, "quick": {},
           "double_down": True, "double_down_after": 12, "explore": 0.15}
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
MONEY = ["how compound interest really grows money", "why an emergency fund comes before investing", "what an index fund is", "how a credit score is built",
         "what a credit card's minimum payment really costs", "the 50/30/20 budget", "paying off debt: smallest balance first or highest interest first",
         "what passive income costs before it pays", "how creators actually get paid for ads", "what it takes for a channel to be monetised",
         "how affiliate marketing pays, and when it doesn't", "the real margins of selling other people's products online", "pricing your first freelance job",
         "why lifestyle creep eats every raise", "what inflation does to savings", "the true cost of owning a car", "what an employer's pension match is worth",
         "how to ask for a raise", "auditing your subscriptions", "opportunity cost: what a purchase really costs", "why spreading money across investments lowers risk",
         "risk and return: why they travel together", "investing the same amount every month", "how banks make money from your deposit", "how insurance works",
         "the signs of a get-rich-quick scam", "why several small incomes take years to build", "skills that keep paying for decades", "renting or buying: what to compare",
         "saving for a known cost a little each month", "what a recession is", "why most small businesses run out of cash, not customers"]
# How a learning video keeps people to the end (Mani's table): each opens a question the viewer stays to have answered.
STRUCTURES = {
    "result_first": "Open with the end result in one sentence. Then say what was done to get it. Then give the lesson as plain steps, promising early that the "
                    "most useful step comes last, and keep it for last.",
    "belief_flip": "Open by stating something most people believe. Contradict it in the very next sentence. Spend the rest on why, and hold the full reason "
                   "until the end.",
    "better_best": "Open with a way that is better than what most people do. Then say there is a best way and that it is coming, to hook again. Deliver the "
                   "best way last.",
    "unless": "Open by saying the usual way will not work unless one thing is done. Do not name it at once: first show why the usual way fails, then give "
              "the one thing and exactly how to do it.",
    "only_if": "Open with the goal. Give the simple answer early, then at once add that it only works if it is done in one specific way. Keep that "
               "specific way for the end, and build towards it.",
    "not_a_not_b": "Open with the goal. Name a first thing people try and say plainly why it was not the answer. Name a second and why that was not it "
                   "either. Then give the third, the one that actually pays off, and why.",
    "most_do_least": "Open with the goal. Say what most people do for it, and that it gets the least results. Ask why. Answer the why last, with what to "
                     "do instead.",
}
# The pattern that loses viewers (first row of Mani's second table): the whole answer in the middle and nothing left to wait for.
HOLD_BACK = ("Never hand over the whole answer before the final third: every part must leave one question open, and the last part closes it.")
RETAIN_STORY = ("Keep them listening: the first sentence opens a question the listener needs answered; around the middle, one line raises the stakes again "
                "(\"and that was not the worst of it\"); the answer comes only at the end.")
PROMISE = re.compile(r"\b(guarantee\w*|get rich|rich quick|overnight|risk[- ]free|easy money|secret (trick|method)|in \d+ (days?|hours?|weeks?))\b|"
                     r"[$€£₹]\s?\d[\d,.]*\s?k?\s*(a|per|every|/)\s*(day|week|month|hour)\b", re.I)
# In the lesson itself, the thing never said is a promise made to the viewer (a myth being examined may be named freely).
TOLD_PROMISE = re.compile(r"\byou(?:'ll| will| can| could)?\s+(?:easily\s+|quickly\s+)?(?:make|earn|get|bank)\b[^.?!]{0,40}[$€£₹]\s?\d|"
                          r"\bguaranteed\s+(?:income|returns?|profits?|money|results?)\b|\b(?:will|is going to) make you rich\b", re.I)


def promises(title: str) -> bool:
    """A title that states an amount, a speed or a certainty of earning. Asked as an open question it explores the claim, which is allowed."""
    return bool(PROMISE.search(title)) and not title.strip().endswith("?")


ANGLES = ["as a journey followed from start to finish", "as a mystery that people slowly solved", "as a day in the life of one creature or thing",
          "as the answer to a question a child might ask", "as a story of something happening right now, unseen"]
GENRE_ASK = {
    "confession": ("Invent premises for short confession-style stories: an ordinary adult did or hid something, and it comes into the open. One premise per numbered "
                   "line below, using that line's ingredients. Believable everyday life; adults only; no names or real places; nothing sexual, no self-harm, no "
                   "violent crime.", "2-3 sentences: who, what they did or hid, what forces it out, what is at stake"),
    "motivational": ("Invent premises for short motivational stories: an ordinary adult faces a real difficulty and gets through it by their own effort, a step at a "
                     "time, with no luck, miracle or sudden riches. One premise per numbered line below, using that line's ingredients. Believable everyday life; "
                     "no names or real places; no self-harm.", "2-3 sentences: who, what they are up against, the low point, what they do about it"),
    "money": ("Plan short lessons about money that teach one thing well and honestly. One plan per numbered line below, on that line's subject. Use only "
              "established facts and principles that any standard personal-finance textbook gives; show what the thing costs or risks as well as what it "
              "gives; no promise of earnings, no income figures, no named shares, coins or products, nothing speculative.",
              "the question it answers, then the 3-4 established points it will make, in order, ending on the most useful one"),
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
    "money": ("Write a short, honest lesson about money from the plan below",
              "- Speak to the viewer as \"you\", plainly, like a friend who knows the subject. Explain any term the moment you use it.\n"
              "- Only established facts and principles. Never promise or suggest an amount, a speed or a certainty of earning; say what it costs, how long "
              "it takes and what can go wrong. No named shares, coins, apps or products, and no advice to buy or sell anything.\n"
              "- One idea, taught well, with one concrete everyday example using small round numbers that are clearly only an illustration.\n"
              "- Explore, do not promise: ask \"how can we...\", \"can you really...\", \"what does it take to...\"; say \"can\" and \"may\", never "
              "\"will\"; be plain that it may or may not work for the viewer, and say what decides it.\n"
              "- The title is an open question in that same spirit.\n"),
    "science": ("Write a true science story from the plan below",
                "- Every statement must be established science, as a good encyclopedia would give it. If you are not certain of a number or a date, leave it out. "
                "Nothing speculative, no myths presented as fact.\n"
                "- Tell it as a story with a beginning, a turn and an end, in plain words a twelve-year-old follows; explain any term you use.\n"
                "- No invented people or dialogue.\n")}
TURNS = ["a message sent to the wrong person", "an old letter found by accident", "an overheard phone call", "a stranger who knew the truth",
         "a photograph that should not exist", "a bank statement left open", "a child's innocent question", "a confession at the worst possible moment",
         "a reunion after ten years", "a diary returned by mistake"]
MOODS = ("dark", "sad", "warm", "light", "dramatic")
# A long video (wide, several minutes) beside the Shorts: channel option `long`, these are its defaults.
LONG = {"enabled": False, "per_day": 1, "minutes": [6, 9], "publish_time": "20:00", "playlist": "Long Stories", "create_after": "03:00",
        "min_source_words": 1600, "shot_seconds": 8}
# A quick Short (20-35 s) beside the regular ones: only an original story can be one; channel option `quick`.
QUICK = {"per_day": 1, "seconds": [20, 35], "outro": "Your story could be next. Comment it."}
OLD_WORDS = ("The original is old: never repeat a slur or a dated word for a race, nationality, religion or disability; describe the person plainly "
             "(\"a musician\", \"a man on the ferry\") or leave the detail out.")
ENDINGS = {"plain": "End on the outcome or the thought it leaves.",
           "hopeful": "However heavy the story, end on a hopeful, motivating note: what the person learned, or how they found the strength to move "
                      "forward. You may add one or two closing sentences of reflection for that, but no new events."}
UNSAFE = re.compile(r"\b(suicid\w*|kill(?:ed|ing)? (?:myself|himself|herself|him|her|them)|self[- ]harm\w*|rap(?:e|ed|es|ing|ist)|molest\w*|"
                    r"sexual(?:ly)? (?:assault|abus)\w*|incest\w*|underage|pedo\w*|child abuse|overdos\w*|murder\w*)\b", re.I)
STOP = set("a an and are as at be but by for from had has have he her his i in is it its me my of on or our she so that the their them "
           "they this to was we were what when which who with you your had been not no one would could there then than into out up".split())


def channel(raw: dict | None) -> dict:
    return {**CHANNEL, **(raw or {})}


def long_of(ch: dict) -> dict:
    return {**LONG, **(ch.get("long") or {})}


def quick_of(ch: dict) -> dict:
    return {**QUICK, **(ch.get("quick") or {})}


def parts(text: str, n: int) -> list[str]:
    """The text cut into n consecutive pieces of about equal length, at paragraph ends (at sentence ends when it has few paragraphs)."""
    units = [" ".join(u.split()) for u in re.split(r"\n\s*\n", text) if u.strip()]
    if len(units) < n * 2:
        units = [u for u in re.split(r"(?<=[.!?])[\"'”’)\]]*\s+", " ".join(text.split())) if u.strip()]
    total, out, cur, done = sum(len(u.split()) for u in units), [], [], 0
    for u in units:
        cur.append(u)
        done += len(u.split())
        if len(out) < n - 1 and done >= total * (len(out) + 1) / n:
            out.append(" ".join(cur))
            cur = []
    return [x for x in out + [" ".join(cur)] if x]


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def words(text: str) -> int:
    return len(text.split())


def word_range(ch: dict, quick: bool = False) -> tuple[int, int]:
    q = quick_of(ch)
    lo, hi = q["seconds"] if quick else ch["seconds"]
    out = words(q["outro"] if quick else ch["outro"])
    return int(lo * WPS) - out, int(hi * WPS) - out - 15


def choose(options: list[str], told: dict[str, int], views: dict[str, float], floor: float) -> str:
    """Double down on what performs without starving the rest: every option keeps a share of `floor`, and the remainder
    follows average views (an option with no views yet counts as the mean of the known ones, so it keeps being tried).
    The option told furthest below its target share is next; a tie goes to the earlier. No views, or a floor that
    leaves nothing to share -> the least told."""
    n, total = len(options), sum(told.get(o, 0) for o in options)
    known = [views[o] for o in options if o in views]
    if floor * n >= 1 or not known or sum(known) <= 0:
        return min(options, key=lambda o: told.get(o, 0))
    mean = sum(known) / len(known)
    seen = {o: views.get(o, mean) for o in options}
    gap = lambda o: round(floor + (1 - floor * n) * seen[o] / sum(seen.values()) - (told.get(o, 0) / total if total else 0), 9)
    return max(options, key=gap)


# Sound effects are cues a line asks for, never decoration: the model names one only where the moment calls for it.
CUES = {"riser": "tension building just before something happens", "impact": "a shock or a revelation lands", "heartbeat": "fear, dread, a held breath",
        "drone": "unease, something is wrong", "tick": "waiting, time running out", "ding": "a realisation, an idea, good news",
        "whoosh": "a jump in time or place", "pop": "something light or funny", "coin": "money gained, paid or lost", "notification": "a message or a call arrives"}
CUE_LEVEL = {"impact": 0.9, "riser": 0.8, "heartbeat": 0.8, "ding": 0.8, "notification": 0.8, "pop": 0.7, "coin": 0.7, "drone": 0.6, "tick": 0.6, "whoosh": 0.6}


def sfx_plan(beats: list[dict], *, volume: float, turn: int = 0) -> list[dict]:
    """Where the sound effects go: only on a line that asked for one (`cue` on a beat), at the moment it is spoken; a riser is
    timed to finish as its line ends. Kept sparse whatever was asked: at least 4 seconds apart and about one per 8 seconds
    of video. A cue whose kind has no file in the library is left out. Times follow the beats' own lengths."""
    starts, t = [], 0.0
    for b in beats:
        starts.append(t)
        t += b["dur"]
    out, used, last = [], {}, -99.0
    for i, b in enumerate(beats):
        cue = b.get("cue")
        if cue not in CUES or b["kind"] == "outro" or len(out) >= max(2, int(t // 8)):
            continue
        path = sfx.pick(cue, turn + used.get(cue, 0))
        if not path:
            continue
        at = starts[i]
        if cue == "riser":
            try:
                at = max(at, starts[i] + b["dur"] - shorts_edit.probe(str(path)))
            except RuntimeError:                       # a file that will not decode is no use
                continue
        if at - last < 4:
            continue
        used[cue] = used.get(cue, 0) + 1
        last = at
        out.append({"at": round(at, 2), "path": str(path), "volume": round(volume * CUE_LEVEL[cue], 3)})
    return out


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
        return job["genre"] if job.get("genre") in ("motivational", "science", "money") else "original"
    return "classic" if job.get("classic") else "viewer" if job["source"].get("from") == "viewer comment" else "real"


def save_record(store, ch: dict, job: dict) -> None:
    """The log entry for a finished video: where it came from and everything that went into it."""
    store.kv_put(LOG, job["id"], {
        "channel": ch["id"], "status": "ready", "made": time.time(), "title": job["title"], "hashtags": job["hashtags"],
        "source": job["source"], "script": job["script"], "keywords": job["keywords"], "seconds": job["seconds"], "file": job["file"],
        "mood": job.get("mood", ""), "voice": job.get("voice", ""), "music": job.get("music", ""), "original": bool(job.get("original")), "kind": kind(job),
        "classic": job.get("classic"), "seo": job.get("seo"), "structure": job.get("structure", ""), "format": job.get("format", "short"), "summary": job.get("summary", ""),
        "caption": job.get("caption", ""), "sfx": job.get("sfx", 0), "quick": bool(job.get("quick")),
        "thumb": job.get("thumb", ""), "thumb_text": job.get("thumb_text", ""),
        "chapters": [{"t": round(sum(x["dur"] for x in job["beats"][:n])), "heading": b["heading"]} for n, b in enumerate(job["beats"]) if b.get("heading")],
        "screenplay": [{"text": b["text"], "seconds": round(b["dur"], 2), "query": b["query"], "footage": (b.get("visual") or {}).get("page", ""),
                        **({"cue": b["cue"]} if b.get("cue") else {})} for b in job["beats"]],
        "credits": sorted({b["visual"]["credit"] for b in job["beats"] if b.get("visual")})})
    store.kv_put(SEEN, job["key"], {"state": "done"})


def next_slot(store, ch: dict, now: float | None = None, fmt: str = "short") -> float:
    """The publishing time for the next video: the first of the channel's publish_times after the last one already
    scheduled (the releases form one queue, in upload order), and at least half an hour away. Long videos have
    their own queue, one a day at long.publish_time, so they never take a Short's slot."""
    now = now or time.time()
    taken = [v["publish_at"] for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("publish_at") and v.get("status") != "deleted"
             and (v.get("format") == "long") == (fmt == "long")]
    after = max([now + 1800] + [t + 60 for t in taken])
    lt = time.localtime(after)
    for day in range(3):
        for hm in sorted([long_of(ch)["publish_time"]] if fmt == "long" else ch["publish_times"]):
            h, m = (int(x) for x in str(hm).split(":"))
            ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + day, h, m, 0, 0, 0, -1))
            if ts > after:
                return ts
    return after + 86400


def made_today(store, ch: dict, fmt: str | None = None, quick: bool = False) -> int:
    # by the day it was made (a later status or stats update re-saves the record); a reset starts the day's count again
    start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
    return sum(v.get("channel") == ch["id"] and (v.get("made") or 0) >= start and (fmt is None or (v.get("format") == "long") == (fmt == "long"))
               and (not quick or bool(v.get("quick"))) for v in store.kv_list(LOG))


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
        ch, store = self.ch, ctx["store"]
        L, now = long_of(ch), time.strftime("%H:%M")
        shorts, longs = made_today(store, ch, "short"), made_today(store, ch, "long")
        short_due, long_due = shorts < ch["shorts_per_day"], bool(L["enabled"]) and longs < L["per_day"]
        if not short_due and not long_due:
            return AgentResult("idle", "QUOTA MET", f"{shorts} of {ch['shorts_per_day']} Shorts made today" + (f", {longs} of {L['per_day']} long" if L["enabled"] else ""))
        waiting = sum(v.get("channel") == ch["id"] and v.get("status") == "ready" for v in store.kv_list(LOG))
        if waiting >= max(1, ch["shorts_per_day"] + (L["per_day"] if L["enabled"] else 0)):    # a day's worth is piling up unsent (YouTube's upload limit)
            return AgentResult("idle", "BACKLOG", f"{waiting} finished videos are waiting to upload; no new ones until they go")
        short_now = short_due and not (ch["create_after"] and now < ch["create_after"])      # neither kind is started before its hour
        long_now = long_due and not (L["create_after"] and now < L["create_after"])
        if not short_now and not long_now:
            return AgentResult("idle", "NOT YET", f"Today's Shorts start at {ch['create_after']}" if short_due else f"Today's long video starts at {L['create_after']}")
        res = None
        if short_now:
            res = await self._short(ctx)
            if ctx.get("job"):
                return res
        if long_now:                                 # the day's long video: a classic rich enough to tell over several minutes
            c = await self._classic(ctx, long=True)
            if c:
                return AgentResult("done", "LONG", f"A long video: “{c['title']}” by {c['author']}", {"source": ctx["job"]["source"]})
        return res or AgentResult("idle", "NOTHING NEW", "No story on the shelf is long enough for a long video")

    async def _short(self, ctx: dict) -> AgentResult:
        """Find the next Short's story: viewers' comments and Mani's own stories, then a classic, then an original."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
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
                return AgentResult("done", "INVENTED", f"An original {ctx['job']['genre']} story" + (" (a quick one)" if ctx["job"].get("quick") else "") + f": “{p['title'][:70]}”", {"source": ctx["job"]["source"]})
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

    async def _classic(self, ctx: dict, long: bool = False) -> dict | None:
        """The next unused story from the shelf of public-domain books (taking from the least-used book): for a Short at
        most classics_per_day; for a long video only stories with enough in them to fill it. A story is told once, in one form."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
        today = sum(v.get("channel") == ch["id"] and v.get("kind") == "classic" and v.get("format") != "long" and (v.get("made") or 0) >= start
                    for v in store.kv_list(LOG))
        if not ch["classics"] or (not long and today >= ch["classics_per_day"]):
            return None
        least = long_of(ch)["min_source_words"] if long else 0
        used = {v["_key"] for v in store.kv_list(CLASSICS, limit=5000)}
        for _ in range(6):                            # a story the rules screen out is marked and the next one is tried
            best = None
            for bid in ch["classics"]:
                try:
                    rows = await gutenberg.shelve(int(bid), self.client() if self.opts.get("client_factory") else None)
                except (RuntimeError, httpx.HTTPError) as e:
                    bus.say(f"⚠ {ch['name']} · book {bid} could not be fetched: {e}")
                    continue
                free = [r for r in rows if f"{ch['id']}:{bid}:{r['n']}" not in used and r["words"] >= least]
                told = sum(f"{ch['id']}:{bid}:{r['n']}" in used for r in rows)
                if free and (best is None or told < best[0]):
                    best = (told, int(bid), free[0])
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
            work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{'long-' if long else ''}{slug}"
            work.mkdir(parents=True, exist_ok=True)
            cite = {"title": row["title"], "author": row["author"], "book": row["book"], "url": gutenberg.page(bid)}
            tag = "long" if long else "classic"
            ctx["job"] = {"id": f"{ch['id']}-{tag}-{bid}-{row['n']}", "key": f"{ch['id']}:{tag}-{bid}-{row['n']}", "channel": ch["id"], "dir": str(work),
                          "format": "long" if long else "short", "raw": text, "classic": cite, "source": {"url": cite["url"], "title": row["title"], "from": "classic", "score": None}}
            return cite
        return None

    def _mixes(self, genre: str, bank: list[dict], rng) -> list[tuple[str, str]]:
        """Eight (seed, ingredient line) pairs for a genre. A science subject is not taken twice while others are still unused."""
        if genre == "science":
            taken = {p.get("seed") for p in bank}
            subjects = [(d, t) for d, ts in SCIENCE.items() for t in ts]
            pool = [x for x in subjects if f"{x[0]}: {x[1]}" not in taken] or subjects
            return [(f"{d}: {t}", f"{d}: {t}; told {rng.choice(ANGLES)}") for d, t in rng.sample(pool, min(8, len(pool)))]
        if genre == "money":
            taken = {p.get("seed") for p in bank}
            pool = [t for t in MONEY if t not in taken] or MONEY
            return [(t, t) for t in rng.sample(pool, min(8, len(pool)))]
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

    def _lean(self, options: list[str], told: dict[str, int], views: dict[str, float]) -> str:
        # the floor is held to 70% of the whole, so a long list (seven patterns) still leaves something to lean on
        return choose(options, told, views, min(self.ch["explore"], 0.7 / len(options)))

    async def _original(self, ctx: dict) -> dict | None:
        ch, store = self.ch, ctx["store"]
        everything = [p for p in store.kv_list(PREMISES, limit=5000) if p.get("channel") == ch["id"]]
        genres = [g for g in ch["original_genres"] if g in GENRE_ASK] or ["confession"]
        told = {g: sum(p.get("used") and p.get("genre", "confession") == g for p in everything) for g in genres}
        log = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"]]
        insights = store.kv_get(STATE, f"{ch['id']}:insights") or {}
        learned = ch["double_down"] and insights.get("videos", 0) >= ch["double_down_after"]       # enough results to lean on
        if learned:
            by_kind = insights.get("views_by_kind") or {}
            genre = self._lean(genres, told, {g: by_kind["original" if g == "confession" else g] for g in genres if ("original" if g == "confession" else g) in by_kind})
        else:
            genre = min(genres, key=lambda g: told[g])             # the kind told least so far, so the kinds take turns
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
        if genre in ("money", "science"):            # a learning video follows one of the watch-to-the-end patterns, the least used so far
            used = [v.get("structure") for v in log]
            shapes = list(STRUCTURES)
            ctx["job"]["structure"] = (self._lean(shapes, {k: used.count(k) for k in shapes}, insights.get("views_by_structure") or {})
                                       if learned else min(shapes, key=used.count))
        Q = quick_of(ch)
        if Q["per_day"] and made_today(store, ch, quick=True) < Q["per_day"]:      # a short, sharp one among the day's Shorts
            ctx["job"]["quick"] = True
        return p


class StoryWriter(Crew):
    name, tier, note = "Story Writer", "CLOUD", "retells it with a hook, names and places removed"

    async def _long(self, ctx: dict, job: dict) -> AgentResult:
        """A long retelling, written chapter by chapter: each request carries only its own part of the original, so
        the whole stays inside the hosted model's per-minute allowance and no chapter is rushed."""
        L, cite, src = long_of(self.ch), job["classic"], job["raw"]
        total = max(L["minutes"][0] * 150, min(L["minutes"][1] * 150, int(words(src) * 0.55)))      # about 150 spoken words a minute
        pieces = parts(src, max(3, min(6, round(words(src) / 700))))
        per, chapters = total // len(pieces), []
        for k, piece in enumerate(pieces):
            where = ("Open with one sentence that hooks a listener, then begin the story." if k == 0 else
                     "This is the end of the story: keep the author's own ending, and add no moral of your own." if k == len(pieces) - 1 else
                     "Do not wrap anything up: the story goes on in the next part.")
            prev = f"- The part before this one ended: “{' '.join(chapters[-1]['text'].split()[-45:])}” Carry straight on from there; do not repeat it.\n" if chapters else ""
            prompt = (f"You are retelling the classic short story “{cite['title']}” by {cite['author']} for a narrated video, in {len(pieces)} parts. "
                      f"This is part {k + 1}.\n"
                      f"- Retell only this part, faithfully, in {int(per * 0.8)}-{int(per * 1.25)} words: the same characters and events, in order; the turns of the story "
                      "matter more than every line of talk. Add nothing.\n"
                      "- Third person, your own plain spoken sentences, easy to follow by ear; do not copy the author's sentences. Character names may stay.\n"
                      f"- {OLD_WORDS}\n"
                      f"- {where}\n{prev}"
                      'Answer as {"heading": "2-5 words naming this part, giving nothing away", "text": "..."}.\n\n'
                      f"This part of the original:\n{piece}")
            note, best = "", None
            for _ in range(3):                         # a part heavy with dialogue comes back long: ask again, then take the nearest
                d = await ctx["llm"].json(prompt + note, tier="writer", max_tokens=2600)
                text = " ".join(str((d or {}).get("text") or "").split()) if isinstance(d, dict) else ""
                if words(text) >= min(80, per * 0.5) and (best is None or abs(words(text) - per) < abs(words(best["text"]) - per)):
                    best = {"heading": " ".join(str(d.get("heading") or f"Part {k + 1}").split())[:50], "text": text}
                if per * 0.6 <= words(text) <= per * 1.5:
                    break
                note = f"\n\nYour last answer had {words(text)} words. This part must be between {int(per * 0.8)} and {int(per * 1.25)} words, as JSON."
            if not best:
                raise RuntimeError(f"the model did not return part {k + 1} of {len(pieces)}")
            chapters.append(best)
        job["chapters"], job["script"] = chapters, " ".join(c["text"] for c in chapters)
        meta = await ctx["llm"].json(
            f"For a narrated video retelling “{cite['title']}” by {cite['author']}, answer as "
            '{"title": "under 70 characters, built around the story\'s own title", "thumbnail": "2-5 words for the cover image that make someone click, '
            'giving nothing away", "thumbnail_image": "2-4 words: one concrete thing to photograph for the cover", "summary": "two sentences for the '
            f'description, giving nothing away", "hashtags": ["3 to 5 words, no #"], "mood": "one word: {" | ".join(MOODS)}"}}.\n\n'
            f"How it opens:\n{' '.join(job['script'].split()[:260])}", tier="writer", max_tokens=1200)
        meta = meta if isinstance(meta, dict) else {}
        job["title"] = " ".join(str(meta.get("title") or f"{cite['title']}, by {cite['author']}").split())[:90]
        job["thumb_text"] = " ".join(str(meta.get("thumbnail") or cite["title"]).split()[:6])
        job["thumb_query"] = " ".join(str(meta.get("thumbnail_image") or "").split())[:60]
        job["summary"] = " ".join(str(meta.get("summary") or "").split())[:400]
        job["hashtags"] = ["#" + re.sub(r"\W", "", str(h)) for h in (meta.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:5]
        mood = re.sub(r"[^a-z]", "", str(meta.get("mood") or "").lower())
        job["mood"] = mood if mood in MOODS else ""
        return AgentResult("done", "WRITTEN", f"“{job['title']}” · {words(job['script'])} words in {len(chapters)} chapters" + (f" · {job['mood']}" if job["mood"] else ""))

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if job.get("format") == "long":
            return await self._long(ctx, job)
        quick = bool(job.get("quick"))
        lo, hi = word_range(self.ch, quick)
        pad = 3 if quick else 20                                 # a quick story's range is narrow: keep its target inside it
        length = f"a {'-'.join(str(x) for x in quick_of(self.ch)['seconds'])} second video" if quick else "a 1-2 minute video"
        ending = ENDINGS.get(self.ch["ending"], ENDINGS["plain"])
        head, rules = GENRE_WRITE.get(job.get("genre") or "confession", GENRE_WRITE["confession"])
        science, learning = job.get("genre") == "science", job.get("structure") in STRUCTURES
        shape = f"- Build it exactly like this: {STRUCTURES[job['structure']]}\n- {HOLD_BACK}\n" if learning else f"- {RETAIN_STORY}\n"
        close = ("End on the one thing to remember or do." if job.get("genre") == "money" else "End on what it means for us, or the wonder of it." if science else ending)
        prompt = (f"{head}, narrated for {length}, {lo + pad}-{hi - pad} words.\n"
                  "- The first sentence is a hook that makes someone stop scrolling (never say \"stop scrolling\" or speak to the scrolling itself).\n"
                  + shape + rules + "- It will be read aloud: no brackets, no labels such as \"Step 1:\"; say \"first\", \"then\", \"and the most useful one\".\n" +
                  "- Short spoken sentences. " + close + " No call to subscribe.\n"
                  'Answer as {"title": "under 70 characters, no names", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"Premise:\n{job['raw']}") if job.get("original") else (
                  f"Retell the classic short story below for {length}, {lo + pad}-{hi - pad} words.\n"
                  "- Stay faithful: the same characters, events and the author's own ending. Do not modernise it or add a moral of your own.\n"
                  "- Third person, in your own plain spoken sentences; do not copy the author's sentences. Character names from the story may stay.\n"
                  f"- {OLD_WORDS}\n"
                  "- The first sentence is a hook that makes someone stop scrolling. No call to subscribe.\n"
                  f'Answer as {{"title": "under 70 characters, built around the story\'s own title", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"“{job['classic']['title']}” by {job['classic']['author']}:\n{job['raw'][:40000]}") if job.get("classic") else (
                  f"Retell the confession below as a narrated story for {length}, {lo + pad}-{hi - pad} words.\n"
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
            if job.get("genre") == "money" and (TOLD_PROMISE.search(story) or promises(str((d or {}).get("title") or ""))):
                note = ("\n\nYour last answer promised or suggested an amount, a speed or a certainty of earning. Write it again with no such promise: "
                        "what it costs, how long it takes and what can go wrong, as JSON.")
                continue
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
        if job.get("format") == "long":             # chapter by chapter; the picture changes every few sentences, not every one
            beats: list[dict] = []
            for k, chp in enumerate(job["chapters"]):
                mine = screenplay(chp["text"], "")
                if mine:
                    mine[0]["heading"] = chp["heading"]
                beats += [{**b, "chapter": k} for b in mine]
            beats += screenplay(f"This was a retelling of “{job['classic']['title']}”, by {job['classic']['author']}.", self.ch["outro"])
            shot, run, need = 0, 0.0, long_of(self.ch)["shot_seconds"]
            for i, b in enumerate(beats):
                last = i + 1 == len(beats) or beats[i + 1]["kind"] == "outro" or beats[i + 1].get("chapter") != b.get("chapter")
                b["i"], b["shot"] = i, shot
                run += b["target_s"]
                if run >= need or last or b["kind"] == "outro":
                    shot, run = shot + 1, 0.0
            job["beats"] = beats
            plan = sum(b["target_s"] for b in beats)
            return AgentResult("done", "TIMED", f"{len(beats)} beats in {shot} shots, about {clock(plan)}")
        told = job["script"]
        if job.get("classic"):                      # the citation is spoken, as the story's last line
            told += f" A retelling of “{job['classic']['title']}”, by {job['classic']['author']}."
        job["beats"] = screenplay(told, quick_of(self.ch)["outro"] if job.get("quick") else self.ch["outro"])
        for b in job["beats"]:
            b["shot"] = b["i"]                      # in a Short every beat has its own picture
        plan = sum(b["target_s"] for b in job["beats"])
        return AgentResult("done", "TIMED", f"{len(job['beats'])} beats, about {round(plan)} s")


class KeywordGenerator(Crew):
    name, tier, note = "Keyword Generator", "CLOUD", "one footage search per beat"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        groups: dict[int, list[dict]] = {}
        for b in job["beats"]:
            if b["kind"] == "story":
                groups.setdefault(b.get("shot", b["i"]), []).append(b)
        shots, modelled = list(groups.values()), True
        for at in range(0, len(shots), 30):           # a long video has more shots than one request should carry
            batch = shots[at:at + 30]
            listing = "\n".join(f"{n + 1}. {' '.join(x['text'] for x in g)[:320]}" for n, g in enumerate(batch))
            got = None
            try:
                got = await ctx["llm"].json(
                    "For each numbered line of this story give one stock-footage search of 2-4 words: a concrete thing a camera could film that fits the "
                    "line (\"woman staring out rainy window\", not \"sadness\"). No names, no text on screen. "
                    f'Answer as a JSON list of exactly {len(batch)} strings, in order.\n\n{listing}', tier="writer", max_tokens=1800)
            except Exception:
                pass                              # no model: plain keywords from the line itself
            ok = isinstance(got, list) and len(got) == len(batch)
            modelled = modelled and ok
            for n, g in enumerate(batch):
                q = str(got[n]).strip()[:60] if ok and str(got[n]).strip() else fallback_query(g[0]["text"])
                for x in g:
                    x["query"] = q
        for b in job["beats"]:
            b.setdefault("query", self.ch["outro_query"])
        job["keywords"] = [b["query"] for b in job["beats"]]
        cues = await self._cues(ctx, shots) if self.ch["sfx"] else 0
        return AgentResult("done", "DONE", f"{len(shots) + 1} searches" + ("" if modelled else " (plain keywords where the model gave none)")
                           + (f", {cues} sound cue{'s' if cues != 1 else ''}" if self.ch["sfx"] else ""))

    async def _cues(self, ctx: dict, shots: list[list[dict]]) -> int:
        """Ask which lines call for a sound, and which one. Most get none; a line gets a sound only if the moment needs it."""
        kinds = [k for k in CUES if sfx.tracks(k)]              # only sounds the library actually has
        if not kinds:
            return 0
        given = 0
        for at in range(0, len(shots), 35):
            batch = shots[at:at + 35]
            listing = "\n".join(f"{n + 1}. {' '.join(x['text'] for x in g)[:260]}" for n, g in enumerate(batch))
            got = None
            try:
                got = await ctx["llm"].json(
                    "This narration will have a few sound effects. For each numbered line name the one sound the moment truly calls for, or \"none\". "
                    f"Most lines need none: a sound belongs only where it makes a listener feel that moment more. At most {max(1, len(batch) // 5)} "
                    "lines in all, and never two lines in a row. Choose only from: " + "; ".join(f"{k} ({CUES[k]})" for k in kinds) + ". "
                    f'Answer as a JSON list of exactly {len(batch)} strings, in order.\n\n{listing}', tier="writer", max_tokens=1200)
            except Exception:
                pass                              # no model: no sound effects, which is always safe
            if not (isinstance(got, list) and len(got) == len(batch)):
                continue
            for g, cue in zip(batch, got):
                cue = re.sub(r"[^a-z]", "", str(cue).lower())
                if cue in kinds:
                    g[0]["cue"] = cue
                    given += 1
        return given


class SEOStrategist(Crew):
    """Packages a video so it can be found and gets the click: the title, the first lines of the description and the
    search tags. It starts from what people really type into YouTube's search box and from the titles that have done
    best on this channel so far, and it never promises what the story doesn't deliver. If it fails, the writer's own
    title stands and the video is made all the same."""
    name, tier, note, blocking = "SEO Strategist", "CLOUD", "title, description and tags from real searches", False

    def seeds(self, job: dict) -> list[str]:
        what = {"science": "science explained", "money": "personal finance tips", "motivational": "motivational story", "classic": "short story", "viewer": "confession story",
                "real": "confession story", "original": "confession story"}[kind(job)]
        mine = " ".join(w for w in re.findall(r"[A-Za-z]{4,}", job.get("title", "")) if w.lower() not in STOP)
        out = [what, " ".join(mine.split()[:3])]
        if job.get("classic"):
            out.append(f"{job['classic']['title']} {job['classic']['author']}")
        if job.get("genre") in ("science", "money"):
            out.append(" ".join(job["source"]["title"].split()[:4]))
        return [x for x in dict.fromkeys(out) if x.strip()]

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        ch, before = self.ch, job["title"]
        searched: list[str] = []
        async with self.client() as c:
            for phrase in self.seeds(job)[:3]:
                searched += await yt_suggest.suggest(c, phrase)
        searched = list(dict.fromkeys(searched))[:24]
        learned = (ctx["store"].kv_get(STATE, f"{ch['id']}:insights") or {}).get("top_titles") or []
        fixed = (f" It retells “{job['classic']['title']}” by {job['classic']['author']}: the story's title and the author's name must be in the title."
                 if job.get("classic") else "")
        d = await ctx["llm"].json(
            f"You package a {'long video' if job.get('format') == 'long' else 'YouTube Short'} for the channel “{ch['name']}” so that it is found in "
            f"search and people choose to watch it.{fixed}\n"
            "- title: under 60 characters, the strongest words first, plain sentence case, honest: it may only promise what the story delivers. No "
            "capitals for emphasis, no emoji, no \"you won't believe\", and never call fiction true.\n"
            + ("- This is a lesson: the title is an open question that the video explores and does not answer in the title (\"How can we make money "
               "from this?\", \"Can you really live on one income?\", \"Everybody makes money, but at what cost?\"). It asks; it never states an "
               "amount, a speed or a certainty of earning.\n" if job.get("structure") else "") +
            "- lead: one or two sentences for the top of the description that say what the video is, using the main search phrase early and naturally.\n"
            "- tags: 8 to 12 search phrases of 2-4 words that someone looking for exactly this video would type, the most specific first. Leave out any "
            "that describe a different video: another language, \"for kids\", \"animated\", \"official\", and \"real life\" or \"true\" for fiction.\n"
            "- hashtags: exactly 3 single words, no #.\n"
            + ("Phrases people are typing into YouTube's search right now (use the ones that truly fit, ignore the rest): " + "; ".join(searched) + "\n" if searched else "")
            + ("Titles that have done best on this channel so far (learn their shape, do not copy them): " + "; ".join(learned[:5]) + "\n" if learned else "")
            + 'Answer as {"title": "...", "lead": "...", "tags": ["..."], "hashtags": ["..."]}.\n\n'
            f"Working title: {before}\nKind: {kind(job)}\nHow it opens:\n{' '.join(job['script'].split()[:150])}", tier="writer", max_tokens=900)
        if not isinstance(d, dict):
            return AgentResult("done", "KEPT", f"No packaging from the model; the writer's title stands: “{before}”")
        title = " ".join(str(d.get("title") or "").split()).strip("\"“” ")
        title = title[:1].upper() + title[1:]          # sentence case still starts with a capital
        if 15 <= len(title) <= 70 and not (job.get("original") and re.search(r"\btrue\b", title, re.I)) and not (kind(job) == "money" and promises(title)):
            job["title"] = title
        tags, size = [], 0
        wrong = r"\b(for kids|animated|official|in (hindi|tamil|telugu|urdu|nepali|tagalog|malayalam|punjabi|spanish))\b" + (
            r"|\b(real life|true)\b" if kind(job) in ("original", "motivational") else "") + (
            r"|\b(get rich|rich quick|overnight|guarantee\w*|easy money|free money)\b" if kind(job) == "money" else "")
        wrong += r"|\b(usa|uk|india|canada|australia|philippines)\b"
        mine = set(re.findall(r"[a-z]{4,}", (job["title"] + " " + job["script"]).lower())) - STOP
        seeds = {x.lower() for x in self.seeds(job)}
        for t in d.get("tags") or []:                 # YouTube allows about 500 characters of tags in all
            t = " ".join(re.sub(r"[<>#,]", " ", str(t)).split())
            if not (t.lower() in seeds or mine & set(re.findall(r"[a-z]{4,}", t.lower()))):
                continue                              # a phrase with nothing in common with the video is someone else's search
            if t and len(t) <= 40 and not re.search(wrong, t, re.I) and size + len(t) + 3 <= 430 and t.lower() not in (x.lower() for x in tags):
                tags.append(t)
                size += len(t) + 3
        hashtags = ["#" + re.sub(r"\W", "", str(h)) for h in (d.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:3]
        if len(hashtags) == 3:
            job["hashtags"] = hashtags
        job["seo"] = {"lead": " ".join(str(d.get("lead") or "").split())[:300], "tags": tags, "searched": searched[:12], "title_before": before}
        return AgentResult("done", "PACKAGED", f"“{job['title']}” · {len(tags)} search tags · from {len(searched)} real searches"
                           + (f", {len(learned[:5])} of our best titles" if learned else ""))


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
        wide = job.get("format") == "long"
        shots: dict[int, dict | None] = {}             # one clip or photo per shot; the beats of a shot share it
        async with self.client() as c:
            for b in job["beats"]:
                sid = b.get("shot", b["i"])
                if sid in shots:
                    b["visual"] = shots[sid]
                    continue
                b["visual"] = shots[sid] = None
                hit = await stock_video.find(c, b["query"], used, wide=wide) or await stock_video.find(c, fallback_query(b["text"]), used, wide=wide)
                if not hit:
                    continue
                path = folder / f"shot{sid:03d}.{'mp4' if hit['kind'] == 'video' else 'jpg'}"
                try:
                    await stock_video.download(c, hit["url"], path)
                except httpx.HTTPError:
                    continue
                b["visual"] = shots[sid] = {**{k: hit[k] for k in ("kind", "duration", "credit", "page", "source")}, "path": str(path)}
        have = [v for v in shots.values() if v]
        clips = sum(v["kind"] == "video" for v in have)
        return AgentResult("done", "COLLECTED", f"{len(have)} of {len(shots)} shots have footage ({clips} clips, {len(have) - clips} photos)")


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
        wide = job.get("format") == "long"
        turn = sum(v.get("mood") == job.get("mood") and v.get("channel") == self.ch["id"] for v in ctx["store"].kv_list(LOG))   # moves the look and the effects on, as the music
        look = fonts.style_for(job.get("mood") or "", kind(job), turn) if self.ch["caption_styles"] else None
        if look and wide:
            look["position"] = "lower"                  # a wide frame keeps its captions low
        job["caption"] = " · ".join(x for x in (look["font_name"], look["fill"], look["highlight"]) if x) if look else ""
        plan = sfx_plan(job["beats"], volume=float(self.ch["sfx_volume"]), turn=turn) if self.ch["sfx"] else None
        out = await asyncio.to_thread(shorts_edit.assemble, Path(job["dir"]), job["beats"], channel=self.ch["name"],
                                      logo=self.ch["logo"] or None, font_path=self.ch["caption_font"] or None,
                                      music=str(track[0]) if track else None, music_volume=float(self.ch["music_volume"]), wide=wide,
                                      motion=bool(self.ch["motion"]), style={k: v for k, v in look.items() if k != "font_name"} if look else None, sfx=plan)
        job["file"], job["seconds"], job["sfx"] = out["file"], out["seconds"], out.get("sfx", 0)
        if wide:
            job["thumb"] = await self._thumbnail(job)
        for part in ("build", "footage", "audio"):            # the downloads and working files are large; the log keeps their sources
            shutil.rmtree(Path(job["dir"]) / part, ignore_errors=True)
        save_record(ctx["store"], self.ch, job)
        what = f"{clock(out['seconds'])} long video, {out['shots']} shots" + (", thumbnail made" if job.get("thumb") else ", no thumbnail") if wide else f"{out['seconds']} s Short"
        font = f" in {look['font_name']}" if look else ""
        return AgentResult("done", "CUT", f"{what}, {out['captions']} captions{font}, {job['sfx']} sound effects" + (", with music" if track else ", no music"))

    async def _thumbnail(self, job: dict) -> str:
        """The cover for a long video: a photo for the story (else a frame of the video itself) with the writer's few words on it."""
        work = Path(job["dir"])
        src, out = work / "thumb_src.jpg", work / "thumb.jpg"
        try:
            hit = None
            if job.get("thumb_query") and stock_video.configured():
                async with self.client() as c:
                    hit = await stock_video.photo(c, job["thumb_query"])
                    if hit:
                        await stock_video.download(c, hit["url"], src)
            if not hit:
                await asyncio.to_thread(shorts_edit.run, ["ffmpeg", "-y", "-v", "error", "-ss", f"{job['seconds'] * 0.15:.1f}", "-i", job["file"], "-frames:v", "1", str(src)])
            await asyncio.to_thread(shorts_edit.thumbnail, out, src, job.get("thumb_text") or job["title"], self.ch["name"], self.ch["caption_font"] or None)
            src.unlink(missing_ok=True)
            return str(out)
        except Exception:
            return ""


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
        long = rec.get("format") == "long"
        tags = list(dict.fromkeys(rec["hashtags"] + ([] if long else ["#Shorts"])))
        when = next_slot(ctx["store"], ch, fmt="long" if long else "short") if ch["privacy"] == "scheduled" else None     # private now, public by itself at its slot
        marks = rec.get("chapters") or []           # YouTube shows chapters from three or more timestamps starting at 0:00
        chapters = "\n\n" + "\n".join(f"{clock(m['t'])} {m['heading']}" for m in marks) if long and len(marks) >= 3 and marks[0]["t"] == 0 else ""
        seo = rec.get("seo") or {}                  # the strategist's search tags and opening lines, when it gave them
        body = {"snippet": {"title": rec["title"][:100], "categoryId": str(ch["category"]), "tags": seo.get("tags") or [t.lstrip("#") for t in tags],
                            "description": (seo["lead"] + "\n\n" if seo.get("lead") else "") + (rec["summary"] + "\n\n" if long and rec.get("summary") else "")
                            + " ".join(tags) + (f"\n\n{ch['cta']}" if ch["cta"] else "")
                            + _about(rec) + chapters
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
        long = rec.get("format") == "long"
        name = long_of(ch)["playlist"] if long else (ch["playlists"] or {}).get(rec.get("kind") or "")
        thumb = rec.get("thumb") if long and Path(rec.get("thumb") or "-").exists() else ""
        if not (name or ch["cta"] or thumb) or not can_manage(ctx, ch):
            return ""
        auth, notes = {"Authorization": f"Bearer {token}"}, []
        try:
            if thumb:
                r = await c.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": rec["video_id"], "uploadType": "media"},
                                 content=Path(thumb).read_bytes(), headers={**auth, "Content-Type": "image/jpeg"})
                notes.append("thumbnail set" if r.status_code == 200 else f"thumbnail failed: {_reason(r)}")
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
                    for attempt in range(3):          # YouTube now and then answers "the operation was aborted" on a fresh upload: ask again
                        r = await c.post(API + "/playlistItems", params={"part": "snippet"}, headers=auth,
                                         json={"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": rec["video_id"]}}})
                        if r.status_code == 200:
                            break
                        await asyncio.sleep(4)
                notes.append(f"in “{name}”" if pid and r.status_code == 200 else f"playlist failed: {_reason(r)}")
            if ch["cta"] and rec.get("status") in ("public", "unlisted"):     # a private (scheduled) video takes no comments: the Analytics
                if await post_invitation(c, auth, ch, rec["video_id"]):        # Manager posts the invitation once it has gone public
                    rec["cta_done"] = True
                else:
                    notes.append("comment failed")
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
                    bus.notice(f"youtube-limit-{ch['id']}", f"{ch['name']}: YouTube itself is refusing uploads for now (its own cap per channel per day, not VISION's count). "
                                                            f"{left} finished Short{'s' if left != 1 else ''} kept; they upload by themselves on a later run. Nothing to do.")
                    return AgentResult("wait", "UPLOAD LIMIT", (f"Uploaded as {ch['privacy']}: " + "; ".join(done) + ". " if done else "")
                                       + f"YouTube's daily upload limit reached; {left} waiting")
                bus.clear_notice(f"youtube-limit-{ch['id']}")
                key = rec.pop("_key")
                rec.pop("_ts", None)
                rec.update(status=ch["privacy"], video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time(), publish_at=out["publish_at"])
                store.kv_put(LOG, key, rec)
                extras = await self._extras(ctx, c, token, rec)
                store.kv_put(LOG, key, rec)
                when = time.strftime(" for %a %H:%M", time.localtime(out["publish_at"])) if out["publish_at"] else ""
                if when:                                   # no review step: it goes public by itself
                    bus.say(f"{ch['name']} · “{rec['title']}” goes public{when.replace(' for', '')}")
                else:
                    review_notice(bus, ch, rec)
                done.append(rec["title"] + when + extras)
        return AgentResult("done", "UPLOADED", f"Uploaded as {ch['privacy']}: " + "; ".join(f"“{t}”" if " for " not in t else t for t in done))


async def post_invitation(c: httpx.AsyncClient, auth: dict, ch: dict, video_id: str) -> bool:
    """The channel's own comment under a video, inviting viewers' confessions. Only a public or unlisted video can take it."""
    try:
        r = await c.post(API + "/commentThreads", params={"part": "snippet"}, headers=auth,
                         json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": ch["cta"]}}}})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _about(rec: dict) -> str:
    """One line on where the story comes from, for the description."""
    c = rec.get("classic")
    if c:
        return f"\n\nRetold from “{c['title']}” by {c['author']}, in “{c['book']}” (public domain): {c['url']}"
    return {"original": "\n\nThis story is fiction.", "motivational": "\n\nThis story is fiction.",
            "money": "\n\nFor education only. This is not financial advice.",
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
        invite = bool(self.ch["cta"]) and "youtube.force-ssl" in oauth.granted(account(self.ch))
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
            if invite and v["status"] == "public" and not v.get("cta_done"):     # it has gone public: now it can take the channel's invitation
                async with self.client() as c2:
                    v["cta_done"] = await post_invitation(c2, {"Authorization": f"Bearer {token}"}, self.ch, v["video_id"])
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
        seen = [v for v in log if v["status"] == "public" and (v.get("stats") or {}).get("view", 0) > 0]      # what the channel's own results teach
        by_kind: dict[str, list[int]] = {}
        for v in seen:
            by_kind.setdefault(v.get("kind") or "real", []).append(v["stats"]["view"])
        by_shape: dict[str, list[int]] = {}
        for v in seen:
            if v.get("structure"):
                by_shape.setdefault(v["structure"], []).append(v["stats"]["view"])
        by_len: dict[str, list[int]] = {}
        for v in seen:
            if v.get("format") != "long":
                by_len.setdefault("quick" if v.get("quick") else "regular", []).append(v["stats"]["view"])
        insights = {"top_titles": [v["title"] for v in sorted(seen, key=lambda v: v["stats"]["view"], reverse=True)[:5]],
                    "views_by_kind": {k: round(sum(x) / len(x)) for k, x in by_kind.items()}, "videos": len(seen)}
        if by_shape:
            insights["views_by_structure"] = {k: round(sum(x) / len(x)) for k, x in by_shape.items()}
        if by_len:
            insights["views_by_length"] = {k: round(sum(x) / len(x)) for k, x in by_len.items()}
        ctx["store"].kv_put(STATE, f"{ch['id']}:insights", insights)
        latest = log[0]
        return AgentResult("done", "LOGGED", f"{ch['name']}: {', '.join(parts)}; latest “{latest['title']}” ({round(latest['seconds'])} s)",
                           {"channel": ch["id"], "made": len(log), **n, "views": views,
                            "videos": [{k: v.get(k) for k in ("title", "status", "url", "seconds", "stats", "source")} for v in log[:20]]})


def crew(ch: dict, **opts: Any) -> list[Stage]:
    return [Stage("SOURCE", [StoryScout(ch, **opts)]), Stage("STORY", [StoryWriter(ch)]), Stage("SCREENPLAY", [ScreenplayWriter(ch)]),
            Stage("PREP", [KeywordGenerator(ch), VoiceArtist(ch, **opts), SEOStrategist(ch, **opts)]), Stage("FOOTAGE", [FootageCollector(ch, **opts)]),
            Stage("GENERATE", [FootageGenerator(ch, **opts)]), Stage("EDIT", [Editor(ch, **opts)]), Stage("UPLOAD", [Uploader(ch, **opts)]),
            Stage("REPORT", [AnalyticsManager(ch, **opts)])]


def reset_today(store, channel_id: str) -> None:
    """Start today's count for a channel again: Shorts made before this moment no longer count toward shorts_per_day."""
    store.kv_put(STATE, f"{channel_id}:quota_reset", {"at": time.time()})


def more_today(ch: dict):
    """One pass of the crew makes one Short. Go round again while the last pass made one and the day's number isn't reached."""
    L = long_of(ch)
    return lambda ctx: bool((ctx.get("job") or {}).get("file")) and (
        made_today(ctx["store"], ch, "short") < ch["shorts_per_day"] or (bool(L["enabled"]) and made_today(ctx["store"], ch, "long") < L["per_day"]))


def build_agents(options: dict, cfg) -> dict[str, SubAgent]:
    out: dict[str, SubAgent] = {}
    for raw in options.get("channels") or [{}]:
        ch = channel(raw)
        out[ch["director"]] = Director(ch["director"], crew(ch), reporter="Analytics Manager", again=more_today(ch), note=f"runs {ch['name']}")
    return out
