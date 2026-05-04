import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

from ..collector.pihole import PiHoleClient

load_dotenv()

app = Flask(__name__)

_pihole: PiHoleClient | None = None


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
def index():
    return render_template("index.html")


@app.route("/api/summary")
def api_summary():
    try:
        return jsonify(get_pihole().summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/top_domains")
def api_top_domains():
    try:
        return jsonify(get_pihole().top_domains(10))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/top_blocked")
def api_top_blocked():
    try:
        return jsonify(get_pihole().top_blocked(10))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/top_clients")
def api_top_clients():
    try:
        return jsonify(get_pihole().top_clients(10))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/query_types")
def api_query_types():
    try:
        return jsonify(get_pihole().query_types())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/history")
def api_history():
    try:
        return jsonify(get_pihole().history())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/recent")
def api_recent():
    try:
        return jsonify(get_pihole().recent_queries(50))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("DASHBOARD_PORT", 5000)))
