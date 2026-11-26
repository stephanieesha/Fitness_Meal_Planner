"""
Weight storage: what gets saved, in what order it comes back, whose it is, and which posted
entries are accepted.

Runs on SQLite by default, or on PostgreSQL when DATABASE_URL is set.
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from auth import create_user
from weight_storage import (
    save_weight_entry, get_weight_history, get_latest_weight, delete_weight_entry,
    validate_weight_entry, InvalidWeightEntry,
)

TODAY = date(2026, 11, 26)


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


@pytest.fixture
def user_id(conn):
    return create_user(conn, "weigher@example.com", "password123")["id"]


# ---------- saving and reading ----------

def test_saved_entry_comes_back_with_its_id(conn, user_id):
    entry = save_weight_entry(conn, user_id, 70.5, "2026-11-20")

    assert entry["weight_kg"] == 70.5 and entry["logged_date"] == "2026-11-20"
    assert get_weight_history(conn, user_id) == [entry]


def test_logging_the_same_day_again_replaces_that_days_weight(conn, user_id):
    first = save_weight_entry(conn, user_id, 71.0, "2026-11-20")
    second = save_weight_entry(conn, user_id, 70.2, "2026-11-20")

    assert second["id"] == first["id"]
    assert get_weight_history(conn, user_id) == [second]
    assert second["weight_kg"] == 70.2


def test_history_is_sorted_by_date_whatever_order_it_was_logged_in(conn, user_id):
    save_weight_entry(conn, user_id, 69.0, "2026-11-25")
    save_weight_entry(conn, user_id, 71.0, "2026-11-01")
    save_weight_entry(conn, user_id, 70.0, "2026-11-12")

    assert [e["logged_date"] for e in get_weight_history(conn, user_id)] == ["2026-11-01", "2026-11-12", "2026-11-25"]


def test_latest_weight_is_the_newest_date_not_the_last_one_logged(conn, user_id):
    save_weight_entry(conn, user_id, 69.0, "2026-11-25")
    save_weight_entry(conn, user_id, 71.0, "2026-11-01")

    assert get_latest_weight(conn, user_id)["weight_kg"] == 69.0


def test_latest_weight_is_none_before_anything_is_logged(conn, user_id):
    assert get_latest_weight(conn, user_id) is None
    assert get_weight_history(conn, user_id) == []


# ---------- whose entries they are ----------

def test_each_person_only_sees_their_own_weights(conn, user_id):
    other_id = create_user(conn, "other@example.com", "password123")["id"]
    save_weight_entry(conn, user_id, 70.0, "2026-11-20")
    save_weight_entry(conn, other_id, 90.0, "2026-11-22")

    assert [e["weight_kg"] for e in get_weight_history(conn, user_id)] == [70.0]
    assert get_latest_weight(conn, user_id)["weight_kg"] == 70.0
    assert get_latest_weight(conn, other_id)["weight_kg"] == 90.0


def test_two_people_can_log_the_same_day(conn, user_id):
    other_id = create_user(conn, "other@example.com", "password123")["id"]
    save_weight_entry(conn, user_id, 70.0, "2026-11-20")
    save_weight_entry(conn, other_id, 90.0, "2026-11-20")

    assert get_weight_history(conn, user_id)[0]["weight_kg"] == 70.0
    assert get_weight_history(conn, other_id)[0]["weight_kg"] == 90.0


def test_deleting_removes_only_that_entry(conn, user_id):
    keep = save_weight_entry(conn, user_id, 70.0, "2026-11-20")
    drop = save_weight_entry(conn, user_id, 71.0, "2026-11-21")

    delete_weight_entry(conn, user_id, drop["id"])

    assert get_weight_history(conn, user_id) == [keep]


def test_someone_else_cannot_delete_your_entry(conn, user_id):
    other_id = create_user(conn, "other@example.com", "password123")["id"]
    entry = save_weight_entry(conn, user_id, 70.0, "2026-11-20")

    delete_weight_entry(conn, other_id, entry["id"])

    assert get_weight_history(conn, user_id) == [entry]


# ---------- which entries are accepted ----------

@pytest.mark.parametrize("posted, expected", [
    pytest.param({"weight_kg": "70.5", "logged_date": "2026-11-20"}, (70.5, "2026-11-20"), id="text-weight"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-11-20"}, (70.0, "2026-11-20"), id="whole-number"),
    pytest.param({"weight_kg": "  72 ", "logged_date": " 2026-11-20 "}, (72.0, "2026-11-20"), id="spaces-around"),
    pytest.param({"weight_kg": "70.456", "logged_date": "2026-11-20"}, (70.5, "2026-11-20"), id="rounded-to-one-decimal"),
    pytest.param({"weight_kg": "70.44", "logged_date": "2026-11-20"}, (70.4, "2026-11-20"), id="rounded-down"),
    pytest.param({"weight_kg": 20, "logged_date": "2026-11-20"}, (20.0, "2026-11-20"), id="lightest-allowed"),
    pytest.param({"weight_kg": 500, "logged_date": "2026-11-20"}, (500.0, "2026-11-20"), id="heaviest-allowed"),
    pytest.param({"weight_kg": 70, "logged_date": "1900-01-01"}, (70.0, "1900-01-01"), id="earliest-date-allowed"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-11-26"}, (70.0, "2026-11-26"), id="today"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-11-27"}, (70.0, "2026-11-27"), id="tomorrow-for-people-east-of-utc"),
])
def test_good_entries_are_accepted(posted, expected):
    assert validate_weight_entry(posted, today=TODAY) == expected


@pytest.mark.parametrize("posted, message", [
    pytest.param(None, "JSON object", id="no-body"),
    pytest.param([70], "JSON object", id="list-body"),
    pytest.param("70", "JSON object", id="string-body"),
    pytest.param(70, "JSON object", id="number-body"),
    pytest.param({"weight_kg": 70}, "YYYY-MM-DD", id="no-date"),
    pytest.param({"weight_kg": 70, "logged_date": None}, "YYYY-MM-DD", id="date-is-null"),
    pytest.param({"weight_kg": 70, "logged_date": 20261120}, "YYYY-MM-DD", id="date-is-a-number"),
    pytest.param({"weight_kg": 70, "logged_date": ""}, "YYYY-MM-DD", id="date-is-empty"),
    pytest.param({"weight_kg": 70, "logged_date": "20/11/2026"}, "YYYY-MM-DD", id="date-in-another-format"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-1-5"}, "YYYY-MM-DD", id="date-without-zeros"),
    pytest.param({"weight_kg": 70, "logged_date": "٢٠٢٦-11-20"}, "YYYY-MM-DD", id="date-in-other-digits"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-02-30"}, "real calendar date", id="date-that-does-not-exist"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-13-01"}, "real calendar date", id="month-13"),
    pytest.param({"weight_kg": 70, "logged_date": "1899-12-31"}, "1900-01-01", id="before-1900"),
    pytest.param({"weight_kg": 70, "logged_date": "0026-11-26"}, "1900-01-01", id="year-typed-as-26"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-11-28"}, "future", id="two-days-ahead"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-11-29"}, "future", id="three-days-ahead"),
    pytest.param({"weight_kg": 70, "logged_date": "2099-01-01"}, "future", id="far-future"),
    pytest.param({"logged_date": "2026-11-20"}, "must be a number", id="no-weight"),
    pytest.param({"weight_kg": None, "logged_date": "2026-11-20"}, "must be a number", id="weight-is-null"),
    pytest.param({"weight_kg": "", "logged_date": "2026-11-20"}, "must be a number", id="weight-is-empty"),
    pytest.param({"weight_kg": "heavy", "logged_date": "2026-11-20"}, "must be a number", id="weight-is-text"),
    pytest.param({"weight_kg": "70,5", "logged_date": "2026-11-20"}, "must be a number", id="comma-decimal"),
    pytest.param({"weight_kg": True, "logged_date": "2026-11-20"}, "must be a number", id="weight-is-true"),
    pytest.param({"weight_kg": [70], "logged_date": "2026-11-20"}, "must be a number", id="weight-is-a-list"),
    pytest.param({"weight_kg": 10 ** 400, "logged_date": "2026-11-20"}, "must be a number", id="weight-too-big-for-a-float"),
    pytest.param({"weight_kg": "nan", "logged_date": "2026-11-20"}, "realistic", id="not-a-number-value"),
    pytest.param({"weight_kg": "inf", "logged_date": "2026-11-20"}, "realistic", id="infinity"),
    pytest.param({"weight_kg": -70, "logged_date": "2026-11-20"}, "realistic", id="negative"),
    pytest.param({"weight_kg": 0, "logged_date": "2026-11-20"}, "realistic", id="zero"),
    pytest.param({"weight_kg": 19.9, "logged_date": "2026-11-20"}, "realistic", id="just-under-20"),
    pytest.param({"weight_kg": 500.1, "logged_date": "2026-11-20"}, "realistic", id="just-over-500"),
])
def test_bad_entries_are_refused_with_a_message(posted, message):
    with pytest.raises(InvalidWeightEntry) as refused:
        validate_weight_entry(posted, today=TODAY)

    assert message in str(refused.value)


def test_a_bad_date_is_reported_before_a_bad_weight():
    with pytest.raises(InvalidWeightEntry) as refused:
        validate_weight_entry({"weight_kg": "heavy", "logged_date": "2026-02-30"}, today=TODAY)

    assert "real calendar date" in str(refused.value)
