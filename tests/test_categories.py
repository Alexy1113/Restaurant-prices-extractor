"""Regression tests for the shared restaurant category taxonomy."""
import unittest

from parsers.categories import canonical_category_ru
from parsers.monk import get_product_type as get_monk_product_type
from parsers.ocean_sushi import (
    get_product_type,
    normalize_baked_category_et,
)


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
                    normalize_baked_category_et(category, product_type),
                    "Maki",
                )

        # A baked gunkan is not a roll and must keep its specific category.
        self.assertEqual(
            normalize_baked_category_et("Küpsetatud Gunkan", "gunkan"),
            "Küpsetatud Gunkan",
        )
        self.assertEqual(normalize_baked_category_et("Maki", "sushi_rolls"), "Maki")

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

    def test_gin_tonic_still_counts_as_drink(self):
        self.assertEqual(get_product_type("Drinks", "Gin Tonic"), "drinks")


if __name__ == "__main__":
    unittest.main()
