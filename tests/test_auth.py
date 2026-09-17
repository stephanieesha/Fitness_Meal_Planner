import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from auth import (
    create_user, authenticate_user, get_user_by_id,
    save_target_entry, get_target_history,
    EmailAlreadyExists, InvalidCredentials,
)


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


def test_create_user_returns_user_with_id(conn):
    user = create_user(conn, "test@example.com", "password123")
    assert user["id"] is not None
    assert user["email"] == "test@example.com"


def test_password_is_hashed_not_stored_plaintext(conn):
    user = create_user(conn, "test@example.com", "password123")
    assert user["password_hash"] != "password123"


def test_duplicate_email_rejected(conn):
    create_user(conn, "test@example.com", "password123")
    with pytest.raises(EmailAlreadyExists):
        create_user(conn, "test@example.com", "differentpassword")


def test_authenticate_with_correct_password_succeeds(conn):
    create_user(conn, "test@example.com", "password123")
    user = authenticate_user(conn, "test@example.com", "password123")
    assert user["email"] == "test@example.com"


def test_authenticate_with_wrong_password_fails(conn):
    create_user(conn, "test@example.com", "password123")
    with pytest.raises(InvalidCredentials):
        authenticate_user(conn, "test@example.com", "wrongpassword")


def test_authenticate_with_nonexistent_email_fails(conn):
    with pytest.raises(InvalidCredentials):
        authenticate_user(conn, "nobody@example.com", "password123")


def test_get_user_by_id_returns_none_for_unknown_id(conn):
    assert get_user_by_id(conn, 9999) is None


SAMPLE_TARGETS = {
    "bmr": 1500, "tdee": 2000, "calorie_target": 1500,
    "floor_applied": False,
    "macros": {"protein_g": 110, "carbs_g": 150, "fat_g": 50},
}

SAMPLE_PROFILE = {
    "weight_kg": 65, "height_cm": 165, "age": 29, "sex": "female",
    "activity_level": "light", "goal": "lose", "region": "nigeria",
}


def test_save_and_retrieve_target_entry(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_target_entry(conn, user["id"], SAMPLE_PROFILE, SAMPLE_TARGETS)

    history = get_target_history(conn, user["id"])
    assert len(history) == 1
    assert history[0]["calorie_target"] == 1500
    assert history[0]["weight_kg"] == 65


def test_target_history_only_returns_entries_for_that_user(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")

    save_target_entry(conn, user1["id"], SAMPLE_PROFILE, SAMPLE_TARGETS)
    save_target_entry(conn, user2["id"], SAMPLE_PROFILE, SAMPLE_TARGETS)

    user1_history = get_target_history(conn, user1["id"])
    assert len(user1_history) == 1


def test_target_history_ordered_oldest_first(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_target_entry(conn, user["id"], SAMPLE_PROFILE, SAMPLE_TARGETS)
    heavier_profile = {**SAMPLE_PROFILE, "weight_kg": 70}
    save_target_entry(conn, user["id"], heavier_profile, SAMPLE_TARGETS)

    history = get_target_history(conn, user["id"])
    assert history[0]["weight_kg"] == 65
    assert history[1]["weight_kg"] == 70


def test_empty_history_for_new_user(conn):
    user = create_user(conn, "test@example.com", "password123")
    assert get_target_history(conn, user["id"]) == []
