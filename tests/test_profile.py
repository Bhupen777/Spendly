"""Profile page, detail updates and password changes."""

from werkzeug.security import check_password_hash

from tests.conftest import DEMO_EMAIL, DEMO_PASSWORD


def test_profile_shows_account_details(auth):
    body = auth.get("/profile").get_data(as_text=True)
    assert "Demo User" in body
    assert DEMO_EMAIL in body


def test_profile_counts_only_your_own_expenses(auth, other_user):
    body = auth.get("/profile").get_data(as_text=True)
    # 14 seeded expenses belong to the demo user; Mallory's must not be counted.
    assert ">14<" in body.replace(" ", "").replace("\n", "")


# ------------------------------------------------------------------ #
# Details                                                             #
# ------------------------------------------------------------------ #

def test_update_details_saves(auth, conn):
    auth.post(
        "/profile/details", data={"name": "Renamed", "email": "renamed@example.com"}
    )

    row = conn.execute(
        "SELECT name, email FROM users WHERE id = 1"
    ).fetchone()
    assert row["name"] == "Renamed"
    assert row["email"] == "renamed@example.com"


def test_update_details_allows_keeping_the_same_email(auth, conn):
    response = auth.post(
        "/profile/details", data={"name": "Same Email", "email": DEMO_EMAIL},
        follow_redirects=True,
    )

    assert "already used" not in response.get_data(as_text=True)
    assert conn.execute("SELECT name FROM users WHERE id = 1").fetchone()["name"] == "Same Email"


def test_update_details_rejects_another_users_email(auth, other_user, conn):
    response = auth.post(
        "/profile/details", data={"name": "Thief", "email": "mallory@example.com"},
        follow_redirects=True,
    )

    assert "already used by another account" in response.get_data(as_text=True)
    assert conn.execute("SELECT email FROM users WHERE id = 1").fetchone()["email"] == DEMO_EMAIL


def test_update_details_rejects_empty_name(auth, conn):
    response = auth.post(
        "/profile/details", data={"name": "   ", "email": DEMO_EMAIL},
        follow_redirects=True,
    )

    assert "enter your name" in response.get_data(as_text=True)
    assert conn.execute("SELECT name FROM users WHERE id = 1").fetchone()["name"] == "Demo User"


# ------------------------------------------------------------------ #
# Password                                                            #
# ------------------------------------------------------------------ #

def test_change_password_updates_the_hash(auth, conn):
    auth.post(
        "/profile/password",
        data={
            "current_password": DEMO_PASSWORD,
            "new_password": "brandnew123",
            "confirm_password": "brandnew123",
        },
    )

    stored = conn.execute(
        "SELECT password_hash FROM users WHERE id = 1"
    ).fetchone()["password_hash"]

    assert check_password_hash(stored, "brandnew123")
    assert not check_password_hash(stored, DEMO_PASSWORD)


def test_change_password_lets_you_sign_in_with_the_new_one(auth, client):
    auth.post(
        "/profile/password",
        data={
            "current_password": DEMO_PASSWORD,
            "new_password": "brandnew123",
            "confirm_password": "brandnew123",
        },
    )

    fresh = client
    assert fresh.post(
        "/login", data={"email": DEMO_EMAIL, "password": "brandnew123"}
    ).status_code == 302


def test_change_password_rejects_wrong_current(auth, conn):
    response = auth.post(
        "/profile/password",
        data={
            "current_password": "not-it",
            "new_password": "brandnew123",
            "confirm_password": "brandnew123",
        },
        follow_redirects=True,
    )

    assert "current password is incorrect" in response.get_data(as_text=True)
    stored = conn.execute("SELECT password_hash FROM users WHERE id = 1").fetchone()["password_hash"]
    assert check_password_hash(stored, DEMO_PASSWORD)


def test_change_password_rejects_short_new_password(auth):
    response = auth.post(
        "/profile/password",
        data={
            "current_password": DEMO_PASSWORD,
            "new_password": "short",
            "confirm_password": "short",
        },
        follow_redirects=True,
    )
    assert "at least 8 characters" in response.get_data(as_text=True)


def test_change_password_rejects_mismatched_confirmation(auth):
    response = auth.post(
        "/profile/password",
        data={
            "current_password": DEMO_PASSWORD,
            "new_password": "brandnew123",
            "confirm_password": "different123",
        },
        follow_redirects=True,
    )
    assert "do not match" in response.get_data(as_text=True)
