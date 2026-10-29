"""Regression tests for the Break Time Burger & Wrap parser."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.break_time import (
    get_cards,
    get_categories,
    get_price,
    get_product_type,
    merge_language_records,
    _catalog_context,
    _discover_category_urls,
    _known_category_urls,
    _url_matches_language,
    parse_menu,
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

    def test_ice_cream_cocktails_map_to_existing_drinks_category(self):
        self.assertEqual(
            get_product_type("Kokteilid", "Jäätisekokteil maasikaga"),
            "ice_cream_shakes",
        )
        self.assertEqual(
            canonical_category_ru("ice_cream_shakes", category_et="Kokteilid"),
            "Напитки",
        )
        self.assertEqual(
            canonical_category_et(
                "ice_cream_shakes",
                category_ru="Напитки",
                category_et="Kokteilid",
            ),
            "Joogid",
        )

    def test_steak_is_not_misclassified_as_tea(self):
        self.assertEqual(get_product_type("Praad", "Steak tartare"), "main_courses")

    def test_categories_seen_on_live_ida_toit_menu_map_to_shared_types(self):
        cases = (
            ("Alkohoolsed joogid", "Gin", "drinks"),
            ("Burgerid", "Klassikaline Veiselihaburger", "burgers"),
            ("Grill", "BBQ grillkanaga", "main_courses"),
            ("Hommikusöök", "Omelett", "breakfast"),
            ("Hot dog", "Hot dog", "main_courses"),
            ("Joogid", "Pepsi", "drinks"),
            ("Kuumad joogid", "Kakao", "drinks"),
            ("Kastmed", "Küüslaugukaste", "sauces"),
            ("Kebab", "Kebab veiselihaga", "main_courses"),
            ("Kombineeritud", "Komplekt", "sets"),
            ("Lavash", "Lavašš kana ja juustuga", "tortillas"),
            ("Magustoit", "Magusad pannkoogid", "desserts"),
            ("Nuudlid", "Nuudlid krevettidega", "noodles"),
            ("Pannkoogid", "Magusad pannkoogid", "desserts"),
            ("Praad", "Steak tartare", "main_courses"),
            ("Salat", "Kanasalat", "salads"),
            ("Shawarma", "Shawarma kanalihaga", "main_courses"),
            ("Doner", "Döner grillkanaga", "main_courses"),
            ("Supid", "Kanasupp", "soups"),
            ("Suupisted", "Paneeritud krevetid", "appetizers"),
            ("Блины", "Блины с шоколадом", "desserts"),
            ("Закуски", "Куриные крылышки", "appetizers"),
        )
        for category, name, expected in cases:
            with self.subTest(category=category, name=name):
                self.assertEqual(get_product_type(category, name), expected)

    def test_estonian_category_matching_normalizes_diacritics(self):
        self.assertEqual(
            get_product_type("Hommikusöök", "Omlett"),
            "breakfast",
        )
        self.assertEqual(
            get_product_type("Nuudlid", "Nuudlid krevettidega"),
            "noodles",
        )
        self.assertEqual(
            get_product_type("Magustoit", "Jäätisetort"),
            "desserts",
        )

    def test_drinks_sauces_and_snacks_use_existing_types(self):
        self.assertEqual(get_product_type("Alkohoolsed joogid", "Gin 0,5 l"), "drinks")
        self.assertEqual(get_product_type("Kastmed", "Küüslaugukaste"), "sauces")
        self.assertEqual(get_product_type("Suupisted", "Kartul friikartulid + kaste"), "appetizers")


class BreakTimeCatalogDiscoveryTests(unittest.TestCase):
    def test_language_guard_rejects_redirects_to_the_other_locale(self):
        self.assertTrue(
            _url_matches_language("https://ida-toit.ee/ru/tootekategooria/burgerid/", "ru")
        )
        self.assertFalse(
            _url_matches_language("https://ida-toit.ee/ru/tootekategooria/burgerid/", "et")
        )
        self.assertTrue(
            _url_matches_language("https://ida-toit.ee/tootekategooria/burgerid/", "et")
        )
        self.assertFalse(
            _url_matches_language("https://ida-toit.ee/tootekategooria/burgerid/", "ru")
        )

    def test_discovers_only_category_pages_for_requested_language(self):
        soup = BeautifulSoup(
            """
            <nav>
              <a href="/ru/tootekategooria/burgerid/">Бургеры</a>
              <a href="/tootekategooria/eine/">Eine</a>
              <a href="/ru/toode/burger/">Product</a>
            </nav>
            """,
            "html.parser",
        )
        russian = _discover_category_urls(soup, "https://ida-toit.ee/ru/", "ru")
        estonian = _discover_category_urls(soup, "https://ida-toit.ee/", "et")
        self.assertEqual(russian, ["https://ida-toit.ee/ru/tootekategooria/burgerid/"])
        self.assertEqual(estonian, ["https://ida-toit.ee/tootekategooria/eine/"])

    def test_catalog_context_matches_same_category_page_across_languages(self):
        ru = _catalog_context(
            "https://ida-toit.ee/ru/tootekategooria/burgerid/page/2/"
        )
        et = _catalog_context(
            "https://ida-toit.ee/tootekategooria/burgerid/page/2/"
        )
        self.assertEqual(ru, ("burgerid", 12))
        self.assertEqual(et, ru)

    def test_known_menu_categories_seed_twenty_urls_for_each_language(self):
        estonian = _known_category_urls("et")
        russian = _known_category_urls("ru")

        self.assertEqual(len(estonian), 20)
        self.assertEqual(len(russian), 20)
        self.assertTrue(all(
            url.startswith("https://ida-toit.ee/tootekategooria/")
            for url in estonian
        ))
        self.assertTrue(all(
            url.startswith("https://ida-toit.ee/ru/tootekategooria/")
            for url in russian
        ))


class BreakTimeSessionTests(unittest.TestCase):
    def test_parse_menu_uses_separate_http_sessions_for_each_language(self):
        sessions = []
        parsed_sessions = []

        def make_session():
            session = SimpleNamespace(headers={})
            sessions.append(session)
            return session

        def fake_parse_language(session, language):
            parsed_sessions.append((session, language))
            return []

        with patch("parsers.break_time.requests.Session", side_effect=make_session):
            with patch("parsers.break_time.parse_language", side_effect=fake_parse_language):
                parse_menu()

        self.assertEqual(len(sessions), 2)
        self.assertEqual([language for _, language in parsed_sessions], ["ru", "et"])
        self.assertIsNot(parsed_sessions[0][0], parsed_sessions[1][0])


class BreakTimeCategorySlugTests(unittest.TestCase):
    def test_category_slug_fallback_reads_custom_theme_classes(self):
        soup = BeautifulSoup(
            '<li class="product product_cat-kokteilid"><h2>Virsiku kokteil</h2></li>',
            "html.parser",
        )
        card = soup.select_one("li.product")
        categories = get_categories(card)
        self.assertEqual(categories, ["kokteilid"])
        self.assertEqual(get_product_type(" ".join(categories), "Virsiku kokteil"), "ice_cream_shakes")

    def test_estonian_lavas_slug_maps_to_tortillas(self):
        self.assertEqual(get_product_type("lavas", "Kana lavašš"), "tortillas")


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

    def test_popular_homepage_sections_are_excluded_from_product_cards(self):
        soup = BeautifulSoup(
            """
            <main>
              <section>
                <h2>Populaarsed valikud</h2>
                <ul class="products">
                  <li class="product">
                    <h2 class="woocommerce-loop-product__title">Popular item ET</h2>
                    <span class="price">€4,50</span>
                  </li>
                </ul>
              </section>
              <section>
                <h2>Популярные блюда</h2>
                <ul class="products">
                  <li class="product">
                    <h2 class="woocommerce-loop-product__title">Popular item RU</h2>
                    <span class="price">€5,00</span>
                  </li>
                </ul>
              </section>
              <section class="menu-category-products">
                <h2>Menu products</h2>
                <ul class="products">
                  <li class="product">
                    <h2 class="woocommerce-loop-product__title">Actual category item</h2>
                    <span class="price">€7,00</span>
                  </li>
                </ul>
              </section>
            </main>
            """,
            "html.parser",
        )

        cards = get_cards(soup)
        self.assertEqual(len(cards), 1)
        self.assertEqual(
            cards[0].select_one(".woocommerce-loop-product__title").get_text(strip=True),
            "Actual category item",
        )

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

    def test_different_translated_names_match_only_at_same_position_type_and_price(self):
        russian = [{
            "dish_code": "break-time:site:11",
            "source_id": "site:11",
            "name": "Классический говяжий бургер",
            "price": 8.5,
            "price_variant": None,
            "category": "Бургеры",
            "product_type": "burgers",
            "language": "ru",
            "catalog_category_key": "burgerid",
            "catalog_position": 4,
        }]
        estonian = [{
            "dish_code": "break-time:site:111",
            "source_id": "site:111",
            "name": "Klassikaline veiselihaburger",
            "price": 8.5,
            "price_variant": None,
            "category": "Burgerid",
            "product_type": "burgers",
            "language": "et",
            "catalog_category_key": "burgerid",
            "catalog_position": 4,
        }]

        result = merge_language_records(russian, estonian)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["dish_name_ru"], "Классический говяжий бургер")
        self.assertEqual(result[0]["dish_name_et"], "Klassikaline veiselihaburger")

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
