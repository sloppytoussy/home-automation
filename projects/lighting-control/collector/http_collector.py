from __future__ import annotations

import threading
import time
from typing import Any

import requests

from . import writer

try:
    from shared.utils import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)


log = get_logger(__name__)


class DeviceUnreachable(ConnectionError):
    def __init__(self, device_id: str):
        super().__init__(f"device unreachable: {device_id}")
        self.device_id = device_id


class LightingHTTPCollector:
    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.poll_loop, name="lighting-http-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def poll_loop(self) -> None:
        interval = float(self._config.get("collection", {}).get("http_poll_interval", 30))
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(interval)

    def poll_once(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for device in self._config.get("devices", []):
            try:
                state = self.poll_device(device)
                states[device["id"]] = state
                writer.write_state(None, device["id"], device["room"], device["type"], device["generation"], "http", state)
            except DeviceUnreachable:
                log.warning("Lighting device unreachable", extra={"device_id": device.get("id")})
        return states

    def poll_device(self, device: dict[str, Any]) -> dict[str, Any]:
        last_exc: requests.RequestException | None = None
        for attempt in range(3):
            try:
                if device["generation"] == "gen1":
                    return self._poll_gen1(device)
                return self._poll_gen2(device)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(min(1 * 2 ** attempt, 4))
        log.warning("HTTP polling failed after retries", extra={"device_id": device["id"], "error": str(last_exc)})
        raise DeviceUnreachable(device["id"])

    def set_device(self, device: dict[str, Any], on: bool | None = None, brightness: int | None = None) -> dict[str, Any]:
        if device["generation"] == "gen1":
            raise NotImplementedError("Gen1 HTTP commands are not configured in Phase 1")
        ip = device["ip"]
        if brightness is not None or device.get("dimmable"):
            body = {"id": 0}
            if on is not None:
                body["on"] = bool(on)
            if brightness is not None:
                body["brightness"] = int(brightness)
            response = requests.post(f"http://{ip}/rpc/Light.Set", json=body, timeout=5)
        else:
            response = requests.post(f"http://{ip}/rpc/Switch.Set", json={"id": 0, "on": bool(on)}, timeout=5)
        response.raise_for_status()
        return response.json()

    def _poll_gen1(self, device: dict[str, Any]) -> dict[str, Any]:
        ip = device["ip"]
        relay = requests.get(f"http://{ip}/relay/0", timeout=5)
        relay.raise_for_status()
        status = requests.get(f"http://{ip}/status", timeout=5)
        status.raise_for_status()
        relay_data = relay.json()
        status_data = status.json()
        state: dict[str, Any] = {"is_on": bool(relay_data["ison"])}
        emeter = (status_data.get("emeters") or status_data.get("emeter") or [{}])[0]
        if device.get("has_power_meter") and isinstance(emeter, dict):
            if emeter.get("power") is not None:
                state["power_w"] = float(emeter["power"])
            if emeter.get("total") is not None:
                state["energy_wh"] = float(emeter["total"])
        wifi = status_data.get("wifi_sta", {})
        if wifi.get("rssi") is not None:
            state["rssi"] = int(wifi["rssi"])
        return state

    def _poll_gen2(self, device: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(f"http://{device['ip']}/rpc/Switch.GetStatus", json={"id": 0}, timeout=5)
        response.raise_for_status()
        data = response.json()
        state: dict[str, Any] = {"is_on": bool(data["output"])}
        if data.get("apower") is not None:
            state["power_w"] = float(data["apower"])
        total = data.get("aenergy", {}).get("total")
        if total is not None:
            state["energy_wh"] = float(total)
        if data.get("temperature", {}).get("tC") is not None:
            state["temperature_c"] = float(data["temperature"]["tC"])
        return state
