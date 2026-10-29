"""Parser for the Ida-Toit online menu, stored as Break Time Burger & Wrap.

The shop is a WooCommerce site with Estonian and Russian catalog routes.
This parser reads both routes, follows catalog pagination, merges confidently
matched translations, and maps source categories into the shared project taxonomy.
"""
import hashlib
import re
import unicodedata
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

try:
    from parsers.categories import canonical_category_ru, canonical_category_et
except ModuleNotFoundError:  # Support running this parser as a standalone script.
    from categories import canonical_category_ru, canonical_category_et


RESTAURANT_NAME = "Break Time Burger & Wrap"
BASE_URL = "https://ida-toit.ee/"
LANGUAGE_URLS = {
    "et": BASE_URL,
    "ru": urljoin(BASE_URL, "ru/"),
}
MAX_CATALOG_PAGES = 40
MAX_LANGUAGE_SECONDS = 180
REQUEST_TIMEOUT = (5, 15)
REQUEST_DELAY_SECONDS = 0.6
MAX_REQUEST_RETRIES = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "et-EE,et;q=0.9,ru;q=0.8,en;q=0.7",
}

PRICE_RE = re.compile(
    r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)|"
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€"
)

TITLE_SELECTORS = (
    ".ee-post__title__heading",
    ".woocommerce-loop-product__title",
    ".product_title",
    ".dish-title",
    ".ee-post__title",
    "h2",
    "h3",
)

CATEGORY_PATH_MARKERS = (
    "tootekategooria",
    "product-category",
    "product_cat",
    "kategoriya-tovara",
    "kategoriya-produkta",
)

_SET_CATEGORY_MARKERS = (
    "kombo", "kombineeritud", "combo", "set menu", "набор", "комбо",
    "комплект", "sets", "komplektid",
)
_SET_NAME_MARKERS = (
    "combo", "kombo", "комбо", "комбо-набор", "набор", "меню",
    "menu", "set menu", "burger eine", "burgeri eine",
)
_BURGER_MARKERS = ("burger", "бург", "бургер")
_TORTILLA_MARKERS = ("lavash", "lavaš", "лаваш", "tortilla", "тортиль", "wrap", "врап")
_DESSERT_MARKERS = (
    "dessert", "magustoit", "magustoid", "десерт", "морожен", "jäätis",
    "churros", "фондан", "пончик", "профитрол", "маффин", "блин", "pannkook",
    "pannkoog", "pancake", "шоколадный",
)
_DRINK_CATEGORY_MARKERS = (
    "joog", "drink", "beverage", "напит", "коктейл", "kokteil",
    "kuumad joogid", "горячие напитки",
)
_DRINK_NAME_MARKERS = (
    "coca-cola", "coca cola", "fanta", "sprite", "mirinda", "red bull",
    "fuzetea", "arizona", "neptunas", "mineral water", "mineraalvesi",
    "water", "vesi", "mahl", "juice", "limonaad", "lemonade", "coffee",
    "kohv", "espresso", "cappuccino", "latte", "tee", "kohvijook",
    "milkshake", "jäätisekokteil", "коктейл", "кофе", "чай", "вода",
    "сок", "лимонад", "пиво", "вино",
)
_ALCOHOL_MARKERS = (
    "alkohool", "alcohol", "алкогол", "beer", "bier", "õlu", "vein",
    "wine", "vahuvein", "champagne", "šampanja", "siider", "cider",
    "vodka", "whisky", "whiskey", "gin", "rum", "prosecco",
)
_SIDE_MARKERS = (
    "friikartul", "fries", "french fries", "kartul", "potato", "bataat",
    "sweet potato", "картофел", "батат", "луковые кольца",
)
_APPETIZER_CATEGORY_MARKERS = (
    "suupist", "eelroad", "закуск", "appetizer", "starter", "snack",
)
_SAUCE_MARKERS = ("kastmed", "sauce", "соус", "соусы")
_SALAD_MARKERS = ("salat", "салат")
_SOUP_MARKERS = ("soup", "supi", "суп")
_NOODLE_MARKERS = ("nuudl", "nuudel", "noodle", "лапша")
_BREAKFAST_MARKERS = ("hommikusöök", "breakfast", "завтрак")
_MAIN_CATEGORY_MARKERS = (
    "praad", "grill", "šaslõkk", "шашлык", "kebab", "doner", "döner",
    "shawarma", "шаверм", "шаурм", "пита", "main course",
)


def clean_text(value):
    """Collapse whitespace and remove surrounding spaces."""
    return " ".join(str(value or "").split()).strip()


def normalize_text(value):
    """Case-fold text and remove diacritics for stable matching."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def normalize_key(value):
    """Return a punctuation-insensitive key, preserving Unicode letters."""
    return " ".join(re.findall(r"[^\W_]+", normalize_text(value), flags=re.UNICODE))


def normalize_product_key(value):
    """Ignore the site's label for products which have not been translated."""
    key = normalize_key(value)
    for prefix in ("eesti ", "estonian ", "по-эстонски "):
        if key.startswith(prefix):
            key = key[len(prefix):].strip()
    return key


def build_catalog_url(language):
    """Start from the live homepage; its category navigation links to the menu."""
    return LANGUAGE_URLS[language]


def _get_page(session, url):
    """Fetch a page politely and retry temporary HTTP 429 responses."""
    for attempt in range(MAX_REQUEST_RETRIES + 1):
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 429:
            response.raise_for_status()
            # Avoid hammering the menu site while following its category pages.
            time.sleep(REQUEST_DELAY_SECONDS)
            return response

        if attempt >= MAX_REQUEST_RETRIES:
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After", "")
        try:
            delay = max(float(retry_after), 3.0)
        except (TypeError, ValueError):
            delay = min(5.0 * (2 ** attempt), 30.0)
        print(
            f"[Break Time] Сайт ограничил частоту запросов (429). "
            f"Повтор через {delay:g} сек.; попытка {attempt + 2}/"
            f"{MAX_REQUEST_RETRIES + 1}."
        )
        time.sleep(delay)

    raise RuntimeError(f"Не удалось загрузить {url}")


def get_title_element(card):
    for selector in TITLE_SELECTORS:
        element = card.select_one(selector)
        if element:
            text = clean_text(element.get_text(" ", strip=True))
            if text:
                return element
    return None


def get_name(card):
    title = get_title_element(card)
    if not title:
        return None
    name = clean_text(title.get_text(" ", strip=True))
    name = re.sub(
        r"\s*(?:lisa ostukorvi|lisa korvi|add to cart|"
        r"в корзину|добавить в корзину)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return name.strip(" \t\r\n-–—") or None


def _parse_price(text):
    matches = list(PRICE_RE.finditer(str(text or "")))
    if not matches:
        return None
    # The current price normally follows the struck-through previous price.
    match = matches[-1]
    value = match.group(1) or match.group(2)
    try:
        price = float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None
    return price if price > 0 else None


def get_price(card):
    """Read the current price, preferring WooCommerce's sale-price element."""
    for selector in (
        ".price ins .woocommerce-Price-amount",
        ".price ins .amount",
        ".ee-post__price ins .woocommerce-Price-amount",
        ".ee-post__price ins .amount",
        "ins .woocommerce-Price-amount",
        "ins .amount",
    ):
        elements = card.select(selector)
        for element in reversed(elements):
            price = _parse_price(element.get_text(" ", strip=True))
            if price is not None:
                return price

    for selector in (
        ".ee-post__price .woocommerce-Price-amount",
        ".price .woocommerce-Price-amount",
        ".price .amount",
        ".woocommerce-Price-amount",
        ".ee-post__price",
        ".price",
        "[class*='price']",
    ):
        elements = card.select(selector)
        parsed = []
        for element in elements:
            price = _parse_price(element.get_text(" ", strip=True))
            if price is not None:
                parsed.append(price)
        if parsed:
            return parsed[-1]

    # Theme fallback: search only after removing controls and non-price metadata.
    clone = BeautifulSoup(str(card), "html.parser")
    for element in clone.select(
        "button, [class*='cart'], [class*='quantity'], "
        "[class*='rating'], .star-rating, del"
    ):
        element.decompose()
    return _parse_price(clone.get_text(" ", strip=True))


def _is_category_url(url):
    path = urlparse(url).path.casefold()
    return any(marker in path for marker in CATEGORY_PATH_MARKERS)


def get_categories(card):
    """Read product-category labels from the card's category links or badges."""
    categories = []
    selectors = (
        ".product-category a",
        ".posted_in a",
        ".product-categories a",
        ".ee-post__category a",
        ".ee-post__categories a",
        "[class*='category'] a",
        "[class*='categories'] a",
    )
    for selector in selectors:
        for link in card.select(selector):
            label = clean_text(link.get_text(" ", strip=True))
            href = urljoin(BASE_URL, link.get("href", ""))
            if not label or not _is_category_url(href):
                continue
            if normalize_key(label) not in {normalize_key(item) for item in categories}:
                categories.append(label)

    if categories:
        return categories

    # Some themes put labels in spans rather than links.
    for selector in (
        ".posted_in",
        ".product-categories",
        ".ee-post__category",
        ".ee-post__categories",
        "[class*='product-category']",
    ):
        for element in card.select(selector):
            label = clean_text(element.get_text(" ", strip=True))
            if not label:
                continue
            label = re.sub(r"\b(?:категори[яи]|category|kategooria)\s*:\s*", "", label, flags=re.I)
            for part in re.split(r"[,|/]", label):
                part = clean_text(part)
                if part and normalize_key(part) not in {
                    normalize_key(item) for item in categories
                }:
                    categories.append(part)

    if categories:
        return categories

    # This custom WooCommerce theme sometimes only exposes category slugs in
    # the product's class list (e.g. product_cat-kokteilid) rather than visible
    # category links. Preserve those tags so classification still sees the
    # site's real menu section instead of guessing from the product name alone.
    classes = card.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    for class_name in classes:
        match = re.match(r"^(?:product_cat|product-category)-(.+)$", str(class_name), re.I)
        if not match:
            continue
        slug = clean_text(match.group(1)).replace("-", " ")
        if slug and normalize_key(slug) not in {
            normalize_key(item) for item in categories
        }:
            categories.append(slug)

    return categories


def get_card_identifier(card):
    """Prefer a stable WooCommerce product ID; fall back to a product slug."""
    for attr in (
        "data-product_id",
        "data-product-id",
        "data-productid",
        "data-post-id",
        "data-postid",
        "data-item-id",
        "data-sku",
    ):
        value = clean_text(card.get(attr, ""))
        if value and re.fullmatch(r"[A-Za-z0-9_-]{2,80}", value):
            return f"site:{value.casefold()}"

    candidates = [clean_text(card.get("id", ""))]
    classes = card.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    candidates.extend(classes)

    for candidate in candidates:
        match = re.search(
            r"(?:^|[\s_-])(?:product|post|item|ee-post)[_-]?(\d+)(?:$|[\s_-])",
            candidate,
            flags=re.IGNORECASE,
        )
        if match:
            return f"site:{match.group(1)}"

    for link in card.select("a[href]"):
        href = link.get("href", "")
        match = re.search(r"[?&](?:add-to-cart|product_id|post_id|p)=(\d+)(?:&|$)", href, re.I)
        if match:
            return f"site:{match.group(1)}"

    product_path_markers = (
        "/toode/",
        "/ru/toode/",
        "/tovar/",
        "/ru/tovar/",
        "/product/",
        "/produkt/",
    )
    for link in card.select("a[href]"):
        parsed = urlparse(urljoin(BASE_URL, link.get("href", "")))
        path = parsed.path.rstrip("/")
        if _is_category_url(parsed.geturl()):
            continue
        if any(marker in path.casefold() for marker in product_path_markers):
            slug = path.split("/")[-1]
            if slug and slug not in {"toode", "tovar", "product", "produkt"}:
                return f"slug:{slug.casefold()}"

    return None


def get_cards(soup):
    """Select WooCommerce cards while avoiding nested wrapper duplicates."""
    candidates = soup.select(
        "ul.products li.product, .woocommerce ul.products li.product, "
        ".products .product, li.product, .product"
    )
    if not candidates:
        candidates = soup.select(".ee-post, article.product, article")

    cards = []
    seen_objects = set()
    for card in candidates:
        object_id = id(card)
        if object_id in seen_objects:
            continue
        seen_objects.add(object_id)

        parent_product = card.find_parent(class_="product")
        if parent_product is not None and get_title_element(parent_product):
            continue

        if not get_title_element(card):
            continue
        if get_price(card) is None:
            continue
        cards.append(card)

    return cards


def get_product_type(category, name):
    """Map Ida-Toit's RU/ET labels into the existing shared product taxonomy."""
    category_text = normalize_text(category)
    name_text = normalize_text(name)
    all_text = f"{category_text} {name_text}"

    def has_any(text, markers):
        # Product names and category constants may contain Estonian diacritics.
        # The source text is normalized, so normalize the marker the same way.
        return any(normalize_text(marker) in text for marker in markers)

    # Milkshakes/cocktails have their own shared product type, which maps to
    # the project's existing drinks category in both languages.
    if has_any(category_text, ("kokteil", "коктейл")):
        return "ice_cream_shakes"

    # A named combo or burger meal is a set, including products in the broad
    # Estonian Eine section. Plain fries under Eine are still a side dish.
    if has_any(category_text, _SET_CATEGORY_MARKERS):
        return "sets"
    # On this menu, the Estonian "Eine" category contains both burger meals
    # and plain sides. Keep products such as fries in sides, but classify an
    # actual meal even when its name does not contain the word "burger".
    if "eine" in category_text and not has_any(name_text, _SIDE_MARKERS):
        return "sets"
    if has_any(name_text, _SET_NAME_MARKERS):
        return "sets"
    if "eine" in name_text and not has_any(name_text, _SIDE_MARKERS):
        return "sets"

    # Explicit menu sections such as Hot dog, Shawarma and Kebab take priority
    # over incidental words like "lavas" in the dish title.
    if has_any(category_text, (
        "hot dog", "hotdog", "хот-дог", "хот дог",
        "shawarma", "шаверм", "шаурм", "kebab", "kebabi",
        "doner", "döner",
    )):
        return "main_courses"

    # A dedicated Lavash category is more specific than ingredients in its title.
    if has_any(category_text, ("lavash", "lavas", "lavass", "лаваш")):
        return "tortillas"
    if has_any(category_text, ("tortilla", "тортиль")):
        return "tortillas"
    if has_any(name_text, ("lavash", "lavas", "lavass", "лаваш", "wrap", "tortilla", "тортиль", "врап")):
        return "tortillas"

    # Product names/categories are more reliable than secondary labels on
    # several cards (e.g. a fish burger can also display a drinks tag).
    if has_any(category_text, _BURGER_MARKERS) or has_any(name_text, _BURGER_MARKERS):
        return "burgers"

    if has_any(category_text, _DESSERT_MARKERS) or has_any(name_text, _DESSERT_MARKERS):
        return "desserts"

    if has_any(category_text, _SALAD_MARKERS) or has_any(name_text, _SALAD_MARKERS):
        return "salads"

    if has_any(category_text, _SOUP_MARKERS) or has_any(name_text, _SOUP_MARKERS):
        return "soups"

    if has_any(category_text, _NOODLE_MARKERS) or has_any(name_text, _NOODLE_MARKERS):
        # "Mussels" appears in the noodle section on this site, so the section
        # label should be retained unless the item clearly belongs elsewhere.
        return "noodles"

    if has_any(category_text, _SAUCE_MARKERS) or has_any(name_text, _SAUCE_MARKERS):
        return "sauces"

    if has_any(category_text, _BREAKFAST_MARKERS):
        return "breakfast"

    if has_any(category_text, _APPETIZER_CATEGORY_MARKERS):
        return "appetizers"

    if has_any(category_text, _DRINK_CATEGORY_MARKERS):
        if has_any(category_text, _ALCOHOL_MARKERS):
            return "drinks"
        return "drinks"

    if has_any(category_text, _SIDE_MARKERS):
        return "sides"

    # The generic Eine page also contains plain side dishes.
    if has_any(name_text, _SIDE_MARKERS) and not has_any(
        name_text,
        ("chicken", "kana", "куриц", "beef", "loomaliha", "говядин", "fish", "kala", "рыб", "liha", "мяс"),
    ):
        return "sides"

    if has_any(all_text, _ALCOHOL_MARKERS):
        return "drinks"
    if has_any(name_text, _DRINK_NAME_MARKERS) or re.search(
        r"\b(?:tea|tee|gin|whisky|whiskey|vodka|rum|coffee|kohv)\b",
        name_text,
    ):
        return "drinks"

    if has_any(category_text, _MAIN_CATEGORY_MARKERS):
        return "main_courses"

    # Hot dogs, kebabs and shawarma do not have dedicated shared product types.
    # Keep them in the existing main-course group instead of inventing categories.
    if has_any(all_text, (
        "hot dog", "hotdog", "hot-dog", "хот-дог", "хот дог",
        "kebab", "kebabi", "doner", "döner", "shawarma", "шаверм", "шаурм",
        "šaslõkk", "шашлык", "praad",
    )):
        return "main_courses"

    if has_any(all_text, (
        "chicken", "kana", "куриц", "beef", "loomaliha", "говядин", "sealiha",
        "pork", "свинин", "fish", "kala", "рыб", "shrimp", "krevet",
        "seafood", "mereannid", "mussels", "пельмен", "dumpling", "pelmeen",
    )):
        if has_any(all_text, ("пельмен", "dumpling", "pelmeen")):
            return "dumplings"
        return "main_courses"

    return "main_courses"


def _discover_category_urls(soup, current_url, language):
    """Find all product-category pages in the site's navigation."""
    current_host = urlparse(current_url).netloc.casefold()
    found = []
    for link in soup.select("a[href]"):
        href = clean_text(link.get("href", ""))
        if not href or href == "#":
            continue
        url = urljoin(current_url, href)
        parsed = urlparse(url)
        if parsed.netloc.casefold() not in {current_host, "ida-toit.ee", "www.ida-toit.ee"}:
            continue
        if not _is_category_url(url):
            continue

        path = parsed.path.casefold()
        is_ru_path = path == "/ru" or path.startswith("/ru/")
        if language == "ru" and not is_ru_path:
            continue
        if language == "et" and is_ru_path:
            continue

        # Ignore any current-page parameters (sorting, cart, tracking).
        url = urlunparse(parsed._replace(query="", fragment=""))
        if url not in found:
            found.append(url)
    return found


def _catalog_context(url):
    """Get a comparable category key and zero-based page offset for RU/ET."""
    parsed = urlparse(url)
    segments = [part for part in parsed.path.strip("/").split("/") if part]
    if segments and segments[0].casefold() == "ru":
        segments = segments[1:]

    category_key = "shop"
    lowered_segments = [part.casefold() for part in segments]
    category_index = None
    if "tootekategooria" in lowered_segments:
        category_index = lowered_segments.index("tootekategooria")
    elif "product-category" in lowered_segments:
        category_index = lowered_segments.index("product-category")

    if category_index is not None and category_index + 1 < len(segments):
        category_segments = segments[category_index + 1:]
        if "page" in [part.casefold() for part in category_segments]:
            page_index = [part.casefold() for part in category_segments].index("page")
            category_segments = category_segments[:page_index]
        category_key = "/".join(category_segments).casefold() or "shop"

    page_number = 1
    lowered_segments = [part.casefold() for part in segments]
    if "page" in lowered_segments:
        index = lowered_segments.index("page")
        if index + 1 < len(segments) and segments[index + 1].isdigit():
            page_number = max(1, int(segments[index + 1]))

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("product-page", "paged", "page"):
        try:
            if key in query:
                page_number = max(1, int(query[key]))
                break
        except (TypeError, ValueError):
            pass

    return category_key, (page_number - 1) * 12


def _pagination_urls(soup, current_url, language):
    """Return product-catalog pagination links only, not category/product links."""
    containers = soup.select(
        "nav.woocommerce-pagination, .woocommerce-pagination, "
        ".woocommerce nav.pagination, .pagination"
    )
    links = []
    for container in containers:
        links.extend(container.select("a[href]"))

    if not links:
        links = soup.select("a.page-numbers[href], a[rel='next'][href]")

    # Some theme versions render the pager as plain anchors without WordPress
    # pagination classes, so also find explicit /page/N and product-page links.
    if not links:
        for link in soup.select("a[href]"):
            href = clean_text(link.get("href", ""))
            parsed_link = urlparse(urljoin(current_url, href))
            if re.search(r"/page/\d+/?$", parsed_link.path, re.IGNORECASE):
                links.append(link)
                continue
            query_keys = {key.casefold() for key, _ in parse_qsl(parsed_link.query)}
            if query_keys.intersection({"product-page", "paged", "page"}):
                links.append(link)

    current_host = urlparse(current_url).netloc.casefold()
    result = []
    for link in links:
        href = clean_text(link.get("href", ""))
        if not href or href == "#":
            continue
        url = urljoin(current_url, href)
        parsed = urlparse(url)
        if parsed.netloc.casefold() not in {current_host, "ida-toit.ee", "www.ida-toit.ee"}:
            continue
        if "add-to-cart" in parsed.query.casefold():
            continue

        path = parsed.path.casefold()
        is_ru_path = path == "/ru" or path.startswith("/ru/")
        if language == "ru" and not is_ru_path:
            continue
        if language == "et" and is_ru_path:
            continue

        # Follow the site's own pagination URL as-is. Its custom "show all"
        # link uses a malformed per_page value on some responses, so do not
        # inject theme-specific page-size parameters into every request.
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.pop("add-to-cart", None)
        url = urlunparse(parsed._replace(
            query=urlencode(query) if query else "",
            fragment="",
        ))
        if url != current_url and url not in result:
            result.append(url)

    return result


def parse_language(session, language):
    """Download one language's catalog and follow pagination until exhausted."""
    initial_url = build_catalog_url(language)
    started_at = time.monotonic()
    queue = [initial_url]
    visited_urls = set()
    seen_products = set()
    records = []

    while (
        queue
        and len(visited_urls) < MAX_CATALOG_PAGES
        and time.monotonic() - started_at < MAX_LANGUAGE_SECONDS
    ):
        url = queue.pop(0)
        if url in visited_urls:
            continue
        visited_urls.add(url)

        try:
            response = _get_page(session, url)
        except requests.RequestException as error:
            print(f"[Break Time/{language}] Не удалось загрузить {url}: {error}")
            if getattr(getattr(error, "response", None), "status_code", None) == 429:
                print(
                    f"[Break Time/{language}] Останавливаю обход языка, "
                    "чтобы не продолжать запросы после ограничения сайта."
                )
                break
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        cards = get_cards(soup)
        page_record_count = 0
        category_key, page_offset = _catalog_context(response.url)

        # The homepage has only featured products; the full catalog lives
        # on separate category pages discovered in the site's own navigation.
        for category_url in _discover_category_urls(soup, response.url, language):
            if category_url not in visited_urls and category_url not in queue:
                queue.append(category_url)

        for card_index, card in enumerate(cards):
            name = get_name(card)
            if not name:
                continue

            price = get_price(card)
            if price is None or price <= 0:
                continue

            categories = get_categories(card)
            category = ", ".join(categories)
            product_type = get_product_type(category, name)
            source_id = get_card_identifier(card)
            variant = None
            this_position = page_offset + card_index

            # Deduplicate repeated cards without conflating distinct WooCommerce IDs.
            if source_id:
                marker = ("source", source_id, variant or "")
            else:
                marker = (
                    "name",
                    normalize_product_key(name),
                    product_type,
                    variant or "",
                )
            if marker in seen_products:
                continue
            seen_products.add(marker)

            if source_id:
                dish_code = f"break-time:{source_id}"
            else:
                digest = hashlib.sha1(
                    normalize_product_key(name).encode("utf-8")
                ).hexdigest()[:14]
                dish_code = f"break-time:name:{digest}"

            records.append({
                "dish_code": dish_code,
                "source_id": source_id,
                "name": name,
                "price": price,
                "price_variant": variant,
                "category": category or None,
                "product_type": product_type,
                "language": language,
                "catalog_category_key": category_key,
                "catalog_position": this_position,
            })
            page_record_count += 1

        print(
            f"[Break Time/{language}] Страница {len(visited_urls)}: "
            f"карточек={len(cards)}, новых записей={page_record_count}",
            flush=True,
        )

        for next_url in _pagination_urls(soup, url, language):
            if next_url not in visited_urls and next_url not in queue:
                queue.append(next_url)

    if queue:
        if len(visited_urls) >= MAX_CATALOG_PAGES:
            reason = f"лимит {MAX_CATALOG_PAGES} страниц"
        else:
            reason = f"лимит времени {MAX_LANGUAGE_SECONDS} секунд"
        print(
            f"[Break Time/{language}][ВНИМАНИЕ] Достигнут {reason}; "
            "часть каталога могла не загрузиться.",
            flush=True,
        )

    print(f"[Break Time/{language}] Всего уникальных записей: {len(records)}")
    return records


def _record_variant_key(record):
    return normalize_key(record.get("price_variant"))


def _record_name_key(record):
    return normalize_product_key(record.get("name"))


def _deduplicate_records(records):
    result = []
    seen = set()
    for record in records:
        source_id = record.get("source_id")
        variant = _record_variant_key(record)
        if source_id:
            key = ("source", source_id, variant)
        else:
            key = (
                "name",
                _record_name_key(record),
                record.get("product_type"),
                variant,
            )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _find_translation(record, candidates):
    """Match by shared source ID, then by an unambiguous normalized product name."""
    source_id = record.get("source_id")
    variant = _record_variant_key(record)

    if source_id:
        matches = [
            item for item in candidates
            if item.get("source_id") == source_id
            and _record_variant_key(item) == variant
        ]
        if len(matches) == 1:
            return matches[0]

    name_key = _record_name_key(record)
    if not name_key:
        return None

    matches = [
        item for item in candidates
        if _record_name_key(item) == name_key
        and item.get("product_type") == record.get("product_type")
        and _record_variant_key(item) == variant
    ]
    if len(matches) == 1:
        return matches[0]

    # If duplicate names exist, only accept a price+category match when it is unique.
    same_price = [
        item for item in matches
        if item.get("price") is not None
        and record.get("price") is not None
        and abs(float(item["price"]) - float(record["price"])) < 0.001
        and normalize_key(item.get("category")) == normalize_key(record.get("category"))
    ]
    if len(same_price) == 1:
        return same_price[0]

    # Translated product names may be completely different and prices in the
    # language copies can temporarily differ. Match only when the item occupies
    # the same position in the same permalink category and has the same shared
    # product type and serving-size variant.
    position = record.get("catalog_position")
    category_key = record.get("catalog_category_key")
    if position is not None and category_key and category_key != "shop":
        positional_matches = [
            item for item in candidates
            if item.get("catalog_position") == position
            and item.get("catalog_category_key") == category_key
            and item.get("product_type") == record.get("product_type")
            and _record_variant_key(item) == variant
        ]
        if len(positional_matches) == 1:
            print(
                "[Break Time] Переводы сопоставлены по категории и позиции: "
                f"{record.get('name')!r} / {positional_matches[0].get('name')!r}"
            )
            return positional_matches[0]

    return None


def merge_language_records(russian_records, estonian_records):
    """Merge RU/ET translations without guessing when a match is ambiguous."""
    russian_records = _deduplicate_records(russian_records)
    estonian_records = _deduplicate_records(estonian_records)

    unused_et = list(estonian_records)
    merged = []

    for ru_row in russian_records:
        et_row = _find_translation(ru_row, unused_et)
        if et_row is not None:
            unused_et.remove(et_row)

        price_ru = ru_row.get("price")
        price_et = et_row.get("price") if et_row is not None else None
        if (
            price_ru is not None
            and price_et is not None
            and abs(float(price_ru) - float(price_et)) >= 0.001
        ):
            print(
                "[Break Time][ВНИМАНИЕ] Различаются цены "
                f"для {ru_row.get('name')!r}: RU={price_ru:.2f} €, "
                f"ET={price_et:.2f} €; сохраняю цену RU."
            )

        name_ru = ru_row.get("name")
        name_et = et_row.get("name") if et_row is not None else None
        category_ru_source = ru_row.get("category")
        category_et_source = et_row.get("category") if et_row is not None else None
        name_text = f"{name_ru or ''} {name_et or ''}"
        category_text = f"{category_ru_source or ''} {category_et_source or ''}"
        product_type = get_product_type(category_text, name_text)

        category_ru = canonical_category_ru(
            product_type,
            category_ru=category_ru_source,
            category_et=category_et_source,
            dish_name=name_text,
        )
        category_et = canonical_category_et(
            product_type,
            category_ru=category_ru,
            category_et=category_et_source,
            dish_name=name_text,
        )

        merged.append({
            "dish_code": ru_row.get("dish_code") or (
                et_row.get("dish_code") if et_row is not None else None
            ),
            "dish_name": name_ru or name_et,
            "dish_name_ru": name_ru,
            "dish_name_et": name_et,
            "category_ru": category_ru or None,
            "category_et": category_et or None,
            "price": price_ru if price_ru is not None else price_et,
            "price_variant": ru_row.get("price_variant") or (
                et_row.get("price_variant") if et_row is not None else None
            ),
            "product_type": product_type,
        })

    # Keep Estonian-only products rather than dropping items with no RU translation.
    for et_row in unused_et:
        name_et = et_row.get("name")
        category_et_source = et_row.get("category")
        product_type = get_product_type(category_et_source, name_et)
        category_ru = canonical_category_ru(
            product_type,
            category_et=category_et_source,
            dish_name=name_et,
        )
        category_et = canonical_category_et(
            product_type,
            category_ru=category_ru,
            category_et=category_et_source,
            dish_name=name_et,
        )
        merged.append({
            "dish_code": et_row.get("dish_code"),
            "dish_name": name_et,
            "dish_name_ru": None,
            "dish_name_et": name_et,
            "category_ru": category_ru or None,
            "category_et": category_et or None,
            "price": et_row.get("price"),
            "price_variant": et_row.get("price_variant"),
            "product_type": product_type,
        })

    print(
        f"[Break Time] После объединения: {len(merged)} записей "
        f"(RU={len(russian_records)}, ET={len(estonian_records)})"
    )
    translated = sum(
        1 for row in merged if row.get("dish_name_ru") and row.get("dish_name_et")
    )
    print(f"[Break Time] Записей с обоими названиями: {translated}")
    return merged


def parse_menu():
    """Parse both language catalogs and return rows compatible with main.py."""
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        russian_records = parse_language(session, "ru")
    except Exception as error:
        print(f"[Break Time/ru] Ошибка парсинга: {error}")
        russian_records = []

    try:
        estonian_records = parse_language(session, "et")
    except Exception as error:
        print(f"[Break Time/et] Ошибка парсинга: {error}")
        estonian_records = []

    if not russian_records and not estonian_records:
        print("[Break Time] Не удалось получить меню ни на одном языке.")
        return []

    return merge_language_records(russian_records, estonian_records)


if __name__ == "__main__":
    menu = parse_menu()
    print(f"Break Time Burger & Wrap: получено {len(menu)} блюд.")
    for item in menu[:10]:
        print(
            f"{item.get('dish_name')} | {item.get('category_ru')} / "
            f"{item.get('category_et')} | {item.get('price')} €"
        )
