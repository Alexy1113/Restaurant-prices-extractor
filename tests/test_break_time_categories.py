"""Break Time-specific classification regressions and shared taxonomy safeguards."""
import unittest

from parsers.break_time import get_product_type as get_break_time_product_type
from parsers.categories import canonical_category_ru, canonical_category_et


class BreakTimeClassificationTests(unittest.TestCase):
    def test_meal_combinations_are_sets_even_when_they_mention_drinks(self):
        cases = (
            ("Напитки", "Шаурма с курицей + картофель фри + напиток", "sets"),
            ("Joogid", "BBQ Burger + Shawarma + 2 jooki", "sets"),
            ("Joogid", "Шаурма с говядиной + картофель фри + напиток", "sets"),
            ("Joogid", "Dubble Shawarma grillkanaga + Mozzarella juustupulgad", "sets"),
            ("Joogid", "Бургер Меню с королевскими креветками", "sets"),
            ("Joogid", "Бургер Кебаб Меню", "sets"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_food_with_sauce_is_not_classified_as_sauce(self):
        cases = (
            ("Соусы", "Куриные стрипсы + сливочно-чесночный соус", "appetizers"),
            ("Kastmed", "Juustupallid + kaste", "appetizers"),
            ("Kastmed", "Картофель фри + соус", "sides"),
            ("Kastmed", "Картофель по-деревенски + соус", "sides"),
            ("Kastmed", "Кольца кальмара + соус", "appetizers"),
            ("Kastmed", "Куриные наггетсы + соус", "appetizers"),
            ("Kastmed", "Овощные рулетики + соус", "appetizers"),
            ("Joogid", "Пивная тарелка + 2 соуса", "appetizers"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_main_dishes_do_not_become_sides_because_of_garnish(self):
        cases = (
            ("Lisandid", "Grillitud lõhesteik värskete köögiviljadega", "main_courses"),
            ("Lisandid", "Armeenia šašlõkk värskete köögiviljadega", "main_courses"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_drink_words_in_food_names_do_not_override_food_product_type(self):
        self.assertEqual(
            canonical_category_ru(
                "sets", category_ru="Напитки", category_et="Joogid",
                dish_name="Шаурма + картофель фри + напиток",
            ),
            "Сеты",
        )
        self.assertEqual(
            canonical_category_et(
                "sets", category_ru="Напитки", category_et="Joogid",
                dish_name="Shawarma + fries + drink",
            ),
            "Komplektid",
        )

    def test_dessert_with_coffee_in_name_stays_dessert(self):
        self.assertEqual(
            canonical_category_ru(
                "desserts", category_ru="Напитки", category_et="Joogid",
                dish_name="Vormitud magustoidud Kohv",
            ),
            "Десерты",
        )
        self.assertEqual(
            canonical_category_et(
                "desserts", category_ru="Напитки", category_et="Joogid",
                dish_name="Vormitud magustoidud Kohv",
            ),
            "Magustoidud",
        )

    def test_alcohol_detection_still_uses_name_for_drink_type(self):
        self.assertEqual(
            canonical_category_ru("drinks", "Напитки", "Joogid", "Gin 0.5l"),
            "Алкогольные напитки (18+)",
        )
        self.assertEqual(
            canonical_category_et("drinks", "Напитки", "Joogid", "Gin 0.5l"),
            "Alkohoolsed joogid (18+)",
        )


if __name__ == "__main__":
    unittest.main()
