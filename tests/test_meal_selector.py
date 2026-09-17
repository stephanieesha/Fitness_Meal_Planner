import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from meal_selector import (
    load_meals, pick_meal_for_slot, scale_meal_to_target,
    build_day_plan, build_week_plan,
)

FIXTURE_MEALS = [
    {"name": "Meal A", "region": "test", "meal_type": "breakfast", "calories": 300, "protein_g": 10, "carbs_g": 40, "fat_g": 8, "serving_desc": "1 bowl"},
    {"name": "Meal B", "region": "test", "meal_type": "breakfast", "calories": 500, "protein_g": 20, "carbs_g": 60, "fat_g": 15, "serving_desc": "1 plate"},
    {"name": "Meal C", "region": "test", "meal_type": "lunch", "calories": 600, "protein_g": 30, "carbs_g": 70, "fat_g": 20, "serving_desc": "1 plate"},
]


def test_picks_closest_calorie_match():
    chosen = pick_meal_for_slot(FIXTURE_MEALS, "breakfast", target_calories=280)
    assert chosen["name"] == "Meal A"


def test_excludes_used_names_when_alternative_exists():
    chosen = pick_meal_for_slot(FIXTURE_MEALS, "breakfast", target_calories=280, exclude_names={"Meal A"})
    assert chosen["name"] == "Meal B"


def test_falls_back_to_full_pool_if_exclusion_empties_it():
    chosen = pick_meal_for_slot(FIXTURE_MEALS, "breakfast", target_calories=280, exclude_names={"Meal A", "Meal B"})
    assert chosen["name"] in ("Meal A", "Meal B")


def test_raises_for_meal_type_with_no_candidates():
    try:
        pick_meal_for_slot(FIXTURE_MEALS, "dinner", target_calories=400)
        assert False, "should have raised"
    except ValueError:
        pass


def test_scale_meal_doubles_all_macros_at_double_calories():
    meal = {"name": "X", "meal_type": "lunch", "calories": 300, "protein_g": 10, "carbs_g": 30, "fat_g": 8, "serving_desc": "1 plate"}
    scaled = scale_meal_to_target(meal, target_calories=600)
    assert scaled["portion_multiplier"] == 2.0
    assert scaled["protein_g"] == 20
    assert scaled["calories"] == 600


def test_scale_meal_at_same_calories_is_multiplier_one():
    meal = {"name": "X", "meal_type": "lunch", "calories": 300, "protein_g": 10, "carbs_g": 30, "fat_g": 8, "serving_desc": "1 plate"}
    scaled = scale_meal_to_target(meal, target_calories=300)
    assert scaled["portion_multiplier"] == 1.0


def test_day_plan_includes_all_requested_meal_types():
    day = build_day_plan(FIXTURE_MEALS, 2000, meal_types=("breakfast", "lunch"))
    meal_types_present = {m["meal_type"] for m in day["meals"]}
    assert meal_types_present == {"breakfast", "lunch"}


def test_day_plan_totals_sum_correctly():
    day = build_day_plan(FIXTURE_MEALS, 2000, meal_types=("breakfast", "lunch"))
    expected_calories = sum(m["calories"] for m in day["meals"])
    assert day["totals"]["calories"] == expected_calories


def test_load_nigeria_meals_returns_nonempty_list():
    meals = load_meals("nigeria")
    assert len(meals) > 0
    assert all(m["region"] == "nigeria" for m in meals)


def test_load_us_meals_returns_nonempty_list():
    meals = load_meals("us")
    assert len(meals) > 0


def test_load_unknown_region_raises():
    try:
        load_meals("atlantis")
        assert False, "should have raised"
    except ValueError:
        pass


def test_build_week_plan_nigeria_produces_seven_days():
    plan = build_week_plan("nigeria", 2000, days=7)
    assert len(plan) == 7
    assert [d["day"] for d in plan] == [1, 2, 3, 4, 5, 6, 7]


def test_build_week_plan_each_day_has_correct_meal_count():
    plan = build_week_plan("nigeria", 2000, days=3, meal_types=("breakfast", "lunch", "dinner"))
    for day in plan:
        assert len(day["meals"]) == 3


def test_build_week_plan_us_region_works_independently_of_nigeria():
    plan = build_week_plan("us", 1800, days=5)
    assert len(plan) == 5
    all_names = {m["name"] for day in plan for m in day["meals"]}
    us_meals = load_meals("us")
    us_names = {m["name"] for m in us_meals}
    assert all_names.issubset(us_names)
