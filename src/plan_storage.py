"""
Persists generated meal plans so they survive a page reload and can be
edited cell by cell, rather than existing only transiently in the
response of /api/generate-plan.

Each generation gets a shared "batch" id (a timestamp) so a week's worth
of meal rows can be fetched back together and reassembled into the same
day/meal structure the plan builder already produces.
"""

import os
from datetime import datetime, timezone


class PlanMealNotFound(Exception):
    pass


def save_plan(conn, user_id: int, week_plan: list) -> str:
    plan_batch = datetime.now(timezone.utc).isoformat()

    for day in week_plan:
        for meal in day["meals"]:
            conn.execute(
                """
                INSERT INTO plan_meals
                    (user_id, plan_batch, day_number, meal_type, food_id, food_name, calories, protein_g, carbs_g, fat_g, grams)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    user_id, plan_batch, day["day"], meal["meal_type"],
                    meal["name"], meal["calories"], meal["protein_g"], meal["carbs_g"], meal["fat_g"],
                ),
            )
    conn.commit()
    _prune_old_plans(conn, user_id)
    return plan_batch


def _prune_old_plans(conn, user_id: int) -> None:
    """With KEEP_PLAN_BATCHES set, delete everything but that person's newest plans so the
    database does not grow without limit on a public deployment."""
    try:
        keep = int(os.environ.get("KEEP_PLAN_BATCHES", "0"))
    except ValueError:
        keep = 0
    if keep <= 0:
        return
    conn.execute(
        """
        DELETE FROM plan_meals
        WHERE user_id = ? AND plan_batch NOT IN (
            SELECT plan_batch FROM (
                SELECT plan_batch, MAX(id) AS newest
                FROM plan_meals WHERE user_id = ?
                GROUP BY plan_batch
                ORDER BY newest DESC
                LIMIT ?
            ) AS newest_plans
        )
        """,
        (user_id, user_id, keep),
    )
    conn.commit()


def get_latest_plan(conn, user_id: int) -> list:
    latest_batch_row = conn.execute(
        "SELECT plan_batch FROM plan_meals WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if latest_batch_row is None:
        return []

    plan_batch = latest_batch_row["plan_batch"]
    rows = conn.execute(
        "SELECT * FROM plan_meals WHERE user_id = ? AND plan_batch = ? ORDER BY day_number ASC, id ASC",
        (user_id, plan_batch),
    ).fetchall()

    days = {}
    for row in rows:
        day_num = row["day_number"]
        if day_num not in days:
            days[day_num] = {"day": day_num, "meals": []}
        days[day_num]["meals"].append({
            "id": row["id"],
            "meal_type": row["meal_type"],
            "name": row["food_name"],
            "calories": row["calories"],
            "protein_g": row["protein_g"],
            "carbs_g": row["carbs_g"],
            "fat_g": row["fat_g"],
            "grams": row["grams"],
        })

    plan = list(days.values())
    for day in plan:
        day["totals"] = {
            "calories": sum(m["calories"] for m in day["meals"]),
            "protein_g": sum(m["protein_g"] for m in day["meals"]),
            "carbs_g": sum(m["carbs_g"] for m in day["meals"]),
            "fat_g": sum(m["fat_g"] for m in day["meals"]),
        }
    return plan


def update_plan_meal(conn, user_id: int, meal_id: int, updated_values: dict) -> dict:
    row = conn.execute(
        "SELECT * FROM plan_meals WHERE id = ? AND user_id = ?", (meal_id, user_id)
    ).fetchone()
    if row is None:
        raise PlanMealNotFound(f"No plan meal with id {meal_id} for this user")

    conn.execute(
        """
        UPDATE plan_meals
        SET food_name = ?, calories = ?, protein_g = ?, carbs_g = ?, fat_g = ?, food_id = ?, grams = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            updated_values["food_name"], updated_values["calories"],
            updated_values.get("protein_g", 0), updated_values.get("carbs_g", 0), updated_values.get("fat_g", 0),
            updated_values.get("food_id"), updated_values.get("grams"),
            meal_id, user_id,
        ),
    )
    conn.commit()

    updated_row = conn.execute("SELECT * FROM plan_meals WHERE id = ?", (meal_id,)).fetchone()

    day_rows = conn.execute(
        "SELECT * FROM plan_meals WHERE user_id = ? AND plan_batch = ? AND day_number = ?",
        (user_id, updated_row["plan_batch"], updated_row["day_number"]),
    ).fetchall()

    day_totals = {
        "calories": sum(r["calories"] for r in day_rows),
        "protein_g": sum(r["protein_g"] for r in day_rows),
        "carbs_g": sum(r["carbs_g"] for r in day_rows),
        "fat_g": sum(r["fat_g"] for r in day_rows),
    }

    return {
        "meal": {
            "id": updated_row["id"],
            "meal_type": updated_row["meal_type"],
            "name": updated_row["food_name"],
            "calories": updated_row["calories"],
            "protein_g": updated_row["protein_g"],
            "carbs_g": updated_row["carbs_g"],
            "fat_g": updated_row["fat_g"],
            "grams": updated_row["grams"],
        },
        "day_totals": day_totals,
    }
