import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from auth import create_user
from food_library import (
    add_food, get_foods, get_food, delete_food, update_food_category,
    FoodNotFound, InvalidCategory,
)


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


SAMPLE_FOOD = {
    "name": "Chicken breast",
    "calories_per_100g": 165,
    "protein_per_100g": 31,
    "carbs_per_100g": 0,
    "fat_per_100g": 3.6,
}


def test_add_food_returns_food_with_id(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], SAMPLE_FOOD)
    assert food["id"] is not None
    assert food["name"] == "Chicken breast"
    assert food["calories_per_100g"] == 165


def test_get_foods_returns_only_that_users_foods(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")

    add_food(conn, user1["id"], SAMPLE_FOOD)
    add_food(conn, user2["id"], {**SAMPLE_FOOD, "name": "Rice"})

    user1_foods = get_foods(conn, user1["id"])
    assert len(user1_foods) == 1
    assert user1_foods[0]["name"] == "Chicken breast"


def test_get_foods_sorted_alphabetically(conn):
    user = create_user(conn, "test@example.com", "password123")
    add_food(conn, user["id"], {**SAMPLE_FOOD, "name": "Rice"})
    add_food(conn, user["id"], {**SAMPLE_FOOD, "name": "Avocado"})

    foods = get_foods(conn, user["id"])
    assert [f["name"] for f in foods] == ["Avocado", "Rice"]


def test_get_food_raises_for_unknown_id(conn):
    user = create_user(conn, "test@example.com", "password123")
    with pytest.raises(FoodNotFound):
        get_food(conn, user["id"], 9999)


def test_delete_food_removes_it(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], SAMPLE_FOOD)

    delete_food(conn, user["id"], food["id"])

    assert get_foods(conn, user["id"]) == []


def test_cannot_delete_another_users_food(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")
    food = add_food(conn, user1["id"], SAMPLE_FOOD)

    with pytest.raises(FoodNotFound):
        delete_food(conn, user2["id"], food["id"])

    assert len(get_foods(conn, user1["id"])) == 1


def test_delete_nonexistent_food_raises(conn):
    user = create_user(conn, "test@example.com", "password123")
    with pytest.raises(FoodNotFound):
        delete_food(conn, user["id"], 9999)


def test_empty_food_list_for_new_user(conn):
    user = create_user(conn, "test@example.com", "password123")
    assert get_foods(conn, user["id"]) == []


def test_food_defaults_micronutrients_to_zero_when_not_provided(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], SAMPLE_FOOD)  # SAMPLE_FOOD has no micronutrient keys
    assert food["calcium_mg_per_100g"] == 0
    assert food["vitamin_c_mg_per_100g"] == 0
    assert food["omega3_g_per_100g"] == 0


def test_food_stores_provided_micronutrients(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], {
        **SAMPLE_FOOD,
        "calcium_mg_per_100g": 15,
        "vitamin_c_mg_per_100g": 8.5,
        "omega3_g_per_100g": 0.3,
    })
    assert food["calcium_mg_per_100g"] == 15
    assert food["vitamin_c_mg_per_100g"] == 8.5
    assert food["omega3_g_per_100g"] == 0.3


def test_food_defaults_to_other_category(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], SAMPLE_FOOD)
    assert food["meal_category"] == "other"


def test_food_stores_provided_category(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], {**SAMPLE_FOOD, "meal_category": "breakfast"})
    assert food["meal_category"] == "breakfast"


def test_add_food_rejects_invalid_category(conn):
    user = create_user(conn, "test@example.com", "password123")
    with pytest.raises(InvalidCategory):
        add_food(conn, user["id"], {**SAMPLE_FOOD, "meal_category": "brunch"})


def test_update_food_category_changes_it(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], SAMPLE_FOOD)  # defaults to "other"

    updated = update_food_category(conn, user["id"], food["id"], "dinner")
    assert updated["meal_category"] == "dinner"

    # confirm it actually persisted, not just returned
    fetched = get_food(conn, user["id"], food["id"])
    assert fetched["meal_category"] == "dinner"


def test_update_category_rejects_invalid_value(conn):
    user = create_user(conn, "test@example.com", "password123")
    food = add_food(conn, user["id"], SAMPLE_FOOD)
    with pytest.raises(InvalidCategory):
        update_food_category(conn, user["id"], food["id"], "brunch")


def test_update_category_cannot_target_another_users_food(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")
    food = add_food(conn, user1["id"], SAMPLE_FOOD)

    with pytest.raises(FoodNotFound):
        update_food_category(conn, user2["id"], food["id"], "dinner")

    # confirm user1's food category is unchanged
    fetched = get_food(conn, user1["id"], food["id"])
    assert fetched["meal_category"] == "other"
