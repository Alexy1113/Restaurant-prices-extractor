"""Shared canonical category labels in Russian and Estonian.

Both category_ru and category_et use this app taxonomy, not the site's raw
section headings, so different source-language sections stay grouped together.
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


# Shared Estonian labels corresponding to the canonical Russian categories.
# category_et stores this app taxonomy, not the menu's original section heading.
CATEGORY_ET_BY_PRODUCT_TYPE = {
    "main_courses": "Põhiroad",
    "bowls": "Bowls",
    "burgers": "Burgerid",
    "tortillas": "Tortillad",
    "breakfast": "Hommikusöögid",
    "salads": "Salatid",
    "appetizers": "Eelroad",
    "sides": "Lisandid",
    "sauces": "Kastmed",
    "drinks": "Joogid",
    "desserts": "Magustoidud",
    "sushi_rolls": "Maki",
    "hosomaki": "Maki",
    "nigiri": "Nigiri",
    "sashimi": "Sashimi",
    "gunkan": "Gunkanid",
    "sets": "Komplektid",
    "inari": "Inari",
    "soups": "Supid",
    "noodles": "Nuudlid",
    "dumplings": "Pelmeenid ja dim sum",
    "syrups": "Siirupid",
    "ice_cream_shakes": "Joogid",
    "campaigns": "Kampaaniad",
}

CATEGORY_ET_BY_RUSSIAN_CATEGORY = {
    "основные блюда": "Põhiroad",
    "боулы": "Bowls",
    "бургеры": "Burgerid",
    "тортильи": "Tortillad",
    "завтраки": "Hommikusöögid",
    "салаты": "Salatid",
    "закуски": "Eelroad",
    "гарниры": "Lisandid",
    "соусы": "Kastmed",
    "напитки": "Joogid",
    "алкогольные напитки (18+)": "Alkohoolsed joogid (18+)",
    "десерты": "Magustoidud",
    "роллы": "Maki",
    "нигири": "Nigiri",
    "сашими": "Sashimi",
    "гунканы": "Gunkanid",
    "сеты": "Komplektid",
    "инари": "Inari",
    "супы": "Supid",
    "лапша": "Nuudlid",
    "пельмени и дим-сам": "Pelmeenid ja dim sum",
    "сиропы": "Siirupid",
    "акции": "Kampaaniad",
    "темпура": "Tempura",
    "другое": "Muu",
    "без категории": "Muu",
}


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



def canonical_category_et(
    product_type,
    category_ru=None,
    category_et=None,
    dish_name=None,
):
    """Return the Estonian equivalent of the shared canonical category taxonomy."""
    product_type = str(product_type or "other").strip().casefold()
    russian_category = " ".join(str(category_ru or "").split()).strip()
    estonian_category = " ".join(str(category_et or "").split()).strip()
    dish_name = " ".join(str(dish_name or "").split()).strip()
    source_categories = f"{russian_category} {estonian_category}"
    source_text = f"{source_categories} {dish_name}"

    # Merge wine, champagne, beer and other alcoholic subcategories into one
    # Estonian label, matching the Russian "Алкогольные напитки (18+)" group.
    if product_type in {"drinks", "ice_cream_shakes"}:
        if _ALCOHOL_RE.search(source_categories):
            return "Alkohoolsed joogid (18+)"
        return "Joogid"

    # Tempura remains distinct unless the menu/name identifies a sushi roll.
    if product_type == "tempura":
        if _SUSHI_CATEGORY_RE.search(source_categories) or _ROLL_RE.search(source_text):
            return "Maki"
        return "Tempura"

    mapped = CATEGORY_ET_BY_PRODUCT_TYPE.get(product_type)
    if mapped:
        return mapped

    # Translate a specific Russian canonical category when product_type is unknown.
    russian_key = russian_category.casefold()
    mapped_from_ru = CATEGORY_ET_BY_RUSSIAN_CATEGORY.get(russian_key)
    generic_ru_categories = {"", "другое", "other", "без категории"}
    if mapped_from_ru and russian_key not in generic_ru_categories:
        return mapped_from_ru

    # If Russian classification is generic, keep both fields generic too.
    # Otherwise the ET source might create a separate category absent in RU.
    if product_type == "other" and russian_key in generic_ru_categories:
        return "Muu"

    # If classification is unknown, preserve an informative source category
    # rather than guessing. Known category types are normalized above.
    if estonian_category and estonian_category.casefold() not in {
        "muu", "other", "без категории", "другое"
    }:
        return estonian_category

    if mapped_from_ru:
        return mapped_from_ru
    return "Muu"
