from __future__ import annotations

from typing import Any

import pytest
from flask import Flask, jsonify

from shared.auth.decorators import require_admin, require_auth


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    state: dict[str, Any] = {"user": None}

    def get_user() -> dict[str, Any] | None:
        return state["user"]

    monkeypatch.setattr("shared.auth.decorators.get_session_user", get_user)
    flask_app.config["AUTH_TEST_STATE"] = state

    @flask_app.route("/private")
    @require_auth
    def private():
        return jsonify({"ok": True})

    @flask_app.route("/admin")
    @require_auth
    @require_admin
    def admin():
        return jsonify({"admin": True})

    @flask_app.route("/admin-direct")
    @require_admin
    def admin_direct():
        return jsonify({"admin": True})

    return flask_app


def set_user(app: Flask, role: str = "user") -> None:
    app.config["AUTH_TEST_STATE"]["user"] = {
        "username": role,
        "role": role,
        "display_name": role.title(),
    }


def test_require_auth_redirects_html_request(app: Flask) -> None:
    response = app.test_client().get("/private")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/login?next=")


def test_require_auth_json_request_returns_401(app: Flask) -> None:
    response = app.test_client().get("/private", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_require_auth_xhr_request_returns_401(app: Flask) -> None:
    response = app.test_client().get(
        "/private",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_require_auth_authenticated_passes_through(app: Flask) -> None:
    set_user(app)
    response = app.test_client().get("/private")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_require_auth_preserves_next_url(app: Flask) -> None:
    response = app.test_client().get("/private?tab=energy")
    assert "%2Fprivate%3Ftab%3Denergy" in response.headers["Location"]


def test_require_auth_json_accept_priority_returns_json(app: Flask) -> None:
    response = app.test_client().get(
        "/private",
        headers={"Accept": "application/json,text/html;q=0.5"},
    )
    assert response.status_code == 401


def test_require_auth_html_accept_priority_redirects(app: Flask) -> None:
    response = app.test_client().get(
        "/private",
        headers={"Accept": "text/html,application/json;q=0.5"},
    )
    assert response.status_code == 302


def test_require_admin_allows_admin_role(app: Flask) -> None:
    set_user(app, "admin")
    response = app.test_client().get("/admin")
    assert response.status_code == 200
    assert response.get_json() == {"admin": True}


def test_require_admin_rejects_user_role(app: Flask) -> None:
    set_user(app, "user")
    response = app.test_client().get("/admin")
    assert response.status_code == 403
    assert response.get_json() == {"error": "admin access required"}


def test_require_admin_rejects_missing_role(app: Flask) -> None:
    app.config["AUTH_TEST_STATE"]["user"] = {"username": "viewer"}
    response = app.test_client().get("/admin")
    assert response.status_code == 403


def test_require_admin_unauthenticated_json_fires_require_auth_first(app: Flask) -> None:
    response = app.test_client().get("/admin", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_require_admin_unauthenticated_html_fires_require_auth_first(app: Flask) -> None:
    response = app.test_client().get("/admin")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/auth/login")


def test_require_admin_direct_unauthenticated_returns_401(app: Flask) -> None:
    response = app.test_client().get("/admin-direct")
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_stacked_decorators_keep_route_name(app: Flask) -> None:
    assert app.view_functions["admin"].__name__ == "admin"


def test_require_auth_keeps_route_name(app: Flask) -> None:
    assert app.view_functions["private"].__name__ == "private"


def test_require_admin_keeps_route_name(app: Flask) -> None:
    assert app.view_functions["admin_direct"].__name__ == "admin_direct"


def test_stacked_decorators_user_cannot_reach_admin_route(app: Flask) -> None:
    set_user(app, "user")
    response = app.test_client().get("/admin")
    assert response.get_json() == {"error": "admin access required"}


def test_stacked_decorators_admin_can_reach_admin_route(app: Flask) -> None:
    set_user(app, "admin")
    response = app.test_client().get("/admin")
    assert response.get_json() == {"admin": True}


def test_unauthenticated_api_does_not_redirect(app: Flask) -> None:
    response = app.test_client().get("/private", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert "Location" not in response.headers


def test_authenticated_request_ignores_accept_header(app: Flask) -> None:
    set_user(app)
    response = app.test_client().get("/private", headers={"Accept": "application/json"})
    assert response.status_code == 200
