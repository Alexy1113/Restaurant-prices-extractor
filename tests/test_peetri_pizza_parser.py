"""Regression tests for the Peetri Pizza Jõhvi menu parser."""
import unittest

from parsers.peetri_pizza import parse_html, get_product_type, parse_react_state


MENU_FIXTURE = """
<html>
  <body>
    <section id="pizzas">
      <h2>Pizzad</h2>
      <div class="products">
        <article class="product-card" data-product-id="101">
          <span class="badge">Uus</span>
          <h3>Pepperoni</h3>
          <p class="description">Pepperoni, juust, kaste</p>
          <span class="price">al. 6.50 €</span>
        </article>
        <article class="product-card" data-product-id="102">
          <span class="badge">Lihata</span>
          <h3>Margherita</h3>
          <p class="description">Juust, kaste</p>
          <span class="price">al. 5,50 €</span>
        </article>
      </div>
    </section>
    <section id="pasta">
      <h2>Pastad</h2>
      <article class="product-card" data-product-id="201">
        <h3>Bolognese</h3>
        <span class="price">7.90 €</span>
      </article>
    </section>
    <section id="drinks">
      <h2>Joogid</h2>
      <article class="product-card" data-product-id="301">
        <h3>Pepsi</h3>
        <span class="price">2.50 €</span>
      </article>
    </section>
  </body>
</html>
"""


class PeetriPizzaParserTests(unittest.TestCase):
    def test_only_pizzas_are_parsed_from_the_pizza_section(self):
        dishes = parse_html(MENU_FIXTURE)
        self.assertEqual(
            [dish["dish_name_et"] for dish in dishes],
            ["Pepperoni", "Margherita"],
        )
        self.assertEqual([dish["price"] for dish in dishes], [6.50, 5.50])

    def test_pizza_records_have_canonical_category_and_stable_codes(self):
        first_run = parse_html(MENU_FIXTURE)
        second_run = parse_html(MENU_FIXTURE)
        self.assertTrue(all(dish["product_type"] == "pizzas" for dish in first_run))
        self.assertTrue(all(dish["category_ru"] == "Пицца" for dish in first_run))
        self.assertTrue(all(dish["category_et"] == "Pitsad" for dish in first_run))
        self.assertEqual(
            [dish["dish_code"] for dish in first_run],
            [dish["dish_code"] for dish in second_run],
        )

    def test_explicit_size_prices_are_returned_as_separate_variants(self):
        html = """
        <section>
          <h2>Pizzad</h2>
          <article class="product-card" data-product-id="303">
            <h3>Oma Pizza</h3>
            <span data-variant="Väike" data-price="6.50">Väike</span>
            <span data-variant="Suur" data-price="9.50">Suur</span>
          </article>
        </section>
        """
        dishes = parse_html(html)
        self.assertEqual(
            [(dish["price"], dish["price_variant"]) for dish in dishes],
            [(6.50, "Väike"), (9.50, "Suur")],
        )
        self.assertNotEqual(dishes[0]["dish_code"], dishes[1]["dish_code"])

    def test_parses_realistic_react_state_and_ignores_other_product_sections(self):
        html = '''
        <html>
          <head><title>Peetri Pizza</title></head>
          <body>
            <div id="page"></div>
            <script>
              window.initialReactState = {
                "lang": "et",
                "pizzeria": {"name": "Jõhvi bussijaam"},
                "productsData": {
                  "pizzas": [
                    {
                      "name": "Margherita",
                      "templateId": 19,
                      "minPrice": 5.5,
                      "originalToppings": [
                        {"name": "Juust", "isOriginal": true, "isRemoved": false},
                        {"name": "Kaste", "isOriginal": true, "isRemoved": false}
                      ]
                    },
                    {"name": "Pepperoni", "templateId": 81, "minPrice": 6.5}
                  ],
                  "pastas": [
                    {"name": "Bolognese", "templateId": 201, "minPrice": 7.9}
                  ],
                  "drinks": [
                    {"name": "Pepsi", "templateId": 301, "minPrice": 2.5}
                  ]
                }
              };
            </script>
          </body>
        </html>
        '''
        dishes = parse_html(html)
        self.assertEqual(
            [dish["dish_name_et"] for dish in dishes],
            ["Margherita", "Pepperoni"],
        )
        self.assertEqual([dish["price"] for dish in dishes], [5.5, 6.5])
        self.assertEqual(dishes[0]["description_et"], "Juust, Kaste")
        self.assertEqual(
            [dish["dish_code"] for dish in dishes],
            ["peetri-johvi:pizza:19:small", "peetri-johvi:pizza:81:small"],
        )


    def test_parses_all_three_pizza_sizes_with_distinct_codes(self):
        import json

        class FakeResponse:
            def __init__(self, state):
                self.text = (
                    "<script>window.initialReactState = "
                    + json.dumps(state)
                    + ";</script>"
                )

            def raise_for_status(self):
                return None

        class FakeSession:
            def get(self, url, timeout=None):
                return FakeResponse({
                    "availableSizes": {
                        "small": 5.5,
                        "large": 7.9,
                        "family": 16.9,
                    }
                })

        state = {
            "productsData": {
                "pizzas": [{
                    "name": "Margherita",
                    "templateId": 19,
                    "minPrice": 5.5,
                    "urlAddNew": "https://example.test/add/19",
                }],
                "simpleProducts": [],
                "combos": [],
            }
        }
        rows = parse_react_state(state, session=FakeSession())
        self.assertEqual(
            [(row["price_variant"], row["price"]) for row in rows],
            [("small", 5.5), ("large", 7.9), ("family", 16.9)],
        )
        self.assertEqual(
            [row["dish_code"] for row in rows],
            [
                "peetri-johvi:pizza:19:small",
                "peetri-johvi:pizza:19:large",
                "peetri-johvi:pizza:19:family",
            ],
        )

    def test_parses_four_pasta_products_and_red_bull_combo(self):
        state = {
            "productsData": {
                "pizzas": [],
                "simpleProducts": [
                    {
                        "name": "Bolognese",
                        "productId": 120,
                        "unitPrice": 7.9,
                        "categoryName": "Pastad",
                        "description": "Pasta, hakkliha",
                    },
                    {
                        "name": "Carbonara",
                        "productId": 121,
                        "unitPrice": 8.2,
                        "categoryName": "Pastad",
                    },
                    {
                        "name": "Chicken Pasta",
                        "productId": 122,
                        "unitPrice": 8.5,
                        "categoryName": "Pastad",
                    },
                    {
                        "name": "Vegetarian Pasta",
                        "productId": 123,
                        "unitPrice": 7.5,
                        "categoryName": "Pastad",
                    },
                    {
                        "name": "Pepsi",
                        "productId": 301,
                        "unitPrice": 2.5,
                        "categoryName": "Joogid",
                    },
                ],
                "combos": [{
                    "id": 49,
                    "name": "Red Bull Combo",
                    "pizzas": [
                        {"name": "Pepperoni", "size": "large"},
                        {"name": "Pepperoni", "size": "large"},
                    ],
                    "products": [
                        {"name": "Red Bull", "details": "0,25 l"},
                        {"name": "Red Bull", "details": "0,25 l"},
                    ],
                    "price": {"discounted": 20, "original": 26.8},
                }],
            }
        }
        rows = parse_react_state(state)
        pasta_rows = [row for row in rows if row["product_type"] == "pasta"]
        combo_rows = [row for row in rows if row["product_type"] == "sets"]
        self.assertEqual(len(pasta_rows), 4)
        self.assertEqual(len(combo_rows), 1)
        self.assertTrue(all(row["category_ru"] == "Паста" for row in pasta_rows))
        self.assertTrue(all(row["category_et"] == "Pastad" for row in pasta_rows))
        self.assertEqual(combo_rows[0]["price"], 20.0)
        self.assertEqual(combo_rows[0]["description_et"], "2 × Pepperoni (large) + 2 × Red Bull (0,25 l)")
        self.assertEqual(combo_rows[0]["dish_code"], "peetri-johvi:combo:49")

    def test_missing_pizza_section_returns_no_records(self):
        self.assertEqual(
            parse_html("<section><h2>Pastad</h2><p>None</p></section>"),
            [],
        )

    def test_product_type_recognizes_estonian_and_russian_pizza_labels(self):
        for category in ("Pizzad", "Pitsad", "Pizza", "Пицца"):
            with self.subTest(category=category):
                self.assertEqual(get_product_type(category), "pizzas")


if __name__ == "__main__":
    unittest.main()
