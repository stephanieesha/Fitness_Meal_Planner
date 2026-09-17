"""
Stores parsed Apple Health activity data (daily active calories) per
user. Re-uploading an export with overlapping dates updates those days'
totals rather than creating duplicates.
"""

import sqlite3


def save_activity_log(conn: sqlite3.Connection, user_id: int, daily_totals: dict) -> int:
    for date_str, calories in daily_totals.items():
        conn.execute(
            """
            INSERT INTO activity_log (user_id, activity_date, active_calories)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, activity_date)
            DO UPDATE SET active_calories = excluded.active_calories
            """,
            (user_id, date_str, calories),
        )
    conn.commit()
    return len(daily_totals)


def get_activity_log(conn: sqlite3.Connection, user_id: int, limit: int = 90) -> list:
    rows = conn.execute(
        "SELECT activity_date, active_calories FROM activity_log WHERE user_id = ? ORDER BY activity_date DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
