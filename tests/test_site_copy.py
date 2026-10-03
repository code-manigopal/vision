import asyncio
import re

import pytest

from vision.masters import site_copy as sc
from vision.masters.web import MORE_TYPES
from vision.services.llm import LLMUnavailable

REQUIRED = ("headline", "tagline", "about_title", "about", "services")


def lead(type_="roofing_contractor", label="Roofing contractor", name="Hartley Roofing", summary="", hours=None, reviews=None, **kw):
    return {"id": "x", "name": name, "type": type_, "type_label": label, "address": "12 Talbot St, Leamington, ON N8H 1A1, Canada",
            "phone": "(519) 555-0100", "rating": 4.8, "reviews": 120,
            "info": {"summary": summary, "hours": hours if hours is not None else ["Monday: 8:00 AM - 5:00 PM", "Tuesday: 8:00 AM - 5:00 PM"],
                     "reviews": reviews if reviews is not None else [{"text": "They fixed our leak and tidied up afterwards.", "rating": 5}]}, **kw}


def good(**over):
    d = {"headline": "Roofing help in Leamington", "tagline": "Tell us about your roof and we will get back to you.", "about_title": "About the team",
         "about": " ".join(["We repair and replace roofs for homes around Leamington."] * 6),
         "services": [{"name": "Roof repair", "text": "Fixing leaks and damaged areas."}, {"name": "Roof replacement", "text": "Replacing worn roofing."},
                      {"name": "Inspections", "text": "A look over your roof."}, {"name": "Eavestroughs", "text": "Installing and repairing eavestroughs."}],
         "highlights": ["Rated 4.8 on Google", "Based in Leamington", "Call to talk it through"],
         "steps": [{"title": "Get in touch", "text": "Call or message about the job."}, {"title": "We visit", "text": "We look at the roof."},
                   {"title": "The work", "text": "The work is carried out."}],
         "faq": [{"q": "Where are you based?", "a": "In Leamington."}], "cta_title": "Need a hand?", "cta_text": "Call us to talk about your roof."}
    d.update(over)
    return d


def full(c):
    for k in REQUIRED:
        assert c.get(k), k
    assert 4 <= len(c["services"]) <= 6 and len(c["highlights"]) == 3 and 3 <= len(c["steps"]) <= 4


class Fake:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def json(self, prompt, **kw):
        self.prompts.append(prompt)
        r = self.replies.pop(0) if self.replies else None
        if isinstance(r, Exception):
            raise r
        return r


def run(c):
    return asyncio.run(c)


def test_categories_cover_all_more_types():
    for t in MORE_TYPES:
        assert sc.category_of(t) in sc.CAT and sc.category_of(t) != "other" or t in ("real_estate_agency", "insurance_agency", "accounting", "lawyer", "travel_agency", "storage"), t
    assert sc.category_of("roofing_contractor") == "trade" and sc.category_of("pizza_place") == "food" and sc.category_of("weird") == "other"


def test_fallback_per_category():
    t = sc.fallback_copy(lead())
    full(t)
    assert t["services_title"] == "What we do" and t["gallery_title"] == "Recent work" and "inside" not in t["gallery_title"].lower()
    assert t["area"] == "Leamington and nearby" and t["headline"] != "Hartley Roofing"
    f = sc.fallback_copy(lead("cafe", "Cafe", "Bean There"))
    full(f)
    assert f["services_title"] == "What we serve" and f["gallery_title"] == "From our kitchen"
    f2 = sc.fallback_copy(lead("cafe", "Cafe", "Bean There", summary="Cozy spot with great espresso and pastries."))
    assert f2["services_title"] == "On the menu"
    b = sc.fallback_copy(lead("hair_salon", "Hair salon", "Studio K"))
    full(b)
    assert b["services_title"] == "Services" and b["gallery_title"] == "The space"
    assert 40 <= len(t["about"].split()) <= 70


def test_fallback_has_no_unsupported_claims():
    for t in ("roofing_contractor", "cafe", "hair_salon", "dentist", "storage", "bed_and_breakfast"):
        l = lead(t, t.replace("_", " "), "Acme")
        c = sc.fallback_copy(l)
        cx = sc._Ctx(l)
        texts = [c["tagline"], c["about"], c["cta_text"]] + [s["text"] for s in c["services"]] + c["highlights"]
        assert not [x for x in texts if sc._unsupported(x, cx)], t


def test_clean_perfect_input():
    c = sc.clean_copy(good(), lead())
    full(c)
    assert c["headline"] == "Roofing help in Leamington" and c["services"][0]["name"] == "Roof repair"
    assert c["highlights"] == ["Rated 4.8 on Google", "Based in Leamington", "Call to talk it through"]
    assert c["faq"][0]["q"] == "Where are you based?" and len(c["steps"]) == 3


@pytest.mark.parametrize("raw", [None, "just some words", ["a", "b"], 42, {}, {"headline": None, "services": 5}])
def test_clean_garbage(raw):
    full(sc.clean_copy(raw, lead()))
    full(sc.clean_copy(raw, None))


def test_fences_and_string_json():
    c = sc.clean_copy("```json\n" + __import__("json").dumps(good(headline="Roofing care in Leamington")) + "\n```", lead())
    assert c["headline"] == "Roofing care in Leamington"


def test_services_as_strings():
    c = sc.clean_copy(good(services=["Roof repair: we fix leaks", "Gutter cleaning - clearing out the gutters", "Inspections", "Roof repair"]), lead())
    names = [s["name"] for s in c["services"]]
    assert names[:3] == ["Roof repair", "Gutter cleaning", "Inspections"] and names.count("Roof repair") == 1
    assert c["services"][0]["text"] == "We fix leaks." and c["services"][2]["text"]
    assert len(c["services"]) >= 4


def test_length_limits():
    long = "word " * 80
    c = sc.clean_copy(good(headline="One two three four five six seven eight nine", tagline="This is a sentence. " + long, about=long + ".",
                           services=[{"name": "A very long service name indeed here", "text": long}] * 1 + good()["services"][:3],
                           highlights=["a b c d e f g h i j", "x", "y", "z"], cta_text=long), lead())
    assert len(c["headline"].split()) <= 7 and len(c["tagline"].split()) <= 22
    assert len(c["about"].split()) <= 70 and all(len(s["name"].split()) <= 4 and len(s["text"].split()) <= 20 for s in c["services"])
    assert len(c["highlights"]) == 3 and all(len(h.split()) <= 6 for h in c["highlights"]) and len(c["cta_text"].split()) <= 25


CLAIMS = {
    "years": "We have been in business since 1998.", "years2": "Over 20 years of experience.", "award": "An award-winning team.", "best": "The best roofer in town.",
    "num1": "We are #1 in Leamington.", "licensed": "Fully licensed roofers.", "insured": "We are insured.", "certified": "Certified installers.",
    "guarantee": "All work is guaranteed.", "family": "A family-owned company.", "247": "Open 24/7 for you.", "emergency": "Emergency repairs available.",
    "price": "Roof repairs from $99.", "discount": "Ask about our discount.", "count": "Trusted by 500+ customers.", "count2": "We have helped 300 homes.",
    "staff": "Meet owner Mike Hartley.", "dr": "Dr. Smith leads the team.",
}


@pytest.mark.parametrize("key", list(CLAIMS))
def test_claims_removed(key):
    keep = "We repair roofs around Leamington."
    c = sc.clean_copy(good(about=f"{keep} {CLAIMS[key]} " + "Call to talk about your roof. " * 4), lead())
    assert CLAIMS[key] not in c["about"] and keep in c["about"], c["about"]
    c = sc.clean_copy(good(highlights=[CLAIMS[key].rstrip("."), "Based in Leamington", "Rated 4.8 on Google", "Call us"]), lead())
    assert CLAIMS[key].rstrip(".") not in c["highlights"] and len(c["highlights"]) == 3
    c = sc.clean_copy(good(services=[{"name": "Roof repair", "text": CLAIMS[key]}] + good()["services"][1:]), lead())
    assert c["services"][0]["text"] != CLAIMS[key]


def test_supported_claims_kept():
    l = lead(summary="Family-owned roofing business, open 24 hours for emergency calls.", hours=["Monday: Open 24 hours"])
    c = sc.clean_copy(good(about="A family-owned team. Open 24/7 for emergency repairs. We cover Leamington roofs. " * 2), l)
    assert "family-owned" in c["about"] and "24/7" in c["about"] and "emergency" in c["about"]
    assert sc.clean_copy(good(tagline="Open 24/7 for you."), lead())["tagline"] != "Open 24/7 for you."
    l2 = lead(reviews=[{"text": "Great licensed crew, very tidy work.", "rating": 5}])
    assert "licensed" in sc.clean_copy(good(tagline="Licensed crew you can call."), l2)["tagline"].lower()


def test_placeholders_html_emoji_caps():
    c = sc.clean_copy(good(tagline="Welcome to [City] roofing", about="Lorem ipsum dolor sit amet. " + good()["about"], about_title="Your Business",
                           services=[{"name": "<b>Roof repair</b> \U0001F527", "text": "Fixing <i>leaks</i> fast..."}] + good()["services"][1:],
                           cta_text="CALL US TODAY TO TALK ABOUT YOUR ROOF AND WHAT IT NEEDS NOW"), lead())
    assert "[" not in c["tagline"] and c["tagline"] == sc.fallback_copy(lead())["tagline"]
    assert "lorem" not in c["about"].lower() and c["about_title"] == "About us"
    assert c["services"][0]["name"] == "Roof repair" and "<" not in c["services"][0]["text"] and not c["services"][0]["text"].endswith("..")
    assert c["cta_text"] != c["cta_text"].upper() and c["cta_text"].startswith("Call us")


def test_headline_equal_to_name_replaced():
    for h in ("Hartley Roofing", "HARTLEY ROOFING!", "Hartley Roofing Ltd"):
        c = sc.clean_copy(good(headline=h), lead())
        assert c["headline"] == sc.fallback_copy(lead())["headline"]


def test_three_highlights():
    assert len(sc.clean_copy(good(highlights=["Only one"]), lead())["highlights"]) == 3
    assert len(sc.clean_copy(good(highlights=[f"Point number {i}" for i in range(6)]), lead())["highlights"]) == 3
    assert len(sc.clean_copy(good(highlights="a thing; another thing"), lead())["highlights"]) == 3


def test_faq_filtering():
    faq = [{"q": "How much does a roof repair cost?", "a": "It depends."}, {"q": "Do you offer a warranty?", "a": "Yes."},
           {"q": "What are your hours?", "a": "See the hours on this page."}, {"q": "Where do you work", "a": "In Leamington and nearby."},
           {"q": "Do you take credit cards?", "a": "Yes."}]
    c = sc.clean_copy(good(faq=faq), lead())
    assert [f["q"] for f in c["faq"]] == ["What are your hours?", "Where do you work?"]
    no_hours = sc.clean_copy(good(faq=faq), lead(hours=[]))
    assert all("hours" not in f["q"].lower() for f in no_hours["faq"])


def test_steps_no_promised_timing():
    steps = [{"title": "Call", "text": "We reply within 24 hours."}, {"title": "Visit", "text": "We look at it."}, {"title": "Work", "text": "Done quickly."}]
    assert sc.clean_copy(good(steps=steps), lead())["steps"] == sc.fallback_copy(lead())["steps"]


def test_invented_menu_items():
    l = lead("restaurant", "Restaurant", "Olive Bar", summary="Serves pizza and pasta.")
    c = sc.clean_copy(good(services=[{"name": "Pizza", "text": "Fresh pizza."}, {"name": "Zorba's Supreme Feast", "text": "A big plate."},
                                     {"name": "Pasta", "text": "Pasta dishes."}, {"name": "Breakfast", "text": "Morning food."},
                                     {"name": "Dine in", "text": "Eat here."}]), l)
    names = [s["name"] for s in c["services"]]
    assert "Pizza" in names and not any("Zorba" in n for n in names)
    ok = sc.clean_copy(good(services=[{"name": "Zorba's Supreme Feast", "text": "A big plate."}]), lead("restaurant", "Restaurant", "Olive Bar", summary="Try Zorba's Supreme Feast."))
    assert ok["services"][0]["name"] == "Zorba's Supreme Feast"
    t = sc.clean_copy(good(services=[{"name": "Roof Repair", "text": "x leaks."}, {"name": "Titan Shield System", "text": "Premium roofing."}] + good()["services"][:3]), lead())
    names = [s["name"] for s in t["services"]]
    assert "Roof Repair" in names and "Titan Shield System" not in names


def test_titles_follow_category():
    c = sc.clean_copy(good(gallery_title="A look inside", services_title="On the menu"), lead())
    assert c["gallery_title"] == "Recent work" and c["services_title"] == "What we do"
    f = sc.clean_copy(good(services_title="On the menu"), lead("cafe", "Cafe", "Bean"))
    assert f["services_title"] == "What we serve"


def test_area_from_address_only():
    assert sc.clean_copy(good(area="Windsor, Essex, Tecumseh"), lead())["area"] == "Leamington and nearby"
    l = lead()
    l["address"] = ""
    assert "area" not in sc.clean_copy(good(), l)


def test_write_copy_good_retry_unavailable():
    f = Fake(good())
    c = run(sc.write_copy(f, lead(), "rivals use big photos"))
    assert c["headline"] == "Roofing help in Leamington" and len(f.prompts) == 1 and "rivals use big photos" in f.prompts[0]
    f = Fake(None, good())
    assert run(sc.write_copy(f, lead()))["headline"] == "Roofing help in Leamington" and len(f.prompts) == 2 and "ONLY the complete JSON" in f.prompts[1]
    f = Fake({"headline": "Roofing help in Leamington"}, good(headline="Roof care in Leamington"))
    assert run(sc.write_copy(f, lead()))["headline"] == "Roof care in Leamington"
    assert run(sc.write_copy(Fake(LLMUnavailable("down")), lead())) == sc.fallback_copy(lead())
    f = Fake(None, None)
    assert run(sc.write_copy(f, lead())) == sc.fallback_copy(lead()) and len(f.prompts) == 2
    assert run(sc.write_copy(Fake(RuntimeError("boom"), ValueError("x")), lead())) == sc.fallback_copy(lead())


BANNED = ("licensed", "insured", "certified", "guarantee", "award", "24/7", "family-owned", "since", "years", "best", "price", "warrant")


@pytest.mark.parametrize("t,label", [("roofing_contractor", "Roofing contractor"), ("restaurant", "Restaurant"), ("hair_salon", "Hair salon"), ("dentist", "Dentist")])
def test_prompt_budget_and_facts(t, label):
    l = lead(t, label, "Hartley & Co", summary="A neat little place.")
    p = sc.copy_prompt(l, "rival tip")
    head = p.split("DATA:")[0]
    assert len(head) < 1800, len(head)
    assert "Hartley & Co" in p and "Leamington" in p and "4.8" in p and "120" in p and "A neat little place." in p and "Mon 8:00 AM" in p
    assert "fixed our leak" in p and "rival tip" in p
    assert not [w for w in BANNED if w in head.lower()], [w for w in BANNED if w in head.lower()]
    assert ("A look inside" not in head)


def test_brief_prompt():
    p = sc.brief_prompt(lead(), ["luxe", "trade"], {"luxe": "dark, elegant, gold accents for premium services", "trade": "bold and practical"})
    assert "- luxe: dark, elegant" in p and "- trade: bold" in p and "4 short searches" in p and "pastel" in p and "Hartley Roofing" in p
