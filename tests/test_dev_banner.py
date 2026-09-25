"""The development-only OTP banner.

Its whole risk is showing up where it shouldn't, so most of these assert
that it stays hidden.
"""

import pytest

import app as app_module
from auth import sms


@pytest.fixture
def debug_client(app, monkeypatch):
    """Debug on, console backend — the only combination that shows the code."""
    monkeypatch.setattr(app, "debug", True)
    monkeypatch.setenv("SMS_BACKEND", "console")
    return app.test_client()


def _start_signup(client):
    return client.post(
        "/register/phone", data={"name": "Priya", "phone": "9876543210"}
    )


def test_banner_shows_the_code_in_development(debug_client):
    _start_signup(debug_client)
    body = debug_client.get("/verify").get_data(as_text=True)

    assert "Dev only" in body
    assert "dev-banner-code" in body


def test_the_shown_code_actually_works(debug_client, conn):
    import re

    _start_signup(debug_client)
    body = debug_client.get("/verify").get_data(as_text=True)
    code = re.search(r'dev-banner-code">(\d{6})<', body).group(1)

    debug_client.post("/verify", data={"code": code})
    assert debug_client.get("/dashboard").status_code == 200


def test_banner_is_hidden_when_debug_is_off(app, monkeypatch):
    monkeypatch.setattr(app, "debug", False)
    monkeypatch.setenv("SMS_BACKEND", "console")
    client = app.test_client()

    _start_signup(client)
    assert "Dev only" not in client.get("/verify").get_data(as_text=True)


def test_banner_is_hidden_when_a_gateway_is_configured(app, monkeypatch):
    # Debug on, but messages are really being sent — the code must not show.
    monkeypatch.setattr(app, "debug", True)
    monkeypatch.setenv("SMS_BACKEND", "msg91")
    monkeypatch.setenv("MSG91_AUTH_KEY", "k")
    monkeypatch.setenv("MSG91_TEMPLATE_ID", "t")
    monkeypatch.setattr(app_module.sms, "send_otp", lambda phone, code: True)

    client = app.test_client()
    _start_signup(client)

    assert "Dev only" not in client.get("/verify").get_data(as_text=True)


def test_banner_is_hidden_in_the_default_test_configuration(client):
    # SMS_BACKEND is null in conftest, so even here it stays off.
    _start_signup(client)
    assert "Dev only" not in client.get("/verify").get_data(as_text=True)


def test_no_stale_code_for_an_unregistered_number(debug_client):
    # Start a real flow so a code lands in the session...
    _start_signup(debug_client)
    assert "Dev only" in debug_client.get("/verify").get_data(as_text=True)

    # ...then ask for one for a number with no account. Nothing is sent, so
    # the previous code must not still be on display.
    debug_client.post("/login/phone", data={"phone": "9999900001"})
    body = debug_client.get("/verify").get_data(as_text=True)

    assert "Dev only" not in body


def test_code_does_not_linger_after_signing_in(debug_client):
    import re

    _start_signup(debug_client)
    body = debug_client.get("/verify").get_data(as_text=True)
    code = re.search(r'dev-banner-code">(\d{6})<', body).group(1)
    debug_client.post("/verify", data={"code": code})

    with debug_client.session_transaction() as session:
        assert "dev_otp" not in session
