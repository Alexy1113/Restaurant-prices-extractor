from parsers.hesburger import (
    get_catalog_products,
    get_catalog_lookup,
    find_catalog_product,
)

catalog = get_catalog_products()
lookup = get_catalog_lookup(catalog)

names = [
    "Kananagitsad 4 tk +1 kaste",
    "Kananagitsad 6 tk +1 kaste",
    "VEKE' Sojapulgad 6 tk +1 kaste",
    'VEKE" Sojapulgad 15 tk + 3 kastet',
    "VEKE” Sojapulgad 4 tk +1 kaste",
]

for name in names:
    product = find_catalog_product(name, lookup)
    print(
        f"{name} -> "
        f"{product['dish_code'] if product else 'NOT FOUND'}"
    )deactivate