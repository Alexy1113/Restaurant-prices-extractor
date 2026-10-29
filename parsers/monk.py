"""Парсер меню Monk Jõhvi.

Считывает категории с русской версии сайта Monk, собирает цены из всех
разделов, приводит товары к уже используемым product_type и сохраняет
размеры/количество порций в price_variant (например, "8 tk", "0.5 l", "300 g").
"""

import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


MENU_BASE_URL = "https://monkrestoran.ee/ru/monk-johvi-2/"
BASE_PATH = "/ru/monk-johvi-2/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}

PRICE_RE = re.compile(
    r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)|"
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€"
)

# Amount + unit + price. Decimal prices are accepted without a repeated euro
# sign because menus often write "8tk 9.60, 12tk 11.60 €".
VARIANT_PRICE_RE = re.compile(
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>milliliitrit|milliliiter|milliliitri|"
    r"kilogrammi|kilogramm|grammi|gramm|"
    r"pieces?|piece|pcs?\.?|tk\.?|"
    r"штук(?:а|и)?|шт\.?|"
    r"литров|литра|литр|л\.?|"
    r"миллилитров|миллилитра|миллилитр|мл\.?|"
    r"килограммов|килограмма|килограмм|кг\.?|"
    r"граммов|грамма|грамм|г\.?|"
    r"ml|kg|g|l)"
    r"\s*(?:[:=,\-–]\s*)?(?:€\s*)?"
    r"(?P<price>\d{1,4}(?:[.,]\d{1,2})?)"
    r"\s*(?P<euro>€)?",
    re.IGNORECASE,
)

QUANTITY_RE = re.compile(
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>milliliitrit|milliliiter|milliliitri|"
    r"kilogrammi|kilogramm|grammi|gramm|"
    r"pieces?|piece|pcs?\.?|tk\.?|"
    r"штук(?:а|и)?|шт\.?|"
    r"литров|литра|литр|л\.?|"
    r"миллилитров|миллилитра|миллилитр|мл\.?|"
    r"килограммов|килограмма|килограмм|кг\.?|"
    r"граммов|грамма|грамм|г\.?|"
    r"ml|kg|g|l)(?=$|[^a-zа-я])",
    re.IGNORECASE,
)

# These links are used if the site's category navigation cannot be discovered.
# The live navigation is also read, so new sections (for example chicken dishes)
# are picked up automatically.
FALLBACK_CATEGORY_URLS = [
    "https://monkrestoran.ee/ru/monk-johvi-2/d181d183d188d0b8/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b7d0b0d0bad183d181d0bad0b8/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b1d0bbd18ed0b4d0b0-d0bdd0b0-d181d0bad0bed0b2d0bed180d0bed0b4d0b5/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b1d0bbd18ed0b4d0b0-d0bdd0b0-d181d0bad0bed0b2d0bed180d0b5/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d185d0bbd0b5d0b1/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b2d0b5d181d0b5d0bdd0bdd0b8d0b5-d180d183d0bbd0b5d182d18b-d0b8-d0b2d180d0b0d0bfd18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d181d0b0d0bbd0b0d182d18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d181d183d0bfd18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d183d182d0b8d0bdd18bd0b5-d0bad183d180d181d18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b1d0bbd18ed0b4d0b0-d0b8d0b7-d0b1d0b0d180d0b0d0bdd0b8d0bdd18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b3d0bed0b2d18fd0b4d0b8d0bdd0b0/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d180d18bd0b1d0b0-d0b8-d0bcd0bed180d0b5d0bfd180d0bed0b4d183d0bad182d18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b2d0b5d0b3d0b5d182d0b0d180d0b8d0b0d0bdd181d0bad0b8d0b5-d0b1d0bbd18ed0b4d0b0/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d180d0b8d181/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0bbd0b0d0bfd188d0b0/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0bfd0b0d181d182d0b0-d0b8-d0b8d180d0b8d0b0d0bdd0b8/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b4d0b5d181d0b5d180d182d18b/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b4d0b5d182d181d0bad0bed0b5-d0bcd0b5d0bdd18e/",
]


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def normalize_text(value):
    """Lowercase and remove accents for keyword and title matching."""
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def normalize_key(value):
    return " ".join(re.findall(r"[^\W_]+", normalize_text(value), flags=re.UNICODE))


def format_amount(value):
    """Normalizes '0,50' to '0.5' and '300.0' to '300'."""
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return clean_text(value)

    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def normalize_unit(unit):
    unit = normalize_text(unit).strip().rstrip(".")
    if unit in {
        "tk", "piece", "pieces", "pc", "pcs", "шт", "штук", "штука", "штуки"
    }:
        return "tk"
    if unit in {
        "l", "л", "литр", "литра", "литров", "milliliiter", "milliliitri",
        "milliliitrit"
    }:
        if unit.startswith("milliliit"):
            return "ml"
        return "l"
    if unit in {"ml", "мл", "миллилитр", "миллилитра", "миллилитров"}:
        return "ml"
    if unit in {"kg", "кг", "килограмм", "килограмма", "килограммов", "kilogramm", "kilogrammi"}:
        return "kg"
    if unit in {"g", "г", "грамм", "грамма", "граммов", "gramm", "grammi"}:
        return "g"
    return unit


def canonical_variant(amount, unit):
    amount_text = format_amount(amount)
    unit_text = normalize_unit(unit)
    return f"{amount_text} {unit_text}" if unit_text else None


def extract_variant_prices(text):
    """Extracts multiple size/price pairs such as '8tk 9.60, 12tk 11.60 €'."""
    found = {}

    for match in VARIANT_PRICE_RE.finditer(text or ""):
        price_text = match.group("price")
        # Avoid treating a serving size followed by an unrelated integer as a price.
        # Integer prices are accepted only when followed by the euro sign.
        if "." not in price_text and "," not in price_text and not match.group("euro"):
            continue

        variant = canonical_variant(match.group("amount"), match.group("unit"))
        if not variant:
            continue

        try:
            price = float(price_text.replace(",", "."))
        except ValueError:
            continue

        if price <= 0:
            continue

        if variant not in found:
            found[variant] = price
        elif found[variant] != price:
            print(
                f"[Monk][ВНИМАНИЕ] Для варианта {variant} найдены разные цены: "
                f"{found[variant]:.2f} и {price:.2f} €."
            )

    return sorted(found.items(), key=lambda item: variant_sort_key(item[0]))


def extract_single_quantity(description):
    """Returns a variant only if the description contains exactly one unique size."""
    variants = []
    for match in QUANTITY_RE.finditer(description or ""):
        variant = canonical_variant(match.group("amount"), match.group("unit"))
        if variant and variant not in variants:
            variants.append(variant)

    if len(variants) == 1:
        return variants[0]
    return None


def variant_sort_key(variant):
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(tk|ml|l|g|kg)\s*$", str(variant), re.I)
    if not match:
        return (9, 0.0, str(variant).casefold())

    amount = float(match.group(1))
    unit = match.group(2).lower()
    unit_order = {"tk": 0, "ml": 1, "l": 2, "g": 3, "kg": 4}
    # Keep each unit type together; numeric order makes size codes stable between runs.
    return (unit_order.get(unit, 9), amount, unit)


def get_product_type(category, name):
    """Maps Monk's many menu sections to the shared product_type vocabulary."""
    category_text = normalize_text(category)
    name_text = normalize_text(name)
    all_text = f"{category_text} {name_text}"

    # First identify types that are useful across restaurants.
    if any(word in all_text for word in ("десерт", "dessert", "magustoit", "jäätis", "морожен", "cake", "gulab jamun")):
        return "desserts"

    if any(word in name_text for word in ("комбо", "combo", "набор", "сет", "set menu", "sushi set")):
        return "sets"

    if any(word in name_text for word in ("dim sum", "dumpling", "пельмен", "дим сам")):
        return "dumplings"

    if "sashimi" in name_text or "сашими" in name_text:
        return "sashimi"
    if "nigiri" in name_text or "нигири" in name_text:
        return "nigiri"
    if "gunkan" in name_text or "гункан" in name_text:
        return "gunkan"
    if "inari" in name_text or "инари" in name_text:
        return "inari"
    if "hosomaki" in name_text or "хосомаки" in name_text:
        return "hosomaki"
    if "tempura" in name_text or "темпура" in name_text:
        return "tempura"

    if any(word in name_text for word in ("wrap", "tortilla", "тортиль", "врап")):
        return "tortillas"

    if any(word in name_text for word in ("spring roll", "spring rolls", "kevadrull", "весенний рулет")):
        return "appetizers"

    if any(word in all_text for word in ("ролл", "маки", "суши", "sushi", "maki", "roll", "rull", "сашими", "nigiri")):
        return "sushi_rolls"

    if any(word in all_text for word in ("суп", "soup", "supid", "tom kha", "tom yam", "том ям", "том кха", "miso", "мисо")):
        return "soups"

    if any(word in all_text for word in ("салат", "salad", "salatid", "salati")):
        return "salads"

    if any(word in name_text for word in ("noodle", "nuudel", "лапша", "nudel")):
        return "noodles"

    if any(word in all_text for word in ("закуск", "appetizer", "starter", "snack", "suupiste")):
        return "appetizers"

    if any(word in name_text for word in ("rice", "riis", "рис")):
        if any(word in name_text for word in (
            "chicken", "kana", "куриц", "beef", "loomaliha", "говядин",
            "lamb", "lammas", "баранин", "duck", "part", "утк",
            "shrimp", "prawn", "krevet", "кревет", "seafood", "mereannid",
            "liha", "мяс"
        )):
            return "main_courses"
        return "sides"

    if any(word in all_text for word in ("bread", "naan", "roti", "хлеб", "наан", "leivad")):
        return "sides"

    if any(word in all_text for word in ("side", "garnish", "гарнир", "lisand")):
        return "sides"

    if any(word in name_text for word in ("картофел", "potato", "fries", "friikartul", "kartul")):
        return "sides"


    if any(word in all_text for word in ("burger", "tortilla")):
        return "burgers" if "burger" in all_text else "tortillas"

    # All remaining Monk categories (duck, lamb, beef, fish, vegetarian dishes,
    # sizzlers, pasta/biryani and children's meals) are folded into existing types.
    if any(word in all_text for word in (
        "паста", "pasta", "biryani", "бирьяни", "говядин", "beef", "loomaliha",
        "баранин", "lamb", "утк", "duck", "рыб", "fish", "seafood", "mereannid",
        "куриц", "chicken", "kana", "vegetarian", "taimetoid", "вегетариан",
        "сковород", "sizzler", "panniroad", "основн", "main course",
        "паста", "lastemenuu", "детское меню", "рис", "riis"
    )):
        return "main_courses"

    # Some menu categories mix items (for example spring rolls and wraps).
    # If a name did not identify a narrower class, use the category default.
    if any(word in category_text for word in ("суши", "sushi", "sushid")):
        return "sushi_rolls"
    if any(word in category_text for word in ("лапша", "noodle", "nuudel")):
        return "noodles"
    if any(word in category_text for word in ("весенн", "spring roll", "kevadrull", "закуск", "appetizer", "suupiste")):
        return "appetizers"
    if any(word in category_text for word in ("рис", "rice", "riis")):
        return "sides"

    return "main_courses"


def get_title_element(card):
    return card.select_one(
        ".ee-post__title__heading, "
        ".product_title, "
        ".woocommerce-loop-product__title, "
        ".dish-title, "
        "h2, h3"
    )


def get_name(card):
    title = get_title_element(card)
    if not title:
        return None

    name = clean_text(title.get_text(" ", strip=True))
    # Some restaurant menus prefix names with an item number.
    name = re.sub(r"^\s*\d{1,4}\s*[.)-]\s*", "", name)
    if not name:
        return None
    if normalize_key(name) in {
        "в корзину", "добавить в корзину", "купить",
        "lisa ostukorvi", "ostukorvi", "add to cart"
    }:
        return None
    return name


def get_description(card):
    clone = BeautifulSoup(str(card), "html.parser")
    for selector in (
        ".ee-post__title__heading",
        ".product_title",
        ".woocommerce-loop-product__title",
        ".dish-title",
        "h2",
        "h3",
        ".ee-post__price",
        ".price",
        ".woocommerce-Price-amount",
        "[class*='price']",
        "button",
        "[class*='cart']",
        "[class*='add-to-cart']",
        "[class*='quantity']",
    ):
        for element in clone.select(selector):
            element.decompose()

    text = clean_text(clone.get_text(" ", strip=True))
    text = re.sub(
        r"\b(?:lisa ostukorvi|lisa korvi|add to cart|в корзину|добавить в корзину)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return clean_text(text)


def get_price(card):
    # Prefer the explicit price element; it avoids catching numbers in a description.
    for selector in (
        ".ee-post__price",
        ".price",
        ".woocommerce-Price-amount",
        "[class*='price']",
    ):
        for element in card.select(selector):
            match = PRICE_RE.search(element.get_text(" ", strip=True))
            if match:
                value = match.group(1) or match.group(2)
                return float(value.replace(",", "."))

    # Fallback for cards using another theme layout.
    clone = BeautifulSoup(str(card), "html.parser")
    for selector in (
        "button", "[class*='cart']", "[class*='add-to-cart']",
        "[class*='quantity']", "[class*='price']"
    ):
        for element in clone.select(selector):
            element.decompose()
    match = PRICE_RE.search(clone.get_text(" ", strip=True))
    if match:
        value = match.group(1) or match.group(2)
        return float(value.replace(",", "."))
    return None


def get_cards(soup):
    cards = soup.select(".product")
    if cards:
        result = []
        for card in cards:
            # Avoid processing a parent card if it contains nested product cards.
            nested = card.select(".product")
            if any(get_title_element(item) for item in nested):
                continue
            if get_title_element(card):
                result.append(card)
        if result:
            return result

    # Fallback selectors for possible theme changes.
    result = []
    seen = set()
    for selector in (".ee-post", "article", "[class*='product']"):
        for card in soup.select(selector):
            title = get_title_element(card)
            if not title:
                continue
            marker = (get_name(card) or "", tuple(card.get("class", ())))
            if marker in seen:
                continue
            if not (card.select_one(".ee-post__price, .price, [class*='price']") or PRICE_RE.search(card.get_text(" ", strip=True))):
                continue
            seen.add(marker)
            result.append(card)
        if result:
            return result
    return result


def get_category_from_page(soup, fallback):
    # The category heading on Monk's category pages is the first H1.
    for selector in ("main h1", ".entry-title", "h1"):
        heading = soup.select_one(selector)
        label = clean_text(heading.get_text(" ", strip=True)) if heading else ""
        if label:
            return label

    return clean_text(fallback) or "Без категории"


def get_category_pages(session):
    pages = {}

    try:
        response = session.get(MENU_BASE_URL, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.select("a[href]"):
            url = urljoin(MENU_BASE_URL, link.get("href", ""))
            parsed = urlparse(url)
            if parsed.netloc.casefold() not in {"monkrestoran.ee", "www.monkrestoran.ee"}:
                continue

            path = parsed.path
            if not path.startswith(BASE_PATH):
                continue

            remainder = path[len(BASE_PATH):].strip("/")
            # A category page has exactly one path segment after the restaurant slug.
            if not remainder or "/" in remainder:
                continue

            label = clean_text(link.get_text(" ", strip=True))
            if not label:
                image = link.find("img")
                label = clean_text(link.get("title") or (image.get("alt", "") if image else ""))

            pages.setdefault(path.rstrip("/") + "/", {
                "url": url.split("#", 1)[0].split("?", 1)[0],
                "label": label,
            })

        print(f"[Monk] Найдено категорий в навигации сайта: {len(pages)}")

    except requests.RequestException as error:
        print(f"[Monk] Не удалось прочитать список категорий: {error}")

    # Add known URLs as a fallback and ensure all categories listed on the site
    # are processed even if the navigation is rendered by JavaScript.
    for url in FALLBACK_CATEGORY_URLS:
        path = urlparse(url).path.rstrip("/") + "/"
        pages.setdefault(path, {"url": url, "label": ""})

    return list(pages.values())


def get_stable_base_code(name):
    key = normalize_key(name)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    return f"monk:{digest}"


def make_variant_slug(variant):
    value = normalize_text(variant)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def parse_category(session, page):
    url = page["url"]

    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"[Monk] Не удалось загрузить категорию {url}: {error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    category = get_category_from_page(soup, page.get("label"))
    records = []

    for card in get_cards(soup):
        name = get_name(card)
        if not name:
            continue

        description = get_description(card)
        base_code = get_stable_base_code(name)
        variant_prices = extract_variant_prices(card.get_text(" ", strip=True))

        if variant_prices:
            for index, (variant, price) in enumerate(variant_prices):
                dish_code = (
                    base_code if index == 0
                    else f"{base_code}:variant:{make_variant_slug(variant)}"
                )
                records.append(
                    make_record(name, category, dish_code, price, variant)
                )
            continue

        price = get_price(card)
        if price is None or price <= 0:
            continue

        # A single size in the description is kept as a variant as well.
        price_variant = extract_single_quantity(description)
        records.append(make_record(name, category, base_code, price, price_variant))

    print(f"[Monk] {category}: получено записей — {len(records)}")
    return records


def make_record(name, category, dish_code, price, price_variant):
    # Monk's Russian menu sometimes uses English names, which are also useful
    # in the Estonian view. Keep an Estonian name only when the title is not Cyrillic.
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", name))
    name_et = None if has_cyrillic else name

    return {
        "dish_code": dish_code,
        "dish_name": name,
        "dish_name_ru": name,
        "dish_name_et": name_et,
        "category_ru": category or None,
        "category_et": None,
        "price": float(price),
        "price_variant": price_variant,
        "product_type": get_product_type(category, name),
    }


def parse_menu():
    """Loads all Monk Jõhvi categories and returns Supabase-compatible dish rows."""
    session = requests.Session()
    session.headers.update(HEADERS)
    pages = get_category_pages(session)
    if not pages:
        print("[Monk] Не удалось найти страницы категорий.")
        return []

    merged = {}
    for page in pages:
        for dish in parse_category(session, page):
            # Some products may be linked from more than one section.
            key = (
                normalize_key(dish.get("dish_name")),
                normalize_key(dish.get("price_variant")),
            )
            if key not in merged:
                merged[key] = dish

    result = list(merged.values())
    print(f"[Monk] После удаления повторов: {len(result)} записей")
    return result


if __name__ == "__main__":
    for item in parse_menu():
        print(
            f'{item["dish_name"]} | {item["price"]:.2f} € | '
            f'{item.get("price_variant") or "—"} | {item["product_type"]}'
        )
