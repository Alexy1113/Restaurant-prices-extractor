-- Normalize category labels across restaurants.
-- Safe maintenance script: does not delete rows or change prices.
-- Run in Supabase SQL Editor and review the RETURNING rows.

BEGIN;

WITH typed AS (
    SELECT
        id,
        restaurant_name,
        dish_name,
        dish_name_ru,
        dish_name_et,
        category_ru,
        category_et,
        product_type,
        CASE
            -- Breakfast products currently misclassified as burgers.
            WHEN product_type = 'burgers'
             AND (
                 coalesce(category_et, '') ILIKE '%hommikupala%'
                 OR coalesce(dish_name_et, '') ILIKE 'Hommikupala%'
                 OR coalesce(dish_name, '') ILIKE 'Hommikupala%'
             )
                THEN 'breakfast'

            -- "Maki" is a sushi category, not a drink category. The parser's
            -- broad "tea"/"gin" substring checks previously caused false matches.
            WHEN restaurant_name = 'Ocean Sushi Jõhvi'
             AND category_ru = 'Маки'
             AND product_type = 'drinks'
                THEN 'sushi_rolls'

            ELSE coalesce(product_type, 'other')
        END AS normalized_product_type
    FROM public.dishes
),
mapped AS (
    SELECT
        *,
        CASE
            -- Keep the age warning while combining wine/champagne/low-alcohol labels.
            WHEN normalized_product_type = 'drinks'
             AND (
                 coalesce(category_ru, '') ILIKE '%18+%'
                 OR coalesce(category_ru, '') ~* '(вино|шампан|игрист|слабоалког|алкогол)'
                 OR coalesce(category_et, '') ~* '(vein|vahuvein|siider|õlu|alkohol)'
             )
                THEN 'Алкогольные напитки (18+)'

            WHEN normalized_product_type = 'main_courses' THEN 'Основные блюда'
            WHEN normalized_product_type = 'bowls' THEN 'Боулы'
            WHEN normalized_product_type = 'burgers' THEN 'Бургеры'
            WHEN normalized_product_type = 'tortillas' THEN 'Тортильи'
            WHEN normalized_product_type = 'breakfast' THEN 'Завтраки'
            WHEN normalized_product_type = 'salads' THEN 'Салаты'
            WHEN normalized_product_type = 'appetizers' THEN 'Закуски'
            WHEN normalized_product_type = 'sides' THEN 'Гарниры'
            WHEN normalized_product_type = 'sauces' THEN 'Соусы'
            WHEN normalized_product_type = 'drinks' THEN 'Напитки'
            WHEN normalized_product_type = 'desserts' THEN 'Десерты'

            WHEN normalized_product_type IN ('sushi_rolls', 'hosomaki')
                THEN 'Роллы'
            WHEN normalized_product_type = 'nigiri' THEN 'Нигири'
            WHEN normalized_product_type = 'sashimi' THEN 'Сашими'
            WHEN normalized_product_type = 'gunkan' THEN 'Гунканы'
            WHEN normalized_product_type = 'sets' THEN 'Сеты'
            WHEN normalized_product_type = 'inari' THEN 'Инари'

            -- "Tempura" under a broad Sushi section means tempura rolls.
            -- Standalone tempura remains a separate category.
            WHEN normalized_product_type = 'tempura'
             AND (
                 coalesce(category_ru, '') ~* '(суши|маки|хосомаки|ролл)'
                 OR coalesce(category_et, '') ~* '(sushi|maki|hosomaki|roll|rull)'
                 OR coalesce(dish_name_ru, '') ~* '(маки|хосомаки|ролл)'
                 OR coalesce(dish_name_et, '') ~* '(maki|hosomaki|roll|rull|sushi)'
             )
                THEN 'Роллы'
            WHEN normalized_product_type = 'tempura' THEN 'Темпура'

            WHEN normalized_product_type = 'soups' THEN 'Супы'
            WHEN normalized_product_type = 'noodles' THEN 'Лапша'
            WHEN normalized_product_type = 'dumplings' THEN 'Пельмени и дим-сам'
            WHEN normalized_product_type = 'syrups' THEN 'Сиропы'
            WHEN normalized_product_type = 'ice_cream_shakes' THEN 'Напитки'
            WHEN normalized_product_type = 'campaigns' THEN 'Акции'

            -- Keep informative source labels for type=other (for example,
            -- "Запечённые") until those individual dishes can be classified safely.
            WHEN normalized_product_type = 'other'
             AND nullif(trim(category_ru), '') IS NOT NULL
             AND category_ru NOT IN ('Другое', 'Other', 'Без категории')
                THEN category_ru
            WHEN normalized_product_type = 'other' THEN 'Другое'
            ELSE coalesce(category_ru, 'Другое')
        END AS normalized_category_ru
    FROM typed
),
updated AS (
    UPDATE public.dishes AS d
    SET
        product_type = m.normalized_product_type,
        category_ru = m.normalized_category_ru
    FROM mapped AS m
    WHERE d.id = m.id
      AND (
          d.product_type IS DISTINCT FROM m.normalized_product_type
          OR d.category_ru IS DISTINCT FROM m.normalized_category_ru
      )
    RETURNING
        d.id,
        d.restaurant_name,
        d.dish_name,
        d.product_type,
        d.category_ru,
        d.dish_code
)
SELECT * FROM updated
ORDER BY restaurant_name, category_ru, dish_name;

COMMIT;

-- Post-update summary
SELECT
    category_ru,
    product_type,
    COUNT(*) AS dishes_count,
    COUNT(DISTINCT restaurant_name) AS restaurants_count
FROM public.dishes
GROUP BY category_ru, product_type
ORDER BY category_ru, product_type;

-- Review these rows manually: their source category is meaningful, but the
-- current product_type is too broad to safely infer a more specific category.
SELECT
    id,
    restaurant_name,
    dish_name,
    dish_name_ru,
    dish_name_et,
    product_type,
    category_ru,
    category_et,
    dish_code
FROM public.dishes
WHERE category_ru = 'Запечённые'
   OR (product_type = 'other' AND category_ru NOT IN ('Другое', 'Other', 'Без категории'))
ORDER BY restaurant_name, category_ru, dish_name;
