# datetime нужен, чтобы записывать дату и время обновления цены.
import datetime
import argparse
import os
import re
import unicodedata
from pathlib import Path
from dotenv import load_dotenv

# Инструменты для подключения к Supabase.
from supabase import create_client, Client

# Импортируем парсеры ресторанов под разными именами.
from parsers.ocean_sushi import parse_menu as parse_ocean
from parsers.hesburger import parse_menu as parse_hesburger
from parsers.monk import parse_menu as parse_monk
from parsers.categories import (
    canonical_category_ru,
    canonical_category_et,
)

# Загружаем переменные из .env в корне проекта.
load_dotenv(Path(__file__).resolve().parent / ".env")

URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_SECRET_KEY")

if not URL or not KEY:
    raise RuntimeError(
        "Не заданы SUPABASE_URL и SUPABASE_SECRET_KEY в .env"
    )

# Создаём подключение к базе данных.
supabase: Client = create_client(URL, KEY)


def normalize_category(value):
    """Исправляет категории, записанные целиком заглавными буквами."""
    if not value:
        return value

    value = " ".join(str(value).split())
    letters = [char for char in value if char.isalpha()]

    if letters and all(char.isupper() for char in letters):
        return value[0].upper() + value[1:].lower()

    return value


def normalize_match_name(value):
    """Normalizes dish names for safe fallback matching across code changes."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def normalize_variant_key(value):
    """Returns a stable key for a price variant such as '0.25 l' or 'suur eine'."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "-".join(re.findall(r"[a-z0-9]+", text))


def stored_variant_key(row):
    """Reads the stored variant, falling back to a known variant in dish_code."""
    explicit = row.get("price_variant")
    if explicit is not None and str(explicit).strip():
        return normalize_variant_key(explicit)

    code = str(row.get("dish_code") or "")
    suffix = code.rsplit(":", 1)[-1].casefold()
    known_variants = {
        "single", "burger", "eine", "suur-eine", "with-topping",
        "6-tk", "8-tk", "12-tk", "200-ml", "300-ml",
        "0-25-l", "0-4-l", "0-5-l",
    }
    if suffix in known_variants or re.fullmatch(r"\d+(?:-\d+)?-(?:l|ml|tk)", suffix):
        return normalize_variant_key(suffix)

    return ""


def matching_existing_rows(rows, dish):
    """Finds exact-name, exact-variant rows without guessing between sizes."""
    incoming_names = {
        normalize_match_name(dish.get(key))
        for key in ("dish_name", "dish_name_ru", "dish_name_et")
        if normalize_match_name(dish.get(key))
    }
    incoming_variant = normalize_variant_key(dish.get("price_variant"))

    if not incoming_names:
        return []

    matches = []
    for row in rows:
        row_names = {
            normalize_match_name(row.get(key))
            for key in ("dish_name", "dish_name_ru", "dish_name_et")
            if normalize_match_name(row.get(key))
        }
        if not incoming_names.intersection(row_names):
            continue

        # Do not match a different volume/meal option to this record.
        if stored_variant_key(row) != incoming_variant:
            continue

        matches.append(row)

    return matches


def save_dishes_to_db(restaurant_name, scraped_dishes):
    """Сохраняет блюда одного ресторана в таблицу dishes Supabase."""
    print(f"\n[Main] Обработка ресторана: {restaurant_name}")

    added = 0
    updated = 0
    unchanged = 0
    errors = 0
    # Every successfully processed row in this run receives the same timestamp.
    run_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for dish in scraped_dishes:
        name_ru = dish.get("dish_name_ru")
        name_et = dish.get("dish_name_et")
        dish_code = dish.get("dish_code")
        name = name_ru or name_et or dish.get("dish_name")

        if not name:
            print("[Пропуск] У блюда отсутствует название.")
            continue

        try:
            new_price = float(dish["price"])
        except (KeyError, TypeError, ValueError):
            print(f"[Ошибка] Некорректная цена у блюда: {name}")
            errors += 1
            continue

        product_type = dish.get("product_type", "Другое")
        category_et = normalize_category(dish.get("category_et"))
        category_ru_source = normalize_category(dish.get("category_ru"))
        dish_text = " ".join(
            str(dish.get(key) or "")
            for key in ("dish_name_ru", "dish_name_et", "dish_name")
        )
        category_ru = canonical_category_ru(
            product_type,
            category_ru=category_ru_source,
            category_et=category_et,
            dish_name=dish_text,
        )
        # Save a matching canonical category in both languages. The original
        # menu's subcategory labels should not create extra ET-only categories.
        category_et = canonical_category_et(
            product_type,
            category_ru=category_ru,
            category_et=category_et,
            dish_name=dish_text,
        )
        now = run_timestamp

        try:
            query = (
                supabase.table("dishes")
                .select("*")
                .eq("restaurant_name", restaurant_name)
            )

            if dish_code is not None:
                query = query.eq("dish_code", str(dish_code))
            else:
                query = query.eq("dish_name", name)

            existing = query.limit(1).execute()
            existing_rows = existing.data or []

            # If a source code changed, try an exact name + exact variant match.
            # This safely reuses one old row rather than inserting a duplicate.
            if not existing_rows and dish_code is not None:
                restaurant_rows_response = (
                    supabase.table("dishes")
                    .select("*")
                    .eq("restaurant_name", restaurant_name)
                    .execute()
                )
                candidates = matching_existing_rows(
                    restaurant_rows_response.data or [], dish
                )

                if len(candidates) == 1:
                    existing_rows = candidates
                    print(
                        f" -> Найдена старая запись по названию и варианту: "
                        f"{name}; код будет обновлён "
                        f"{candidates[0].get('dish_code')} -> {dish_code}"
                    )
                elif len(candidates) > 1:
                    candidate_codes = [
                        str(row.get("dish_code")) for row in candidates
                    ]
                    print(
                        f"[Неоднозначное совпадение] {name}: найдено несколько "
                        f"записей с тем же названием и вариантом: {candidate_codes}. "
                        "Новая запись не создаётся; требуется проверить дубли."
                    )
                    errors += 1
                    continue

            # Не перезаписываем уже сохранённый русский перевод значением None.
            # Это важно для Hesburger: его парсер получает названия с эстонского сайта.
            dish_data = {
                "restaurant_name": restaurant_name,
                "dish_name": name,
                "dish_code": str(dish_code) if dish_code is not None else None,
                "product_type": product_type,
            }
            # An unavailable translation should not erase a previously saved
            # localized category (for example if the Estonian site is temporarily down).
            if category_et is not None:
                dish_data["category_et"] = category_et
            price_variant = dish.get("price_variant")
            if price_variant is not None:
                dish_data["price_variant"] = price_variant
            if name_ru is not None:
                dish_data["dish_name_ru"] = name_ru
            if name_et is not None:
                dish_data["dish_name_et"] = name_et
            if category_ru is not None:
                dish_data["category_ru"] = category_ru

            if not existing_rows:
                print(f" -> Новое блюдо: {name} ({new_price:.2f} €)")
                dish_data.update({
                    "current_price": new_price,
                    "old_price": new_price,
                    "price_delta": 0.00,
                    "last_updated": now,
                })
                supabase.table("dishes").insert(dish_data).execute()
                added += 1
            else:
                db_dish = existing_rows[0]
                current_db_price = float(db_dish["current_price"])
                dish_data["last_updated"] = now

                if new_price != current_db_price:
                    delta = round(new_price - current_db_price, 2)
                    print(
                        f" -> Изменение цены: {name}: "
                        f"{current_db_price:.2f} € -> {new_price:.2f} € "
                        f"(дельта: {delta:+.2f} €)"
                    )
                    dish_data.update({
                        "old_price": current_db_price,
                        "current_price": new_price,
                        "price_delta": delta,
                    })
                    updated += 1
                else:
                    unchanged += 1

                supabase.table("dishes").update(dish_data).eq(
                    "id", db_dish["id"]
                ).execute()

        except Exception as e:
            errors += 1
            print(f"[Ошибка] Не удалось обработать {name}: {e}")

    print("\n--- Итоги обработки ---")
    print(f"Добавлено новых блюд: {added}")
    print(f"Изменено цен: {updated}")
    print(f"Без изменения цены: {unchanged}")
    print(f"Ошибок: {errors}")


def run_parser(parser_function, restaurant_name):
    """Запускает парсер и сохраняет результаты; ошибка одного ресторана не мешает другому."""
    print(f"\n[Main] Запускаю парсер: {restaurant_name}")
    try:
        data = parser_function()
    except Exception as e:
        print(f"[Ошибка] Парсер {restaurant_name} завершился с ошибкой: {e}")
        return

    if not data:
        print(
            f"[Внимание] Парсер {restaurant_name} не вернул данные. "
            "Для этого ресторана Supabase не изменена."
        )
        return

    print(f"[Main] Получено записей: {len(data)}")
    save_dishes_to_db(restaurant_name, data)


def main():
    """Обновляет меню выбранного ресторана или всех ресторанов."""
    parser = argparse.ArgumentParser(description="Мониторинг цен ресторанов")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только запустить парсеры и показать количество записей, не изменяя Supabase.",
    )
    parser.add_argument(
        "--restaurant",
        choices=("all", "ocean", "hesburger", "monk"),
        default="all",
        help="Какой ресторан обрабатывать: all (по умолчанию), ocean, hesburger или monk.",
    )
    args = parser.parse_args()

    restaurant_parsers = {
        "ocean": (parse_ocean, "Ocean Sushi Jõhvi"),
        "hesburger": (parse_hesburger, "Hesburger"),
        "monk": (parse_monk, "Monk Jõhvi"),
    }
    selected_parsers = (
        list(restaurant_parsers.items())
        if args.restaurant == "all"
        else [(args.restaurant, restaurant_parsers[args.restaurant])]
    )

    print("=== ЗАПУСК МОНИТОРИНГА ЦЕН ===")
    if args.dry_run:
        print("[Main] Режим dry-run: данные в Supabase записываться не будут.")
        for _, (parser_function, restaurant_name) in selected_parsers:
            print(f"\n[Main] Запускаю парсер: {restaurant_name}")
            try:
                data = parser_function()
                print(f"[Main] {restaurant_name}: получено записей — {len(data or [])}; запись в Supabase пропущена.")
            except Exception as e:
                print(f"[Ошибка] Парсер {restaurant_name} завершился с ошибкой: {e}")
    else:
        for _, (parser_function, restaurant_name) in selected_parsers:
            run_parser(parser_function, restaurant_name)

    print("\n=== МОНИТОРИНГ ЗАВЕРШЁН ===")


# Запускать main() только при запуске этого файла напрямую.
if __name__ == "__main__":
    main()
