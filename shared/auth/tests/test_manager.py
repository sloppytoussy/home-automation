from __future__ import annotations

from pathlib import Path

import bcrypt
import pytest
from flask import Flask, session

from shared.auth import manager


@pytest.fixture
def users_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "users.yaml"
    monkeypatch.setenv("AUTH_USERS_FILE", str(path))
    return path


@pytest.fixture
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    return flask_app


def password_hash(password: str = "secret") -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def write_users(path: Path, hash_value: str | None = None) -> None:
    path.write_text(
        "\n".join(
            [
                "users:",
                "  - username: admin",
                f"    password_hash: \"{hash_value or password_hash()}\"",
                "    role: admin",
                "    display_name: Admin",
                "  - username: viewer",
                f"    password_hash: \"{password_hash('viewerpass')}\"",
                "    role: user",
                "    display_name: Viewer",
            ]
        )
    )


def test_users_file_path_uses_env_path(users_file: Path) -> None:
    assert manager.users_file_path() == users_file


def test_users_file_path_resolves_relative_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_USERS_FILE", "custom/users.yaml")
    assert manager.users_file_path() == manager.repo_root() / "custom/users.yaml"


def test_users_file_path_defaults_to_infrastructure_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_USERS_FILE", raising=False)
    assert manager.users_file_path() == manager.repo_root() / "infrastructure/users.yaml"


def test_load_users_reads_valid_file(users_file: Path) -> None:
    write_users(users_file)
    users = manager.load_users()
    assert [user["username"] for user in users] == ["admin", "viewer"]


def test_load_users_returns_display_name(users_file: Path) -> None:
    write_users(users_file)
    assert manager.load_users()[0]["display_name"] == "Admin"


def test_load_users_raises_when_file_missing(users_file: Path) -> None:
    with pytest.raises(FileNotFoundError):
        manager.load_users()


def test_load_users_raises_for_missing_username(users_file: Path) -> None:
    users_file.write_text("users:\n  - password_hash: abc\n    role: admin\n")
    with pytest.raises(ValueError):
        manager.load_users()


def test_load_users_raises_for_missing_password_hash(users_file: Path) -> None:
    users_file.write_text("users:\n  - username: admin\n    role: admin\n")
    with pytest.raises(ValueError):
        manager.load_users()


def test_load_users_raises_for_missing_role(users_file: Path) -> None:
    users_file.write_text("users:\n  - username: admin\n    password_hash: abc\n")
    with pytest.raises(ValueError):
        manager.load_users()


def test_load_users_raises_for_invalid_role(users_file: Path) -> None:
    users_file.write_text("users:\n  - username: admin\n    password_hash: abc\n    role: owner\n")
    with pytest.raises(ValueError):
        manager.load_users()


def test_load_users_empty_file_returns_empty_list(users_file: Path) -> None:
    users_file.write_text("")
    assert manager.load_users() == []


def test_load_users_empty_users_returns_empty_list(users_file: Path) -> None:
    users_file.write_text("users:\n")
    assert manager.load_users() == []


def test_load_users_raises_when_users_is_not_list(users_file: Path) -> None:
    users_file.write_text("users:\n  admin:\n    role: admin\n")
    with pytest.raises(ValueError):
        manager.load_users()


def test_load_users_raises_when_entry_is_not_mapping(users_file: Path) -> None:
    users_file.write_text("users:\n  - admin\n")
    with pytest.raises(ValueError):
        manager.load_users()


def test_load_users_raises_for_invalid_yaml(users_file: Path) -> None:
    users_file.write_text("users: [")
    with pytest.raises(ValueError):
        manager.load_users()


def test_find_user_known_username(users_file: Path) -> None:
    write_users(users_file)
    assert manager.find_user("admin")["role"] == "admin"


def test_find_user_unknown_username(users_file: Path) -> None:
    write_users(users_file)
    assert manager.find_user("missing") is None


def test_find_user_case_insensitive(users_file: Path) -> None:
    write_users(users_file)
    assert manager.find_user("ADMIN")["username"] == "admin"


def test_verify_password_correct_password(users_file: Path) -> None:
    write_users(users_file, password_hash("correct"))
    assert manager.verify_password("admin", "correct") is True


def test_verify_password_wrong_password(users_file: Path) -> None:
    write_users(users_file, password_hash("correct"))
    assert manager.verify_password("admin", "wrong") is False


def test_verify_password_unknown_user(users_file: Path) -> None:
    write_users(users_file)
    assert manager.verify_password("missing", "secret") is False


def test_verify_password_never_raises_on_bad_hash(users_file: Path) -> None:
    write_users(users_file, "not-a-bcrypt-hash")
    assert manager.verify_password("admin", "secret") is False


def test_verify_password_never_raises_on_missing_file(users_file: Path) -> None:
    assert manager.verify_password("admin", "secret") is False


def test_verify_password_casts_bad_input_safely(users_file: Path) -> None:
    write_users(users_file)
    assert manager.verify_password(None, None) is False


def test_get_session_user_returns_user(app: Flask) -> None:
    with app.test_request_context("/"):
        session["username"] = "admin"
        session["role"] = "admin"
        session["display_name"] = "Admin"
        assert manager.get_session_user() == {
            "username": "admin",
            "role": "admin",
            "display_name": "Admin",
        }


def test_get_session_user_uses_username_as_display_fallback(app: Flask) -> None:
    with app.test_request_context("/"):
        session["username"] = "admin"
        session["role"] = "admin"
        assert manager.get_session_user()["display_name"] == "admin"


def test_get_session_user_empty_session_returns_none(app: Flask) -> None:
    with app.test_request_context("/"):
        assert manager.get_session_user() is None


def test_get_session_user_missing_role_returns_none(app: Flask) -> None:
    with app.test_request_context("/"):
        session["username"] = "admin"
        assert manager.get_session_user() is None


def test_login_user_sets_session_keys(users_file: Path, app: Flask) -> None:
    write_users(users_file)
    with app.test_request_context("/"):
        manager.login_user("admin")
        assert session["username"] == "admin"
        assert session["role"] == "admin"
        assert session["display_name"] == "Admin"
        assert "logged_in_at" in session


def test_login_user_marks_session_modified(users_file: Path, app: Flask) -> None:
    write_users(users_file)
    with app.test_request_context("/"):
        manager.login_user("admin")
        assert session.modified is True


def test_login_user_unknown_user_raises(users_file: Path, app: Flask) -> None:
    write_users(users_file)
    with app.test_request_context("/"):
        with pytest.raises(ValueError):
            manager.login_user("missing")


def test_logout_user_clears_session(app: Flask) -> None:
    with app.test_request_context("/"):
        session["username"] = "admin"
        manager.logout_user()
        assert dict(session) == {}


def test_logout_user_marks_session_modified(app: Flask) -> None:
    with app.test_request_context("/"):
        manager.logout_user()
        assert session.modified is True
