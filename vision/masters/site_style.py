"""Which style a demo site gets, and why.

Every style that suits the kind of business is scored against what is actually known about this business: the words
customers use in reviews, the Google summary, cues in its name. The best match wins; the model's suggestion is one
signal among the others; a style already used by another demo in play is passed over. The reason is kept with the
lead so the choice can be read later.
"""

from __future__ import annotations

import re

from .sitekit import CLASSIC, RECIPES, recipes_for, styles_for

# what each style feels like (0..1 per trait). "dark" marks the four dark styles.
TRAITS = {
    "foreman":    {"bold": 1.0, "practical": 0.8, "modern": 0.4},
    "forge":      {"bold": 1.0, "dark": 1.0, "practical": 0.5},
    "clinic":     {"calm": 0.8, "modern": 0.9, "formal": 0.8},
    "artisan":    {"warm": 1.0, "traditional": 0.5, "playful": 0.2},
    "gazette":    {"refined": 0.7, "traditional": 0.8, "formal": 0.4},
    "atelier":    {"refined": 1.0, "calm": 0.6},
    "sprout":     {"playful": 1.0, "warm": 0.6},
    "noir":       {"refined": 1.0, "dark": 1.0, "bold": 0.3},
    "mainstreet": {"traditional": 0.9, "warm": 0.5, "practical": 0.5},
    "swiss":      {"modern": 1.0, "formal": 0.7, "calm": 0.4},
    "bloom":      {"calm": 1.0, "warm": 0.5, "refined": 0.4},
    "chalkboard": {"warm": 0.7, "dark": 1.0, "traditional": 0.4},
    "harbour":    {"calm": 1.0, "modern": 0.3},
    "parlour":    {"traditional": 1.0, "dark": 1.0, "refined": 0.5},
    CLASSIC:      {"practical": 1.0, "modern": 0.3},
}

# words that reveal a trait, in reviews and the Google summary (matched as whole words, plurals included)
WORDS = {
    "warm": ["cozy", "cosy", "friendly", "welcoming", "homemade", "home made", "family", "kind", "warm", "comfort", "comfortable", "neighbourhood",
             "neighborhood", "homey", "local favourite", "local favorite", "like family"],
    "refined": ["luxury", "luxurious", "elegant", "upscale", "beautiful", "stunning", "pamper", "pampered", "boutique", "premium", "classy", "high end",
                "high-end", "gorgeous", "exquisite", "chic", "sophisticated"],
    "bold": ["fast", "quick", "quickly", "same day", "emergency", "right away", "strong", "tough", "heavy duty", "big job", "no nonsense"],
    "practical": ["reliable", "on time", "honest", "fair price", "fair", "affordable", "reasonable", "fixed", "got the job done", "hard working",
                  "hard-working", "straightforward", "dependable", "showed up"],
    "playful": ["fun", "kids", "children", "colourful", "colorful", "playful", "cute", "treats", "sweet", "birthday", "party"],
    "calm": ["calm", "relaxing", "relaxed", "peaceful", "quiet", "gentle", "soothing", "clean", "spotless", "serene"],
    "modern": ["modern", "new", "sleek", "stylish", "trendy", "contemporary", "state of the art", "up to date"],
    "traditional": ["classic", "traditional", "old fashioned", "old-fashioned", "authentic", "generations", "heritage", "vintage", "old school",
                    "old-school", "timeless", "for years", "for decades"],
    "formal": ["professional", "knowledgeable", "thorough", "expert", "detailed", "experienced", "explained everything", "courteous"],
    "dark": ["evening", "night", "late night", "bar", "lounge", "cocktail", "moody", "barber", "tattoo", "industrial", "garage", "speakeasy", "candlelit"],
}
# cues in the business name
NAME_CUES = [(r"\b(studio|boutique|atelier|lounge|salon|spa)\b", "refined"), (r"\b(kids?|little|tiny|tots?|play)\b", "playful"),
             (r"(&|\band\b)\s*(sons?|daughters?|bros?|brothers)\b|\bfamily\b", "traditional"), (r"\b(pro|express|24|rapid|quick|speedy)\b", "bold"),
             (r"\b(kitchen|bakery|bake|cafe|café|coffee|deli|diner)\b", "warm"), (r"\b(clinic|dental|law|legal|accounting|medical|wellness)\b", "formal"),
             (r"\b(barber\w*|tattoo\w*|garage|ink)\b", "dark"), (r"\b(heritage|classic|vintage|old)\b", "traditional")]
SAYS = {"warm": "warm and friendly", "refined": "refined", "bold": "fast and direct", "practical": "plain and practical", "playful": "playful",
        "calm": "calm", "modern": "modern", "traditional": "traditional", "formal": "professional", "dark": "an evening or workshop feel"}
# palette moods (ColorHunt tags) that go with a style, so the colours follow the look
MOODS = {"foreman": ["cold", "sky"], "forge": ["dark", "cold"], "clinic": ["cold", "light", "sky"], "artisan": ["warm", "earth", "coffee", "cream"],
         "gazette": ["vintage", "cream", "fall"], "atelier": ["pastel", "cream", "skin"], "sprout": ["happy", "summer", "kids", "pastel"],
         "noir": ["dark", "gold", "night"], "mainstreet": ["warm", "retro", "earth"], "swiss": ["cold", "light"], "bloom": ["pastel", "nature", "spring", "skin"],
         "chalkboard": ["dark", "coffee", "food"], "harbour": ["sea", "sky", "light"], "parlour": ["vintage", "retro", "gold"], CLASSIC: []}


def signals(lead: dict) -> dict:
    """{trait: (strength 0..1, [the words or name cue that showed it])} from the business's own reviews, summary and name."""
    info = lead.get("info") or {}
    text = " ".join([str(info.get("summary") or "")] + [str(r.get("text") if isinstance(r, dict) else r) for r in (info.get("reviews") or [])[:6]]).lower()
    out = {}
    for trait, words in WORDS.items():
        hits = [w for w in words if re.search(r"(?<![a-z])" + re.escape(w) + r"(s|es)?(?![a-z])", text)]
        if hits:
            out[trait] = (min(1.0, len(hits) / 2), hits[:3])
    name = str(lead.get("name") or "").lower()
    for rx, trait in NAME_CUES:
        if re.search(rx, name):
            s, why = out.get(trait, (0.0, []))
            out[trait] = (min(1.0, s + 0.6), why + ["its name"])
    return out


def rank(lead: dict, model_pick: str | None = None, used=()) -> list[dict]:
    """Suitable styles, best first: [{style, score, why}]. A style already in use by another demo ranks after the free ones."""
    fits, sig = recipes_for(lead.get("type")), signals(lead)
    known = min(1.0, sum(v[0] for v in sig.values()))     # how much is actually known about this business's character
    rows = []
    for name in styles_for(lead.get("type")):
        base = max(1.0, 2.4 - 0.3 * fits.index(name)) if name in fits else 1.3        # how well it suits the kind of business
        match = {t: sig[t][0] * w for t, w in TRAITS[name].items() if t in sig}
        # what the style says that the business shows no sign of (a handmade look for a sleek shop, a dark page with no
        # reason for one); only counted once something is known about the business
        miss = sum(w for t, w in TRAITS[name].items() if t not in sig) * known
        score = base + 2.0 * sum(match.values()) - 0.9 * miss + (1.2 if name == model_pick else 0.0)
        why = []
        for t in sorted(match, key=match.get, reverse=True)[:2]:
            words = [w for w in sig[t][1] if w != "its name"]
            why.append(f"{SAYS[t]} ({'reviews mention ' + ', '.join(words) if words else 'from its name'})")
        if name == model_pick:
            why.append("the model suggested it")
        if not why:
            why.append("the usual fit for this kind of business" if name in fits[:1] else "a good fit for this kind of business")
        rows.append({"style": name, "score": round(score, 2), "why": "; ".join(why), "used": name in set(used)})
    return sorted(rows, key=lambda r: (r["used"], -r["score"], r["style"]))


def choose(lead: dict, model_pick: str | None = None, used=()) -> dict:
    """{style, why, ranked}: the best-scoring style not already used by another demo in play."""
    rows = rank(lead, model_pick, used)
    best, top = rows[0], max(rows, key=lambda r: r["score"])
    why = f"{best['style']}: {best['why']}"
    if top["style"] != best["style"]:
        why += f" ({top['style']} matched best but is already used by another demo)"
    return {"style": best["style"], "why": why, "ranked": [r["style"] for r in rows]}


def palette_moods(style: str, model_moods=None) -> list[str]:
    """Palette tags to look for: the style's own, then up to two the model asked for."""
    return list(dict.fromkeys(MOODS.get(style, []) + list(model_moods or [])[:2]))


assert set(TRAITS) == set(RECIPES) | {CLASSIC} == set(MOODS), "every style needs traits and palette moods"
