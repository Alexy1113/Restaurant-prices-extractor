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
            ("Nuudlid", "Rannakarbid koores", "main_courses"),
            ("Eelroad", "Kanaribad ahjukartuli ja köögiviljadega", "main_courses"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_mussels_are_appetizers(self):
        cases = (
            ("Eelroad", "Paneeritud rannakarbid", "appetizers"),
            ("Nuudlid", "Rannakarbid koorega", "appetizers"),
            ("Закуски", "Нежнейшие мидии в хрустящей панировке", "appetizers"),
            ("Лапша", "Мидии в ракушке", "appetizers"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name, category=category):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_wrap_shawarma_doner_and_kebab_share_tortillas_type(self):
        cases = (
            ("Wraps", "Chicken wrap", "tortillas"),
            ("Tortillad", "Kana tortilla", "tortillas"),
            ("Shawarma", "Chicken shawarma", "tortillas"),
            ("Дёнер-кебаб", "Дёнер-кебаб", "tortillas"),
            ("Kebab", "Döner kebab", "tortillas"),
            ("Brrrum", "Brrrum kanaga", "tortillas"),
            ("Лаваш", "Бургер в лаваше", "tortillas"),
            ("Основные блюда", "Шаурма с курицей", "tortillas"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name, category=category):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_standalone_hot_dogs_use_the_dedicated_category(self):
        cases = (
            ("Hot Dog", "Classic hot dog", "hot_dogs"),
            ("Hot-Dog", "Klassikaline hot dog", "hot_dogs"),
            ("Pearoad", "Klassikaline hot dog", "hot_dogs"),
            ("Praad", "Hot dog vorstiga", "hot_dogs"),
            ("Основные блюда", "Классический хот-дог", "hot_dogs"),
        )
        for category, name, expected in cases:
            with self.subTest(category=category, name=name):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_hot_dogs_in_lavash_are_tortillas(self):
        cases = (
            ("Hot Dog", "Hot dog в лаваше", "tortillas"),
            ("Hot Dog", "Двойной Hot dog в лаваше", "tortillas"),
            ("Hot Dog", "Hot dog lavas", "tortillas"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_standalone_burger_kebab_is_a_burger_but_menu_is_a_set(self):
        self.assertEqual(
            get_break_time_product_type("Kebab", "Бургер Кебаб"),
            "burgers",
        )
        self.assertEqual(
            get_break_time_product_type("Kebab", "Бургер Кебаб Меню"),
            "sets",
        )


    def test_every_product_in_praad_section_is_a_main_course(self):
        cases = (
            ("Praad", "Friikartulid viineritega", "main_courses"),
            ("Жаркое", "Картофель фри с сосисками и овощами + соус", "main_courses"),
            ("Жаркое", 'Картофель фри "веселая улыбка" с наггетсами и соусом', "main_courses"),
            ("Praad", "Friikartulid viineritega", "main_courses"),
            ("Жаркое", "Куриные стрипсы с картофелем по-деревенски и овощами", "main_courses"),
            ("Жаркое", "Белая рыба с картофелем по-деревенски и овощами", "main_courses"),
        )
        for category, name, expected in cases:
            with self.subTest(name=name, category=category):
                self.assertEqual(get_break_time_product_type(category, name), expected)

    def test_standalone_strips_outside_praad_remain_appetizers(self):
        self.assertEqual(
            get_break_time_product_type("Eelroad", "Kanaribad"),
            "appetizers",
        )
        self.assertEqual(
            get_break_time_product_type("Закуски", "Куриные стрипсы"),
            "appetizers",
        )

    def test_onion_rings_are_appetizers_not_sides(self):
        self.assertEqual(
            get_break_time_product_type("Lisandid", "Sibularõngad"),
            "appetizers",
        )
        self.assertEqual(
            get_break_time_product_type("Гарниры", "Луковые кольца"),
            "appetizers",
        )

    def test_drink_words_in_food_names_do_not_override_food_product_type(self):
        self.assertEqual(
            canonical_category_ru(
                "sets", category_ru="Напитки", category_et="Joogid",
                dish_name="Шаурма + картофель фри + напиток",
            ),
            "Наборы и комбо",
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
