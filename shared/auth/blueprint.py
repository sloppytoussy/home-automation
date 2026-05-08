from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

from .manager import get_session_user, login_user, logout_user, verify_password

auth_bp = Blueprint(
    "auth",
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    url_prefix="/auth",
)


def wants_json_response() -> bool:
    if request.is_json:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    if request.accept_mimetypes["application/json"]:
        return (
            request.accept_mimetypes["application/json"]
            >= request.accept_mimetypes["text/html"]
        )
    return False


def request_login_body() -> dict[str, Any]:
    if request.is_json:
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}
    return request.form.to_dict()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": user["username"],
        "role": user["role"],
        "display_name": user.get("display_name") or user["username"],
    }


def session_lifetime() -> timedelta:
    raw_hours = os.getenv("AUTH_SESSION_LIFETIME_HOURS", "24")
    try:
        hours = int(raw_hours)
    except (TypeError, ValueError):
        hours = 24
    return timedelta(hours=max(hours, 1))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    current_user = get_session_user()
    if request.method == "GET":
        if current_user:
            return redirect(request.args.get("next") or "/")
        return render_template("auth/login.html", next_url=request.args.get("next", ""))

    if current_user:
        return jsonify(public_user(current_user))

    body = request_login_body()
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))
    if not verify_password(username, password):
        current_app.logger.warning("Invalid login attempt for username %s", username)
        if wants_json_response():
            return jsonify({"error": "invalid credentials"}), 401
        return render_template(
            "auth/login.html",
            error="Invalid username or password.",
            next_url=request.args.get("next") or body.get("next", ""),
        ), 401

    login_user(username)
    session.permanent = bool(body.get("remember"))
    current_app.permanent_session_lifetime = session_lifetime()
    user = get_session_user()
    if not user:
        current_app.logger.error("Session user missing after successful login")
        return jsonify({"error": "service unavailable"}), 503
    if wants_json_response():
        return jsonify(public_user(user))
    return redirect(request.args.get("next") or body.get("next") or "/")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    if wants_json_response():
        return jsonify({"logged_out": True})
    return redirect("/auth/login")


@auth_bp.route("/me")
def me():
    user = get_session_user()
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({**public_user(user), "logged_in": True})
