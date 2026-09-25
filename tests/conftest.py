"""
When DATABASE_URL points at PostgreSQL, start every test from empty tables, so the same
tests run against both databases:  DATABASE_URL=postgresql://... pytest tests
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def clean_postgres_tables():
    if not os.environ.get("DATABASE_URL"):
        yield
        return
    from db import get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        conn.execute("TRUNCATE day_log, plan_meals, activity_log, foods, target_history, users, usage_counters RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        conn.close()
    yield
