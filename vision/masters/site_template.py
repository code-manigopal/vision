"""Demo-site template for the Web Designer. The page builder now lives in the sitekit package (section library +
recipes); this module keeps the old import path working.

render_site(lead, copy, theme, images, style) -> html. STYLES holds every accepted style name: the sitekit recipes
plus the four legacy names (luxe, sunny, trade, editorial). STYLE_BY_TYPE is the default recipe per business type.
"""

from __future__ import annotations

from .sitekit import CATEGORY_OF, RECIPES, STYLE_BY_TYPE, STYLES, category_of, city_of, recipes_for, render_site

__all__ = ["render_site", "city_of", "STYLES", "STYLE_BY_TYPE", "RECIPES", "CATEGORY_OF", "category_of", "recipes_for"]
