import os
from datetime import date
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

from auth import otp, sms
from database import db

# Reads .env into the environment. Real environment variables win, so a
# deployment's own config is never overwritten by a stray file.
load_dotenv()

app = Flask(__name__)

# Signs session cookies and CSRF tokens. No fallback on purpose: a default
# everyone can read makes both forgeable, and failing at startup is easier to
# notice than a quietly insecure app.
SECRET_KEY = os.environ.get("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set.\n"
        "Create a .env file in the project root containing:\n\n"
        "    SECRET_KEY=<random value>\n\n"
        "Generate one with:\n"
        "    python -c \"import secrets; print(secrets.token_hex(32))\""
    )

app.secret_key = SECRET_KEY

# Rejects any POST without a valid token, so every form has to opt in rather
# than remember to. Templates get csrf_token() for free.
csrf = CSRFProtect(app)

# Closes the request-scoped connection when each request ends.
db.init_app(app)


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    """Explain the usual cause — a stale tab — instead of a bare 400.

    The redirect keeps its 302: a browser won't follow a 400, so pairing the
    two would leave the user on a blank page with the message unread.
    """
    flash("That form expired. Please try again.", "error")
    return redirect(request.referrer or url_for("landing"))


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def login_required(view):
    """Redirect anonymous visitors to the sign-in page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please sign in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_current_user():
    """Make the signed-in user available to every template."""
    user = None

    if session.get("user_id") is not None:
        user = db.get_db().execute(
            """
            SELECT id, name, email, phone,
                   password_hash IS NOT NULL AS has_password
            FROM users WHERE id = ?
            """,
            (session["user_id"],),
        ).fetchone()

        # Session points at a user who no longer exists.
        if user is None:
            session.clear()

    return {"current_user": user}


@app.template_filter("rupees")
def rupees(amount):
    """Format a number the Indian way: 1234567.5 -> 12,34,567.50"""
    whole, _, fraction = "{:.2f}".format(float(amount)).partition(".")

    if len(whole) > 3:
        last3, rest = whole[-3:], whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups + [last3])

    return "{}.{}".format(whole, fraction)


# ------------------------------------------------------------------ #
# Public routes                                                       #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id") is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        error = None
        if not name:
            error = "Please enter your name."
        elif not email:
            error = "Please enter your email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."

        if error is None:
            conn = db.get_db()
            existing = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()

            if existing is not None:
                error = "An account with that email already exists."
            else:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)),
                )
                conn.commit()

                session.clear()
                session["user_id"] = cursor.lastrowid
                return redirect(url_for("dashboard"))

        return render_template("register.html", error=error)

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id") is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = db.get_db().execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()

        # One message for both cases, so the form can't be used to discover
        # which email addresses have accounts.
        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Incorrect email or password.")

        session.clear()
        session["user_id"] = user["id"]

        destination = request.args.get("next")
        if not destination or not destination.startswith("/"):
            destination = url_for("dashboard")

        return redirect(destination)

    return render_template("login.html")


# ------------------------------------------------------------------ #
# Phone + OTP                                                         #
# ------------------------------------------------------------------ #

def _dev_code_visible():
    """Whether the code may be shown on screen.

    Two conditions, both required: debug mode is on, and nothing is actually
    being delivered. A configured gateway or a production run disables it, so
    the code cannot surface in front of real users.
    """
    return bool(app.debug) and sms.get_backend().name == "console"


def _start_verification(phone, purpose, pending_name=None):
    """Issue and send a code, then stash what the verify step needs.

    Returns an error string, or None on success.
    """
    code, error = otp.issue(phone, purpose, pending_name)

    if error is not None:
        return error

    if not sms.send_otp(phone, code):
        # Say so rather than leaving them watching for a code that isn't
        # coming. The backend logs why.
        return "We couldn't send a code to that number. Please try again shortly."

    session["otp_phone"] = phone
    session["otp_purpose"] = purpose

    if _dev_code_visible():
        session["dev_otp"] = code
    else:
        session.pop("dev_otp", None)

    return None


@app.route("/register/phone", methods=["GET", "POST"])
def register_phone():
    if session.get("user_id") is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = otp.normalize_phone(request.form.get("phone", ""))

        if not name:
            error = "Please enter your name."
        elif phone is None:
            error = "Enter a valid Indian mobile number."
        else:
            existing = db.get_db().execute(
                "SELECT id FROM users WHERE phone = ?", (phone,)
            ).fetchone()

            if existing is not None:
                error = "That number already has an account. Sign in instead."
            else:
                error = _start_verification(phone, otp.PURPOSE_REGISTER, name)

        if error is not None:
            return render_template("register_phone.html", error=error)

        return redirect(url_for("verify_otp"))

    return render_template("register_phone.html")


@app.route("/login/phone", methods=["GET", "POST"])
def login_phone():
    if session.get("user_id") is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        phone = otp.normalize_phone(request.form.get("phone", ""))

        if phone is None:
            return render_template(
                "login_phone.html", error="Enter a valid Indian mobile number."
            )

        known = db.get_db().execute(
            "SELECT id FROM users WHERE phone = ?", (phone,)
        ).fetchone()

        if known is None:
            # Move to the verify screen regardless, so the form can't be used
            # to discover which numbers are registered. No code is sent, so
            # nothing can be entered that will work.
            session["otp_phone"] = phone
            session["otp_purpose"] = otp.PURPOSE_LOGIN
            # No code exists, so make sure an older one isn't still on show.
            session.pop("dev_otp", None)
            return redirect(url_for("verify_otp"))

        error = _start_verification(phone, otp.PURPOSE_LOGIN)

        if error is not None:
            return render_template("login_phone.html", error=error)

        return redirect(url_for("verify_otp"))

    return render_template("login_phone.html")


@app.route("/verify", methods=["GET", "POST"])
def verify_otp():
    phone = session.get("otp_phone")
    purpose = session.get("otp_purpose")

    def render(error=None):
        return render_template(
            "verify_otp.html",
            error=error,
            masked=otp.mask_phone(phone),
            purpose=purpose,
            dev_code=session.get("dev_otp") if _dev_code_visible() else None,
        )

    if not phone or not purpose:
        flash("Start by entering your mobile number.", "error")
        return redirect(url_for("login_phone"))

    if request.method == "POST":
        row, error = otp.verify(phone, purpose, request.form.get("code", ""))

        if error is not None:
            return render(error)

        conn = db.get_db()

        if purpose == otp.PURPOSE_REGISTER:
            cursor = conn.execute(
                "INSERT INTO users (name, phone) VALUES (?, ?)",
                (row["pending_name"], phone),
            )
            conn.commit()
            user_id = cursor.lastrowid

        elif purpose == otp.PURPOSE_LINK:
            user_id = session.get("user_id")
            if user_id is None:
                return redirect(url_for("login"))

            conn.execute(
                "UPDATE users SET phone = ? WHERE id = ?", (phone, user_id)
            )
            conn.commit()

            session.pop("otp_phone", None)
            session.pop("otp_purpose", None)
            flash("Mobile number verified.", "success")
            return redirect(url_for("profile"))

        else:
            user = conn.execute(
                "SELECT id FROM users WHERE phone = ?", (phone,)
            ).fetchone()

            if user is None:
                return render("That code is incorrect or has expired.")

            user_id = user["id"]

        session.clear()
        session["user_id"] = user_id
        return redirect(url_for("dashboard"))

    return render()


@app.route("/verify/resend", methods=["POST"])
def resend_otp():
    phone = session.get("otp_phone")
    purpose = session.get("otp_purpose")

    if not phone or not purpose:
        return redirect(url_for("login_phone"))

    # Registration carries the pending name on the previous code; reuse it so
    # a resend doesn't lose it.
    previous = db.get_db().execute(
        """
        SELECT pending_name FROM otp_codes
        WHERE phone = ? AND purpose = ?
        ORDER BY id DESC LIMIT 1
        """,
        (phone, purpose),
    ).fetchone()

    error = _start_verification(
        phone, purpose, previous["pending_name"] if previous else None
    )

    flash(error or "A new code is on its way.", "error" if error else "success")
    return redirect(url_for("verify_otp"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Dashboard                                                           #
# ------------------------------------------------------------------ #

@app.route("/dashboard")
@login_required
def dashboard():
    conn = db.get_db()
    user_id = session["user_id"]
    month_start = date.today().replace(day=1).isoformat()

    expenses = conn.execute(
        """
        SELECT e.id, e.amount, e.description, e.spent_on, c.name AS category
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        WHERE e.user_id = ?
        ORDER BY e.spent_on DESC, e.id DESC
        """,
        (user_id,),
    ).fetchall()

    month_total = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ? AND spent_on >= ?
        """,
        (user_id, month_start),
    ).fetchone()["total"]

    all_time_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id = ?",
        (user_id,),
    ).fetchone()["total"]

    breakdown = conn.execute(
        """
        SELECT c.name, SUM(e.amount) AS total
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        WHERE e.user_id = ? AND e.spent_on >= ?
        GROUP BY c.name
        ORDER BY total DESC
        """,
        (user_id, month_start),
    ).fetchall()

    categories = conn.execute(
        "SELECT id, name FROM categories ORDER BY name"
    ).fetchall()

    # Widest bar in the breakdown sets the scale for the rest.
    largest = breakdown[0]["total"] if breakdown else 0

    return render_template(
        "dashboard.html",
        expenses=expenses,
        month_total=month_total,
        all_time_total=all_time_total,
        breakdown=breakdown,
        largest=largest,
        categories=categories,
        today=date.today().isoformat(),
    )


def _owned_expense_or_404(expense_id):
    """Fetch one of the signed-in user's expenses, or 404.

    Scoping the lookup to the user means someone else's id is
    indistinguishable from one that doesn't exist, so the response can't be
    used to probe which ids are real.
    """
    expense = db.get_db().execute(
        """
        SELECT id, user_id, category_id, amount, description, spent_on
        FROM expenses
        WHERE id = ? AND user_id = ?
        """,
        (expense_id, session["user_id"]),
    ).fetchone()

    if expense is None:
        abort(404)

    return expense


def _expense_form(form):
    """Read and validate the fields shared by add and edit.

    Returns ``(values, error)`` — ``error`` is None when the input is usable.
    """
    category_id = form.get("category_id", "").strip()
    spent_on = form.get("spent_on", "").strip()
    description = form.get("description", "").strip()

    try:
        amount = float(form.get("amount", "").strip())
    except ValueError:
        amount = 0

    error = None
    if amount <= 0:
        error = "Enter an amount greater than zero."
    elif not category_id:
        error = "Choose a category."
    elif not spent_on:
        error = "Choose a date."

    values = {
        "amount": amount,
        "category_id": category_id,
        "spent_on": spent_on,
        "description": description or None,
    }

    return values, error


@app.route("/expenses/add", methods=["POST"])
@login_required
def add_expense():
    values, error = _expense_form(request.form)

    if error is not None:
        flash(error, "error")
    else:
        conn = db.get_db()
        conn.execute(
            """
            INSERT INTO expenses (user_id, category_id, amount, description, spent_on)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                values["category_id"],
                values["amount"],
                values["description"],
                values["spent_on"],
            ),
        )
        conn.commit()
        flash("Expense added.", "success")

    return redirect(url_for("dashboard"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(id):
    expense = _owned_expense_or_404(id)
    conn = db.get_db()

    categories = conn.execute(
        "SELECT id, name FROM categories ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        values, error = _expense_form(request.form)

        if error is not None:
            # Re-render with what they typed, so nothing has to be retyped.
            return render_template(
                "edit_expense.html",
                expense=expense,
                categories=categories,
                values=values,
                error=error,
                today=date.today().isoformat(),
            )

        conn.execute(
            """
            UPDATE expenses
            SET category_id = ?, amount = ?, description = ?, spent_on = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                values["category_id"],
                values["amount"],
                values["description"],
                values["spent_on"],
                id,
                session["user_id"],
            ),
        )
        conn.commit()

        flash("Expense updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "edit_expense.html",
        expense=expense,
        categories=categories,
        values=dict(expense),
        error=None,
        today=date.today().isoformat(),
    )


@app.route("/expenses/<int:id>/delete", methods=["POST"])
@login_required
def delete_expense(id):
    _owned_expense_or_404(id)

    conn = db.get_db()
    conn.execute(
        "DELETE FROM expenses WHERE id = ? AND user_id = ?",
        (id, session["user_id"]),
    )
    conn.commit()

    flash("Expense deleted.", "success")
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------------ #
# Profile                                                             #
# ------------------------------------------------------------------ #

@app.route("/profile")
@login_required
def profile():
    conn = db.get_db()
    user_id = session["user_id"]

    stats = conn.execute(
        """
        SELECT
            COUNT(*)                   AS entries,
            COALESCE(SUM(amount), 0)   AS total,
            MIN(spent_on)              AS first_on,
            MAX(spent_on)              AS last_on
        FROM expenses
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    top_category = conn.execute(
        """
        SELECT c.name, SUM(e.amount) AS total
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        WHERE e.user_id = ?
        GROUP BY c.name
        ORDER BY total DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    return render_template(
        "profile.html",
        stats=stats,
        top_category=top_category,
    )


@app.route("/profile/details", methods=["POST"])
@login_required
def update_profile():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()

    conn = db.get_db()
    user_id = session["user_id"]

    if not name:
        flash("Please enter your name.", "error")
    elif not email:
        flash("Please enter your email address.", "error")
    else:
        # COLLATE NOCASE on the column makes this check case-insensitive.
        clash = conn.execute(
            "SELECT id FROM users WHERE email = ? AND id != ?",
            (email, user_id),
        ).fetchone()

        if clash is not None:
            flash("That email is already used by another account.", "error")
        else:
            conn.execute(
                "UPDATE users SET name = ?, email = ? WHERE id = ?",
                (name, email, user_id),
            )
            conn.commit()
            flash("Profile updated.", "success")

    return redirect(url_for("profile"))


@app.route("/profile/phone", methods=["POST"])
@login_required
def link_phone():
    """Start verifying a mobile number for an existing account."""
    phone = otp.normalize_phone(request.form.get("phone", ""))

    if phone is None:
        flash("Enter a valid Indian mobile number.", "error")
        return redirect(url_for("profile"))

    taken = db.get_db().execute(
        "SELECT id FROM users WHERE phone = ? AND id != ?",
        (phone, session["user_id"]),
    ).fetchone()

    if taken is not None:
        flash("That number is already linked to another account.", "error")
        return redirect(url_for("profile"))

    error = _start_verification(phone, otp.PURPOSE_LINK)

    if error is not None:
        flash(error, "error")
        return redirect(url_for("profile"))

    return redirect(url_for("verify_otp"))


@app.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    conn = db.get_db()
    user_id = session["user_id"]

    user = conn.execute(
        "SELECT password_hash FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    if user["password_hash"] is None:
        # Phone-only account: there is no current password to check against,
        # so let them set one by confirming the new value twice.
        if len(new) < 8:
            flash("New password must be at least 8 characters.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), user_id),
            )
            conn.commit()
            flash("Password set.", "success")

        return redirect(url_for("profile"))

    if not check_password_hash(user["password_hash"], current):
        flash("Your current password is incorrect.", "error")
    elif len(new) < 8:
        flash("New password must be at least 8 characters.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    else:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new), user_id),
        )
        conn.commit()
        flash("Password changed.", "success")

    return redirect(url_for("profile"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
