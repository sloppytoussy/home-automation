from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

from collector.pihole import PiHoleClient
from shared.auth.blueprint import auth_bp
from shared.auth.decorators import require_auth

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key-replace-in-production")
app.register_blueprint(auth_bp)
log = app.logger

_pihole: PiHoleClient | None = None


def service_unavailable(exc: Exception):
    log.error("InfluxDB error: %s", exc, exc_info=True)
    return jsonify({"error": "InfluxDB unavailable"}), 503


def get_pihole() -> PiHoleClient:
    global _pihole
    if _pihole is None:
        _pihole = PiHoleClient(
            host=os.environ["PIHOLE_HOST"],
            password=os.environ["PIHOLE_PASSWORD"],
            port=int(os.environ.get("PIHOLE_PORT", 80)),
            tls=os.environ.get("PIHOLE_TLS", "false").lower() == "true",
        )
    return _pihole


@app.route("/")
@require_auth
def index():
    return render_template("index.html")


@app.route("/api/summary")
@require_auth
def api_summary():
    try:
        return jsonify(get_pihole().summary())
    except Exception as exc:
        return service_unavailable(exc)


@app.route("/api/top_domains")
@require_auth
def api_top_domains():
    try:
        return jsonify(get_pihole().top_domains(10))
    except Exception as exc:
        return service_unavailable(exc)


@app.route("/api/top_blocked")
@require_auth
def api_top_blocked():
    try:
        return jsonify(get_pihole().top_blocked(10))
    except Exception as exc:
        return service_unavailable(exc)


@app.route("/api/top_clients")
@require_auth
def api_top_clients():
    try:
        return jsonify(get_pihole().top_clients(10))
    except Exception as exc:
        return service_unavailable(exc)


@app.route("/api/query_types")
@require_auth
def api_query_types():
    try:
        return jsonify(get_pihole().query_types())
    except Exception as exc:
        return service_unavailable(exc)


@app.route("/api/history")
@require_auth
def api_history():
    try:
        return jsonify(get_pihole().history())
    except Exception as exc:
        return service_unavailable(exc)


@app.route("/api/recent")
@require_auth
def api_recent():
    try:
        return jsonify(get_pihole().recent_queries(50))
    except Exception as exc:
        return service_unavailable(exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DASHBOARD_PORT", 5000)))
