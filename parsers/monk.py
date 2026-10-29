"""Парсер меню Monk Jõhvi на русском и эстонском языках.

Собирает полное меню, определяет категорию каждого блюда по ближайшему
заголовку раздела, объединяет переводы и сохраняет количество/размер
в price_variant (например, "8 tk", "0.5 l", "300 g").
"""

import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


LANGUAGE_CONFIG = {
    "ru": {
        "base_url": "https://monkrestoran.ee/ru/monk-johvi-2/",
        "base_path": "/ru/monk-johvi-2/",
        "legacy_url": "https://monkrestoran.ee/ru/monk-johvi-2/d181d183d188d0b8/",
    },
    "et": {
        "base_url": "https://monkrestoran.ee/monk-johvi/",
        "base_path": "/monk-johvi/",
        "legacy_url": None,
    },
}

# Backwards-compatible constants used by the Russian-only fallback menu.
MENU_BASE_URL = LANGUAGE_CONFIG["ru"]["base_url"]
BASE_PATH = LANGUAGE_CONFIG["ru"]["base_path"]
LEGACY_MENU_URL = LANGUAGE_CONFIG["ru"]["legacy_url"]

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
# are picked up automatically. Russian URLs were supplied by the user; Estonian
# URLs follow Monk's current public routes (without an /et/ prefix).
FALLBACK_CATEGORY_URLS_ET = [
    "https://monkrestoran.ee/monk-johvi/sushid/",
    "https://monkrestoran.ee/monk-johvi/eelroad/",
    "https://monkrestoran.ee/monk-johvi/panniroad/",
    "https://monkrestoran.ee/monk-johvi/leivad/",
    "https://monkrestoran.ee/monk-johvi/kevadrullid-wrapid/",
    "https://monkrestoran.ee/monk-johvi/salatid/",
    "https://monkrestoran.ee/monk-johvi/supid/",
    "https://monkrestoran.ee/monk-johvi/pardilihatoidud/",
    "https://monkrestoran.ee/monk-johvi/lambalihatoidud/",
    "https://monkrestoran.ee/monk-johvi/loomalihatoidud/",
    "https://monkrestoran.ee/monk-johvi/kala-mereannid/",
    "https://monkrestoran.ee/monk-johvi/taimetoidud/",
    "https://monkrestoran.ee/monk-johvi/riis/",
    "https://monkrestoran.ee/monk-johvi/nuudlid/",
    "https://monkrestoran.ee/monk-johvi/pasta/",
    "https://monkrestoran.ee/monk-johvi/magustoidud/",
    "https://monkrestoran.ee/monk-johvi/lastemenuu/",
    "https://monkrestoran.ee/monk-johvi/kanalihatoidud/",
]

FALLBACK_CATEGORY_URLS = [
    "https://monkrestoran.ee/ru/monk-johvi-2/d181d183d188d0b8/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b7d0b0d0bad183d181d0bad0b8/",
    "https://monkrestoran.ee/ru/monk-johvi-2/d0b1d0bbd18ed0b4d0b0-d0bdd0b0-d181d0bad0bed0b2d0bed180d0bed0b4d0b5/",
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
    "https://monkrestoran.ee/ru/monk-johvi-2/d0bad183d180d0b8d0bdd18bd0b5-d0b1d0bbd18ed0b4d0b0/",
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

    if any(word in name_text for word in (
        "spring roll", "spring rolls", "kevadrull", "весенний рулет",
        "спринг-ролл", "спринг ролл"
    )):
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
            marker = (get_name(card) or "", tuple(card.get("class") or ()))
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


def clean_url(url):
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") + "/"
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}{path}"


def find_alternate_category_url(soup, target_language):
    """Looks for the same category linked by the site's language switcher."""
    config = LANGUAGE_CONFIG[target_language]
    expected_prefix = config["base_path"]
    candidates = []

    for link in soup.select("a[href], link[href]"):
        href = link.get("href", "")
        if not href:
            continue

        url = urljoin("https://monkrestoran.ee/", href)
        parsed = urlparse(url)
        if parsed.netloc.casefold() not in {"monkrestoran.ee", "www.monkrestoran.ee"}:
            continue
        if not parsed.path.startswith(expected_prefix):
            continue

        remainder = parsed.path[len(expected_prefix):].strip("/")
        if not remainder or "/" in remainder:
            continue

        declared_lang = clean_text(
            link.get("hreflang")
            or link.get("lang")
            or link.get("data-lang")
            or ""
        ).casefold()
        attrs = " ".join([
            str(link.get("class", "")),
            str(link.get("aria-label", "")),
            str(link.get("title", "")),
            clean_text(link.get_text(" ", strip=True)),
        ]).casefold()

        # Don't accidentally use an ordinary category link as a language switch.
        # Prefer metadata, language labels, or common multilingual-menu classes.
        has_language_marker = (
            declared_lang.startswith(target_language)
            or any(token in attrs for token in (
                "lang-item", "language", "switcher", "wpml", "polylang",
                "eesti", "estonian", "et-ee", "русский", "russian",
                "english", "inglise", "flag-icon"
            ))
        )
        if not has_language_marker:
            continue

        priority = 0 if declared_lang.startswith(target_language) else 1
        candidates.append((priority, clean_url(url)))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]

CATEGORY_PAIR_LABELS = {
    # Russian and Estonian section headings map to a shared matching key.
    "суши": "sushi",
    "sushid": "sushi",
    "закуски": "appetizers",
    "eelroad": "appetizers",
    "блюда на сковороде": "sizzlers",
    "panniroad": "sizzlers",
    "хлеб": "bread",
    "leivad": "bread",
    "весенние рулеты и врапы": "spring-wraps",
    "kevadrullid wrapid": "spring-wraps",
    "салаты": "salads",
    "salatid": "salads",
    "супы": "soups",
    "supid": "soups",
    "утиные курсы": "duck",
    "утиные блюда": "duck",
    "pardilihatoidud": "duck",
    "блюда из баранины": "lamb",
    "lambalihatoidud": "lamb",
    "говядина": "beef",
    "loomalihatoidud": "beef",
    "рыба и морепродукты": "fish-seafood",
    "kala mereannid": "fish-seafood",
    "вегетарианские блюда": "vegetarian",
    "taimetoidud": "vegetarian",
    "рис": "rice",
    "riis": "rice",
    "лапша": "noodles",
    "nuudlid": "noodles",
    "паста и бириани": "pasta-biryani",
    "pasta": "pasta-biryani",
    "десерты": "desserts",
    "magustoidud": "desserts",
    "детское меню": "children",
    "lastemenuu": "children",
    "блюда из курицы": "chicken",
    "kanalihatoidud": "chicken",
}


def canonical_category_pair_key(category):
    return CATEGORY_PAIR_LABELS.get(normalize_key(category))


def get_category_pair_key(soup, current_url, language, category=None):
    """Returns a stable key for a category across the Russian and Estonian menus."""
    # Most category labels have a direct Russian/Estonian equivalent, so don't
    # depend on the language switcher being present in the page HTML.
    shared_category = canonical_category_pair_key(category)
    if shared_category:
        return f"category:{shared_category}"

    other_language = "et" if language == "ru" else "ru"
    alternate_url = find_alternate_category_url(soup, other_language)

    if alternate_url:
        return "|".join(sorted((clean_url(current_url), alternate_url)))

    # If category slugs are identical across languages, this produces the
    # same key without requiring a language-switcher link.
    path = urlparse(current_url).path
    config = LANGUAGE_CONFIG[language]
    remainder = path[len(config["base_path"]):].strip("/")
    return f"slug:{normalize_key(remainder)}"


def get_category_pages(session, language="ru"):
    config = LANGUAGE_CONFIG[language]
    pages = {}

    discovery_urls = [config["base_url"]]
    if config.get("legacy_url"):
        discovery_urls.append(config["legacy_url"])

    for discovery_url in discovery_urls:
        try:
            response = session.get(discovery_url, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for link in soup.select("a[href]"):
                url = urljoin(discovery_url, link.get("href", ""))
                parsed = urlparse(url)
                if parsed.netloc.casefold() not in {"monkrestoran.ee", "www.monkrestoran.ee"}:
                    continue

                path = parsed.path
                if not path.startswith(config["base_path"]):
                    continue

                remainder = path[len(config["base_path"]):].strip("/")
                # A category page has exactly one path segment after the restaurant slug.
                if not remainder or "/" in remainder:
                    continue

                label = clean_text(link.get_text(" ", strip=True))
                if not label:
                    image = link.find("img")
                    label = clean_text(link.get("title") or (image.get("alt", "") if image else ""))

                canonical_url = url.split("#", 1)[0].split("?", 1)[0]
                pages.setdefault(clean_url(canonical_url), {
                    "url": canonical_url,
                    "label": label,
                    "language": language,
                })

        except requests.RequestException as error:
            print(f"[Monk/{language}] Не удалось прочитать навигацию {discovery_url}: {error}")

    print(f"[Monk/{language}] Найдено категорий в навигации сайта: {len(pages)}")

    # Known Russian category URLs are a fallback. For Estonian, try their
    # matching paths too; if the site localizes slugs, the live navigation
    # above will supply the correct links.
    fallback_urls = (
        FALLBACK_CATEGORY_URLS_ET
        if language == "et"
        else FALLBACK_CATEGORY_URLS
    )

    if not pages:
        for url in fallback_urls:
            path = urlparse(url).path.rstrip("/") + "/"
            if path.startswith(config["base_path"]):
                pages.setdefault(clean_url(url), {
                    "url": url,
                    "label": "",
                    "language": language,
                })

    return list(pages.values())

def get_card_identifier(card):
    """Tries to extract a stable product/SKU ID from a product card."""
    if card is None:
        return None

    id_attributes = (
        "data-product_id", "data-product-id", "data-productid",
        "data-post-id", "data-postid", "data-item-id", "data-id", "data-sku",
    )
    id_patterns = (
        re.compile(r"^(?:product|post|item|ee-post)[_-]?(\d+)$", re.I),
        re.compile(r"(?:^|\s)(?:post|product|product-id|postid|ee-post)[_-](\d+)(?:\s|$)", re.I),
    )

    for attr in id_attributes:
        value = clean_text(card.get(attr, ""))
        if value and re.fullmatch(r"[A-Za-z0-9_-]{2,80}", value):
            return f"site:{value.casefold()}"

    candidates = [clean_text(card.get("id", ""))]
    classes = card.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    candidates.extend(classes)

    for candidate in candidates:
        for pattern in id_patterns:
            match = pattern.search(candidate)
            if match:
                return f"site:{match.group(1)}"

    for link in card.select("a[href]"):
        href = link.get("href", "")
        match = re.search(r"[?&](?:product_id|post_id|p)=(\d+)(?:&|$)", href, re.I)
        if match:
            return f"site:{match.group(1)}"

    return None

def get_stable_base_code(name, card=None):
    """Uses a site product ID when available, otherwise a stable name hash."""
    identifier = get_card_identifier(card)
    if identifier:
        return f"monk:{identifier}"

    key = normalize_key(name)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
    return f"monk:{digest}"


def make_variant_slug(variant):
    value = normalize_text(variant)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def parse_category(session, page, language="ru"):
    url = page["url"]

    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"[Monk/{language}] Не удалось загрузить меню {url}: {error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    page_category = get_category_from_page(soup, page.get("label"))
    cards = get_cards(soup)
    records = []
    found_categories = set()

    for card_index, card in enumerate(cards):
        name = get_name(card)
        if not name:
            continue

        # Every Monk category route appears to render the full menu. The item
        # belongs to the nearest preceding section H2, not the page's H1
        # ("Monk Jõhvi" / "Monk Йыхви").
        category = get_category_before_card(card)
        normalized_category = normalize_key(category)
        if not category or normalized_category in {
            "без категории", "monk johvi", "monk йыхви", "monk johvi 2",
            "monk йыхви 2",
        }:
            category = page_category
            normalized_category = normalize_key(category)

        if normalized_category in {
            "monk johvi", "monk йыхви", "monk johvi 2", "monk йыхви 2"
        }:
            category = "Без категории"

        found_categories.add(category)
        category_pair_key = get_category_pair_key(
            soup, url, language, category
        )

        description = get_description(card)
        base_code = get_stable_base_code(name, card)
        match_id = get_card_identifier(card) or f"name:{normalize_key(name)}"
        variant_prices = extract_variant_prices(card.get_text(" ", strip=True))

        if variant_prices:
            for index, (variant, price) in enumerate(variant_prices):
                dish_code = (
                    base_code if index == 0
                    else f"{base_code}:variant:{make_variant_slug(variant)}"
                )
                records.append(make_record(
                    name, category, dish_code, price, variant, language,
                    match_id, category_pair_key, card_index, len(cards)
                ))
            continue

        price = get_price(card)
        if price is None or price <= 0:
            continue

        price_variant = extract_single_quantity(description)
        records.append(make_record(
            name, category, base_code, price, price_variant, language,
            match_id, category_pair_key, card_index, len(cards)
        ))

    print(
        f"[Monk/{language}] URL {url}: карточек={len(cards)}, "
        f"категорий распознано={len(found_categories)}, записей={len(records)}"
    )
    if len(found_categories) <= 2:
        print(
            f"[Monk/{language}][ВНИМАНИЕ] Категории, извлечённые из заголовков: "
            f"{sorted(found_categories)}"
        )
    return records


def get_category_before_card(card):
    """Finds the nearest section heading on Monk's legacy all-in-one menu."""
    for heading in card.find_all_previous("h2"):
        # Ignore an h2 that is actually a product title inside the previous card.
        is_product_heading = False
        for parent in heading.parents:
            classes = parent.get("class", []) if hasattr(parent, "get") else []
            if isinstance(classes, str):
                classes = [classes]
            if any(cls in {"product", "ee-post"} for cls in classes):
                is_product_heading = True
                break
        if is_product_heading:
            continue

        label = clean_text(heading.get_text(" ", strip=True))
        if label:
            return label

    return "Без категории"


def parse_legacy_menu(session):
    """Supplement category-page results from the legacy all-in-one Monk menu."""
    try:
        response = session.get(LEGACY_MENU_URL, timeout=20)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"[Monk] Не удалось загрузить резервное меню: {error}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    cards = get_cards(soup)
    records = []

    for card in cards:
        name = get_name(card)
        if not name:
            continue

        category = get_category_before_card(card)
        description = get_description(card)
        base_code = get_stable_base_code(name)
        variant_prices = extract_variant_prices(card.get_text(" ", strip=True))

        if variant_prices:
            for index, (variant, price) in enumerate(variant_prices):
                dish_code = (
                    base_code if index == 0
                    else f"{base_code}:variant:{make_variant_slug(variant)}"
                )
                records.append(make_record(name, category, dish_code, price, variant))
            continue

        price = get_price(card)
        if price is None or price <= 0:
            continue

        price_variant = extract_single_quantity(description)
        records.append(make_record(name, category, base_code, price, price_variant))

    print(f"[Monk] Резервное меню: получено записей — {len(records)}")
    return records

def make_record(
    name, category, dish_code, price, price_variant, language="ru",
    match_id=None, category_pair_key=None, card_index=None, card_count=None
):
    """Builds one localized row and retains internal match keys for bilingual merge."""
    category_text = clean_text(category)
    if normalize_key(category_text) in {"", "без категории", "monk johvi"}:
        category_text = None

    is_ru = language == "ru"
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", name))
    # English product names can be displayed in either UI language, but the
    # category/name source still belongs only to the language being parsed.
    result = {
        "dish_code": dish_code,
        "dish_name": name,
        "dish_name_ru": name if is_ru else None,
        "dish_name_et": name if not is_ru else None,
        "category_ru": category_text if is_ru else None,
        "category_et": category_text if not is_ru else None,
        "price": float(price),
        "price_variant": price_variant,
        "product_type": get_product_type(category_text, name),
        "_source_language": language,
        "_match_id": match_id or f"name:{normalize_key(name)}",
        "_category_pair_key": category_pair_key,
        "_card_index": card_index,
        "_card_count": card_count,
    }
    return result


def record_variant_key(record):
    return normalize_key(record.get("price_variant"))


def record_name_key(record):
    return normalize_key(record.get("dish_name") or "")


def deduplicate_language_records(records):
    """Drops duplicate listings within a single language without merging translations."""
    result = []
    seen = set()
    for record in records:
        key = (record.get("_match_id"), record_variant_key(record))
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def merge_language_records(russian_records, estonian_records):
    """Merges Russian and Estonian menu rows while preserving both localized fields."""
    russian_records = deduplicate_language_records(russian_records)
    estonian_records = deduplicate_language_records(estonian_records)

    result = []
    used_ru = set()
    used_et = set()

    # First match explicit shared product IDs, then genuinely identical names.
    # If both are missing, fall back to the same paired category/card position,
    # but only when the price and serving-size variant also agree.
    for et_index, et_row in enumerate(estonian_records):
        et_variant = record_variant_key(et_row)
        et_name = record_name_key(et_row)
        candidates = []

        for ru_index, ru_row in enumerate(russian_records):
            if ru_index in used_ru:
                continue
            if record_variant_key(ru_row) != et_variant:
                continue

            same_shared_id = (
                ru_row.get("_match_id", "").startswith("site:")
                and ru_row.get("_match_id") == et_row.get("_match_id")
            )
            same_name = bool(et_name) and record_name_key(ru_row) == et_name
            if same_shared_id or same_name:
                candidates.append((0 if same_shared_id else 1, ru_index))

        if candidates:
            _, ru_index = sorted(candidates)[0]
        else:
            positional_candidates = []
            et_pair = et_row.get("_category_pair_key")
            et_position = et_row.get("_card_index")
            et_count = et_row.get("_card_count")

            if et_pair is not None and et_position is not None:
                for ru_index, ru_row in enumerate(russian_records):
                    if ru_index in used_ru:
                        continue
                    if record_variant_key(ru_row) != et_variant:
                        continue
                    if ru_row.get("_category_pair_key") != et_pair:
                        continue
                    if ru_row.get("_card_index") != et_position:
                        continue
                    if ru_row.get("_card_count") != et_count:
                        continue
                    if abs(float(ru_row["price"]) - float(et_row["price"])) > 0.001:
                        continue
                    positional_candidates.append(ru_index)

            if len(positional_candidates) != 1:
                continue
            ru_index = positional_candidates[0]

        ru_row = russian_records[ru_index]
        used_ru.add(ru_index)
        used_et.add(et_index)

        # Keep the Russian dish_code when available so future price runs update
        # the same Supabase row. RU price takes priority if both pages agree.
        merged = {
            "dish_code": ru_row.get("dish_code") or et_row.get("dish_code"),
            "dish_name": ru_row.get("dish_name") or et_row.get("dish_name"),
            "dish_name_ru": ru_row.get("dish_name_ru") or None,
            "dish_name_et": et_row.get("dish_name_et") or None,
            "category_ru": ru_row.get("category_ru") or None,
            "category_et": et_row.get("category_et") or None,
            "price": float(ru_row["price"] if ru_row.get("price") is not None else et_row["price"]),
            "price_variant": ru_row.get("price_variant") or et_row.get("price_variant"),
            "product_type": get_product_type(
                f"{ru_row.get('category_ru') or ''} {et_row.get('category_et') or ''}",
                f"{ru_row.get('dish_name_ru') or ''} {et_row.get('dish_name_et') or ''}",
            ),
        }

        if abs(float(ru_row["price"]) - float(et_row["price"])) > 0.001:
            print(
                "[Monk][ВНИМАНИЕ] Отличаются цены для "
                f"{merged['dish_name']}: RU={float(ru_row['price']):.2f} €, "
                f"ET={float(et_row['price']):.2f} €; сохранена русская цена."
            )
        result.append(merged)

    # Preserve records that could not be paired instead of guessing and merging
    # potentially different dishes that happen to have the same price.
    for ru_index, row in enumerate(russian_records):
        if ru_index not in used_ru:
            result.append({
                "dish_code": row.get("dish_code"),
                "dish_name": row.get("dish_name"),
                "dish_name_ru": row.get("dish_name_ru"),
                "dish_name_et": None,
                "category_ru": row.get("category_ru"),
                "category_et": None,
                "price": float(row["price"]),
                "price_variant": row.get("price_variant"),
                "product_type": row.get("product_type"),
            })

    for et_index, row in enumerate(estonian_records):
        if et_index not in used_et:
            result.append({
                "dish_code": row.get("dish_code"),
                "dish_name": row.get("dish_name"),
                "dish_name_ru": None,
                "dish_name_et": row.get("dish_name_et"),
                "category_ru": None,
                "category_et": row.get("category_et"),
                "price": float(row["price"]),
                "price_variant": row.get("price_variant"),
                "product_type": row.get("product_type"),
            })

    return result



def parse_menu():
    """Parses Monk Jõhvi in Russian and Estonian, then merges translations."""
    session = requests.Session()
    session.headers.update(HEADERS)

    language_records = {}
    for language in ("ru", "et"):
        pages = get_category_pages(session, language)

        # On the live site, each category link renders the same whole menu.
        # Process only one representative URL per language to avoid fetching
        # 18 copies of the same 223 product cards.
        if len(pages) > 1:
            print(
                f"[Monk/{language}] Найдено {len(pages)} ссылок категорий; "
                "обрабатываю одну страницу, содержащую всё меню."
            )
            pages = pages[:1]

        records = []
        for page in pages:
            records.extend(parse_category(session, page, language))

        # Retry a known valid Russian menu route only if the first route failed.
        if language == "ru" and not records:
            records.extend(parse_legacy_menu(session))

        language_records[language] = records
        print(f"[Monk/{language}] Всего получено записей: {len(records)}")

    russian_records = language_records.get("ru", [])
    estonian_records = language_records.get("et", [])

    if not russian_records and not estonian_records:
        print("[Monk] Не удалось получить меню ни на русском, ни на эстонском.")
        return []

    result = merge_language_records(russian_records, estonian_records)
    print(f"[Monk] После объединения языков и удаления повторов: {len(result)} записей")
    return result

if __name__ == "__main__":
    for item in parse_menu():
        print(
            f'RU: {item.get("dish_name_ru") or "—"} | '
            f'ET: {item.get("dish_name_et") or "—"} | '
            f'Категории: {item.get("category_ru") or "—"} / '
            f'{item.get("category_et") or "—"} | '
            f'{item["price"]:.2f} € | '
            f'{item.get("price_variant") or "—"} | '
            f'{item["product_type"]}'
        )
