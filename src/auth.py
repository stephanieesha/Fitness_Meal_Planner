"""
User account logic: creating accounts, verifying login, and saving/reading
target history. Takes a db connection as a parameter throughout rather
than importing a fixed one, so this is testable against a temporary
database instead of the real one.
"""


from werkzeug.security import generate_password_hash, check_password_hash

from db import IntegrityError


class EmailAlreadyExists(Exception):
    pass


class InvalidCredentials(Exception):
    pass


def create_user(conn, email: str, password: str) -> dict:
    password_hash = generate_password_hash(password)
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, password_hash),
        )
        conn.commit()
    except IntegrityError:
        raise EmailAlreadyExists(f"An account with email '{email}' already exists")

    return get_user_by_id(conn, cursor.lastrowid)


def authenticate_user(conn, email: str, password: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        raise InvalidCredentials("Incorrect email or password")
    return dict(row)


def get_user_by_id(conn, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_target_entry(conn, user_id: int, profile_inputs: dict, targets: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO target_history
            (user_id, weight_kg, height_cm, age, sex, activity_level, goal, region,
             bmr, tdee, calorie_target, protein_g, carbs_g, fat_g, floor_applied)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            profile_inputs["weight_kg"], profile_inputs["height_cm"], profile_inputs["age"],
            profile_inputs["sex"], profile_inputs["activity_level"], profile_inputs["goal"],
            profile_inputs["region"],
            targets["bmr"], targets["tdee"], targets["calorie_target"],
            targets["macros"]["protein_g"], targets["macros"]["carbs_g"], targets["macros"]["fat_g"],
            int(targets["floor_applied"]),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_target_history(conn, user_id: int) -> list:
    rows = conn.execute(
        "SELECT * FROM target_history WHERE user_id = ? ORDER BY created_at ASC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]
