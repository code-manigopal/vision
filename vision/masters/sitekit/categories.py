"""Business categories: Google Places type -> category, the section order and neutral wording that fit it,
and which recipes suit it (best first).

Wording is UI text only (headings, labels). It never claims anything about the business, and since demo photos
are stock, gallery headings do not call them the business's own work.
"""

from __future__ import annotations

CATEGORY_OF = {
    # trade: people who come to you
    "plumber": "trade", "electrician": "trade", "roofing_contractor": "trade", "painter": "trade", "locksmith": "trade",
    "car_repair": "trade", "moving_company": "trade", "car_wash": "trade", "general_contractor": "trade", "hvac_contractor": "trade",
    "storage": "trade", "laundry": "trade",
    # food
    "restaurant": "food", "cafe": "food", "bakery": "food", "meal_takeaway": "food", "meal_delivery": "food", "bar": "food",
    "coffee_shop": "food", "ice_cream_shop": "food",
    # beauty
    "beauty_salon": "beauty", "hair_care": "beauty", "hair_salon": "beauty", "nail_salon": "beauty", "spa": "beauty", "barber_shop": "beauty",
    "tailor": "beauty",
    # health
    "dentist": "health", "physiotherapist": "health", "veterinary_care": "health", "gym": "health", "doctor": "health", "pharmacy": "health",
    # retail
    "florist": "retail", "pet_store": "retail", "gift_shop": "retail", "jewelry_store": "retail", "clothing_store": "retail",
    "furniture_store": "retail", "hardware_store": "retail", "bicycle_store": "retail", "book_store": "retail", "store": "retail",
    # care
    "child_care_agency": "care", "funeral_home": "care",
    # stay
    "bed_and_breakfast": "stay", "lodging": "stay", "travel_agency": "stay",
    # professional services
    "real_estate_agency": "pro", "insurance_agency": "pro", "accounting": "pro", "lawyer": "pro",
}
CATEGORIES = ["trade", "food", "beauty", "health", "retail", "care", "stay", "pro", "other"]


def category_of(lead_type) -> str:
    return CATEGORY_OF.get(str(lead_type or "").strip().lower(), "other")


# section order by category ("hero" is always first, the footer always last)
ORDER = {
    "trade": ["highlights", "services", "steps", "area", "gallery", "about", "reviews", "faq", "cta", "visit"],
    "food": ["highlights", "gallery", "services", "visit", "about", "reviews", "faq", "area", "steps", "cta"],
    "beauty": ["about", "highlights", "services", "gallery", "reviews", "steps", "faq", "area", "cta", "visit"],
    "health": ["highlights", "services", "about", "steps", "reviews", "gallery", "faq", "area", "cta", "visit"],
    "retail": ["highlights", "gallery", "services", "about", "reviews", "steps", "faq", "area", "cta", "visit"],
    "care": ["highlights", "about", "services", "steps", "reviews", "gallery", "faq", "area", "cta", "visit"],
    "stay": ["gallery", "about", "services", "highlights", "reviews", "steps", "faq", "area", "cta", "visit"],
    "pro": ["highlights", "services", "about", "steps", "reviews", "faq", "area", "gallery", "cta", "visit"],
    "other": ["highlights", "services", "about", "gallery", "reviews", "steps", "faq", "area", "cta", "visit"],
}

_BASE = {
    "services_eyebrow": "Services", "services_title": "What we do",
    "gallery_eyebrow": "Gallery", "gallery_title": "A closer look",
    "about_eyebrow": "About",
    "reviews_eyebrow": "Reviews", "reviews_title": "What customers say",
    "visit_eyebrow": "Visit", "visit_title": "Come and see us", "where_label": "Address",
    "steps_eyebrow": "How it works", "steps_title": "What to expect",
    "faq_eyebrow": "Questions", "faq_title": "Good to know",
    "area_eyebrow": "Service area", "area_prefix": "Serving",
    "nav": {"services": "Services", "about": "About", "gallery": "Gallery", "reviews": "Reviews", "visit": "Visit"},
}


def _w(nav: dict | None = None, **kw) -> dict:
    return {**_BASE, **kw, "nav": {**_BASE["nav"], **(nav or {})}}


WORDS = {
    "trade": _w({"visit": "Contact"}, gallery_eyebrow="On the job", gallery_title="The kind of work we do",
                visit_eyebrow="Contact", visit_title="Get in touch", where_label="Reach us",
                steps_title="From first call to finished job"),
    "food": _w({"services": "Menu", "gallery": "Photos", "visit": "Hours & location"}, services_eyebrow="Food & drink", services_title="What we serve",
               gallery_eyebrow="Photos", gallery_title="On the table", reviews_title="What guests say",
               visit_eyebrow="Hours & location", visit_title="Find us", area_eyebrow="Where we serve", steps_eyebrow="How to order"),
    "beauty": _w(services_title="Treatments and services", gallery_title="The look and feel", reviews_title="What clients say",
                 visit_title="Come and see us", steps_eyebrow="Your visit"),
    "health": _w(services_title="How we can help", reviews_title="What people say", visit_title="Find us", steps_eyebrow="Your visit"),
    "retail": _w({"services": "In store", "visit": "Visit"}, services_eyebrow="In store", services_title="What you will find",
                 gallery_title="A look around", visit_title="Visit the shop"),
    "care": _w(services_title="What we offer", reviews_title="What families say", gallery_title="A look around", visit_title="Find us"),
    "stay": _w({"services": "Your stay"}, services_eyebrow="Your stay", services_title="What to expect here", gallery_title="A look around",
               reviews_title="What guests say", visit_title="Find us", steps_title="Planning your stay"),
    "pro": _w({"visit": "Contact"}, services_title="How we can help", reviews_title="What clients say",
              visit_eyebrow="Contact", visit_title="Get in touch", where_label="Reach us", steps_title="Working with us"),
    "other": _w(),
}

# recipes that suit each category, best first (at least four each, so a batch of sites can all differ)
_BY_CATEGORY = {
    "trade": ["foreman", "forge", "swiss", "mainstreet", "clinic"],
    "food": ["artisan", "chalkboard", "gazette", "sprout", "noir", "harbour", "mainstreet", "parlour"],
    "beauty": ["atelier", "bloom", "noir", "gazette", "parlour"],
    "health": ["clinic", "bloom", "swiss", "mainstreet", "harbour"],
    "retail": ["harbour", "artisan", "mainstreet", "gazette", "sprout", "atelier", "parlour"],
    "care": ["sprout", "clinic", "bloom", "mainstreet", "harbour"],
    "stay": ["harbour", "gazette", "atelier", "noir", "artisan"],
    "pro": ["swiss", "clinic", "mainstreet", "gazette", "harbour"],
    "other": ["mainstreet", "swiss", "clinic", "harbour", "foreman"],
}
# a type's own favourites go in front of its category's list
_BY_TYPE = {
    "car_repair": ["forge", "foreman"], "locksmith": ["forge", "foreman"], "roofing_contractor": ["foreman", "forge"],
    "barber_shop": ["parlour", "noir"], "jewelry_store": ["atelier", "noir"], "spa": ["bloom", "atelier"],
    "nail_salon": ["atelier", "bloom"], "hair_care": ["gazette", "atelier"], "restaurant": ["gazette", "noir", "chalkboard"],
    "meal_takeaway": ["chalkboard", "sprout"], "bakery": ["artisan", "sprout"], "cafe": ["artisan", "chalkboard"],
    "florist": ["artisan", "bloom"], "pet_store": ["sprout", "mainstreet"], "gift_shop": ["artisan", "harbour"],
    "child_care_agency": ["sprout", "clinic"], "funeral_home": ["harbour", "atelier", "mainstreet", "gazette"],
    "gym": ["forge", "swiss"], "dentist": ["clinic", "swiss"], "veterinary_care": ["clinic", "sprout"],
    "lawyer": ["gazette", "swiss"], "bed_and_breakfast": ["harbour", "gazette"],
}


def recipes_for(lead_type) -> list:
    """Recipe names that suit this Google Places type, best first (always at least four)."""
    t = str(lead_type or "").strip().lower()
    names = list(_BY_TYPE.get(t, []))
    if t == "funeral_home":
        return names
    return names + [n for n in _BY_CATEGORY[category_of(t)] if n not in names]
