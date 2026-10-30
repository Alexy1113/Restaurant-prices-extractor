"""Parser for Peetri Pizza Jõhvi Bussijaam.

Only the pizzeria's pizza section is imported. Other menu sections (pasta,
drinks and combos) are intentionally not classified as pizzas.
"""
import json
import re
import time
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


def extract_initial_react_state(html):
    """Decode the server-provided JSON state used by Peetri Pizza's React app."""
    anchor = (html or "").find("window.initialReactState")
    if anchor < 0:
        return None

    object_start = (html or "").find("{", anchor)
    if object_start < 0:
        return None

    try:
        state, _ = json.JSONDecoder().raw_decode(html[object_start:])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    return state if isinstance(state, dict) else None


PIZZA_SIZE_ORDER = ("small", "large", "family")
PIZZA_SIZE_LABELS = {
    "small": "small",
    "large": "large",
    "family": "family",
}
REQUEST_DELAY_SECONDS = 0.15


def fetch_pizza_size_prices(session, product):
    """Load the size-selection step and return its complete availableSizes map."""
    url = product.get("urlAddNew")
    if not url:
        return {}

    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    detail_state = extract_initial_react_state(response.text)
    if not isinstance(detail_state, dict):
        return {}

    prices = detail_state.get("availableSizes")
    if not isinstance(prices, dict):
        return {}

    result = {}
    for size in PIZZA_SIZE_ORDER:
        price = parse_price(prices.get(size))
        if price is not None and price > 0:
            result[size] = price
    return result


def _pizza_description(product):
    toppings = product.get("originalToppings") or []
    return ", ".join(
        clean_text(topping.get("name"))
        for topping in toppings
        if isinstance(topping, dict)
        and topping.get("isOriginal", True)
        and not topping.get("isRemoved", False)
        and clean_text(topping.get("name"))
    ) or None


def parse_react_pizzas(state, session=None):
    """Return a separate price row for each available pizza size."""
    products_data = state.get("productsData") if isinstance(state, dict) else None
    products = products_data.get("pizzas") if isinstance(products_data, dict) else None
    if not isinstance(products, list):
        return []

    parsed = []
    seen_codes = set()
    failed_size_lookups = 0

    for index, product in enumerate(products):
        if not isinstance(product, dict):
            continue

        name = clean_text(product.get("name"))
        template_id = product.get("templateId") or product.get("id")
        if not name or template_id is None:
            continue

        size_prices = {}
        if session is not None:
            try:
                size_prices = fetch_pizza_size_prices(session, product)
            except requests.RequestException as error:
                failed_size_lookups += 1
                print(
                    f"[Peetri Pizza/Jõhvi] Не удалось получить размеры "
                    f"{name}: {error}"
                )
            if index < len(products) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)

        # A live product with a working configurator returns all three size
        # prices. If the detail request fails, retain the site's minimum
        # advertised price as a small-size fallback rather than losing it.
        if not size_prices:
            minimum_price = parse_price(product.get("minPrice"))
            if minimum_price is not None and minimum_price > 0:
                size_prices = {"small": minimum_price}

        if set(size_prices) != set(PIZZA_SIZE_ORDER):
            print(
                f"[Peetri Pizza/Jõhvi][Размеры] {name} (templateId={template_id}): "
                f"получены {size_prices}; ожидаются {list(PIZZA_SIZE_ORDER)}"
            )

        description = _pizza_description(product)
        for size in PIZZA_SIZE_ORDER:
            price = size_prices.get(size)
            if price is None:
                continue

            code = f"peetri-johvi:pizza:{template_id}:{size}"
            if code in seen_codes:
                continue
            seen_codes.add(code)

            parsed.append({
                "dish_code": code,
                "dish_name": name,
                "dish_name_et": name,
                "dish_name_ru": None,
                "description_et": description,
                "category_ru": "Пицца",
                "category_et": "Pitsad",
                "product_type": "pizzas",
                "price": price,
                "price_variant": size,
            })

    if failed_size_lookups:
        print(
            f"[Peetri Pizza/Jõhvi] Конфигуратор размеров не ответил "
            f"для {failed_size_lookups} из {len(products)} пицц."
        )
    return parsed


def parse_react_pastas(state):
    """Read the four pasta dishes from productsData.simpleProducts."""
    products_data = state.get("productsData") if isinstance(state, dict) else None
    products = products_data.get("simpleProducts") if isinstance(products_data, dict) else None
    if not isinstance(products, list):
        return []

    parsed = []
    for product in products:
        if not isinstance(product, dict):
            continue

        category = normalize_text(product.get("categoryName"))
        category_en = normalize_text(product.get("categoryNameEnglish"))
        if category not in {"pastad", "pastas", "pasta"} and category_en not in {"pastas", "pasta"}:
            continue

        name = clean_text(product.get("name"))
        price = parse_price(product.get("unitPrice"))
        product_id = product.get("productId") or product.get("id")
        if not name or price is None or price <= 0 or product_id is None:
            continue

        parsed.append({
            "dish_code": f"peetri-johvi:pasta:{product_id}",
            "dish_name": name,
            "dish_name_et": name,
            "dish_name_ru": None,
            "description_et": clean_text(product.get("description")) or None,
            "category_ru": "Паста",
            "category_et": "Pastad",
            "product_type": "pasta",
            "price": price,
            "price_variant": clean_text(product.get("packageSize")) or None,
        })
    return parsed


def _combo_description(combo):
    details = []
    for group_key, label in (("pizzas", "Pizza"), ("products", "Toode")):
        items = combo.get(group_key) or []
        counts = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name"))
            if not name:
                continue
            variant = clean_text(item.get("size") or item.get("details"))
            key = (name, variant)
            counts[key] = counts.get(key, 0) + 1
        for (name, variant), count in counts.items():
            description = f"{count} × {name}" if count > 1 else name
            if variant:
                description += f" ({variant})"
            details.append(description)
    return " + ".join(details) or None


def parse_react_combos(state):
    """Read the combo products, using the discounted price currently shown."""
    products_data = state.get("productsData") if isinstance(state, dict) else None
    combos = products_data.get("combos") if isinstance(products_data, dict) else None
    if not isinstance(combos, list):
        return []

    parsed = []
    for combo in combos:
        if not isinstance(combo, dict):
            continue
        name = clean_text(combo.get("name"))
        combo_id = combo.get("id")
        price_info = combo.get("price") or {}
        price = parse_price(
            price_info.get("discounted")
            if isinstance(price_info, dict) and price_info.get("discounted") is not None
            else price_info.get("original") if isinstance(price_info, dict) else None
        )
        if not name or combo_id is None or price is None or price <= 0:
            continue

        parsed.append({
            "dish_code": f"peetri-johvi:combo:{combo_id}",
            "dish_name": name,
            "dish_name_et": name,
            "dish_name_ru": None,
            "description_et": _combo_description(combo),
            "category_ru": "Сеты",
            "category_et": "Komplektid",
            "product_type": "sets",
            "price": price,
            "price_variant": None,
        })
    return parsed


def parse_react_state(state, session=None):
    """Parse pizzas with size prices, pasta dishes, and combo offers."""
    return (
        parse_react_pizzas(state, session=session)
        + parse_react_pastas(state)
        + parse_react_combos(state)
    )


def parse_html(html):
    """Parse only pizza records from a Peetri Pizza pizzeria page."""
    initial_state = extract_initial_react_state(html)
    if initial_state:
        react_products = parse_react_state(initial_state)
        if react_products:
            return react_products

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
    session = requests.Session()
    session.headers.update(HEADERS)
    response = session.get(
        MENU_URL,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    state = extract_initial_react_state(response.text)
    if state:
        dishes = parse_react_state(state, session=session)
        pizza_count = sum(row["product_type"] == "pizzas" for row in dishes)
        pasta_count = sum(row["product_type"] == "pasta" for row in dishes)
        combo_count = sum(row["product_type"] == "sets" for row in dishes)
        print(
            f"[Peetri Pizza/Jõhvi] Пиццы с вариантами размеров: {pizza_count}; "
            f"паста: {pasta_count}; комбо: {combo_count}; всего ценовых строк: {len(dishes)}"
        )
        sizes_per_pizza = {}
        for row in dishes:
            if row["product_type"] == "pizzas":
                base_code = row["dish_code"].rsplit(":", 1)[0]
                sizes_per_pizza.setdefault(base_code, set()).add(row["price_variant"])
        incomplete = {
            code: sorted(sizes)
            for code, sizes in sizes_per_pizza.items()
            if sizes != set(PIZZA_SIZE_ORDER)
        }
        if incomplete:
            print(
                f"[Peetri Pizza/Jõhvi] Внимание: {len(incomplete)} пицц имеют "
                f"не все варианты размеров: {incomplete}"
            )
        return dishes

    dishes = parse_html(response.text)
    print(
        f"[Peetri Pizza/Jõhvi] React state не найден; HTML fallback вернул "
        f"{len(dishes)} записей."
    )
    return dishes
