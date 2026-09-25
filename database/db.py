"""SQLite access layer for Spendly.

Public API
----------
get_db()   — a connection with row_factory and foreign keys enabled
init_db()  — creates all tables (safe to run repeatedly)
seed_db()  — inserts sample data for development

Run both directly with:  python -m database.db
"""

import os
import sqlite3
from datetime import date, timedelta

from flask import current_app, g, has_app_context
from werkzeug.security import generate_password_hash


# The project root — one level up from this package.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "expense_tracker.db")


SCHEMA = """
-- email/password and phone are both optional individually, because an
-- account can be created either way — but every account needs at least one
-- of them, which the CHECK enforces.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT COLLATE NOCASE UNIQUE,
    password_hash TEXT,
    phone         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    amount      REAL    NOT NULL CHECK (amount > 0),
    description TEXT,
    spent_on    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (user_id)     REFERENCES users (id)      ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE RESTRICT
);

-- Every expense list is "this user, this date range", so index that pair.
CREATE INDEX IF NOT EXISTS idx_expenses_user_date
    ON expenses (user_id, spent_on);

-- One-time passcodes for phone sign-in. Codes are stored hashed, never in
-- plain text, and rows are kept after use so resend and rate limits can
-- count recent activity.
CREATE TABLE IF NOT EXISTS otp_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT    NOT NULL,
    code_hash   TEXT    NOT NULL,
    purpose     TEXT    NOT NULL,
    pending_name TEXT,
    expires_at  TEXT    NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    consumed_at TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_otp_phone_created
    ON otp_codes (phone, created_at);
"""


# The users table shipped with email and password_hash as NOT NULL. Phone
# sign-up fills in neither, and SQLite cannot relax a constraint in place, so
# an existing database needs the table rebuilt.
USERS_REBUILD = """
CREATE TABLE users_rebuilt (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT COLLATE NOCASE UNIQUE,
    password_hash TEXT,
    phone         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

INSERT INTO users_rebuilt (id, name, email, password_hash, phone, created_at)
    SELECT id, name, email, password_hash, NULL, created_at FROM users;

DROP TABLE users;

ALTER TABLE users_rebuilt RENAME TO users;
"""


DEFAULT_CATEGORIES = [
    "Bills",
    "Food",
    "Health",
    "Transport",
    "Shopping",
    "Entertainment",
    "Other",
]


# ------------------------------------------------------------------ #
# Connection                                                          #
# ------------------------------------------------------------------ #

def _connect():
    """Open a new connection with the settings the whole app relies on."""
    conn = sqlite3.connect(DB_PATH)

    # Rows behave like dicts: row["amount"] instead of row[3].
    conn.row_factory = sqlite3.Row

    # Off by default in SQLite — without this, ON DELETE CASCADE is ignored.
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def get_db():
    """Return the connection for this request, opening one if needed.

    Inside a Flask request the connection is cached on ``g`` and closed by
    ``close_db`` when the request ends. Outside one (scripts, tests) a plain
    connection is returned and the caller is responsible for closing it.
    """
    if not has_app_context():
        return _connect()

    if "db" not in g:
        g.db = _connect()

    return g.db


def close_db(exception=None):
    """Close the request-scoped connection, if one was opened."""
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_app(app):
    """Wire ``close_db`` into the app's teardown so connections don't leak."""
    app.teardown_appcontext(close_db)


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #

def init_db():
    """Create every table and index. Safe to call on an existing database."""
    conn = _connect()

    try:
        conn.executescript(SCHEMA)
        _migrate_users(conn)

        # A partial index keeps the numbers that do exist unique while letting
        # any number of accounts have none.
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone
                ON users (phone) WHERE phone IS NOT NULL
            """
        )

        conn.commit()
    finally:
        conn.close()


def _migrate_users(conn):
    """Bring an older users table up to the current shape."""
    columns = {
        row["name"]: row for row in conn.execute("PRAGMA table_info(users)")
    }

    if "phone" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        columns = {
            row["name"]: row for row in conn.execute("PRAGMA table_info(users)")
        }

    # notnull on email means this database predates phone sign-up.
    if not columns["email"]["notnull"]:
        return

    # SQLite's documented rebuild: foreign keys off, or dropping users would
    # cascade every expense away with it.
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(USERS_REBUILD)
        conn.commit()

        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                "users rebuild left dangling references: {}".format(broken)
            )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# ------------------------------------------------------------------ #
# Sample data                                                         #
# ------------------------------------------------------------------ #

def seed_db():
    """Insert development data: default categories, a demo user, expenses.

    Categories are inserted if missing. The demo user and their expenses are
    only created when that user does not already exist, so re-running this
    will not pile up duplicates.
    """
    conn = _connect()

    try:
        conn.executemany(
            "INSERT OR IGNORE INTO categories (name) VALUES (?)",
            [(name,) for name in DEFAULT_CATEGORIES],
        )

        demo_email = "demo@spendly.app"
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (demo_email,)
        ).fetchone()

        if existing is not None:
            conn.commit()
            return

        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", demo_email, generate_password_hash("spendly123")),
        )
        user_id = cursor.lastrowid

        categories = {
            row["name"]: row["id"]
            for row in conn.execute("SELECT id, name FROM categories")
        }

        today = date.today()

        # (days ago, category, amount, description)
        sample = [
            (1,   "Food",          320.00, "Groceries"),
            (2,   "Transport",     145.50, "Cab to office"),
            (4,   "Bills",        1899.00, "Electricity"),
            (6,   "Food",          480.00, "Dinner out"),
            (9,   "Health",       1250.00, "Pharmacy"),
            (12,  "Shopping",     2340.00, "Winter jacket"),
            (15,  "Bills",         799.00, "Broadband"),
            (18,  "Transport",     260.00, "Metro card top-up"),
            (21,  "Entertainment", 599.00, "Cinema tickets"),
            (24,  "Food",          275.00, "Groceries"),
            (30,  "Bills",        1802.00, "Rent share"),
            (35,  "Health",        800.00, "Doctor visit"),
            (41,  "Food",          410.00, "Groceries"),
            (48,  "Other",         150.00, "Stationery"),
        ]

        conn.executemany(
            """
            INSERT INTO expenses (user_id, category_id, amount, description, spent_on)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    user_id,
                    categories[category],
                    amount,
                    description,
                    (today - timedelta(days=days_ago)).isoformat(),
                )
                for days_ago, category, amount, description in sample
            ],
        )

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    seed_db()
    print("Database ready at {}".format(DB_PATH))
