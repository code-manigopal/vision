import asyncio
from pathlib import Path

from vision.masters import motion

LINE = "Venus stays at four hundred sixty degrees Celsius everywhere, day and night."


def test_said_numbers_reads_digits_and_words():
    assert "460" in motion.said_numbers(LINE)
    assert "90" in motion.said_numbers("a blanket ninety times thicker than Earth's")
    assert "2026" in motion.said_numbers("in 2026 it changed")


def test_on_screen_text_must_come_from_the_line():
    assert motion.text_ok("Venus everywhere", LINE)
    assert not motion.text_ok("Hottest planet ever recorded", LINE)        # words the line never says
    assert not motion.text_ok("500 degrees", LINE)                         # a figure the line never says
    assert not motion.text_ok("one two three four five six seven", LINE)   # too long


def test_check_refuses_unsaid_figures_and_missing_pictures():
    assert motion.check({"type": "number", "value": "460°C", "label": "Venus everywhere"}, LINE, set(), set())["value"] == "460°C"
    assert motion.check({"type": "gauge", "value": "500", "label": "Venus"}, LINE, set(), set()) is None
    assert motion.check({"type": "photo", "image": "Venus"}, LINE, set(), set()) is None            # the Asset Finder found no picture
    assert motion.check({"type": "photo", "image": "Venus"}, LINE, {"Venus"}, set())["image"] == "Venus"
    assert motion.check({"type": "compare", "a": "Mercury", "b": "Venus"}, LINE, set(), set()) is None   # the line names no Mercury
    flow = motion.check({"type": "flow", "steps": ["Venus", "night"], "icons": ["sun", "made-up"]}, LINE, set(), {"sun"})
    assert flow["icons"] == ["sun", ""]
    assert motion.check({"type": "html", "code": "<script>"}, LINE, set(), set()) is None


def test_keywords_skip_little_words_and_repeats():
    assert motion.keywords("the temperature climbs and climbs") == "temperature climbs"
    assert "Venus" not in motion.keywords("Venus stays hot everywhere", avoid="Venus")


def beats():
    return [{"text": "Venus burns hotter than Mercury.", "dur": 2.0}, {"text": "Scientists puzzled over this for decades.", "dur": 4.0},
            {"text": LINE, "dur": 2.5}, {"text": "Follow for more.", "dur": 1.5, "kind": "outro"}]


def test_timeline_covers_the_voice_and_splits_long_lines():
    plan = [{"type": "hook", "title": "Venus hotter", "beat": 0}, {"type": "outro", "text": "Follow", "beat": 3}]
    tl = motion.timeline(plan, beats(), 10.4)
    assert tl[0]["type"] == "hook" and tl[0]["start"] == 0
    assert tl[-1]["type"] == "outro" and tl[-1]["end"] == 10.4
    assert [s for s in tl if 2.0 <= s["start"] < 6.0].__len__() == 2      # a 4 s line gets two scenes
    assert all(a["end"] == b["start"] for a, b in zip(tl, tl[1:]))      # no gap, no overlap


class PlanLLM:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    async def json(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.answer


def test_planner_checks_places_and_finds_pictures(monkeypatch, tmp_path):
    from vision.services import visuals
    pic = tmp_path / "venus.jpg"
    pic.write_bytes(b"x")

    async def picture(c, kind, subject, judge=None):
        return {"path": str(pic), "credit": "NASA", "page": "https://images.nasa.gov/x", "license": "Public domain", "title": subject} if subject == "Venus" else None

    async def icon(c, name):
        return tmp_path / f"{name}.svg"
    monkeypatch.setattr(visuals, "picture", picture)
    monkeypatch.setattr(visuals, "icon", icon)
    answer = {"lines": [
        {"line": 0, "scenes": [{"type": "hook", "title": "Venus hotter?", "image": "Venus"}]},
        {"line": 1, "scenes": [{"type": "number", "value": "460°C", "label": "Venus everywhere"}]},   # really line 2's figure: moved there
        {"line": 2, "scenes": [{"type": "photo", "image": "Saturn", "tag": "Venus"}]},                 # no picture found: refused
        {"line": 3, "scenes": [{"type": "text", "lines": ["Follow"]}]},                                # the outro is code's own
    ]}
    llm = PlanLLM(answer)
    got = asyncio.run(motion.plan_short(llm, beats(), "space", "Follow for more", None))
    kinds = [(s["beat"], s["type"]) for s in got["plan"]]
    assert kinds == [(0, "hook"), (2, "number"), (3, "outro")]
    assert len(got["refused"]) == 1 and got["images"] == {"Venus": Path(pic)}
    assert got["credits"] == ["Venus: NASA (Public domain), https://images.nasa.gov/x"]
    assert "Every word shown must come from that same line" in llm.prompts[0] and "map" not in llm.prompts[0].split("Rules:")[0]


def test_planner_without_an_answer_gives_only_the_outro():
    got = asyncio.run(motion.plan_short(PlanLLM(None), beats(), "space", "Follow", None))
    assert [s["type"] for s in got["plan"]] == ["outro"]


def test_build_names_assets_by_their_real_extension(tmp_path):
    plan = motion.timeline([{"type": "outro", "text": "Follow", "beat": 3}], beats(), 10.4)
    page, assets = motion.build(plan, [], kind="body", seconds=10.4, images={}, icons={}, voice=tmp_path / "v.wav",
                                music=tmp_path / "song.ogg", sfx={"whoosh": tmp_path / "w.wav"})
    assert "assets/music.ogg" in page and "music.ogg" in assets and "whoosh.wav" in assets


def test_a_flag_is_the_named_countrys_own_flag(monkeypatch, tmp_path):
    from vision.masters import maps
    from vision.services import visuals
    monkeypatch.setattr(maps, "known", lambda name: {"nepal": "Nepal"}.get(name.lower()))
    asked = []

    async def flag(c, country):
        asked.append(country)
        return {"path": str(tmp_path / "np.png"), "credit": "Commons", "page": "p", "license": "Public domain", "title": "Flag of Nepal"}

    async def picture(c, kind, subject, judge=None):
        raise AssertionError("a flag is never searched for")
    monkeypatch.setattr(visuals, "flag", flag)
    monkeypatch.setattr(visuals, "picture", picture)
    bs = [{"text": "Nepal has the only flag that is not a rectangle.", "dur": 3.0}, {"text": "A single flag.", "dur": 2.0}]
    answer = {"lines": [{"line": 0, "scenes": [{"type": "photo", "image": "flag of Nepal", "tag": "Nepal flag"}]},
                        {"line": 1, "scenes": [{"type": "photo", "image": "flag", "tag": "single flag"}]}]}
    got = asyncio.run(motion.plan_short(PlanLLM(answer), bs, "geography", "Follow", None))
    assert asked == ["Nepal"] and [s["image"] for s in got["plan"]] == ["flag of Nepal"]


def test_the_vision_models_answer_is_read_as_yes_no_or_unsure():
    assert motion.verdict("**Yes**, a mountain range from orbit.") is True
    assert motion.verdict("No, it is a photo of Neptune, a planet.") is False
    assert motion.verdict("The picture shows a river valley.") is None


def test_the_judge_stops_after_three_looks_and_stands_aside_without_cloudflare(monkeypatch, tmp_path):
    from vision.services import cfai
    pic = tmp_path / "p.jpg"
    pic.write_bytes(b"x")
    answers = []

    async def look(store, data, q, **kw):
        answers.append(q)
        return "No, it shows a logo."
    monkeypatch.setattr(cfai, "look", look)
    judge = motion.judge_with(object(), "space")
    rec = {"path": str(pic)}
    assert [asyncio.run(judge(rec, "Saturn")) for _ in range(4)] == [False] * 4 and len(answers) == 3
    assert "Saturn" in answers[0] and "kind, not the name" in answers[0]

    async def down(store, data, q, **kw):
        raise cfai.CFError("no key")
    monkeypatch.setattr(cfai, "look", down)
    assert asyncio.run(motion.judge_with(object(), "space")(rec, "Saturn")) is None


def test_a_filler_reuses_a_photo_only_on_a_line_about_it():
    assert motion._filler("The Alps rise above the lakes", "", "Swiss Alps")["type"] == "photo"
    assert motion._filler("Rivers guide trade and daily life", "", "Swiss Alps")["type"] == "text"


def test_a_compare_shows_pictures_only_when_both_sides_have_one():
    line = "The Rhine runs between Germany and France."
    one = motion.check({"type": "compare", "a": "Germany", "b": "France", "a_image": "flag of Germany"}, line, {"flag of Germany"}, set())
    two = motion.check({"type": "compare", "a": "Germany", "b": "France", "a_image": "flag of Germany", "b_image": "flag of France"}, line,
                       {"flag of Germany", "flag of France"}, set())
    assert one["a_image"] is None and two["b_image"] == "flag of France"
