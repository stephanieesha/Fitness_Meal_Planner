"""
Daily calorie total: the foods actually eaten on a given date, each with
its own quantity and calories, so the timetable page can show the day's
running total against a target range.

Each entry keeps its own copy of the name and calories, so later edits
to (or removal of) the food in the library never rewrite past days.
"""

from datetime import date

from food_library import MEAL_CATEGORIES, get_food, nutrition_for

MAX_ENTRIES_PER_DAY = 100


class DayEntryNotFound(Exception):
    pass


class InvalidDayEntry(Exception):
    pass


def parse_log_date(value) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise InvalidDayEntry("date must be a real date in YYYY-MM-DD format")


def _positive_number(value, field):
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise InvalidDayEntry(f"{field} must be a number")
    if number < 0:
        raise InvalidDayEntry(f"{field} must be at least 0")
    return number


def add_day_entry(conn, user_id: int, data: dict) -> dict:
    log_date = parse_log_date(data.get("date"))
    meal_type = data.get("meal_type") or "other"
    if meal_type not in MEAL_CATEGORIES:
        raise InvalidDayEntry(f"meal_type must be one of {MEAL_CATEGORIES}")

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM day_log WHERE user_id = ? AND log_date = ?", (user_id, log_date)
    ).fetchone()["n"]
    if count >= MAX_ENTRIES_PER_DAY:
        raise InvalidDayEntry(f"A day can hold up to {MAX_ENTRIES_PER_DAY} entries")

    if data.get("food_id") not in (None, ""):
        try:
            food_id = int(data["food_id"])
        except (ValueError, TypeError):
            raise InvalidDayEntry("food_id must be a number")
        food = get_food(conn, user_id, food_id)  # raises FoodNotFound for someone else's food
        quantity = data.get("quantity")
        quantity = food["serving_size"] if quantity in (None, "") else _positive_number(quantity, "Quantity")
        values = (food["id"], food["name"], quantity, food["serving_unit"], nutrition_for(food, quantity)["calories"])
    else:
        name = (data.get("food_name") or "").strip()[:200]
        if not name:
            raise InvalidDayEntry("Enter a food name")
        calories = _positive_number(data.get("calories"), "Calories")
        quantity = None if data.get("quantity") in (None, "") else _positive_number(data["quantity"], "Quantity")
        unit = (data.get("unit") or "").strip()[:20] or ("g" if quantity is not None else None)
        values = (None, name, quantity, unit, calories)

    cursor = conn.execute(
        """
        INSERT INTO day_log (user_id, log_date, meal_type, food_id, food_name, quantity, unit, calories)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, log_date, meal_type, *values),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM day_log WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _entry(row)


def _entry(row) -> dict:
    return {
        "id": row["id"],
        "date": row["log_date"],
        "meal_type": row["meal_type"],
        "food_id": row["food_id"],
        "name": row["food_name"],
        "quantity": row["quantity"],
        "unit": row["unit"],
        "calories": row["calories"],
    }


def get_day(conn, user_id: int, log_date) -> dict:
    log_date = parse_log_date(log_date)
    rows = conn.execute(
        "SELECT * FROM day_log WHERE user_id = ? AND log_date = ? ORDER BY id ASC",
        (user_id, log_date),
    ).fetchall()
    entries = [_entry(r) for r in rows]
    return {
        "date": log_date,
        "entries": entries,
        "total_calories": round(sum(e["calories"] for e in entries), 1),
    }


def delete_day_entry(conn, user_id: int, entry_id: int) -> None:
    cursor = conn.execute("DELETE FROM day_log WHERE id = ? AND user_id = ?", (entry_id, user_id))
    conn.commit()
    if cursor.rowcount == 0:
        raise DayEntryNotFound(f"No entry with id {entry_id} for this user")


def get_recent_days(conn, user_id: int, limit: int = 60) -> list:
    """Every day with at least one entry, newest first, with its total and item count."""
    rows = conn.execute(
        """
        SELECT log_date, SUM(calories) AS total, COUNT(*) AS items
        FROM day_log WHERE user_id = ?
        GROUP BY log_date ORDER BY log_date DESC LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [{"date": r["log_date"], "total_calories": round(r["total"], 1), "items": r["items"]} for r in rows]
