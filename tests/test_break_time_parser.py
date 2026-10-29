"""Regression tests for the Break Time Burger & Wrap parser."""
import unittest

from bs4 import BeautifulSoup

from parsers.break_time import (
    get_cards,
    get_price,
    get_product_type,
    merge_language_records,
)
from parsers.categories import canonical_category_et, canonical_category_ru


class BreakTimeCategoryTests(unittest.TestCase):
    def test_burgers_use_shared_burger_category(self):
        self.assertEqual(get_product_type("Burgerid", "Klassikaline veiselihaburger"), "burgers")
        self.assertEqual(
            canonical_category_ru("burgers", category_et="Burgerid"),
            "Бургеры",
        )
        self.assertEqual(
            canonical_category_et("burgers", category_ru="Бургеры", category_et="Burgerid"),
            "Burgerid",
        )

    def test_burger_meal_is_a_set_but_plain_fries_are_a_side(self):
        self.assertEqual(
            get_product_type("Eine", "Klassikaline Veiselihaburger Eine"),
            "sets",
        )
        self.assertEqual(
            get_product_type("Eine", "Friikartulid + kaste"),
            "sides",
        )

    def test_lavash_uses_existing_tortilla_category(self):
        self.assertEqual(
            get_product_type("Lavash", "Lavašš kana ja juustuga"),
            "tortillas",
        )
        self.assertEqual(
            canonical_category_ru("tortillas", category_et="Lavash"),
            "Тортильи",
        )

    def test_shawarma_kebab_and_hot_dog_do_not_create_new_categories(self):
        self.assertEqual(get_product_type("Shawarma", "Shawarma kanalihaga"), "main_courses")
        self.assertEqual(get_product_type("Kebab", "Kebab veiselihaga"), "main_courses")
        self.assertEqual(get_product_type("Hot dog", "Hot dog lavas"), "main_courses")

    def test_drinks_sauces_and_snacks_use_existing_types(self):
        self.assertEqual(get_product_type("Alkohoolsed joogid", "Gin 0,5 l"), "drinks")
        self.assertEqual(get_product_type("Kastmed", "Küüslaugukaste"), "sauces")
        self.assertEqual(get_product_type("Suupisted", "Kartul friikartulid + kaste"), "appetizers")


class BreakTimeHtmlTests(unittest.TestCase):
    def test_current_sale_price_is_used_instead_of_old_price(self):
        soup = BeautifulSoup(
            """
            <ul class="products">
              <li class="product">
                <h2 class="woocommerce-loop-product__title">BBQ Burger</h2>
                <span class="price">
                  <del><span class="woocommerce-Price-amount">€10,00</span></del>
                  <ins><span class="woocommerce-Price-amount">€8,50</span></ins>
                </span>
              </li>
            </ul>
            """,
            "html.parser",
        )
        cards = get_cards(soup)
        self.assertEqual(len(cards), 1)
        self.assertEqual(get_price(cards[0]), 8.50)

    def test_ru_and_et_names_merge_when_unambiguous(self):
        russian = [{
            "dish_code": "break-time:site:10",
            "source_id": "site:10",
            "name": "Klassikaline Burger",
            "price": 8.5,
            "price_variant": None,
            "category": "Бургеры",
            "product_type": "burgers",
            "language": "ru",
        }]
        estonian = [{
            "dish_code": "break-time:site:99",
            "source_id": "site:99",
            "name": "Klassikaline Burger",
            "price": 8.5,
            "price_variant": None,
            "category": "Burgerid",
            "product_type": "burgers",
            "language": "et",
        }]

        result = merge_language_records(russian, estonian)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dish_name_ru"], "Klassikaline Burger")
        self.assertEqual(result[0]["dish_name_et"], "Klassikaline Burger")
        self.assertEqual(result[0]["category_ru"], "Бургеры")
        self.assertEqual(result[0]["category_et"], "Burgerid")

    def test_untranslated_product_with_eesti_prefix_is_matched(self):
        russian = [{
            "dish_code": "break-time:name:1",
            "source_id": None,
            "name": "(Eesti) Arizona sidrun jäätee",
            "price": 2.7,
            "price_variant": None,
            "category": "Напитки",
            "product_type": "drinks",
            "language": "ru",
        }]
        estonian = [{
            "dish_code": "break-time:name:2",
            "source_id": None,
            "name": "Arizona sidrun jäätee",
            "price": 2.7,
            "price_variant": None,
            "category": "Joogid",
            "product_type": "drinks",
            "language": "et",
        }]

        result = merge_language_records(russian, estonian)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dish_name_ru"], "(Eesti) Arizona sidrun jäätee")
        self.assertEqual(result[0]["dish_name_et"], "Arizona sidrun jäätee")


if __name__ == "__main__":
    unittest.main()
