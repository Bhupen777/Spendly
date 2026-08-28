# ◈ Spendly

A personal expense tracker built with Flask. Log expenses, understand your spending
patterns, and take control of your financial life — one transaction at a time.

> **Status:** work in progress. The landing, register, and login pages are built;
> the expense CRUD routes and the database layer are still stubs. See
> [Project status](#project-status) below.

## Tech stack

| | |
|---|---|
| Language | Python 3.12 |
| Framework | Flask 3.1.3 |
| Templating | Jinja2 |
| Database | SQLite (`sqlite3`, standard library) |
| Testing | pytest 8.3.5 + pytest-flask 1.3.0 |
| Frontend | Vanilla CSS and JavaScript, no build step |

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

### Run

```bash
python app.py
```

The app starts on **http://127.0.0.1:5001** with debug mode and auto-reload enabled.

> If activation is blocked on Windows with an execution-policy error, either run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or use
> `.\venv\Scripts\activate.bat` instead.

## Project structure

```
expense-tracker/
├── app.py                 # Flask application and route definitions
├── requirements.txt       # Pinned dependencies
├── database/
│   ├── __init__.py
│   └── db.py              # Connection, schema, and seed helpers
├── templates/
│   ├── base.html          # Shared layout — navbar, footer, blocks
│   ├── landing.html       # Marketing / home page
│   ├── login.html
│   └── register.html
└── static/
    ├── css/style.css
    └── js/main.js
```

## Routes

| Route | Method | Status |
|---|---|---|
| `/` | GET | ✅ Landing page |
| `/register` | GET | ✅ Registration form |
| `/login` | GET | ✅ Login form |
| `/logout` | GET | 🚧 Placeholder |
| `/profile` | GET | 🚧 Placeholder |
| `/expenses/add` | GET | 🚧 Placeholder |
| `/expenses/<id>/edit` | GET | 🚧 Placeholder |
| `/expenses/<id>/delete` | GET | 🚧 Placeholder |

## Project status

The frontend is complete; the backend is being filled in step by step.

- [ ] **Step 1** — Database setup: `get_db()`, `init_db()`, `seed_db()` in `database/db.py`
- [ ] **Step 2** — User registration with hashed passwords
- [ ] **Step 3** — Login and logout via sessions
- [ ] **Step 4** — Profile page
- [ ] **Step 5** — Expense list view
- [ ] **Step 6** — Category breakdown and monthly summary
- [ ] **Step 7** — Add expense
- [ ] **Step 8** — Edit expense
- [ ] **Step 9** — Delete expense

Notes for whoever picks this up:

- `app.secret_key` is not set yet. Sessions in Step 3 will need it — load it from
  a `.env` file, which is already listed in `.gitignore`.
- The SQLite database is expected at `expense_tracker.db` in the project root
  (also gitignored, so it stays out of version control).
- Password hashing needs no extra dependency: Werkzeug ships
  `generate_password_hash` and `check_password_hash` in `werkzeug.security`.
- The edit and delete routes are currently GET-only. They should accept `POST`
  before they do anything destructive.

## Testing

pytest and pytest-flask are installed, but no tests have been written yet.
Once a `tests/` directory exists:

```bash
pytest
```

## License

Not currently licensed.
