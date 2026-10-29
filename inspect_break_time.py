"""Live diagnostic report for the Break Time parser.

Run from the repository root:
    python inspect_break_time.py

This fetches the live RU and ET menus and prints every merged record.
It does not import main.py, connect to Supabase, or write to the database.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from parsers.break_time import parse_menu


def show(value):
    return "-" if value is None or value == "" else str(value)


def main():
    print("=" * 110)
    print("BREAK TIME — ПОЛНЫЙ ОТЧЁТ ПАРСЕРА (RU + ET)")
    print("Режим: только чтение сайта; Supabase не используется и не изменяется.")
    print("=" * 110)

    records = parse_menu()
    if not records:
        print("\nОШИБКА: парсер не вернул ни одной записи.")
        return 1

    print(f"\nВсего объединённых записей: {len(records)}")
    print("\n" + "=" * 110)
    print("ВСЕ БЛЮДА")
    print("=" * 110)

    headers = (
        "№", "dish_code", "Название RU", "Название ET", "Категория RU",
        "Категория ET", "product_type", "Цена €", "Вариант цены",
    )
    rows = []
    for index, item in enumerate(records, 1):
        rows.append((
            str(index),
            show(item.get("dish_code")),
            show(item.get("dish_name_ru") or item.get("dish_name")),
            show(item.get("dish_name_et")),
            show(item.get("category_ru")),
            show(item.get("category_et")),
            show(item.get("product_type")),
            show(item.get("price")),
            show(item.get("price_variant")),
        ))

    widths = [min(max(len(headers[i]), *(len(row[i]) for row in rows)), 42)
              for i in range(len(headers))]
    def line(values):
        return " | ".join(str(value)[:widths[i]].ljust(widths[i])
                          for i, value in enumerate(values))

    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(line(row))

    print("\n" + "=" * 110)
    print("СВОДКА И ПРОВЕРКИ")
    print("=" * 110)

    ru_names = sum(bool(x.get("dish_name_ru")) for x in records)
    et_names = sum(bool(x.get("dish_name_et")) for x in records)
    both_names = sum(bool(x.get("dish_name_ru") and x.get("dish_name_et"))
                     for x in records)
    missing_price = [x for x in records if x.get("price") is None]
    invalid_price = []
    for item in records:
        try:
            price = Decimal(str(item.get("price")))
            if not price.is_finite() or price <= 0:
                invalid_price.append(item)
        except (InvalidOperation, TypeError, ValueError):
            invalid_price.append(item)

    missing_code = [x for x in records if not x.get("dish_code")]
    missing_ru_category = [x for x in records if not x.get("category_ru")]
    missing_et_category = [x for x in records if not x.get("category_et")]
    missing_type = [x for x in records if not x.get("product_type")]

    codes = [x.get("dish_code") for x in records if x.get("dish_code")]
    duplicate_codes = [code for code, count in Counter(codes).items() if count > 1]

    print(f"Названий на русском:             {ru_names}/{len(records)}")
    print(f"Названий на эстонском:           {et_names}/{len(records)}")
    print(f"Записей с обоими названиями:     {both_names}/{len(records)}")
    print(f"Без цены:                        {len(missing_price)}")
    print(f"Некорректная/нулевая цена:       {len(invalid_price)}")
    print(f"Без dish_code:                   {len(missing_code)}")
    print(f"Без русской категории:           {len(missing_ru_category)}")
    print(f"Без эстонской категории:         {len(missing_et_category)}")
    print(f"Без product_type:                {len(missing_type)}")
    print(f"Повторяющиеся dish_code:         {len(duplicate_codes)}")

    print("\nКоличество записей по product_type:")
    for kind, count in Counter(x.get("product_type") or "(пусто)"
                               for x in records).most_common():
        print(f"  {kind}: {count}")

    print("\nКоличество записей по категории RU:")
    for category, count in Counter(x.get("category_ru") or "(пусто)"
                                   for x in records).most_common():
        print(f"  {category}: {count}")

    print("\nКоличество записей по категории ET:")
    for category, count in Counter(x.get("category_et") or "(пусто)"
                                   for x in records).most_common():
        print(f"  {category}: {count}")

    issues = []
    checks = (
        ("Нет русского названия", [x for x in records if not x.get("dish_name_ru")]),
        ("Нет эстонского названия", [x for x in records if not x.get("dish_name_et")]),
        ("Нет цены", missing_price),
        ("Некорректная цена", invalid_price),
        ("Нет dish_code", missing_code),
        ("Нет русской категории", missing_ru_category),
        ("Нет эстонской категории", missing_et_category),
        ("Нет product_type", missing_type),
    )
    for label, items in checks:
        if items:
            issues.append((label, items))

    if duplicate_codes:
        print("\n[ПРОВЕРИТЬ] Повторяющиеся dish_code:")
        for code in duplicate_codes:
            print(f"  {code}")

    if issues:
        print("\nЗАПИСИ, ТРЕБУЮЩИЕ ВНИМАНИЯ:")
        for label, items in issues:
            print(f"\n[{label}] — {len(items)}")
            for item in items:
                print(
                    "  "
                    f"code={show(item.get('dish_code'))}; "
                    f"RU={show(item.get('dish_name_ru'))}; "
                    f"ET={show(item.get('dish_name_et'))}; "
                    f"category={show(item.get('category_ru'))} / "
                    f"{show(item.get('category_et'))}; "
                    f"type={show(item.get('product_type'))}; "
                    f"price={show(item.get('price'))}"
                )
    else:
        print("\nАвтоматические проверки заполненности пройдены.")

    print("\nВАЖНО: этот отчёт проверяет структуру и заполненность.")
    print("Правильность перевода и смысловой классификации категорий нужно")
    print("дополнительно просмотреть по таблице ВСЕ БЛЮДА выше.")
    print("=" * 110)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
