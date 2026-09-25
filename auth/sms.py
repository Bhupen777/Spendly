"""Delivery of one-time passcodes.

Pick a backend with the ``SMS_BACKEND`` environment variable. The default
logs the code rather than sending it, which is fine locally and unusable
anywhere else. Add a provider by writing a class with a ``send`` method and
registering it in ``BACKENDS``.
"""

import json
import logging
import os
import urllib.error
import urllib.request


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds


class ConsoleBackend:
    """Logs the code. Development only — anyone reading the log can sign in."""

    name = "console"

    def send(self, phone, message, code=None):
        logger.warning("[SMS -> %s] %s", phone, message)
        print("\n  [SMS -> {}] {}\n".format(phone, message), flush=True)
        return True


class NullBackend:
    """Accepts and discards. For tests that don't care about delivery."""

    name = "null"

    def send(self, phone, message, code=None):
        return True


class Msg91Backend:
    """MSG91's Flow API.

    Spendly generates and verifies its own codes, so this only has to deliver
    one. That means the Flow endpoint with a DLT-approved template, not
    MSG91's OTP API — which would issue and check codes itself and duplicate
    the hashing, expiry and rate limiting already in auth/otp.py.

    Required:
        MSG91_AUTH_KEY      from the MSG91 dashboard
        MSG91_TEMPLATE_ID   the DLT-approved template's id

    Optional:
        MSG91_OTP_VAR       template variable holding the code (default OTP)
        MSG91_SENDER        sender/DLT header, if your flow needs one
        MSG91_ENDPOINT      override the API URL
    """

    name = "msg91"
    DEFAULT_ENDPOINT = "https://control.msg91.com/api/v5/flow/"

    def __init__(self):
        self.auth_key = os.environ.get("MSG91_AUTH_KEY", "").strip()
        self.template_id = os.environ.get("MSG91_TEMPLATE_ID", "").strip()
        self.otp_var = os.environ.get("MSG91_OTP_VAR", "OTP").strip() or "OTP"
        self.sender = os.environ.get("MSG91_SENDER", "").strip()
        self.endpoint = os.environ.get("MSG91_ENDPOINT", "").strip() or self.DEFAULT_ENDPOINT

    def _missing_config(self):
        missing = []
        if not self.auth_key:
            missing.append("MSG91_AUTH_KEY")
        if not self.template_id:
            missing.append("MSG91_TEMPLATE_ID")
        return missing

    def build_payload(self, phone, code):
        """The request body. Separate from send() so tests can inspect it."""
        # MSG91 wants country code and number with no plus sign.
        recipient = {"mobiles": phone.lstrip("+"), self.otp_var: code}

        payload = {
            "template_id": self.template_id,
            "short_url": "0",
            "recipients": [recipient],
        }

        if self.sender:
            payload["sender"] = self.sender

        return payload

    def send(self, phone, message, code=None):
        missing = self._missing_config()
        if missing:
            logger.error("MSG91 is not configured; missing %s", ", ".join(missing))
            return False

        # The template supplies the wording, so only the code travels.
        payload = self.build_payload(phone, code if code is not None else message)

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "authkey": self.auth_key,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            logger.error("MSG91 rejected the request (%s): %s", error.code, detail)
            return False
        except (urllib.error.URLError, OSError) as error:
            logger.error("MSG91 unreachable: %s", error)
            return False

        try:
            parsed = json.loads(body)
        except ValueError:
            logger.error("MSG91 returned an unreadable response: %s", body[:500])
            return False

        # A 200 does not mean accepted — MSG91 reports failures in the body.
        if str(parsed.get("type", "")).lower() == "success":
            return True

        logger.error("MSG91 did not accept the message: %s", body[:500])
        return False


BACKENDS = {
    "console": ConsoleBackend,
    "null": NullBackend,
    "msg91": Msg91Backend,
}


def get_backend():
    name = os.environ.get("SMS_BACKEND", "console").lower()
    backend = BACKENDS.get(name)

    if backend is None:
        logger.warning("Unknown SMS_BACKEND %r, falling back to console", name)
        backend = ConsoleBackend

    return backend()


def send_otp(phone, code):
    """Deliver a passcode. Returns True if the backend accepted it."""
    message = "{} is your Spendly verification code. It expires in 5 minutes.".format(code)

    # Template-driven providers need the bare code, not the rendered sentence,
    # so every backend takes both.
    return get_backend().send(phone, message, code=code)
