"""Dashboard, and the add / edit / delete routes."""

import pytest


# ------------------------------------------------------------------ #
# Dashboard                                                           #
# ------------------------------------------------------------------ #

def test_dashboard_lists_the_users_expenses(auth):
    body = auth.get("/dashboard").get_data(as_text=True)
    assert "Winter jacket" in body
    assert "Electricity" in body


def test_dashboard_shows_only_your_own_expenses(auth, other_user):
    body = auth.get("/dashboard").get_data(as_text=True)
    assert "Private" not in body


def test_dashboard_shows_an_empty_state_for_a_new_account(client):
    client.post(
        "/register",
        data={"name": "Fresh", "email": "fresh@example.com", "password": "password123"},
    )
    body = client.get("/dashboard").get_data(as_text=True)
    assert "No expenses yet" in body


# ------------------------------------------------------------------ #
# Add                                                                 #
# ------------------------------------------------------------------ #

def test_add_expense_persists(auth, conn):
    auth.post(
        "/expenses/add",
        data={
            "amount": "123.45",
            "category_id": "1",
            "spent_on": "2026-09-20",
            "description": "Added by test",
        },
    )

    row = conn.execute(
        "SELECT amount, spent_on FROM expenses WHERE description = 'Added by test'"
    ).fetchone()
    assert row["amount"] == 123.45
    assert row["spent_on"] == "2026-09-20"


def test_add_expense_belongs_to_the_signed_in_user(auth, conn):
    auth.post(
        "/expenses/add",
        data={"amount": "10", "category_id": "1", "spent_on": "2026-09-20", "description": "Mine"},
    )

    owner_email = conn.execute(
        """
        SELECT u.email FROM expenses e
        JOIN users u ON u.id = e.user_id
        WHERE e.description = 'Mine'
        """
    ).fetchone()["email"]
    assert owner_email == "demo@spendly.app"


def test_add_expense_requires_post(auth):
    assert auth.get("/expenses/add").status_code == 405


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("amount", "-5", "greater than zero"),
        ("amount", "0", "greater than zero"),
        ("amount", "abc", "greater than zero"),
        ("spent_on", "", "Choose a date"),
    ],
)
def test_add_expense_rejects_bad_input(auth, conn, field, value, message):
    before = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]

    data = {"amount": "10", "category_id": "1", "spent_on": "2026-09-20"}
    data[field] = value
    response = auth.post("/expenses/add", data=data, follow_redirects=True)

    assert message in response.get_data(as_text=True)
    after = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    assert after == before


# ------------------------------------------------------------------ #
# Edit                                                                #
# ------------------------------------------------------------------ #

def test_edit_form_is_prefilled(auth, demo_expense, conn):
    expected = conn.execute(
        "SELECT amount, spent_on FROM expenses WHERE id = ?", (demo_expense,)
    ).fetchone()

    body = auth.get("/expenses/%d/edit" % demo_expense).get_data(as_text=True)
    assert 'value="%.2f"' % expected["amount"] in body
    assert 'value="%s"' % expected["spent_on"] in body


def test_edit_saves_changes(auth, demo_expense, conn):
    auth.post(
        "/expenses/%d/edit" % demo_expense,
        data={
            "amount": "999.99",
            "category_id": "3",
            "spent_on": "2026-09-11",
            "description": "Edited",
        },
    )

    row = conn.execute(
        "SELECT amount, category_id, spent_on, description FROM expenses WHERE id = ?",
        (demo_expense,),
    ).fetchone()
    assert row["amount"] == 999.99
    assert row["category_id"] == 3
    assert row["spent_on"] == "2026-09-11"
    assert row["description"] == "Edited"


def test_edit_keeps_input_when_validation_fails(auth, demo_expense, conn):
    before = conn.execute(
        "SELECT amount FROM expenses WHERE id = ?", (demo_expense,)
    ).fetchone()["amount"]

    response = auth.post(
        "/expenses/%d/edit" % demo_expense,
        data={
            "amount": "-1",
            "category_id": "2",
            "spent_on": "2026-09-11",
            "description": "Typed text",
        },
    )

    body = response.get_data(as_text=True)
    assert "greater than zero" in body
    assert 'value="Typed text"' in body

    after = conn.execute(
        "SELECT amount FROM expenses WHERE id = ?", (demo_expense,)
    ).fetchone()["amount"]
    assert after == before


def test_edit_rejects_another_users_expense(auth, other_user, conn):
    expense_id = other_user["expense_id"]

    assert auth.get("/expenses/%d/edit" % expense_id).status_code == 404
    assert (
        auth.post(
            "/expenses/%d/edit" % expense_id,
            data={"amount": "1", "category_id": "1", "spent_on": "2026-09-01"},
        ).status_code
        == 404
    )

    unchanged = conn.execute(
        "SELECT amount FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()["amount"]
    assert unchanged == 99.0


# ------------------------------------------------------------------ #
# Delete                                                              #
# ------------------------------------------------------------------ #

def test_delete_requires_post(auth, demo_expense, conn):
    assert auth.get("/expenses/%d/delete" % demo_expense).status_code == 405

    still_there = conn.execute(
        "SELECT COUNT(*) c FROM expenses WHERE id = ?", (demo_expense,)
    ).fetchone()["c"]
    assert still_there == 1


def test_delete_removes_the_row(auth, demo_expense, conn):
    auth.post("/expenses/%d/delete" % demo_expense)

    gone = conn.execute(
        "SELECT COUNT(*) c FROM expenses WHERE id = ?", (demo_expense,)
    ).fetchone()["c"]
    assert gone == 0


def test_delete_rejects_another_users_expense(auth, other_user, conn):
    expense_id = other_user["expense_id"]

    assert auth.post("/expenses/%d/delete" % expense_id).status_code == 404

    survived = conn.execute(
        "SELECT COUNT(*) c FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()["c"]
    assert survived == 1


def test_delete_is_404_for_a_missing_id(auth):
    assert auth.post("/expenses/999999/delete").status_code == 404
