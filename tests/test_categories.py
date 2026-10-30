"""Regression tests for the shared restaurant category taxonomy."""
import unittest

from parsers.categories import canonical_category_ru, canonical_category_et
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
        self.assertEqual(canonical_category_ru("sets", "Комплекты"), "Сеты")
        self.assertEqual(canonical_category_ru("sushi_rolls", "Суши"), "Роллы")
        self.assertEqual(canonical_category_ru("hosomaki", "Хосомаки"), "Роллы")

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
            ("main_courses", "Основные блюда", "Põhiroad"),
            ("appetizers", "Закуски", "Eelroad"),
            ("sides", "Гарниры", "Lisandid"),
            ("salads", "Салаты", "Salatid"),
            ("desserts", "Десерты", "Magustoidud"),
            ("sushi_rolls", "Роллы", "Maki"),
            ("gunkan", "Гунканы", "Gunkanid"),
            ("sets", "Сеты", "Komplektid"),
            ("soups", "Супы", "Supid"),
            ("noodles", "Лапша", "Nuudlid"),
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
            "Роллы",
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
                    "Роллы",
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
                    "Роллы",
                )
                self.assertEqual(
                    canonical_category_et(
                        product_type,
                        category_ru="Роллы",
                        category_et=category,
                        dish_name=name,
                    ),
                    "Maki",
                )

        # A baked gunkan maps to the regular gunkan category in Estonian.
        self.assertEqual(
            canonical_category_et(
                "gunkan",
                category_ru="Гунканы",
                category_et="Küpsetatud Gunkan",
                dish_name="Lõhe Gunkan",
            ),
            "Gunkanid",
        )
        self.assertEqual(
            canonical_category_et("sushi_rolls", category_ru="Роллы", category_et="Maki"),
            "Maki",
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
                    "Роллы",
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
                    "Роллы",
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
                    "Põhiroad",
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


    def test_pizza_category_is_canonical_in_both_languages(self):
        self.assertEqual(
            canonical_category_ru("pizzas", category_ru="Pizzad", category_et="Pitsad"),
            "Пицца",
        )
        self.assertEqual(
            canonical_category_et("pizzas", category_ru="Пицца", category_et="Pizzad"),
            "Pitsad",
        )


    def test_pasta_category_is_canonical_in_both_languages(self):
        self.assertEqual(
            canonical_category_ru("pasta", category_ru="Pastad", category_et="Pastad"),
            "Паста",
        )
        self.assertEqual(
            canonical_category_et("pasta", category_ru="Паста", category_et="Pastad"),
            "Pastad",
        )


if __name__ == "__main__":
    unittest.main()
