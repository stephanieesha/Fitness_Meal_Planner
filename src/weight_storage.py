"""
Weight tracking: one entry per user per calendar date. Logging the same
date twice overwrites that day's entry rather than creating a duplicate,
so correcting a mis-entered weight is just logging it again.
"""

import re
from datetime import date, datetime, timedelta, timezone

MIN_WEIGHT_KG = 20
MAX_WEIGHT_KG = 500
EARLIEST_LOGGED_DATE = date(1900, 1, 1)


class InvalidWeightEntry(Exception):
    pass


def validate_weight_entry(data, today: date = None) -> tuple:
    """Check a posted weight entry and return (weight_kg, logged_date).

    The weight is rounded to 0.1 kg and the date comes back as YYYY-MM-DD.
    Raises InvalidWeightEntry with a message the page can show as it is.
    """
    if not isinstance(data, dict):
        raise InvalidWeightEntry("Send a JSON object with weight_kg and logged_date")

    raw_date = data.get("logged_date")
    date_str = raw_date.strip() if isinstance(raw_date, str) else ""
    if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", date_str):
        raise InvalidWeightEntry("logged_date must be in YYYY-MM-DD format")
    try:
        logged_on = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise InvalidWeightEntry("logged_date must be a real calendar date")
    if logged_on < EARLIEST_LOGGED_DATE:
        raise InvalidWeightEntry(f"logged_date must be {EARLIEST_LOGGED_DATE.isoformat()} or later")
    # Someone ahead of UTC can already be on tomorrow's date, so allow one day of slack.
    if logged_on > (today or datetime.now(timezone.utc).date()) + timedelta(days=1):
        raise InvalidWeightEntry("logged_date cannot be in the future")

    raw_weight = data.get("weight_kg")
    if isinstance(raw_weight, bool):
        raise InvalidWeightEntry("weight_kg must be a number")
    try:
        weight_kg = float(raw_weight)
    except (TypeError, ValueError, OverflowError):
        raise InvalidWeightEntry("weight_kg must be a number")
    # NaN and infinity fail this comparison too.
    if not (MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG):
        raise InvalidWeightEntry(f"weight_kg must be a realistic value ({MIN_WEIGHT_KG}-{MAX_WEIGHT_KG})")

    return round(weight_kg, 1), logged_on.isoformat()


def save_weight_entry(conn, user_id: int, weight_kg: float, logged_date: str) -> dict:
    existing = conn.execute(
        "SELECT id FROM weight_log WHERE user_id = ? AND logged_date = ?",
        (user_id, logged_date),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE weight_log SET weight_kg = ? WHERE id = ?",
            (weight_kg, existing["id"]),
        )
        conn.commit()
        entry_id = existing["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO weight_log (user_id, weight_kg, logged_date) VALUES (?, ?, ?)",
            (user_id, weight_kg, logged_date),
        )
        conn.commit()
        entry_id = cursor.lastrowid

    return {"id": entry_id, "weight_kg": weight_kg, "logged_date": logged_date}


def get_weight_history(conn, user_id: int) -> list:
    rows = conn.execute(
        "SELECT id, weight_kg, logged_date FROM weight_log WHERE user_id = ? ORDER BY logged_date ASC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_latest_weight(conn, user_id: int) -> dict:
    row = conn.execute(
        "SELECT id, weight_kg, logged_date FROM weight_log WHERE user_id = ? ORDER BY logged_date DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_weight_entry(conn, user_id: int, entry_id: int) -> bool:
    conn.execute(
        "DELETE FROM weight_log WHERE id = ? AND user_id = ?",
        (entry_id, user_id),
    )
    conn.commit()
    return True
