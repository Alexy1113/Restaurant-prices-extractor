"""Single source of truth for restaurant category labels and normalization."""

from __future__ import annotations

import json
import re
import unicodedata
from importlib.resources import files
from typing import Any


_REGISTRY = json.loads(
    files(__package__).joinpath("categories.json").read_text(encoding="utf-8")
)
CATEGORIES: dict[str, dict[str, Any]] = _REGISTRY["categories"]
PRODUCT_TYPE_ALIASES: dict[str, str] = {
    str(key).casefold(): str(value).casefold()
    for key, value in _REGISTRY.get("product_type_aliases", {}).items()
}
DRINK_PRODUCT_TYPES = {
    "drinks", "ice_cream_shakes", "hot_drinks", "hotdrinks",
    "cocktails", "cocktail", "alcoholic_drinks", "alcoholicdrinks",
}
_ALCOHOL_RE = re.compile(
    r"(?:18\s*\+|\b(?:вино|вин[ао]|шампан\w*|игрист\w*|слабоалког\w*|алкогол\w*|"
    r"wine|champagne|sparkling|beer|bier|õlu|vein\w*|vahuvein\w*|siider|cider|"
    r"vodka|whisk(?:y|ey)|rum|tequila|prosecco|moscato|pinot|sinebrychoff|"
    r"somersby|saku|raasiku|maschio|gin tonic)\b|\bgin\b)",
    re.IGNORECASE,
)
_SUSHI_CATEGORY_RE = re.compile(r"\b(?:суши|sushi)\b", re.IGNORECASE)
_ROLL_RE = re.compile(
    r"(?:\brolls?\b|\brull\w*|\bmaki\b|\bhosomaki\b|"
    r"\buramaki\b|\bfutomaki\b|ролл|\bмаки\b|хосомаки)",
    re.IGNORECASE,
)

_HOT_DOG_RE = re.compile(
    r"(?:\bhot[\s-]?dog\w*\b|\bхот[\s-]?дог\w*)",
    re.IGNORECASE,
)
_HOT_DOG_WRAP_RE = re.compile(
    r"(?:\b(?:lavash|lavas|wrap|tortilla)\b|лаваш|врап|тортиль)",
    re.IGNORECASE,
)
_DRINK_LIKE_RE = re.compile(
    r"(?:"
    r"\b(?:drink|drinks|beverage|beverages|coffee|espresso|cappuccino|"
    r"latte|tea|lemonade|cocktail|milkshake|shake|soda|cola|fanta|sprite|"
    r"beer|bier|wine|vodka|whisky|whiskey|rum|gin|prosecco|hot drinks?)\b|"
    r"\b(?:joog\w*|jook|kohv\w*|tee|limonaad\w*|kokteil\w*|"
    r"alkohol\w*|alcohol\w*|õlu|vein\w*|vahuvein\w*|siider|cider)\b|"
    r"\b(?:напит\w*|горяч\w* напит\w*|коктейл\w*|алкогол\w*|"
    r"пив\w*|вин\w*|ча\w*|кофе|сок\w*|молочн\w* коктейл\w*)\b|"
    r"jäätisekokteil|milk shake"
    r")",
    re.IGNORECASE,
)
_GENERIC_RU = {"", "другое", "другие", "other", "без категории"}
_GENERIC_ET = {"", "muu", "muud", "other", "другое", "без категории"}


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.split()).strip()


def _build_alias_index() -> dict[str, str]:
    result: dict[str, str] = {}
    for key, data in CATEGORIES.items():
        result[_fold(key)] = key
        result[_fold(data["ru"])] = key
        result[_fold(data["et"])] = key
        for language in ("ru", "et"):
            for alias in data.get("aliases", {}).get(language, []):
                result[_fold(alias)] = key
    for product_type in set(CATEGORIES) | set(PRODUCT_TYPE_ALIASES):
        result[_fold(product_type)] = PRODUCT_TYPE_ALIASES.get(product_type, product_type)
    return result


_ALIAS_TO_CATEGORY = _build_alias_index()


def category_label(category_key: str | None, language: str = "Русский") -> str:
    """Return the canonical localized label for a category key."""
    key = str(category_key or "other").casefold()
    data = CATEGORIES.get(key, CATEGORIES["other"])
    lang = _REGISTRY.get("languages", {}).get(language, "ru")
    return str(data.get(lang, data["ru"]))


def category_key_for_product_type(product_type: str | None) -> str | None:
    """Resolve a parser product_type to its public category key."""
    value = str(product_type or "").strip().casefold()
    if not value or value == "other":
        # "other" is deliberately contextual: preserve informative source
        # headings instead of overriding them with the generic fallback.
        return None
    key = PRODUCT_TYPE_ALIASES.get(value, value)
    return key if key in CATEGORIES else None


def _is_alcoholic(text: str) -> bool:
    return bool(_ALCOHOL_RE.search(text))


def _is_drink_like(text: str) -> bool:
    return bool(_DRINK_LIKE_RE.search(text))


def resolve_category_key(
    product_type: str | None,
    category_ru: str | None = None,
    category_et: str | None = None,
    dish_name: str | None = None,
) -> str | None:
    """Resolve parser/source fields to one canonical category key.

    Food and beverage distinctions are intentional: alcoholic drinks remain
    separate from ordinary drinks, and sushi subtypes such as nigiri, sashimi
    and gunkan are not merged into the rolls category.
    """
    product = str(product_type or "other").strip().casefold()
    ru = " ".join(str(category_ru or "").split()).strip()
    et = " ".join(str(category_et or "").split()).strip()
    name = " ".join(str(dish_name or "").split()).strip()
    source_categories = f"{ru} {et}"
    source_text = f"{source_categories} {name}"

    if product in {"alcoholic_drinks", "alcoholicdrinks"}:
        return "alcoholic_drinks"

    is_drink = product in DRINK_PRODUCT_TYPES or (
        product == "other" and _is_drink_like(source_categories)
    )
    if is_drink:
        return "alcoholic_drinks" if _is_alcoholic(source_text) else "drinks"

    # Pasta/noodle source sections are intentionally one public category.
    if product in {"noodles", "pasta"} or re.search(
        r"(?:лапш\w*|паст\w*|nuudl\w*|pastad|\bpasta\b)",
        _fold(source_categories),
    ):
        return "noodles_pasta"

    # Tempura preparation is merged into rolls only when the menu or name
    # explicitly identifies it as a sushi/roll product.
    if product == "tempura":
        return (
            "sushi_rolls"
            if _SUSHI_CATEGORY_RE.search(source_categories)
            or _ROLL_RE.search(source_text)
            else "tempura"
        )

    # An explicit hot_dogs parser classification is authoritative, including
    # products served in lavash/wraps (for example, Break Time hot dogs).
    if product == "hot_dogs":
        return "hot_dogs"

    # Recognize hot dogs from legacy/generic source data when the parser did
    # not supply the dedicated product type. Other restaurants may still
    # classify a hot dog wrap as a tortilla.
    if product not in {"sets", "tortillas", "breakfast", "desserts", "pizzas"}:
        if _HOT_DOG_RE.search(source_text):
            if _HOT_DOG_WRAP_RE.search(name):
                return "tortillas"
            return "hot_dogs"

    key = category_key_for_product_type(product)
    if key:
        return key

    if product == "other":
        ru_key = _fold(ru)
        et_key = _fold(et)
        if ru_key not in _GENERIC_RU and ru_key in _ALIAS_TO_CATEGORY:
            return _ALIAS_TO_CATEGORY[ru_key]
        # Do not create a new ET category when the Russian category is generic.
        if ru_key in _GENERIC_RU:
            return None
        if et_key in _ALIAS_TO_CATEGORY:
            return _ALIAS_TO_CATEGORY[et_key]
    return None


def canonical_category_ru(
    product_type: str | None,
    category_ru: str | None = None,
    category_et: str | None = None,
    dish_name: str | None = None,
) -> str:
    """Return a canonical Russian category label, retaining unknown source labels."""
    key = resolve_category_key(product_type, category_ru, category_et, dish_name)
    if key:
        return category_label(key, "Русский")
    ru = " ".join(str(category_ru or "").split()).strip()
    if str(product_type or "").strip().casefold() == "other" and ru.casefold() not in _GENERIC_RU:
        return ru
    return ru or category_label("other", "Русский")


def canonical_category_et(
    product_type: str | None,
    category_ru: str | None = None,
    category_et: str | None = None,
    dish_name: str | None = None,
) -> str:
    """Return the canonical Estonian category label or preserve an unknown source label."""
    key = resolve_category_key(product_type, category_ru, category_et, dish_name)
    if key:
        return category_label(key, "Eesti")
    ru_key = _fold(category_ru)
    et = " ".join(str(category_et or "").split()).strip()
    if str(product_type or "").strip().casefold() == "other" and ru_key in _GENERIC_RU:
        return category_label("other", "Eesti")
    if et and _fold(et) not in _GENERIC_ET:
        return et
    return category_label("other", "Eesti")


def get_category_emoji(*values: Any) -> str:
    """Resolve an emoji from product types, canonical labels, or legacy aliases."""
    keys = []
    for value in values:
        folded = _fold(value)
        if folded in _ALIAS_TO_CATEGORY:
            keys.append(_ALIAS_TO_CATEGORY[folded])
    if "alcoholic_drinks" in keys:
        return str(CATEGORIES["alcoholic_drinks"]["emoji"])
    for key in keys:
        return str(CATEGORIES[key].get("emoji", "🍽️"))
    return "🍽️"


def category_label_for_product_type(product_type: str | None, language: str = "Русский") -> str:
    key = category_key_for_product_type(product_type)
    return category_label(key, language)


# Compatibility maps are generated from this registry, never maintained separately.
CATEGORY_RU_BY_PRODUCT_TYPE = {
    product_type: category_label(category_key_for_product_type(product_type), "Русский")
    for product_type in sorted(set(CATEGORIES) | set(PRODUCT_TYPE_ALIASES))
}
CATEGORY_ET_BY_PRODUCT_TYPE = {
    product_type: category_label(category_key_for_product_type(product_type), "Eesti")
    for product_type in sorted(set(CATEGORIES) | set(PRODUCT_TYPE_ALIASES))
}
CATEGORY_ET_BY_RUSSIAN_CATEGORY = {
    _fold(CATEGORIES[key]["ru"]): CATEGORIES[key]["et"]
    for key in CATEGORIES
}
for _key, _definition in CATEGORIES.items():
    for _alias in _definition.get("aliases", {}).get("ru", []):
        CATEGORY_ET_BY_RUSSIAN_CATEGORY[_fold(_alias)] = _definition["et"]


__all__ = [
    "CATEGORIES",
    "PRODUCT_TYPE_ALIASES",
    "CATEGORY_RU_BY_PRODUCT_TYPE",
    "CATEGORY_ET_BY_PRODUCT_TYPE",
    "CATEGORY_ET_BY_RUSSIAN_CATEGORY",
    "category_label",
    "category_key_for_product_type",
    "category_label_for_product_type",
    "resolve_category_key",
    "canonical_category_ru",
    "canonical_category_et",
    "get_category_emoji",
]
