"""
Database layer. A file-based database is the right call here -
this is a personal app, not a multi-server deployment, and SQLite needs
no separate database process to run or manage.

Schema is deliberately set up now to support Phase 2-5 features without
restructuring later: target_history already captures everything the
Phase 3 dashboard (weight trend, target history) will need to read.
"""

import os
import re
import sqlite3
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # SQLite-only setups do not need the PostgreSQL driver
    psycopg = None

DB_PATH = Path(__file__).parent.parent / "data" / "app.db"

# Catch this instead of sqlite3.IntegrityError so both databases are covered.
IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

SQLITE_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS usage_counters (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);
"""

# The same tables for PostgreSQL. Timestamps stay text in the format SQLite produces, and REAL becomes
# DOUBLE PRECISION (PostgreSQL's REAL is only single precision), so both databases return identical values.
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS target_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    weight_kg DOUBLE PRECISION NOT NULL,
    height_cm DOUBLE PRECISION NOT NULL,
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
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS foods (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    calories_per_100g DOUBLE PRECISION NOT NULL,
    protein_per_100g DOUBLE PRECISION NOT NULL,
    carbs_per_100g DOUBLE PRECISION NOT NULL,
    fat_per_100g DOUBLE PRECISION NOT NULL,
    calcium_mg_per_100g DOUBLE PRECISION NOT NULL DEFAULT 0,
    vitamin_c_mg_per_100g DOUBLE PRECISION NOT NULL DEFAULT 0,
    omega3_g_per_100g DOUBLE PRECISION NOT NULL DEFAULT 0,
    meal_category TEXT NOT NULL DEFAULT 'other',
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS plan_meals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan_batch TEXT NOT NULL,
    day_number INTEGER NOT NULL,
    meal_type TEXT NOT NULL,
    food_id INTEGER REFERENCES foods(id),
    food_name TEXT NOT NULL,
    calories DOUBLE PRECISION NOT NULL,
    protein_g DOUBLE PRECISION NOT NULL DEFAULT 0,
    carbs_g DOUBLE PRECISION NOT NULL DEFAULT 0,
    fat_g DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    activity_date TEXT NOT NULL,
    active_calories DOUBLE PRECISION NOT NULL,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    UNIQUE(user_id, activity_date)
);

CREATE TABLE IF NOT EXISTS usage_counters (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);
"""

# Columns added after the original release - ALTER TABLE ADD COLUMN keeps
# existing rows (and existing databases) intact rather than requiring a
# fresh database every time the schema grows. (SQLite only: PostgreSQL databases
# are created with the full schema.)
MIGRATIONS = [
    ("foods", "calcium_mg_per_100g", "REAL NOT NULL DEFAULT 0"),
    ("foods", "vitamin_c_mg_per_100g", "REAL NOT NULL DEFAULT 0"),
    ("foods", "omega3_g_per_100g", "REAL NOT NULL DEFAULT 0"),
    ("foods", "meal_category", "TEXT NOT NULL DEFAULT 'other'"),
]

# Tables whose primary key column is called id, so INSERTs can return the new id on PostgreSQL.
_TABLES_WITH_ID = {"users", "target_history", "foods", "plan_meals", "activity_log"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


class _PgResult:
    """Looks like a sqlite3 cursor: fetchone, fetchall, lastrowid, rowcount."""

    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PgConnection:
    """A PostgreSQL connection that accepts the sqlite3-style SQL used across this app."""

    def __init__(self, dsn: str):
        self._conn = psycopg.connect(dsn, row_factory=dict_row, prepare_threshold=None)  # no server-side prepared statements, so Neon's pooled connection string works too

    def execute(self, sql: str, params=()):
        pg_sql = sql.replace("%", "%%").replace("?", "%s")
        match = _INSERT_RE.match(pg_sql)
        wants_id = bool(match) and match.group(1).lower() in _TABLES_WITH_ID and "RETURNING" not in pg_sql.upper()
        if wants_id:
            pg_sql += " RETURNING id"
        try:
            cursor = self._conn.execute(pg_sql, params)
            lastrowid = cursor.fetchone()["id"] if wants_id else None
        except psycopg.Error:
            self._conn.rollback()  # PostgreSQL refuses further work in a failed transaction
            raise
        return _PgResult(cursor, lastrowid)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def get_connection(db_path: Path = None):
    """db_path is injectable so tests can point at a temp file instead of
    the real database. It is ignored when DATABASE_URL is set."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set but the PostgreSQL driver is missing: pip install 'psycopg[binary]'")
        return PgConnection(database_url)

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
        if isinstance(conn, PgConnection):
            conn.execute(POSTGRES_SCHEMA)
            conn.commit()
        else:
            conn.executescript(SQLITE_SCHEMA)
            conn.commit()
            _run_migrations(conn)
    finally:
        conn.close()
