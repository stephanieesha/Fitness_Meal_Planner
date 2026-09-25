"""
Personal food library: foods a user has added, categorized by meal type.

Each food has a serving: an amount and a unit that you choose, such as
100 g, 10 g, 1 slice, 1 egg or 1 tbsp, and the calories in that serving.
A serving can optionally be cut from a whole item (a loaf of bread, a
litre of yoghurt): give the whole item's calories and how many servings
it makes, and the calories per serving are worked out from that.

Storage note: the *_per_100g columns mean "per 100 of the serving unit".
For gram foods that is exactly per 100 g, as before. For a unit like
"slice" it is per 100 slices, which is not something you'd ever display,
but it keeps every existing scaling calculation (value * quantity / 100)
correct without special cases.
"""


MEAL_CATEGORIES = ("breakfast", "lunch", "dinner", "snack", "other")
MAX_NOTES_LENGTH = 1000
MAX_UNIT_LENGTH = 20


class FoodNotFound(Exception):
    pass


class InvalidCategory(Exception):
    pass


class InvalidFoodData(Exception):
    pass


def _number(value, field, required=False, positive=False):
    if value in (None, ""):
        if required:
            raise InvalidFoodData(f"{field} is required")
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise InvalidFoodData(f"{field} must be a number")
    if number < 0 or (positive and number == 0):
        raise InvalidFoodData(f"{field} must be {'more than' if positive else 'at least'} 0")
    return number


def _clean_text(value, max_length):
    text = (value or "").strip()
    return text[:max_length] if text else None


def normalize_food(food_data: dict) -> dict:
    """Turn what the user (or the USDA lookup) supplied into stored columns.

    Accepts either per-serving values (serving_size, serving_unit,
    serving_calories, protein/carbs/fat per serving) or the older
    per-100g values. A whole item (whole_calories + servings_per_whole)
    takes priority for the calories per serving.
    """
    name = (food_data.get("name") or "").strip()
    if not name:
        raise InvalidFoodData("Food name is required")

    category = food_data.get("meal_category", "other")
    if category not in MEAL_CATEGORIES:
        raise InvalidCategory(f"meal_category must be one of {MEAL_CATEGORIES}")

    serving_size = _number(food_data.get("serving_size"), "Serving amount", positive=True) or 100.0
    serving_unit = _clean_text(food_data.get("serving_unit"), MAX_UNIT_LENGTH) or "g"

    whole_calories = _number(food_data.get("whole_calories"), "Whole item calories")
    servings_per_whole = _number(food_data.get("servings_per_whole"), "Number of servings", positive=True)
    whole_label = _clean_text(food_data.get("whole_label"), 40)
    if whole_calories is not None and servings_per_whole is None:
        raise InvalidFoodData("Enter how many servings the whole item makes")
    if servings_per_whole is not None and whole_calories is None:
        raise InvalidFoodData("Enter the whole item's calories")

    scale_to_100 = 100 / serving_size

    if whole_calories is not None:
        serving_calories = whole_calories / servings_per_whole
    else:
        serving_calories = _number(food_data.get("serving_calories"), "Calories")

    if serving_calories is not None:
        calories_per_100 = serving_calories * scale_to_100
    else:
        calories_per_100 = _number(food_data.get("calories_per_100g"), "Calories", required=True)

    def per_100(nutrient):
        per_serving = _number(food_data.get(f"{nutrient}_per_serving"), nutrient.capitalize())
        if per_serving is not None:
            return per_serving * scale_to_100
        return _number(food_data.get(f"{nutrient}_per_100g"), nutrient.capitalize()) or 0.0

    return {
        "name": name,
        "meal_category": category,
        "calories_per_100g": round(calories_per_100, 4),
        "protein_per_100g": round(per_100("protein"), 4),
        "carbs_per_100g": round(per_100("carbs"), 4),
        "fat_per_100g": round(per_100("fat"), 4),
        "calcium_mg_per_100g": _number(food_data.get("calcium_mg_per_100g"), "Calcium") or 0.0,
        "vitamin_c_mg_per_100g": _number(food_data.get("vitamin_c_mg_per_100g"), "Vitamin C") or 0.0,
        "omega3_g_per_100g": _number(food_data.get("omega3_g_per_100g"), "Omega-3") or 0.0,
        "serving_size": serving_size,
        "serving_unit": serving_unit,
        "whole_label": whole_label if whole_calories is not None else None,
        "whole_calories": whole_calories,
        "servings_per_whole": servings_per_whole,
        "notes": _clean_text(food_data.get("notes"), MAX_NOTES_LENGTH),
    }


def _with_serving_values(food: dict) -> dict:
    """Add the per-serving figures the pages display, so they never have to redo this math."""
    size = food.get("serving_size") or 100
    food["serving_size"] = size
    food["serving_unit"] = food.get("serving_unit") or "g"
    food["serving_calories"] = round(food["calories_per_100g"] * size / 100, 1)
    food["protein_per_serving"] = round(food["protein_per_100g"] * size / 100, 1)
    food["carbs_per_serving"] = round(food["carbs_per_100g"] * size / 100, 1)
    food["fat_per_serving"] = round(food["fat_per_100g"] * size / 100, 1)
    return food


def nutrition_for(food: dict, quantity: float) -> dict:
    """Calories and macros for a quantity measured in the food's own serving unit."""
    factor = quantity / 100
    return {
        "calories": round(food["calories_per_100g"] * factor, 1),
        "protein_g": round(food["protein_per_100g"] * factor, 1),
        "carbs_g": round(food["carbs_per_100g"] * factor, 1),
        "fat_g": round(food["fat_per_100g"] * factor, 1),
    }


_COLUMNS = (
    "name", "calories_per_100g", "protein_per_100g", "carbs_per_100g", "fat_per_100g",
    "calcium_mg_per_100g", "vitamin_c_mg_per_100g", "omega3_g_per_100g", "meal_category",
    "serving_size", "serving_unit", "whole_label", "whole_calories", "servings_per_whole", "notes",
)


def add_food(conn, user_id: int, food_data: dict) -> dict:
    values = normalize_food(food_data)
    cursor = conn.execute(
        f"INSERT INTO foods (user_id, {', '.join(_COLUMNS)}) VALUES (?, {', '.join('?' for _ in _COLUMNS)})",
        (user_id, *(values[c] for c in _COLUMNS)),
    )
    conn.commit()
    return get_food(conn, user_id, cursor.lastrowid)


def update_food(conn, user_id: int, food_id: int, food_data: dict) -> dict:
    """Replace a food's details. Micronutrients the edit form doesn't show are kept as they were."""
    existing = get_food(conn, user_id, food_id)
    merged = {
        "calcium_mg_per_100g": existing["calcium_mg_per_100g"],
        "vitamin_c_mg_per_100g": existing["vitamin_c_mg_per_100g"],
        "omega3_g_per_100g": existing["omega3_g_per_100g"],
        **food_data,
    }
    values = normalize_food(merged)
    conn.execute(
        f"UPDATE foods SET {', '.join(f'{c} = ?' for c in _COLUMNS)} WHERE id = ? AND user_id = ?",
        (*(values[c] for c in _COLUMNS), food_id, user_id),
    )
    conn.commit()
    return get_food(conn, user_id, food_id)


def get_foods(conn, user_id: int) -> list:
    rows = conn.execute(
        "SELECT * FROM foods WHERE user_id = ? ORDER BY name ASC",
        (user_id,),
    ).fetchall()
    return [_with_serving_values(dict(row)) for row in rows]


def get_food(conn, user_id: int, food_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM foods WHERE id = ? AND user_id = ?",
        (food_id, user_id),
    ).fetchone()
    if row is None:
        raise FoodNotFound(f"No food with id {food_id} for this user")
    return _with_serving_values(dict(row))


def delete_food(conn, user_id: int, food_id: int) -> None:
    get_food(conn, user_id, food_id)
    # Plan cells and daily entries keep their own copy of the name and calories,
    # so unlink them rather than letting the database refuse the delete.
    conn.execute("UPDATE plan_meals SET food_id = NULL WHERE food_id = ? AND user_id = ?", (food_id, user_id))
    conn.execute("UPDATE day_log SET food_id = NULL WHERE food_id = ? AND user_id = ?", (food_id, user_id))
    cursor = conn.execute(
        "DELETE FROM foods WHERE id = ? AND user_id = ?",
        (food_id, user_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise FoodNotFound(f"No food with id {food_id} for this user")


def update_food_category(conn, user_id: int, food_id: int, category: str) -> dict:
    if category not in MEAL_CATEGORIES:
        raise InvalidCategory(f"meal_category must be one of {MEAL_CATEGORIES}")

    cursor = conn.execute(
        "UPDATE foods SET meal_category = ? WHERE id = ? AND user_id = ?",
        (category, food_id, user_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise FoodNotFound(f"No food with id {food_id} for this user")

    return get_food(conn, user_id, food_id)
