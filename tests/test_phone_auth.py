"""Phone number handling, OTP issuing/verifying, and the sign-in flows."""

import re
from datetime import timedelta

import pytest

from auth import otp
from tests.conftest import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PHONE


# ------------------------------------------------------------------ #
# Number parsing                                                      #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "raw",
    [
        "9876543210",
        "+919876543210",
        "919876543210",
        "98765 43210",
        "+91 98765-43210",
        "+91(98765)43210",
        "  9876543210  ",
    ],
)
def test_accepts_the_usual_ways_of_writing_a_number(raw):
    assert otp.normalize_phone(raw) == "+919876543210"


@pytest.mark.parametrize(
    "raw",
    [
        "1234567890",   # doesn't start 6-9
        "5876543210",   # landline-style leading digit
        "987654321",    # too short
        "98765432101",  # too long
        "abcdefghij",
        "+1 415 555 0123",  # not Indian
        "",
        None,
    ],
)
def test_rejects_anything_that_is_not_an_indian_mobile(raw):
    assert otp.normalize_phone(raw) is None


def test_masking_hides_the_middle(app):
    masked = otp.mask_phone("+919876543210")
    assert "98" in masked and "210" in masked
    assert "76543" not in masked


# ------------------------------------------------------------------ #
# Issuing                                                             #
# ------------------------------------------------------------------ #

def test_issued_code_is_six_digits(app):
    with app.app_context():
        code, error = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)

    assert error is None
    assert re.fullmatch(r"\d{6}", code)


def test_code_is_stored_hashed(app, conn):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)

    stored = conn.execute(
        "SELECT code_hash FROM otp_codes ORDER BY id DESC LIMIT 1"
    ).fetchone()["code_hash"]

    assert code not in stored
    assert stored != code


def test_resend_is_rate_limited(app):
    with app.app_context():
        otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)
        code, error = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)

    assert code is None
    assert "wait" in error.lower()


def test_hourly_cap_is_enforced(app, no_cooldown):
    with app.app_context():
        for _ in range(otp.MAX_PER_HOUR):
            code, error = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)
            assert error is None

        code, error = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)

    assert code is None
    assert "Too many codes" in error


# ------------------------------------------------------------------ #
# Verifying                                                           #
# ------------------------------------------------------------------ #

def test_correct_code_verifies(app):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)
        row, error = otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, code)

    assert error is None
    assert row is not None


def test_code_cannot_be_reused(app):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)
        otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, code)
        row, error = otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, code)

    assert row is None
    assert error is not None


def test_wrong_code_is_rejected(app):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)
        wrong = "000000" if code != "000000" else "111111"
        row, error = otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, wrong)

    assert row is None
    assert "incorrect or has expired" in error


def test_expired_code_is_rejected(app, monkeypatch):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)

        # Jump past the five-minute window.
        real_now = otp._now()
        monkeypatch.setattr(otp, "_now", lambda: real_now + timedelta(minutes=6))

        row, error = otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, code)

    assert row is None
    assert "incorrect or has expired" in error


def test_guesses_are_capped(app):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_LOGIN)
        wrong = "000000" if code != "000000" else "111111"

        for _ in range(otp.MAX_ATTEMPTS):
            otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, wrong)

        # Even the right code is refused once the cap is hit.
        row, error = otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, code)

    assert row is None
    assert "Too many incorrect attempts" in error


def test_a_code_is_scoped_to_its_purpose(app):
    with app.app_context():
        code, _ = otp.issue(DEMO_PHONE, otp.PURPOSE_REGISTER, "Someone")
        row, error = otp.verify(DEMO_PHONE, otp.PURPOSE_LOGIN, code)

    assert row is None


# ------------------------------------------------------------------ #
# Sign-up flow                                                        #
# ------------------------------------------------------------------ #

def test_phone_signup_creates_an_account(client, captured_codes, conn):
    client.post("/register/phone", data={"name": "Priya", "phone": "9876543210"})
    assert captured_codes, "no code was sent"

    client.post("/verify", data={"code": captured_codes[0]["code"]})

    row = conn.execute(
        "SELECT name, email, password_hash FROM users WHERE phone = '+919876543210'"
    ).fetchone()
    assert row["name"] == "Priya"
    assert row["email"] is None
    assert row["password_hash"] is None


def test_phone_signup_signs_you_in(client, captured_codes):
    client.post("/register/phone", data={"name": "Priya", "phone": "9876543210"})
    client.post("/verify", data={"code": captured_codes[0]["code"]})

    assert client.get("/dashboard").status_code == 200


def test_phone_signup_rejects_a_bad_number(client, captured_codes):
    response = client.post(
        "/register/phone", data={"name": "Priya", "phone": "12345"}
    )
    assert "valid Indian mobile number" in response.get_data(as_text=True)
    assert captured_codes == []


def test_phone_signup_requires_a_name(client, captured_codes):
    response = client.post(
        "/register/phone", data={"name": "  ", "phone": "9876543210"}
    )
    assert "enter your name" in response.get_data(as_text=True)
    assert captured_codes == []


def test_phone_signup_rejects_a_number_already_registered(client, phone_user, captured_codes):
    response = client.post(
        "/register/phone", data={"name": "Impostor", "phone": DEMO_PHONE}
    )
    assert "already has an account" in response.get_data(as_text=True)
    assert captured_codes == []


# ------------------------------------------------------------------ #
# Sign-in flow                                                        #
# ------------------------------------------------------------------ #

def test_phone_login_signs_in_an_existing_account(client, phone_user, captured_codes):
    client.post("/login/phone", data={"phone": DEMO_PHONE})
    client.post("/verify", data={"code": captured_codes[0]["code"]})

    assert client.get("/dashboard").status_code == 200


def test_phone_login_does_not_reveal_unregistered_numbers(client, captured_codes):
    response = client.post("/login/phone", data={"phone": "9999900001"})

    # Same next step as a real number...
    assert response.status_code == 302
    assert "/verify" in response.headers["Location"]
    # ...but nothing was actually sent.
    assert captured_codes == []


def test_verify_requires_a_started_flow(client):
    response = client.get("/verify")
    assert response.status_code == 302
    assert "/login/phone" in response.headers["Location"]


def test_resend_issues_a_new_code(client, phone_user, captured_codes, no_cooldown):
    client.post("/login/phone", data={"phone": DEMO_PHONE})
    client.post("/verify/resend")

    assert len(captured_codes) == 2
    assert captured_codes[0]["code"] != captured_codes[1]["code"]

    # The newest code is the one that works.
    client.post("/verify", data={"code": captured_codes[1]["code"]})
    assert client.get("/dashboard").status_code == 200


def test_resend_keeps_the_pending_name(client, captured_codes, conn, no_cooldown):
    client.post("/register/phone", data={"name": "Priya", "phone": "9876543210"})
    client.post("/verify/resend")
    client.post("/verify", data={"code": captured_codes[-1]["code"]})

    row = conn.execute(
        "SELECT name FROM users WHERE phone = '+919876543210'"
    ).fetchone()
    assert row is not None and row["name"] == "Priya"


# ------------------------------------------------------------------ #
# Linking a number to an existing account                             #
# ------------------------------------------------------------------ #

def test_linking_a_number_to_an_email_account(auth, captured_codes, conn):
    auth.post("/profile/phone", data={"phone": "9876543210"})
    auth.post("/verify", data={"code": captured_codes[0]["code"]})

    row = conn.execute("SELECT phone FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    assert row["phone"] == "+919876543210"


def test_linking_keeps_you_signed_in(auth, captured_codes):
    auth.post("/profile/phone", data={"phone": "9876543210"})
    auth.post("/verify", data={"code": captured_codes[0]["code"]})

    assert auth.get("/dashboard").status_code == 200


def test_cannot_link_a_number_another_account_uses(auth, phone_user, captured_codes):
    response = auth.post("/profile/phone", data={"phone": DEMO_PHONE}, follow_redirects=True)

    assert "already linked to another account" in response.get_data(as_text=True)
    assert captured_codes == []


def test_linking_requires_sign_in(client, captured_codes):
    assert client.post("/profile/phone", data={"phone": "9876543210"}).status_code == 302
    assert captured_codes == []


# ------------------------------------------------------------------ #
# Email sign-in still works                                           #
# ------------------------------------------------------------------ #

def test_email_login_is_unaffected(client):
    response = client.post(
        "/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 302


def test_phone_only_account_can_set_a_password(client, captured_codes, conn):
    client.post("/register/phone", data={"name": "Priya", "phone": "9876543210"})
    client.post("/verify", data={"code": captured_codes[0]["code"]})

    client.post(
        "/profile/password",
        data={"new_password": "brandnew123", "confirm_password": "brandnew123"},
    )

    from werkzeug.security import check_password_hash

    stored = conn.execute(
        "SELECT password_hash FROM users WHERE phone = '+919876543210'"
    ).fetchone()["password_hash"]
    assert stored is not None and check_password_hash(stored, "brandnew123")
