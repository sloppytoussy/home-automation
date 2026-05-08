from __future__ import annotations

from typing import Any

import pytest
from flask import Flask, session

from shared.auth.blueprint import auth_bp


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.register_blueprint(auth_bp)

    def fake_get_session_user() -> dict[str, Any] | None:
        if "username" not in session:
            return None
        return {
            "username": session["username"],
            "role": session["role"],
            "display_name": session["display_name"],
        }

    def fake_login_user(username: str) -> None:
        session["username"] = username
        session["role"] = "admin" if username == "admin" else "user"
        session["display_name"] = username.title()

    def fake_logout_user() -> None:
        session.clear()

    monkeypatch.setattr("shared.auth.blueprint.get_session_user", fake_get_session_user)
    monkeypatch.setattr("shared.auth.blueprint.login_user", fake_login_user)
    monkeypatch.setattr("shared.auth.blueprint.logout_user", fake_logout_user)
    monkeypatch.setattr(
        "shared.auth.blueprint.verify_password",
        lambda username, password: username in {"admin", "viewer"} and password == "secret",
    )
    return flask_app


def test_login_valid_json_returns_user_dict(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "username": "admin",
        "role": "admin",
        "display_name": "Admin",
    }


def test_login_valid_json_sets_session(app: Flask) -> None:
    client = app.test_client()
    client.post("/auth/login", json={"username": "admin", "password": "secret"})
    with client.session_transaction() as saved_session:
        assert saved_session["username"] == "admin"
        assert saved_session["role"] == "admin"


def test_login_invalid_json_returns_401(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid credentials"}


def test_login_accepts_form_body(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        data={"username": "viewer", "password": "secret"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.get_json()["username"] == "viewer"


def test_login_invalid_form_renders_template(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        data={"username": "viewer", "password": "wrong"},
    )
    assert response.status_code == 401
    assert b"Invalid username or password" in response.data


def test_login_next_param_redirects_after_html_login(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login?next=/dashboard",
        data={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/dashboard"


def test_login_hidden_next_redirects_after_html_login(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        data={"username": "admin", "password": "secret", "next": "/from-form"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/from-form"


def test_login_defaults_redirect_to_root_for_html(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        data={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_login_already_logged_in_returns_current_user(app: Flask) -> None:
    client = app.test_client()
    with client.session_transaction() as saved_session:
        saved_session["username"] = "admin"
        saved_session["role"] = "admin"
        saved_session["display_name"] = "Admin"
    response = client.post("/auth/login", json={"username": "viewer", "password": "secret"})
    assert response.status_code == 200
    assert response.get_json()["username"] == "admin"


def test_logout_clears_session_and_redirects_html(app: Flask) -> None:
    client = app.test_client()
    with client.session_transaction() as saved_session:
        saved_session["username"] = "admin"
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/login"
    with client.session_transaction() as saved_session:
        assert "username" not in saved_session


def test_logout_json_returns_logged_out(app: Flask) -> None:
    response = app.test_client().post("/auth/logout", json={})
    assert response.status_code == 200
    assert response.get_json() == {"logged_out": True}


def test_me_logged_in_returns_full_user_dict(app: Flask) -> None:
    client = app.test_client()
    with client.session_transaction() as saved_session:
        saved_session["username"] = "viewer"
        saved_session["role"] = "user"
        saved_session["display_name"] = "Viewer"
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.get_json() == {
        "username": "viewer",
        "role": "user",
        "display_name": "Viewer",
        "logged_in": True,
    }


def test_me_not_logged_in_returns_public_false(app: Flask) -> None:
    response = app.test_client().get("/auth/me")
    assert response.status_code == 200
    assert response.get_json() == {"logged_in": False}


def test_get_login_renders_page(app: Flask) -> None:
    response = app.test_client().get("/auth/login")
    assert response.status_code == 200
    assert b"<form" in response.data


def test_get_login_includes_next_hidden_field(app: Flask) -> None:
    response = app.test_client().get("/auth/login?next=/private")
    assert b'value="/private"' in response.data


def test_get_login_redirects_when_already_logged_in(app: Flask) -> None:
    client = app.test_client()
    with client.session_transaction() as saved_session:
        saved_session["username"] = "admin"
        saved_session["role"] = "admin"
        saved_session["display_name"] = "Admin"
    response = client.get("/auth/login?next=/private")
    assert response.status_code == 302
    assert response.headers["Location"] == "/private"


def test_json_login_sets_permanent_session_when_remember_true(app: Flask) -> None:
    client = app.test_client()
    client.post(
        "/auth/login",
        json={"username": "admin", "password": "secret", "remember": True},
    )
    with client.session_transaction() as saved_session:
        assert saved_session.permanent is True


def test_json_login_without_remember_is_not_permanent(app: Flask) -> None:
    client = app.test_client()
    client.post("/auth/login", json={"username": "admin", "password": "secret"})
    with client.session_transaction() as saved_session:
        assert saved_session.permanent is False


def test_login_empty_json_returns_invalid_credentials(app: Flask) -> None:
    response = app.test_client().post("/auth/login", json={})
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid credentials"}


def test_login_xhr_failure_returns_json(app: Flask) -> None:
    response = app.test_client().post(
        "/auth/login",
        data={"username": "admin", "password": "wrong"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid credentials"}
