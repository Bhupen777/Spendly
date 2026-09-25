"""The data layer: schema, connection settings, seeding, constraints."""

import sqlite3

import pytest

from database import db as db_module


def test_creates_expected_tables(conn):
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert {"users", "categories", "expenses"} <= names


def test_connection_enables_foreign_keys(conn):
    # Off by default in SQLite and scoped per connection, so without this
    # ON DELETE CASCADE is silently ignored.
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_rows_are_mappings(conn):
    row = conn.execute("SELECT 1 AS value").fetchone()
    assert row["value"] == 1


def test_seed_inserts_data(conn):
    assert conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] >= 1
    assert conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"] == 7
    assert conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"] == 14


def test_init_and_seed_are_idempotent(app, conn):
    before = {
        table: conn.execute("SELECT COUNT(*) c FROM " + table).fetchone()["c"]
        for table in ("users", "categories", "expenses")
    }

    db_module.init_db()
    db_module.seed_db()

    after = {
        table: conn.execute("SELECT COUNT(*) c FROM " + table).fetchone()["c"]
        for table in ("users", "categories", "expenses")
    }
    assert before == after


def test_email_uniqueness_is_case_insensitive(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Clash", "DEMO@SPENDLY.APP", "hash"),
        )


def test_amount_must_be_positive(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO expenses (user_id, category_id, amount, spent_on)
            VALUES (1, 1, -5, '2026-09-01')
            """
        )


def test_expense_requires_a_real_user(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO expenses (user_id, category_id, amount, spent_on)
            VALUES (9999, 1, 10, '2026-09-01')
            """
        )


def test_deleting_a_user_removes_their_expenses(conn, other_user):
    conn.execute("DELETE FROM users WHERE id = ?", (other_user["id"],))
    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) c FROM expenses WHERE user_id = ?", (other_user["id"],)
    ).fetchone()["c"]
    assert remaining == 0


def test_in_request_connection_is_reused(app):
    from flask import g

    with app.test_request_context("/"):
        first = db_module.get_db()
        assert db_module.get_db() is first
        assert "db" in g


def test_connection_is_closed_on_teardown(app):
    # close_db is wired to teardown_appcontext, so the connection outlives the
    # request context and dies with the app context.
    with app.app_context():
        connection = db_module.get_db()

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
