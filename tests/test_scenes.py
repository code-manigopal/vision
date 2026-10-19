"""Animated scenes in Shorts: the model only names a template and short labels; code refuses a scene with an unknown template, a
long label or a figure the line does not say; any trouble leaves the stock footage."""
import asyncio
from pathlib import Path

from vision.bus import EventBus, Store
from vision.masters import scenes, youtube
from vision.services import hyperframes

LINE = "Mount Everest rises 8,849 metres, while the Mariana Trench sinks 10,935 metres below the waves."


def test_check_keeps_only_short_labels_and_figures_the_line_says():
    ok = scenes.check({"template": "compare", "a": "Everest", "b": "Mariana Trench", "a_value": "8,849 m", "b_value": "10,935 m"}, LINE, {"science"})
    assert ok and ok["a_value"] == "8,849 m"
    made_up = scenes.check({"template": "compare", "a": "Everest", "b": "Trench", "a_value": "9,000 m", "b_value": "10,935 m"}, LINE, {"science"})
    assert made_up and made_up["a_value"] == "" and made_up["b_value"] == ""              # a figure the line doesn't say: both values go
    assert scenes.check({"template": "number", "value": "12%", "label": "of the ocean"}, LINE, {"science"}) is None
    assert scenes.check({"template": "flow", "steps": ["Sunlight", "a very long label that keeps going on", "Sugar"]}, "x", {"science"}) is None
    assert scenes.check({"template": "chart3d", "a": "x"}, LINE, {"science"}) is None
    assert scenes.check({"template": "orbit", "center": "Earth", "body": "Moon"}, "x", {"money"}) is None           # not this kind's template
    c = scenes.check({"template": "cycle", "steps": ["Evaporation", "Clouds", "Rain", "Rivers", "Sea", "Sky"]}, "x", {"science"})
    assert c["steps"] == ["Evaporation", "Clouds", "Rain", "Rivers", "Sea"]


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def json(self, prompt, **kw):
        self.asked.append(prompt)
        return self.answer


def job(tmp_path):
    beats = [{"i": i, "text": t, "dur": 3.0, "kind": "story", "visual": {"kind": "video", "path": "stock.mp4", "credit": "Pexels", "source": "pexels"}}
             for i, t in enumerate(["Hook line.", LINE, "Sunlight feeds the leaves, which make sugar.", "Last line."])]
    beats.append({"i": 4, "text": "Subscribe.", "dur": 2.0, "kind": "outro"})
    return {"dir": str(tmp_path), "beats": beats, "original": True, "genre": "science", "source": {"from": "original (science)"}}


def test_the_footage_generator_puts_rendered_scenes_on_their_beats(tmp_path, monkeypatch):
    llm = FakeLLM({"scenes": [{"line": 0, "template": "number", "value": "1", "label": "x"},                        # never the hook
                              {"line": 1, "template": "compare", "a": "Everest", "b": "Mariana Trench", "a_value": "8,849 m", "b_value": "10,935 m"},
                              {"line": 2, "template": "flow", "steps": ["Sunlight", "Leaves", "Sugar"]},
                              {"line": 3, "template": "number", "value": "99%", "label": "made up"}]})        # figure not in the line
    rendered = []

    def fake_render(shots, work):
        rendered.append(shots)
        return [Path(work) / f"scene-{n:02d}.mp4" for n in range(len(shots))]

    monkeypatch.setattr(scenes, "render_shots", fake_render)
    monkeypatch.setattr(hyperframes, "ready", lambda: True)
    j = job(tmp_path)
    gen = youtube.FootageGenerator(youtube.channel({"diagrams": ["science"]}))
    res = asyncio.run(gen.run({"job": j, "llm": llm, "store": Store(tmp_path / "t.db"), "bus": EventBus()}))
    assert [sc["template"] for sc, _ in rendered[0]] == ["compare", "flow"] and res.label == "DIAGRAMS"
    assert j["beats"][1]["visual"]["diagram"] and j["beats"][1]["visual"]["source"] == "diagram" and j["beats"][0]["visual"]["path"] == "stock.mp4"
    assert j["diagrams"] == [{"line": 1, "template": "compare"}, {"line": 2, "template": "flow"}]
    assert "Subscribe." not in llm.asked[0]                                                     # the outro is never a scene


def test_off_for_other_kinds_and_on_render_trouble(tmp_path, monkeypatch):
    monkeypatch.setattr(hyperframes, "ready", lambda: True)
    llm = FakeLLM({"scenes": [{"line": 2, "template": "flow", "steps": ["Sunlight", "Leaves", "Sugar"]}]})
    j = job(tmp_path)
    asyncio.run(youtube.FootageGenerator(youtube.channel({"diagrams": []})).run({"job": j, "llm": llm}))
    assert not llm.asked and "diagrams" not in j                                                # not switched on for science

    def boom(shots, work):
        raise hyperframes.RenderFailed("no chrome")

    monkeypatch.setattr(scenes, "render_shots", boom)
    res = asyncio.run(youtube.FootageGenerator(youtube.channel({"diagrams": ["science"]})).run({"job": j, "llm": llm}))
    assert j["beats"][2]["visual"]["path"] == "stock.mp4" and "not rendered" in res.summary


def test_scene_page_has_one_clip_per_scene_and_no_internet():
    h, js = scenes.scene_html(0, {"template": "number", "value": "59%", "label": "seen"}, 2.0, 3.0)
    assert 'data-start="2.000" data-duration="3.000"' in h and any('"59%"' in x for x in js) and "https://" not in h


def test_finance_scenes_never_promise_money_and_show_no_invented_figures():
    line = "The 50/30/20 rule puts 50% of income to needs, 30% to wants and 20% to savings."
    b = scenes.check({"template": "breakdown", "parts": [{"label": "Needs", "share": "50%"}, {"label": "Wants", "share": "30%"}, {"label": "Savings", "share": "20%"}]}, line, {"money"})
    assert [p["share"] for p in b["parts"]] == ["50%", "30%", "20%"]
    b = scenes.check({"template": "breakdown", "parts": [{"label": "Needs", "share": "60%"}, {"label": "Wants", "share": "40%"}]}, line, {"money"})
    assert [p["share"] for p in b["parts"]] == ["", ""]                                         # shares the line doesn't say: shown without them
    assert scenes.check({"template": "growth", "shape": "compound", "label": "Guaranteed returns"}, line, {"money"}) is None
    assert scenes.check({"template": "growth", "shape": "compound", "label": "Grows 12% a year"}, line, {"money"}) is None   # no figures on a curve
    assert scenes.check({"template": "myth", "myth": "Stocks only go up", "fact": "You will earn ₹5,000 a month"}, line, {"money"}) is None
    assert scenes.check({"template": "checklist", "items": ["Lock-in period", "Interest rate"]}, line, {"money"})
    h, _ = scenes.scene_html(0, {"template": "growth", "shape": "compound", "label": "Interest earns interest"}, 0, 3)
    assert "ILLUSTRATION, NOT A PROMISE" in h


def test_story_scenes_use_the_lines_own_words():
    line = "Her phone buzzed: we need to talk tonight. She typed back, about what? Three years later she still had that message."
    assert scenes.check({"template": "chat", "messages": [{"from": "them", "text": "We need to talk tonight"}, {"from": "me", "text": "About what?"}]}, line, {"story"})
    assert scenes.check({"template": "chat", "messages": [{"from": "them", "text": "I always loved you secretly"}]}, line, {"story"}) is None
    assert scenes.check({"template": "quote", "text": "she still had that message"}, line, {"story"})
    assert scenes.check({"template": "quote", "text": "she deleted every message"}, line, {"story"}) is None    # not the line's words
    assert scenes.check({"template": "timejump", "text": "Three years later"}, line, {"story"})
    assert scenes.check({"template": "timejump", "text": "10 years later"}, line, {"story"}) is None
