"""YouTube Manager: the Director tier, the channel crew end to end (Reddit, stock footage and the model mocked; ffmpeg real)."""

import asyncio
import json
import shutil
import subprocess

import httpx
import pytest
from PIL import Image

from vision.agents import AgentResult, Director, Master, Stage, SubAgent
from vision.bus import EventBus, Store
from vision.config import Config, LLMConfig
from vision.masters import shorts_edit, youtube
from vision.services import genmedia, oauth, reddit, stock_video
from vision.services.llm import LLM

FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
GOOD = ("I have carried this for eleven years and nobody in my family knows. " * 12).strip()


class WriterLLM:
    def __init__(self, safe=True, story_words=200):
        self.safe, self.story_words, self.prompts = safe, story_words, []

    async def json(self, prompt, **kw):
        self.prompts.append(prompt)
        if prompt.startswith("You screen"):
            return {"ok": True, "why": ""} if self.safe else None
        if prompt.startswith("Retell"):
            sentence = "She kept the letter in a drawer, and every year she almost threw it away. "
            return {"title": "The letter she never sent", "story": " ".join((sentence * 40).split()[:self.story_words]) + ".", "hashtags": ["confession", "#storytime"]}
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
    assert all(youtube.words(b["text"]) <= 22 for b in beats) and " ".join(b["text"] for b in beats[:-1]).startswith("She never told anyone. Not her husband")
    assert youtube.fallback_query("She kept the letter in a drawer") == "letter drawer kept"


def test_speed_and_caption_chunks():
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
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    llm = LLM(Config(llm=LLMConfig(writer_model="llama-x")), client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert asyncio.run(llm.json("hi", tier="writer")) == {"ok": True}
    assert seen == {"url": "https://api.groq.com/openai/v1/chat/completions", "auth": "Bearer k", "model": "llama-x"}
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm._local_ok = (9e12, True)
    assert asyncio.run(llm.pick("writer")) == "local"


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
        if "upload/youtube/v3/videos" in u:
            yt["meta"], yt["auth"] = json.loads(req.content), req.headers["authorization"]
            return httpx.Response(200, headers={"Location": "https://upload.test/session1"})
        if u.startswith("https://upload.test/"):
            yt["bytes"] = len(req.read())
            return httpx.Response(200, json={"id": "vid1", "status": {"privacyStatus": "unlisted"}})
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
    for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "PEXELS_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    c = youtube.channel({"subreddits": ["confession"], "seconds": [20, 60], **ch})
    d = Director(c["director"], youtube.crew(c, client_factory=web(media, posts, yt if yt is not None else {}), synth=tone), reporter="Analytics Manager")
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
    bus, store = EventBus(), Store(tmp_path / "t.db")
    report = asyncio.run(m.cycle(bus, store))
    crew = {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}
    assert [crew[n]["status"] for n in ("Story Scout", "Story Writer", "Screenplay Writer", "Keyword Generator", "Voice Artist", "Footage Collector", "Editor")] == ["done"] * 7, crew
    assert crew["Footage Generator"]["label"] == "OFF" and crew["Uploader"]["label"] == "SIGN IN"       # not signed in: made, kept, asked for
    assert bus.state["notices"]["auth:youtube-confessions"]["url"].endswith("/auth/youtube/login?account=youtube-confessions")
    assert "1 made, 1 waiting for upload" in report and "The letter she never sent" in report

    rec = store.kv_list(youtube.LOG)[0]
    assert rec["source"]["url"] == "https://www.reddit.com/r/confession/ok1" and rec["script"].startswith("She kept the letter") and rec["status"] == "ready"
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
    rec = store.kv_list(youtube.LOG)[0]
    assert rec["status"] == "unlisted" and rec["url"] == "https://youtu.be/vid1" and "1 unlisted for your review" in report
    assert bus.state["notices"]["youtube-review-vid1"]["url"] == "https://studio.youtube.com/video/vid1/edit" and "auth:youtube-confessions" not in bus.state["notices"]

    yt["items"] = [{"id": "vid1", "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "1234", "likeCount": "56"}}]
    report = asyncio.run(m.cycle(bus, store))                # Mani made it public on YouTube: noticed, counted, the reminder goes
    assert "1 public with 1,234 views" in report and "youtube-review-vid1" not in bus.state["notices"] and yt["bytes"] and len(yt) == 4
    assert store.kv_list(youtube.LOG)[0]["stats"] == {"view": 1234, "like": 56, "comment": 0}
    assert {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Uploader"]["label"] == "IDLE"

    yt["items"] = []
    assert "1 deleted" in asyncio.run(m.cycle(bus, store)) and store.kv_list(youtube.LOG)[0]["status"] == "deleted"


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


def test_only_masters_switches_the_others_off():
    from vision.masters import build_masters
    cfg = Config(only_masters=["youtube"], masters={"youtube": {"mode": "live"}, "news": {"enabled": True}})
    assert {m.id for m in build_masters(cfg) if m.enabled} == {"youtube"}
    assert cfg.masters["news"].enabled and not cfg.master("news").enabled          # the master's own setting is left as it was
    cfg = Config(only_masters=[], masters={"news": {"enabled": False}})
    assert not cfg.master("news").enabled and cfg.master("traffic").enabled
