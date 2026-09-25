"""Access control and CSRF.

The CSRF tests turn WTF_CSRF_ENABLED back on — conftest disables it so the
behavioural tests don't have to thread tokens through every request.
"""

import re

import pytest

from tests.conftest import DEMO_EMAIL, DEMO_PASSWORD


PRIVATE_GET_ROUTES = ["/dashboard", "/profile", "/expenses/1/edit"]

PRIVATE_POST_ROUTES = [
    "/expenses/add",
    "/expenses/1/edit",
    "/expenses/1/delete",
    "/profile/details",
    "/profile/password",
]


# ------------------------------------------------------------------ #
# Access control                                                      #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("path", PRIVATE_GET_ROUTES)
def test_private_get_routes_redirect_anonymous_visitors(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", PRIVATE_POST_ROUTES)
def test_private_post_routes_redirect_anonymous_visitors(client, path):
    assert client.post(path).status_code == 302


def test_redirect_preserves_the_requested_path(client):
    response = client.get("/dashboard")
    assert "next=%2Fdashboard" in response.headers["Location"] or \
           "next=/dashboard" in response.headers["Location"]


# ------------------------------------------------------------------ #
# CSRF                                                                #
# ------------------------------------------------------------------ #

@pytest.fixture
def csrf_client(app, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    return app.test_client()


def _token(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else None


def _sign_in(csrf_client):
    token = _token(csrf_client.get("/login").get_data(as_text=True))
    csrf_client.post(
        "/login",
        data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, "csrf_token": token},
    )
    return csrf_client


def test_forms_render_a_token(csrf_client):
    assert _token(csrf_client.get("/login").get_data(as_text=True)) is not None
    assert _token(csrf_client.get("/register").get_data(as_text=True)) is not None


def test_login_without_a_token_is_rejected(csrf_client):
    # The handler redirects rather than returning 400, so the explanation is
    # actually rendered — browsers don't follow redirects on a 400.
    response = csrf_client.post(
        "/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 302
    # What matters: no session was created.
    assert csrf_client.get("/dashboard").status_code == 302


def test_login_with_a_token_succeeds(csrf_client):
    _sign_in(csrf_client)
    assert csrf_client.get("/dashboard").status_code == 200


@pytest.mark.parametrize(
    "path,data",
    [
        ("/expenses/add", {"amount": "10", "category_id": "1", "spent_on": "2026-09-20"}),
        ("/profile/details", {"name": "Hacked", "email": "hacked@example.com"}),
        ("/logout", {}),
    ],
)
def test_post_without_a_token_is_rejected(csrf_client, path, data):
    _sign_in(csrf_client)
    response = csrf_client.post(path, data=data, follow_redirects=True)
    # Refused, and the user is told why rather than being left on a blank page.
    assert "That form expired" in response.get_data(as_text=True)


def test_tokenless_post_changes_nothing(csrf_client, conn):
    _sign_in(csrf_client)
    before = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]

    csrf_client.post(
        "/expenses/add",
        data={"amount": "10", "category_id": "1", "spent_on": "2026-09-20"},
    )

    after = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    assert after == before


def test_tokenless_logout_leaves_the_session_intact(csrf_client):
    _sign_in(csrf_client)
    csrf_client.post("/logout")
    assert csrf_client.get("/dashboard").status_code == 200


def test_invalid_token_explains_itself(csrf_client):
    response = csrf_client.post(
        "/login",
        data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD, "csrf_token": "nonsense"},
        follow_redirects=True,
    )
    assert "That form expired" in response.get_data(as_text=True)
