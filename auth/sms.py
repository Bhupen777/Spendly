"""Delivery of one-time passcodes.

No gateway is configured, so the default backend logs the code instead of
sending it. Swap in a real provider by implementing ``send`` and selecting it
with the ``SMS_BACKEND`` environment variable.
"""

import logging
import os


logger = logging.getLogger(__name__)


class ConsoleBackend:
    """Logs the code. Development only — anyone reading the log can sign in."""

    name = "console"

    def send(self, phone, message):
        logger.warning("[SMS -> %s] %s", phone, message)
        print("\n  [SMS -> {}] {}\n".format(phone, message), flush=True)
        return True


class NullBackend:
    """Accepts and discards. For tests that don't care about delivery."""

    name = "null"

    def send(self, phone, message):
        return True


BACKENDS = {
    "console": ConsoleBackend,
    "null": NullBackend,
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
    return get_backend().send(phone, message)
