"""
Weight tracking: one entry per user per calendar date. Logging the same
date twice overwrites that day's entry rather than creating a duplicate,
so correcting a mis-entered weight is just logging it again.
"""


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
