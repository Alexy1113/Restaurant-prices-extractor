"""Regression tests for the shared restaurant category taxonomy."""
import unittest

from parsers.categories import (
    CATEGORIES,
    category_label,
    get_category_emoji,
    resolve_category_key,
    canonical_category_ru,
    canonical_category_et,
)
from parsers.hesburger import get_product_type as get_hesburger_product_type
from parsers.monk import get_product_type as get_monk_product_type
from parsers.ocean_sushi import get_product_type


class CategoryNormalizationTests(unittest.TestCase):
    def test_gunkan_variants_share_one_category(self):
        for source in ("Гункан", "Острый гункан", "Запечённый гункан"):
            with self.subTest(source=source):
                self.assertEqual(
                    canonical_category_ru("gunkan", category_ru=source),
                    "Гунканы",
                )

    def test_sets_and_roll_variants_are_unified(self):
        self.assertEqual(canonical_category_ru("sets", "Комплекты"), "Наборы и комбо")
        self.assertEqual(canonical_category_ru("sushi_rolls", "Суши"), "Роллы и маки")
        self.assertEqual(canonical_category_ru("hosomaki", "Хосомаки"), "Роллы и маки")

    def test_restaurant_parsers_emit_the_shared_hot_dogs_product_type(self):
        self.assertEqual(get_monk_product_type("Hot Dog", "Classic"), "hot_dogs")
        self.assertEqual(get_monk_product_type("Основные блюда", "Classic hot dog"), "hot_dogs")
        self.assertEqual(get_monk_product_type("Hot Dog", "Hot dog lavas"), "tortillas")
        self.assertEqual(get_hesburger_product_type("Hot Dog", "Classic hot dog"), "hot_dogs")

    def test_hot_dogs_share_a_dedicated_category_across_languages_and_legacy_types(self):
        self.assertEqual(category_label("hot_dogs", "Русский"), "Хот-доги")
        self.assertEqual(category_label("hot_dogs", "Eesti"), "Hot dogid")
        self.assertEqual(get_category_emoji("hot_dogs"), "🌭")

        for product_type in ("hot_dogs", "hotdog", "hot_dog", "hotdogs"):
            with self.subTest(product_type=product_type):
                self.assertEqual(resolve_category_key(product_type), "hot_dogs")
                self.assertEqual(canonical_category_ru(product_type), "Хот-доги")
                self.assertEqual(canonical_category_et(product_type), "Hot dogid")

        # Older or future parsers may only return main_courses/other; the
        # shared resolver still recognizes the category heading or dish name.
        self.assertEqual(resolve_category_key("main_courses", "Hot Dog"), "hot_dogs")
        self.assertEqual(
            resolve_category_key("main_courses", "Основные блюда", dish_name="Classic hot dog"),
            "hot_dogs",
        )
        self.assertEqual(
            resolve_category_key("main_courses", "Основные блюда", "Pearoad", "Klassikaline hot dog"),
            "hot_dogs",
        )

        # A hot dog served in lavash remains a wrap, not a standalone hot dog.
        self.assertEqual(
            resolve_category_key("main_courses", "Hot Dog", dish_name="Hot dog in lavash"),
            "tortillas",
        )
        self.assertEqual(
            resolve_category_key("tortillas", "Hot Dog", dish_name="Hot dog lavas"),
            "tortillas",
        )

    def test_alcohol_age_warning_is_preserved(self):
        self.assertEqual(
            canonical_category_ru("drinks", "Вино (18+)", "Joogid"),
            "Алкогольные напитки (18+)",
        )
        self.assertEqual(
            canonical_category_ru("drinks", "Игристое вино и шампанское (18+)"),
            "Алкогольные напитки (18+)",
        )

    def test_estonian_alcohol_subcategories_merge_like_russian_category(self):
        source_categories = (
            "Lahja alkohol (18+)",
            "Vein (18+)",
            "Vahuvein ja šampanja (18+)",
        )
        for source_category in source_categories:
            with self.subTest(source_category=source_category):
                self.assertEqual(
                    canonical_category_et(
                        "drinks",
                        category_ru="Алкогольные напитки (18+)",
                        category_et=source_category,
                    ),
                    "Alkohoolsed joogid (18+)",
                )

        self.assertEqual(
            canonical_category_et("drinks", category_ru="Напитки", category_et="Joogid"),
            "Joogid",
        )

    def test_estonian_categories_follow_shared_russian_category_taxonomy(self):
        cases = (
            ("main_courses", "Основные блюда", "Pearoad"),
            ("appetizers", "Закуски", "Eelroad"),
            ("tortillas", "Тортильи", "Tortillad"),
            ("sides", "Гарниры", "Lisandid"),
            ("salads", "Салаты", "Salatid"),
            ("desserts", "Десерты", "Magustoidud"),
            ("sushi_rolls", "Роллы и маки", "Sushirullid ja maki"),
            ("gunkan", "Гунканы", "Gunkan"),
            ("sets", "Наборы и комбо", "Komplektid"),
            ("soups", "Супы", "Supid"),
            ("noodles", "Лапша и Паста", "Nuudlid ja pasta"),
        )
        for product_type, category_ru, expected_et in cases:
            with self.subTest(product_type=product_type):
                self.assertEqual(
                    canonical_category_et(
                        product_type,
                        category_ru=category_ru,
                        category_et="Küpsetatud",
                    ),
                    expected_et,
                )

    def test_unknown_category_does_not_create_et_only_group_when_ru_is_generic(self):
        self.assertEqual(
            canonical_category_et(
                "other",
                category_ru="Другое",
                category_et="Küpsetatud",
            ),
            "Muu",
        )
        # If Russian has a meaningful, unclassified category, retain its ET
        # counterpart rather than inventing a product type.
        self.assertEqual(
            canonical_category_et(
                "other",
                category_ru="Запечённые",
                category_et="Küpsetatud",
            ),
            "Küpsetatud",
        )

    def test_standalone_tempura_stays_separate(self):
        self.assertEqual(
            canonical_category_ru("tempura", "Темпура", "Tempura", "Kana tempura"),
            "Темпура",
        )
        self.assertEqual(
            canonical_category_ru("tempura", "Суши", "Sushi", "Ebi tempura"),
            "Роллы и маки",
        )

    def test_ocean_sushi_hot_baked_rolls_are_grouped_as_rolls(self):
        names = (
            "Hot Salmon",
            "Hot Oishi",
            "Hot Bussido",
            "Hot Jatomi",
            "Hot Sakai",
            "Hot Kiesu",
            "Hot Tuna",
            "Hot Krevett",
            "Hot Sapporo",
            "Hot Jamoto",
            "Hot Unagi (10 шт)",
            "Hot Tojako (10 шт)",
        )
        for name in names:
            with self.subTest(name=name):
                product_type = get_product_type("Запечённые", name)
                self.assertEqual(product_type, "sushi_rolls")
                self.assertEqual(
                    canonical_category_ru(
                        product_type,
                        category_ru="Запечённые",
                        dish_name=name,
                    ),
                    "Роллы и маки",
                )

    def test_ocean_sushi_baked_roll_category_normalized_in_both_languages(self):
        cases = (
            ("Запечённые", "Hot Salmon"),
            ("Baked", "Hot Tuna"),
            ("Küpsetatud", "Hot Krevett"),
        )
        for category, name in cases:
            with self.subTest(category=category, name=name):
                product_type = get_product_type(category, name)
                self.assertEqual(product_type, "sushi_rolls")
                self.assertEqual(
                    canonical_category_ru(product_type, category_ru=category, dish_name=name),
                    "Роллы и маки",
                )
                self.assertEqual(
                    canonical_category_et(
                        product_type,
                        category_ru="Роллы",
                        category_et=category,
                        dish_name=name,
                    ),
                    "Sushirullid ja maki",
                )

        # A baked gunkan maps to the regular gunkan category in Estonian.
        self.assertEqual(
            canonical_category_et(
                "gunkan",
                category_ru="Гунканы",
                category_et="Küpsetatud Gunkan",
                dish_name="Lõhe Gunkan",
            ),
            "Gunkan",
        )
        self.assertEqual(
            canonical_category_et("sushi_rolls", category_ru="Роллы", category_et="Maki"),
            "Sushirullid ja maki",
        )

    def test_ocean_sushi_baked_gunkan_remains_gunkan(self):
        cases = (
            ("Küpsetatud Gunkan", "Lõhe Gunkan"),
            ("Запечённые Гунканы", "Гункан с лососем"),
        )
        for category, name in cases:
            with self.subTest(category=category, name=name):
                product_type = get_product_type(category, name)
                self.assertEqual(product_type, "gunkan")
                self.assertEqual(
                    canonical_category_ru(
                        product_type,
                        category_ru=category,
                        dish_name=name,
                    ),
                    "Гунканы",
                )

    def test_ocean_sushi_baked_section_items_are_rolls_even_without_hot_name(self):
        cases = (
            ("Запечённые", "Salmon"),
            ("Запеченные", "Ebi"),
            ("Baked", "Tuna"),
            ("Küpsetatud", "Lõhe"),
        )
        for category, name in cases:
            with self.subTest(category=category, name=name):
                product_type = get_product_type(category, name)
                self.assertEqual(product_type, "sushi_rolls")
                self.assertEqual(
                    canonical_category_ru(
                        product_type,
                        category_ru=category,
                        dish_name=name,
                    ),
                    "Роллы и маки",
                )

    def test_monk_baked_sushi_section_is_grouped_as_rolls(self):
        cases = (
            ("Запечённые", "Hot Salmon"),
            ("Запеченные", "Hot Tuna"),
            ("Baked", "Hot Unagi"),
            ("Küpsetatud", "Hot Krevett"),
        )
        for category, name in cases:
            with self.subTest(category=category, name=name):
                product_type = get_monk_product_type(category, name)
                self.assertEqual(product_type, "sushi_rolls")
                self.assertEqual(
                    canonical_category_ru(
                        product_type,
                        category_ru=category,
                        dish_name=name,
                    ),
                    "Роллы и маки",
                )

    def test_unknown_baked_section_is_not_guessed(self):
        self.assertEqual(
            canonical_category_ru("other", "Запечённые"),
            "Запечённые",
        )

    def test_steak_and_ginger_do_not_trigger_drinks(self):
        self.assertEqual(get_product_type("Маки", "Steak Maki"), "sushi_rolls")
        self.assertEqual(get_product_type("Маки", "Ginger Maki"), "sushi_rolls")

    def test_short_words_do_not_classify_food_as_drinks(self):
        for name in ("Steak", "Steak Maki", "Ginger", "Ginger Maki"):
            with self.subTest(name=name):
                self.assertEqual(
                    canonical_category_ru(
                        "main_courses",
                        category_ru="Основные блюда",
                        dish_name=name,
                    ),
                    "Основные блюда",
                )
                self.assertEqual(
                    canonical_category_et(
                        "main_courses",
                        category_ru="Основные блюда",
                        category_et="Põhiroad",
                        dish_name=name,
                    ),
                    "Pearoad",
                )

    def test_alcohol_is_detected_from_dish_name_in_generic_drinks_category(self):
        cases = (
            ("Gin", "Алкогольные напитки (18+)", "Alkohoolsed joogid (18+)"),
            ("Vodka", "Алкогольные напитки (18+)", "Alkohoolsed joogid (18+)"),
            ("Whisky", "Алкогольные напитки (18+)", "Alkohoolsed joogid (18+)"),
            ("Gin Tonic", "Алкогольные напитки (18+)", "Alkohoolsed joogid (18+)"),
            ("Coca-Cola", "Напитки", "Joogid"),
        )
        for name, expected_ru, expected_et in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    canonical_category_ru(
                        "drinks",
                        category_ru="Напитки",
                        category_et="Joogid",
                        dish_name=name,
                    ),
                    expected_ru,
                )
                self.assertEqual(
                    canonical_category_et(
                        "drinks",
                        category_ru="Напитки",
                        category_et="Joogid",
                        dish_name=name,
                    ),
                    expected_et,
                )

    def test_explicit_alcohol_product_type_keeps_alcohol_category(self):
        self.assertEqual(
            canonical_category_ru(
                "alcoholic_drinks",
                category_ru="Напитки",
                dish_name="Unknown drink name",
            ),
            "Алкогольные напитки (18+)",
        )
        self.assertEqual(
            canonical_category_et(
                "alcoholic_drinks",
                category_ru="Напитки",
                category_et="Joogid",
                dish_name="Unknown drink name",
            ),
            "Alkohoolsed joogid (18+)",
        )

    def test_regular_beverages_stay_in_general_drinks_category(self):
        cases = ("Coffee", "Tea", "Coca-Cola", "Orange juice", "Lemonade")
        for name in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    canonical_category_ru(
                        "drinks",
                        category_ru="Напитки",
                        category_et="Joogid",
                        dish_name=name,
                    ),
                    "Напитки",
                )
                self.assertEqual(
                    canonical_category_et(
                        "drinks",
                        category_ru="Напитки",
                        category_et="Joogid",
                        dish_name=name,
                    ),
                    "Joogid",
                )

    def test_gin_tonic_still_counts_as_drink(self):
        self.assertEqual(get_product_type("Drinks", "Gin Tonic"), "drinks")


    def test_registry_owns_all_canonical_labels_and_emojis(self):
        expected = {
            "sets": ("Наборы и комбо", "Komplektid", "📦"),
            "sushi_rolls": ("Роллы и маки", "Sushirullid ja maki", "🍣"),
            "sauces": ("Соусы и добавки", "Kastmed ja lisandid", "🌶️"),
            "syrups": ("Сиропы и добавки", "Siirupid ja lisandid", "🍯"),
            "breakfast": ("Завтраки", "Hommikusöök", "🍳"),
            "main_courses": ("Основные блюда", "Pearoad", "🍛"),
            "gunkan": ("Гунканы", "Gunkan", "🍣"),
            "bowls": ("Боулы", "Bow'id", "🥣"),
            "tortillas": ("Тортильи", "Tortillad", "🌯"),
        }
        for key, (expected_ru, expected_et, emoji) in expected.items():
            with self.subTest(category=key):
                self.assertEqual(category_label(key, "Русский"), expected_ru)
                self.assertEqual(category_label(key, "Eesti"), expected_et)
                self.assertEqual(CATEGORIES[key]["emoji"], emoji)
                self.assertEqual(get_category_emoji(key), emoji)

    def test_distinct_categories_remain_distinct(self):
        self.assertEqual(resolve_category_key("drinks", "Напитки", "Joogid"), "drinks")
        self.assertEqual(
            resolve_category_key("drinks", "Алкогольные напитки (18+)", "Joogid"),
            "alcoholic_drinks",
        )
        self.assertEqual(resolve_category_key("appetizers"), "appetizers")
        self.assertEqual(resolve_category_key("sides"), "sides")
        self.assertEqual(resolve_category_key("sushi_rolls"), "sushi_rolls")
        self.assertEqual(resolve_category_key("nigiri"), "nigiri")
        self.assertEqual(resolve_category_key("sashimi"), "sashimi")
        self.assertEqual(resolve_category_key("sauces"), "sauces")
        self.assertEqual(resolve_category_key("syrups"), "syrups")

    def test_legacy_category_labels_resolve_to_the_new_canonical_labels(self):
        cases = (
            ("tortillas", "Врапы и шаурма", "Wrapid ja kebabid", "Тортильи", "Tortillad"),
            ("sets", "Сеты", "Komplektid", "Наборы и комбо", "Komplektid"),
            ("sushi_rolls", "Роллы", "Maki", "Роллы и маки", "Sushirullid ja maki"),
        )
        for product_type, ru_source, et_source, expected_ru, expected_et in cases:
            with self.subTest(product_type=product_type):
                self.assertEqual(canonical_category_ru(product_type, ru_source, et_source), expected_ru)
                self.assertEqual(canonical_category_et(product_type, ru_source, et_source), expected_et)

    def test_pizza_category_is_canonical_in_both_languages(self):
        self.assertEqual(
            canonical_category_ru("pizzas", category_ru="Pizzad", category_et="Pitsad"),
            "Пицца",
        )
        self.assertEqual(
            canonical_category_et("pizzas", category_ru="Пицца", category_et="Pizzad"),
            "Pitsad",
        )


    def test_noodles_and_pasta_share_one_category_in_both_languages(self):
        for product_type in ("noodles", "pasta"):
            with self.subTest(product_type=product_type):
                self.assertEqual(
                    canonical_category_ru(product_type),
                    "Лапша и Паста",
                )
                self.assertEqual(
                    canonical_category_et(product_type),
                    "Nuudlid ja pasta",
                )

    def test_source_pasta_and_noodles_headings_are_unified_even_if_type_is_generic(self):
        cases = (
            ("main_courses", "Паста и бириани", "Pasta"),
            ("other", "Лапша", "Nuudlid"),
            ("main_courses", "Pasta", "Pastad"),
        )
        for product_type, category_ru, category_et in cases:
            with self.subTest(category_ru=category_ru, category_et=category_et):
                self.assertEqual(
                    canonical_category_ru(product_type, category_ru, category_et),
                    "Лапша и Паста",
                )
                self.assertEqual(
                    canonical_category_et(product_type, category_ru, category_et),
                    "Nuudlid ja pasta",
                )

    def test_monk_pasta_and_noodles_sections_keep_specific_product_types(self):
        cases = (
            ("Pasta", "Creamy pasta", "pasta"),
            ("Паста и бириани", "Chicken biryani", "pasta"),
            ("Лапша", "Удон с курицей", "noodles"),
            ("Nuudlid", "Kana nuudlid", "noodles"),
        )
        for category, name, expected in cases:
            with self.subTest(category=category, name=name):
                self.assertEqual(get_monk_product_type(category, name), expected)


if __name__ == "__main__":
    unittest.main()
