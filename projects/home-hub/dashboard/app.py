from __future__ import annotations

import os
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from yaml import YAMLError

from shared.auth import auth_bp, require_auth
from shared.auth.manager import get_session_user


for _env_candidate in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent.parent / ".env",
]:
    if _env_candidate.exists():
        load_dotenv(_env_candidate, override=False)
        break

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key-replace-in-production")
app.register_blueprint(auth_bp)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "hub.yaml"
DEFAULT_TIMEOUT_SECONDS = 2
MAX_SERVICE_WORKERS = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    try:
        with CONFIG_PATH.open() as config_file:
            config = yaml.safe_load(config_file) or {}
    except (FileNotFoundError, YAMLError) as exc:
        app.logger.warning("Unable to load hub config: %s", exc)
        return {}

    for service in config.get("services", []):
        service_id = service.get("id")
        if service_id:
            override = os.getenv(f"HUB_SERVICE_{service_id.upper()}_URL")
            if override:
                service["url"] = override
    return config


def hub_timeout(config: dict[str, Any]) -> int | float:
    return config.get("hub", {}).get("fetch_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)


def safe_get(data: dict[str, Any], key: str) -> Any:
    return data.get(key) if isinstance(data, dict) else None


def extract_metrics(service_id: str, data: dict | list) -> dict:
    try:
        if service_id == "dns_monitor":
            return {
                "queries_today": safe_get(data, "dns_queries_today"),
                "blocked_pct": safe_get(data, "ads_percentage_today"),
            }
        if service_id == "power_dashboard":
            return {
                "remaining_kwh": safe_get(data, "remaining_kwh"),
                "days_left": safe_get(data, "days_left"),
                "consumption_rate_kwh_per_day": safe_get(data, "consumption_rate_kwh_per_day"),
            }
        if service_id == "water_monitor":
            tanks = data if isinstance(data, list) else []
            return {
                "tanks": [
                    {
                        "id": tank.get("id"),
                        "name": tank.get("name"),
                        "level_pct": tank.get("level_pct"),
                        "volume_liters": tank.get("volume_liters"),
                    }
                    for tank in tanks
                    if isinstance(tank, dict)
                ]
            }
        if service_id == "solar_battery":
            return {
                "battery_soc_pct": safe_get(data, "battery_soc_pct"),
                "pv_power_w": safe_get(data, "pv_power_w"),
                "data_available": safe_get(data, "data_available"),
            }
        if service_id == "lighting_control":
            return {
                "devices_on": safe_get(data, "devices_on"),
                "devices_total": safe_get(data, "devices_total"),
                "total_power_w": safe_get(data, "total_power_w"),
            }
    except (AttributeError, TypeError) as exc:
        app.logger.warning("Unable to extract metrics for %s: %s", service_id, exc)
        return {}

    app.logger.warning("Unknown service id for metric extraction: %s", service_id)
    return {}


def service_result(service: dict[str, Any], timeout: int | float) -> dict[str, Any]:
    service_url = service.get("url")
    result = {
        "id": service.get("id"),
        "name": service.get("name"),
        "port": service.get("port"),
        "url": service_url,
        "online": False,
        "data_available": False,
        "key_metrics": {},
        "last_updated": None,
    }
    try:
        response = requests.get(
            urljoin(f"{service_url}/", str(service.get("metrics_endpoint", "")).lstrip("/")),
            timeout=timeout,
        )
        if response.status_code >= 500:
            return result
        result["online"] = True
        try:
            data = response.json()
        except ValueError:
            data = {}
        result["data_available"] = bool(data)
        result["key_metrics"] = extract_metrics(str(service.get("id")), data) if data else {}
        result["last_updated"] = now_iso() if data else None
    except requests.exceptions.RequestException as exc:
        app.logger.warning("Service check failed for %s: %s", service.get("id"), exc)
    return result


def collect_service_statuses(config: dict[str, Any]) -> list[dict[str, Any]]:
    services = config.get("services", [])
    timeout = hub_timeout(config)
    if not services:
        return []

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=MAX_SERVICE_WORKERS) as executor:
        future_to_service = {
            executor.submit(service_result, service, timeout): service
            for service in services
        }
        try:
            completed = as_completed(future_to_service, timeout=(timeout * len(services)) + 1)
            for future in completed:
                service = future_to_service[future]
                try:
                    results[str(service.get("id"))] = future.result()
                except Exception as exc:
                    app.logger.warning("Service future failed for %s: %s", service.get("id"), exc)
                    results[str(service.get("id"))] = service_result_shape(service)
        except TimeoutError as exc:
            app.logger.warning("Service collection timed out: %s", exc)

    return [results.get(str(service.get("id")), service_result_shape(service)) for service in services]


def service_result_shape(service: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": service.get("id"),
        "name": service.get("name"),
        "port": service.get("port"),
        "url": service.get("url"),
        "online": False,
        "data_available": False,
        "key_metrics": {},
        "last_updated": None,
    }


def check_http_health(url: str, health_path: str, timeout: int | float) -> bool:
    try:
        response = requests.get(urljoin(f"{url}/", health_path.lstrip("/")), timeout=timeout)
        return response.status_code == 200
    except Exception as exc:
        app.logger.warning("HTTP health check failed for %s: %s", url, exc)
        return False


def check_mqtt_health(host: str, port: int, timeout: int | float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception as exc:
        app.logger.warning("MQTT health check failed for %s:%s: %s", host, port, exc)
        return False


def check_infrastructure(config: dict) -> dict:
    timeout = hub_timeout(config)
    infrastructure = config.get("infrastructure", {})
    influxdb = infrastructure.get("influxdb", {})
    grafana = infrastructure.get("grafana", {})
    mqtt = infrastructure.get("mqtt", {})
    try:
        mqtt_port = int(mqtt.get("port", 1883))
    except (TypeError, ValueError):
        mqtt_port = 1883
    return {
        "influxdb": {
            "online": check_http_health(influxdb.get("url"), influxdb.get("health_path", "/health"), timeout),
            "url": influxdb.get("url"),
        },
        "grafana": {
            "online": check_http_health(grafana.get("url"), grafana.get("health_path", "/api/health"), timeout),
            "url": grafana.get("url"),
        },
        "mqtt": {
            "online": check_mqtt_health(mqtt.get("host", "localhost"), mqtt_port, timeout),
            "host": mqtt.get("host", "localhost"),
            "port": mqtt_port,
        },
    }


def overview_payload() -> dict[str, Any]:
    config = load_config()
    services = collect_service_statuses(config)
    services_online = sum(1 for service in services if service.get("online"))
    return {
        "services": services,
        "infrastructure": check_infrastructure(config),
        "services_online": services_online,
        "services_total": len(services),
        "data_available": any(service.get("data_available") for service in services),
        "last_updated": now_iso(),
    }


@app.route("/")
@require_auth
def index():
    user = get_session_user() or {}
    config = load_config()
    return render_template(
        "index.html",
        username=user.get("username"),
        role=user.get("role"),
        services=config.get("services", []),
    )


@app.route("/api/hub/overview")
def api_hub_overview():
    try:
        return jsonify(overview_payload())
    except ValueError as exc:
        app.logger.warning("Bad request: %s", exc)
        return jsonify({"error": "invalid input"}), 400
    except Exception as exc:
        app.logger.error("Hub error: %s", exc, exc_info=True)
        return jsonify({"error": "service unavailable"}), 503


@app.route("/api/hub/status")
def api_hub_status():
    try:
        config = load_config()
        services = collect_service_statuses(config)
        return jsonify({
            "online": True,
            "services_total": len(services),
            "services_online": sum(1 for service in services if service.get("online")),
            "last_updated": now_iso(),
        })
    except ValueError as exc:
        app.logger.warning("Bad request: %s", exc)
        return jsonify({"error": "invalid input"}), 400
    except Exception as exc:
        app.logger.error("Hub error: %s", exc, exc_info=True)
        return jsonify({"error": "service unavailable"}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("HOME_HUB_PORT", 5006)))
