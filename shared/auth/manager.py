from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bcrypt
import yaml
from flask import session
from yaml import YAMLError

LOGGER = logging.getLogger(__name__)
VALID_ROLES = {"admin", "user"}
REQUIRED_FIELDS = {"username", "password_hash", "role"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def users_file_path() -> Path:
    raw_path = os.getenv("AUTH_USERS_FILE", "infrastructure/users.yaml")
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return repo_root() / path


def load_users() -> list[dict[str, Any]]:
    path = users_file_path()
    try:
        with path.open() as users_file:
            data = yaml.safe_load(users_file) or {}
    except FileNotFoundError:
        raise
    except YAMLError as exc:
        raise ValueError("users file is not valid YAML") from exc

    users = data.get("users", []) if isinstance(data, dict) else []
    if users is None:
        return []
    if not isinstance(users, list):
        raise ValueError("users must be a list")

    validated: list[dict[str, Any]] = []
    for index, user in enumerate(users):
        if not isinstance(user, dict):
            raise ValueError(f"user entry {index} must be a mapping")
        missing = REQUIRED_FIELDS - set(user)
        if missing:
            raise ValueError(f"user entry {index} missing required fields")
        if user["role"] not in VALID_ROLES:
            raise ValueError(f"user entry {index} has invalid role")
        validated.append(dict(user))
    return validated


def find_user(username: str) -> dict[str, Any] | None:
    normalized = str(username).casefold()
    for user in load_users():
        if str(user.get("username", "")).casefold() == normalized:
            return user
    return None


def verify_password(username: str, password: str) -> bool:
    try:
        user = find_user(username)
        if not user:
            return False
        password_hash = str(user["password_hash"]).encode("utf-8")
        password_bytes = str(password).encode("utf-8")
        return bool(bcrypt.checkpw(password_bytes, password_hash))
    except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
        LOGGER.warning("Password verification failed safely: %s", exc)
        return False


def get_session_user() -> dict[str, Any] | None:
    username = session.get("username")
    role = session.get("role")
    if not username or not role:
        return None
    return {
        "username": username,
        "role": role,
        "display_name": session.get("display_name") or username,
    }


def login_user(username: str) -> None:
    user = find_user(username)
    if not user:
        raise ValueError("unknown user")
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["display_name"] = user.get("display_name") or user["username"]
    session["logged_in_at"] = datetime.now(timezone.utc).isoformat()
    session.modified = True


def logout_user() -> None:
    session.clear()
    session.modified = True
