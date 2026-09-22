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
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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
        conn.commit()
    finally:
        conn.close()


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
