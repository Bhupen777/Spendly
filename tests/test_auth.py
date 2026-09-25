"""Registration, sign-in and sign-out."""

from werkzeug.security import check_password_hash

from tests.conftest import DEMO_EMAIL, DEMO_PASSWORD


# ------------------------------------------------------------------ #
# Registration                                                        #
# ------------------------------------------------------------------ #

def test_register_creates_account_and_signs_in(client, conn):
    response = client.post(
        "/register",
        data={"name": "New Person", "email": "new@example.com", "password": "password123"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Hello, New Person" in response.get_data(as_text=True)

    row = conn.execute(
        "SELECT name, password_hash FROM users WHERE email = 'new@example.com'"
    ).fetchone()
    assert row["name"] == "New Person"


def test_register_hashes_the_password(client, conn):
    client.post(
        "/register",
        data={"name": "Hashed", "email": "hashed@example.com", "password": "password123"},
    )

    stored = conn.execute(
        "SELECT password_hash FROM users WHERE email = 'hashed@example.com'"
    ).fetchone()["password_hash"]

    assert stored != "password123"
    assert check_password_hash(stored, "password123")


def test_register_rejects_duplicate_email(client):
    response = client.post(
        "/register",
        data={"name": "Clash", "email": DEMO_EMAIL, "password": "password123"},
    )
    assert "already exists" in response.get_data(as_text=True)


def test_register_rejects_duplicate_email_in_a_different_case(client, conn):
    client.post(
        "/register",
        data={"name": "Clash", "email": DEMO_EMAIL.upper(), "password": "password123"},
    )
    count = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE email = ?", (DEMO_EMAIL,)
    ).fetchone()["c"]
    assert count == 1


def test_register_rejects_short_password(client):
    response = client.post(
        "/register", data={"name": "Short", "email": "s@example.com", "password": "abc"}
    )
    assert "at least 8 characters" in response.get_data(as_text=True)


def test_register_rejects_missing_name(client):
    response = client.post(
        "/register", data={"name": "  ", "email": "s@example.com", "password": "password123"}
    )
    assert "enter your name" in response.get_data(as_text=True)


def test_register_redirects_when_already_signed_in(auth):
    response = auth.get("/register")
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


# ------------------------------------------------------------------ #
# Login                                                               #
# ------------------------------------------------------------------ #

def test_login_succeeds_with_correct_credentials(client):
    response = client.post(
        "/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_login_is_case_insensitive_on_email(client):
    response = client.post(
        "/login", data={"email": DEMO_EMAIL.upper(), "password": DEMO_PASSWORD}
    )
    assert response.status_code == 302


def test_login_rejects_wrong_password(client):
    response = client.post("/login", data={"email": DEMO_EMAIL, "password": "nope"})
    assert "Incorrect email or password" in response.get_data(as_text=True)


def test_login_does_not_reveal_whether_an_account_exists(client):
    unknown = client.post(
        "/login", data={"email": "nobody@example.com", "password": "whatever"}
    ).get_data(as_text=True)
    wrong_password = client.post(
        "/login", data={"email": DEMO_EMAIL, "password": "wrong"}
    ).get_data(as_text=True)

    assert "Incorrect email or password" in unknown
    assert unknown == wrong_password


def test_login_honours_next_parameter(client):
    response = client.post(
        "/login?next=/profile", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.headers["Location"].endswith("/profile")


def test_login_ignores_offsite_next_parameter(client):
    response = client.post(
        "/login?next=https://evil.example.com",
        data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    assert "evil.example.com" not in response.headers["Location"]


# ------------------------------------------------------------------ #
# Logout                                                              #
# ------------------------------------------------------------------ #

def test_logout_requires_post(auth):
    assert auth.get("/logout").status_code == 405
    # The GET attempt must not have signed them out.
    assert auth.get("/dashboard").status_code == 200


def test_logout_clears_the_session(auth):
    auth.post("/logout")
    assert auth.get("/dashboard").status_code == 302
