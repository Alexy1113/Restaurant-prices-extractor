# datetime нужен, чтобы записывать дату и время обновления цены.
import datetime
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

# Инструменты для подключения к Supabase.
from supabase import create_client, Client

# Импортируем парсеры двух ресторанов под разными именами.
from parsers.ocean_sushi import parse_menu as parse_ocean
from parsers.hesburger import parse_menu as parse_hesburger

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


def save_dishes_to_db(restaurant_name, scraped_dishes):
    """Сохраняет блюда одного ресторана в таблицу dishes Supabase."""
    print(f"\n[Main] Обработка ресторана: {restaurant_name}")

    added = 0
    updated = 0
    unchanged = 0
    errors = 0

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
        category_ru = normalize_category(dish.get("category_ru"))
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

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

            # Не перезаписываем уже сохранённый русский перевод значением None.
            # Это важно для Hesburger: его парсер получает названия с эстонского сайта.
            dish_data = {
                "restaurant_name": restaurant_name,
                "dish_name": name,
                "category_et": category_et,
                "dish_code": str(dish_code) if dish_code is not None else None,
                "product_type": product_type,
            }
            price_variant = dish.get("price_variant")
            if price_variant is not None:
                dish_data["price_variant"] = price_variant
            if name_ru is not None:
                dish_data["dish_name_ru"] = name_ru
            if name_et is not None:
                dish_data["dish_name_et"] = name_et
            if category_ru is not None:
                dish_data["category_ru"] = category_ru

            if not existing.data:
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
                db_dish = existing.data[0]
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
    """Последовательно обновляет меню Ocean Sushi и Hesburger."""
    parser = argparse.ArgumentParser(description="Мониторинг цен ресторанов")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только запустить парсеры и показать количество записей, не изменяя Supabase.",
    )
    args = parser.parse_args()

    print("=== ЗАПУСК МОНИТОРИНГА ЦЕН ===")
    if args.dry_run:
        print("[Main] Режим dry-run: данные в Supabase записываться не будут.")
        for parser_function, restaurant_name in (
            (parse_ocean, "Ocean Sushi Jõhvi"),
            (parse_hesburger, "Hesburger"),
        ):
            print(f"\n[Main] Запускаю парсер: {restaurant_name}")
            try:
                data = parser_function()
                print(f"[Main] {restaurant_name}: получено записей — {len(data or [])}; запись в Supabase пропущена.")
            except Exception as e:
                print(f"[Ошибка] Парсер {restaurant_name} завершился с ошибкой: {e}")
    else:
        run_parser(parse_ocean, "Ocean Sushi Jõhvi")
        run_parser(parse_hesburger, "Hesburger")

    print("\n=== МОНИТОРИНГ ЗАВЕРШЁН ===")


# Запускать main() только при запуске этого файла напрямую.
if __name__ == "__main__":
    main()
