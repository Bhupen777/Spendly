# ◈ Spendly

A personal expense tracker built with Flask. Log expenses, understand your spending
patterns, and take control of your financial life — one transaction at a time.

Register an account, record what you spend, and see where your money goes with
monthly totals and a category breakdown.

> **Status:** feature-complete for its intended scope. See
> [Known gaps](#known-gaps) before deploying it anywhere public.

## Features

- **Accounts** — register and sign in; passwords are hashed, never stored in plain text
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
| Auth | `werkzeug.security` hashing + Flask sessions |
| CSRF | Flask-WTF 1.3.0 (`CSRFProtect`) |
| Testing | pytest 8.3.5 + pytest-flask 1.3.0 |
| Frontend | Vanilla CSS and JavaScript, no build step |

Five direct dependencies. No Node, no bundler, no database server.

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

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-only-insecure-key` | Signs session cookies |

The fallback is fine locally. Set a real value anywhere else — with the default in
place, session cookies are forgeable:

```bash
# macOS / Linux
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

```powershell
# Windows (PowerShell)
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
```

## Project structure

```
expense-tracker/
├── app.py                    # Routes, auth helpers, template filters
├── requirements.txt          # Pinned dependencies
├── database/
│   ├── __init__.py
│   └── db.py                 # Connection, schema, seed data
├── templates/
│   ├── base.html             # Shared layout — navbar, flashes, footer
│   ├── landing.html          # Marketing / home page
│   ├── login.html
│   ├── register.html
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

Three tables, created by `init_db()`:

```sql
users       id, name, email (UNIQUE, case-insensitive), password_hash, created_at
categories  id, name (UNIQUE)
expenses    id, user_id → users, category_id → categories,
            amount (CHECK > 0), description, spent_on, created_at
```

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
| `/register` | GET, POST | — | Create an account |
| `/login` | GET, POST | — | Sign in |
| `/logout` | POST | — | Sign out |
| `/terms` | GET | — | Terms and Conditions |
| `/privacy` | GET | — | Privacy Policy |
| `/dashboard` | GET | ✅ | Expenses, totals, category breakdown |
| `/expenses/add` | POST | ✅ | Create an expense |
| `/expenses/<id>/edit` | GET, POST | ✅ | Edit an expense |
| `/expenses/<id>/delete` | POST | ✅ | Delete an expense |
| `/profile` | GET | ✅ | Account summary |
| `/profile/details` | POST | ✅ | Update name and email |
| `/profile/password` | POST | ✅ | Change password |

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

## Known gaps

- **`SECRET_KEY` has a hardcoded fallback** — see [Configuration](#configuration).
  CSRF tokens are signed with it too, so a known key undermines that protection
  as well as session integrity.
- **`amount` is stored as `REAL`.** Floats can't represent every decimal exactly,
  so large sums can drift by fractions of a paisa. Integer paise is the rigorous
  alternative; cheaper to change before there's data to migrate.
- **No tests.** pytest and pytest-flask are installed but `tests/` doesn't exist.
- **Dev server only.** `app.run(debug=True)` is not for production — use a WSGI
  server such as Waitress or Gunicorn.

## Testing

pytest and pytest-flask are installed, but no tests have been written yet.
Once a `tests/` directory exists:

```bash
pytest
```

## License

Not currently licensed.
