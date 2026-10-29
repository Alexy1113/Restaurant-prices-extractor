
import re
import requests
from bs4 import BeautifulSoup


MENU_URLS = {
    "ru": "https://johvi.oceansushi.ee/ru/menu/",
    "et": "https://johvi.oceansushi.ee/menu/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
}

PRICE_RE = re.compile(
    r"€\s*(\d+(?:[.,]\d{1,2})?)|"
    r"(\d+(?:[.,]\d{1,2})?)\s*€"
)

CODE_RE = re.compile(r"^\s*(\d{1,4})\s*\.?\s*")

# Formats such as "8tk 9.60, 12tk 11.60 €" in product descriptions.
VARIANT_PRICE_RE = re.compile(
    r"(?P<count>\d+)\s*(?:tk\.?|шт\.?|pcs?\.?)\s*(?:€\s*)?"
    r"(?P<price>\d+(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def get_product_type(category, name):
    """
    Определяет общую категорию блюда.

    category — категория из меню ресторана.
    name     — название блюда.

    Возвращает постоянный код категории, например:
    "sushi_rolls", "drinks", "soups".

    Эти коды не зависят от языка сайта.
    Поэтому разные рестораны можно сравнивать между собой.
    """

    # Приводим значения к строкам и нижнему регистру.
    # Если значение отсутствует (None), используем пустую строку.
    category_text = str(category or "").casefold()
    name_text = str(name or "").casefold()

    # Объединяем категорию и название.
    # Иногда тип можно понять по категории, а иногда — по названию.
    text = f"{category_text} {name_text}"

    # Вспомогательная функция:
    # возвращает True, если хотя бы одно ключевое слово
    # найдено в категории или названии блюда.
    def has_any(keywords):
        return any(keyword in text for keyword in keywords)

    # --------------------------------------------------
    # 1. НАПИТКИ
    # Проверяем первыми, потому что напитки могут иметь
    # названия брендов без слов "напиток" или "вода".
    # --------------------------------------------------
    if has_any([
        "напит", "вода", "сок", "лимонад", "пиво", "вино",
        "шампан", "кофе", "чай", "тоник", "безалкоголь",
        "drink", "beverage", "water", "juice", "lemonade",
        "beer", "wine", "champagne", "coffee", "tea",
        "joog", "jook", "vesi", "mahl", "limonaad",
        "õlu", "vein", "kohv", "toonik", "alkoholivaba",
        "coca-cola", "coca cola", "fanta", "sprite",
        "fuzetea", "sinebrychoff", "somersby",
        "prosecco", "moscato", "pinot", "saku",
        "raasiku", "kirin", "haage", "lacrima",
        "maschio", "takara plum", "armenia", "gin "
    ]):
        return "drinks"

    # --------------------------------------------------
    # 2. ДЕСЕРТЫ
    # Проверяем до пельменей и роллов, чтобы, например,
    # сладкие пельмени не попали в закуски.
    # --------------------------------------------------
    if has_any([
        "десерт", "морожен", "чизкейк", "моти", "сладк",
        "dessert", "ice cream", "cake", "sweet",
        "magustoit", "magusad", "jäätis", "kook",
        "maasika-banaani rull"
    ]):
        return "desserts"

    # --------------------------------------------------
    # 3. НАБОРЫ И КОМБО
    # Разные рестораны могут называть их по-разному:
    # Set, Combo, набор, сет или комплект.
    # --------------------------------------------------
    if has_any([
        "комбо", "combo", "комплект", "набор",
        "сеты", "сет ", "set menu", "sushi set", "sets",
        "komplekt", "komplektid"
    ]):
        return "sets"

    # --------------------------------------------------
    # 4. ПЕЛЬМЕНИ И DIM SUM
    # Это отдельная группа, а не суши и не роллы.
    # --------------------------------------------------
    if has_any([
        "dim sum", "dim-sum", "дим сам",
        "dumpling", "pelmeen"
    ]):
        return "dumplings"

    # --------------------------------------------------
    # 5. ОТДЕЛЬНЫЕ ВИДЫ СУШИ
    # Более конкретные типы проверяем раньше общих роллов.
    # --------------------------------------------------
    if has_any(["сашими", "sashimi"]):
        return "sashimi"

    if has_any(["нигири", "nigiri"]):
        return "nigiri"

    if has_any(["гункан", "gunkan"]):
        return "gunkan"

    if has_any(["инари", "inari"]):
        return "inari"

    if has_any(["хосомаки", "hosomaki"]):
        return "hosomaki"

    # Темпура может быть самостоятельной категорией меню.
    if has_any(["темпура", "tempura"]):
        return "tempura"

    # --------------------------------------------------
    # 6. ЗАКУСКИ
    # Проверяем до общих роллов, чтобы спринг-роллы
    # не классифицировались как суши-роллы.
    # --------------------------------------------------
    if has_any([
        "закуск", "appetizer", "starter", "snack",
        "suupiste", "suupisted", "спринг-ролл",
        "spring roll", "kevadrull"
    ]):
        return "appetizers"

    # --------------------------------------------------
    # 7. ОБЫЧНЫЕ СУШИ И РОЛЛЫ
    # --------------------------------------------------
    if has_any([
        "ролл", "маки", "sushi roll", "sushi",
        "maki", "roll", "rull"
    ]):
        return "sushi_rolls"

    # --------------------------------------------------
    # 8. СУПЫ
    # Некоторые супы определяются по конкретному названию,
    # даже если в нём нет слова "суп".
    # --------------------------------------------------
    if has_any([
        "суп", "soup", "supid", "suimono",
        "том ям", "tom yam", "том кха", "tom kha",
        "мисо", "miso"
    ]):
        return "soups"

    # --------------------------------------------------
    # 9. САЛАТЫ
    # --------------------------------------------------
    if has_any(["салат", "salad", "salat"]):
        return "salads"

    # --------------------------------------------------
    # 10. БОУЛЫ
    # --------------------------------------------------
    if has_any(["боул", "bowl"]):
        return "bowls"

    # --------------------------------------------------
    # 11. ЛАПША
    # --------------------------------------------------
    if has_any([
        "лапша", "nuudel", "nuudlid",
        "noodle", "klaasnuudlid", "tatranuudlid"
    ]):
        return "noodles"

    # --------------------------------------------------
    # 12. ОСНОВНЫЕ БЛЮДА
    # --------------------------------------------------
    if has_any([
        "основное блюдо", "основные блюда", "горячие блюда",
        "main course", "main courses", "põhiroad", "praed"
    ]):
        return "main_courses"

    # --------------------------------------------------
    # 13. ЕСЛИ НЕ УДАЛОСЬ ОПРЕДЕЛИТЬ ТИП
    # Не угадываем категорию: сохраняем безопасный вариант.
    # Позже можно будет расширить список ключевых слов.
    # --------------------------------------------------
    return "other"


def get_price(card):
    for selector in [
        ".ee-post__price",
        ".price",
        ".woocommerce-Price-amount",
        "[class*='price']",
    ]:
        for element in card.select(selector):
            match = PRICE_RE.search(
                element.get_text(" ", strip=True)
            )
            if match:
                value = match.group(1) or match.group(2)
                return float(value.replace(",", "."))

    clone = BeautifulSoup(str(card), "html.parser")

    for element in clone.select(
        "button, .button, [class*='cart'], "
        "[class*='addon'], [class*='option']"
    ):
        element.decompose()

    match = PRICE_RE.search(clone.get_text(" ", strip=True))

    if match:
        value = match.group(1) or match.group(2)
        return float(value.replace(",", "."))

    return None


def get_price_variants(card):
    """Reads quantity/price pairs, for example '8tk 9.60, 12tk 11.60 €'."""
    text = clean_text(card.get_text(" ", strip=True))
    found = {}

    for match in VARIANT_PRICE_RE.finditer(text):
        count = int(match.group("count"))
        price = float(match.group("price").replace(",", "."))

        # Ignore repeated copies of the same pair caused by duplicated HTML text.
        if count not in found:
            found[count] = price
        elif found[count] != price:
            print(
                f"[Ocean Sushi][ВНИМАНИЕ] Для размера {count} tk "
                f"найдены разные цены: {found[count]:.2f} и {price:.2f} €."
            )

    return [(count, found[count]) for count in sorted(found)]


def get_default_price_variant(category):
    """Ordinary maki are sold as six pieces unless the card specifies sizes."""
    category_text = clean_text(category).casefold()

    if any(word in category_text for word in ("хосомаки", "hosomaki")):
        return None

    if "маки" in category_text or "maki" in category_text:
        return "6 tk"

    return None


def make_variant_slug(value):
    """Creates a stable ASCII suffix for a size-specific dish_code."""
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-") or "unknown"


def get_name_and_code(card):
    title = card.select_one(
        ".ee-post__title__heading, "
        ".product_title, "
        ".woocommerce-loop-product__title, "
        ".dish-title"
    )

    if not title:
        return None, None

    # Сначала читаем название вместе с кодом.
    raw_name = clean_text(title.get_text(" ", strip=True))
    code_match = CODE_RE.match(raw_name)
    dish_code = code_match.group(1) if code_match else None

    # Убираем номер из названия.
    name = CODE_RE.sub("", raw_name).strip(" .-–—")

    return name or None, dish_code



def get_category_before(card, soup):
    """Находит предыдущий заголовок раздела,
    пропуская заголовки блюд с числовыми кодами.
    """
    for heading in card.find_all_previous("h2"):
        category = clean_text(
            heading.get_text(" ", strip=True)
        )

        if not category:
            continue

        # Заголовок вида "224. Стеклянная лапша..."
        # — это блюдо, а не категория меню.
        if CODE_RE.match(category):
            continue

        return category

    return "Без категории"



def parse_language(language, url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    dishes = []

    for card in soup.select(".product"):
        # Не обрабатываем внешние карточки, внутри которых
        # находятся другие карточки товаров.
        nested_products = card.select(".product")
        if any(
            nested.select_one(".ee-post__title__heading")
            for nested in nested_products
        ):
            continue

        name, dish_code = get_name_and_code(card)

        if not name:
            continue

        if name.casefold() in {
            "в корзину",
            "добавить в корзину",
            "купить",
            "lisa ostukorvi",
            "ostukorvi",
        }:
            continue

        category = get_category_before(card, soup)

        # If a card lists several sizes and prices, create one record per size.
        price_variants = get_price_variants(card)
        if price_variants:
            for count, variant_price in price_variants:
                dishes.append({
                    "dish_code": dish_code,
                    "name": name,
                    "price": variant_price,
                    "price_variant": f"{count} tk",
                    "category": category,
                    "language": language,
                })
            continue

        # Otherwise use the card's normal price and infer six pieces for
        # products in the ordinary Maki section.
        price = get_price(card)
        if price is None:
            continue

        dishes.append({
            "dish_code": dish_code,
            "name": name,
            "price": price,
            "price_variant": get_default_price_variant(category),
            "category": category,
            "language": language,
        })

    print(
        f"[Ocean Sushi/{language}] "
        f"Получено блюд: {len(dishes)}"
    )

    return dishes


def parse_menu():
    try:
        ru_dishes = parse_language("ru", MENU_URLS["ru"])
        et_dishes = parse_language("et", MENU_URLS["et"])

        # Match Russian and Estonian cards by both product code and size.
        # This keeps 8 tk and 12 tk prices as separate records.
        merged = {}

        def variant_key(value):
            return clean_text(value).casefold() if value else ""

        for dish in ru_dishes:
            code = dish["dish_code"]
            variant = dish.get("price_variant")
            if code:
                key = ("code", str(code), variant_key(variant))
            else:
                key = ("ru", dish["name"].casefold(), variant_key(variant))

            if key not in merged:
                merged[key] = {
                    "dish_code": code,
                    "dish_name_ru": None,
                    "dish_name_et": None,
                    "category_ru": None,
                    "category_et": None,
                    "price_ru": None,
                    "price_et": None,
                    "price_variant": variant,
                }

            merged[key]["dish_name_ru"] = dish["name"]
            merged[key]["category_ru"] = dish["category"]
            merged[key]["price_ru"] = dish["price"]

        for dish in et_dishes:
            code = dish["dish_code"]
            variant = dish.get("price_variant")
            if code:
                key = ("code", str(code), variant_key(variant))
            else:
                key = ("et", dish["name"].casefold(), variant_key(variant))

            if key not in merged:
                merged[key] = {
                    "dish_code": code,
                    "dish_name_ru": None,
                    "dish_name_et": None,
                    "category_ru": None,
                    "category_et": None,
                    "price_ru": None,
                    "price_et": None,
                    "price_variant": variant,
                }

            merged[key]["dish_name_et"] = dish["name"]
            merged[key]["category_et"] = dish["category"]
            merged[key]["price_et"] = dish["price"]

        # A product with size prices needs a stable unique code per size.
        # Keep the smallest size's original code so an existing DB row is
        # updated instead of duplicated; append a suffix to additional sizes.
        rows_by_code = {}
        for item in merged.values():
            if item["dish_code"] is not None:
                rows_by_code.setdefault(str(item["dish_code"]), []).append(item)

        def size_sort_key(item):
            match = re.match(r"\s*(\d+)", str(item.get("price_variant") or ""))
            return (
                int(match.group(1)) if match else 10**9,
                str(item.get("price_variant") or "").casefold(),
            )

        for base_code, items in rows_by_code.items():
            items.sort(key=size_sort_key)
            for index, item in enumerate(items):
                if index == 0:
                    item["output_dish_code"] = base_code
                else:
                    suffix = make_variant_slug(item.get("price_variant"))
                    item["output_dish_code"] = f"{base_code}:variant:{suffix}"

        # A few cards may lack a numeric product code. Keep the first size
        # matched by name (so an existing row can be updated) and give every
        # additional size a deterministic code so different prices don't
        # overwrite one another on each run.
        rows_without_code = {}
        for item in merged.values():
            if item["dish_code"] is None:
                product_name = item["dish_name_ru"] or item["dish_name_et"] or ""
                rows_without_code.setdefault(product_name.casefold(), []).append(item)

        for product_name, items in rows_without_code.items():
            if len(items) < 2:
                continue

            items.sort(key=size_sort_key)
            base_slug = make_variant_slug(product_name)
            for index, item in enumerate(items):
                if index == 0:
                    item["output_dish_code"] = None
                else:
                    suffix = make_variant_slug(item.get("price_variant"))
                    item["output_dish_code"] = f"ocean:{base_slug}:variant:{suffix}"

        result = []

        for item in merged.values():
            price_ru = item["price_ru"]
            price_et = item["price_et"]

            if (
                price_ru is not None
                and price_et is not None
                and price_ru != price_et
            ):
                print(
                    "[ВНИМАНИЕ] Различаются цены "
                    f"для кода {item['dish_code']}: "
                    f"RU={price_ru:.2f} €, ET={price_et:.2f} €"
                )

            # Приоритет русской цене, если она есть.
            price = price_ru if price_ru is not None else price_et

            name_ru = item["dish_name_ru"]
            name_et = item["dish_name_et"]

            # Старое поле dish_name оставляем для совместимости
            # с существующим main.py на переходном этапе.
            display_name = name_ru or name_et

            category_ru = item["category_ru"] or ""
            category_et = item["category_et"] or ""

            # Определяем общую категорию, используя данные обоих языков.
            # Это позволит сопоставлять категории разных ресторанов.
            product_type = get_product_type(
                f"{category_ru or ''} {category_et or ''}",
                f"{name_ru or ''} {name_et or ''}"
            )

            result.append({
                "dish_code": item.get("output_dish_code", item["dish_code"]),
                "dish_name": display_name,
                "dish_name_ru": name_ru,
                "dish_name_et": name_et,
                "category_ru": category_ru or None,
                "category_et": category_et or None,
                "price": price,
                "price_variant": item.get("price_variant"),
                "product_type": product_type,
            })

        print(
            f"[Ocean Sushi] После объединения: "
            f"{len(result)} записей"
        )

        matched = sum(
            1 for item in result
            if item["dish_name_ru"] and item["dish_name_et"]
        )
        print(f"[Ocean Sushi] Совпали по коду: {matched}")

        return result

    except requests.RequestException as error:
        print(f"[Ocean Sushi] Ошибка загрузки меню: {error}")
        return []

    except Exception as error:
        print(f"[Ocean Sushi] Ошибка парсинга: {error}")
        return []


if __name__ == "__main__":
    data = parse_menu()

    for dish in data:
        print(
            f' Код= {dish["dish_code"]}, '
            f' RU= {dish["dish_name_ru"]}, '
            f' ET= {dish["dish_name_et"]}, '
            f' Цена= {dish["price"]}'
            f' category_ru= {dish["category_ru"]}, '
            f' category_et= {dish["category_et"]}, '
        )
