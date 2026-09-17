import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from auth import create_user
from plan_storage import save_plan, get_latest_plan, update_plan_meal, PlanMealNotFound


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


SAMPLE_WEEK_PLAN = [
    {
        "day": 1,
        "meals": [
            {"meal_type": "breakfast", "name": "Oatmeal", "calories": 300, "protein_g": 10, "carbs_g": 50, "fat_g": 5, "serving_desc": "1 bowl", "portion_multiplier": 1.0},
            {"meal_type": "lunch", "name": "Chicken salad", "calories": 500, "protein_g": 35, "carbs_g": 20, "fat_g": 18, "serving_desc": "1 bowl", "portion_multiplier": 1.0},
        ],
        "totals": {"calories": 800, "protein_g": 45, "carbs_g": 70, "fat_g": 23},
    },
    {
        "day": 2,
        "meals": [
            {"meal_type": "breakfast", "name": "Eggs", "calories": 280, "protein_g": 20, "carbs_g": 2, "fat_g": 20, "serving_desc": "2 eggs", "portion_multiplier": 1.0},
        ],
        "totals": {"calories": 280, "protein_g": 20, "carbs_g": 2, "fat_g": 20},
    },
]


def test_save_plan_returns_a_batch_id(conn):
    user = create_user(conn, "test@example.com", "password123")
    batch = save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)
    assert batch is not None
    assert isinstance(batch, str)


def test_get_latest_plan_reassembles_days_and_meals(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)

    plan = get_latest_plan(conn, user["id"])
    assert len(plan) == 2
    assert len(plan[0]["meals"]) == 2
    assert plan[0]["meals"][0]["name"] == "Oatmeal"


def test_get_latest_plan_computes_correct_totals(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)

    plan = get_latest_plan(conn, user["id"])
    day1 = next(d for d in plan if d["day"] == 1)
    assert day1["totals"]["calories"] == 800


def test_get_latest_plan_returns_empty_list_when_no_plan_saved(conn):
    user = create_user(conn, "test@example.com", "password123")
    assert get_latest_plan(conn, user["id"]) == []


def test_saved_meals_have_real_ids_for_editing(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)

    plan = get_latest_plan(conn, user["id"])
    assert plan[0]["meals"][0]["id"] is not None


def test_get_latest_plan_only_returns_that_users_plan(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")

    save_plan(conn, user1["id"], SAMPLE_WEEK_PLAN)

    assert get_latest_plan(conn, user2["id"]) == []


def test_get_latest_plan_returns_most_recent_batch_not_all_history(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)

    second_plan = [{"day": 1, "meals": [{"meal_type": "breakfast", "name": "Toast", "calories": 200, "protein_g": 5, "carbs_g": 30, "fat_g": 5}], "totals": {}}]
    save_plan(conn, user["id"], second_plan)

    plan = get_latest_plan(conn, user["id"])
    assert len(plan) == 1
    assert plan[0]["meals"][0]["name"] == "Toast"


def test_update_plan_meal_changes_the_food_and_calories(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)
    meal_id = get_latest_plan(conn, user["id"])[0]["meals"][0]["id"]

    result = update_plan_meal(conn, user["id"], meal_id, {
        "food_name": "Pancakes", "calories": 450, "protein_g": 8, "carbs_g": 60, "fat_g": 15,
    })

    assert result["meal"]["name"] == "Pancakes"
    assert result["meal"]["calories"] == 450


def test_update_plan_meal_recalculates_day_totals_correctly(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)
    meal_id = get_latest_plan(conn, user["id"])[0]["meals"][0]["id"]  # Oatmeal, 300 kcal

    result = update_plan_meal(conn, user["id"], meal_id, {
        "food_name": "Pancakes", "calories": 450, "protein_g": 8, "carbs_g": 60, "fat_g": 15,
    })

    assert result["day_totals"]["calories"] == 950  # 450 + 500, not the stale 800


def test_update_plan_meal_persists_not_just_returns(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_plan(conn, user["id"], SAMPLE_WEEK_PLAN)
    meal_id = get_latest_plan(conn, user["id"])[0]["meals"][0]["id"]

    update_plan_meal(conn, user["id"], meal_id, {
        "food_name": "Pancakes", "calories": 450, "protein_g": 8, "carbs_g": 60, "fat_g": 15,
    })

    plan = get_latest_plan(conn, user["id"])
    assert plan[0]["meals"][0]["name"] == "Pancakes"


def test_update_plan_meal_raises_for_unknown_id(conn):
    user = create_user(conn, "test@example.com", "password123")
    with pytest.raises(PlanMealNotFound):
        update_plan_meal(conn, user["id"], 9999, {"food_name": "X", "calories": 100})


def test_cannot_edit_another_users_plan_meal(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")
    save_plan(conn, user1["id"], SAMPLE_WEEK_PLAN)
    meal_id = get_latest_plan(conn, user1["id"])[0]["meals"][0]["id"]

    with pytest.raises(PlanMealNotFound):
        update_plan_meal(conn, user2["id"], meal_id, {"food_name": "Hacked", "calories": 1})

    plan = get_latest_plan(conn, user1["id"])
    assert plan[0]["meals"][0]["name"] == "Oatmeal"
