"""
Your own serving sizes, whole items split into servings, notes, food
editing, and the daily calorie total. Cases use real entries from the
food timetable this feature was built for (bread, banana bread, cashews,
boiled egg, yoghurt).

Runs on SQLite by default, or on PostgreSQL when DATABASE_URL is set.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db

_scratch = Path(tempfile.mkdtemp()) / "import.db"
db.DB_PATH = _scratch

import app as app_module  # noqa: E402
import limits  # noqa: E402
from food_library import normalize_food, nutrition_for, InvalidFoodData  # noqa: E402

PASSWORD = "Password-123"
PROFILE = {
    "weight_kg": 70, "height_cm": 170, "age": 30, "sex": "female",
    "activity_level": "sedentary", "goal": "maintain", "region": "nigeria", "days": 5,
}
BANANA_BREAD = {
    "name": "Banana bread", "meal_category": "breakfast",
    "serving_size": 1, "serving_unit": "slice",
    "whole_label": "loaf", "whole_calories": 3000, "servings_per_whole": 20,
    "notes": "Homemade loaf, cut into 20 slices",
}
CASHEWS = {"name": "Cashews", "meal_category": "snack", "serving_size": 10, "serving_unit": "g", "serving_calories": 55}


@pytest.fixture(autouse=True)
def fresh_database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    limits.reset_rate_limits()
    yield
    limits.reset_rate_limits()


@pytest.fixture
def user():
    client = app_module.app.test_client()
    assert client.post("/signup", data={"email": "eater@example.com", "password": PASSWORD}).status_code == 302
    return client


# ---------- serving sizes ----------

def test_whole_item_sets_calories_per_serving():
    food = normalize_food(BANANA_BREAD)
    assert food["calories_per_100g"] * food["serving_size"] / 100 == pytest.approx(150)


def test_bread_loaf_divided_into_twelve():
    food = normalize_food({"name": "Bread", "serving_size": 1, "serving_unit": "slice",
                           "whole_label": "loaf", "whole_calories": 2480, "servings_per_whole": 12})
    assert nutrition_for(food, 1)["calories"] == pytest.approx(206.7)
    assert nutrition_for(food, 12)["calories"] == pytest.approx(2480)


def test_small_gram_serving_scales_correctly():
    food = normalize_food(CASHEWS)
    assert nutrition_for(food, 10)["calories"] == 55
    assert nutrition_for(food, 30)["calories"] == 165


def test_per_serving_macros_are_scaled_too():
    food = normalize_food({**CASHEWS, "protein_per_serving": 1.8})
    assert nutrition_for(food, 20)["protein_g"] == pytest.approx(3.6)


def test_older_per_100g_input_still_works():
    food = normalize_food({"name": "Rice", "calories_per_100g": 130, "protein_per_100g": 2.7,
                           "carbs_per_100g": 28, "fat_per_100g": 0.3})
    assert food["serving_size"] == 100 and food["serving_unit"] == "g"
    assert nutrition_for(food, 250)["calories"] == 325


@pytest.mark.parametrize("bad", [
    {"serving_size": 0}, {"serving_size": "abc"}, {"serving_calories": -5},
    {"whole_calories": 3000, "servings_per_whole": None}, {"servings_per_whole": 20, "serving_calories": None},
    {"name": "  "},
])
def test_invalid_food_values_are_rejected(bad):
    with pytest.raises(InvalidFoodData):
        normalize_food({**CASHEWS, **bad})


# ---------- the food API ----------

def test_add_food_with_own_serving_and_notes(user):
    response = user.post("/api/foods", json=BANANA_BREAD)
    assert response.status_code == 201
    food = response.get_json()
    assert food["serving_calories"] == 150
    assert food["serving_unit"] == "slice"
    assert food["whole_calories"] == 3000 and food["servings_per_whole"] == 20 and food["whole_label"] == "loaf"
    assert food["notes"] == "Homemade loaf, cut into 20 slices"


def test_manual_food_does_not_need_a_lookup(user, monkeypatch):
    monkeypatch.setattr(app_module, "search_food_nutrition", lambda name: pytest.fail("lookup should be skipped"))
    assert user.post("/api/foods", json={"name": "Boiled egg", "serving_size": 1, "serving_unit": "egg",
                                         "serving_calories": 75}).status_code == 201


def test_invalid_manual_food_is_a_client_error(user):
    response = user.post("/api/foods", json={**CASHEWS, "serving_size": 0})
    assert response.status_code == 400
    assert "Serving amount" in response.get_json()["error"]


def test_editing_the_loaf_recalculates_the_slice(user):
    food = user.post("/api/foods", json=BANANA_BREAD).get_json()
    edited = user.put(f"/api/foods/{food['id']}", json={**BANANA_BREAD, "servings_per_whole": 15, "notes": "Thicker slices"})
    assert edited.status_code == 200
    assert edited.get_json()["serving_calories"] == 200
    assert edited.get_json()["notes"] == "Thicker slices"


def test_editing_keeps_micronutrients_the_form_does_not_show(user):
    food = user.post("/api/foods", json={**CASHEWS, "calcium_mg_per_100g": 37}).get_json()
    edited = user.put(f"/api/foods/{food['id']}", json={**CASHEWS, "serving_calories": 60}).get_json()
    assert edited["calcium_mg_per_100g"] == 37


def test_cannot_edit_someone_elses_food(user):
    food = user.post("/api/foods", json=CASHEWS).get_json()
    other = app_module.app.test_client()
    other.post("/signup", data={"email": "other@example.com", "password": PASSWORD})
    assert other.put(f"/api/foods/{food['id']}", json=CASHEWS).status_code == 404


def test_timetable_edit_uses_the_foods_own_unit(user):
    food = user.post("/api/foods", json=BANANA_BREAD).get_json()
    meal_id = user.post("/api/generate-plan", json=PROFILE).get_json()["plan"][0]["meals"][0]["id"]
    result = user.patch(f"/api/plan/meals/{meal_id}", json={"food_id": food["id"], "quantity": 2}).get_json()
    assert result["meal"]["calories"] == 300
    assert result["meal"]["grams"] == 2 and result["meal"]["unit"] == "slice"


def test_timetable_edit_defaults_to_one_serving(user):
    food = user.post("/api/foods", json=CASHEWS).get_json()
    meal_id = user.post("/api/generate-plan", json=PROFILE).get_json()["plan"][0]["meals"][0]["id"]
    result = user.patch(f"/api/plan/meals/{meal_id}", json={"food_id": food["id"]}).get_json()
    assert result["meal"]["calories"] == 55 and result["meal"]["grams"] == 10


def test_a_food_used_in_the_timetable_can_still_be_removed(user):
    food = user.post("/api/foods", json=CASHEWS).get_json()
    meal_id = user.post("/api/generate-plan", json=PROFILE).get_json()["plan"][0]["meals"][0]["id"]
    user.patch(f"/api/plan/meals/{meal_id}", json={"food_id": food["id"]})
    user.post("/api/day-log", json={"date": "2026-09-25", "food_id": food["id"]})
    assert user.delete(f"/api/foods/{food['id']}").status_code == 200
    day = user.get("/api/day-log?date=2026-09-25").get_json()
    assert day["entries"][0]["name"] == "Cashews" and day["total_calories"] == 55


# ---------- daily calorie total ----------

def test_daily_total_adds_up_the_days_items(user):
    bread = user.post("/api/foods", json=BANANA_BREAD).get_json()
    cashews = user.post("/api/foods", json=CASHEWS).get_json()
    user.post("/api/day-log", json={"date": "2026-09-25", "meal_type": "breakfast", "food_id": bread["id"], "quantity": 2})
    user.post("/api/day-log", json={"date": "2026-09-25", "meal_type": "snack", "food_id": cashews["id"], "quantity": 20})
    added = user.post("/api/day-log", json={"date": "2026-09-25", "meal_type": "lunch", "food_name": "Eba", "calories": 160, "quantity": 100})
    assert added.status_code == 201
    assert added.get_json()["total_calories"] == 570

    day = user.get("/api/day-log?date=2026-09-25").get_json()
    assert [e["name"] for e in day["entries"]] == ["Banana bread", "Cashews", "Eba"]
    assert day["entries"][0]["unit"] == "slice" and day["entries"][2]["unit"] == "g"
    assert day["total_calories"] == 570


def test_days_are_kept_separate(user):
    user.post("/api/day-log", json={"date": "2026-09-24", "food_name": "Yoghurt", "calories": 220})
    assert user.get("/api/day-log?date=2026-09-25").get_json()["total_calories"] == 0


def test_removing_an_entry_updates_the_total(user):
    entry = user.post("/api/day-log", json={"date": "2026-09-25", "food_name": "Boiled egg", "calories": 75}).get_json()["entry"]
    user.post("/api/day-log", json={"date": "2026-09-25", "food_name": "Apple", "calories": 50})
    assert user.delete(f"/api/day-log/{entry['id']}").status_code == 200
    assert user.get("/api/day-log?date=2026-09-25").get_json()["total_calories"] == 50


def test_daily_entries_are_private(user):
    entry = user.post("/api/day-log", json={"date": "2026-09-25", "food_name": "Egg", "calories": 75}).get_json()["entry"]
    other = app_module.app.test_client()
    other.post("/signup", data={"email": "other@example.com", "password": PASSWORD})
    assert other.get("/api/day-log?date=2026-09-25").get_json()["entries"] == []
    assert other.delete(f"/api/day-log/{entry['id']}").status_code == 404


@pytest.mark.parametrize("bad", [
    {"date": "2026-02-30", "food_name": "Egg", "calories": 75},
    {"date": "2026-09-25", "food_name": "", "calories": 75},
    {"date": "2026-09-25", "food_name": "Egg", "calories": "lots"},
    {"date": "2026-09-25", "food_name": "Egg", "calories": 75, "meal_type": "brunch"},
    {"date": "2026-09-25", "food_id": "abc"},
])
def test_bad_daily_entries_are_rejected(user, bad):
    assert user.post("/api/day-log", json=bad).status_code == 400


def test_cannot_log_someone_elses_food(user):
    food = user.post("/api/foods", json=CASHEWS).get_json()
    other = app_module.app.test_client()
    other.post("/signup", data={"email": "other@example.com", "password": PASSWORD})
    assert other.post("/api/day-log", json={"date": "2026-09-25", "food_id": food["id"]}).status_code == 404
