"""Compatibility re-exports for the shared restaurant category taxonomy.

The actual category registry and normalization rules live in the installable
`restaurant-taxonomy` package under `shared_taxonomy/`. Keep this module so
existing parsers and tests can continue importing `parsers.categories`.
"""
from pathlib import Path
import sys


# Allow standalone execution of parsers (for example: python parsers/monk.py)
# as well as normal imports from the repository root.
_SHARED_PACKAGE_ROOT = str(
    Path(__file__).resolve().parents[1] / "shared_taxonomy"
)
if _SHARED_PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_PACKAGE_ROOT)

from restaurant_taxonomy import (  # noqa: E402
    CATEGORIES,
    PRODUCT_TYPE_ALIASES,
    CATEGORY_RU_BY_PRODUCT_TYPE,
    CATEGORY_ET_BY_PRODUCT_TYPE,
    CATEGORY_ET_BY_RUSSIAN_CATEGORY,
    category_label,
    category_key_for_product_type,
    category_label_for_product_type,
    resolve_category_key,
    canonical_category_ru,
    canonical_category_et,
    get_category_emoji,
)


__all__ = [
    "CATEGORIES",
    "PRODUCT_TYPE_ALIASES",
    "CATEGORY_RU_BY_PRODUCT_TYPE",
    "CATEGORY_ET_BY_PRODUCT_TYPE",
    "CATEGORY_ET_BY_RUSSIAN_CATEGORY",
    "category_label",
    "category_key_for_product_type",
    "category_label_for_product_type",
    "resolve_category_key",
    "canonical_category_ru",
    "canonical_category_et",
    "get_category_emoji",
]
