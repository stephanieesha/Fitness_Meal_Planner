import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from auth import create_user
from activity_storage import save_activity_log, get_activity_log


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


def test_save_and_retrieve_activity_log(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_activity_log(conn, user["id"], {"2026-01-01": 450.5, "2026-01-02": 380.0})

    log = get_activity_log(conn, user["id"])
    assert len(log) == 2


def test_reuploading_same_date_updates_not_duplicates(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_activity_log(conn, user["id"], {"2026-01-01": 400.0})
    save_activity_log(conn, user["id"], {"2026-01-01": 450.0})

    log = get_activity_log(conn, user["id"])
    assert len(log) == 1
    assert log[0]["active_calories"] == 450.0


def test_activity_log_isolated_per_user(conn):
    user1 = create_user(conn, "user1@example.com", "password123")
    user2 = create_user(conn, "user2@example.com", "password123")

    save_activity_log(conn, user1["id"], {"2026-01-01": 400.0})
    save_activity_log(conn, user2["id"], {"2026-01-01": 999.0})

    user1_log = get_activity_log(conn, user1["id"])
    assert len(user1_log) == 1
    assert user1_log[0]["active_calories"] == 400.0


def test_get_activity_log_ordered_most_recent_first(conn):
    user = create_user(conn, "test@example.com", "password123")
    save_activity_log(conn, user["id"], {"2026-01-01": 100.0, "2026-01-03": 300.0, "2026-01-02": 200.0})

    log = get_activity_log(conn, user["id"])
    dates = [entry["activity_date"] for entry in log]
    assert dates == sorted(dates, reverse=True)


def test_empty_log_for_new_user(conn):
    user = create_user(conn, "test@example.com", "password123")
    assert get_activity_log(conn, user["id"]) == []


def test_save_returns_count_of_days_written(conn):
    user = create_user(conn, "test@example.com", "password123")
    count = save_activity_log(conn, user["id"], {"2026-01-01": 100.0, "2026-01-02": 200.0, "2026-01-03": 300.0})
    assert count == 3
