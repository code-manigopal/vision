import asyncio
import io
import random

import httpx
import pytest
from PIL import Image, ImageDraw

from vision.bus import EventBus, Store
from vision.config import Config, MasterConfig
from vision.masters import build_masters, ebook_art as art, ebook_print as pr, ebooks
from vision.services import cfai


def png(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def line_page(seed: int) -> bytes:
    """A clean coloring page: bold outlines of a few shapes, different for every seed."""
    r = random.Random(seed)
    im = Image.new("L", (1024, 1328), 255)
    d = ImageDraw.Draw(im)
    for _ in range(30):
        x, y, s = r.randint(60, 800), r.randint(60, 1100), r.randint(90, 220)
        (d.ellipse if r.random() < 0.5 else d.rectangle)((x, y, x + s, y + s), outline=0, width=7)
    return png(im)


def grey_page() -> bytes:
    im = Image.open(io.BytesIO(line_page(1))).convert("L")
    ImageDraw.Draw(im).rectangle((0, 0, 1024, 900), fill=140)
    return png(im)


def black_page() -> bytes:
    im = Image.open(io.BytesIO(line_page(2))).convert("L")
    ImageDraw.Draw(im).rectangle((0, 0, 1024, 500), fill=0)
    return png(im)


def test_page_checks_refuse_grey_black_and_empty_pages():
    assert art.issues(art.measure(line_page(3))) == []
    assert any("grey" in w for w in art.issues(art.measure(grey_page())))
    assert any("solid black" in w for w in art.issues(art.measure(black_page())))
    assert any("empty" in w for w in art.issues(art.measure(png(Image.new("L", (1024, 1328), 255)))))
    a, b = art.dhash(line_page(4)), art.dhash(line_page(5))
    assert art.alike(a, art.dhash(line_page(4))) and not art.alike(a, b)


def test_print_page_is_pure_black_and_white_at_300_dpi_inside_the_margins():
    p = art.to_print(line_page(6))
    assert p.mode == "1" and p.size == (2550, 3300)
    box = Image.eval(p.convert("L"), lambda v: 255 - v).getbbox()
    assert box[0] >= 0.625 * 300 - 1 and box[1] >= 0.5 * 300 - 1 and box[2] <= 2550 - 0.5 * 300 + 1


def test_price_keeps_a_royalty_and_the_market_band():
    pages = pr.page_count(30)
    assert pages == 66 and pr.spine_in(pages) == pytest.approx(0.1486, abs=1e-4)
    price, royalty = pr.price(30, pages)
    assert price == 7.99 and royalty == round(0.6 * 7.99 - pr.print_cost(pages), 2) and royalty > 1.75


def test_cloudflare_allowance_is_counted_and_a_429_means_spent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    store = Store(tmp_path / "t.db")
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if len(calls) > 1:
            return httpx.Response(429, json={"errors": [{"message": "used up"}]})
        return httpx.Response(200, json={"result": {"image": "aGk="}})

    c = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(cfai.draw(store, "x", 1024, 1328, 1, client=c())) == b"hi"
    assert cfai.used(store) == pytest.approx(6 * cfai.TILE)
    with pytest.raises(cfai.Spent):
        asyncio.run(cfai.draw(store, "x", 1024, 1328, 2, client=c()))
    with pytest.raises(cfai.Spent):                      # the day is marked spent: no further call is made
        asyncio.run(cfai.draw(store, "x", 1024, 1328, 3, client=c()))
    assert len(calls) == 2


class LLM:
    def __init__(self, scenes=40):
        self.scenes = scenes

    async def json(self, prompt, **kw):
        if "NEW scenes" in prompt:
            return {"scenes": [{"title": f"More {i}", "scene": f"a whale and a seal play game number {i}"} for i in range(8)]}
        if "scenes" in prompt:
            return {"title": "Ocean Friends", "subtitle": "30 Big Under-the-Sea Coloring Pages for Ages 4-8",
                    "scenes": [{"title": "Nemo", "scene": "Nemo the clownfish swims"}] +
                              [{"title": f"Scene {i}", "scene": f"a sea turtle and a crab play game number {i} near coral"} for i in range(self.scenes)]}
        return {"description": "Dive in!\n\n• 30 pages", "blurb": "Thirty big happy pages of sea friends to colour.",
                "keywords": ["ocean coloring book", "Bluey coloring", "sea animals for kids"], "categories": [0, 2, 99]}


def setup(tmp_path, monkeypatch, pages=None, look='{"score": 8}', scenes=12):
    monkeypatch.setattr(ebooks, "DATA", tmp_path / "ebooks")
    monkeypatch.setattr(ebooks, "INBOX", tmp_path / "inbox")
    n = iter(range(10_000))
    pages = pages or (lambda prompt: line_page(next(n)))

    async def draw(store, prompt, w, h, seed, budget=10_000, client=None):
        if cfai.left(store, budget) < cfai.draw_cost(w, h):
            raise cfai.Spent("used")
        cfai._spend(store, cfai.draw_cost(w, h))
        return line_page(999) if "cover" in prompt else pages(prompt)

    async def look_(store, png_, q, budget=10_000, client=None):
        cfai._spend(store, cfai.LOOK_COST)
        return look

    monkeypatch.setattr(cfai, "draw", draw)
    monkeypatch.setattr(cfai, "look", look_)
    cfg = Config(masters={"ebooks": MasterConfig(mode="live", options={"queue": ["Ocean Animals | 4-8"], "neuron_budget": 100_000,
                                                                       "pictures": 6, "spares": 3})})
    m = next(x for x in build_masters(cfg) if x.id == "ebooks")
    m.services.update(llm=LLM(scenes), cfg=cfg)
    return m, Store(tmp_path / "t.db"), EventBus()


def test_a_book_is_made_checked_built_and_waits_for_approval(tmp_path, monkeypatch):
    m, store, bus = setup(tmp_path, monkeypatch)
    for _ in range(3):
        asyncio.run(m.cycle(bus, store))
    b = store.kv_list(ebooks.NS)[0]
    assert b["status"] == "awaiting" and b["title"] == "Ocean Friends"
    assert not any("Nemo" in s["scene"] for s in b["scenes"])                # brand and character names never become a page
    assert all(s["state"] == "ok" for s in ebooks.active(b)) and b["pages"] == 4 + 2 * 6 + 2
    L = b["listing"]
    assert L["keywords"] == ["ocean coloring book", "sea animals for kids"]  # a brand keyword is dropped
    assert L["price"] == 7.99 and len(L["categories"]) == 2
    a = store.pending_approvals()
    assert len(a) == 1 and a[0]["payload"]["interior"].startswith("/api/files/") is False   # outside data/: no served link in tests
    for f in ("interior.pdf", "cover.pdf", "cover.png", "contact.png"):
        assert (tmp_path / "ebooks" / b["id"] / f).is_file()
    asyncio.run(m.cycle(bus, store))
    assert len(store.pending_approvals()) == 1                                # asked once, not every run

    out = asyncio.run(ebooks.approve_book(a[0], "approved", {"store": store, "bus": bus}))
    assert out.startswith("approved") and store.kv_get(ebooks.NS, b["id"])["status"] == "ready"
    assert f"ebook:{b['id']}" in bus.state["notices"]


def test_a_page_dropin_rebuilds_and_asks_again_and_the_old_approval_is_outdated(tmp_path, monkeypatch):
    m, store, bus = setup(tmp_path, monkeypatch)
    for _ in range(3):
        asyncio.run(m.cycle(bus, store))
    b = store.kv_list(ebooks.NS)[0]
    old = store.pending_approvals()[0]
    (tmp_path / "inbox" / b["id"]).mkdir(parents=True)
    (tmp_path / "inbox" / b["id"] / "page-03.png").write_bytes(line_page(5000))
    asyncio.run(m.cycle(bus, store))
    asyncio.run(m.cycle(bus, store))
    assert asyncio.run(ebooks.approve_book(old, "approved", {"store": store, "bus": bus})).startswith("outdated")
    newest = [a for a in store.pending_approvals() if a["id"] != old["id"]]
    assert newest and newest[0]["payload"]["key"] != old["payload"]["key"]


def test_bad_pages_are_redrawn_then_dropped_for_a_spare(tmp_path, monkeypatch):
    n = iter(range(100, 900))
    m, store, bus = setup(tmp_path, monkeypatch, pages=lambda p: grey_page() if "number 0 " in p else line_page(next(n)))
    for _ in range(5):
        asyncio.run(m.cycle(bus, store))
    b = store.kv_list(ebooks.NS)[0]
    first = b["scenes"][0]
    assert first["state"] == "dropped" and first["rounds"] == 3 and all(not t["ok"] for t in first["tries"])
    assert len(ebooks.active(b)) == 6 and b["status"] == "awaiting"


def test_vision_check_refuses_a_deformed_page(tmp_path, monkeypatch):
    m, store, bus = setup(tmp_path, monkeypatch, look='{"score": 9, "deformed": true}')
    asyncio.run(m.cycle(bus, store))
    b = store.kv_list(ebooks.NS)[0]
    t = b["scenes"][0]["tries"][0]
    assert t["ok"] is False and "deformed character" in t["why"]


def test_the_free_allowance_running_out_is_a_rest_not_a_fault(tmp_path, monkeypatch):
    m, store, bus = setup(tmp_path, monkeypatch)
    m.services["options"] = {**m.services["options"], "neuron_budget": 500}
    asyncio.run(m.cycle(bus, store))
    agents = {a["name"]: a for a in bus.state["masters"]["ebooks"]["agents"]}
    assert agents["Illustrator"]["label"] == "RESTING" and agents["Illustrator"]["status"] == "done"
    assert store.kv_list(ebooks.NS)[0]["status"] == "drawing"


def test_spares_running_out_asks_the_writer_for_more(tmp_path, monkeypatch):
    n = iter(range(500, 900))
    m, store, bus = setup(tmp_path, monkeypatch, pages=lambda p: grey_page() if "number 0 " in p else line_page(next(n)), scenes=6)
    for _ in range(6):
        asyncio.run(m.cycle(bus, store))
    b = store.kv_list(ebooks.NS)[0]
    assert any(s["title"].startswith("More") for s in b["scenes"]) and b["status"] == "awaiting"
