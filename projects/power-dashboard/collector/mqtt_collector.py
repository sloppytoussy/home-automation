from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import requests
import yaml

from shared.db import influx

try:
    from shared.utils import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)


CONFIG_PATH = Path(__file__).parent.parent / "config" / "power_collector.yaml"
DEFAULT_BUFFER_SIZE = 100

log = get_logger(__name__)


class ConfigError(ValueError):
    """Raised when collector configuration is invalid."""


class PowerMQTTCollector:
    """MQTT and optional REST collector for configured power devices."""

    def __init__(self, config: dict[str, Any]):
        self._config = self._validate_config(config)
        mqtt_config = self._config["mqtt"]
        self._stop_event = threading.Event()
        self._rest_thread: threading.Thread | None = None
        self._buffer: list[dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_limit = int(self._config.get("buffer", {}).get("max_readings", DEFAULT_BUFFER_SIZE))
        self._topic_routes = self._build_topic_routes(self._config["devices"])
        self._client = mqtt.Client(client_id=mqtt_config.get("client_id", "power-dashboard-collector"))
        username = os.getenv(mqtt_config.get("username_env", "MQTT_USERNAME"), "")
        if username:
            password = os.getenv(mqtt_config.get("password_env", "MQTT_PASSWORD"), "")
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def buffered_count(self) -> int:
        with self._buffer_lock:
            return len(self._buffer)

    @property
    def subscribed_topics(self) -> list[str]:
        return [route["subscribe_topic"] for route in self._topic_routes]

    def start(self) -> None:
        mqtt_config = self._config["mqtt"]
        host = os.getenv(mqtt_config.get("host_env", "MQTT_BROKER_HOST"), mqtt_config.get("default_host", "localhost"))
        port = int(os.getenv(mqtt_config.get("port_env", "MQTT_BROKER_PORT"), mqtt_config.get("default_port", 1883)))
        self._connect_with_backoff(host, port)
        self._client.loop_start()
        self._start_rest_polling()
        log.info("Power MQTT collector started", extra={"host": host, "port": port})

    def stop(self) -> None:
        self._stop_event.set()
        if self._rest_thread and self._rest_thread.is_alive():
            self._rest_thread.join(timeout=5)
        self._client.loop_stop()
        self._client.disconnect()
        log.info("Power MQTT collector stopped")

    def _connect_with_backoff(self, host: str, port: int) -> None:
        reconnect = self._config["mqtt"].get("reconnect", {})
        max_tries = int(reconnect.get("max_tries", 5))
        base_delay = int(reconnect.get("base_delay_seconds", 2))
        max_delay = int(reconnect.get("max_delay_seconds", 60))
        last_error: OSError | None = None

        for attempt in range(max_tries):
            try:
                self._client.connect(host, port)
                return
            except OSError as exc:
                last_error = exc
                delay = min(base_delay * 2 ** attempt, max_delay)
                log.warning(
                    "MQTT connect failed; retrying",
                    extra={"attempt": attempt + 1, "max_tries": max_tries, "delay_seconds": delay},
                )
                if attempt < max_tries - 1:
                    time.sleep(delay)
        raise ConnectionError(f"MQTT connect failed after {max_tries} attempts: {last_error}")

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict[str, Any], rc: int) -> None:
        if rc != 0:
            log.error("MQTT connect failed", extra={"rc": rc})
            return
        for route in self._topic_routes:
            client.subscribe(route["subscribe_topic"])
            log.info("Subscribed to power topic", extra={"topic": route["subscribe_topic"]})

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc == 0 or self._stop_event.is_set():
            return
        log.warning("MQTT disconnected unexpectedly", extra={"rc": rc})
        try:
            client.reconnect()
        except OSError as exc:
            log.error("MQTT reconnect failed", extra={"error": str(exc)})

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode("utf-8")
        try:
            reading = self.parse_message(msg.topic, payload)
            if reading is None:
                return
            self._write_or_buffer(reading)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            log.warning("Failed to parse power MQTT message", extra={"topic": msg.topic, "error": str(exc)})

    def parse_message(self, topic: str, payload: str) -> dict[str, Any] | None:
        for route in self._topic_routes:
            match = route["regex"].match(topic)
            if not match:
                continue
            groups = match.groupdict()
            metric = groups.get("metric")
            field = route["metric_fields"].get(metric)
            if not field:
                return None
            circuit_cfg = route["circuits"].get(groups.get("channel") or groups.get("sensor"))
            if not circuit_cfg:
                return None
            value = self._parse_payload(payload, route["payload"])
            return self._build_reading(
                device=route["device"],
                circuit_cfg=circuit_cfg,
                source="mqtt",
                fields={field: value},
            )
        return None

    def poll_iotawatt_rest_once(self) -> list[dict[str, Any]]:
        readings: list[dict[str, Any]] = []
        for device in self._config["devices"]:
            rest = device.get("rest", {})
            if not device.get("enabled", True) or not rest.get("enabled", False):
                continue
            base_url = os.getenv(rest.get("base_url_env", "IOTAWATT_BASE_URL"), "")
            if not base_url:
                continue
            response = requests.get(
                f"{base_url.rstrip('/')}{rest.get('query_path', '/query')}",
                timeout=float(rest.get("timeout_seconds", 5)),
            )
            response.raise_for_status()
            payload = response.json()
            readings.extend(self._parse_rest_payload(device, payload))
        for reading in readings:
            self._write_or_buffer(reading)
        return readings

    def _start_rest_polling(self) -> None:
        enabled = any(device.get("rest", {}).get("enabled", False) for device in self._config["devices"])
        if not enabled:
            return
        self._rest_thread = threading.Thread(target=self._rest_loop, name="power-iotawatt-rest", daemon=True)
        self._rest_thread.start()

    def _rest_loop(self) -> None:
        while not self._stop_event.is_set():
            interval = self._rest_interval_seconds()
            try:
                self.poll_iotawatt_rest_once()
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                log.warning("IotaWatt REST poll failed", extra={"error": str(exc)})
            self._stop_event.wait(interval)

    def _rest_interval_seconds(self) -> float:
        intervals = [
            float(device.get("rest", {}).get("interval_seconds", 30))
            for device in self._config["devices"]
            if device.get("rest", {}).get("enabled", False)
        ]
        return min(intervals) if intervals else 30.0

    def _parse_rest_payload(self, device: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("REST payload must be a JSON object")
        circuits = self._circuits_by_key(device, "sensor")
        readings = []
        for sensor, value in payload.items():
            circuit_cfg = circuits.get(str(sensor))
            if not circuit_cfg:
                continue
            fields = self._rest_fields(value)
            if fields:
                readings.append(self._build_reading(device=device, circuit_cfg=circuit_cfg, source="rest", fields=fields))
        return readings

    def _rest_fields(self, value: Any) -> dict[str, float]:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return {"watts": float(value)}
        if not isinstance(value, dict):
            raise ValueError("REST sensor value must be a number or object")
        fields = {}
        if "watts" in value:
            fields["watts"] = self._float_value(value["watts"])
        if "wh" in value:
            fields["watt_hours"] = self._float_value(value["wh"])
        return fields

    def _parse_payload(self, payload: str, payload_type: str) -> float:
        if payload_type == "scalar_float":
            return self._float_value(payload)
        if payload_type == "json_value":
            decoded = json.loads(payload)
            if not isinstance(decoded, dict) or "value" not in decoded:
                raise ValueError("JSON payload must contain value")
            return self._float_value(decoded["value"])
        raise ValueError(f"unsupported payload parser: {payload_type}")

    def _build_reading(
        self,
        *,
        device: dict[str, Any],
        circuit_cfg: dict[str, Any],
        source: str,
        fields: dict[str, float],
    ) -> dict[str, Any]:
        if not fields:
            raise ValueError("reading must include at least one field")
        return {
            "measurement": self._config.get("influx", {}).get("measurement", "power_readings"),
            "tags": {
                "device_id": str(device["id"]),
                "device_type": str(device["type"]),
                "circuit": str(circuit_cfg["circuit"]),
                "phase": str(circuit_cfg.get("phase", "none")),
                "source": source,
            },
            "fields": fields,
        }

    def _write_or_buffer(self, reading: dict[str, Any]) -> None:
        try:
            influx.write_point(
                measurement=reading["measurement"],
                tags=reading["tags"],
                fields=reading["fields"],
            )
            self._drain_buffer()
        except Exception as exc:
            log.error("InfluxDB write failed: %s", exc)
            self._append_buffer(reading)

    def _drain_buffer(self) -> None:
        with self._buffer_lock:
            while self._buffer:
                buffered = self._buffer.pop(0)
                try:
                    influx.write_point(
                        measurement=buffered["measurement"],
                        tags=buffered["tags"],
                        fields=buffered["fields"],
                    )
                except Exception as exc:
                    log.error("Buffer drain failed: %s", exc)
                    self._buffer.insert(0, buffered)
                    break

    def _append_buffer(self, reading: dict[str, Any]) -> None:
        with self._buffer_lock:
            self._append_buffer_locked(reading)

    def _append_buffer_locked(self, reading: dict[str, Any]) -> None:
        if len(self._buffer) >= self._buffer_limit:
            self._buffer.pop(0)
            log.warning("Power reading buffer full; dropping oldest reading")
        self._buffer.append(reading)

    def _build_topic_routes(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        routes = []
        for device in devices:
            if not device.get("enabled", True):
                continue
            for topic_config in device.get("topic_patterns", []):
                circuit_key = "channel" if "{channel}" in topic_config["pattern"] else "sensor"
                circuits = self._circuits_by_key(device, circuit_key)
                pattern = topic_config["pattern"].format(device_id=device["id"], channel="+", sensor="+", metric="+")
                regex = self._topic_regex(topic_config["pattern"], str(device["id"]))
                routes.append({
                    "device": device,
                    "subscribe_topic": pattern,
                    "regex": regex,
                    "payload": topic_config["payload"],
                    "metric_fields": topic_config.get("metric_fields", {}),
                    "circuits": circuits,
                })
        return routes

    def _circuits_by_key(self, device: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
        return {str(circuit[key]): circuit for circuit in device.get("circuits", []) if key in circuit}

    def _topic_regex(self, pattern: str, device_id: str) -> re.Pattern[str]:
        regex = re.escape(pattern)
        replacements = {
            r"\{device_id\}": re.escape(device_id),
            r"\{channel\}": r"(?P<channel>[^/]+)",
            r"\{sensor\}": r"(?P<sensor>[^/]+)",
            r"\{metric\}": r"(?P<metric>[^/]+)",
        }
        for token, replacement in replacements.items():
            regex = regex.replace(token, replacement)
        return re.compile(f"^{regex}$")

    def _float_value(self, value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("value must be numeric")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("value must be numeric") from exc

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise ConfigError("config must be a dictionary")
        if "mqtt" not in config:
            raise ConfigError("config must include mqtt settings")
        if "devices" not in config or not isinstance(config["devices"], list):
            raise ConfigError("config must include devices list")
        if int(config.get("buffer", {}).get("max_readings", DEFAULT_BUFFER_SIZE)) <= 0:
            raise ConfigError("buffer max_readings must be positive")
        return config


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open() as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ConfigError("collector config must be a dictionary")
    return config


def run_until_stopped(collector: PowerMQTTCollector) -> None:
    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    collector.start()
    try:
        while not stop_event.is_set():
            stop_event.wait(1)
    finally:
        collector.stop()
