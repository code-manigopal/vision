"""Which style a demo gets, and why (vision/masters/site_style.py)."""
from vision.masters.site_style import MOODS, TRAITS, choose, palette_moods, rank, signals
from vision.masters.sitekit import CLASSIC, RECIPES, recipes_for, styles_for


def lead(type_, name="Acme", summary="", reviews=()):
    return {"id": name, "name": name, "type": type_, "type_label": type_, "info": {"summary": summary, "reviews": [{"text": r} for r in reviews]}}


def test_every_style_has_traits_and_palette_moods():
    assert set(TRAITS) == set(RECIPES) | {CLASSIC} == set(MOODS)


def test_no_signals_gives_the_usual_fit_and_says_so():
    c = choose(lead("plumber"))
    assert c["style"] == recipes_for("plumber")[0] and "usual fit" in c["why"] and set(c["ranked"]) == set(styles_for("plumber"))


def test_what_customers_say_decides_the_style():
    cozy = choose(lead("cafe", "Corner Spot", reviews=["So cozy and friendly, the homemade pie is the best", "Feels like family"]))
    assert cozy["style"] == "artisan" and "cozy" in cozy["why"] and "warm" in cozy["why"]
    posh = choose(lead("beauty_salon", "Glow", "An elegant, upscale salon", ["Luxurious and beautiful space, I felt pampered"]))
    assert posh["style"] in ("atelier", "noir") and "refined" in posh["why"]
    # the same kind of business, different character -> a different style
    quick = choose(lead("cafe", "Grab and Go", reviews=["Quick and modern, sleek new place"]))
    assert quick["style"] != cozy["style"]


def test_plain_practical_business_gets_the_classic_page_on_merit():
    c = choose(lead("locksmith", "Lakeside Lock", reviews=["Reliable and honest, fair price", "Showed up on time, affordable"]))
    assert c["style"] == CLASSIC and "practical" in c["why"]
    assert choose(lead("locksmith", "Lakeside Lock"))["style"] != CLASSIC      # with nothing to go on, it is not a default


def test_dark_styles_need_a_reason():
    day = rank(lead("cafe", "Sunny Side", reviews=["Bright, friendly, great for kids"]))
    dark = [r for r in day if "dark" in TRAITS[r["style"]]]
    assert all(r["score"] < day[0]["score"] for r in dark) and "dark" not in TRAITS[day[0]["style"]]
    evening = choose(lead("restaurant", "The Lounge Bar", reviews=["Lovely cocktail bar for an evening out, moody and candlelit"]))
    assert "dark" in TRAITS[evening["style"]]


def test_name_cues_count():
    s = signals(lead("hair_care", "Head First Barbershop"))
    assert "dark" in s and s["dark"][1] == ["its name"]
    assert "playful" in signals(lead("child_care_agency", "Little Sprouts Kids Club"))


def test_model_pick_is_one_signal_not_the_decider():
    fits = recipes_for("plumber")
    assert choose(lead("plumber"), fits[2])["style"] == fits[2] and "model suggested" in choose(lead("plumber"), fits[2])["why"]   # nothing else to go on
    strong = lead("plumber", "Rapid Rooter", reviews=["Fast emergency call out, came right away, same day"])
    assert choose(strong, "swiss")["style"] in ("foreman", "forge")                                            # the evidence outweighs it
    assert choose(lead("plumber"), "chalkboard")["style"] == fits[0]                                           # an unsuitable pick is ignored


def test_no_two_demos_alike_and_the_reason_says_when_that_changed_the_choice():
    l = lead("cafe", "Corner Spot", reviews=["So cozy and friendly, homemade everything"])
    first = choose(l)
    second = choose(l, None, {first["style"]})
    assert second["style"] != first["style"] and first["style"] in second["why"] and "already used" in second["why"]
    assert choose(l, None, set(styles_for("cafe")))["style"] == first["style"]                                 # everything taken: best match anyway
    assert choose(l) == choose(l)                                                                              # same business, same answer


def test_palette_follows_the_style():
    assert palette_moods("artisan", [])[:2] == ["warm", "earth"] and "dark" in palette_moods("noir")
    assert palette_moods("artisan", ["vintage", "gold", "neon"]) == ["warm", "earth", "coffee", "cream", "vintage", "gold"]   # the model adds at most two
    assert palette_moods(CLASSIC, []) == []                                                                    # classic keeps the business type's own palettes
    from vision.masters.web import pick_theme
    warm = pick_theme({"id": "a", "type": "cafe"}, palette_moods("artisan"))
    cold = pick_theme({"id": "a", "type": "cafe"}, palette_moods("clinic"))
    assert warm["palette"] != cold["palette"]
