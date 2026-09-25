# ◈ Spendly

A personal expense tracker built with Flask. Log expenses, understand your spending
patterns, and take control of your financial life — one transaction at a time.

Register an account, record what you spend, and see where your money goes with
monthly totals and a category breakdown.

> **Status:** feature-complete for its intended scope. See
> [Known gaps](#known-gaps) before deploying it anywhere public.

## Features

- **Two ways in** — email and password, or an Indian mobile number with a one-time
  code. Passwords and OTPs are both hashed, never stored in plain text
- **Dashboard** — every expense listed newest-first, with monthly and all-time totals
- **Category breakdown** — current month's spending by category, as scaled bars
- **Full CRUD** — add expenses inline, edit them on their own page, delete with confirmation
- **Profile** — account summary, editable name and email, password change

## Tech stack

| | |
|---|---|
| Language | Python 3.12 |
| Framework | Flask 3.1.3 |
| Templating | Jinja2 |
| Database | SQLite (`sqlite3`, standard library) — no ORM |
| Auth | `werkzeug.security` hashing + Flask sessions, or phone + OTP |
| CSRF | Flask-WTF 1.3.0 (`CSRFProtect`) |
| Config | python-dotenv 1.2.3 (`.env`) |
| Testing | pytest 8.3.5 + pytest-flask 1.3.0 |
| Frontend | Vanilla CSS and JavaScript, no build step |

Six direct dependencies. No Node, no bundler, no database server.

## Getting started

### Prerequisites

Python 3.12 or newer. Check with `python --version`.

> On Windows, use `python` — there is no `python3.exe`. If `python` prints
> *"Python was not found"*, it is hitting the Microsoft Store alias stub and
> Python is not actually installed. Install it with
> `winget install Python.Python.3.12`, then open a new terminal.

### Setup

Clone and enter the project:

```bash
git clone https://github.com/Bhupen777/Spendly.git
cd Spendly
```

Create and activate a virtual environment:

```powershell
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

Your prompt should now be prefixed with `(venv)`.

Install dependencies:

```bash
pip install -r requirements.txt
```

> If activation is blocked on Windows with an execution-policy error, either run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use
> `.\venv\Scripts\activate.bat` instead.

### Create the database

```bash
python -m database.db
```

This creates `expense_tracker.db` in the project root and seeds it with default
categories plus a demo account. Both steps are idempotent — re-running will not
duplicate anything.

**Demo login:** `demo@spendly.app` / `spendly123`

### Run

```bash
python app.py
```

The app starts on **http://127.0.0.1:5001** with debug mode and auto-reload enabled.

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | yes | Signs session cookies and CSRF tokens |
| `SMS_BACKEND` | no | How OTPs are delivered — `console` (default), `null`, or `msg91` |
| `MSG91_AUTH_KEY` | with `msg91` | Auth key from the MSG91 dashboard |
| `MSG91_TEMPLATE_ID` | with `msg91` | DLT-approved template id |
| `MSG91_OTP_VAR` | no | Template variable holding the code (default `OTP`) |
| `MSG91_SENDER` | no | Sender / DLT header, if your flow needs one |

Settings are read from a `.env` file in the project root, which is gitignored.
Copy the template and fill it in:

```bash
cp .env.example .env
```

Generate a value:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**There is no fallback.** The app raises at startup if `SECRET_KEY` is missing,
rather than booting with a default that makes every session cookie and CSRF token
forgeable. Real environment variables take precedence over `.env`, so a
deployment's own configuration is never overridden by a stray file.

> Changing the key invalidates existing sessions — everyone signed in is signed
> out, which is the correct behaviour if a key was ever exposed.

## Project structure

```
expense-tracker/
├── app.py                    # Routes, auth helpers, template filters
├── requirements.txt          # Pinned dependencies
├── .env.example              # Template for .env (gitignored)
├── auth/
│   ├── __init__.py
│   ├── otp.py                # Number parsing, code issuing and verifying
│   └── sms.py                # Pluggable delivery backends
├── database/
│   ├── __init__.py
│   └── db.py                 # Connection, schema, migrations, seed data
├── templates/
│   ├── base.html             # Shared layout — navbar, flashes, footer
│   ├── landing.html          # Marketing / home page
│   ├── login.html
│   ├── register.html
│   ├── register_phone.html
│   ├── login_phone.html
│   ├── verify_otp.html
│   ├── dashboard.html        # Expense list, totals, add form
│   ├── edit_expense.html
│   ├── profile.html
│   ├── terms.html
│   └── privacy.html
└── static/
    ├── css/style.css
    └── js/main.js
```

## Database

Four tables, created by `init_db()`:

```sql
users       id, name, email (UNIQUE, case-insensitive), password_hash,
            phone (UNIQUE where present), created_at
            CHECK (email IS NOT NULL OR phone IS NOT NULL)
categories  id, name (UNIQUE)
expenses    id, user_id → users, category_id → categories,
            amount (CHECK > 0), description, spent_on, created_at
otp_codes   id, phone, code_hash, purpose, pending_name,
            expires_at, attempts, consumed_at, created_at
```

Email and phone are each optional so an account can be created either way, but
the `CHECK` means every account keeps at least one identifier.

`init_db()` migrates older databases in place: it adds `users.phone`, and if
`email` is still `NOT NULL` it rebuilds the table, since SQLite cannot relax a
constraint with `ALTER`. The rebuild disables foreign keys for the swap —
dropping `users` with them on would cascade every expense away — and verifies
`PRAGMA foreign_key_check` afterwards.

Indexed on `(user_id, spent_on)`, since every expense query filters that pair.

`get_db()` enables the `foreign_keys` pragma on every connection. SQLite leaves it
off by default and scopes it per connection — without it, `ON DELETE CASCADE` is
silently ignored.

Inside a request the connection is cached on `g` and closed on teardown, wired up
by `db.init_app(app)` in `app.py`.

## Routes

| Route | Methods | Auth | Purpose |
|---|---|---|---|
| `/` | GET | — | Landing page |
| `/register` | GET, POST | — | Create an account with email and password |
| `/login` | GET, POST | — | Sign in with email and password |
| `/register/phone` | GET, POST | — | Create an account with a mobile number |
| `/login/phone` | GET, POST | — | Request a sign-in code |
| `/verify` | GET, POST | — | Enter the code |
| `/verify/resend` | POST | — | Request another code |
| `/logout` | POST | — | Sign out |
| `/terms` | GET | — | Terms and Conditions |
| `/privacy` | GET | — | Privacy Policy |
| `/dashboard` | GET | ✅ | Expenses, totals, category breakdown |
| `/expenses/add` | POST | ✅ | Create an expense |
| `/expenses/<id>/edit` | GET, POST | ✅ | Edit an expense |
| `/expenses/<id>/delete` | POST | ✅ | Delete an expense |
| `/profile` | GET | ✅ | Account summary |
| `/profile/details` | POST | ✅ | Update name and email |
| `/profile/phone` | POST | ✅ | Link or replace a mobile number |
| `/profile/password` | POST | ✅ | Set or change password |

Routes marked ✅ require a session; anonymous visitors are redirected to
`/login?next=…` and returned afterwards.

### Design notes

- **Everything destructive is POST-only.** A `GET` delete would let a prefetch or
  an image tag destroy a row.
- **Ownership is enforced in the SQL.** Both the lookup and the write filter on
  `user_id`, and another user's id returns **404, not 403** — a 403 would confirm
  the row exists.
- **Login reports one message** for unknown email and wrong password alike, so the
  form can't be used to enumerate accounts.
- **CSRF is enforced globally.** `CSRFProtect` rejects any POST without a valid
  token, so a new form has to opt *out* rather than remember to opt in. Every form
  carries `{{ csrf_token() }}` as a hidden field.

### One-time codes

Six digits, stored hashed, valid for five minutes, and limited three ways: five
guesses per code, a sixty-second resend cooldown, and five codes per number per
hour. A consumed code cannot be replayed, and a code issued for sign-up will not
verify a sign-in.

`/login/phone` sends nothing for an unregistered number but moves to the verify
screen exactly as it would for a real one, so the form cannot be used to discover
which numbers have accounts.

### Delivery

`auth/sms.py` holds the backends, chosen with `SMS_BACKEND`:

| Backend | Behaviour |
|---|---|
| `console` | Logs the code instead of sending it. **Default.** |
| `null` | Discards it. Used by the tests. |
| `msg91` | Sends it through MSG91's Flow API. |

> `console` is for development only — anyone who can read the log can sign in as
> anyone.

**Setting up MSG91.** Spendly generates and verifies its own codes, so it needs
the Flow API (send a templated message), not MSG91's OTP API — that would issue
and check codes itself and duplicate the hashing, expiry and rate limiting in
`auth/otp.py`.

1. Register your sender ID and message template on the DLT portal. Indian
   regulation requires this and approval takes a few days.
2. Create a flow in MSG91 against that template with a variable for the code.
3. Put the auth key and template id in `.env`, and set `SMS_BACKEND=msg91`.

If your template names the variable something other than `OTP`, set
`MSG91_OTP_VAR` to match — a mismatch is silently delivered as an empty code.

Only the bare code is transmitted; the wording comes from your template. A
delivery failure is reported to the user rather than leaving them waiting, and
the reason is logged. Note that MSG91 returns HTTP 200 for rejected messages, so
the backend checks the response body rather than the status code.

Add another provider by writing a class with `send(phone, message, code=None)`
and registering it in `BACKENDS`.

## Known gaps

- **MSG91 is implemented but unverified against the live API.** The backend and
  its tests are written to MSG91's documented Flow contract, with the network
  stubbed. Nobody has yet sent a real message through it — confirm the payload
  against current MSG91 docs before relying on it.
- **`amount` is stored as `REAL`.** Floats can't represent every decimal exactly,
  so large sums can drift by fractions of a paisa. Integer paise is the rigorous
  alternative; cheaper to change before there's data to migrate.
- **Dev server only.** `app.run(debug=True)` is not for production — use a WSGI
  server such as Waitress or Gunicorn.

## Testing

```bash
pytest
```

135 tests:

| File | Covers |
|---|---|
| `test_database.py` | schema, the `foreign_keys` pragma, seed idempotency, constraints, connection lifecycle |
| `test_auth.py` | registration, hashing, login, account enumeration, logout |
| `test_phone_auth.py` | number parsing, OTP issuing and verifying, rate limits, sign-up / sign-in / linking |
| `test_expenses.py` | dashboard, add / edit / delete, validation, ownership |
| `test_profile.py` | account details, email collisions, password changes |
| `test_security.py` | `login_required` on every private route, CSRF |
| `test_sms.py` | backend selection, MSG91 payload and failure handling |

Each test runs against a fresh SQLite file in a pytest `tmp_path`, created by
monkeypatching `database.db.DB_PATH`. Your real `expense_tracker.db` is never
opened, so the suite is safe to run at any time.

CSRF is disabled in the default fixture so behavioural tests don't have to thread
tokens through every request; `test_security.py` turns it back on to test the
protection itself. `SMS_BACKEND` is forced to `null`, and a `captured_codes`
fixture intercepts outgoing codes so tests can read them.

## License

Not currently licensed.
