"""YouTube Manager: the Director tier, the channel crew end to end (Reddit, stock footage and the model mocked; ffmpeg real)."""

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from PIL import Image

from vision.agents import AgentResult, Director, Master, Stage, SubAgent
from vision.bus import EventBus, Store
from vision.config import Config, LLMConfig
from vision.masters import shorts_edit, youtube
from vision.services import bgm, fonts, genmedia, gutenberg, oauth, reddit, sfx, stock_video
from vision.services.llm import LLM

FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
TALE = "Old Behrman had always meant to paint a masterpiece, and never had. " * 40
BOOK = ("Title: The Four Million\nAuthor: O. Henry\n\n*** START OF THE PROJECT GUTENBERG EBOOK THE FOUR MILLION ***\n\nCONTENTS\n\nThe Last Leaf\n\n"
        f"THE LAST LEAF\n\n{TALE}\n\nA SHORT NOTE\n\nToo brief to be a story.\n\nTHE COP AND THE ANTHEM\n\n{TALE}\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK THE FOUR MILLION ***\nlicence text")
GOOD = ("I have carried this for eleven years and nobody in my family knows. " * 12).strip()


class WriterLLM:
    def __init__(self, safe=True, story_words=200, seo=None):
        self.safe, self.story_words, self.prompts, self.seo = safe, story_words, [], seo

    async def json(self, prompt, **kw):
        self.prompts.append(prompt)
        if prompt.startswith("You screen"):
            return {"ok": True, "why": ""} if self.safe else None
        if prompt.startswith("Plan short science") or prompt.startswith("Plan short lessons") or "motivational stories" in prompt[:60]:
            what = "science" if prompt.startswith("Plan short science") else "money" if prompt.startswith("Plan short lessons") else "motivational"
            body = {"money": "What does a minimum payment really cost? Interest is charged on what is left, so most of each payment is interest; paying a little more ends it years sooner.",
                    "science": "Why is the sea salty? Rain wears salts out of rock, rivers carry them down, and the sun lifts only the water back out.",
                    "motivational": "A single father fails his licence exam twice, nearly gives up, and passes by studying one page every night."}[what]
            return [{"title": f"A {what} one", "premise": body}]
        if prompt.startswith("Invent premises"):
            texts = ["A retired teacher kept quiet about the exam she let a struggling pupil pass, until an old letter turned up at a funeral.",
                     "A delivery driver pocketed a tip meant for a colleague, and a message sent to the wrong person brought it all out.",
                     "An eldest daughter told the family the shop was thriving while the bank statements said otherwise, until one was left open."]
            return [{"title": f"Premise {n + 1}", "premise": t} for n, t in enumerate(texts)] + [
                {"title": "Same again", "premise": texts[0].replace("funeral", "wedding")}, {"title": "Too thin", "premise": "Short."},
                {"title": "Dark", "premise": "A man planned a murder in a small town and nobody ever found out about it at all."}]
        if prompt.startswith("You package") and self.seo:
            return self.seo
        if prompt.startswith("You are retelling"):
            part = int(prompt.split("This is part ")[1].split(".")[0])
            return {"heading": f"Chapter {part}", "text": " ".join(("He climbed the stair once more that night and said nothing. " * 12).split()[:self.story_words])}
        if prompt.startswith("For a narrated video"):
            return {"title": "The Last Leaf, Retold", "thumbnail": "one last leaf", "thumbnail_image": "ivy leaf wall", "summary": "A painter. A promise.",
                    "hashtags": ["classic", "ohenry"], "mood": "sad"}
        if prompt.startswith("Retell") or prompt.startswith("Write a"):
            sentence = "She kept the letter in a drawer, and every year she almost threw it away. "
            return {"title": "The letter she never sent", "story": " ".join((sentence * 40).split()[:self.story_words]) + ".", "hashtags": ["confession", "#storytime"], "mood": "Sad"}
        return None                                    # keyword list: fall back to plain keywords


class Step(SubAgent):
    def __init__(self, name, fail=False, **kw):
        super().__init__(name=name, **kw)
        self.fail = fail

    async def run(self, ctx):
        if self.fail:
            raise RuntimeError("boom")
        ctx.setdefault("trail", []).append(self.name)
        return AgentResult(summary=f"{self.name} ok")


def run_master(m, tmp_path):
    bus, store = EventBus(), Store(tmp_path / "t.db")
    return asyncio.run(m.cycle(bus, store)), bus, store


def test_director_runs_its_crew_and_reports_up(tmp_path):
    d = Director("Dir", [Stage("A", [Step("One")]), Stage("B", [Step("Two"), Step("Three")])], reporter="Three")
    report, bus, store = run_master(Master("yt", "YT", [Stage("CH", [d])], reporter="Dir"), tmp_path)
    assert report == "Three ok"
    crew = {a["name"]: a for a in bus.state["masters"]["yt"]["agents"]}
    assert crew["Two"]["director"] == "Dir" and crew["Two"]["status"] == "done" and "director" not in crew["Dir"]
    assert store.last_run("yt", "One")["status"] == "done"
    with pytest.raises(ValueError):
        Director("Dir", [Stage("A", [Step("One")])], reporter="Nobody")


def test_director_crew_failure_blocks_the_rest(tmp_path):
    d = Director("Dir", [Stage("A", [Step("One", fail=True)]), Stage("B", [Step("Two")])], reporter="Two")
    report, bus, _ = run_master(Master("yt", "YT", [Stage("CH", [d])], reporter="Dir"), tmp_path)
    crew = {a["name"]: a for a in bus.state["masters"]["yt"]["agents"]}
    assert crew["One"]["status"] == "error" and crew["Two"]["label"] == "BLOCKED" and crew["Dir"]["status"] == "error"
    assert report == "Dir: One failed: boom"


def test_screenplay_beats_and_outro():
    beats = youtube.screenplay("She never told anyone. Not her husband, not her sister, and certainly not the woman who had trusted her with the key to the "
                               "house on that long, quiet afternoon. Then the phone rang.", "Subscribe for more.")
    assert beats[-1] == {"i": len(beats) - 1, "text": "Subscribe for more.", "target_s": 1.4, "kind": "outro", "end": True}
    assert [b["end"] for b in beats] == [False, False, True, True]          # the long sentence is spoken as one line across three beats
    durs, per = youtube.split_times(["She kept", "the letter."], 2.0, [["She", 0.0, 0.3], ["kept", 0.3, 0.7], ["the", 0.9, 1.0], ["letter", 1.0, 1.6]])
    assert durs == pytest.approx([0.8, 1.2]) and per[1] == [["the", pytest.approx(0.1), pytest.approx(0.2)], ["letter", pytest.approx(0.2), pytest.approx(0.8)]]
    assert youtube.split_times(["ab", "abcde"], 3.0, None) == ([1.0, 2.0], [None, None])
    # the script's own words, timed from what was heard: "3" was heard as "three" and shares the gap; nothing in common -> no timings
    got = youtube.align("She had 3 cats.", [["She", 0.0, 0.2], ["had", 0.2, 0.5], ["three", 0.5, 0.9], ["cats", 0.9, 1.4]], 1.5)
    assert got == [["She", 0.0, 0.2], ["had", 0.2, 0.5], ["3", 0.5, 0.9], ["cats.", 0.9, 1.4]]
    assert youtube.align("She had some cats.", [["She", 0.0, 0.2], ["had", 0.2, 0.5], ["cats", 0.9, 1.4]], 1.5)[2] == ["some", 0.5, 0.9]
    assert youtube.align("one two three", [["alpha", 0, 1]], 2.0) is None
    va = youtube.VoiceArtist(youtube.channel({"voices": {"dark": {"engine": "kokoro", "voice": "am_onyx", "pause": 0.45}}}))
    assert va.voice_for("dark") == {"engine": "kokoro", "voice": "am_onyx", "speed": 0.95, "pause": 0.45}
    assert va.voice_for("warm") == {"engine": "edge", "voice": "en-US-GuyNeural", "speed": 0.95, "pause": 0.32}
    assert all(youtube.words(b["text"]) <= 22 for b in beats) and " ".join(b["text"] for b in beats[:-1]).startswith("She never told anyone. Not her husband")
    assert youtube.fallback_query("She kept the letter in a drawer") == "letter drawer kept"


def test_speed_and_caption_chunks():
    assert shorts_edit.plain("side\u2011walk\u00a0now") == "side-walk now"
    assert shorts_edit.speed(4, 4) == 1 and shorts_edit.speed(30, 4) == 1 and shorts_edit.speed(5, 4) == 1.25 and shorts_edit.speed(1, 4) == 0.6
    caps = shorts_edit.chunks([{"start": 0, "dur": 2.2, "speech": 2.0, "text": "one two three four"},
                               {"start": 2.2, "dur": 1.2, "text": "x", "words": [["Hello", 0.1, 0.4], ["extraordinarily", 0.4, 1.0]]}])
    assert [c[2] for c in caps] == ["one two three", "four", "Hello", "extraordinarily"]
    assert caps[0][1] == caps[1][0] and caps[2][0] == pytest.approx(2.3) and caps[3][1] <= 3.4


def test_stock_file_choice():
    files = [{"width": 3840, "height": 2160, "link": "4k"}, {"width": 1920, "height": 1080, "link": "hd"}, {"width": 720, "height": 1280, "link": "p720"}]
    assert stock_video.best_file(files)["link"] == "4k"                  # landscape HD is too narrow once cropped to 9:16
    assert stock_video.best_file(files + [{"width": 1080, "height": 1920, "link": "p1080"}])["link"] == "p1080"
    assert stock_video.best_file([{"width": 1280, "height": 720}]) is None
    hit = {"about": "bride and groom wedding", "w": 1080, "h": 1920}
    assert stock_video.relevance(hit, "cousin wedding ceremony") == (1, True) and stock_video.relevance({**hit, "about": "autumn leaves", "w": 3840}, "wedding") == (0, False)


def test_writer_tier_uses_groq_then_falls_back(monkeypatch):
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["model"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)["model"]
        seen["effort"] = json.loads(req.content).get("reasoning_effort")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    llm = LLM(Config(llm=LLMConfig(writer_model="llama-x", writer_reasoning="low")), client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert asyncio.run(llm.json("hi", tier="writer")) == {"ok": True}
    assert seen == {"url": "https://api.groq.com/openai/v1/chat/completions", "auth": "Bearer k", "model": "llama-x", "effort": "low"}
    calls = []                                    # a 429 from the hosted model: wait as told, then the same request again

    async def nap(seconds):
        calls.append(seconds)

    def busy(req):
        calls.append("post")
        return httpx.Response(429, headers={"retry-after": "7"}) if calls.count("post") == 1 else httpx.Response(200, json={"choices": [{"message": {"content": "[1]"}}]})

    import vision.services.llm as llm_mod
    monkeypatch.setattr(llm_mod.asyncio, "sleep", nap)
    slow = LLM(Config(llm=LLMConfig(writer_model="llama-x")), client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(busy)))
    assert asyncio.run(slow.json("hi", tier="writer")) == [1] and calls == ["post", 7.0, "post"]
    monkeypatch.undo()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm._local_ok = (9e12, True)
    assert asyncio.run(llm.pick("writer")) == "local"


def test_music_library_keeps_instrumentals_and_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(bgm, "DIR", tmp_path)
    hit = lambda i, tags, **kw: {"id": i, "title": f"T{i}", "creator": "C", "license": "by", "license_version": "3.0", "duration": 120000,
                                 "url": f"https://audio.test/{i}", "foreign_landing_url": f"https://page.test/{i}", "tags": [{"name": t} for t in tags], **kw}
    results = [hit("a", ["instrumental", "piano"]), hit("b", ["instrumental", "vocal"]), hit("c", ["piano"]), hit("d", ["instrumental"], duration=20000)]

    def handler(req):
        if "openverse" in str(req.url):
            assert req.url.params["license"] == "cc0,pdm,by" and "instrumental" in req.url.params["q"]
            return httpx.Response(200, json={"results": results})
        return httpx.Response(200, content=b"x" * 200_000)

    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    saved = asyncio.run(bgm.fetch("sad", 3, client()))
    assert [c["title"] for c in saved] == ["Ta"] and saved[0]["license"] == "CC BY 3.0"       # sung, untagged and too-short tracks are left out
    assert asyncio.run(bgm.fetch("sad", 3, client())) == []                                    # already in the library
    (tmp_path / "sad" / "my-own.mp3").write_bytes(b"y")                                        # a file dropped in by hand has no credit
    assert bgm.pick("sad", 0)[0].name == "my-own.mp3" and bgm.pick("sad", 0)[1] is None
    assert bgm.pick("sad", 1)[1]["title"] == "Ta" and bgm.pick("sad", 2)[0].name == "my-own.mp3" and bgm.pick("dark") is None
    assert bgm.line(bgm.pick("sad", 1)[1]) == "“Ta” by C (CC BY 3.0) https://page.test/a"


def test_generator_slot_is_off_until_a_provider_is_named(monkeypatch, tmp_path):
    assert not genmedia.ready({}) and not genmedia.ready({"provider": "nope"})

    @genmedia.provider("fake")
    async def fake(c, spec, prompt, out, kind, seconds):
        out.write_bytes(b"x")
        return out

    assert not genmedia.ready({"provider": "fake", "key_env": "FAKE_KEY"})
    monkeypatch.setenv("FAKE_KEY", "k")
    assert asyncio.run(genmedia.generate(None, {"provider": "fake", "key_env": "FAKE_KEY"}, "p", tmp_path / "a.png")).read_bytes() == b"x"
    genmedia.PROVIDERS.pop("fake")
    with pytest.raises(genmedia.NotConfigured):
        asyncio.run(genmedia.generate(None, {}, "p", tmp_path / "b.png"))


# ---------- the crew, end to end ----------

@pytest.fixture
def media(tmp_path):
    clip, photo = tmp_path / "clip.mp4", tmp_path / "photo.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=540x960:r=30:d=3", "-pix_fmt", "yuv420p", str(clip)], check=True)
    Image.new("RGB", (800, 1200), (40, 60, 90)).save(photo)
    return {"clip": clip.read_bytes(), "photo": photo.read_bytes()}


def web(media, posts, yt):
    n = {"v": 0}

    def handler(req):
        u = str(req.url)
        if "suggestqueries" in u:
            return httpx.Response(200, json=[req.url.params["q"], ["confession story time", "family secret confession"]])
        if "gutenberg.org" in u:
            return httpx.Response(200, content=BOOK.encode())
        if "/commentThreads" in u:
            if req.method == "POST":
                yt.setdefault("posted", []).append(json.loads(req.content)["snippet"]["topLevelComment"]["snippet"]["textOriginal"])
                return httpx.Response(200, json={"id": "c9"})
            return httpx.Response(200, json={"items": [{"snippet": {"topLevelComment": {"id": "cm1", "snippet": {"textOriginal": t}}}} for t in yt.get("comments", [])]})
        if "/playlists" in u:
            if req.method == "POST":
                yt["made_playlist"] = json.loads(req.content)["snippet"]["title"]
                return httpx.Response(200, json={"id": "PL1"})
            return httpx.Response(200, json={"items": []})
        if "thumbnails/set" in u:
            yt["thumb"] = (req.url.params["videoId"], len(req.read()), req.headers["content-type"])
            return httpx.Response(200, json={"items": []})
        if "/playlistItems" in u:
            yt.setdefault("playlist_items", []).append(json.loads(req.content)["snippet"])
            return httpx.Response(200, json={"id": "pi1"})
        if "upload/youtube/v3/videos" in u and yt.get("limit"):
            return httpx.Response(400, json={"error": {"message": "The user has exceeded the number of videos they may upload.", "errors": [{"reason": "uploadLimitExceeded"}]}})
        if "upload/youtube/v3/videos" in u:
            yt["meta"], yt["auth"] = json.loads(req.content), req.headers["authorization"]
            return httpx.Response(200, headers={"Location": "https://upload.test/session1"})
        if u.startswith("https://upload.test/"):
            yt["bytes"] = len(req.read())
            return httpx.Response(200, json={"id": "vid1", "status": {"privacyStatus": "unlisted"}})
        if "youtube/v3/videos" in u and req.url.params.get("chart"):
            yt["chart_calls"] = yt.get("chart_calls", 0) + 1
            return httpx.Response(200 if not req.url.params.get("videoCategoryId") == "26" else 404, json={"items": yt.get("popular", [])})
        if "youtube/v3/videos" in u:
            return httpx.Response(200, json={"items": yt.get("items", [])})
        if "access_token" in u:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if "oauth.reddit.com" in u:
            return httpx.Response(200, json={"data": {"children": [{"data": p} for p in posts]}})
        if "drive/v3/files" in u:
            q = req.url.params.get("q", "")
            if "/export" in u or req.url.params.get("alt") == "media":
                return httpx.Response(200, content=("\ufeffhttps://example.com/post/9\r\n" + GOOD).encode())
            if "mimeType = 'application/vnd.google-apps.folder'" in q:
                return httpx.Response(200, json={"files": [{"id": "fold1"}] if "Confessions Inbox" in q else []})
            return httpx.Response(200, json={"files": yt.get("drive", [])})
        if "pexels.com/videos/search" in u:
            n["v"] += 1
            if n["v"] % 3 == 0:                       # every third search finds no video: the photo search is tried
                return httpx.Response(200, json={"videos": []})
            return httpx.Response(200, json={"videos": [{"id": n["v"], "url": f"https://pexels.test/v/{n['v']}", "duration": 3, "user": {"name": "Ana"},
                                                         "video_files": [{"link": "https://cdn.test/clip.mp4", "width": 1080, "height": 1920, "file_type": "video/mp4"}]}]})
        if "pexels.com/v1/search" in u:
            return httpx.Response(200, json={"photos": [{"id": 900 + n["v"], "url": "https://pexels.test/p/1", "photographer": "Ben", "width": 800, "height": 1200,
                                                         "src": {"original": "https://cdn.test/photo.jpg"}}]})
        if u.startswith("https://cdn.test/clip"):
            return httpx.Response(200, content=media["clip"])
        if u.startswith("https://cdn.test/photo"):
            return httpx.Response(200, content=media["photo"])
        return httpx.Response(404)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def tone(text, stem):
    """A stand-in voice: a quiet tone as long as the words would take to say."""
    out = stem.with_suffix(".src.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={max(0.6, len(text.split()) / 4):.2f}", str(out)], check=True)
    return out, None


def make(tmp_path, monkeypatch, media, posts, llm, yt=None, **ch):
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    monkeypatch.setattr(reddit, "_token", None)
    monkeypatch.setattr(oauth, "TOKENS", tmp_path / "tokens.json")      # never the real sign-ins
    monkeypatch.setattr(bgm, "DIR", tmp_path / "assets" / "bgm")        # nor the real music library
    monkeypatch.setattr(gutenberg, "DIR", tmp_path / "data" / "classics")
    monkeypatch.setattr(fonts, "DIR", tmp_path / "assets" / "fonts")    # nor the fonts or the sound effects
    monkeypatch.setattr(sfx, "DIR", tmp_path / "assets" / "sfx")
    for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "PEXELS_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    c = youtube.channel({"subreddits": ["confession"], "seconds": [20, 60], "quick": {"per_day": 0}, **ch})     # quick Shorts are tested apart
    d = Director(c["director"], youtube.crew(c, client_factory=web(media, posts, yt if yt is not None else {}), synth=tone), reporter="Analytics Manager",
                 again=youtube.more_today(c))
    m = Master("youtube", "YOUTUBE MANAGER", [Stage("CHANNELS", [d])], reporter=c["director"], mode="live")
    m.services.update(llm=llm, cfg=Config())
    return m


POSTS = [{"id": "bad", "title": "Dark", "selftext": "I thought about suicide every day. " * 30, "permalink": "/r/confession/bad", "score": 900, "subreddit": "confession"},
         {"id": "ok1", "title": "The letter I never sent", "selftext": GOOD, "permalink": "/r/confession/ok1", "score": 500, "subreddit": "confession"},
         {"id": "pin", "title": "Rules", "selftext": GOOD, "stickied": True, "permalink": "/r/confession/pin", "score": 9999, "subreddit": "confession"}]


@FFMPEG
def test_crew_makes_a_short_uploads_it_unlisted_and_follows_it(tmp_path, monkeypatch, media):
    yt, signed_in = {}, {"ok": False}

    async def token(account, provider, client=None):
        if not signed_in["ok"]:
            raise oauth.AuthNeeded(account, provider)
        return "tok"

    monkeypatch.setattr(oauth, "access_token", token)
    m = make(tmp_path, monkeypatch, media, POSTS, WriterLLM(story_words=70), yt)
    sad = tmp_path / "assets" / "bgm" / "sad"                  # one track in the library for the story's mood
    sad.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=4", str(sad / "slow-piano.mp3")], check=True)
    (sad / "slow-piano.json").write_text(json.dumps({"title": "Slow Piano", "creator": "Ana", "license": "CC BY 3.0", "page": "https://music.test/1"}))
    bus, store = EventBus(), Store(tmp_path / "t.db")
    report = asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert [crew[n]["status"] for n in ("Story Scout", "Story Writer", "Screenplay Writer", "Keyword Generator", "Voice Artist", "Footage Collector", "Editor")] == ["done"] * 7, crew
    assert crew["Footage Generator"]["label"] == "OFF" and crew["Uploader"]["label"] == "SIGN IN"       # not signed in: made, kept, asked for
    assert bus.state["notices"]["auth:youtube-confessions"]["url"].endswith("/auth/youtube/login?account=youtube-confessions")
    assert "1 made, 1 waiting for upload" in report and "The letter she never sent" in report

    rec = store.kv_list(youtube.LOG)[0]
    assert rec["source"]["url"] == "https://www.reddit.com/r/confession/ok1" and rec["script"].startswith("She kept the letter") and rec["status"] == "ready"
    assert rec["mood"] == "sad" and rec["voice"] == "edge en-US-GuyNeural"
    assert any(p.startswith("Retell") and "end on a hopeful, motivating note" in p and "no new events" in p for p in m.services["llm"].prompts)
    assert rec["music"] == "“Slow Piano” by Ana (CC BY 3.0) https://music.test/1" and "with music" in crew["Editor"]["summary"]
    assert rec["hashtags"] == ["#confession", "#storytime"] and len(rec["keywords"]) == len(rec["screenplay"]) and rec["screenplay"][-1]["text"].startswith("Subscribe")
    assert any("Ana (Pexels)" in c for c in rec["credits"]) and any("Ben (Pexels)" in c for c in rec["credits"])
    assert store.kv_get(youtube.SEEN, "confessions:bad")["state"] == "rejected" and store.kv_get(youtube.SEEN, "confessions:ok1")["state"] == "done"

    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", rec["file"]],
                         capture_output=True, text=True, check=True)
    info = json.loads(out.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920) and any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - rec["seconds"]) < 0.25
    assert sorted(p.name for p in (tmp_path / "data" / "shorts" / "confessions").glob("*/*")) == ["final.mp4"]      # working files are cleared

    signed_in["ok"] = True
    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "unlisted"}, "statistics": {"viewCount": "0"}}]
    report = asyncio.run(m.cycle(bus, store))                # the day's Short is made: nothing new is built, the waiting one goes up
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert crew["Story Scout"]["label"] == "QUOTA MET" and crew["Uploader"]["label"] == "UPLOADED" and len(store.kv_list(youtube.LOG)) == 1
    assert yt["auth"] == "Bearer tok" and yt["bytes"] == (tmp_path / "data" / "shorts" / "confessions").glob("*/final.mp4").__next__().stat().st_size
    assert yt["meta"]["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    assert yt["meta"]["snippet"]["title"] == "The letter she never sent" and yt["meta"]["snippet"]["description"].startswith("#confession #storytime #Shorts\n\nFootage: ")
    assert yt["meta"]["snippet"]["description"].endswith("\nMusic: “Slow Piano” by Ana (CC BY 3.0) https://music.test/1")
    rec = store.kv_list(youtube.LOG)[0]
    assert rec["status"] == "unlisted" and rec["url"] == "https://youtu.be/vid1" and "1 unlisted for your review" in report
    assert bus.state["notices"]["youtube-review-vid1"]["url"] == "https://studio.youtube.com/video/vid1/edit" and "auth:youtube-confessions" not in bus.state["notices"]

    bus.state["notices"].clear()                             # as after a restart: the reminder comes back while it is still unlisted
    asyncio.run(m.cycle(bus, store))
    assert "youtube-review-vid1" in bus.state["notices"]

    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "1234", "likeCount": "56"}}]
    report = asyncio.run(m.cycle(bus, store))                # Mani made it public on YouTube: noticed, counted, the reminder goes
    assert "1 public with 1,234 views" in report and "youtube-review-vid1" not in bus.state["notices"] and yt["bytes"] and len(yt) == 4
    assert store.kv_list(youtube.LOG)[0]["stats"] == {"view": 1234, "like": 56, "comment": 0}
    assert {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Uploader"]["label"] == "IDLE"

    yt["items"] = []
    assert "1 deleted" in asyncio.run(m.cycle(bus, store)) and store.kv_list(youtube.LOG)[0]["status"] == "deleted"


@FFMPEG
def test_one_run_makes_shorts_until_the_days_number_is_reached(tmp_path, monkeypatch, media):
    m = make(tmp_path, monkeypatch, media, [], WriterLLM(story_words=70), shorts_per_day=2)
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    box = tmp_path / "inbox" / "confessions" / "confessions"
    box.mkdir(parents=True)
    for n in "abc":
        (box / f"story {n}.txt").write_text(GOOD)
    bus, store = EventBus(), Store(tmp_path / "t.db")
    report = asyncio.run(m.cycle(bus, store))
    assert len(store.kv_list(youtube.LOG)) == 2 and "2 made" in report              # three stories waiting, two a day
    assert len(list((tmp_path / "data" / "shorts" / "confessions").glob("*/final.mp4"))) == 2
    asyncio.run(m.cycle(bus, store))
    assert len(store.kv_list(youtube.LOG)) == 2

    youtube.reset_today(store, "confessions")                 # a reset: what was made earlier today no longer counts
    assert youtube.made_today(store, m.agents[0].members[0].ch) == 0
    store.kv_delete(youtube.STATE, "confessions:quota_reset")
    assert youtube.made_today(store, m.agents[0].members[0].ch) == 2

    for v in store.kv_list(youtube.LOG):                      # yesterday's Shorts, re-saved today by a stats update, don't use up today
        store.kv_put(youtube.LOG, v["_key"], {**{k: x for k, x in v.items() if not k.startswith("_")}, "made": v["made"] - 86400, "status": "public"})
    asyncio.run(m.cycle(bus, store))
    assert len(store.kv_list(youtube.LOG)) == 3


@FFMPEG
def test_original_stories_fill_the_day_when_no_real_story_is_waiting(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    yt = {}
    monkeypatch.setattr(oauth, "access_token", token)
    llm = WriterLLM(story_words=70)
    m = make(tmp_path, monkeypatch, media, [], llm, yt, originals=True, shorts_per_day=2)
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    bus, store = EventBus(), Store(tmp_path / "t.db")
    report = asyncio.run(m.cycle(bus, store))
    log = store.kv_list(youtube.LOG)
    assert len(log) == 2 and all(v["original"] and v["source"]["from"] == "original (confession)" and v["kind"] == "original" for v in log) and "2 made" in report
    assert len({v["source"]["title"] for v in log} & {"Premise 1", "Premise 2", "Premise 3"}) == 2     # two different premises, each used once
    bank = store.kv_list(youtube.PREMISES)
    assert sorted(p["title"] for p in bank) == ["Premise 1", "Premise 2", "Premise 3"] and sum(p["used"] for p in bank) == 2   # thin and unsafe ones never enter
    assert sum(p.startswith("Invent premises") for p in llm.prompts) == 1 and sum(p.startswith("Write an original") for p in llm.prompts) == 2
    assert not any(p.startswith("You screen") for p in llm.prompts) and "youtube-source-confessions" not in bus.state["notices"]
    assert "\n\nThis story is fiction.\n\nFootage: " in yt["meta"]["snippet"]["description"]


def test_gutenberg_book_is_cut_into_its_stories():
    meta, text = gutenberg.body(BOOK)
    assert meta == {"title": "The Four Million", "author": "O. Henry"} and "licence text" not in text and "START OF" not in text
    assert [s["title"] for s in gutenberg.stories(text)] == ["The Last Leaf", "The Cop And The Anthem"]      # the contents page and a stub are not stories
    assert gutenberg.body("Author: graf Leo Tolstoy\nTitle: Fables")[0]["author"] == "Leo Tolstoy"


@FFMPEG
def test_viewer_comment_then_a_classic_with_citation_playlist_and_invitation(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    monkeypatch.setattr(oauth, "access_token", token)
    monkeypatch.setattr(oauth, "granted", lambda account: "https://www.googleapis.com/auth/youtube.force-ssl")
    yt = {"comments": ["nice video!", GOOD]}
    cta = "Got a confession of your own? Leave it in the comments. It could be our next story."
    m = make(tmp_path, monkeypatch, media, [], WriterLLM(story_words=70), yt, shorts_per_day=2, viewer_comments=True, classics=[2776], cta=cta,
             playlists={"classic": "Classic Stories"})
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    bus, store = EventBus(), Store(tmp_path / "t.db")
    store.kv_put(youtube.LOG, "old", {"channel": "confessions", "status": "public", "video_id": "old1", "made": 1.0, "title": "Earlier", "seconds": 60})
    yt["items"] = [{"id": "old1", "status": {"privacyStatus": "public"}, "statistics": {}}, {"id": "vid1", "status": {"privacyStatus": "unlisted"}, "statistics": {}}]
    asyncio.run(m.cycle(bus, store))
    by_kind = {v.get("kind"): v for v in store.kv_list(youtube.LOG) if v.get("kind")}
    assert set(by_kind) == {"viewer", "classic"}                 # the viewer's confession first, then one classic; "nice video!" is too short to be a story
    assert by_kind["viewer"]["source"]["url"] == "https://www.youtube.com/watch?v=old1&lc=cm1"
    c = by_kind["classic"]
    assert c["classic"] == {"title": "The Last Leaf", "author": "O. Henry", "book": "The Four Million", "url": "https://www.gutenberg.org/ebooks/2776"}
    assert c["screenplay"][-2]["text"].endswith("A retelling of “The Last Leaf”, by O. Henry.") and c["screenplay"][-1]["text"].startswith("Subscribe")
    desc = yt["meta"]["snippet"]["description"]                  # the last upload was the classic
    assert f"\n\n{cta}\n\nRetold from “The Last Leaf” by O. Henry, in “The Four Million” (public domain): https://www.gutenberg.org/ebooks/2776" in desc
    assert yt["made_playlist"] == "Classic Stories" and [i["playlistId"] for i in yt["playlist_items"]] == ["PL1"] and yt["posted"] == [cta, cta, cta]     # both uploads, and the earlier public Short that never had it
    assert store.kv_get(youtube.STATE, "confessions:playlist:Classic Stories") == {"id": "PL1"}
    assert "in “Classic Stories”" in {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Uploader"]["summary"]

    monkeypatch.setattr(oauth, "granted", lambda account: "")    # an older sign-in: uploads go on, and one more sign-in is asked for
    youtube.reset_today(store, "confessions")
    m.agents[0].members[0].ch["shorts_per_day"] = 1
    asyncio.run(m.cycle(bus, store))
    assert "youtube-scope-confessions" in bus.state["notices"] and len(yt["posted"]) == 3
    assert len([v for v in store.kv_list(youtube.LOG) if v.get("kind") == "classic"]) == 2


def test_original_kinds_take_turns_and_each_is_written_by_its_own_rules(tmp_path, monkeypatch, media):
    llm = WriterLLM(story_words=70)
    m = make(tmp_path, monkeypatch, media, [], llm, originals=True, original_genres=["confession", "motivational", "science"])
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    scout, writer = m.agents[0].members[0], m.agents[0].members[1]
    store, bus = Store(tmp_path / "t.db"), EventBus()
    seen = []
    for _ in range(3):
        ctx = {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
        asyncio.run(scout.run(ctx))
        asyncio.run(writer.run(ctx))
        seen.append((ctx["job"]["genre"], youtube.kind(ctx["job"]), next(p for p in reversed(llm.prompts) if p.startswith("Write a"))))
    assert [g for g, _, _ in seen] == ["confession", "motivational", "science"] and [k for _, k, _ in seen] == ["original", "motivational", "science"]
    assert "confession-style story" in seen[0][2] and "end on a hopeful, motivating note" in seen[0][2]
    assert "motivational story" in seen[1][2] and "never by luck" in seen[1][2]
    assert seen[2][2].startswith("Write a true science story") and "leave it out" in seen[2][2] and "the wonder of it" in seen[2][2] and "hopeful" not in seen[2][2]
    science = next(p for p in store.kv_list(youtube.PREMISES) if p["genre"] == "science")
    assert science["seed"].split(":")[0] in youtube.SCIENCE and science["used"]
    assert youtube._about({"kind": "motivational"}).strip() == "This story is fiction." and youtube._about({"kind": "science"}) == ""
    assert "Keep them listening" in seen[0][2] and "Build it exactly like this" not in seen[0][2]          # a story gets the retention rule, not a lesson's pattern
    assert "Build it exactly like this: Open with the end result" in seen[2][2] and ctx["job"]["structure"] == "result_first"
    assert "Never hand over the whole answer before the final third" in seen[2][2] and "Never hand over" not in seen[0][2]
    # opening shapes: a story opens in one (third person); a lesson's goes to its title, never into its patterned script
    first = next(iter(youtube.HOOKS["story"].values()))
    assert f"Shape the first sentence like this one, fitted to this story and in the third person: “{first}”" in seen[0][2]
    assert "Shape the first sentence" not in seen[2][2] and ctx["job"]["hook"] in youtube.HOOKS["lesson"]
    assert not any(re.search(r"\b(I|my|me)\b", h) for group in youtube.HOOKS.values() for h in group.values())       # the narrator has no "I"
    assert not any(youtube.promises(h) for h in youtube.HOOKS["lesson"].values())
    assert list(youtube.STRUCTURES) == ["result_first", "belief_flip", "better_best", "unless", "only_if", "not_a_not_b", "most_do_least"]


def test_money_lessons_follow_a_pattern_and_never_promise_earnings(tmp_path, monkeypatch, media):
    for title, bad in [("Get Monetized in 3 Days", True), ("How to make $500 a day", True), ("Guaranteed passive income", True), ("Get rich quick with this", True),
                       ("Everybody makes money, but at what cost?", False), ("Why your minimum payment keeps you in debt", False)]:
        assert youtube.promises(title) == bad, title
    assert not youtube.promises("Can you get monetized in 3 days?") and not youtube.promises("How can we make passive income from this?")    # asked, not claimed
    assert youtube.TOLD_PROMISE.search("Honestly, you can make $500 a day.") and youtube.TOLD_PROMISE.search("It gives guaranteed returns.")
    assert not youtube.TOLD_PROMISE.search("People who promise you will get rich quick are selling something. A $10 gadget sold for $20 nets $3.40.")

    class Tempted(WriterLLM):                                  # the model's first lesson promises an income: it is sent back
        async def json(self, prompt, **kw):
            d = await super().json(prompt, **kw)
            if prompt.startswith("Write a short, honest lesson") and "promised or suggested" not in prompt:
                return {**d, "story": "You can make $500 a day. " + d["story"]}
            return d

    llm = Tempted(story_words=70, seo={"title": "Get rich quick: pay it off in 3 days", "lead": "A money lesson.", "tags": ["letter kept in a drawer", "get rich quick", "minimum payment rules"],
                                       "hashtags": ["money", "debt", "credit"]})
    m = make(tmp_path, monkeypatch, media, [], llm, originals=True, original_genres=["money"])
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    scout, writer = m.agents[0].members[0], m.agents[0].members[1]
    strategist = next(a for a in m.agents[0].members if a.name == "SEO Strategist")
    store, bus = Store(tmp_path / "t.db"), EventBus()
    store.kv_put(youtube.LOG, "earlier", {"channel": "confessions", "status": "public", "structure": "result_first", "made": 1.0, "title": "E", "seconds": 60})
    ctx = {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
    asyncio.run(scout.run(ctx))
    job = ctx["job"]
    assert job["genre"] == "money" and job["structure"] == "belief_flip" and youtube.kind(job) == "money"       # the pattern used least so far
    asyncio.run(writer.run(ctx))
    asks = [p for p in llm.prompts if p.startswith("Write a short, honest lesson")]
    assert len(asks) == 2 and "Open by stating something most people believe" in asks[0] and "promised or suggested an amount" in asks[1] and "$500" not in job["script"]
    assert "Explore, do not promise" in asks[0] and "may or may not work" in asks[0]
    asyncio.run(strategist.run(ctx))
    assert job["title"] == "The letter she never sent" and job["seo"]["tags"] == ["letter kept in a drawer"]             # a promising title is refused, and so is that tag
    assert "the title is an open question" in next(p for p in llm.prompts if p.startswith("You package"))
    assert f"only if the lesson really shows it, and turned into a question: “{youtube.HOOKS['lesson'][job['hook']]}”" in next(p for p in llm.prompts if p.startswith("You package"))
    assert youtube._about({"kind": "money"}).strip() == "For education only. This is not financial advice."
    assert store.kv_list(youtube.PREMISES)[0]["seed"] in youtube.MONEY


def test_scheduled_upload_takes_the_next_free_slot_and_needs_no_review(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    import time as _t
    monkeypatch.setattr(oauth, "access_token", token)
    yt = {}
    m = make(tmp_path, monkeypatch, media, [], WriterLLM(), yt, privacy="scheduled", publish_times=["08:00", "20:00"])
    uploader, analytics = m.agents[0].members[-2], m.agents[0].members[-1]
    ch = uploader.ch
    store, bus = Store(tmp_path / "t.db"), EventBus()
    lt = _t.localtime()
    noon = _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
    first = youtube.next_slot(store, ch, noon)
    assert _t.strftime("%H:%M", _t.localtime(first)) == "20:00" and first - noon == 8 * 3600
    store.kv_put(youtube.LOG, "taken", {"channel": "confessions", "status": "scheduled", "publish_at": first, "made": 1.0, "title": "T", "seconds": 60})
    second = youtube.next_slot(store, ch, noon)
    assert _t.strftime("%H:%M", _t.localtime(second)) == "08:00" and 0 < second - first < 86400        # that slot is taken: the next morning
    assert youtube.next_slot(store, ch, first - 600) == second                                             # under half an hour away is too close
    store.kv_put(youtube.LOG, "later", {"channel": "confessions", "status": "scheduled", "publish_at": second + 86400, "made": 1.0, "title": "T2", "seconds": 60})
    queued = youtube.next_slot(store, ch, noon)                # releases form one queue: after the last one scheduled, never into a gap before it
    assert queued > second + 86400 and _t.strftime("%H:%M", _t.localtime(queued)) == "20:00" and queued - (second + 86400) == 12 * 3600
    store.kv_delete(youtube.LOG, "taken")
    store.kv_delete(youtube.LOG, "later")

    f = tmp_path / "final.mp4"
    f.write_bytes(b"v" * 10)
    store.kv_put(youtube.LOG, "j1", {"channel": "confessions", "status": "ready", "made": _t.time(), "title": "A Short", "hashtags": [], "file": str(f), "seconds": 60, "kind": "real"})
    ctx = {"store": store, "bus": bus, "cfg": Config(), "master": "youtube"}
    res = asyncio.run(uploader.run(ctx))
    rec = store.kv_get(youtube.LOG, "j1")
    assert yt["meta"]["status"]["privacyStatus"] == "private" and yt["meta"]["status"]["publishAt"] == _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(rec["publish_at"]))
    assert rec["status"] == "scheduled" and rec["publish_at"] > _t.time() + 1700 and "Uploaded as scheduled: A Short for " in res.summary
    assert not bus.state["notices"]                                                                          # nothing waits for Mani

    # YouTube's own daily cap on uploads: the Short waits, it is said plainly, nothing turns red, and no more are made on top of a backlog
    store.kv_put(youtube.LOG, "j2", {"channel": "confessions", "status": "ready", "made": _t.time(), "title": "Second", "hashtags": [], "file": str(f), "seconds": 60, "kind": "real"})
    yt["limit"] = True
    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "private", "publishAt": "2031-01-02T03:04:05Z"}, "statistics": {}}]
    res = asyncio.run(uploader.run(ctx))
    assert (res.status, res.label) == ("wait", "UPLOAD LIMIT") and "1 waiting" in res.summary and store.kv_get(youtube.LOG, "j2")["status"] == "ready"
    assert "YouTube itself is refusing uploads" in bus.state["notices"]["youtube-limit-confessions"]["text"]
    scout = m.agents[0].members[0]
    scout.ch["shorts_per_day"] = 1
    youtube.reset_today(store, "confessions")
    assert asyncio.run(scout.run({**ctx, "llm": WriterLLM()})).label == "BACKLOG"
    yt["limit"] = False
    assert asyncio.run(uploader.run(ctx)).label == "UPLOADED" and "youtube-limit-confessions" not in bus.state["notices"]
    assert store.kv_get(youtube.LOG, "j2")["publish_at"] > 1925089445          # queued after the release already set for 2031
    store.kv_delete(youtube.LOG, "j2")

    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "private", "publishAt": "2031-01-02T03:04:05Z"}, "statistics": {}}]
    assert "1 scheduled" in asyncio.run(analytics.run(ctx)).summary and store.kv_get(youtube.LOG, "j1")["publish_at"] == 1925089445
    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "7"}}]
    monkeypatch.setattr(oauth, "granted", lambda account: "https://www.googleapis.com/auth/youtube.force-ssl")
    uploader.ch["cta"] = "Tell us yours."                      # a scheduled video is private, so the invitation waits until it is public
    assert "posted" not in yt
    assert "1 public with 7 views" in asyncio.run(analytics.run(ctx)).summary
    asyncio.run(analytics.run(ctx))
    assert yt["posted"] == ["Tell us yours."] and store.kv_get(youtube.LOG, "j1")["cta_done"] is True      # once, not on every run


def test_text_is_cut_into_even_parts():
    text = "\n\n".join(f"Paragraph {n} has exactly seven words here." for n in range(12))
    cut = youtube.parts(text, 3)
    assert len(cut) == 3 and [len(c.split()) for c in cut] == [28, 28, 28] and " ".join(cut) == " ".join(text.split())
    assert len(youtube.parts("One. Two. Three. Four. Five. Six.", 3)) == 3 and youtube.clock(605) == "10:05"


@FFMPEG
def test_long_video_is_written_in_chapters_made_wide_given_a_cover_and_queued_apart(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    import time as _t
    monkeypatch.setattr(oauth, "access_token", token)
    monkeypatch.setattr(oauth, "granted", lambda account: "https://www.googleapis.com/auth/youtube.force-ssl")
    yt, llm = {}, WriterLLM(story_words=45)
    m = make(tmp_path, monkeypatch, media, [], llm, yt, shorts_per_day=0, classics=[2776], privacy="scheduled", publish_times=["06:00"],
             long={"enabled": True, "minutes": [1, 1], "min_source_words": 300, "create_after": "", "publish_time": "20:00", "shot_seconds": 6})
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    bus, store = EventBus(), Store(tmp_path / "t.db")
    store.kv_put(youtube.LOG, "short", {"channel": "confessions", "status": "scheduled", "publish_at": _t.time() + 9 * 86400, "made": 1.0, "title": "A Short", "seconds": 60,
                                        "video_id": "s1"})
    yt["items"] = [{"id": "s1", "status": {"privacyStatus": "private", "publishAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() + 9 * 86400))}, "statistics": {}},
                   {"id": "vid1", "status": {"privacyStatus": "private", "publishAt": "2031-01-02T03:04:05Z"}, "statistics": {}}]
    report = asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    rec = next(v for v in store.kv_list(youtube.LOG) if v.get("format") == "long")
    assert sum(p.startswith("You are retelling") for p in llm.prompts) == 3 and "3 chapters" in crew["Story Writer"]["summary"]     # one request per chapter
    first, last = [p for p in llm.prompts if p.startswith("You are retelling")][0], [p for p in llm.prompts if p.startswith("You are retelling")][-1]
    assert "Open with one sentence that hooks" in first and "keep the author's own ending" in last and "The part before this one ended" in last
    assert [c["heading"] for c in rec["chapters"]] == ["Chapter 1", "Chapter 2", "Chapter 3"] and rec["chapters"][0]["t"] == 0 and rec["chapters"][1]["t"] > 5
    assert "shots" in crew["Screenplay Writer"]["summary"] and "long video" in crew["Editor"]["summary"] and "thumbnail made" in crew["Editor"]["summary"]
    assert rec["title"] == "The Last Leaf, Retold" and rec["thumb_text"] == "one last leaf" and rec["kind"] == "classic" and rec["mood"] == "sad"

    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", rec["file"]],
                                      capture_output=True, text=True, check=True).stdout)
    video = next(x for x in probe["streams"] if x["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)
    assert Image.open(rec["thumb"]).size == (1280, 720) and sorted(p.name for p in Path(rec["file"]).parent.iterdir()) == ["final.mp4", "thumb.jpg"]

    desc, tags = yt["meta"]["snippet"]["description"], yt["meta"]["snippet"]["tags"]
    assert desc.startswith("A painter. A promise.\n\n#classic #ohenry") and "#Shorts" not in desc and "Shorts" not in tags
    assert "\n\n0:00 Chapter 1\n" in desc and "Retold from “The Last Leaf” by O. Henry" in desc
    assert yt["thumb"][0] == "vid1" and yt["thumb"][1] > 2000 and yt["thumb"][2] == "image/jpeg" and yt["made_playlist"] == "Long Stories"
    import calendar
    sent = calendar.timegm(_t.strptime(yt["meta"]["status"]["publishAt"], "%Y-%m-%dT%H:%M:%SZ"))
    due = _t.localtime(sent)                                    # its own queue: the next 20:00, not after the Short scheduled nine days out
    assert (due.tm_hour, due.tm_min) == (20, 0) and sent < _t.time() + 2 * 86400 and "thumbnail set" in crew["Uploader"]["summary"]
    assert "2 made" in report


def test_seo_strategist_packages_from_real_searches_and_the_channels_best(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    monkeypatch.setattr(oauth, "access_token", token)
    yt = {}
    seo = {"title": "She hid one letter for thirty years", "lead": "A confession story about a letter never sent.", "hashtags": ["confession", "story", "secrets"],
           "tags": ["confession story", "the letter never sent", "Confession Story", "x" * 60, "confession story for kids", "confession story in hindi",
                    "car insurance quotes"] + [f"letter story number {n} of many" for n in range(30)]}
    llm = WriterLLM(story_words=70, seo=seo)
    m = make(tmp_path, monkeypatch, media, POSTS, llm, yt)
    bus, store = EventBus(), Store(tmp_path / "t.db")
    store.kv_put(youtube.STATE, "confessions:insights", {"top_titles": ["The night she told the truth"]})
    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "unlisted"}, "statistics": {}}]
    asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    ask = next(p for p in llm.prompts if p.startswith("You package"))
    assert "confession story time; family secret confession" in ask and "The night she told the truth" in ask and "Working title: The letter she never sent" in ask
    assert crew["SEO Strategist"]["label"] == "PACKAGED" and "from 2 real searches, 1 of our best titles" in crew["SEO Strategist"]["summary"]
    rec = store.kv_list(youtube.LOG)[0]
    assert rec["title"] == "She hid one letter for thirty years" and rec["seo"]["title_before"] == "The letter she never sent" and rec["hashtags"] == ["#confession", "#story", "#secrets"]
    sent = yt["meta"]["snippet"]
    assert sent["title"] == "She hid one letter for thirty years" and sent["description"].startswith("A confession story about a letter never sent.\n\n#confession #story #secrets #Shorts")
    assert sent["tags"][:2] == ["confession story", "the letter never sent"] and "car insurance quotes" not in sent["tags"] and len(sent["tags"]) == len(set(t.lower() for t in sent["tags"]))   # no repeats
    assert not any("kids" in t or "hindi" in t for t in sent["tags"])                                                                            # tags for some other video are dropped
    assert sum(len(t) + 3 for t in sent["tags"]) <= 430 and all(len(t) <= 40 for t in sent["tags"])                                              # inside YouTube's limit

    # the channel's own results become what it learns from; a fiction story is never titled "true"; no answer = the writer's title stands
    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "40"}}]
    asyncio.run(m.cycle(bus, store))
    assert store.kv_get(youtube.STATE, "confessions:insights") == {"top_titles": ["She hid one letter for thirty years"], "views_by_kind": {"real": 40}, "videos": 1, "views_by_length": {"regular": 40}}
    strategist = next(a for a in m.agents[0].members if a.name == "SEO Strategist")
    job = {"title": "A quiet lie", "script": "She lied. " * 30, "original": True, "genre": "confession", "source": {"from": "original (confession)", "title": "x"}}
    asyncio.run(strategist.run({"job": job, "store": store, "llm": WriterLLM(seo={**seo, "title": "The true story of a quiet lie"})}))
    assert job["title"] == "A quiet lie" and job["seo"]["title_before"] == "A quiet lie"
    job2 = {k: v for k, v in job.items() if k != "seo"}
    res = asyncio.run(strategist.run({"job": job2, "store": store, "llm": WriterLLM()}))
    assert res.label == "KEPT" and "seo" not in job2 and not strategist.blocking


def test_todays_most_watched_steers_lesson_subjects_and_informs_titles(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    monkeypatch.setattr(oauth, "access_token", token)
    hot = {"videos": [{"title": "Why inflation is back and what it does to your savings", "tags": ["economy"]}, {"title": "Minecraft speedrun world record", "tags": []}]}
    words = youtube.trending_words(hot)
    assert {"inflation", "savings", "minecraft"} <= words and youtube.trend_score("what inflation does to savings", words) == 2
    assert youtube.trend_score("how a credit score is built", words) == 0 and youtube.trend_score("anything", set()) == 0

    yt = {"popular": [{"id": "p1", "snippet": {"title": "Why inflation is back and what it does to your savings", "tags": ["economy"]}},
                      {"id": "p2", "snippet": {"title": "Musica nueva", "defaultAudioLanguage": "es"}}]}
    llm = WriterLLM(story_words=70, seo={"title": "What does inflation do to your savings?", "lead": "A money lesson.", "tags": ["inflation savings"], "hashtags": ["a", "b", "c"]})
    m = make(tmp_path, monkeypatch, media, [], llm, yt, originals=True, original_genres=["money"])
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    scout = m.agents[0].members[0]
    strategist = next(a for a in m.agents[0].members if a.name == "SEO Strategist")
    store, bus = Store(tmp_path / "t.db"), EventBus()
    ctx = {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
    asyncio.run(scout.run(ctx))
    kept = store.kv_get(youtube.STATE, "confessions:trends")
    assert [v["title"] for v in kept["videos"]] == ["Why inflation is back and what it does to your savings"] and kept["region"] == "US"     # other languages left out
    plan = next(p for p in llm.prompts if p.startswith("Plan short lessons"))
    assert plan.split("\n\n")[-1].startswith("1. what inflation does to savings")           # the subject that touches today's list is offered first
    calls = yt["chart_calls"]
    ctx2 = {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
    asyncio.run(scout.run(ctx2))
    assert yt["chart_calls"] == calls                                                       # read at most twice a day, then kept
    job = {"title": "What inflation does to savings", "script": "Prices rise and savings buy less. " * 20, "original": True, "genre": "money", "structure": "unless",
           "source": {"from": "original (money)", "title": "what inflation does to savings"}}
    asyncio.run(strategist.run({"job": job, "store": store, "llm": llm}))
    ask = [p for p in llm.prompts if p.startswith("You package")][-1]
    assert "Being watched most on YouTube today" in ask and "Why inflation is back" in ask and "never name a channel or a person" in ask
    strategist.ch["trends"] = False
    asyncio.run(strategist.run({"job": {**job, "title": "What inflation does to savings"}, "store": store, "llm": llm}))
    assert "Being watched most" not in [p for p in llm.prompts if p.startswith("You package")][-1]


def test_scout_says_no_without_a_clear_yes_and_asks_for_a_source(tmp_path, monkeypatch, media):
    m = make(tmp_path, monkeypatch, media, POSTS, WriterLLM(safe=False))
    bus, store = EventBus(), Store(tmp_path / "t.db")
    asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert crew["Story Scout"]["label"] == "NOTHING NEW" and crew["Editor"]["label"] == "IDLE"
    assert store.kv_get(youtube.SEEN, "confessions:ok1") == {"state": "unclear", "tries": 1} and store.kv_list(youtube.LOG) == []

    monkeypatch.delenv("REDDIT_CLIENT_ID")
    asyncio.run(m.cycle(bus, store))
    assert {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Story Scout"]["label"] == "NEEDS SOURCE"
    assert "youtube-source-confessions" in bus.state["notices"]

    box = tmp_path / "inbox" / "confessions" / "confessions"
    box.mkdir(parents=True)
    (box / "my story.txt").write_text("https://example.com/post/1\n" + GOOD)
    m.services["llm"] = WriterLLM(story_words=10)             # a story far too short is refused, twice, and the chain stops
    report = asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert crew["Story Scout"]["label"] == "FOUND" and crew["Story Writer"]["status"] == "error" and crew["Editor"]["label"] == "BLOCKED"
    assert "youtube-source-confessions" not in bus.state["notices"] and "did not return a story" in report


def test_scout_copies_new_drive_documents_into_the_inbox(tmp_path, monkeypatch, media):
    async def token(account, provider, client=None):
        return "tok"

    yt = {"drive": [{"id": "docAAA111", "name": "My sister's wedding", "mimeType": "application/vnd.google-apps.document"}]}
    m = make(tmp_path, monkeypatch, media, [], WriterLLM(story_words=10), yt, drive_folder="Confessions Inbox")
    monkeypatch.setattr(oauth, "access_token", token)
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    bus, store = EventBus(), Store(tmp_path / "t.db")
    asyncio.run(m.cycle(bus, store))
    saved = tmp_path / "inbox" / "confessions" / "confessions" / "My-sister-s-wedding-docAAA.txt"
    assert saved.read_text().startswith("https://example.com/post/9\nI have carried this")
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert crew["Story Scout"]["label"] == "FOUND" and "My-sister-s-wedding" in crew["Story Scout"]["summary"]
    assert store.kv_has(youtube.DRIVE, "confessions:docAAA111") and not bus.state["notices"]

    saved.unlink()                                             # already fetched once: not fetched again
    asyncio.run(m.cycle(bus, store))
    assert not saved.exists()

    m.agents[0].members[0].ch["drive_folder"] = "Missing"      # wrong folder name: a notice, not a failure
    asyncio.run(m.cycle(bus, store))
    assert "no folder named “Missing”" in bus.state["notices"]["youtube-drive-confessions"]["text"]
    assert {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Story Scout"]["status"] != "error"


def test_catalog_matches_the_crew():
    from vision.masters import CATALOG, build_masters
    spec = CATALOG["masters"]["youtube"]
    d = youtube.build_agents({}, Config())[spec["reporter"]]
    assert [a.name for a in d.members] == [c["name"] for c in spec["agents"][0]["crew"]] and d.reporter == spec["agents"][0]["crew_reporter"]
    assert [[s.title, [a.name for a in s.agents]] for s in d.crew] == spec["agents"][0]["crew_stages"]
    cfg = Config(masters={"youtube": {"mode": "live"}})
    assert isinstance(next(m for m in build_masters(cfg) if m.id == "youtube").agents[0], Director)


def test_morning_run_and_no_shorts_before_the_starting_hour(tmp_path, monkeypatch, media):
    from vision.orchestrator import Orchestrator
    cfg = Config(only_masters=["youtube"], masters={"youtube": {"mode": "live", "run_at": ["05:00"], "cycle_minutes": 360}})
    from vision.masters import build_masters

    async def jobs():
        orch = Orchestrator(cfg, build_masters(cfg), EventBus(), Store(tmp_path / "o.db"))
        orch.start_schedules()
        found = {j.id: str(j.trigger) for j in orch.scheduler.get_jobs()}
        orch.scheduler.shutdown(wait=False)
        orch._watch.cancel()
        return found

    found = asyncio.run(jobs())
    assert "cycle:youtube" in found and "hour='5', minute='0'" in found["at:youtube:05:00"] and not any(k.startswith("at:news") for k in found)

    m = make(tmp_path, monkeypatch, media, [], WriterLLM(), originals=True, create_after="23:59")
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    monkeypatch.setattr(youtube.time, "strftime", lambda fmt, *a: "04:10" if fmt == "%H:%M" else __import__("time").strftime(fmt, *a))
    bus, store = EventBus(), Store(tmp_path / "t.db")
    asyncio.run(m.cycle(bus, store))
    scout = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Story Scout"]
    assert scout["label"] == "NOT YET" and scout["summary"] == "Today's Shorts start at 23:59" and store.kv_list(youtube.LOG) == []


def test_only_masters_switches_the_others_off():
    from vision.masters import build_masters
    cfg = Config(only_masters=["youtube"], masters={"youtube": {"mode": "live"}, "news": {"enabled": True}})
    assert {m.id for m in build_masters(cfg) if m.enabled} == {"youtube"}
    assert cfg.masters["news"].enabled and not cfg.master("news").enabled          # the master's own setting is left as it was
    cfg = Config(only_masters=[], masters={"news": {"enabled": False}})
    assert not cfg.master("news").enabled and cfg.master("traffic").enabled


# ---------- editing upgrade, quick format, double down ----------

def library(tmp_path, monkeypatch, kinds=("ding", "whoosh", "riser", "pop"), files=2):
    monkeypatch.setattr(sfx, "DIR", tmp_path / "sfx")
    for k in kinds:
        (tmp_path / "sfx" / k).mkdir(parents=True, exist_ok=True)
        for n in range(files):
            (tmp_path / "sfx" / k / f"{k}{n}.wav").write_bytes(b"x")
    monkeypatch.setattr(shorts_edit, "probe", lambda p: 2.0)


def test_sound_effects_only_where_a_line_asks_and_kept_sparse(tmp_path, monkeypatch):
    library(tmp_path, monkeypatch, kinds=("impact", "riser", "heartbeat", "ding"))
    name = lambda e: Path(e["path"]).stem.rstrip("01")
    beats = [{"kind": "story", "shot": i, "dur": 3.0, "text": f"line {i}"} for i in range(10)] + [{"kind": "outro", "shot": 10, "dur": 2.0, "text": "bye", "cue": "ding"}]   # 32 s
    assert youtube.sfx_plan(beats, volume=0.5) == []                                    # no line asked for a sound: silence
    beats[2]["cue"], beats[3]["cue"], beats[6]["cue"], beats[9]["cue"] = "impact", "ding", "riser", "coin"
    plan = youtube.sfx_plan(beats, volume=0.5)
    # the impact where its line starts; the ding one line later is too close (under 4 s); the riser finishes as its line ends
    # (2 s long in a 3 s line starting at 18); "coin" has no file; the outro never gets one
    assert [(e["at"], name(e)) for e in plan] == [(6.0, "impact"), (19.0, "riser")]
    assert plan[0]["volume"] == 0.45 and plan[1]["volume"] == 0.4
    for b in beats[:10]:
        b["cue"] = "heartbeat"                                                          # asked for on every line: still about one per 8 seconds
    assert [e["at"] for e in youtube.sfx_plan(beats, volume=0.5)] == [0.0, 6.0, 12.0, 18.0]
    assert len({e["path"] for e in youtube.sfx_plan(beats, volume=0.5)}) == 2           # repeated cues take different files


def test_the_model_names_a_sound_only_for_lines_that_need_one(tmp_path, monkeypatch, media):
    library(tmp_path, monkeypatch, kinds=("impact", "ding"))

    class Cues(WriterLLM):
        async def json(self, prompt, **kw):
            if prompt.startswith("This narration will have a few sound effects"):
                self.prompts.append(prompt)
                n = int(prompt.split("exactly ")[1].split(" ")[0])
                return (["none", "IMPACT", "explosion", "ding."] + ["none"] * n)[:n]
            return await super().json(prompt, **kw)

    llm = Cues()
    m = make(tmp_path, monkeypatch, media, [], llm)
    library(tmp_path, monkeypatch, kinds=("impact", "ding"))
    keywords = next(a for a in m.agents[0].members if a.name == "Keyword Generator")
    beats = [{"i": i, "shot": i, "kind": "story", "text": f"Line number {i} of the story."} for i in range(6)] + [{"i": 6, "shot": 6, "kind": "outro", "text": "Subscribe."}]
    job = {"beats": beats}
    res = asyncio.run(keywords.run({"job": job, "llm": llm}))
    ask = next(p for p in llm.prompts if p.startswith("This narration"))
    assert "impact (a shock or a revelation lands); ding (a realisation, an idea, good news)" in ask and "riser" not in ask      # only sounds the library has
    assert "Most lines need none" in ask and "At most 1 lines" in ask
    assert [b.get("cue") for b in beats] == [None, "impact", None, "ding", None, None, None] and "2 sound cues" in res.summary  # an unknown sound is ignored
    keywords.ch["sfx"] = False
    job2 = {"beats": [{"i": 0, "shot": 0, "kind": "story", "text": "One line."}]}
    assert "sound cue" not in asyncio.run(keywords.run({"job": job2, "llm": llm})).summary and "cue" not in job2["beats"][0]


def edit_job(tmp_path, mood="sad", **extra):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    beats = [{"i": i, "text": f"beat {i}", "kind": "story", "shot": i, "dur": 4.0, "query": "q", "visual": {"credit": "c", "page": "p"}} for i in range(4)]
    beats[0]["cue"] = "ding"                                   # the one line that asked for a sound
    beats.append({"i": 4, "text": "Subscribe", "kind": "outro", "shot": 4, "dur": 2.0, "query": "q"})
    return {"id": "confessions-x", "key": "confessions:x", "dir": str(work), "title": "T", "hashtags": [], "source": {"title": "t"}, "script": "s", "keywords": [],
            "mood": mood, "original": True, "genre": "confession", "beats": beats, **extra}


def test_editor_passes_motion_caption_look_and_effects_to_assemble(tmp_path, monkeypatch, media):
    library(tmp_path, monkeypatch)
    seen = {}

    def fake(work, beats, **kw):
        seen.update(kw)
        return {"file": str(work / "final.mp4"), "seconds": 18.0, "captions": 7, "shots": 5, "sfx": len(kw["sfx"] or [])}

    monkeypatch.setattr(shorts_edit, "assemble", fake)
    m = make(tmp_path, monkeypatch, media, [], WriterLLM(), music=False)
    monkeypatch.setattr(sfx, "DIR", tmp_path / "sfx")                     # make() points it at an empty folder; use the small library
    editor, store = next(a for a in m.agents[0].members if a.name == "Editor"), Store(tmp_path / "t.db")
    job = edit_job(tmp_path)
    res = asyncio.run(editor.run({"job": job, "store": store, "bus": EventBus()}))
    look = fonts.style_for("sad", "original", 0)
    assert seen["motion"] is True and seen["style"]["fill"] == look["fill"] and seen["style"]["highlight"] == look["highlight"] and seen["style"]["position"] == "center"
    assert "font_name" not in seen["style"] and seen["sfx"] and all(set(e) == {"at", "path", "volume"} for e in seen["sfx"]) and seen["sfx"][0]["volume"] == 0.28 and len(seen["sfx"]) == 1
    rec = store.kv_list(youtube.LOG)[0]
    assert rec["caption"].startswith(look["font_name"]) and look["fill"] in rec["caption"] and rec["sfx"] == len(seen["sfx"]) and rec["quick"] is False
    assert f"in {look['font_name']}" in res.summary and f"{rec['sfx']} sound effects" in res.summary
    # a long video keeps its captions low; each mood's look moves on as the channel makes more of that mood
    job = edit_job(tmp_path, format="long", classic={"title": "x", "author": "y"})
    asyncio.run(editor.run({"job": job, "store": store, "bus": EventBus()}))
    assert seen["wide"] is True and seen["style"]["position"] == "lower"
    # switched off: no style, no effects, no motion
    off = make(tmp_path, monkeypatch, media, [], WriterLLM(), music=False, caption_styles=False, sfx=False, motion=False)
    editor = next(a for a in off.agents[0].members if a.name == "Editor")
    job = edit_job(tmp_path)
    asyncio.run(editor.run({"job": job, "store": Store(tmp_path / "t2.db"), "bus": EventBus()}))
    assert seen["style"] is None and seen["sfx"] is None and seen["motion"] is False and job["caption"] == ""


def test_quick_format_is_an_original_story_once_a_day_with_its_own_length_and_outro(tmp_path, monkeypatch, media):
    llm = WriterLLM(story_words=55)
    m = make(tmp_path, monkeypatch, media, [], llm, originals=True, shorts_per_day=3, quick={"per_day": 1})
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    scout, writer, shaper = (next(a for a in m.agents[0].members if a.name == n) for n in ("Story Scout", "Story Writer", "Screenplay Writer"))
    ch, store, bus = scout.ch, Store(tmp_path / "t.db"), EventBus()
    assert youtube.quick_of(ch) == {"per_day": 1, "seconds": [20, 35], "outro": "Your story could be next. Comment it."}
    assert youtube.quick_of({"quick": {"per_day": 0}})["per_day"] == 0 and youtube.word_range(ch, True) == (43, 65) and youtube.word_range(ch) == (42, 127)
    ctx = {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
    res = asyncio.run(scout.run(ctx))
    assert ctx["job"]["quick"] is True and "a quick one" in res.summary
    asyncio.run(writer.run(ctx))
    prompt = next(p for p in llm.prompts if p.startswith("Write an original"))
    assert "narrated for a 20-35 second video, 46-62 words" in prompt and "1-2 minute" not in prompt
    assert "Keep them listening" in prompt and "No personal names" in prompt                       # the rest of the rules stand
    asyncio.run(shaper.run(ctx))
    assert ctx["job"]["beats"][-1]["text"] == "Your story could be next. Comment it."
    job = ctx["job"]
    job.update(title="T", hashtags=[], keywords=[], seconds=25.0, file="f.mp4")
    for b in job["beats"]:
        b.update(dur=1.0, query="q")
    youtube.save_record(store, ch, job)
    assert store.kv_list(youtube.LOG)[0]["quick"] is True and youtube.made_today(store, ch, quick=True) == 1
    ctx2 = {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
    res2 = asyncio.run(scout.run(ctx2))                                                          # the day's quick one is made: the next is a regular Short
    assert not ctx2["job"].get("quick") and "quick" not in res2.summary
    regular = WriterLLM(story_words=100)
    asyncio.run(writer.run({"job": ctx2["job"], "llm": regular}))                                # a regular story keeps the regular length
    assert "a 1-2 minute video, 62-107 words" in regular.prompts[0]


def test_choose_leans_to_what_performs_and_keeps_trying_the_rest():
    choose = youtube.choose
    assert choose(["a", "b"], {"a": 5, "b": 5}, {"a": 900, "b": 100}, 0.15) == "a"            # the better performer is told more
    assert choose(["a", "b"], {"a": 9, "b": 1}, {"a": 900, "b": 100}, 0.15) == "b"            # but the weaker keeps its floor: 10% told is under 22%
    assert choose(["a", "b", "c"], {"a": 3, "b": 3}, {"a": 100, "b": 100}, 0.15) == "c"       # untested counts as the mean, and is behind
    assert choose(["a", "b"], {"a": 0, "b": 0}, {"a": 1, "b": 1}, 0.1) == "a"                 # a tie goes to the earlier
    assert choose(["a", "b"], {"a": 1, "b": 0}, {}, 0.1) == "b" and choose(["a", "b"], {"a": 0, "b": 4}, {"b": 0}, 0.1) == "a"    # no views: least told
    assert choose(["a", "b"], {"a": 0, "b": 4}, {"a": 100, "b": 1}, 0.5) == "a"              # a floor that takes the whole share: least told


def test_double_down_takes_over_from_least_told_once_there_are_results(tmp_path, monkeypatch, media):
    llm = WriterLLM(story_words=70)
    m = make(tmp_path, monkeypatch, media, [], llm, originals=True, original_genres=["confession", "motivational"], quick={"per_day": 0})
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    scout, store, bus = m.agents[0].members[0], Store(tmp_path / "t.db"), EventBus()
    ctx = lambda: {"store": store, "bus": bus, "llm": llm, "cfg": Config(), "master": "youtube"}
    insights = {"top_titles": [], "views_by_kind": {"original": 10, "motivational": 1000}, "videos": 11}
    store.kv_put(youtube.STATE, "confessions:insights", insights)
    c = ctx()
    asyncio.run(scout.run(c))
    assert c["job"]["genre"] == "confession"                                                  # too few results yet: least told, as before
    store.kv_put(youtube.STATE, "confessions:insights", {**insights, "videos": 12})
    for key in [p["_key"] for p in store.kv_list(youtube.PREMISES)]:
        store.kv_delete(youtube.PREMISES, key)
    c = ctx()
    asyncio.run(scout.run(c))
    assert c["job"]["genre"] == "motivational"                                                # enough: the one that gets views
    # the learning pattern: same switch
    s = youtube.StoryScout(youtube.channel({"original_genres": ["science"], "quick": {"per_day": 0}}))
    assert s._lean(list(youtube.STRUCTURES), {k: 0 for k in youtube.STRUCTURES}, {"belief_flip": 900, "unless": 50}) == "belief_flip"


def test_analytics_compares_quick_and_regular_shorts(tmp_path, monkeypatch, media):
    m = make(tmp_path, monkeypatch, media, [], WriterLLM())
    analytics, store = next(a for a in m.agents[0].members if a.name == "Analytics Manager"), Store(tmp_path / "t.db")
    row = lambda k, views, **kw: store.kv_put(youtube.LOG, k, {"channel": "confessions", "status": "public", "title": k, "seconds": 20, "made": 1, "stats": {"view": views}, **kw})
    asyncio.run(analytics.run({"store": store, "bus": EventBus()}))
    assert store.kv_get(youtube.STATE, "confessions:insights") is None                      # nothing made: nothing saved
    row("a", 100, quick=True), row("b", 300, quick=True), row("c", 50), row("d", 70, quick=False), row("e", 9999, format="long")
    asyncio.run(analytics.run({"store": store, "bus": EventBus()}))
    assert store.kv_get(youtube.STATE, "confessions:insights")["views_by_length"] == {"quick": 200, "regular": 60}       # long videos are not compared
    for k in "abcde":
        store.kv_delete(youtube.LOG, k)
    row("z", 0)
    asyncio.run(analytics.run({"store": store, "bus": EventBus()}))
    assert "views_by_length" not in store.kv_get(youtube.STATE, "confessions:insights")      # no views, no data
