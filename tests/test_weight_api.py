"""
The weight API: logging, correcting and removing weights, and refusing entries that would leave the
history or the current weight shown on the dashboard wrong.

Runs on SQLite by default, or on PostgreSQL when DATABASE_URL is set.
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db

_scratch = Path(tempfile.mkdtemp()) / "import.db"
db.DB_PATH = _scratch

import app as app_module  # noqa: E402
import limits  # noqa: E402

PASSWORD = "Password-123"


def days_from_today(days: int) -> str:
    """A date relative to today's UTC date, which is the day the server counts as today."""
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def fresh_database(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    limits.reset_rate_limits()
    yield
    limits.reset_rate_limits()


def signed_up(email: str):
    client = app_module.app.test_client()
    assert client.post("/signup", data={"email": email, "password": PASSWORD}).status_code == 302
    return client


@pytest.fixture
def user():
    return signed_up("weigher@example.com")


def log(client, weight, logged_date):
    return client.post("/api/weight", json={"weight_kg": weight, "logged_date": logged_date})


# ---------- logging in is needed ----------

def test_the_weight_api_needs_a_login():
    anonymous = app_module.app.test_client()

    responses = [
        anonymous.get("/api/weight"),
        anonymous.get("/api/weight/latest"),
        log(anonymous, 70, days_from_today(-1)),
        anonymous.delete("/api/weight/1"),
    ]

    for response in responses:
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# ---------- logging and reading ----------

def test_a_logged_weight_comes_back_in_the_history(user):
    response = log(user, "70.5", days_from_today(-3))

    assert response.status_code == 201
    entry = response.get_json()
    assert entry["weight_kg"] == 70.5 and entry["logged_date"] == days_from_today(-3)
    assert user.get("/api/weight").get_json() == [entry]


def test_weight_is_kept_to_one_decimal(user):
    assert log(user, "70.456", days_from_today(-3)).get_json()["weight_kg"] == 70.5


def test_logging_the_same_day_again_corrects_it(user):
    day = days_from_today(-3)
    log(user, 71, day)
    log(user, 70.2, day)

    history = user.get("/api/weight").get_json()

    assert [(e["logged_date"], e["weight_kg"]) for e in history] == [(day, 70.2)]


def test_tomorrows_date_is_allowed_for_people_ahead_of_utc(user):
    assert log(user, 70, days_from_today(1)).status_code == 201


def test_current_weight_is_empty_before_anything_is_logged(user):
    assert user.get("/api/weight/latest").get_json() is None


def test_current_weight_is_the_newest_date_not_the_last_one_logged(user):
    log(user, 69, days_from_today(-1))
    log(user, 71, days_from_today(-10))

    assert user.get("/api/weight/latest").get_json()["weight_kg"] == 69


# ---------- refusing bad entries ----------

@pytest.mark.parametrize("body, message", [
    pytest.param([70], "JSON object", id="list-instead-of-object"),
    pytest.param("70", "JSON object", id="string-instead-of-object"),
    pytest.param({"weight_kg": 70, "logged_date": 20261120}, "YYYY-MM-DD", id="date-is-a-number"),
    pytest.param({"weight_kg": 70}, "YYYY-MM-DD", id="no-date"),
    pytest.param({"weight_kg": 70, "logged_date": "2026-02-30"}, "real calendar date", id="date-that-does-not-exist"),
    pytest.param({"weight_kg": 70, "logged_date": "0026-11-26"}, "1900-01-01", id="year-typed-as-26"),
    pytest.param({"weight_kg": 70, "logged_date": days_from_today(3)}, "future", id="future-date"),
    pytest.param({"logged_date": days_from_today(-1)}, "must be a number", id="no-weight"),
    pytest.param({"weight_kg": "heavy", "logged_date": days_from_today(-1)}, "must be a number", id="weight-is-text"),
    pytest.param({"weight_kg": True, "logged_date": days_from_today(-1)}, "must be a number", id="weight-is-true"),
    pytest.param({"weight_kg": 19.9, "logged_date": days_from_today(-1)}, "realistic", id="too-light"),
    pytest.param({"weight_kg": 500.1, "logged_date": days_from_today(-1)}, "realistic", id="too-heavy"),
])
def test_a_bad_entry_is_refused_with_a_message_and_not_saved(user, body, message):
    response = user.post("/api/weight", json=body)

    assert response.status_code == 400
    assert message in response.get_json()["error"]
    assert user.get("/api/weight").get_json() == []


@pytest.mark.parametrize("request_args", [
    pytest.param({"data": "{not json", "content_type": "application/json"}, id="broken-json"),
    pytest.param({"data": {"weight_kg": "70", "logged_date": "2026-11-20"}}, id="form-instead-of-json"),
])
def test_a_body_that_is_not_json_gets_a_json_error_not_an_error_page(user, request_args):
    response = user.post("/api/weight", **request_args)

    assert response.status_code == 400
    assert "JSON object" in response.get_json()["error"]


def test_a_refused_future_date_cannot_become_the_current_weight(user):
    log(user, 69, days_from_today(-1))

    assert log(user, 90, "2099-01-01").status_code == 400

    assert user.get("/api/weight/latest").get_json()["weight_kg"] == 69


# ---------- removing and privacy ----------

def test_an_entry_can_be_deleted(user):
    entry = log(user, 70, days_from_today(-3)).get_json()

    assert user.delete(f"/api/weight/{entry['id']}").status_code == 200

    assert user.get("/api/weight").get_json() == []


def test_nobody_else_can_see_or_delete_your_entry(user):
    entry = log(user, 70, days_from_today(-3)).get_json()
    other = signed_up("other@example.com")

    assert other.get("/api/weight").get_json() == []
    assert other.get("/api/weight/latest").get_json() is None
    other.delete(f"/api/weight/{entry['id']}")

    assert user.get("/api/weight").get_json() == [entry]
