"""Shared fixtures.

Every test runs against a throwaway SQLite file in a tmp directory, so the
real expense_tracker.db is never opened, written to, or read.
"""

import os

import pytest

# app.py raises at import if this is missing, and CI has no .env.
os.environ.setdefault("SECRET_KEY", "test-key-never-used-outside-tests")
# Tests must never try to deliver anything.
os.environ["SMS_BACKEND"] = "null"

import app as app_module  # noqa: E402
from auth import otp as otp_module  # noqa: E402
from database import db as db_module  # noqa: E402


DEMO_EMAIL = "demo@spendly.app"
DEMO_PASSWORD = "spendly123"
DEMO_PHONE = "+919876500001"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The Flask app, pointed at a fresh seeded database."""
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))

    db_module.init_db()
    db_module.seed_db()

    flask_app = app_module.app
    monkeypatch.setitem(flask_app.config, "TESTING", True)
    # Most tests are about behaviour, not tokens; test_security.py turns this
    # back on to check the protection itself.
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", False)

    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth(client):
    """A client already signed in as the demo user."""
    client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    return client


@pytest.fixture
def conn(app):
    """A direct connection, for asserting on what actually landed on disk."""
    connection = db_module._connect()
    yield connection
    connection.close()


@pytest.fixture
def other_user(conn):
    """A second account with one expense, for ownership checks."""
    from werkzeug.security import generate_password_hash

    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Mallory", "mallory@example.com", generate_password_hash("password123")),
    )
    user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'mallory@example.com'"
    ).fetchone()["id"]

    cursor = conn.execute(
        """
        INSERT INTO expenses (user_id, category_id, amount, description, spent_on)
        VALUES (?, 1, 99.0, 'Private', '2026-09-01')
        """,
        (user_id,),
    )
    conn.commit()

    return {"id": user_id, "expense_id": cursor.lastrowid}


@pytest.fixture
def captured_codes(monkeypatch):
    """Intercept outgoing codes so tests can read what was sent."""
    sent = []

    def fake_send(phone, code):
        sent.append({"phone": phone, "code": code})
        return True

    monkeypatch.setattr(app_module.sms, "send_otp", fake_send)
    return sent


@pytest.fixture
def no_cooldown(monkeypatch):
    """Drop the resend cooldown, for tests issuing several codes in a row."""
    from datetime import timedelta

    monkeypatch.setattr(otp_module, "RESEND_COOLDOWN", timedelta(seconds=0))


@pytest.fixture
def phone_user(conn):
    """An account that signs in by phone only — no email, no password."""
    conn.execute(
        "INSERT INTO users (name, phone) VALUES (?, ?)", ("Phone Person", DEMO_PHONE)
    )
    conn.commit()

    return conn.execute(
        "SELECT id, name, phone FROM users WHERE phone = ?", (DEMO_PHONE,)
    ).fetchone()["id"]


@pytest.fixture
def demo_expense(conn):
    """One of the demo user's expense ids."""
    return conn.execute(
        """
        SELECT e.id FROM expenses e
        JOIN users u ON u.id = e.user_id
        WHERE u.email = ?
        ORDER BY e.id
        LIMIT 1
        """,
        (DEMO_EMAIL,),
    ).fetchone()["id"]
