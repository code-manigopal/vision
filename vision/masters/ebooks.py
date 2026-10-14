"""E-books Manager (live): KDP paperback coloring books for children, brand "Grow Kids Max Studio" (Mani, 2026-10-14).

Theme Planner -> Page Writer -> Illustrator -> Page Inspector -> Book Builder + Cover Designer + Listing Writer
-> (YOU) -> Shelf Manager (reporter). One book at a time; quality before volume.

Zero cost: pictures from FLUX.2 klein on Cloudflare Workers AI and a vision check on Cloudflare's Llama 3.2 Vision,
both inside the free 10,000 neurons a day (`services/cfai.py`, about 60 pages a day; a book takes one to two days and
simply carries on after the allowance resets at 00:00 UTC); words from Groq. Each page is drawn `tries` times a
round; a try passes the code checks (`ebook_art.issues`: grey shading, solid black fills, hairlines, empty or too
dense, spaces too small for the age) and the vision check (deformed, garbled text, scary, off-scene), and the best
passing try is kept. A page with no passing try after `rounds` rounds is dropped and a spare scene takes its place.

You can replace anything: drop `page-07.png` (or `cover.png` for the front art) into `inbox/ebooks/<book>/` and
the book is rebuilt and asked again. `python -m vision ebooks redraw <book> 7` draws a page again.
Nothing is uploaded: after you approve, a notice says the files are ready, you upload them to KDP yourself, then
`python -m vision ebooks published <book>`. Records: kv `ebooks` (one per book); files in data/ebooks/<book>/.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from ..agents import AgentResult, SubAgent, request_approval
from ..config import ROOT
from ..services import cfai
from . import ebook_art as art
from . import ebook_print as pr

NS = "ebooks"
DATA = ROOT / "data" / "ebooks"
INBOX = ROOT / "inbox" / "ebooks"
ACTIVE = ("planned", "written", "drawing", "checked", "built", "awaiting")

THEMES = [  # theme, ages, what the pages are about
    ("Ocean Animals", "4-8", "sea turtles, dolphins, octopus, whales, clownfish, crabs, seahorses at play under the sea"),
    ("Dinosaur Days", "4-8", "friendly dinosaurs playing, eating, hatching, exploring volcano valleys"),
    ("Space Adventure", "4-8", "kid astronauts, rockets, planets, moon buggies, friendly aliens, stars"),
    ("Farm Friends", "2-4", "cows, pigs, chickens, sheep, a tractor, a barn, simple big shapes"),
    ("Jungle Safari", "4-8", "lions, elephants, giraffes, monkeys, parrots, zebras in the jungle"),
    ("Sports Day", "4-8", "animals playing football, cricket, basketball, swimming, running races"),
    ("Vehicles on the Go", "2-4", "cars, trucks, fire engines, trains, buses, planes, big simple shapes"),
    ("Bugs and Butterflies", "4-8", "butterflies, ladybugs, bees, snails, caterpillars in a garden"),
    ("Under the Sea Mermaids", "4-8", "mermaids with sea friends, coral castles, treasure chests"),
    ("Cute Cats and Dogs", "4-8", "puppies and kittens playing, sleeping, baking, at the park"),
    ("Robots and Inventions", "8-12", "kid inventors, robots, gadgets, workshops, flying machines"),
    ("Weather and Seasons", "4-8", "rain, snow, sunshine, rainbows, autumn leaves, children outdoors"),
    ("Money Smart Kids", "4-8", "a piggy bank, saving coins, a lemonade stand, a market, sharing"),
    ("Healthy Food Friends", "2-4", "smiling fruits and vegetables, a picnic, a kitchen"),
    ("Mandala Animals", "8-12", "animals filled with simple mandala patterns, bold outlines"),
    ("Fairy Tale Castles", "4-8", "castles, dragons, knights, princesses, unicorns, enchanted forests"),
    ("Arctic Animals", "4-8", "polar bears, penguins, seals, arctic foxes, igloos, northern lights"),
    ("Birds of the World", "8-12", "owls, peacocks, parrots, eagles, flamingos, hummingbirds"),
    ("Construction Site", "2-4", "diggers, cranes, dump trucks, bulldozers, cement mixers"),
    ("Musical Animals", "4-8", "animals playing drums, guitar, piano, violin, singing on stage"),
]
STYLE = {
    "2-4": "very simple bold thick outlines, big shapes, one main subject, very few details, plain background",
    "4-8": "clean bold outlines, cute friendly characters with big eyes, medium detail, a simple background scene",
    "8-12": "clean confident outlines, detailed scene with background, patterns and many areas to colour",
}
PAGE = ("Black and white coloring book page for children, portrait. Pure black outlines on a plain white background, "
        "no shading, no grey, no color, no gradients, no hatching, no solid black areas, no text, no letters, no border. {style}. Scene: {scene}")
COVER = ("Bright colorful children's coloring book cover illustration, portrait. {scene}. Cheerful cute cartoon style, "
         "vivid colours, soft sky, lots of characters smiling at the viewer, leave the top third calm and simple for the title. "
         "No text, no letters, no words, no logos.")
LOOK_Q = ("This is a page from a children's coloring book (ages {ages}). It should show: {scene}\n"
          "Look carefully and reply with JSON only: {{\"score\": 0-10 for how good and clear a coloring page it is, "
          "\"deformed\": true if any character has extra or missing limbs, a melted or broken face or body, "
          "\"garbled_text\": true if there are letters or words in the picture, \"scary\": true if anything is frightening for a young child, "
          "\"missing\": [main things from the description that are not in the picture], \"notes\": \"one short sentence\"}}")
BRANDS = re.compile(r"\b(disney|pixar|marvel|pok[eé]mon|pikachu|mickey|minnie|elsa|frozen|bluey|peppa|paw patrol|spider-?man|batman|superman|"
                    r"barbie|hello kitty|minecraft|roblox|sonic|mario|lego|nemo|dory|simba|lion king|shrek|sesame|elmo|cocomelon|moana|"
                    r"toy story|harry potter|star wars|transformers|hot wheels|care bears|smurfs?|garfield|snoopy|peanuts|looney|bugs bunny|"
                    r"scooby|dora|thomas the tank|my little pony|teletubbies|spongebob|crayola|baby shark)\b", re.I)
HYPE = re.compile(r"\b(best ?sell\w*|#\s?1|number one|free|amazon|kindle|award|top rated|guaranteed)\b", re.I)
CATEGORIES = [
    "Children's Books › Activities, Crafts & Games › Coloring Books",
    "Children's Books › Activities, Crafts & Games › Activity Books",
    "Children's Books › Animals › Marine Life",
    "Children's Books › Animals › Dinosaurs",
    "Children's Books › Animals › Farm Animals",
    "Children's Books › Animals › Zoos",
    "Children's Books › Animals › Pets",
    "Children's Books › Animals › Birds",
    "Children's Books › Animals › Insects, Spiders, Etc.",
    "Children's Books › Science, Nature & How It Works › Astronomy & Space",
    "Children's Books › Science, Nature & How It Works › Weather",
    "Children's Books › Cars, Trains & Things That Go",
    "Children's Books › Sports & Outdoors",
    "Children's Books › Fairy Tales, Folk Tales & Myths",
    "Children's Books › Growing Up & Facts of Life › Health",
    "Children's Books › Money",
    "Children's Books › Arts, Music & Photography › Music",
    "Children's Books › Science Fiction & Fantasy › Robots",
]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def folder(b: dict) -> Path:
    return DATA / b["id"]


def load(store, bid: str) -> dict | None:
    return store.kv_get(NS, bid)


def save(store, b: dict) -> None:
    store.kv_put(NS, b["id"], {k: v for k, v in b.items() if not k.startswith("_")})


def current(store) -> dict | None:
    books = [b for b in store.kv_list(NS, 0, 500) if b.get("status") in ACTIVE]
    books.sort(key=lambda b: b.get("made") or 0)
    return books[0] if books else None


def active(b: dict) -> list[dict]:
    """The pages in the book: the first `pictures` scenes that are not dropped."""
    return [s for s in b.get("scenes", []) if s.get("state") != "dropped"][: b["pictures"]]


def dropin(b: dict, name: str) -> Path | None:
    p = INBOX / b["id"] / name
    return p if p.is_file() else None


def seed(b: dict, n: int, k: int) -> int:
    return int(hashlib.sha1(f"{b['id']}:{n}:{k}".encode()).hexdigest()[:8], 16)


def _opts(ctx) -> dict:
    return ctx.get("options") or {}


def _budget(ctx) -> int:
    return int(_opts(ctx).get("neuron_budget", 9500))


# ---------- agents ----------
class ThemePlanner(SubAgent):
    name, tier, note = "Theme Planner", "QUICK", "next theme + age band"

    async def run(self, ctx):
        store, o = ctx["store"], _opts(ctx)
        b = current(store)
        if b:
            return AgentResult("done", "IN PROGRESS", f"{b['theme']} (ages {b['ages']}) is still being made", {"book": b["id"]})
        done = {(x.get("theme") or "").lower() for x in store.kv_list(NS, 0, 500)}
        queue = [q.split("|") for q in o.get("queue") or []]
        pick = next(((t.strip(), (a.strip() if a else "4-8"), "") for t, *rest in queue for a in [rest[0] if rest else ""] if t.strip().lower() not in done), None)
        if not pick:
            pick = next(((t, a, h) for t, a, h in THEMES if t.lower() not in done), None)
        if not pick:
            return AgentResult("done", "NO THEMES", "Every theme in the bank has a book; add more to masters.ebooks.options.queue", {})
        theme, ages, hint = pick
        hint = hint or next((h for t, a, h in THEMES if t.lower() == theme.lower()), "")
        b = {"id": f"{slug(theme)}-{date.today().isoformat()}", "theme": theme, "ages": ages if ages in art.AGES else "4-8", "hint": hint,
             "pictures": int(o.get("pictures", 30)), "author": o.get("author", "Grow Kids Max Studio"), "trim": o.get("trim", [8.5, 11.0]),
             "status": "planned", "made": time.time(), "year": date.today().year}
        save(store, b)
        return AgentResult("done", "PLANNED", f"Next book: {theme}, ages {b['ages']}, {b['pictures']} pictures", {"book": b["id"]})


class PageWriter(SubAgent):
    name, tier, note = "Page Writer", "CLOUD", "30 scenes · Groq"

    async def run(self, ctx):
        store, o = ctx["store"], _opts(ctx)
        b = current(store)
        if b and b.get("more"):
            return await self.more(ctx, b)
        if not b or b["status"] != "planned":
            return AgentResult("done", "WAITING" if not b else "WRITTEN", "Nothing to write" if not b else f"{b['theme']}: scenes written", {})
        want = b["pictures"] + int(o.get("spares", 8))
        ask = (f"Plan a children's coloring book. Theme: {b['theme']}. Ages {b['ages']}. About: {b['hint']}.\n"
               f"Give a catchy book title (2-5 words, no brand or character names), a subtitle under 70 characters that says what is inside and for what ages, "
               f"and {want} different coloring page scenes. Each scene: a short page title and one sentence describing exactly what is drawn "
               f"(who, doing what, where, 2-4 main things). Every scene different in setting and action; cheerful, kind and safe; "
               f"no text or signs in the picture; no famous characters or brands.\n"
               'JSON: {"title": "...", "subtitle": "...", "scenes": [{"title": "...", "scene": "..."}]}')
        out = await ctx["llm"].json(ask, tier="writer", max_tokens=4000, model=o.get("model") or None)
        scenes, seen = [], set()
        for s in (out or {}).get("scenes") or []:
            text = f"{s.get('title', '')} {s.get('scene', '')}".strip()
            key = re.sub(r"\W+", " ", (s.get("scene") or "").lower()).strip()
            if not s.get("scene") or BRANDS.search(text) or key in seen:
                continue
            seen.add(key)
            scenes.append({"n": len(scenes) + 1, "title": str(s.get("title") or "")[:60], "scene": str(s["scene"])[:300], "state": "todo", "tries": [], "rounds": 0})
        title, sub = str((out or {}).get("title") or b["theme"])[:60], str((out or {}).get("subtitle") or "")[:90]
        if BRANDS.search(title) or HYPE.search(title):
            title = b["theme"]
        if len(scenes) < b["pictures"]:
            raise RuntimeError(f"the writer gave {len(scenes)} usable scenes, {b['pictures']} needed")
        b.update(title=title, subtitle=sub if not BRANDS.search(sub) else "", scenes=scenes, status="written")
        save(store, b)
        return AgentResult("done", "WRITTEN", f"{title}: {len(scenes)} scenes ({b['pictures']} pages + {len(scenes) - b['pictures']} spares)", {"book": b["id"]})


    async def more(self, ctx, b: dict) -> AgentResult:
        """Pages kept failing and the spares are used up: new scenes, different from every scene so far."""
        want = b["more"] + 4
        before = "; ".join(s["scene"][:80] for s in b["scenes"])[:3000]
        out = await ctx["llm"].json(f"Children's coloring book, theme {b['theme']}, ages {b['ages']}. Scenes already used:\n{before}\n"
                                    f"Write {want} NEW scenes unlike all of those (different place and action), cheerful and safe, no text or brands.\n"
                                    'JSON: {"scenes": [{"title": "...", "scene": "..."}]}', tier="writer", max_tokens=2000, model=_opts(ctx).get("model") or None)
        added = 0
        for s in (out or {}).get("scenes") or []:
            if s.get("scene") and not BRANDS.search(f"{s.get('title', '')} {s['scene']}"):
                b["scenes"].append({"n": len(b["scenes"]) + 1, "title": str(s.get("title") or "")[:60], "scene": str(s["scene"])[:300],
                                    "state": "todo", "tries": [], "rounds": 0})
                added += 1
        if not added:
            raise RuntimeError("the writer gave no usable new scenes")
        b.pop("more", None)
        save(ctx["store"], b)
        return AgentResult("done", "MORE SCENES", f"{b['title']}: {added} new scenes written", {"book": b["id"]})


class Illustrator(SubAgent):
    name, tier, note = "Illustrator", "API", "FLUX.2 klein · Cloudflare free"
    blocking = False

    async def run(self, ctx):
        store, o = ctx["store"], _opts(ctx)
        b = current(store)
        if not b or b["status"] not in ("written", "drawing"):
            return AgentResult("done", "IDLE", "No pages to draw", {})
        tries, W, H = int(o.get("tries", 2)), 1024, 1328
        drawn, rest = 0, ""
        for s in active(b):
            if s["state"] != "todo" or dropin(b, f"page-{s['n']:02d}.png"):
                continue
            fresh = [t for t in s["tries"] if t.get("round") == s["rounds"]]
            for k in range(len(fresh), tries):
                if cfai.left(store, _budget(ctx)) < cfai.draw_cost(W, H) + cfai.LOOK_COST * tries:
                    rest = "allowance"
                    break
                try:
                    png = await cfai.draw(store, PAGE.format(style=STYLE[b["ages"]], scene=s["scene"]), W, H, seed(b, s["n"], s["rounds"] * 10 + k),
                                          budget=_budget(ctx))
                except cfai.Spent:
                    rest = "allowance"
                    break
                f = folder(b) / "tries" / f"page-{s['n']:02d}-r{s['rounds']}-{k}.png"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(png)
                s["tries"].append({"file": str(f), "round": s["rounds"]})
                drawn += 1
            if rest:
                break
        b["status"] = "drawing"
        save(store, b)
        ready = sum(1 for s in active(b) if s["state"] == "ok")
        if rest:
            return AgentResult("done", "RESTING", f"{b['title']}: drew {drawn} · today's free allowance is used · {ready} of {b['pictures']} pages ready · carries on after 8 pm", {"book": b["id"]})
        return AgentResult("done", f"{drawn} DRAWN", f"{b['title']}: drew {drawn} pictures · {ready} of {b['pictures']} pages ready", {"book": b["id"]})


def _verdict(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


class PageInspector(SubAgent):
    name, tier, note = "Page Inspector", "API", "grey · fills · lines · vision check"
    blocking = False

    async def run(self, ctx):
        store, o = ctx["store"], _opts(ctx)
        b = current(store)
        if not b or b["status"] != "drawing":
            return AgentResult("done", "IDLE", "No pages to check", {})
        rounds, tries, min_score = int(o.get("rounds", 3)), int(o.get("tries", 2)), float(o.get("min_score", 6))
        kept = {s["n"]: s["hash"] for s in active(b) if s["state"] == "ok" and s.get("hash")}
        looked = passed = 0
        spent = False
        for s in active(b):
            if s["state"] != "todo":
                continue
            for t in s["tries"]:
                if "ok" in t or spent:
                    continue
                png = Path(t["file"]).read_bytes()
                t["m"] = art.measure(png)
                t["hash"] = art.dhash(png)
                why = art.issues(t["m"], b["ages"])
                if any(art.alike(t["hash"], h) for n, h in kept.items() if n != s["n"]):
                    why.append("near-copy of another page")
                if not why:
                    try:
                        v = _verdict(await cfai.look(store, png, LOOK_Q.format(ages=b["ages"], scene=s["scene"]), budget=_budget(ctx)))
                    except cfai.Spent:
                        spent = True
                        t.pop("m", None)
                        continue
                    looked += 1
                    t["score"] = float(v.get("score") or 0)
                    t["notes"] = str(v.get("notes") or "")[:160]
                    why += [w for w, bad in (("deformed character", v.get("deformed")), ("letters in the picture", v.get("garbled_text")),
                                             ("scary for a young child", v.get("scary"))) if bad]
                    if t["score"] < min_score:
                        why.append(f"scored {t['score']:.0f}/10")
                    if len(v.get("missing") or []) > 1:
                        why.append("missing " + ", ".join(map(str, v["missing"][:3])))
                t["ok"], t["why"] = not why, why
            if spent:
                break
            this = [t for t in s["tries"] if t.get("round") == s["rounds"]]
            good = [t for t in s["tries"] if t.get("ok")]
            if good:
                best = max(good, key=lambda t: (t.get("score") or 0, -(t["m"]["grey"])))
                s.update(state="ok", pick=best["file"], hash=best["hash"], score=best.get("score"))
                kept[s["n"]] = best["hash"]
                passed += 1
            elif len(this) >= tries and all("ok" in t for t in this):
                s["rounds"] += 1
                if s["rounds"] >= rounds:
                    s["state"] = "dropped"            # a spare scene steps in: active() takes the next one
        pages = active(b)
        if len(pages) < b["pictures"]:
            b["more"] = b["pictures"] - len(pages)     # the Page Writer adds fresh scenes on the next run
            save(store, b)
            return AgentResult("done", "MORE SCENES", f"{b['title']}: {len(pages)} usable scenes of {b['pictures']}; new scenes are written next run", {"book": b["id"]})
        ok = sum(1 for s in pages if s["state"] == "ok" or dropin(b, f"page-{s['n']:02d}.png"))
        if ok == b["pictures"]:
            b["status"] = "checked"
        save(store, b)
        dropped = sum(1 for s in b["scenes"] if s["state"] == "dropped")
        label = "ALL PASSED" if ok == b["pictures"] else "RESTING" if spent else f"{ok}/{b['pictures']}"
        return AgentResult("done", label, f"{b['title']}: {ok} of {b['pictures']} pages passed · {looked} looked at by the vision check"
                           + (f" · {dropped} scenes dropped after {rounds} rounds" if dropped else "") + (" · allowance used, carries on after 8 pm" if spent else ""),
                           {"book": b["id"]})


def _final_pngs(b: dict) -> list[bytes]:
    out = []
    for s in active(b):
        p = dropin(b, f"page-{s['n']:02d}.png") or Path(s["pick"])
        out.append(p.read_bytes())
    return out


def signature(b: dict) -> str:
    parts = [str(dropin(b, f"page-{s['n']:02d}.png") or s.get("pick")) for s in active(b)]
    for p in [dropin(b, f"page-{s['n']:02d}.png") for s in active(b)] + [dropin(b, "cover.png")]:
        if p:
            parts.append(str(p.stat().st_mtime))
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _ready_to_build(b: dict | None, mark: str | None = None) -> bool:
    """All pages passed and (with `mark`) this step hasn't been done for the pages as they are now."""
    return bool(b) and b["status"] in ("checked", "awaiting") and (mark is None or b.get(mark) != signature(b))


class BookBuilder(SubAgent):
    name, tier, note = "Book Builder", "QUICK", "300 DPI interior PDF"

    async def run(self, ctx):
        store = ctx["store"]
        b = current(store)
        if not _ready_to_build(b, "built_sig"):
            return AgentResult("done", "IDLE", "Nothing to build", {})
        trim = tuple(b.get("trim") or (8.5, 11.0))
        pngs = _final_pngs(b)
        pages = []
        for i, png in enumerate(pngs):
            pg = art.to_print(png, trim)
            f = folder(b) / "pages" / f"page-{i + 1:02d}.png"
            f.parent.mkdir(parents=True, exist_ok=True)
            pg.save(f, dpi=(art.DPI, art.DPI))
            pages.append(pg)
        n = pr.interior(pages, b, folder(b) / "interior.pdf")
        pr.contact_sheet(pngs, folder(b) / "contact.png")
        b.update(pages=n, interior=str(folder(b) / "interior.pdf"), contact=str(folder(b) / "contact.png"), built_sig=signature(b))
        save(store, b)
        return AgentResult("done", "BUILT", f"{b['title']}: interior PDF, {n} pages at 300 DPI", {"book": b["id"]})


class CoverDesigner(SubAgent):
    name, tier, note = "Cover Designer", "API", "colour cover + spine"
    blocking = False

    async def run(self, ctx):
        store = ctx["store"]
        b = current(store)
        if not _ready_to_build(b, "cover_sig"):
            return AgentResult("done", "IDLE", "Nothing to cover", {})
        if not b.get("listing"):
            return AgentResult("done", "WAITING", f"{b['title']}: the cover waits for the listing (its back-cover text)", {"book": b["id"]})
        own = dropin(b, "cover.png")
        art_file = folder(b) / "cover-art.png"
        if own:
            art_png = own.read_bytes()
        elif art_file.is_file():
            art_png = art_file.read_bytes()
        else:
            scene = f"{b['theme']}: {b['hint']}" if b.get("hint") else b["theme"]
            try:
                art_png = await cfai.draw(store, COVER.format(scene=scene), 1536, 1984, seed(b, 0, 0), budget=_budget(ctx) + 400)
            except cfai.Spent:
                return AgentResult("done", "RESTING", f"{b['title']}: the cover waits for tomorrow's allowance", {"book": b["id"]})
            art_file.parent.mkdir(parents=True, exist_ok=True)
            art_file.write_bytes(art_png)
        pngs = _final_pngs(b)
        blurb = b["listing"].get("blurb") or ""
        size = pr.cover(art_png, [pngs[i * len(pngs) // 6] for i in range(6)], {**b, "blurb": blurb},
                        pr.page_count(b["pictures"]), folder(b) / "cover.pdf", folder(b) / "cover.png")
        b.update(cover=str(folder(b) / "cover.pdf"), cover_png=str(folder(b) / "cover.png"), cover_size=size, cover_own=bool(own), cover_sig=signature(b))
        save(store, b)
        return AgentResult("done", "COVER", f"{b['title']}: cover {size['width_in']} x {size['height_in']} in, spine {size['spine_in']} in"
                           + (" (your art)" if own else ""), {"book": b["id"]})


class ListingWriter(SubAgent):
    name, tier, note = "Listing Writer", "CLOUD", "title · keywords · price"

    async def run(self, ctx):
        store, o = ctx["store"], _opts(ctx)
        b = current(store)
        if not _ready_to_build(b) or b.get("listing"):
            return AgentResult("done", "IDLE", "Nothing to list" if not b or not b.get("listing") else f"{b['title']}: listing written", {})
        cats = "\n".join(f"{i}. {c}" for i, c in enumerate(CATEGORIES))
        scenes = "; ".join(s["title"] for s in active(b))[:900]
        ask = (f"Write the Amazon KDP listing for a children's coloring book.\nTitle: {b['title']}\nSubtitle: {b.get('subtitle', '')}\n"
               f"Ages {b['ages']}. {b['pictures']} single-sided pages (blank backs), 8.5 x 11 in. Pages: {scenes}\n"
               "Rules: honest and warm, for parents; no claims of awards, bestseller, free, or educational outcomes; no brand or character names; "
               "no mention of Amazon or Kindle.\n"
               "Give: description (120-180 words, short paragraphs, a few bullet lines starting with '• '), blurb (one 35-50 word paragraph for the back cover), "
               "7 search keywords or phrases parents would type (each under 50 characters, not repeating the title), and the numbers of the 3 best categories from:\n"
               f"{cats}\n"
               'JSON: {"description": "...", "blurb": "...", "keywords": ["..."], "categories": [0, 1, 2]}')
        out = await ctx["llm"].json(ask, tier="writer", max_tokens=1500, model=o.get("model") or None) or {}
        desc, blurb = str(out.get("description") or "").strip(), str(out.get("blurb") or "").strip()
        notes = []
        for name, txt in (("description", desc), ("blurb", blurb)):
            if BRANDS.search(txt) or HYPE.search(txt):
                notes.append(f"the {name} named a brand or a claim and was replaced by plain wording")
        if notes or not desc:
            desc = (f"{b['pictures']} big, cheerful pages to colour, all about {b['theme'].lower()}.\n\n"
                    f"• One picture per page, with a blank back so markers don't bleed through\n• Bold, clean outlines for ages {b['ages']}\n"
                    "• Large 8.5 x 11 inch pages\n• A \"This book belongs to\" page at the front")
            blurb = f"{b['pictures']} big, fun pages to colour, all about {b['theme'].lower()}. One picture per page with blank backs, bold outlines for ages {b['ages']}."
        kws, seen = [], set()
        for k in out.get("keywords") or []:
            k = re.sub(r"\s+", " ", str(k)).strip()[:50]
            if k and k.lower() not in seen and not BRANDS.search(k) and not HYPE.search(k):
                seen.add(k.lower())
                kws.append(k)
        idx = [i for i in out.get("categories") or [] if isinstance(i, int) and 0 <= i < len(CATEGORIES)]
        cats_ = [CATEGORIES[i] for i in dict.fromkeys(idx)][:3] or CATEGORIES[:1]
        pages = pr.page_count(b["pictures"])
        price, royalty = pr.price(b["pictures"], pages, tuple(o.get("price_band", (6.99, 9.99))))
        b["listing"] = {"title": b["title"], "subtitle": b.get("subtitle", ""), "author": b["author"], "description": desc, "blurb": blurb,
                        "keywords": kws[:7], "categories": cats_, "ages": b["ages"], "price": price, "royalty": royalty, "print_cost": pr.print_cost(pages),
                        "ai": {"images": "Yes: AI-generated (FLUX.2 klein), every page checked", "text": "No AI-generated text inside the book (front pages are templates)"},
                        "notes": notes}
        save(store, b)
        return AgentResult("done", "LISTED", f"{b['title']}: listing ready · ${price} (about ${royalty} a copy)", {"book": b["id"]})


def _file_url(p: str | None) -> str:
    try:
        return "/api/files/" + Path(p).resolve().relative_to((ROOT / "data").resolve()).as_posix() if p else ""
    except ValueError:
        return ""


class ShelfManager(SubAgent):
    name, tier, note = "Shelf Manager", "QUICK", "books → VISION"

    async def run(self, ctx):
        store = ctx["store"]
        b = current(store)
        if b and b["status"] in ("checked", "built", "awaiting") and b.get("listing") and b.get("built_sig") == b.get("cover_sig") == signature(b) \
                and b.get("sig") != signature(b):
            b["sig"] = signature(b)
            b["status"] = "awaiting"
            L = b["listing"]
            request_approval(ctx, self.name, f"Publish \"{b['title']}\" on KDP? ({b['pictures']} pictures, ages {b['ages']}, ${L['price']})", {
                "key": f"ebook:{b['id']}:{b['sig']}", "book": b["id"], "title": b["title"], "subtitle": b.get("subtitle", ""), "theme": b["theme"],
                "ages": b["ages"], "pictures": b["pictures"], "pages": b.get("pages"), "price": L["price"], "royalty": L["royalty"],
                "contact": _file_url(b.get("contact")), "interior": _file_url(b.get("interior")), "cover": _file_url(b.get("cover")),
                "cover_png": _file_url(b.get("cover_png")), "listing": L, "notes": L.get("notes") or []})
            save(store, b)
        books = store.kv_list(NS, 0, 500)
        count = lambda *st: sum(1 for x in books if x.get("status") in st)
        parts = []
        if b:
            ok = sum(1 for s in active(b) if s.get("state") == "ok") if b.get("scenes") else 0
            parts.append(f"{b.get('title') or b['theme']}: " + {"awaiting": "waiting for your yes", "built": "built", "checked": "all pages passed"}.get(
                b["status"], f"{ok} of {b['pictures']} pages ready"))
        if count("ready"):
            parts.append(f"{count('ready')} ready to upload to KDP")
        if count("published"):
            parts.append(f"{count('published')} published")
        return AgentResult("done", "AWAITING YOU" if b and b["status"] == "awaiting" else "REPORTED", " · ".join(parts) or "No books yet",
                           {"books": [{k: x.get(k) for k in ("id", "title", "theme", "ages", "status", "pictures")} for x in books]})


async def approve_book(row: dict, decision: str, ctx: dict) -> str:
    store, p = ctx["store"], row["payload"]
    b = load(store, p["book"])
    if not b:
        return "book not found"
    if p.get("key") != f"ebook:{b['id']}:{b.get('sig')}":
        return "outdated: the book changed after this was asked; the newer version is waiting"
    if decision != "approved":
        b["status"] = "parked"
        save(store, b)
        ctx["rerun"] = True
        return "parked: the next book starts"
    b.update(status="ready", approved=time.time())
    save(store, b)
    ctx["bus"].notice(f"ebook:{b['id']}", f"\"{b['title']}\" is ready for KDP: upload interior.pdf and cover.pdf and paste the listing from the E-books desk. "
                      f"Then run: python -m vision ebooks published {b['id']}", None)
    ctx["rerun"] = True
    return "approved: ready to upload to KDP"


APPROVAL_HANDLERS = {"ebook_publish": approve_book}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Theme Planner": ThemePlanner(), "Page Writer": PageWriter(), "Illustrator": Illustrator(), "Page Inspector": PageInspector(),
            "Book Builder": BookBuilder(), "Cover Designer": CoverDesigner(), "Listing Writer": ListingWriter(), "Shelf Manager": ShelfManager()}


# ---------- command line: python -m vision ebooks ... ----------
def cli(args: list[str]) -> str:
    from ..bus import Store
    store = Store(ROOT / "data" / "vision.db")
    cmd = args[0] if args else "list"
    if cmd == "list":
        rows = sorted(store.kv_list(NS, 0, 500), key=lambda b: b.get("made") or 0)
        return "\n".join(f"{b['id']:40} {b.get('status', ''):10} {b.get('title') or b['theme']}" for b in rows) or "no books yet"
    b = load(store, args[1]) if len(args) > 1 else None
    if cmd in ("published", "redraw") and not b:
        return "usage: ebooks published <book> | ebooks redraw <book> <page> | ebooks theme \"Theme\" <ages> | ebooks list"
    if cmd == "published":
        b.update(status="published", published=time.time(), asin=args[2] if len(args) > 2 else b.get("asin"))
        save(store, b)
        return f"{b['title']}: marked published"
    if cmd == "redraw":
        n = int(args[2])
        s = active(b)[n - 1]
        s.update(state="todo", rounds=s.get("rounds", 0) + 1, pick=None, hash=None)
        b["status"] = "drawing"
        save(store, b)
        return f"{b['title']}: page {n} will be drawn again on the next run"
    if cmd == "theme" and len(args) > 1:
        return "add it to masters.ebooks.options.queue in config.yaml as \"" + args[1] + " | " + (args[2] if len(args) > 2 else "4-8") + "\""
    return "usage: ebooks list | published <book> [ASIN] | redraw <book> <page>"
