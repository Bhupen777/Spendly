"""SMS backends.

Nothing here touches the network — urlopen is replaced in every test that
exercises MSG91.
"""

import io
import json
import urllib.error

import pytest

from auth import sms


@pytest.fixture
def msg91(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "test-auth-key")
    monkeypatch.setenv("MSG91_TEMPLATE_ID", "test-template-id")
    monkeypatch.delenv("MSG91_SENDER", raising=False)
    monkeypatch.delenv("MSG91_OTP_VAR", raising=False)
    return sms.Msg91Backend()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def captured_request(monkeypatch):
    """Capture the outgoing request instead of sending it."""
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({"type": "success", "message": "ok"}).encode())

    monkeypatch.setattr(sms.urllib.request, "urlopen", fake_urlopen)
    return captured


# ------------------------------------------------------------------ #
# Backend selection                                                   #
# ------------------------------------------------------------------ #

def test_backend_defaults_to_console(monkeypatch):
    monkeypatch.delenv("SMS_BACKEND", raising=False)
    assert sms.get_backend().name == "console"


def test_backend_is_selected_by_environment(monkeypatch):
    monkeypatch.setenv("SMS_BACKEND", "msg91")
    assert sms.get_backend().name == "msg91"


def test_unknown_backend_falls_back_to_console(monkeypatch):
    monkeypatch.setenv("SMS_BACKEND", "carrier-pigeon")
    assert sms.get_backend().name == "console"


# ------------------------------------------------------------------ #
# MSG91 payload                                                       #
# ------------------------------------------------------------------ #

def test_payload_carries_template_and_code(msg91):
    payload = msg91.build_payload("+917039291706", "185064")

    assert payload["template_id"] == "test-template-id"
    assert payload["recipients"][0]["OTP"] == "185064"


def test_payload_strips_the_plus_from_the_number(msg91):
    payload = msg91.build_payload("+917039291706", "185064")
    assert payload["recipients"][0]["mobiles"] == "917039291706"


def test_payload_uses_a_custom_variable_name(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "k")
    monkeypatch.setenv("MSG91_TEMPLATE_ID", "t")
    monkeypatch.setenv("MSG91_OTP_VAR", "code")

    payload = sms.Msg91Backend().build_payload("+917039291706", "185064")
    assert payload["recipients"][0]["code"] == "185064"
    assert "OTP" not in payload["recipients"][0]


def test_sender_is_omitted_unless_configured(msg91):
    assert "sender" not in msg91.build_payload("+917039291706", "185064")


def test_sender_is_included_when_configured(monkeypatch):
    monkeypatch.setenv("MSG91_AUTH_KEY", "k")
    monkeypatch.setenv("MSG91_TEMPLATE_ID", "t")
    monkeypatch.setenv("MSG91_SENDER", "SPNDLY")

    assert sms.Msg91Backend().build_payload("+91703929170", "1")["sender"] == "SPNDLY"


# ------------------------------------------------------------------ #
# MSG91 request                                                       #
# ------------------------------------------------------------------ #

def test_send_posts_to_the_flow_endpoint(msg91, captured_request):
    assert msg91.send("+917039291706", "ignored", code="185064") is True

    assert captured_request["method"] == "POST"
    assert "control.msg91.com" in captured_request["url"]
    assert "/flow/" in captured_request["url"]


def test_send_authenticates_with_the_auth_key(msg91, captured_request):
    msg91.send("+917039291706", "ignored", code="185064")
    assert captured_request["headers"]["authkey"] == "test-auth-key"


def test_send_transmits_the_bare_code_not_the_sentence(msg91, captured_request):
    msg91.send("+917039291706", "185064 is your Spendly verification code.", code="185064")

    recipient = captured_request["body"]["recipients"][0]
    assert recipient["OTP"] == "185064"
    assert "verification code" not in json.dumps(captured_request["body"])


def test_send_applies_a_timeout(msg91, captured_request):
    msg91.send("+917039291706", "ignored", code="185064")
    assert captured_request["timeout"] == sms.REQUEST_TIMEOUT


# ------------------------------------------------------------------ #
# MSG91 failure handling                                              #
# ------------------------------------------------------------------ #

def test_send_fails_without_configuration(monkeypatch):
    monkeypatch.delenv("MSG91_AUTH_KEY", raising=False)
    monkeypatch.delenv("MSG91_TEMPLATE_ID", raising=False)

    assert sms.Msg91Backend().send("+917039291706", "x", code="1") is False


def test_send_does_not_call_out_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MSG91_AUTH_KEY", raising=False)
    monkeypatch.delenv("MSG91_TEMPLATE_ID", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("should not have reached the network")

    monkeypatch.setattr(sms.urllib.request, "urlopen", explode)
    assert sms.Msg91Backend().send("+917039291706", "x", code="1") is False


def test_send_reports_a_failure_body_despite_http_200(msg91, monkeypatch):
    def fake_urlopen(request, timeout=None):
        return FakeResponse(
            json.dumps({"type": "error", "message": "invalid template"}).encode()
        )

    monkeypatch.setattr(sms.urllib.request, "urlopen", fake_urlopen)
    assert msg91.send("+917039291706", "x", code="1") is False


def test_send_handles_an_http_error(msg91, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad authkey"}')
        )

    monkeypatch.setattr(sms.urllib.request, "urlopen", fake_urlopen)
    assert msg91.send("+917039291706", "x", code="1") is False


def test_send_handles_an_unreachable_host(msg91, monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(sms.urllib.request, "urlopen", fake_urlopen)
    assert msg91.send("+917039291706", "x", code="1") is False


def test_send_handles_an_unparseable_response(msg91, monkeypatch):
    def fake_urlopen(request, timeout=None):
        return FakeResponse(b"<html>gateway error</html>")

    monkeypatch.setattr(sms.urllib.request, "urlopen", fake_urlopen)
    assert msg91.send("+917039291706", "x", code="1") is False


# ------------------------------------------------------------------ #
# The app surfaces a delivery failure                                 #
# ------------------------------------------------------------------ #

def test_signup_reports_when_delivery_fails(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module.sms, "send_otp", lambda phone, code: False)

    response = client.post(
        "/register/phone", data={"name": "Priya", "phone": "9876543210"}
    )
    # Jinja escapes the apostrophe, so match a stretch without one.
    assert "send a code to that number" in response.get_data(as_text=True)


def test_no_account_is_created_when_delivery_fails(client, monkeypatch, conn):
    import app as app_module

    monkeypatch.setattr(app_module.sms, "send_otp", lambda phone, code: False)
    client.post("/register/phone", data={"name": "Priya", "phone": "9876543210"})

    count = conn.execute(
        "SELECT COUNT(*) c FROM users WHERE phone = '+919876543210'"
    ).fetchone()["c"]
    assert count == 0
