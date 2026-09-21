"""
Personal food library: foods a user has added, each with macros per 100g,
categorized by meal type. This is the data Phase 4's plan builder will
let users select from, with a calories-per-100g tooltip on each entry.
"""


MEAL_CATEGORIES = ("breakfast", "lunch", "dinner", "snack", "other")


class FoodNotFound(Exception):
    pass


class InvalidCategory(Exception):
    pass


def add_food(conn, user_id: int, food_data: dict) -> dict:
    category = food_data.get("meal_category", "other")
    if category not in MEAL_CATEGORIES:
        raise InvalidCategory(f"meal_category must be one of {MEAL_CATEGORIES}")

    cursor = conn.execute(
        """
        INSERT INTO foods (
            user_id, name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g,
            calcium_mg_per_100g, vitamin_c_mg_per_100g, omega3_g_per_100g, meal_category
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            food_data["name"],
            float(food_data["calories_per_100g"]),
            float(food_data["protein_per_100g"]),
            float(food_data["carbs_per_100g"]),
            float(food_data["fat_per_100g"]),
            float(food_data.get("calcium_mg_per_100g") or 0),
            float(food_data.get("vitamin_c_mg_per_100g") or 0),
            float(food_data.get("omega3_g_per_100g") or 0),
            category,
        ),
    )
    conn.commit()
    return get_food(conn, user_id, cursor.lastrowid)


def get_foods(conn, user_id: int) -> list:
    rows = conn.execute(
        "SELECT * FROM foods WHERE user_id = ? ORDER BY name ASC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_food(conn, user_id: int, food_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM foods WHERE id = ? AND user_id = ?",
        (food_id, user_id),
    ).fetchone()
    if row is None:
        raise FoodNotFound(f"No food with id {food_id} for this user")
    return dict(row)


def delete_food(conn, user_id: int, food_id: int) -> None:
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
