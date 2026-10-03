"""Relevant stock photos for a local business's demo site.

`pick_images` searches Pexels, Pixabay and Openverse with trade-specific phrases, keeps the descriptive text of every
candidate and only uses photos whose text matches the trade (and none of its reject terms). Credits keep the exact
format used by web.search_images.
"""
from __future__ import annotations

import asyncio
import re

import httpx

from ..config import secret

MIN_SCORE = 2.0          # below this a candidate is not used (fewer photos beat weak photos)
PER_QUERY = 15
MAX_QUERIES = 7

# trade -> (search phrases separated by |, RELEVANT terms, REJECT terms)
_T = {
    "plumber": ("plumber fixing pipe|plumber installing faucet|copper pipes plumbing|bathroom sink repair|plumbing tools wrench",
                "plumber plumbing pipe faucet tap sink wrench drain toilet water heater leak", "restaurant fashion laptop"),
    "electrician": ("electrician working|electrician wiring panel|electrical wires installation|electrician tools|light fixture installation",
                    "electrician electrical wire wiring circuit breaker outlet panel voltage cable socket switch", "restaurant fashion kitchen"),
    "roofing_contractor": ("roofer installing shingles|roof repair worker|new shingle roof house|roofing tools|roofers on a roof",
                           "roof roofer roofing shingle gutter ladder rooftop tile chimney eave", "interior kitchen bathroom sofa floor"),
    "painter": ("house painter painting wall|painter roller wall|paint brushes colors|interior painting room|paint cans",
                "paint painter painting roller brush wall color ladder drywall", "canvas easel artist portrait gallery"),
    "locksmith": ("locksmith opening door|door lock key|locksmith tools|house key lock|lock installation",
                  "locksmith lock key padlock deadbolt door keyhole latch", "bike bicycle"),
    "moving_company": ("movers carrying boxes|moving truck|moving day boxes house|movers loading van|furniture moving",
                       "mover movers moving truck van box furniture carrying relocation", "gas office"),
    "plumbing": ("plumber working|pipes|faucet|bathroom repair", "plumber plumbing pipe faucet tap sink wrench drain", ""),
    "beauty_salon": ("beauty salon interior|facial treatment|manicure|makeup brushes|salon styling",
                     "salon beauty facial makeup manicure skincare cosmetic nail brush treatment", "surgery hospital"),
    "hair_care": ("hair stylist cutting hair|hair salon interior|salon chairs|haircut|hairdresser",
                  "hair haircut stylist hairdresser salon barber scissors comb blow", "surgery hospital"),
    "hair_salon": ("hair salon interior|hairdresser cutting hair|hair coloring|blow dry stylist|salon chairs",
                   "hair haircut stylist hairdresser salon scissors comb color coloring blow", "surgery hospital"),
    "barber_shop": ("barber shop interior|barber cutting hair|barber chair|beard trim|straight razor shave",
                    "barber barbershop beard razor haircut shave clipper chair trim", "surgery hospital"),
    "nail_salon": ("nail salon manicure|nail polish colors|nail technician|manicure hands|pedicure spa",
                   "nail manicure pedicure polish salon technician gel", "surgery hospital"),
    "spa": ("spa treatment|massage therapy|spa interior|candles and towels|relaxing spa",
            "spa massage towel candle wellness relax treatment stone aromatherapy facial", "surgery hospital"),
    "restaurant": ("restaurant interior|plated food|chef cooking kitchen|dinner table|restaurant dining room",
                   "restaurant dining food dish chef plate meal table dinner cuisine kitchen waiter", "fast gas station"),
    "cafe": ("coffee shop interior|latte art|barista making coffee|pastry and coffee|cafe table",
             "cafe coffee latte espresso barista cup pastry cappuccino croissant", "gas station"),
    "bakery": ("bakery display|fresh bread|baker with dough|pastries|croissants bakery",
               "bakery bread baker pastry croissant dough bun cake loaf baking oven", "gas station"),
    "meal_takeaway": ("takeout food|food container takeaway|burger takeout|noodles takeout box|street food",
                      "takeout takeaway food burger noodle box meal pizza sandwich delivery", "gas station"),
    "car_repair": ("auto mechanic working|car workshop|engine repair|tire service|mechanic with tools",
                   "mechanic car auto engine garage repair tire wheel workshop vehicle brake", "dealership showroom"),
    "car_wash": ("car wash foam|washing a car|car detailing|car wash tunnel|car polishing",
                 "car wash washing foam detailing polish vehicle auto soap", "gas station"),
    "dentist": ("dental clinic|dentist with patient|dental chair|dental tools|teeth cleaning",
                "dentist dental tooth teeth clinic orthodontic smile dentistry", "pharmacy"),
    "physiotherapist": ("physiotherapy session|physical therapist treating patient|rehabilitation exercise|back massage therapy|physio clinic",
                        "physiotherapy physiotherapist physical therapy therapist rehabilitation exercise massage clinic stretching", "surgery"),
    "gym": ("gym interior|weight training|dumbbells gym|fitness equipment|personal trainer",
            "gym fitness weight dumbbell barbell workout trainer exercise treadmill training", "hospital"),
    "veterinary_care": ("veterinarian examining dog|vet clinic|cat at vet|veterinary care|pet checkup",
                        "veterinarian vet veterinary dog cat pet animal clinic checkup", "hunting"),
    "pet_store": ("pet shop|dog toys|pet supplies|puppy|pet food aisle",
                  "pet dog cat puppy kitten supplies leash toy store shop", "hunting"),
    "florist": ("florist arranging flowers|flower shop|bouquet|flowers arrangement|flower bucket",
                "florist flower bouquet floral bloom rose tulip arrangement shop", "funeral coffin"),
    "laundry": ("laundromat washing machines|folded laundry|dry cleaning clothes|laundry service|clothes on hangers",
                "laundry laundromat washing machine dryer clothes folded cleaning iron hanger", "hospital"),
    "clothing_store": ("clothing boutique|clothes on rack|fashion store interior|clothing shop|boutique dresses",
                       "clothing clothes boutique fashion rack dress shirt store shop apparel hanger", "factory"),
    "jewelry_store": ("jewelry display|gold rings|jewelry shop|diamond necklace|jeweler",
                      "jewelry jewellery ring necklace gold diamond jeweler bracelet earring gem", "pawn"),
    "furniture_store": ("furniture showroom|sofa living room|furniture store|wooden table chairs|modern furniture",
                        "furniture sofa couch chair table showroom store wooden shelf cabinet", "warehouse"),
    "hardware_store": ("hardware store tools|power tools|screws and nails|paint aisle hardware|tool shelf",
                       "hardware tool tools drill hammer screw nail wrench store shelf paint", "gas station"),
    "bicycle_store": ("bicycle shop|bike repair|bicycles in store|bike mechanic|bicycle wheel",
                      "bicycle bike cycling shop repair wheel mechanic store helmet", "motorcycle"),
    "book_store": ("bookstore shelves|books on shelf|bookshop interior|reading books|stack of books",
                   "book books bookstore bookshop shelf library reading novel", "laptop"),
    "gift_shop": ("gift shop display|wrapped gifts|gift boxes ribbon|souvenir shop|handmade gifts",
                  "gift gifts present shop store souvenir ribbon wrapped box handmade", "gas station"),
    "child_care_agency": ("children playing daycare|child care classroom|kids painting|preschool toys|toddlers playing",
                          "child children kid kids daycare preschool toddler playing classroom toy nursery", "adult party"),
    "tailor": ("tailor sewing|tailor measuring suit|sewing machine|fabric and thread|alterations tailor shop",
               "tailor sewing seamstress fabric thread needle suit measuring alteration machine garment", "factory"),
    "real_estate_agency": ("house exterior|real estate for sale sign|modern home|house keys|living room home",
                           "house home real estate property apartment keys exterior residential building", "skyscraper"),
    "insurance_agency": ("family home protection|car insurance|insurance consultation|house and umbrella|family safety",
                         "insurance family home protection car policy umbrella agent safety", "accident wreck"),
    "accounting": ("accountant calculator|bookkeeping desk|tax documents|accounting paperwork|calculator and spreadsheet",
                   "accountant accounting calculator tax bookkeeping finance spreadsheet document budget paperwork", "bitcoin crypto"),
    "lawyer": ("law office|lawyer desk|legal books|gavel|legal documents",
               "lawyer attorney law legal gavel court justice document contract books", "bitcoin crypto"),
    "travel_agency": ("travel planning map|suitcase and passport|tropical beach vacation|airplane window|travel agent",
                      "travel vacation passport suitcase map beach airplane tourism trip holiday destination", "refugee"),
    "bed_and_breakfast": ("bed and breakfast room|cozy bedroom|breakfast table|guest house|inn exterior",
                          "bed breakfast bedroom inn guesthouse room cozy hotel pillow guest", "hospital"),
    "funeral_home": ("white lilies|candle memorial|peaceful chapel|flowers condolence|quiet sunset",
                     "lily candle flower memorial chapel peaceful sympathy calm cemetery", "party smile"),
    "storage": ("self storage units|storage facility doors|moving boxes storage|warehouse shelves|garage storage",
                "storage unit warehouse box boxes shelf garage facility locker", "gas station"),
    "general_contractor": ("contractor on construction site|home renovation|builder with tools|carpenter working|house framing",
                           "contractor construction renovation builder carpenter hammer framing tool site", "skyscraper"),
    "hvac_contractor": ("hvac technician|air conditioner installation|furnace repair|heat pump|duct work",
                        "hvac air conditioner furnace heating cooling technician duct thermostat", "gas station"),
    "landscaper": ("landscaper mowing lawn|garden design|lawn care|garden plants|hedge trimming",
                   "landscaping landscaper lawn garden mower hedge plant yard grass", "golf"),
}
TRADE = {k: {"queries": v[0].split("|"), "relevant": set(v[1].split()), "reject": set(v[2].split())} for k, v in _T.items()}

PEOPLE_TRADES = {"beauty_salon", "hair_care", "hair_salon", "barber_shop", "nail_salon", "spa", "dentist", "child_care_agency", "physiotherapist"}
STOP = {"a", "an", "and", "at", "of", "the", "in", "on", "with", "for", "to", "small", "business", "owner", "work", "working"}
BLOCK_TOKENS = {"watermark", "watermarked", "logo", "illustration", "vector", "render", "rendering", "3d", "ai", "generated", "clipart", "cartoon",
                "icon", "mockup", "handshake", "sketch", "drawing", "infographic", "shutterstock", "istock", "alamy", "copyspace"}
BLOCK_PHRASES = ["gas station", "petrol station", "packing box", "packing boxes", "office meeting", "business meeting", "stock photo", "text overlay",
                 "ai generated", "3d render", "digital art", "shaking hand", "hand shake", "business team", "team meeting", "call center"]
FACE_TOKENS = {"portrait", "smiling", "headshot", "selfie", "closeup", "face", "posing", "pose"}
PEOPLE_TOKENS = {"worker", "working", "man", "men", "woman", "women", "team", "crew", "installing", "repairing", "staff", "owner", "technician",
                 "mechanic", "roofer", "chef", "person", "people", "interior", "inside", "indoor", "customer", "professional"}


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", (text or "").lower())]


def _label_terms(type_: str, query: str) -> set[str]:
    return {t for t in _tokens(query.replace("_", " ") + " " + type_.replace("_", " ")) if t not in STOP and len(t) > 2}


def score_text(text: str, type_: str, query: str) -> float | None:
    """Relevance of a photo's description for a trade; None means rejected (junk, or nothing relevant in it)."""
    toks = _tokens(text)
    if not toks:
        return None
    joined = " " + " ".join(toks) + " "
    if any(t in BLOCK_TOKENS for t in toks) or any(" " + " ".join(_tokens(p)) + " " in joined for p in BLOCK_PHRASES):
        return None
    trade = TRADE.get(type_)
    reject = {_stem(w) for w in trade["reject"]} if trade else set()
    if reject & set(toks):
        return None
    qwords = {t for t in _tokens(query) if t not in STOP and len(t) > 2}
    relevant = {_stem(w) for w in trade["relevant"]} if trade else _label_terms(type_, query)
    seen = set(toks)
    rel = len(relevant & seen)
    if not rel:
        return None
    score = 2.0 * min(rel, 3) + 0.5 * min(len(qwords & seen), 3)
    if type_ not in PEOPLE_TRADES and FACE_TOKENS & seen:
        score -= 1.5
    return score


def _queries(lead: dict, brief: dict | None) -> list[str]:
    t, label = lead.get("type") or "", (lead.get("type_label") or (lead.get("type") or "").replace("_", " ")).lower().strip()
    base = list(TRADE[t]["queries"]) if t in TRADE else [label, f"{label} at work", f"{label} interior", f"{label} tools", f"{label} shop"]
    out, seen = [], set()
    for q in base + [k for k in (brief or {}).get("keywords", []) if isinstance(k, str)]:
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:MAX_QUERIES]


def _slug_text(url: str) -> str:
    m = re.search(r"/(?:photo|photos)/([a-z0-9-]+?)(?:-\d+)?/?$", url or "")
    return m.group(1).replace("-", " ") if m else ""


async def _get(c, url, **kw):
    try:
        r = await c.get(url, **kw)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


async def _pexels(c, q):
    key = secret("PEXELS_API_KEY")
    if not key:
        return []
    d = await _get(c, "https://api.pexels.com/v1/search", headers={"Authorization": key}, params={"query": q, "per_page": PER_QUERY, "orientation": "landscape"})
    out = []
    for p in d.get("photos", []) if isinstance(d, dict) else []:
        try:
            src = p.get("src") or {}
            out.append({"url": src.get("large2x") or src["original"], "credit": f"Photo by {p.get('photographer') or 'unknown'} (Pexels)", "source": "Pexels", "page": p.get("url") or "",
                        "text": (p.get("alt") or "") or _slug_text(p.get("url", "")), "creator": p.get("photographer") or "", "w": p.get("width") or 0, "h": p.get("height") or 0})
        except Exception:
            continue
    return out


async def _pixabay(c, q):
    key = secret("PIXABAY_API_KEY")
    if not key:
        return []
    d = await _get(c, "https://pixabay.com/api/", params={"key": key, "q": q, "image_type": "photo", "orientation": "horizontal", "min_width": 1200,
                                                         "safesearch": "true", "per_page": PER_QUERY})
    out = []
    for p in d.get("hits", []) if isinstance(d, dict) else []:
        try:
            out.append({"url": p["largeImageURL"], "credit": f"Photo by {p.get('user') or 'unknown'} (Pixabay)", "source": "Pixabay", "page": p.get("pageURL") or "",
                        "text": p.get("tags") or "", "creator": p.get("user") or "", "w": p.get("imageWidth") or 0, "h": p.get("imageHeight") or 0})
        except Exception:
            continue
    return out


async def _openverse(c, q):
    d = await _get(c, "https://api.openverse.org/v1/images/", params={"q": q, "license_type": "commercial,modification", "page_size": PER_QUERY,
                                                                      "aspect_ratio": "wide", "size": "large"})
    out = []
    for i in d.get("results", []) if isinstance(d, dict) else []:
        try:
            tags = " ".join(str(t.get("name", "")) for t in i.get("tags") or [] if isinstance(t, dict))
            out.append({"url": i["url"], "credit": f"{i.get('title') or 'Photo'} by {i.get('creator') or 'unknown'} ({(i.get('license') or '').upper()} {i.get('license_version') or ''})",
                        "source": "Openverse", "page": i.get("foreign_landing_url") or i.get("url") or "", "text": f"{i.get('title') or ''} {tags}", "creator": i.get("creator") or "", "w": i.get("width") or 0, "h": i.get("height") or 0})
        except Exception:
            continue
    return out


def _alt(text: str, creator: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").replace("_", " ").replace("-", " ")).strip(" ,.")
    if creator:
        s = re.sub(re.escape(creator), "", s, flags=re.I)
    s = re.sub(r"(?i)\b(photo|picture|image)s? by\b.*$", "", s)
    s = re.sub(r"(?i)\b(pexels|pixabay|openverse|unsplash|shutterstock|istock|getty|alamy)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    if len(s) > 110:
        s = s[:110].rsplit(" ", 1)[0]
    return s[:1].upper() + s[1:]


def _score(cand: dict, type_: str, query: str) -> float | None:
    s = score_text(cand["text"], type_, query)
    if s is None:
        return None
    w, h = cand["w"], cand["h"]
    if w:
        s += 1.0 if w >= 1200 else -1.0
        if h and w / h >= 1.3:
            s += 0.5
        elif h and w < h:
            s -= 1.0
    return s


def _similar(a: set, b: set) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.8


async def pick_images(c: httpx.AsyncClient, lead: dict, brief: dict | None, want: int = 6, min_score: float = MIN_SCORE) -> list[dict]:
    """Up to `want` relevant photos, best first (hero, about, then gallery). Fewer rather than weak ones."""
    type_ = lead.get("type") or ""
    queries = _queries(lead, brief)
    scored: dict[str, dict] = {}
    for fetch in (_pexels, _pixabay, _openverse):
        try:
            batches = await asyncio.gather(*[fetch(c, q) for q in queries], return_exceptions=True)
        except Exception:
            continue
        for q, res in zip(queries, batches):
            if isinstance(res, Exception):
                continue
            for cand in res:
                s = _score(cand, type_, q)
                if s is None or s < min_score:
                    continue
                old = scored.get(cand["url"])
                if old is None or s > old["score"]:
                    scored[cand["url"]] = {**cand, "score": s, "query": q}
        if sum(1 for v in scored.values()) >= want:
            break
    ranked = sorted(scored.values(), key=lambda x: (-x["score"], x["url"]))
    picked: list[dict] = []
    for pool in (True, False):                      # first pass enforces variety among the first 4
        for cand in ranked:
            if len(picked) >= want:
                break
            if cand in picked:
                continue
            toks = set(_tokens(cand["text"]))
            if any(cand["creator"] and cand["creator"] == p["creator"] and _similar(toks, set(_tokens(p["text"]))) for p in picked):
                continue
            if pool and len(picked) < 4 and sum(1 for p in picked if p["query"] == cand["query"]) >= 2:
                continue
            picked.append(cand)
    if not picked:
        return []

    def tok(x):
        return set(_tokens(x["text"]))

    def establishing(x):
        w, h = x["w"], x["h"]
        return 0.4 * x["score"] + (1.0 if h and w / h >= 1.5 else 0) + (0.5 if w >= 1600 else 0) - (1.0 if FACE_TOKENS & tok(x) else 0) - (1.0 if PEOPLE_TOKENS & tok(x) else 0)

    hero = max(picked, key=lambda x: (establishing(x), x["url"]))
    rest = [x for x in picked if x is not hero]
    about = next((x for x in rest if PEOPLE_TOKENS & tok(x)), rest[0] if rest else None)
    order = [hero] + ([about] if about else []) + [x for x in rest if x is not about]
    roles = ["hero", "about"] + ["gallery"] * len(order)
    # "source" is the photo's own page (the credit links to it, as before); "provider" names the stock library
    return [{"url": x["url"], "credit": x["credit"], "source": x.get("page", ""), "provider": x["source"], "alt": _alt(x["text"], x["creator"]), "role": roles[n],
             "score": round(x["score"], 2), "query": x["query"]} for n, x in enumerate(order)]
