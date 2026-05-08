from __future__ import annotations

from functools import wraps
from urllib.parse import urlencode

from flask import jsonify, redirect, request

from .manager import get_session_user


# Decoration convention: write routes that must be admin-only carry both
# @require_auth (outer) and @require_admin (inner).  The outer @require_auth
# ensures that unauthenticated browser clients receive a redirect to the login
# page rather than a raw JSON 401 from @require_admin.  This stacking is
# intentional and consistent across all dashboards.


def wants_json_response() -> bool:
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    if request.accept_mimetypes["application/json"]:
        return (
            request.accept_mimetypes["application/json"]
            >= request.accept_mimetypes["text/html"]
        )
    return False


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if get_session_user():
            return f(*args, **kwargs)
        if wants_json_response():
            return jsonify({"error": "authentication required"}), 401
        query = urlencode({"next": request.url})
        return redirect(f"/auth/login?{query}")

    return wrapper


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_session_user()
        if not user:
            return jsonify({"error": "authentication required"}), 401
        if user.get("role") != "admin":
            return jsonify({"error": "admin access required"}), 403
        return f(*args, **kwargs)

    return wrapper
