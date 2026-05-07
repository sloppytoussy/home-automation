from __future__ import annotations

import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import yaml

from . import writer

try:
    from shared.utils import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)


CONFIG_PATH = Path(__file__).parent.parent / "config" / "lighting.yaml"
DEFAULT_BUFFER_SIZE = 200
log = get_logger(__name__)


class ConfigError(ValueError):
    """Raised when lighting collector configuration is invalid."""


class LightingMQTTCollector:
    def __init__(self, config: dict[str, Any]):
        self._config = self._validate_config(config)
        self._devices = {device["id"]: device for device in self._config["devices"]}
        self._devices_by_shelly = {device["shelly_id"]: device for device in self._config["devices"]}
        self._stop_event = threading.Event()
        self._buffer: list[dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        self._last_energy: dict[str, float] = {}
        self._buffer_limit = int(self._config.get("collection", {}).get("buffer_size", DEFAULT_BUFFER_SIZE))
        self._client = mqtt.Client(client_id=self._config.get("mqtt", {}).get("client_id", "lighting-control"))
        if os.getenv("MQTT_USERNAME"):
            self._client.username_pw_set(os.getenv("MQTT_USERNAME"), os.getenv("MQTT_PASSWORD", ""))
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def buffered_count(self) -> int:
        with self._buffer_lock:
            return len(self._buffer)

    @property
    def subscribed_topics(self) -> list[str]:
        topics: list[str] = []
        for device in self._config["devices"]:
            sid = device["shelly_id"]
            if device["generation"] == "gen1":
                topics.extend([
                    f"shellies/{sid}/relay/0",
                    f"shellies/{sid}/light/0",
                    f"shellies/{sid}/emeter/0/power",
                    f"shellies/{sid}/emeter/0/energy",
                ])
            else:
                topics.extend([f"{sid}/status/switch:0", f"{sid}/status/light:0", f"{sid}/events/rpc"])
        return topics

    def start(self) -> None:
        mqtt_config = self._config.get("mqtt", {})
        host = os.getenv("MQTT_BROKER_HOST", mqtt_config.get("broker_host", "localhost"))
        port = int(os.getenv("MQTT_BROKER_PORT", mqtt_config.get("broker_port", 1883)))
        self._client.connect(host, port)
        self._client.loop_start()
        self._publish_home_assistant_discovery()
        log.info("Lighting MQTT collector started", extra={"host": host, "port": port})

    def stop(self) -> None:
        self._stop_event.set()
        self._client.loop_stop()
        self._client.disconnect()
        log.info("Lighting MQTT collector stopped")

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict[str, Any], rc: int) -> None:
        if rc != 0:
            log.error("MQTT connect failed", extra={"rc": rc})
            return
        for topic in self.subscribed_topics:
            client.subscribe(topic)
        self._drain_buffer()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc == 0 or self._stop_event.is_set():
            return
        log.warning("MQTT disconnected unexpectedly", extra={"rc": rc})
        try:
            client.reconnect()
        except OSError as exc:
            log.error("MQTT reconnect failed", extra={"error": str(exc)})

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            parsed = self.parse_message(msg.topic, msg.payload.decode("utf-8"))
            if parsed is None:
                log.warning("Unknown lighting MQTT topic", extra={"topic": msg.topic})
                return
            self._write_or_buffer(parsed)
            self._mirror_home_assistant_state(parsed)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            log.warning("Failed to parse lighting MQTT message", extra={"topic": msg.topic, "error": str(exc)})

    def parse_message(self, topic: str, payload: str) -> dict[str, Any] | None:
        for device in self._config["devices"]:
            if device["generation"] == "gen1":
                state = self._parse_gen1(device, topic, payload)
            else:
                state = self._parse_gen2(device, topic, payload)
            if state is not None:
                return {"device": device, "state": state, "source": "mqtt"}
        return None

    def _parse_gen1(self, device: dict[str, Any], topic: str, payload: str) -> dict[str, Any] | None:
        base = f"shellies/{device['shelly_id']}"
        if topic == f"{base}/relay/0":
            value = payload.strip().lower()
            if value not in {"on", "off"}:
                raise ValueError("relay payload must be on or off")
            return {"is_on": value == "on"}
        if topic == f"{base}/light/0":
            data = json.loads(payload)
            return {"is_on": bool(data["ison"]), "brightness_pct": float(data["brightness"])}
        if topic == f"{base}/emeter/0/power":
            return {"power_w": float(payload)}
        if topic == f"{base}/emeter/0/energy":
            return {"energy_wh": float(payload)}
        return None

    def _parse_gen2(self, device: dict[str, Any], topic: str, payload: str) -> dict[str, Any] | None:
        base = device["shelly_id"]
        if topic == f"{base}/status/switch:0":
            return self._state_from_gen2_switch(json.loads(payload))
        if topic == f"{base}/status/light:0":
            data = json.loads(payload)
            return {"is_on": bool(data["output"]), "brightness_pct": float(data["brightness"])}
        if topic == f"{base}/events/rpc":
            data = json.loads(payload)
            params = data.get("params", {})
            switch = params.get("switch:0")
            light = params.get("light:0")
            if switch:
                return self._state_from_gen2_switch(switch)
            if light:
                return {"is_on": bool(light["output"]), "brightness_pct": float(light["brightness"])}
        return None

    def _state_from_gen2_switch(self, data: dict[str, Any]) -> dict[str, Any]:
        state = {"is_on": bool(data["output"])}
        if "apower" in data:
            state["power_w"] = float(data["apower"])
        total = data.get("aenergy", {}).get("total")
        if total is not None:
            state["energy_wh"] = float(total)
        return state

    def _write_or_buffer(self, reading: dict[str, Any]) -> None:
        try:
            self._write_reading(reading)
            self._drain_buffer()
        except Exception as exc:
            log.error("InfluxDB write failed", extra={"error": str(exc)})
            self._append_buffer(reading)

    def _write_reading(self, reading: dict[str, Any]) -> None:
        device = reading["device"]
        state = reading["state"]
        writer.write_state(
            None,
            device["id"],
            device["room"],
            device["type"],
            device["generation"],
            reading["source"],
            state,
        )
        if device.get("has_power_meter") and state.get("power_w") is not None and state.get("energy_wh") is not None:
            total = float(state["energy_wh"])
            previous = self._last_energy.get(device["id"], total)
            self._last_energy[device["id"]] = total
            writer.write_energy(None, device["id"], device["room"], float(state["power_w"]), max(total - previous, 0.0), total)

    def _drain_buffer(self) -> None:
        with self._buffer_lock:
            while self._buffer:
                reading = self._buffer.pop(0)
                try:
                    self._write_reading(reading)
                except Exception as exc:
                    log.error("Lighting buffer drain failed", extra={"error": str(exc)})
                    self._buffer.insert(0, reading)
                    break

    def _append_buffer(self, reading: dict[str, Any]) -> None:
        with self._buffer_lock:
            if len(self._buffer) >= self._buffer_limit:
                self._buffer.pop(0)
                log.warning("Lighting reading buffer full; dropping oldest reading")
            self._buffer.append(reading)

    def _publish_home_assistant_discovery(self) -> None:
        ha = self._config.get("home_assistant", {})
        if not ha.get("enabled", False):
            return
        prefix = ha.get("discovery_prefix", "homeassistant")
        for device in self._config["devices"]:
            payload = {
                "name": device["name"],
                "unique_id": device["id"],
                "state_topic": f"homelab/lighting/{device['id']}/state",
                "command_topic": f"homelab/lighting/{device['id']}/set",
                "payload_on": "ON",
                "payload_off": "OFF",
            }
            self._client.publish(f"{prefix}/light/{device['id']}/config", json.dumps(payload), retain=True)

    def _mirror_home_assistant_state(self, reading: dict[str, Any]) -> None:
        if not self._config.get("home_assistant", {}).get("enabled", False):
            return
        state = reading["state"]
        if "is_on" in state:
            self._client.publish(f"homelab/lighting/{reading['device']['id']}/state", "ON" if state["is_on"] else "OFF")

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise ConfigError("config must be a dictionary")
        if not isinstance(config.get("devices"), list):
            raise ConfigError("config must include devices")
        for device in config["devices"]:
            for key in ("id", "name", "room", "type", "generation", "shelly_id"):
                if key not in device:
                    raise ConfigError(f"device missing {key}")
            if device["generation"] not in {"gen1", "gen2"}:
                raise ConfigError("device generation must be gen1 or gen2")
        return config


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open() as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ConfigError("collector config must be a dictionary")
    return config


def run_until_stopped(collector: LightingMQTTCollector) -> None:
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
