"""Copywriting layer for the Web Designer's demo sites.

The model only writes JSON; everything here makes sure that JSON is usable and strictly factual:
`write_copy` -> prompt -> llm.json -> `clean_copy` (validated, merged over `fallback_copy`). Nothing in here raises
or calls the network except through the `llm` object passed in.
"""
from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------- categories

CATEGORY_TYPES = {
    "trade": ["plumber", "electrician", "roofing_contractor", "painter", "locksmith", "moving_company", "car_repair", "car_wash", "laundry",
              "general_contractor", "hvac_contractor", "landscaper", "cleaning_service", "auto_repair"],
    "food": ["restaurant", "cafe", "bakery", "meal_takeaway", "pizza_restaurant", "bar", "coffee_shop", "ice_cream_shop", "meal_delivery"],
    "beauty": ["beauty_salon", "hair_care", "hair_salon", "barber_shop", "nail_salon", "spa", "tattoo_shop"],
    "health": ["dentist", "physiotherapist", "gym", "doctor", "chiropractor", "optometrist", "massage"],
    "retail": ["florist", "pet_store", "clothing_store", "jewelry_store", "furniture_store", "hardware_store", "bicycle_store", "book_store",
               "gift_shop", "tailor", "store", "shoe_store", "grocery_store"],
    "care": ["child_care_agency", "veterinary_care", "funeral_home", "preschool", "pet_care"],
    "stay": ["bed_and_breakfast", "lodging", "hotel", "guest_house", "motel", "campground"],
    "other": ["real_estate_agency", "insurance_agency", "accounting", "lawyer", "travel_agency", "storage"],
}
_CAT = {t: c for c, ts in CATEGORY_TYPES.items() for t in ts}
_KEYWORD_CAT = [("food", r"restaurant|cafe|coffee|bakery|pizza|diner|grill|kitchen|eatery|takeaway|takeout|food|bar$"),
                ("beauty", r"salon|barber|hair|nail|spa$|beauty|lash|brow"), ("health", r"dent|physio|clinic|gym|fitness|chiro|health|therap"),
                ("trade", r"plumb|electric|roof|paint|lock|moving|repair|contractor|mechanic|hvac|clean|garage|wash"),
                ("care", r"child|daycare|vet|funeral|care"), ("stay", r"lodg|hotel|b_and_b|bed_and|inn$|motel"),
                ("retail", r"store|shop|florist|boutique|market")]


def category_of(type_: str) -> str:
    t = (type_ or "").strip().lower().replace(" ", "_")
    if t in _CAT:
        return _CAT[t]
    for cat, rx in _KEYWORD_CAT:
        if re.search(rx, t):
            return cat
    return "other"


# per-category wording: section titles, tone and generic fallback pieces
CAT = {
    "trade": dict(services_title="What we do", gallery_title="Recent work", reviews_title="What customers say", visit_title="Get in touch",
                  tone="straightforward and reassuring, about getting the job done",
                  tagline="Tell us what needs doing and we will get back to you.",
                  fillers=["Call or send a message to talk through the job.", "Tell us what is wrong or what you want done, and we will take it from there.",
                           "Reach out by phone to get started."],
                  highlights=["Call to talk it through", "Clear, friendly communication", "Work done to your brief"],
                  cta_title="Need a hand?", cta_text="Call or message to talk about your job."),
    "food": dict(services_title="What we serve", gallery_title="From our kitchen", reviews_title="What guests say", visit_title="Come and eat",
                 tone="warm, appetising and relaxed; general words about food, no dish names unless given",
                 tagline="Come by, take a seat and see what is on today.",
                 fillers=["Pop in to see what is on today.", "Call ahead if you have a question before you visit.", "Come hungry and settle in."],
                 highlights=["Food and drinks", "Come in and sit down", "Ask us about takeaway"],
                 cta_title="Hungry?", cta_text="Call ahead or just come in and see what is on today."),
    "beauty": dict(services_title="Services", gallery_title="The space", reviews_title="What clients say", visit_title="Come and visit",
                   tone="calm, polished and welcoming",
                   tagline="Drop in or get in touch to plan your visit.",
                   fillers=["Get in touch to ask about a service or plan your visit.", "Call or message and we will help you choose.",
                            "Come by and see the space for yourself."],
                   highlights=["Relaxed, welcoming space", "Get in touch to plan a visit", "Ask about any service"],
                   cta_title="Treat yourself", cta_text="Call or message to ask about a visit."),
    "health": dict(services_title="Care we offer", gallery_title="Inside the practice", reviews_title="What patients say", visit_title="Visit us",
                   tone="calm, professional and reassuring",
                   tagline="Get in touch to talk about how we can help.",
                   fillers=["Call to ask a question or arrange a visit.", "Get in touch and the team will point you in the right direction.",
                            "Reach out by phone to get started."],
                   highlights=["Call to arrange a visit", "Friendly, clear communication", "Ask us any question"],
                   cta_title="Talk to us", cta_text="Call to ask a question or arrange a visit."),
    "retail": dict(services_title="What we sell", gallery_title="Inside the shop", reviews_title="What customers say", visit_title="Visit the shop",
                   tone="friendly and inviting, about browsing and finding the right thing",
                   tagline="Come in, have a look around, or give us a call.",
                   fillers=["Call ahead if you are looking for something in particular.", "Drop in and have a browse.",
                            "Ask us if you cannot find what you need."],
                   highlights=["Come in and browse", "Call ahead with questions", "Friendly help in store"],
                   cta_title="Come and browse", cta_text="Drop in, or call to ask about something in particular."),
    "care": dict(services_title="How we help", gallery_title="Our space", reviews_title="What families say", visit_title="Get in touch",
                 tone="gentle, caring and clear",
                 tagline="Get in touch and we will be glad to talk.",
                 fillers=["Call to ask a question or find out more.", "Get in touch and we will talk it through with you.", "Reach out by phone to begin."],
                 highlights=["Call to find out more", "Gentle, clear communication", "Ask us any question"],
                 cta_title="Talk to us", cta_text="Call to ask a question or find out more."),
    "stay": dict(services_title="Your stay", gallery_title="Around the property", reviews_title="What guests say", visit_title="Find us",
                 tone="warm, calm and welcoming",
                 tagline="Get in touch to ask about staying with us.",
                 fillers=["Call or message to ask about a stay.", "Get in touch with any question before you travel.", "We are happy to talk it through."],
                 highlights=["Call to ask about a stay", "Easy to find and contact", "Questions welcome"],
                 cta_title="Plan your stay", cta_text="Call or message to ask about a stay."),
    "other": dict(services_title="What we do", gallery_title="Gallery", reviews_title="What clients say", visit_title="Get in touch",
                  tone="clear, professional and approachable",
                  tagline="Get in touch to talk about what you need.",
                  fillers=["Call or send a message to start the conversation.", "Tell us what you need and we will take it from there.",
                           "Reach out by phone to find out more."],
                  highlights=["Call to start a conversation", "Clear, friendly communication", "Questions welcome"],
                  cta_title="Let's talk", cta_text="Call or message to talk about what you need."),
}

STEPS = {
    "trade": [("Call or message", "Call or message and tell us about the job."), ("We take a look", "We visit or talk it through to understand what is needed."),
              ("We do the work", "The work is carried out as agreed."), ("Follow-up", "We check in afterwards to make sure you are happy.")],
    "food": [("Find us", "Look us up and see when we are open."), ("Come in", "Pop in and take a look at what is on."), ("Enjoy", "Sit down, or take something with you.")],
    "beauty": [("Call or message", "Call or message about the service you want."), ("Come in", "Visit us and tell us what you have in mind."),
               ("Enjoy", "Relax while we take care of it."), ("Follow-up", "Let us know how it went.")],
    "health": [("Call or message", "Call to ask a question or arrange a visit."), ("Visit", "Come in and talk about what you need."),
               ("Plan", "We go through the next steps with you."), ("Follow-up", "We check in afterwards.")],
    "retail": [("Find us", "Look us up and check our opening hours."), ("Browse", "Come in and have a look around."), ("Ask", "Ask us if you need help finding something.")],
    "care": [("Call or message", "Call to ask a question."), ("Visit", "Come and see the space and meet us."), ("Plan", "We talk through what you need.")],
    "stay": [("Call or message", "Call or message with your questions."), ("Plan", "We talk through what you need."), ("Arrive", "Come and see us.")],
    "other": [("Call or message", "Call or message to start."), ("We talk it through", "We listen to what you need."), ("Next steps", "We agree how to go ahead."),
              ("Follow-up", "We check in afterwards.")],
}

_G = lambda *pairs: [dict(name=n, text=t) for n, t in pairs]  # noqa: E731
TYPE_SERVICES = {
    "plumber": _G(("Leak repair", "Fixing dripping taps and leaking pipes."), ("Drain clearing", "Clearing blocked sinks, toilets and drains."),
                  ("Fixture installation", "Fitting taps, toilets and sinks."), ("Water heaters", "Help with water heater problems."),
                  ("Bathroom plumbing", "Plumbing for bathroom updates.")),
    "electrician": _G(("Electrical repair", "Tracing and fixing electrical faults."), ("Lighting", "Installing and replacing lights."),
                      ("Outlets and switches", "Fitting new outlets and switches."), ("Panel work", "Help with electrical panels."),
                      ("Wiring", "Wiring for renovations and additions.")),
    "roofing_contractor": _G(("Roof repair", "Fixing leaks and damaged areas."), ("Roof replacement", "Replacing worn roofing."),
                             ("Inspections", "A look over your roof to see what it needs."), ("Eavestroughs", "Installing and repairing eavestroughs."),
                             ("Flat roofs", "Work on flat roofing.")),
    "painter": _G(("Interior painting", "Painting rooms, ceilings and trim."), ("Exterior painting", "Painting outside walls and trim."),
                  ("Surface prep", "Preparing walls before painting."), ("Colour advice", "Help choosing a colour."), ("Touch-ups", "Small repaint jobs.")),
    "locksmith": _G(("Lock repair", "Fixing stiff or broken locks."), ("Lock replacement", "Fitting new locks."), ("Rekeying", "Changing keys on existing locks."),
                    ("Lockouts", "Help when you cannot get in."), ("Key cutting", "Cutting spare keys.")),
    "moving_company": _G(("Home moves", "Moving a household from one address to another."), ("Packing help", "Help packing up your things."),
                         ("Loading and unloading", "Carrying items on and off the truck."), ("Local moves", "Moves within the area."),
                         ("Furniture moving", "Moving large or heavy items.")),
    "car_repair": _G(("Car repair", "Diagnosing and fixing vehicle problems."), ("Brakes", "Brake checks and repairs."), ("Oil changes", "Routine oil and filter changes."),
                     ("Tires", "Tire fitting and changes."), ("Inspections", "General vehicle checks.")),
    "car_wash": _G(("Exterior wash", "Washing the outside of your vehicle."), ("Interior cleaning", "Cleaning the inside of your vehicle."),
                   ("Waxing", "Wax and shine for the paint."), ("Vacuuming", "Vacuuming seats and floors.")),
    "laundry": _G(("Wash and fold", "Washing and folding your laundry."), ("Dry cleaning", "Cleaning for items that need extra care."),
                  ("Ironing", "Pressed and ready to wear."), ("Alterations", "Small clothing fixes.")),
}
CAT_SERVICES = {
    "trade": _G(("Repairs", "Fixing problems around your home or business."), ("Installation", "Fitting and setting up new work."),
                ("Maintenance", "Keeping things in good working order."), ("Quotes and advice", "Talk to us about what you need.")),
    "food": _G(("Dine in", "Come in and sit down for a meal."), ("Takeaway", "Ask us about taking food with you."), ("Drinks", "Something to drink with your visit."),
               ("Daily food", "Come by to see what is on today.")),
    "beauty": _G(("Hair", "Cuts and styling."), ("Nails", "Manicures and nail care."), ("Skin care", "Facials and skin treatments."), ("Consultations", "Talk through what you want.")),
    "health": _G(("Appointments", "Get in touch to arrange a visit."), ("Check-ups", "Routine visits and advice."), ("Treatment", "Care to suit what you need."),
                 ("Advice", "Ask us your questions.")),
    "retail": _G(("In-store shopping", "Browse what we have in the shop."), ("Gifts", "Ideas for the people in your life."), ("Special requests", "Ask about something specific."),
                 ("Advice", "Friendly help choosing.")),
    "care": _G(("Care and support", "Help for you and your family."), ("Advice", "Ask us your questions."), ("Visits", "Come and see the space."),
               ("Enquiries", "Get in touch to find out more.")),
    "stay": _G(("Stays", "Ask about staying with us."), ("Local information", "Questions about the area are welcome."), ("Enquiries", "Get in touch before you arrive."),
               ("Directions", "We can help you find us.")),
    "other": _G(("Consultations", "Talk through what you need."), ("Advice", "Clear, friendly guidance."), ("Support", "Help with the next steps."),
                ("Enquiries", "Get in touch to find out more.")),
}

# words that make a (title-case) service or menu name "generic" rather than an invented product name
_VOCAB = set("""repair repairs repairing installation install installing maintenance service services cleaning clean inspection inspections replacement removal
quote quotes advice consultation consultations support enquiries inquiries work job jobs home homes house residential commercial local emergency leak leaks drain drains
pipe pipes tap taps toilet toilets sink sinks water heater heaters bathroom kitchen basement fixture fixtures outlet outlets switch switches wiring lighting lights panel
panels roof roofing flat shingle shingles eavestrough eavestroughs gutters siding paint painting interior exterior walls ceilings trim colour color prep surface lock locks
locksmith rekeying key keys lockout lockouts moving packing loading unloading furniture truck brake brakes oil change changes tire tires engine diagnostics wash waxing
vacuuming laundry dry ironing alterations hair cut cuts styling colouring nails nail manicure pedicure skin care facial facials treatment treatments massage waxing
makeup brows lashes beard shave shaves barber appointment appointments check checkup checkups exam exams cleaning whitening fillings crowns implants therapy physio
training classes class membership gym fitness food drinks takeaway takeout delivery catering dine dining breakfast lunch dinner brunch dessert desserts sides specials daily
fresh baked homemade menu coffee espresso latte tea sandwiches sandwich soup salads salad pastries pastry bread cakes cake cookies pizza pasta burgers burger fries wings
shop store gifts gift flowers bouquets plants arrangements wedding weddings event events bike bikes books clothing jewellery jewelry stay stays rooms room breakfast
directions information area local grooming boarding walks pets pet vaccinations puppy kitten childcare daycare preschool programs program care visits visit planning
tailoring hemming fitting custom orders order pickup storage units unit insurance accounting tax taxes bookkeeping legal law property listings buying selling travel
trips tours bookings booking and the for with your our in of to on a an at by or""".split())
_MENU_WORDS = set("""pizza pasta burger burgers fries wings salad salads soup soups sandwich sandwiches wrap wraps breakfast brunch lunch dinner dessert desserts cake cakes
cookie cookies pastry pastries bread bagel bagels croissant croissants muffin muffins donut donuts doughnuts sushi ramen noodles rice curry curries tacos taco steak steaks chicken
fish seafood bbq ribs vegan vegetarian coffee espresso latte cappuccino tea smoothie smoothies juice beer wine cocktails cocktail pie pies tart tarts scone scones waffles pancakes
eggs bacon sausage kebab shawarma falafel gelato ice-cream sourdough baguette cupcakes brownies""".split())
_GENERIC_FOOD = set("food drinks drink menu takeaway takeout delivery catering dine dining sides specials daily fresh baked homemade eat order ahead pickup group events party platter "
                    "come in sit down meal meals snacks treats sweet savoury savory hot cold bites light kids family".split())


# ---------------------------------------------------------------- lead facts

def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _city(lead: dict) -> str:
    parts = [p.strip() for p in _s(lead.get("address")).split(",")]
    return parts[-3] if len(parts) >= 3 else ""


def _label(lead: dict) -> str:
    return (_s(lead.get("type_label")) or _s(lead.get("type")).replace("_", " ") or "local business").lower()


def _review_texts(lead: dict) -> list[str]:
    out = []
    for r in (lead.get("info") or {}).get("reviews", []) or []:
        text = r if isinstance(r, str) else (r.get("text") if isinstance(r, dict) else "")
        rating = r.get("rating") if isinstance(r, dict) else None
        text = re.sub(r"\s+", " ", text or "").strip()
        try:
            low = rating is not None and float(rating) < 4
        except (TypeError, ValueError):
            low = False
        if len(text) >= 12 and not low:
            out.append(text)
    return out


def _hours(lead: dict) -> list[str]:
    return [str(h) for h in ((lead.get("info") or {}).get("hours") or []) if h]


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _reviews_n(lead: dict) -> int:
    for k in ("reviews", "review_count", "userRatingCount", "user_ratings_total"):
        v = lead.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return int(v)
    return 0


def _summary(lead: dict) -> str:
    s = (lead.get("info") or {}).get("summary")
    return re.sub(r"\s+", " ", s).strip() if isinstance(s, str) else ""


def _facts(lead: dict) -> str:
    """Everything the page may legitimately say, as one string."""
    rating, n = _num(lead.get("rating")), _reviews_n(lead)
    return " ".join([_s(lead.get("name")), _s(lead.get("type")).replace("_", " "), _label(lead), _s(lead.get("address")), _s(lead.get("phone")),
                     str(rating or ""), str(n or ""), _summary(lead), " ".join(_hours(lead)), " ".join(_review_texts(lead))])


_H24 = re.compile(r"open 24 hours|24 hours|24/7|24-hour|24 ?hrs", re.I)


def _is24(lead: dict) -> bool:
    return bool(_H24.search(" ".join(_hours(lead)) + " " + _summary(lead)))


def menu_known(lead: dict) -> bool:
    if category_of(lead.get("type", "")) != "food":
        return False
    text = (_summary(lead) + " " + " ".join(_review_texts(lead))).lower()
    return bool(_MENU_WORDS & set(re.findall(r"[a-z][a-z-]+", text)))


def _titles(lead: dict) -> dict:
    cat = category_of(lead.get("type", ""))
    t = {k: CAT[cat][k] for k in ("services_title", "gallery_title", "reviews_title", "visit_title")}
    if cat == "food" and menu_known(lead):
        t["services_title"] = "On the menu"
    return t


# ---------------------------------------------------------------- fallback

def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def fallback_copy(lead: dict) -> dict:
    """Complete copy with no model, built only from what the lead holds."""
    cat = category_of(lead.get("type", ""))
    c, name, city, label = CAT[cat], _s(lead.get("name")) or "This business", _city(lead), _label(lead)
    rating, n = _num(lead.get("rating")), _reviews_n(lead)
    titles = _titles(lead)
    hours = _hours(lead)

    headline = f"{_cap(label)} in {city}" if city else f"Your local {label}"
    if cat == "food":
        headline = f"Eat and drink in {city}" if city else f"Your local {label}"
    elif cat in ("beauty", "retail", "stay"):
        headline = f"Visit us in {city}" if city else f"Your local {label}"
    if _norm(headline) == _norm(name):
        headline = f"Welcome to {name}"
    # About: facts only, padded with neutral category sentences up to ~40-70 words
    sents = [f"{name} is a {label} in {city}." if city else (f"{name} is a {label} at {_s(lead.get('address'))}." if _s(lead.get("address")) else f"{name} is a {label}.")]
    summ = _summary(lead)
    if summ:
        sents.append(_fit(summ, 30))
    if rating and n:
        sents.append(f"It is rated {rating:g} on Google from {n} reviews.")
    elif rating:
        sents.append(f"It is rated {rating:g} on Google.")
    for f in c["fillers"]:
        if sum(len(x.split()) for x in sents) >= 40:
            break
        sents.append(f)
    about = " ".join(sents)

    highlights = []
    if rating and rating >= 4:
        highlights.append(f"Rated {rating:g} on Google")
    if city:
        highlights.append(f"Based in {city}")
    if hours:
        highlights.append("Opening hours listed below")
    highlights += [h for h in c["highlights"] if h not in highlights]

    svc = TYPE_SERVICES.get(_s(lead.get("type")).lower()) or CAT_SERVICES[cat]
    steps = STEPS[cat][:4]
    faq = []
    if hours:
        faq.append({"q": "When are you open?", "a": "Our opening hours are listed on this page, so you can check before you visit."})
    if _s(lead.get("address")):
        faq.append({"q": "Where are you?", "a": f"You can find us at {_s(lead.get('address'))}."})
    if _s(lead.get("phone")):
        faq.append({"q": "How do I get in touch?", "a": f"Call us on {_s(lead.get('phone'))}."})
    faq.append({"q": "What do you offer?", "a": "See the list above, or get in touch and ask."})

    out = {"headline": headline, "tagline": c["tagline"], "about_title": "About us", "about": _fit(about, 70),
           "services": [dict(s) for s in svc[:6]], **titles,
           "highlights": highlights[:3], "steps": [{"title": a, "text": b} for a, b in steps], "faq": faq[:4],
           "cta_title": c["cta_title"], "cta_text": c["cta_text"]}
    if city:
        out["area"] = f"{city} and nearby"
    return out


# ---------------------------------------------------------------- prompts

def _compact_hours(lead: dict) -> str:
    if _is24(lead) and not _hours(lead):
        return "open 24 hours"
    out = []
    for h in _hours(lead)[:7]:
        day, _, when = h.partition(": ")
        out.append(f"{day[:3]} {when}".strip() if when else h[:30])
    return "; ".join(out)[:260]


def _data(lead: dict, rival_tips: str) -> dict:
    d = {"name": _s(lead.get("name")), "type": _label(lead), "city": _city(lead), "rating": _num(lead.get("rating")), "review_count": _reviews_n(lead) or None,
         "google_summary": _summary(lead)[:220] or None, "hours": _compact_hours(lead) or None,
         "review_excerpts": [t[:120] for t in _review_texts(lead)[:3]] or None}
    d = {k: v for k, v in d.items() if v not in (None, "")}
    if rival_tips and isinstance(rival_tips, str):
        d["competitor_ideas_style_only"] = rival_tips.strip()[:200]
    return d


def copy_prompt(lead: dict, rival_tips: str = "") -> str:
    cat = category_of(lead.get("type", ""))
    t, c = _titles(lead), CAT[cat]
    menu = ""
    if cat == "food":
        menu = ("8. Dish names only if they appear in DATA; otherwise describe the food in general words.\n" if menu_known(lead)
                else "8. Name no dishes; describe the food in general words.\n")
    skeleton = ('{"headline":"3-7 words, not the business name","tagline":"one sentence, max 22 words","about_title":"2-5 words","about":"40-70 words",'
                f'"services_title":"{t["services_title"]}","services":[{{"name":"max 4 words","text":"max 20 words"}}],"gallery_title":"{t["gallery_title"]}",'
                f'"reviews_title":"{t["reviews_title"]}","visit_title":"{t["visit_title"]}","highlights":["max 6 words","max 6 words","max 6 words"],'
                '"steps":[{"title":"","text":""}],"faq":[{"q":"","a":""}],"cta_title":"max 6 words","cta_text":"one or two sentences"}')
    return ("You write website copy for one small local business. Reply with ONLY the JSON object below, filled in.\n"
            "Rules:\n"
            "1. Use only the facts in DATA. Add nothing else: no history, credentials, offers, numbers, promises or people's names.\n"
            "2. Plain, concrete words. The headline must not be the business name.\n"
            f"3. Tone: {c['tone']}.\n"
            "4. Give 4 to 6 services, with generic names for what this kind of business does.\n"
            "5. Exactly 3 highlights. 3 or 4 steps using plain process words only (contact, visit, work, follow-up); no times or costs.\n"
            "6. FAQ: 0 to 4 items, only about opening hours, location, how to get in touch, or what is offered.\n"
            "7. Keep the section titles shown.\n" + menu +
            f"JSON to fill:\n{skeleton}\n"
            f"DATA:\n{json.dumps(_data(lead, rival_tips), ensure_ascii=False)}")


def brief_prompt(lead: dict, recipes: list[str], recipe_notes: dict[str, str]) -> str:
    from .web import MOODS  # lazy: web.py imports this layer

    names = [r for r in recipes if isinstance(r, str)]
    notes = "\n".join(f"- {r}: {' '.join(str((recipe_notes or {}).get(r, '')).split()[:10])}".rstrip(": ") for r in names)
    d = {"name": _s(lead.get("name")), "type": _label(lead), "city": _city(lead), "google_summary": _summary(lead)[:200] or None}
    d = {k: v for k, v in d.items() if v}
    return ("You choose a look for a small business website. Reply with ONLY JSON: "
            '{"style":"<one recipe name>","mood":["<1 to 3 moods>"],"keywords":["<4 stock photo searches>"]}\n'
            f"Rules:\n1. style must be exactly one of:\n{notes}\n"
            f"2. mood: 1 to 3 words from: {', '.join(sorted(MOODS))}.\n"
            "3. keywords: 4 short searches for photos of this exact trade at work, or its typical product or interior. No brand names, no place names.\n"
            f"DATA:\n{json.dumps(d, ensure_ascii=False)}")


# ---------------------------------------------------------------- cleaning

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿⌀-⏿]")
_TAG = re.compile(r"<[^>]*>")
_PLACEHOLDER = re.compile(r"lorem|ipsum|\[[^\]]*\]|\{[^}]*\}|\byour (?:business|company|name|city|town|brand|service)\b|\bbusiness name\b|\bcompany name\b|"
                          r"\binsert\b|\bplaceholder\b|\btbd\b|\bx{3,}\b|example\.com|\bcity name\b|\b(?:sample|dummy) text\b|\b(?:max|up to) \d+ words?\b|"
                          r"\b\d+\s?-\s?\d+ words\b|\bone sentence\b|\bone or two sentences\b|\bnot the business name\b", re.I)
_STOP = {"and", "or", "the", "a", "an", "of", "with", "for", "to", "in", "on", "at", "by", "from", "your", "our", "is", "are", "that", "&"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _sentences(text: str) -> list[str]:
    return [p for p in re.split(r"(?<!\bDr\.)(?<!\bMr\.)(?<!\bMrs\.)(?<!\bMs\.)(?<!\bSt\.)(?<!\bNo\.)(?<=[.!?])\s+", text.strip()) if p]


def _end(text: str, period: bool) -> str:
    text = text.strip().rstrip(",;:-–— ")
    if not period:
        return text.rstrip(".!?:;, ")
    return text if text.endswith((".", "!", "?")) else text + "."


def _fit(text: str, max_words: int, period: bool = True) -> str:
    """Trim at a sentence boundary if possible, else at a word boundary."""
    text = text.strip()
    if len(text.split()) <= max_words:
        return _end(text, period)
    out, n = [], 0
    for s in _sentences(text):
        w = len(s.split())
        if n + w > max_words:
            break
        out.append(s)
        n += w
    if out:
        return _end(" ".join(out), period)
    words = text.split()[:max_words]
    clause = re.split(r"[,;:–—]| - ", " ".join(words))[0].split()
    if len(clause) >= max(3, max_words // 2):
        words = clause
    while words and words[-1].lower().strip(",;:.") in _STOP:
        words.pop()
    return _end(" ".join(words), period)


class _Ctx:
    """Facts for one lead: what claims and numbers the lead text supports."""

    def __init__(self, lead: dict):
        self.lead = lead if isinstance(lead, dict) else {}
        self.cat = category_of(self.lead.get("type", ""))
        self.name = _s(self.lead.get("name"))
        self.city = _city(self.lead)
        self.facts = _facts(self.lead)
        self.low = self.facts.lower()
        self.tokens = set(re.findall(r"[a-z][a-z'-]+", self.low))
        self.nums = set(re.findall(r"\d+(?:\.\d+)?", self.facts))
        r = _num(self.lead.get("rating"))
        if r is not None:
            self.nums |= {f"{r:g}", f"{r:.1f}"}
        self.h24 = _is24(self.lead)
        self.summary_low = _summary(self.lead).lower()
        self.menu = menu_known(self.lead)
        self.upper_words = {w for w in re.findall(r"\b[A-Z]{2,}\b", self.facts)}


# (name, pattern, support mode): facts = same pattern appears in the lead text; exact = the matched words appear in it;
# never = no lead text can support it; h24 = hours data shows round-the-clock; emerg = h24 or the Google summary says emergency
_CLAIMS = [
    ("years", re.compile(r"\bsince\s+(?:19|20)\d{2}\b|\b\d+\+?\s*(?:years?|yrs?)\b|\byears (?:of|in)\b|\bdecades?\b|\bgenerations?\b|\bestablished\b|\bfounded\b|\best\.\s*\d{4}", re.I), "facts"),
    ("award", re.compile(r"award[- ]winning|\bawards?\b|\bawarded\b|\bvoted\b", re.I), "facts"),
    ("superlative", re.compile(r"#\s?1\b|\bnumber (?:one|1)\b|\bbest\b|\btop[- ]rated\b|\bfinest\b|\bleading\b|\bpremier\b|\bunbeatable\b|\bunmatched\b|"
                               r"\bsecond to none\b|\b(?:5|five)[- ]star\b", re.I), "never"),
    ("credential", re.compile(r"\blicen[sc]ed\b|\binsured\b|\bcertified\b|\baccredited\b|\bbonded\b|\bfully (?:qualified|trained)\b|\bregistered\b", re.I), "facts"),
    ("guarantee", re.compile(r"\bguarantee[sd]?\b|\bwarrant(?:y|ies)\b", re.I), "facts"),
    ("family", re.compile(r"\bfamily[- ](?:owned|run|operated)\b|\bowner[- ]operated\b|\blocally[- ](?:owned|operated)\b|\bindependent(?:ly)?[- ](?:owned|run)\b", re.I), "facts"),
    ("round_clock", re.compile(r"\b24\s?/\s?7\b|\b24[- ]hours?\b|\baround the clock\b|\b365\b", re.I), "h24"),
    ("emergency", re.compile(r"\bemergenc(?:y|ies)\b|\bsame[- ]day\b|\bafter[- ]hours\b|\bnext[- ]day\b|\bon[- ]call\b", re.I), "emerg"),
    ("price", re.compile(r"[$£€]\s?\d|\b\d+(?:\.\d+)?\s?%|\bdiscounts?\b|\bfree (?:quotes?|estimates?|consultations?|shipping|delivery|parking|wi-?fi|inspections?|assessments?)\b|"
                         r"\baffordabl[ey]\b|\bcheap(?:est)?\b|\blowest\b|\bcompetitive (?:pric\w+|rates)\b|\bno hidden\b|\bbudget[- ]friendly\b|"
                         r"\b(?:transparent|upfront|fair|low|great|best) (?:pric\w+|rates?)\b|\bpric(?:es|ing)\b", re.I), "exact"),
    ("count", re.compile(r"\b\d[\d,]*\+\s*\w+|\b\d{2,}[\d,]*\s+(?:\w+\s+)?(?:customers|clients|projects|jobs|homes|families|patients|guests|weddings|cars|locations|branches|happy)\b|"
                         r"\b(?:hundreds|thousands|millions) of\b|\bcountless\b|\bmany satisfied\b", re.I), "exact"),
    ("staff", re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Chef)\.?\s+[A-Z][a-z]+|\b(?i:owner|founder|founded by|run by|led by|owned by|managed by)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"), "exact"),
]


def _unsupported(text: str, cx: _Ctx) -> bool:
    """True when the text makes a claim (or states a number) that the lead text does not support."""
    for name, rx, mode in _CLAIMS:
        for m in list(rx.finditer(text)):
            g = m.group(0).lower().strip()
            ok = {"facts": lambda: bool(rx.search(cx.facts)), "exact": lambda: g in cx.low, "never": lambda: False,
                  "h24": lambda: cx.h24, "emerg": lambda: cx.h24 or "emergency" in cx.summary_low}[mode]()
            if not ok:
                return True
            text = text.replace(m.group(0), " ")  # a supported claim's own digits (24/7, 20 years) are fine
    for n in re.findall(r"\d+(?:\.\d+)?", text):
        if n not in cx.nums:
            return True
    return False


def _clean_str(v: Any, cx: _Ctx) -> str:
    """Plain text: no tags/emoji/markdown, sane capitals, no placeholders. '' means unusable."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        return ""
    s = _TAG.sub(" ", v)
    s = _EMOJI.sub("", s)
    s = re.sub(r"[*_`#>]+|^\s*(?:[-•]|\d+[.)])\s+", "", s, flags=re.M)
    s = re.sub(r"\s+", " ", s).strip(" \t\"'")
    s = re.sub(r"(?:\.{2,}|…)+\s*$", "", s).strip()
    if not s or _PLACEHOLDER.search(s):
        return ""
    letters = [ch for ch in s if ch.isalpha()]
    if len(letters) >= 6 and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        s = ". ".join(_cap(p.strip()) for p in s.lower().split(". "))
        s = _cap(s)
        for w in cx.upper_words:
            s = re.sub(rf"\b{re.escape(w.lower())}\b", w, s)
        if cx.name:
            s = re.sub(re.escape(cx.name), cx.name, s, flags=re.I)
    return s


def _clean_text(v: Any, cx: _Ctx) -> str:
    """Prose: unsupported-claim sentences are dropped, not rewritten."""
    s = _clean_str(v, cx)
    return " ".join(x for x in _sentences(s) if not _unsupported(x, cx))


def _clean_short(v: Any, cx: _Ctx, max_words: int) -> str:
    """Titles, names, highlights: one claim anywhere drops the whole item."""
    s = _clean_str(v, cx)
    if not s or _unsupported(s, cx):
        return ""
    s = _fit(_sentences(s)[0] if len(s.split()) > max_words and _sentences(s) else s, max_words, period=False)
    return "" if _unsupported(s, cx) else s


def _stem(w: str) -> str:
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def _brandish(name: str, cx: _Ctx) -> bool:
    """Looks like an invented brand/product name: not generic vocabulary and not in the lead text."""
    if re.search(r"[™®©\d]", name):
        return True
    toks = re.findall(r"[A-Za-z][A-Za-z'’-]*", name)
    known = lambda t: t.lower() in _VOCAB or _stem(t.lower()) in _VOCAB or t.lower() in cx.tokens or _stem(t.lower()) in cx.tokens  # noqa: E731
    if cx.cat == "food":
        food = lambda t: known(t) or t.lower() in _MENU_WORDS or _stem(t.lower()) in _MENU_WORDS or t.lower() in _GENERIC_FOOD  # noqa: E731
        return any(len(t) > 3 and not food(t) for t in toks)
    return any(t[:1].isupper() and not t.isupper() and len(t) > 3 and not known(t) for t in toks[1:])


def _split_pair(s: str) -> tuple[str, str]:
    m = re.split(r"\s*[:–—]\s*|\s+-\s+", s, maxsplit=1)
    return (m[0], m[1]) if len(m) == 2 else (s, "")


def _pairs(raw: Any, keys_a: tuple, keys_b: tuple) -> list[tuple[Any, Any]]:
    """Normalise list items given as dicts or 'Name: text' strings into (a, b) pairs."""
    if isinstance(raw, str):
        raw = [p for p in re.split(r"\n+|;\s*", raw) if p.strip()]
    if isinstance(raw, dict):
        raw = [{"name": k, "text": v} for k, v in raw.items()] if not any(k in raw for k in keys_a) else [raw]
    out = []
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, dict):
            low = {str(k).lower(): v for k, v in it.items()}
            out.append((next((low[k] for k in keys_a if k in low), ""), next((low[k] for k in keys_b if k in low), "")))
        elif isinstance(it, str):
            a, b = _split_pair(it)
            out.append((a, b))
    return out


def _services(raw: Any, cx: _Ctx, fb: list[dict]) -> list[dict]:
    out, seen = [], set()
    for a, b in _pairs(raw, ("name", "title", "service"), ("text", "description", "desc", "details")):
        name = _clean_short(a, cx, 4)
        if not name or _norm(name) in seen or _brandish(name, cx):
            continue
        text = _cap(_fit(_clean_text(b, cx), 20)) if _clean_text(b, cx) else ""
        if _norm(text) == _norm(name):
            text = ""
        seen.add(_norm(name))
        out.append({"name": name, "text": text})
    fbt = {_norm(s["name"]): s["text"] for s in fb}
    for s in out:
        s["text"] = s["text"] or fbt.get(_norm(s["name"]), "") or f"Get in touch to ask about {s['name'].lower()}."
    out = out[:6]
    for s in fb:
        if len(out) >= 4:
            break
        if _norm(s["name"]) not in seen:
            seen.add(_norm(s["name"]))
            out.append(dict(s))
    return out


_TIMING = re.compile(r"\b(?:within|in|under|just)\s+\d+|\b\d+\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|business)\b|\bsame[- ]day\b|\bnext[- ]day\b|\bimmediately\b|"
                     r"\b(?:fast|quick(?:ly)?|prompt(?:ly)?|rapid|instant(?:ly)?)\b|\bfree\b|\bno obligation\b", re.I)


def _steps(raw: Any, cx: _Ctx, fb: list[dict]) -> list[dict]:
    out, seen = [], set()
    for a, b in _pairs(raw, ("title", "name", "step"), ("text", "description", "desc")):
        title, text = _clean_short(a, cx, 4), _clean_text(b, cx)
        text = _fit(text, 18) if text else ""
        if not title or not text or _TIMING.search(title + " " + text) or _norm(title) in seen:
            continue
        seen.add(_norm(title))
        out.append({"title": title, "text": text})
    return out[:4] if len(out) >= 3 else fb


_FAQ_BAN = re.compile(r"\bpric\w*|\bcost\w*|how much|\bfees?\b|\bwarrant\w*|\bguarant\w*|\binsur\w*|\bpay(?:ment|ments)?\b|credit card|\bcash\b|\bfinanc\w*|\blicen\w*|"
                      r"\bcertif\w*|\bdeposit\w*|\bdiscount\w*|\bquote\w*|\bestimate\w*|\brefund\w*|\bcancel\w*", re.I)
_FAQ_OK = re.compile(r"\b(?:open|hours?|when|where|located|location|address|find|area|serve|book|appointments?|contact|call|reach|phone|visit|offer|services?|what|do you|how (?:do|can))\b", re.I)


def _faq(raw: Any, cx: _Ctx) -> list[dict]:
    out, seen = [], set()
    for q, a in _pairs(raw, ("q", "question"), ("a", "answer")):
        q, a = _clean_short(q, cx, 14), _clean_text(a, cx)
        if not q or not a or _FAQ_BAN.search(q + " " + a) or not _FAQ_OK.search(q):
            continue
        if re.search(r"\b(?:open|hours?)\b", q, re.I) and not _hours(cx.lead):
            continue
        q = q.rstrip("?. ") + "?"
        if _norm(q) in seen:
            continue
        seen.add(_norm(q))
        out.append({"q": q, "a": _fit(a, 40)})
    return out[:4]


def _title_ok(key: str, text: str, cx: _Ctx) -> bool:
    low = text.lower()
    if "menu" in low and not (cx.cat == "food" and cx.menu):
        return False
    if re.search(r"\b(?:inside|kitchen|space|studio|salon|table|dining)\b", low) and key == "gallery_title":
        return text == CAT[cx.cat]["gallery_title"]
    return True


def _parse(raw: Any) -> dict:
    if isinstance(raw, str):
        s = re.sub(r"```(?:json)?", "", raw)
        a, b = s.find("{"), s.rfind("}")
        try:
            raw = json.loads(s[a:b + 1]) if a != -1 and b > a else {}
        except ValueError:
            raw = {}
    if isinstance(raw, list):
        raw = next((x for x in raw if isinstance(x, dict)), {})
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip().lower(): v for k, v in raw.items()}


def clean_copy(raw: Any, lead: dict) -> dict:
    """The model's copy, kept only where it is usable and supported; merged over fallback_copy. Never raises."""
    try:
        lead = lead if isinstance(lead, dict) else {}
        fb = fallback_copy(lead)
        cx = _Ctx(lead)
        r = _parse(raw)
        out = dict(fb)

        h = _clean_short(r.get("headline"), cx, 7)
        rest = _norm(re.sub(re.escape(cx.name), " ", h, flags=re.I)) if cx.name else _norm(h)
        if h and len(h.split()) >= 3 and len(rest.split()) >= 2 and _norm(h) != _norm(cx.name):
            out["headline"] = h
        tg = _clean_text(r.get("tagline"), cx)
        if tg:
            tg = _fit(_sentences(tg)[0], 22)
            if len(tg.split()) >= 3:
                out["tagline"] = tg
        at = _clean_short(r.get("about_title"), cx, 5)
        if len(at.split()) >= 2:
            out["about_title"] = at
        about = _clean_text(r.get("about"), cx)
        if about and len(about.split()) >= 12:
            if len(about.split()) < 40:  # top up with the fallback's own sentences
                for s in _sentences(fb["about"]):
                    if len(about.split()) >= 40:
                        break
                    if _norm(s) not in _norm(about) and len(about.split()) + len(s.split()) <= 70:
                        about += " " + s
            out["about"] = _fit(about, 70)
        out["services"] = _services(r.get("services"), cx, fb["services"])
        for k in ("services_title", "gallery_title", "reviews_title", "visit_title", "cta_title"):
            t = _clean_short(r.get(k), cx, 6 if k == "cta_title" else 5)
            if t and (k == "cta_title" or _title_ok(k, t, cx)) and len(t.split()) >= 1:
                out[k] = t
        # section titles are tied to the category; the model may only reword them when it stays inside the category's wording
        if cx.cat == "food" and not cx.menu and "menu" in out["services_title"].lower():
            out["services_title"] = CAT["food"]["services_title"]
        raw_h = r.get("highlights")
        if isinstance(raw_h, str):
            raw_h = [p for p in re.split(r"\n+|;|•", raw_h) if p.strip()]
        hl, seen = [], set()
        for x in raw_h if isinstance(raw_h, list) else []:
            x = _clean_short(x.get("text") if isinstance(x, dict) else x, cx, 6)
            if x and _norm(x) not in seen:
                seen.add(_norm(x))
                hl.append(x)
        for x in fb["highlights"] + CAT[cx.cat]["highlights"]:
            if len(hl) >= 3:
                break
            if _norm(x) not in seen:
                seen.add(_norm(x))
                hl.append(x)
        out["highlights"] = hl[:3]
        out["steps"] = _steps(r.get("steps"), cx, fb["steps"])
        faq = _faq(r.get("faq"), cx)
        out["faq"] = faq or fb["faq"]
        ct = _clean_text(r.get("cta_text"), cx)
        if ct:
            out["cta_text"] = _fit(" ".join(_sentences(ct)[:2]), 25)
        if fb.get("area"):
            out["area"] = fb["area"]  # always built from the address, never from the model
        return out
    except Exception:  # noqa: BLE001 - copy must never break a build
        return fallback_copy(lead if isinstance(lead, dict) else {})


# ---------------------------------------------------------------- the model call

def _missing(raw: Any) -> list[str]:
    r = _parse(raw)
    miss = [k for k in ("headline", "tagline", "about_title", "about") if not (isinstance(r.get(k), str) and r[k].strip())]
    if not (isinstance(r.get("services"), (list, str, dict)) and r.get("services")):
        miss.append("services")
    return miss


async def write_copy(llm, lead: dict, rival_tips: str = "") -> dict:
    """prompt -> llm.json -> clean_copy; one repair attempt; fallback copy when the model is missing or useless."""
    try:
        from ..services.llm import LLMUnavailable
    except Exception:  # noqa: BLE001
        LLMUnavailable = ()  # type: ignore[assignment]  # noqa: N806
    try:
        prompt = copy_prompt(lead, rival_tips)
        raw = None
        try:
            raw = await llm.json(prompt, tier="cloud", max_tokens=1100)
        except LLMUnavailable:
            return fallback_copy(lead)
        except Exception:  # noqa: BLE001
            raw = None
        miss = _missing(raw)
        if miss:
            shown = ""
            if raw:
                try:
                    shown = f"\nYour last reply (fix it):\n{(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False))[:1200]}"
                except (TypeError, ValueError):
                    shown = ""
            fix = (f"Your last reply was not usable JSON: missing or empty keys: {', '.join(miss) or 'all'}. "
                   f"Reply again with ONLY the complete JSON object.{shown}\n\n" + prompt)
            try:
                raw2 = await llm.json(fix, tier="cloud", max_tokens=1100)
                if raw2 and len(_missing(raw2)) <= len(miss):
                    raw = raw2
            except LLMUnavailable:
                pass
            except Exception:  # noqa: BLE001
                pass
        return clean_copy(raw, lead) if raw else fallback_copy(lead)
    except Exception:  # noqa: BLE001
        return fallback_copy(lead)
