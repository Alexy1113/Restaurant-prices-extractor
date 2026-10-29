"""Shared Russian category labels used by all restaurant parsers.

The original website section remains available in category_et. category_ru is the
stable, cross-restaurant category displayed and filtered in the application.
"""
import re


CATEGORY_RU_BY_PRODUCT_TYPE = {
    "main_courses": "Основные блюда",
    "bowls": "Боулы",
    "burgers": "Бургеры",
    "tortillas": "Тортильи",
    "breakfast": "Завтраки",
    "salads": "Салаты",
    "appetizers": "Закуски",
    "sides": "Гарниры",
    "sauces": "Соусы",
    "drinks": "Напитки",
    "desserts": "Десерты",
    "sushi_rolls": "Роллы",
    "hosomaki": "Роллы",
    "nigiri": "Нигири",
    "sashimi": "Сашими",
    "gunkan": "Гунканы",
    "sets": "Сеты",
    "inari": "Инари",
    "soups": "Супы",
    "noodles": "Лапша",
    "dumplings": "Пельмени и дим-сам",
    "syrups": "Сиропы",
    "ice_cream_shakes": "Напитки",
    "campaigns": "Акции",
    "other": "Другое",
}

_ALCOHOL_RE = re.compile(
    r"(?:18\s*\+|вино|вин[ао]|шампан|игрист|слабоалког|алкогол|"
    r"wine|champagne|sparkling|beer|bier|õlu|vein|vahuvein|siider|cider|"
    r"vodka|whisk(?:y|ey)|rum|tequila|prosecco|moscato|pinot|sinebrychoff|"
    r"somersby|saku|raasiku|maschio|gin tonic)",
    re.IGNORECASE,
)
_SUSHI_CATEGORY_RE = re.compile(r"\b(?:суши|sushi)\b", re.IGNORECASE)
_ROLL_RE = re.compile(
    r"(?:\brolls?\b|\brull\w*|\bmaki\b|\bhosomaki\b|"
    r"\buramaki\b|\bfutomaki\b|ролл|\bмаки\b|хосомаки)",
    re.IGNORECASE,
)


def canonical_category_ru(
    product_type,
    category_ru=None,
    category_et=None,
    dish_name=None,
):
    """Return the common Russian display category without losing useful exceptions."""
    product_type = str(product_type or "other").strip().casefold()
    russian_category = " ".join(str(category_ru or "").split()).strip()
    estonian_category = " ".join(str(category_et or "").split()).strip()
    dish_name = " ".join(str(dish_name or "").split()).strip()
    source_categories = f"{russian_category} {estonian_category}"
    source_text = f"{source_categories} {dish_name}"

    # Preserve the 18+ distinction while merging wine/champagne/low-alcohol
    # subcategories into one clear label.
    if product_type in {"drinks", "ice_cream_shakes"}:
        if _ALCOHOL_RE.search(source_categories):
            return "Алкогольные напитки (18+)"
        return "Напитки"

    # Some menus put tempura rolls under a broad "Sushi" section, while
    # standalone tempura remains a distinct food type.
    if product_type == "tempura":
        if _SUSHI_CATEGORY_RE.search(source_categories) or _ROLL_RE.search(source_text):
            return "Роллы"
        return "Темпура"

    # "Запечённые" is a meaningful source category, but its rows currently have
    # product_type="other"; retain it until names can be audited individually.
    if product_type == "other":
        if russian_category and russian_category.casefold() not in {
            "другое", "other", "без категории"
        }:
            return russian_category
        return "Другое"

    return CATEGORY_RU_BY_PRODUCT_TYPE.get(
        product_type,
        russian_category or "Другое",
    )
