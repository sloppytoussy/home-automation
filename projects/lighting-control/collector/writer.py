from __future__ import annotations

from typing import Any

from shared.db import influx


STATE_FIELDS = ("is_on", "brightness_pct", "power_w", "energy_wh", "temperature_c", "rssi")
EVENT_TYPES = {"on", "off", "dim", "scene", "presence", "schedule"}
TRIGGERED_BY = {"manual", "schedule", "scene", "presence", "api", "mqtt"}


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def write_state(
    client: object,
    device_id: str,
    room: str,
    device_type: str,
    generation: str,
    source: str,
    state: dict[str, Any],
) -> None:
    _require_text(device_id, "device_id")
    _require_text(room, "room")
    _require_text(device_type, "device_type")
    if generation not in {"gen1", "gen2"}:
        raise ValueError("generation must be gen1 or gen2")
    if source not in {"mqtt", "http", "command"}:
        raise ValueError("source must be mqtt, http, or command")
    fields = _clean_fields({key: state.get(key) for key in STATE_FIELDS})
    if not fields:
        raise ValueError("state must include at least one field")
    influx.write_point(
        measurement="lighting_state",
        tags={
            "device_id": device_id,
            "room": room,
            "device_type": device_type,
            "generation": generation,
            "source": source,
        },
        fields=fields,
    )


def write_event(
    client: object,
    device_id: str,
    room: str,
    event_type: str,
    triggered_by: str,
    brightness_pct: float | None = None,
) -> None:
    _require_text(device_id, "device_id")
    _require_text(room, "room")
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown event_type")
    if triggered_by not in TRIGGERED_BY:
        raise ValueError("unknown triggered_by")
    if brightness_pct is not None and (brightness_pct < 0 or brightness_pct > 100):
        raise ValueError("brightness_pct must be between 0 and 100")
    fields = _clean_fields({"triggered_by": triggered_by, "brightness_pct": brightness_pct})
    influx.write_point(
        measurement="lighting_events",
        tags={"device_id": device_id, "room": room, "event_type": event_type},
        fields=fields,
    )


def write_energy(client: object, device_id: str, room: str, power_w: float, wh_delta: float, wh_total: float) -> None:
    _require_text(device_id, "device_id")
    _require_text(room, "room")
    if power_w < 0:
        raise ValueError("power_w must be non-negative")
    if wh_delta < 0:
        raise ValueError("wh_delta must be non-negative")
    if wh_total < 0:
        raise ValueError("wh_total must be non-negative")
    influx.write_point(
        measurement="lighting_energy",
        tags={"device_id": device_id, "room": room},
        fields={"power_w": float(power_w), "wh_delta": float(wh_delta), "wh_total": float(wh_total)},
    )
