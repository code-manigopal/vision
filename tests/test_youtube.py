"""YouTube Manager: the Director tier, the channel crew end to end (Reddit, stock footage and the model mocked; ffmpeg real)."""

import asyncio
import json
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
from vision.services import bgm, genmedia, gutenberg, oauth, reddit, stock_video
from vision.services.llm import LLM

FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
TALE = "Old Behrman had always meant to paint a masterpiece, and never had. " * 40
BOOK = ("Title: The Four Million\nAuthor: O. Henry\n\n*** START OF THE PROJECT GUTENBERG EBOOK THE FOUR MILLION ***\n\nCONTENTS\n\nThe Last Leaf\n\n"
        f"THE LAST LEAF\n\n{TALE}\n\nA SHORT NOTE\n\nToo brief to be a story.\n\nTHE COP AND THE ANTHEM\n\n{TALE}\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK THE FOUR MILLION ***\nlicence text")
GOOD = ("I have carried this for eleven years and nobody in my family knows. " * 12).strip()


class WriterLLM:
    def __init__(self, safe=True, story_words=200):
        self.safe, self.story_words, self.prompts = safe, story_words, []

    async def json(self, prompt, **kw):
        self.prompts.append(prompt)
        if prompt.startswith("You screen"):
            return {"ok": True, "why": ""} if self.safe else None
        if prompt.startswith("Plan short science") or "motivational stories" in prompt[:60]:
            what = "science" if prompt.startswith("Plan") else "motivational"
            body = {"science": "Why is the sea salty? Rain wears salts out of rock, rivers carry them down, and the sun lifts only the water back out.",
                    "motivational": "A single father fails his licence exam twice, nearly gives up, and passes by studying one page every night."}[what]
            return [{"title": f"A {what} one", "premise": body}]
        if prompt.startswith("Invent premises"):
            texts = ["A retired teacher kept quiet about the exam she let a struggling pupil pass, until an old letter turned up at a funeral.",
                     "A delivery driver pocketed a tip meant for a colleague, and a message sent to the wrong person brought it all out.",
                     "An eldest daughter told the family the shop was thriving while the bank statements said otherwise, until one was left open."]
            return [{"title": f"Premise {n + 1}", "premise": t} for n, t in enumerate(texts)] + [
                {"title": "Same again", "premise": texts[0].replace("funeral", "wedding")}, {"title": "Too thin", "premise": "Short."},
                {"title": "Dark", "premise": "A man planned a murder in a small town and nobody ever found out about it at all."}]
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
    for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "PEXELS_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    c = youtube.channel({"subreddits": ["confession"], "seconds": [20, 60], **ch})
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
    assert yt["made_playlist"] == "Classic Stories" and [i["playlistId"] for i in yt["playlist_items"]] == ["PL1"] and yt["posted"] == [cta, cta]
    assert store.kv_get(youtube.STATE, "confessions:playlist:Classic Stories") == {"id": "PL1"}
    assert "in “Classic Stories”" in {a["name"]: a for a in bus.state["masters"]["youtube"]["agents"]}["Uploader"]["summary"]

    monkeypatch.setattr(oauth, "granted", lambda account: "")    # an older sign-in: uploads go on, and one more sign-in is asked for
    youtube.reset_today(store, "confessions")
    m.agents[0].members[0].ch["shorts_per_day"] = 1
    asyncio.run(m.cycle(bus, store))
    assert "youtube-scope-confessions" in bus.state["notices"] and len(yt["posted"]) == 2
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
    assert "1 public with 7 views" in asyncio.run(analytics.run(ctx)).summary


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
