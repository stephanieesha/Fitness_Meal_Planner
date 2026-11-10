"""
Selects meals to build a day or week of meals approximating a calorie/macro
target, with portions scaled to hit that target and variety tracking so the
same meal doesn't repeat every day.

Meals come either from a regional database (build_week_plan) or from the
user's own food library (build_week_plan_from_foods).
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

DEFAULT_MEAL_TYPES = ("breakfast", "lunch", "dinner")


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


def build_day_plan(meals: list, calorie_target: float, meal_types: tuple = DEFAULT_MEAL_TYPES,
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


def _build_week(meals: list, calorie_target: float, days: int, meal_types: tuple) -> list:
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


def build_week_plan(region: str, calorie_target: float, days: int = 7,
                      meal_types: tuple = DEFAULT_MEAL_TYPES) -> list:
    return _build_week(load_meals(region), calorie_target, days, meal_types)


def foods_as_meals(foods: list) -> list:
    """Turn the user's food library rows into the same shape as regional meals."""
    meals = []
    for food in foods:
        if not food.get("serving_calories"):
            continue
        meals.append({
            "name": food["name"],
            "meal_type": food["meal_category"],
            "serving_desc": f"{food['serving_size']:g} {food['serving_unit']}",
            "calories": food["serving_calories"],
            "protein_g": food.get("protein_per_serving") or 0,
            "carbs_g": food.get("carbs_per_serving") or 0,
            "fat_g": food.get("fat_per_serving") or 0,
        })
    return meals


def build_week_plan_from_foods(foods: list, calorie_target: float, days: int = 7,
                                 meal_types: tuple = DEFAULT_MEAL_TYPES) -> list:
    meals = foods_as_meals(foods)
    for meal_type in meal_types:
        if not any(m["meal_type"] == meal_type for m in meals):
            raise ValueError(f"Add at least one {meal_type} food to My Foods before generating a plan")
    return _build_week(meals, calorie_target, days, meal_types)


def library_covers(foods: list, meal_types: tuple) -> bool:
    """True when the user's library has at least one usable food for every meal type."""
    categories = {f["meal_category"] for f in foods if f.get("serving_calories")}
    return all(meal_type in categories for meal_type in meal_types)