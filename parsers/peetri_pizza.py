"""Parser for Peetri Pizza Jõhvi Bussijaam.

Only the pizzeria's pizza section is imported. Other menu sections (pasta,
drinks and combos) are intentionally not classified as pizzas.
"""
import re
import unicodedata

import requests
from bs4 import BeautifulSoup, Tag


RESTAURANT_NAME = "Peetri Pizza Jõhvi Bussijaam"
MENU_URL = "https://peetripizza.ee/pizzeria/johvi-bussijaam"
REQUEST_TIMEOUT = (8, 25)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "et-EE,et;q=0.9,en;q=0.8",
}

PIZZA_SECTION_NAMES = {"pizza", "pizzad", "pitsad", "pizzas"}
IGNORED_TITLES = PIZZA_SECTION_NAMES | {
    "pastad", "pasta", "joogid", "drinks", "kombod", "kombo",
    "menüü", "menu", "lisandid", "additions",
}

PRICE_RE = re.compile(
    r"(?:(?:alates|al)\s*\.?\s*)?"
    r"(?P<before>\d+(?:[.,]\d{1,2})?)\s*€"
    r"|€\s*(?P<after>\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)

CARD_SELECTORS = (
    "[data-product-id]", "[data-product]", ".product-card",
    ".product-item", ".pizza-card", ".menu-item", ".product",
    "article", "li",
)
TITLE_SELECTORS = (
    "h2, h3, h4, h5, h6",
    ".product-title, .product-name, .menu-item-title, [itemprop='name']",
)
DESCRIPTION_SELECTORS = (
    ".product-description", ".description", ".ingredients",
    "[itemprop='description']",
)


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def normalize_text(value):
    text = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")
    return slug or "unknown"


def parse_price(value):
    """Convert a displayed or data-attribute price into a float."""
    if value is None:
        return None
    match = PRICE_RE.search(str(value))
    if match:
        number = match.group("before") or match.group("after")
    else:
        number_match = re.search(r"\d+(?:[.,]\d{1,2})?", str(value))
        number = number_match.group(0) if number_match else None
    if not number:
        return None
    try:
        return round(float(number.replace(",", ".")), 2)
    except ValueError:
        return None


def get_product_type(category, name=None):
    """Return the shared category code for Peetri Pizza's pizza section."""
    category_key = normalize_text(category)
    if (
        category_key in PIZZA_SECTION_NAMES
        or category_key == "пицца"
        or "pitsa" in category_key
        or "pizza" in category_key
    ):
        return "pizzas"
    return "other"


def _title_nodes(card):
    found = []
    seen = set()
    for selector in TITLE_SELECTORS:
        for node in card.select(selector):
            title = clean_text(node.get_text(" ", strip=True))
            key = title.casefold()
            if title and key not in seen:
                found.append(node)
                seen.add(key)
    return found


def get_card_name(card):
    for node in _title_nodes(card):
        name = clean_text(node.get_text(" ", strip=True))
        if normalize_text(name) not in IGNORED_TITLES:
            return name

    for selector in (".title", ".name", "strong"):
        node = card.select_one(selector)
        if node:
            name = clean_text(node.get_text(" ", strip=True))
            if name and normalize_text(name) not in IGNORED_TITLES:
                return name
    return None


def get_card_description(card):
    for selector in DESCRIPTION_SELECTORS:
        node = card.select_one(selector)
        if node:
            value = clean_text(node.get_text(" ", strip=True))
            if value:
                return value

    for node in card.select("p"):
        value = clean_text(node.get_text(" ", strip=True))
        if value and not PRICE_RE.search(value) and len(value) > 5:
            return value
    return None


def _has_price(card):
    return PRICE_RE.search(card.get_text(" ", strip=True)) is not None or bool(
        card.select_one("[data-price], [itemprop='price']")
    )


def _candidate_card_elements(container):
    # A combined CSS selector preserves the order in which products appear in
    # the menu. Querying one selector at a time can reorder product cards.
    candidates = []
    for element in container.select(", ".join(CARD_SELECTORS)):
        if not get_card_name(element) or not _has_price(element):
            continue

        names = {
            clean_text(node.get_text(" ", strip=True)).casefold()
            for node in _title_nodes(element)
            if normalize_text(node.get_text(" ", strip=True)) not in IGNORED_TITLES
        }
        if len(names) > 1:
            continue
        candidates.append(element)

    # Drop outer wrappers when they contain a more specific candidate card,
    # while preserving the document order of the remaining product elements.
    candidate_ids = {id(element) for element in candidates}
    return [
        element
        for element in candidates
        if not any(
            id(descendant) in candidate_ids
            for descendant in element.find_all(True)
        )
    ]


def _find_pizza_section(soup):
    headings = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if normalize_text(node.get_text(" ", strip=True)) in PIZZA_SECTION_NAMES:
            headings.append(node)

    if not headings:
        for node in soup.find_all(["div", "span"]):
            classes = " ".join(node.get("class", []))
            if not any(
                word in classes.casefold()
                for word in ("category", "section", "heading", "title")
            ):
                continue
            if normalize_text(node.get_text(" ", strip=True)) in PIZZA_SECTION_NAMES:
                headings.append(node)

    for heading in headings:
        for ancestor in heading.parents:
            if not isinstance(ancestor, Tag) or ancestor.name in {"body", "html"}:
                break
            if _candidate_card_elements(ancestor):
                return ancestor
    return None


def _find_cards_from_headings(container):
    """Fallback for pages whose product cards have no recognizable CSS class."""
    cards = []
    seen = set()
    for heading in container.find_all(["h2", "h3", "h4", "h5", "h6"]):
        name = clean_text(heading.get_text(" ", strip=True))
        if not name or normalize_text(name) in IGNORED_TITLES:
            continue
        for ancestor in heading.parents:
            if ancestor is container.parent or ancestor is container or ancestor.name in {"body", "html"}:
                break
            names = {
                clean_text(node.get_text(" ", strip=True)).casefold()
                for node in _title_nodes(ancestor)
                if normalize_text(node.get_text(" ", strip=True)) not in IGNORED_TITLES
            }
            if len(names) == 1 and _has_price(ancestor):
                identity = (name.casefold(), id(ancestor))
                if identity not in seen:
                    cards.append(ancestor)
                    seen.add(identity)
                break
    return cards


def _variant_prices(card):
    """Read explicit size/variant prices when the page exposes them in HTML."""
    variants = []
    selectors = (
        "option[data-price]",
        "[data-price][data-variant]",
        "[data-price][data-size]",
        "[data-variant-price]",
    )
    for node in card.select(", ".join(selectors)):
        raw_price = node.get("data-price") or node.get("data-variant-price")
        price = parse_price(raw_price)
        if price is None:
            continue
        label = (
            node.get("data-variant")
            or node.get("data-size")
            or clean_text(node.get_text(" ", strip=True))
        )
        label = clean_text(label)
        if not label:
            continue
        if (label.casefold(), price) not in {
            (existing_label.casefold(), existing_price)
            for existing_label, existing_price in variants
        }:
            variants.append((label, price))
    return variants


def get_prices(card):
    variants = _variant_prices(card)
    if variants:
        return [(price, label) for label, price in variants]

    # Most product cards advertise a starting price, e.g. "al. 6.50 €".
    for selector in (
        ".price", ".product-price", ".product__price", "[itemprop='price']"
    ):
        node = card.select_one(selector)
        if node:
            price = parse_price(
                node.get("content")
                or node.get("data-price")
                or node.get_text(" ", strip=True)
            )
            if price is not None:
                return [(price, None)]

    match = PRICE_RE.search(card.get_text(" ", strip=True))
    if not match:
        return []
    price = parse_price(match.group(0))
    return [(price, None)] if price is not None else []


def get_stable_code(card, name, variant=None):
    source_id = (
        card.get("data-product-id")
        or card.get("data-id")
        or card.get("id")
    )
    base = f"id-{slugify(source_id)}" if source_id else slugify(name)
    if variant:
        base = f"{base}:{slugify(variant)}"
    return f"peetri-johvi:{base}"


def parse_html(html):
    """Parse only pizza records from a Peetri Pizza pizzeria page."""
    soup = BeautifulSoup(html or "", "html.parser")
    section = _find_pizza_section(soup)
    if section is None:
        return []

    cards = _candidate_card_elements(section)
    if not cards:
        cards = _find_cards_from_headings(section)

    parsed = []
    seen = set()
    for card in cards:
        name = get_card_name(card)
        if not name:
            continue
        description = get_card_description(card)
        for price, variant in get_prices(card):
            code = get_stable_code(card, name, variant)
            identity = (code, price, (variant or "").casefold())
            if identity in seen:
                continue
            seen.add(identity)
            parsed.append({
                "dish_code": code,
                "dish_name": name,
                "dish_name_et": name,
                "dish_name_ru": None,
                "description_et": description,
                "category_ru": "Пицца",
                "category_et": "Pitsad",
                "product_type": get_product_type("Pizzad", name),
                "price": price,
                "price_variant": variant,
            })
    return parsed


def parse_menu():
    response = requests.get(
        MENU_URL,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    dishes = parse_html(response.text)
    print(f"[Peetri Pizza/Jõhvi] HTTP {response.status_code}; URL: {response.url}; HTML: {len(response.text)} байт")
    print(f"[Peetri Pizza/Jõhvi] Получено пицц: {len(dishes)} из {MENU_URL}")
    if not dishes:
        soup = BeautifulSoup(response.text, "html.parser")
        page_title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        headings = [
            clean_text(node.get_text(" ", strip=True))
            for node in soup.find_all(["h1", "h2", "h3", "h4"])
        ]
        body_text = (
            clean_text(soup.body.get_text(" ", strip=True))[:2500]
            if soup.body else ""
        )
        script_sources = [
            node.get("src")
            for node in soup.find_all("script", src=True)
        ]
        root_nodes = [
            {
                "tag": node.name,
                "id": node.get("id"),
                "class": node.get("class"),
            }
            for node in (soup.body.find_all(recursive=False)[:20] if soup.body else [])
        ]
        html_lower = response.text.casefold()
        marker_contexts = {}
        for marker in ("pizzad", "pizza", "product", "graphql", "wp-json", "api", "react", "next"):
            position = html_lower.find(marker)
            if position >= 0:
                marker_contexts[marker] = response.text[max(0, position - 180):position + 420]
        print(f"[Peetri Pizza/Jõhvi][Диагностика] Заголовок страницы: {page_title!r}")
        print(f"[Peetri Pizza/Jõhvi][Диагностика] Заголовки: {headings[:40]!r}")
        print(f"[Peetri Pizza/Jõhvi][Диагностика] Текст страницы: {body_text!r}")
        print(f"[Peetri Pizza/Jõhvi][Диагностика] Script src: {script_sources[:50]!r}")
        print(f"[Peetri Pizza/Jõhvi][Диагностика] Body roots: {root_nodes!r}")
        print(f"[Peetri Pizza/Jõhvi][Диагностика] HTML marker contexts: {marker_contexts!r}")
        print(
            "[Peetri Pizza/Jõhvi] Не найдена секция Pizzad или в карточках "
            "не обнаружены названия и цены. Supabase не будет изменена."
        )
    return dishes
