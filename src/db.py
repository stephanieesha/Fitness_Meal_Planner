"""
SQLite database layer. A file-based database is the right call here -
this is a personal app, not a multi-server deployment, and SQLite needs
no separate database process to run or manage.

Schema is deliberately set up now to support Phase 2-5 features without
restructuring later: target_history already captures everything the
Phase 3 dashboard (weight trend, target history) will need to read.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS target_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    weight_kg REAL NOT NULL,
    height_cm REAL NOT NULL,
    age INTEGER NOT NULL,
    sex TEXT NOT NULL,
    activity_level TEXT NOT NULL,
    goal TEXT NOT NULL,
    region TEXT NOT NULL,
    bmr INTEGER NOT NULL,
    tdee INTEGER NOT NULL,
    calorie_target INTEGER NOT NULL,
    protein_g INTEGER NOT NULL,
    carbs_g INTEGER NOT NULL,
    fat_g INTEGER NOT NULL,
    floor_applied INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    calories_per_100g REAL NOT NULL,
    protein_per_100g REAL NOT NULL,
    carbs_per_100g REAL NOT NULL,
    fat_per_100g REAL NOT NULL,
    calcium_mg_per_100g REAL NOT NULL DEFAULT 0,
    vitamin_c_mg_per_100g REAL NOT NULL DEFAULT 0,
    omega3_g_per_100g REAL NOT NULL DEFAULT 0,
    meal_category TEXT NOT NULL DEFAULT 'other',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan_batch TEXT NOT NULL,
    day_number INTEGER NOT NULL,
    meal_type TEXT NOT NULL,
    food_id INTEGER REFERENCES foods(id),
    food_name TEXT NOT NULL,
    calories REAL NOT NULL,
    protein_g REAL NOT NULL DEFAULT 0,
    carbs_g REAL NOT NULL DEFAULT 0,
    fat_g REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    activity_date TEXT NOT NULL,
    active_calories REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, activity_date)
);
"""

# Columns added after the original release - ALTER TABLE ADD COLUMN keeps
# existing rows (and existing databases) intact rather than requiring a
# fresh database every time the schema grows.
MIGRATIONS = [
    ("foods", "calcium_mg_per_100g", "REAL NOT NULL DEFAULT 0"),
    ("foods", "vitamin_c_mg_per_100g", "REAL NOT NULL DEFAULT 0"),
    ("foods", "omega3_g_per_100g", "REAL NOT NULL DEFAULT 0"),
    ("foods", "meal_category", "TEXT NOT NULL DEFAULT 'other'"),
]


def get_connection(db_path: Path = None) -> sqlite3.Connection:
    """db_path is injectable so tests can point at a temp file instead of
    the real database."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, column, coltype in MIGRATIONS:
        existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()


def init_db(db_path: Path = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _run_migrations(conn)
    finally:
        conn.close()
