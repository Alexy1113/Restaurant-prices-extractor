"""Парсер актуальных цен Hesburger Eesti.

По умолчанию загружает актуальный PDF с сайта Hesburger, сначала пробует
извлечь текстовый слой через PyMuPDF и запускает Tesseract OCR, если
текстовый слой отсутствует или его недостаточно. Локальный PDF разрешён
только для тестирования; загрузка локального PDF в Supabase запрещена.

Для записи в базу нужно явно передать --upload и настроить переменные среды.
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pymupdf
import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    # Можно передать переменные среды средствами Windows/VS Code.
    pass


# Каталог продуктов на эстонском сайте Hesburger.
MENU_URL = "https://www.hesburger.ee/tooted"

# Tesseract можно указать через переменную окружения TESSERACT_CMD.
# Если она не задана, пробуем найти программу в PATH, а затем используем
# стандартную папку установки Windows.
TESSERACT_EXE = (
    os.environ.get("TESSERACT_CMD")
    or shutil.which("tesseract")
    or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Языки для распознавания PDF.
OCR_LANGUAGES = "est+eng"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    )
}


# Некоторые названия в PDF и каталоге сайта отличаются из-за сокращений
# или ошибок OCR. Эти варианты помогают сопоставить их друг с другом.
CATALOG_ALIASES = {
    "veke soe sojasalat": "soe veke sojasalat",
    "sibularongad stk 1 kaste": "sibularongad 5 tk kaste",
    "kananagitsad 4 tk 1 kaste": "kananagitsad 4 tk kaste",
    "kananagitsad 6 tk 1 kaste": "kananagitsad 6 tk kaste",
    "krobe kanafilee 2 tk 1 kaste": "krobe kanafilee 2 tk kaste",
}


def clean_text(text):
    """Убирает лишние пробелы и переносы строк."""
    return " ".join((text or "").split()).strip()


def normalize_name(text):
    """Нормализует название для поиска совпадений между сайтом и PDF.

    Например, "BBQ - burger" и "BBQ-burger" будут иметь один ключ.
    Диакритические знаки удаляются только для сравнения; исходное название
    в данных остаётся без изменений.
    """
    text = unicodedata.normalize("NFKD", str(text or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def make_slug(text):
    """Создаёт ASCII-идентификатор из названия или варианта цены."""
    return normalize_name(text).replace(" ", "-") or "unknown"


def make_unicode_slug(text):
    """Создаёт читаемый slug из названия, сохраняя эстонские буквы.

    Используется только для внутреннего dish_code, если исходный URL-slug
    Hesburger содержит специальные двойные дефисы вместо букв. Сам product_url
    при этом остаётся исходным официальным URL.
    """
    text = unicodedata.normalize("NFC", str(text or "").casefold())
    result = []
    separator_pending = False

    for char in text:
        if char.isalnum():
            if separator_pending and result:
                result.append("-")
            result.append(char)
            separator_pending = False
        else:
            separator_pending = True

    return "".join(result).strip("-") or "unknown"


def normalize_category(category):
    """Объединяет все напитки в категорию Supabase «Joogid»."""
    category = clean_text(category)
    normalized = normalize_name(category)
    if normalized in {"joogid", "kuumad joogid"}:
        return "Joogid"
    return category


def clean_pdf_product_name(name):
    """Исправляет несколько частых особенностей распознанного названия."""
    name = clean_text(name)
    name = re.sub(r"^[\-–—]\s*", "", name)

    normalized = normalize_name(name)

    # OCR иногда не распознаёт бренд VEKE® перед названием соевых палочек.
    if normalized.startswith("sojapulgad "):
        name = "VEKE® " + name

    # В PDF название выглядит как "VEKE Soe sojasalat", а на сайте
    # порядок слов другой: "Soe VEKE® Sojasalat".
    if normalized == "veke soe sojasalat":
        return "Soe VEKE® Sojasalat"

    # OCR неверно прочитал количество в названии луковых колец.
    if normalized == "sibularongad stk 1 kaste":
        return "Sibularõngad 5 tk + kaste"

    return name


def get_product_type(category, name):
    """Возвращает универсальную категорию, независимую от языка сайта."""
    category_text = normalize_name(category)
    name_text = normalize_name(name)
    text = f"{category_text} {name_text}"

    # Более специфические типы проверяем до общих категорий.
    if "jaatisekokteil" in text:
        return "ice_cream_shakes"

    if any(word in name_text for word in ["burger", "hamburger"]):
        return "burgers"

    if "tortilla" in name_text:
        return "tortillas"

    if "salat" in name_text or "salad" in name_text:
        return "salads"

    if any(word in text for word in ["kananagitsad", "sojapulgad", "sibularongad", "kanafilee"]):
        return "appetizers"

    if any(word in text for word in ["friikartul", "kartulid", "rostkartulid"]):
        return "sides"

    if any(word in text for word in ["kastmed", "kaste", "ketsup", "majonees"]):
        return "sauces"

    if any(word in text for word in [
        "jaatis", "sookrik", "kupsis", "magustoid", "shokolaad", "pistaatsia"
    ]):
        return "desserts"

    # Syrup for coffee is an additive, not a beverage. Check this before
    # the drinks rule because "kohvile" contains the substring "kohv".
    if any(word in name_text for word in ["siirup", "syrup", "siroop", "siirupid"]):
        return "syrups"

    if any(word in text for word in [
        "coca cola", "fanta", "sprite", "kohv", "espresso", "cappuccino",
        "latte", "tee", "vesi", "mahl", "smuuti", "limonaad", "jook",
        "cappy", "jook", "cappuccino", "jäätee", "jaatee"
    ]) or "joogid" in category_text or "kuumad joogid" in category_text:
        return "drinks"

    if "hommikupala" in category_text:
        return "breakfast"

    if "kampaaniad" in category_text:
        return "campaigns"

    return "other"


def get_catalog_products():
    """Загружает каталог товаров Hesburger и извлекает названия, категории и URL."""
    response = requests.get(MENU_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    products = {}

    for link in soup.select("a[href]"):
        product_url = urljoin(MENU_URL, link.get("href", ""))
        parsed_url = urlparse(product_url)

        # Нас интересуют только отдельные страницы товаров Hesburger.
        if parsed_url.netloc and not parsed_url.netloc.endswith("hesburger.ee"):
            continue

        if not parsed_url.path.startswith("/tooted/"):
            continue

        path_parts = [part for part in parsed_url.path.split("/") if part]

        if len(path_parts) < 3:
            continue

        name_et = clean_text(link.get_text(" ", strip=True))

        # Если в ссылке нет текста, пробуем взять alt или title.
        if not name_et:
            image = link.find("img")
            name_et = clean_text(
                link.get("title")
                or (image.get("alt", "") if image else "")
            )

        if not name_et:
            continue

        # Находим категорию товара.
        heading = link.find_previous("h2")

        if heading:
            category_et = clean_text(
                heading.get_text(" ", strip=True)
            )

            if category_et.casefold().startswith("hommikupala"):
                category_et = "Hommikupala"
        else:
            category_et = "Muu"

        # Формируем внутренний код товара.
        if "--" in path_parts[-1]:
            code_path_parts = path_parts[:-1] + [
                make_unicode_slug(name_et)
            ]
        else:
            code_path_parts = path_parts

        dish_code = "hesburger:" + "/".join(code_path_parts)

        products.setdefault(dish_code, {
            "dish_code": dish_code,
            "dish_name": name_et,
            "dish_name_ru": None,
            "dish_name_et": name_et,
            "category_ru": None,
            "category_et": category_et,
            "product_type": get_product_type(category_et, name_et),
            "product_url": product_url,
        })

    return list(products.values())


def get_catalog_lookup(catalog_products):
    """Создаёт индекс каталога по нормализованному названию."""
    lookup = {}

    for product in catalog_products:
        key = normalize_name(product["dish_name_et"])
        # Если одно название встречается в нескольких разделах,
        # оставляем первое найденное совпадение.
        lookup.setdefault(key, product)

    return lookup


def find_catalog_product(name, catalog_lookup):
    """Находит соответствующий товар на сайте, если такое название есть."""
    key = normalize_name(clean_pdf_product_name(name))
    key = CATALOG_ALIASES.get(key, key)
    return catalog_lookup.get(key)


def find_price_list_url():
    """Находит актуальную ссылку Hinnakiri на странице товаров."""
    response = requests.get(MENU_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.select("a[href]"):
        link_text = normalize_name(link.get_text(" ", strip=True))
        if "hinnakiri" in link_text:
            return urljoin(MENU_URL, link["href"])

    raise RuntimeError("Не удалось найти ссылку Hinnakiri на сайте Hesburger.")


def read_local_price_list(pdf_path):
    """Читает и проверяет локальный PDF-прайс-лист."""
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Локальный PDF не найден: {path}")

    pdf_data = path.read_bytes()
    if not pdf_data.startswith(b"%PDF"):
        raise RuntimeError(f"Файл не похож на PDF или повреждён: {path}")

    print(f"[Hesburger] Использую локальный PDF: {path}")
    return pdf_data


def download_price_list(local_pdf_path=None):
    """Получает локальный PDF или скачивает актуальный прайс с сайта.

    Локальный файл можно передать через local_pdf_path или переменную
    окружения HESBURGER_PDF_PATH. Если путь не задан, поведение остаётся
    прежним: скачивается официальный актуальный PDF.
    """
    # Локальный PDF используется только при явном указании --pdf.
    # Обычный запуск всегда получает ссылку на актуальный PDF с сайта.
    if local_pdf_path:
        return read_local_price_list(local_pdf_path)

    pdf_url = find_price_list_url()
    print(f"[Hesburger] Ссылка на прайс-лист: {pdf_url}")

    response = requests.get(pdf_url, headers=HEADERS, timeout=60)
    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        raise RuntimeError(
            "Ссылка Hinnakiri не вернула PDF. "
            "Возможно, сайт изменил формат прайс-листа."
        )

    return response.content


def parse_price_token(raw_text):
    """Преобразует строку OCR в число цены.

    OCR иногда распознаёт 1.50 как 150 или 10.60 как 1060.
    Преобразование применяется только к токенам из известных колонок цен.
    """
    text = re.sub(r"[^0-9.,]", "", str(raw_text or "")).replace(",", ".")

    # Обычный формат: 4.20, 1.50, 0.30.
    if re.fullmatch(r"\d{1,2}\.\d{1,2}", text):
        try:
            return round(float(text), 2)
        except ValueError:
            return None

    # Формат без точки, например 150 -> 1.50, 1060 -> 10.60.
    if re.fullmatch(r"\d{3,4}", text):
        value = int(text) / 100
        if 0 < value <= 100:
            return round(value, 2)

    return None


def group_words_into_rows(words, tolerance=35):
    """Группирует слова с близкими координатами Y в одну строку."""
    words.sort(key=lambda word: word["y"])
    rows = []

    for word in words:
        if not rows or abs(word["y"] - rows[-1]["average_y"]) > tolerance:
            rows.append({"words": [word], "average_y": word["y"]})
        else:
            row = rows[-1]
            row["words"].append(word)
            row["average_y"] = sum(
                item["y"] for item in row["words"]
            ) / len(row["words"])

    for row in rows:
        row["words"].sort(key=lambda word: word["x"])
        row["y"] = int(row["average_y"])

    return rows


def ocr_pdf_region(page, clip, image_path):
    """Рендерит область PDF и возвращает распознанные строки с координатами."""
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(400 / 72, 400 / 72),
        clip=clip,
        alpha=False,
    )
    pixmap.save(str(image_path))

    # TSV содержит отдельные слова и их координаты на изображении.
    result = subprocess.run(
        [
            TESSERACT_EXE,
            str(image_path),
            "stdout",
            "-l", OCR_LANGUAGES,
            "--psm", "6",
            "tsv",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )

    words = []
    reader = csv.DictReader(result.stdout.splitlines(), delimiter="\t")

    for item in reader:
        # level=5 — отдельное слово, а не страница или строка.
        if item.get("level") != "5":
            continue

        text = clean_text(item.get("text", ""))
        if not text:
            continue

        try:
            confidence = float(item.get("conf", "-1"))
            x = int(item["left"])
            y = int(item["top"])
        except (TypeError, ValueError, KeyError):
            continue

        # Сохраняем даже слова с неидеальной уверенностью, но удаляем
        # самые ненадёжные шумовые распознавания.
        if confidence < 25:
            continue

        words.append({"text": text, "x": x, "y": y, "confidence": confidence})

    return group_words_into_rows(words)


def ocr_breakfast_price_from_region(page, right_clip, row_y, x_min, x_max):
    """Повторно распознаёт одну цену завтрака в узкой области изображения.

    Основной OCR работает по всей половине страницы. Если он пропускает цену,
    эта функция использует отдельный crop и несколько режимов Tesseract.
    Значение принимается при повторном совпадении либо при однозначном чтении
    с явной десятичной точкой. Цены не зашиты в код.
    """
    if not Path(TESSERACT_EXE).exists() and not shutil.which(TESSERACT_EXE):
        return None

    scale = 400 / 72
    # y координата из OCR — верхняя часть строки; поля снизу/сверху нужны,
    # чтобы не обрезать цифры или десятичную точку.
    y_min = max(0, row_y - 35)
    y_max = row_y + 100
    region = pymupdf.Rect(
        right_clip.x0 + x_min / scale,
        right_clip.y0 + y_min / scale,
        min(right_clip.x1, right_clip.x0 + x_max / scale),
        min(right_clip.y1, right_clip.y0 + y_max / scale),
    )
    if region.is_empty or region.width <= 0 or region.height <= 0:
        return None

    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "breakfast_price.png"
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale), clip=region, alpha=False
        )
        pixmap.save(str(image_path))

        votes = {}
        explicit_decimal_values = set()
        all_values = set()
        for psm in (6, 7, 8, 11, 13):
            try:
                result = subprocess.run(
                    [
                        TESSERACT_EXE, str(image_path), "stdout",
                        "-l", "eng", "--psm", str(psm),
                        "-c", "tessedit_char_whitelist=0123456789.,",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=True,
                )
            except (subprocess.SubprocessError, OSError):
                continue

            output = result.stdout.replace("O", "0").replace("o", "0")
            tokens = re.findall(
                r"(?<!\d)(?:\d{1,2}[.,]\d{1,2}|\d{3,4})(?!\d)", output
            )
            mode_values = set()
            for token in tokens:
                price = parse_price_token(token)
                # Отсекаем склейки вроде 4506 -> 45.06, которые слишком велики
                # для строки завтраков и часто появляются при ошибке OCR.
                if price is None or not 0.20 <= price <= 20.00:
                    continue
                price = round(price, 2)
                mode_values.add(price)
                all_values.add(price)
                if re.fullmatch(r"\d{1,2}[.,]\d{1,2}", token):
                    explicit_decimal_values.add(price)

            if len(mode_values) == 1:
                value = next(iter(mode_values))
                votes[value] = votes.get(value, 0) + 1

    if not votes:
        return None

    max_votes = max(votes.values())
    winners = [value for value, count in votes.items() if count == max_votes]
    if len(winners) == 1 and max_votes >= 2:
        return winners[0]

    # Единичное чтение допускается только если это единственный кандидат
    # и Tesseract вывел цену с десятичной точкой, например 4.50.
    if len(all_values) == 1 and len(explicit_decimal_values) == 1:
        return next(iter(explicit_decimal_values))

    return None


def inspect_pdf_text_layer(page):
    """Проверяет, содержит ли PDF достаточно текстовых данных для разбора.

    Одного заголовка или даты внизу страницы недостаточно: нам нужны
    названия и несколько распознаваемых цен. Если слой слишком бедный,
    основной алгоритм переключается на Tesseract OCR.
    """
    raw_words = page.get_text("words", sort=True)
    words = [item for item in raw_words if len(item) >= 5 and clean_text(item[4])]

    name_words = sum(
        1 for item in words
        if re.search(r"[A-Za-zÀ-ž]", clean_text(item[4]))
    )
    price_words = sum(
        1 for item in words
        if parse_price_token(item[4]) is not None
    )

    # Порог специально консервативный: неполный текстовый слой не должен
    # мешать OCR читать страницу целиком.
    is_usable = len(words) >= 40 and name_words >= 12 and price_words >= 10
    return is_usable, len(words), name_words, price_words


def extract_pdf_text_region(page, clip):
    """Извлекает слова из текстового слоя PDF с координатами, совместимыми с OCR.

    Координаты PyMuPDF измеряются в пунктах. Умножаем их на тот же масштаб
    400/72, который использует OCR, чтобы обе стратегии могли применять
    существующие правила расположения товаров и цен.
    """
    scale = 400 / 72
    words = []

    for item in page.get_text("words", clip=clip, sort=True):
        if len(item) < 5:
            continue

        x0, y0, _x1, _y1, raw_text = item[:5]
        text = clean_text(raw_text)
        if not text:
            continue

        words.append({
            "text": text,
            "x": int(round((x0 - clip.x0) * scale)),
            "y": int(round(y0 * scale)),
            "confidence": 100.0,
        })

    return group_words_into_rows(words)


def row_text(row, max_x=850):
    """Собирает название из слов слева, до первой ценовой колонки."""
    parts = [word["text"] for word in row["words"] if word["x"] < max_x]
    return clean_pdf_product_name(" ".join(parts))


def price_in_x_range(row, min_x, max_x):
    """Находит первую похожую на цену цифру в заданной области X."""
    for word in row["words"]:
        if min_x <= word["x"] < max_x:
            price = parse_price_token(word["text"])
            if price is not None:
                return price
    return None


def price_at_x(row, min_x):
    """Находит цену в самой правой колонке от min_x и правее."""
    candidates = []
    for word in row["words"]:
        if word["x"] >= min_x:
            price = parse_price_token(word["text"])
            if price is not None:
                candidates.append((word["x"], price))
    return candidates[0][1] if candidates else None


def add_record(records, catalog_lookup, name, price, variant, category_hint, warnings):
    """Готовит запись товара в формате, совместимом с основным проектом."""
    name = clean_pdf_product_name(name)
    if not name or price is None:
        return

    # Если товар есть в каталоге, берём его исходное имя, код и категорию.
    catalog_item = find_catalog_product(name, catalog_lookup)

    if catalog_item:
        dish_name_et = catalog_item["dish_name_et"]
        category_et = normalize_category(catalog_item["category_et"] or category_hint)
        base_code = catalog_item["dish_code"]
        product_url = catalog_item.get("product_url")
    else:
        dish_name_et = name
        category_et = normalize_category(category_hint or "Muu")
        # Fallback-код нужен для строк из прайс-листа, которых нет в каталоге.
        # Внутренний dish_code сохраняет эстонские буквы; product_url для таких
        # строк отсутствует, поэтому здесь не нужно копировать URL-slug сайта.
        base_code = "hesburger:price-list:" + make_unicode_slug(name)
        product_url = None

    # У одного товара могут быть разные цены: сам бургер, eine и suur eine,
    # либо разные объёмы напитка. Вариант добавляется к коду, чтобы записи
    # не конфликтовали с уникальным ограничением restaurant_name + dish_code.
    variant_slug = make_slug(variant)
    dish_code = f"{base_code}:{variant_slug}"

    record = {
        "dish_code": dish_code,
        "dish_name": dish_name_et,
        "dish_name_ru": None,          # У Hesburger нет русской версии сайта.
        "dish_name_et": dish_name_et,
        "category_ru": None,
        "category_et": category_et,
        "product_type": get_product_type(category_et, dish_name_et),
        "price": round(float(price), 2),
        "price_variant": variant,
        "product_url": product_url,
    }

    # При повторном появлении одного кода не создаём дубликат.
    if dish_code in records:
        previous = records[dish_code]
        if previous["price"] != record["price"]:
            warnings.append(
                f"Разные цены для кода {dish_code}: "
                f"{previous['price']:.2f} и {record['price']:.2f}; "
                "оставлена первая цена."
            )
        return

    records[dish_code] = record


def parse_left_side(rows, catalog_lookup, records, warnings):
    """Извлекает бургеры с тремя ценами и товары с одной ценой слева."""
    for row in rows:
        y = row["y"]

        # Верхняя левая таблица: бургер, eine, suur eine.
        if 400 <= y < 2000:
            name = row_text(row, max_x=850)
            if not name:
                continue

            prices = {"burger": None, "eine": None, "suur eine": None}

            for word in row["words"]:
                if word["x"] < 900:
                    continue
                price = parse_price_token(word["text"])
                if price is None:
                    continue

                if word["x"] < 1100:
                    prices["burger"] = price
                elif word["x"] < 1320:
                    prices["eine"] = price
                else:
                    prices["suur eine"] = price

            # Если строка содержит только одну цену в колонке "eine" и
            # название не найдено среди обычных товаров каталога, считаем её
            # отдельной позицией с одной ценой. Это обобщённое правило полезно
            # для новых/изменённых строк прайс-листа и не привязано к одному
            # названию вроде "Laste eine".
            catalog_item = find_catalog_product(name, catalog_lookup)
            only_meal_price = (
                prices["eine"] is not None
                and prices["burger"] is None
                and prices["suur eine"] is None
            )
            if only_meal_price and catalog_item is None:
                add_record(
                    records, catalog_lookup, name, prices["eine"],
                    "single", "HAMBURGERID", warnings
                )
            elif all(value is not None for value in prices.values()):
                for variant, price in prices.items():
                    add_record(
                        records, catalog_lookup, name, price, variant,
                        "HAMBURGERID", warnings
                    )
            elif any(value is not None for value in prices.values()):
                warnings.append(
                    f"Пропущена неполная строка бургеров: {name!r}; "
                    f"распознано {prices}."
                )

        # Средняя и нижняя часть слева: салаты, картофель,
        # закуски и соусы; у этих строк одна цена в правой колонке.
        elif 2800 <= y < 6200:
            name = row_text(row, max_x=900)
            if not name:
                continue

            price = price_at_x(row, 1320)
            if price is None:
                continue

            if y < 3800:
                category_hint = "SALATID"
            else:
                category_hint = "FRIIKARTULID JA ERITOOTED"

            add_record(
                records, catalog_lookup, name, price, "single",
                category_hint, warnings
            )


def parse_right_side(rows, catalog_lookup, records, warnings, page=None, right_clip=None):
    """Извлекает завтраки, напитки, десерты и коктейли справа."""
    processed = set()

    # 1. Завтраки: две колонки — отдельный товар и eine.
    for index, row in enumerate(rows):
        y = row["y"]
        if not 400 <= y < 1050:
            continue

        name = row_text(row, max_x=850)
        if not name:
            continue

        name_key = normalize_name(name)

        # Röstkartulid продаются отдельно и имеют только одну цену.
        if "rostkartulid" in name_key:
            price = price_in_x_range(row, 900, 1200)
            if price is not None:
                add_record(
                    records, catalog_lookup, "Röstkartulid", price,
                    "single", "HOMMIKUPALA", warnings
                )
            processed.add(index)
            continue

        if "hommikupala" in name_key:
            single_price = price_in_x_range(row, 900, 1150)
            combo_price = price_in_x_range(row, 1150, 1350)

            # Если основной OCR пропустил цену, повторно читаем узкие ценовые
            # области несколькими режимами Tesseract. Суммы не зашиваем в код.
            if (
                (single_price is None or combo_price is None)
                and page is not None
                and right_clip is not None
            ):
                print(
                    f"[Hesburger][OCR fallback] Уточняю цены завтрака {name!r}..."
                )
                fallback_single = ocr_breakfast_price_from_region(
                    page, right_clip, row["y"], 900, 1150
                )
                fallback_combo = ocr_breakfast_price_from_region(
                    page, right_clip, row["y"], 1150, 1350
                )
                if single_price is None:
                    single_price = fallback_single
                if combo_price is None:
                    combo_price = fallback_combo
                print(
                    "[Hesburger][OCR fallback] Результат: "
                    f"single={single_price}, eine={combo_price}."
                )

            # Не добавляем завтрак, если цена всё ещё неизвестна: лучше остановить
            # загрузку, чем записать догадку.
            if single_price is None or combo_price is None:
                warnings.append(
                    f"Пропущен завтрак {name!r}: OCR не распознал обе цены."
                )
            else:
                add_record(
                    records, catalog_lookup, name, single_price,
                    "single", "HOMMIKUPALA", warnings
                )
                add_record(
                    records, catalog_lookup, name, combo_price,
                    "eine", "HOMMIKUPALA", warnings
                )
            processed.add(index)

    # 2. Coca-Cola / Coca-Cola Zero / Fanta / Sprite делят одну строку
    # с тремя размерами. Цены извлекаются по координатам ценовых ячеек.
    for index, row in enumerate(rows):
        if index in processed or not 1200 <= row["y"] < 1700:
            continue

        name = row_text(row, max_x=850)
        if "coca" not in normalize_name(name):
            continue

        for next_index in range(index + 1, min(index + 3, len(rows))):
            next_row = rows[next_index]
            if next_row["y"] - row["y"] > 180:
                break

            price_025 = price_in_x_range(next_row, 200, 600)
            price_040 = price_in_x_range(next_row, 780, 1050)
            price_050 = price_in_x_range(next_row, 1320, 1530)

            if all(price is not None for price in [price_025, price_040, price_050]):
                # На сайте эти напитки перечислены отдельно, хотя в прайс-листе
                # для них используется общая строка цен.
                drink_names = ["Coca-Cola", "Coca-Cola zero", "Fanta", "Sprite"]
                volume_prices = [
                    ("0.25 l", price_025),
                    ("0.4 l", price_040),
                    ("0.5 l", price_050),
                ]

                for drink_name in drink_names:
                    for variant, price in volume_prices:
                        add_record(
                            records, catalog_lookup, drink_name, price,
                            variant, "Joogid", warnings
                        )

                processed.update({index, next_index})
                break

        if index not in processed:
            warnings.append(
                "Не удалось надёжно извлечь три цены из строки Coca-Cola/Fanta/Sprite."
            )

    # 3. Чай и кофе имеют два объёма в одной строке.
    for index, row in enumerate(rows):
        if index in processed or not 1550 <= row["y"] < 1950:
            continue

        name = row_text(row, max_x=600)
        key = normalize_name(name)

        small_price = price_in_x_range(row, 800, 1100)
        large_price = price_in_x_range(row, 1320, 1530)

        if key == "tee" and small_price is not None and large_price is not None:
            add_record(
                records, catalog_lookup, "Tee", small_price,
                "200 ml", "Joogid", warnings
            )
            add_record(
                records, catalog_lookup, "Suur tee", large_price,
                "300 ml", "Joogid", warnings
            )
            processed.add(index)

        elif key == "kohv" and small_price is not None and large_price is not None:
            # В прайс-листе чёрный и молочный кофе объединены под общими
            # ценами для 200 ml и 300 ml. Используем эти общие цены для
            # соответствующих позиций, указанных в каталоге сайта.
            for coffee_name in ["Must kohv", "Piimakohv"]:
                add_record(
                    records, catalog_lookup, coffee_name, small_price,
                    "200 ml", "Joogid", warnings
                )
            for coffee_name in ["Suur must kohv", "Suur piimakohv"]:
                add_record(
                    records, catalog_lookup, coffee_name, large_price,
                    "300 ml", "Joogid", warnings
                )
            processed.add(index)

    # 4. Jäätisekokteil: общая таблица содержит цены трёх объёмов.
    # Не назначаем эти цены отдельным вкусам без явного подтверждения,
    # потому что в прайс-листе вкус не указан.
    for index, row in enumerate(rows):
        if index in processed or not 4700 <= row["y"] < 5100:
            continue

        name = row_text(row, max_x=850)
        if "jaatisekokteil" not in normalize_name(name):
            continue

        for next_index in range(index + 1, min(index + 3, len(rows))):
            next_row = rows[next_index]
            if next_row["y"] - row["y"] > 180:
                break

            price_025 = price_in_x_range(next_row, 250, 600)
            price_040 = price_in_x_range(next_row, 780, 1050)
            price_050 = price_in_x_range(next_row, 1320, 1530)

            if all(price is not None for price in [price_025, price_040, price_050]):
                for variant, price in [
                    ("0.25 l", price_025),
                    ("0.4 l", price_040),
                    ("0.5 l", price_050),
                ]:
                    add_record(
                        records, catalog_lookup, "Jäätisekokteil", price,
                        variant, "JÄÄTISEKOKTEILID", warnings
                    )
                processed.update({index, next_index})
                break

        if index not in processed:
            warnings.append("Не удалось надёжно извлечь цены Jäätisekokteil.")

    # 5. Обычный jäätis — в прайс-листе указан одной общей строкой.
    # Назначаем эту общую цену четырём обычным вкусам из каталога.
    for index, row in enumerate(rows):
        if index in processed or not 4000 <= row["y"] < 4400:
            continue

        name = row_text(row, max_x=850)
        if normalize_name(name) != "jaatis":
            continue

        price = price_at_x(row, 1320)
        if price is not None:
            for flavor in [
                "Vanillijäätis",
                "Maasikajäätis",
                "Šokolaadijäätis",
                "Karamellijäätis",
            ]:
                add_record(
                    records, catalog_lookup, flavor, price,
                    "single", "MAGUSTOIDUD", warnings
                )
        processed.add(index)

    # 6. Jäätis koos — в прайс-листе цена 2,10 € относится к четырём
    # вариантам топпинга. OCR часто не распознаёт маркеры перед вариантами,
    # поэтому названия берём из известного списка, а цену — из строки PDF.
    jaatis_koos_variants = [
        "Jäätis koos pistaatsiakreemiga",
        "Jäätis koos Pop'n corn karamellikastmega",
        "Jäätis koos maasikamaitseliste kommide ja maasikakastmega",
        "Jäätis koos šokolaadikommide ja šokolaadikastmega",
    ]

    for index, row in enumerate(rows):
        if index in processed or not 4300 <= row["y"] < 4650:
            continue

        name = row_text(row, max_x=850)
        if normalize_name(name) != "jaatis koos":
            continue

        price = price_at_x(row, 1320)
        if price is None:
            warnings.append("Не распознана цена для Jäätis koos.")
            processed.add(index)
            continue

        for variant_name in jaatis_koos_variants:
            add_record(
                records, catalog_lookup, variant_name, price,
                "with topping", "MAGUSTOIDUD", warnings
            )

        # Не добавляем отдельную запись «Jäätis koos» без варианта: это
        # родительская строка цены, а реальные товары — четыре варианта выше.
        processed.add(index)

    # 7. Оставшиеся строки с одной ценой: горячие напитки, десерты,
    # соусы и другие продукты. Строки с несколькими объёмами выше уже
    # обработаны отдельно и пропускаются через processed.
    for index, row in enumerate(rows):
        if index in processed:
            continue

        y = row["y"]
        in_drinks_area = 1800 <= y <= 3050
        in_dessert_area = 3500 <= y <= 4900
        if not (in_drinks_area or in_dessert_area):
            continue

        name = row_text(row, max_x=850)
        if not name:
            continue

        key = normalize_name(name)
        if key in {"tee", "kohv", "jaatis", "jaatis koos", "jaatisekokteil"}:
            continue

        price = price_at_x(row, 1320)
        if price is None:
            continue

        category_hint = "Joogid" if in_drinks_area else "MAGUSTOIDUD"
        add_record(
            records, catalog_lookup, name, price,
            "single", category_hint, warnings
        )


LAST_PARSE_WARNINGS = []
LAST_PARSE_METHOD = "unknown"


def parse_rows_to_records(left_rows, right_rows, catalog_lookup, page=None, right_clip=None):
    """Применяет общий алгоритм сопоставления к текстовым строкам или OCR."""
    records = {}
    warnings = []
    parse_left_side(left_rows, catalog_lookup, records, warnings)
    parse_right_side(
        right_rows, catalog_lookup, records, warnings,
        page=page, right_clip=right_clip,
    )
    return records, warnings


def run_ocr_for_page(page, left_clip, right_clip):
    """Извлекает строки из обеих половин страницы через Tesseract OCR."""
    if not Path(TESSERACT_EXE).exists() and not shutil.which(TESSERACT_EXE):
        raise FileNotFoundError(
            f"Не найден Tesseract: {TESSERACT_EXE}. "
            "Установи Tesseract или укажи путь в переменной TESSERACT_CMD."
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        left_rows = ocr_pdf_region(
            page, left_clip, temp_path / "left.png"
        )
        right_rows = ocr_pdf_region(
            page, right_clip, temp_path / "right.png"
        )

    return left_rows, right_rows


def parse_menu(pdf_path=None):
    """Считывает прайс: сначала текстовый слой PDF, затем при необходимости OCR.

    Обычный запуск скачивает актуальный официальный PDF. Путь pdf_path
    предназначен для локального теста и не даёт права на запись в Supabase.
    """
    global LAST_PARSE_METHOD

    print("[Hesburger] Загружаю каталог товаров...")
    catalog_products = get_catalog_products()
    catalog_lookup = get_catalog_lookup(catalog_products)
    print(f"[Hesburger] Товаров в каталоге: {len(catalog_products)}")

    print("[Hesburger] Загружаю прайс-лист...")
    pdf_data = download_price_list(local_pdf_path=pdf_path)

    with pymupdf.open(stream=pdf_data, filetype="pdf") as pdf:
        if len(pdf) == 0:
            raise RuntimeError("PDF-прайс-лист пустой.")
        if len(pdf) != 1:
            raise RuntimeError(
                f"PDF содержит {len(pdf)} страниц. Текущий алгоритм разбора "
                "проверен для одностраничного прайс-листа. Запись в базу "
                "остановлена, чтобы не загрузить неполные цены."
            )

        page = pdf[0]
        middle_x = page.rect.width / 2
        left_clip = pymupdf.Rect(0, 0, middle_x, page.rect.height)
        right_clip = pymupdf.Rect(middle_x, 0, page.rect.width, page.rect.height)

        print("[Hesburger] Проверяю, можно ли извлечь текст напрямую...")
        text_usable, word_count, name_count, price_count = inspect_pdf_text_layer(page)
        print(
            f"[Hesburger] Текстовый слой: слов={word_count}, "
            f"слов с буквами={name_count}, распознаваемых цен={price_count}."
        )

        if text_usable:
            print("[Hesburger] Использую текстовый слой PDF (без OCR).")
            left_rows = extract_pdf_text_region(page, left_clip)
            right_rows = extract_pdf_text_region(page, right_clip)
            records, warnings = parse_rows_to_records(
                left_rows, right_rows, catalog_lookup,
                page=page, right_clip=right_clip
            )

            # Если текстовый слой есть, но текущие правила макета смогли
            # извлечь слишком мало товаров, не доверяем такому результату:
            # пробуем OCR. Это важно при изменении структуры PDF.
            min_text_records = int(os.environ.get("HESBURGER_TEXT_MIN_RECORDS", "70"))
            if len(records) < min_text_records:
                print(
                    f"[Hesburger][Проверить] Текстовый разбор дал только "
                    f"{len(records)} записей (минимум {min_text_records}); "
                    "повторяю распознавание через OCR."
                )
                left_rows, right_rows = run_ocr_for_page(
                    page, left_clip, right_clip
                )
                records, warnings = parse_rows_to_records(
                    left_rows, right_rows, catalog_lookup,
                    page=page, right_clip=right_clip,
                )
                LAST_PARSE_METHOD = "ocr_fallback"
            else:
                LAST_PARSE_METHOD = "text"
        else:
            print("[Hesburger] Полноценного текстового слоя нет; запускаю Tesseract OCR.")
            left_rows, right_rows = run_ocr_for_page(
                page, left_clip, right_clip
            )
            records, warnings = parse_rows_to_records(
                left_rows, right_rows, catalog_lookup,
                page=page, right_clip=right_clip
            )
            LAST_PARSE_METHOD = "ocr"

    result = list(records.values())
    LAST_PARSE_WARNINGS.clear()
    LAST_PARSE_WARNINGS.extend(warnings)

    method_labels = {
        "text": "извлечение текста PDF",
        "ocr": "Tesseract OCR",
        "ocr_fallback": "Tesseract OCR после неудачного текстового разбора",
    }
    print(f"[Hesburger] Использованный метод: {method_labels.get(LAST_PARSE_METHOD, LAST_PARSE_METHOD)}")
    print(f"[Hesburger] Записей с распознанными ценами: {len(result)}")
    print(f"[Hesburger] Предупреждений/пропусков: {len(warnings)}")

    for warning in warnings:
        print(f"[Hesburger][Проверить] {warning}")

    return result


def validate_before_upload(records, warnings):
    """Отсекает явно неполные или подозрительные результаты перед записью."""
    min_records = int(os.environ.get("HESBURGER_MIN_RECORDS", "70"))

    if warnings:
        preview = "\n".join(f"- {item}" for item in warnings[:10])
        extra = "\n…" if len(warnings) > 10 else ""
        raise RuntimeError(
            f"Загрузка в Supabase отменена: OCR сообщил {len(warnings)} "
            f"предупреждений. Исправьте их или проверьте PDF вручную:\n"
            f"{preview}{extra}"
        )

    if len(records) < min_records:
        raise RuntimeError(
            f"Загрузка в Supabase отменена: найдено только {len(records)} "
            f"записей, минимум для загрузки — {min_records}. Вероятно, "
            "изменился макет PDF или часть цен не распознана."
        )

    codes = [item.get("dish_code") for item in records]
    if any(not code for code in codes) or len(codes) != len(set(codes)):
        raise RuntimeError(
            "Загрузка в Supabase отменена: отсутствуют dish_code или есть дубликаты."
        )

    for item in records:
        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError(
                f"Загрузка в Supabase отменена: некорректная цена в записи {item!r}."
            )
        if not 0 < price <= 50:
            raise RuntimeError(
                f"Загрузка в Supabase отменена: подозрительная цена {price} "
                f"для {item.get('dish_name_et')!r}."
            )


def upload_to_supabase(records):
    """Обновляет записи через upsert, чтобы не создавать дубликаты."""
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError(
            "Не установлен пакет Supabase. Выполните: "
            "python -m pip install supabase"
        ) from exc

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = (
        os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    table_name = os.environ.get("SUPABASE_TABLE")

    missing = []
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not supabase_key:
        missing.append("SUPABASE_KEY (или SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY)")
    if not table_name:
        missing.append("SUPABASE_TABLE")
    if missing:
        raise RuntimeError(
            "Для Supabase не настроены переменные среды: " + ", ".join(missing)
        )

    client = create_client(supabase_url, supabase_key)
    payload = [
        {**item, "restaurant_name": "Hesburger"}
        for item in records
    ]

    # Ожидаем примерно 100–150 записей, поэтому отправляем их одним upsert,
    # чтобы не получить частичное обновление из-за ошибки во втором пакете.
    batch_size = 500
    total = 0
    for start in range(0, len(payload), batch_size):
        batch = payload[start:start + batch_size]
        response = client.table(table_name).upsert(
            batch,
            on_conflict="restaurant_name,dish_code",
        ).execute()
        if getattr(response, "error", None):
            raise RuntimeError(f"Supabase вернул ошибку: {response.error}")
        total += len(batch)

    print(f"[Hesburger] Supabase: отправлено записей через upsert: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Парсер актуальных цен Hesburger. Без параметров скачивает "
            "текущий PDF; --pdf доступен только для локального теста."
        )
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Локальный PDF только для тестирования парсера (не для Supabase).",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Записать распознанные цены в Supabase после успешных проверок.",
    )
    args = parser.parse_args()

    if args.upload and args.pdf:
        parser.error("--upload нельзя использовать вместе с --pdf: локальные тестовые PDF не загружаются в Supabase.")

    menu = parse_menu(pdf_path=args.pdf)
    print("\n========== ПЕРВЫЕ 40 ЗАПИСЕЙ ==========")

    for item in menu[:40]:
        print(
            f"Код={item['dish_code']} | "
            f"Название={item['dish_name_et']} | "
            f"Вариант={item['price_variant']} | "
            f"Цена={item['price']:.2f} € | "
            f"Тип={item['product_type']}"
        )

    if args.upload:
        # Upload is allowed only when the official live PDF was used and all
        # parser safeguards passed. Any warning prevents database changes.
        validate_before_upload(menu, warnings=LAST_PARSE_WARNINGS)
        upload_to_supabase(menu)
    else:
        mode = "локальный тестовый PDF" if args.pdf else "актуальный PDF с сайта"
        print(f"\n[Hesburger] Проверка завершена. Источник: {mode}. В Supabase ничего не записывали.")
