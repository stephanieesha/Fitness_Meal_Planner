"""
Selects meals from a regional database to build a day or week of meals
approximating a calorie/macro target, with portions scaled to hit that
target and variety tracking so the same meal doesn't repeat every day.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

MEAL_SLOT_SPLIT = {
    "breakfast": 0.25,
    "lunch": 0.35,
    "dinner": 0.40,
}

MEAL_SLOT_SPLIT_WITH_SNACK = {
    "breakfast": 0.22,
    "lunch": 0.30,
    "dinner": 0.33,
    "snack": 0.15,
}


def load_meals(region: str) -> list:
    path = DATA_DIR / f"meals_{region}.json"
    if not path.exists():
        raise ValueError(f"No meal database for region '{region}'")
    return json.loads(path.read_text(encoding="utf-8"))


def pick_meal_for_slot(meals: list, meal_type: str, target_calories: float, exclude_names: set = None) -> dict:
    exclude_names = exclude_names or set()

    candidates = [m for m in meals if m["meal_type"] == meal_type]
    if not candidates:
        raise ValueError(f"No meals available for meal_type '{meal_type}' in this region")

    fresh_candidates = [m for m in candidates if m["name"] not in exclude_names]
    pool = fresh_candidates if fresh_candidates else candidates

    return min(pool, key=lambda m: abs(m["calories"] - target_calories))


def scale_meal_to_target(meal: dict, target_calories: float) -> dict:
    multiplier = target_calories / meal["calories"] if meal["calories"] else 1.0
    return {
        "name": meal["name"],
        "meal_type": meal["meal_type"],
        "serving_desc": meal["serving_desc"],
        "portion_multiplier": round(multiplier, 2),
        "calories": round(meal["calories"] * multiplier),
        "protein_g": round(meal["protein_g"] * multiplier),
        "carbs_g": round(meal["carbs_g"] * multiplier),
        "fat_g": round(meal["fat_g"] * multiplier),
    }


def build_day_plan(meals: list, calorie_target: float, meal_types: tuple = ("breakfast", "lunch", "dinner"),
                     used_names: dict = None) -> dict:
    if used_names is None:
        used_names = {mt: set() for mt in meal_types}

    split = MEAL_SLOT_SPLIT_WITH_SNACK if "snack" in meal_types else MEAL_SLOT_SPLIT

    day_meals = []
    for meal_type in meal_types:
        slot_target = calorie_target * split[meal_type]
        chosen = pick_meal_for_slot(meals, meal_type, slot_target, used_names.get(meal_type, set()))
        scaled = scale_meal_to_target(chosen, slot_target)
        day_meals.append(scaled)
        used_names.setdefault(meal_type, set()).add(chosen["name"])

    day_totals = {
        "calories": sum(m["calories"] for m in day_meals),
        "protein_g": sum(m["protein_g"] for m in day_meals),
        "carbs_g": sum(m["carbs_g"] for m in day_meals),
        "fat_g": sum(m["fat_g"] for m in day_meals),
    }

    return {"meals": day_meals, "totals": day_totals}


def build_week_plan(region: str, calorie_target: float, days: int = 7,
                      meal_types: tuple = ("breakfast", "lunch", "dinner")) -> list:
    meals = load_meals(region)
    used_names = {mt: set() for mt in meal_types}

    plan = []
    for day_num in range(1, days + 1):
        for meal_type in meal_types:
            available = [m for m in meals if m["meal_type"] == meal_type]
            if len(used_names[meal_type]) >= len(available):
                used_names[meal_type] = set()

        day_plan = build_day_plan(meals, calorie_target, meal_types, used_names)
        day_plan["day"] = day_num
        plan.append(day_plan)

    return plan
