"""One-time passcodes for Indian mobile numbers.

Codes are six digits, stored hashed, valid for five minutes, and limited in
three ways: how many can be requested per hour, how soon another can be
requested, and how many guesses each one allows.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from database import db


CODE_LENGTH = 6
CODE_TTL = timedelta(minutes=5)

MAX_ATTEMPTS = 5            # guesses allowed per code
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5            # codes a single number can request per hour

PURPOSE_REGISTER = "register"
PURPOSE_LOGIN = "login"
PURPOSE_LINK = "link"

# Indian mobile numbers are ten digits starting 6-9, optionally carrying the
# 91 country code and any of the usual separators.
_SEPARATORS = re.compile(r"[\s\-().]")
_MOBILE = re.compile(r"^(?:\+?91)?([6-9]\d{9})$")


def normalize_phone(raw):
    """Return the number as +91XXXXXXXXXX, or None if it isn't a valid one."""
    if not raw:
        return None

    match = _MOBILE.match(_SEPARATORS.sub("", raw))
    return "+91" + match.group(1) if match else None


def mask_phone(phone):
    """+919876543210 -> +91 98••• ••210, for showing on the verify screen."""
    if not phone or len(phone) < 13:
        return phone
    digits = phone[-10:]
    return "+91 {}••• ••{}".format(digits[:2], digits[-3:])


def _now():
    """UTC, without a tzinfo — stored timestamps are naive strings."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(moment):
    return moment.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ #
# Issuing                                                             #
# ------------------------------------------------------------------ #

def recent_count(phone):
    """How many codes this number has requested in the last hour."""
    since = _iso(_now() - timedelta(hours=1))
    return db.get_db().execute(
        "SELECT COUNT(*) AS c FROM otp_codes WHERE phone = ? AND created_at >= ?",
        (phone, since),
    ).fetchone()["c"]


def seconds_until_resend(phone):
    """Seconds left before this number may request another code."""
    row = db.get_db().execute(
        """
        SELECT created_at FROM otp_codes
        WHERE phone = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (phone,),
    ).fetchone()

    if row is None:
        return 0

    created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    elapsed = _now() - created
    remaining = RESEND_COOLDOWN - elapsed

    return max(0, int(remaining.total_seconds()))


def issue(phone, purpose, pending_name=None):
    """Create a code for this number.

    Returns ``(code, error)``. ``code`` is the plain six digits, for handing
    to the SMS backend and nothing else — only its hash is stored.
    """
    if recent_count(phone) >= MAX_PER_HOUR:
        return None, "Too many codes requested. Please try again later."

    wait = seconds_until_resend(phone)
    if wait:
        return None, "Please wait {} seconds before requesting another code.".format(wait)

    code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))

    conn = db.get_db()
    conn.execute(
        """
        INSERT INTO otp_codes (phone, code_hash, purpose, pending_name, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            phone,
            generate_password_hash(code),
            purpose,
            pending_name,
            _iso(_now() + CODE_TTL),
            _iso(_now()),
        ),
    )
    conn.commit()

    return code, None


# ------------------------------------------------------------------ #
# Verifying                                                           #
# ------------------------------------------------------------------ #

def verify(phone, purpose, submitted):
    """Check a submitted code.

    Returns ``(row, error)``. On success the code is marked consumed so it
    cannot be replayed.
    """
    conn = db.get_db()

    row = conn.execute(
        """
        SELECT id, code_hash, pending_name, expires_at, attempts, consumed_at
        FROM otp_codes
        WHERE phone = ? AND purpose = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (phone, purpose),
    ).fetchone()

    # A number with no outstanding code and a wrong code look the same, so a
    # failed attempt says nothing about whether the account exists.
    generic = "That code is incorrect or has expired."

    if row is None or row["consumed_at"] is not None:
        return None, generic

    if row["attempts"] >= MAX_ATTEMPTS:
        return None, "Too many incorrect attempts. Request a new code."

    if datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S") < _now():
        return None, generic

    if not check_password_hash(row["code_hash"], (submitted or "").strip()):
        conn.execute(
            "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],)
        )
        conn.commit()
        return None, generic

    conn.execute(
        "UPDATE otp_codes SET consumed_at = ? WHERE id = ?", (_iso(_now()), row["id"])
    )
    conn.commit()

    return row, None
