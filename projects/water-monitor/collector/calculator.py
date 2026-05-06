from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TankReading:
    tank_id: str
    distance_raw_cm: float      # raw sensor distance
    level_cm: float             # usable water depth
    level_pct: float            # 0–100 %
    volume_liters: float        # calculated volume
    usable_depth_cm: float      # max usable depth
    capacity_liters: float


def compute_reading(tank_cfg: dict, distance_cm: float) -> TankReading:
    """
    Convert a raw ultrasonic distance reading into a full TankReading.

    Physical Reality:
    The ultrasonic sensor is mounted on the ceiling (inside tank). Water fills from
    bottom up, so distance decreases as tank fills. When distance becomes negative
    (sensor reading shows water above the physical tank height), the tank is
    experiencing an overflow condition.

    Overflow Meaning Depends on Tank Configuration:
    - If overflow_handling == "no_outlet":
      Water exceeding capacity indicates inlet shutoff failure → ALERT condition
    - If overflow_handling == "open_outlet":
      Water exceeding capacity means safe outlet is working → NORMAL condition

    Args:
        tank_cfg: Tank configuration dictionary with fields:
            Required:
                - id: Tank identifier (str)
                - depth_cm: Physical tank depth in centimeters (float or str)
                - capacity_liters: Tank capacity in liters (float or str)
            Optional (Phase 1):
                - sensor_offset_cm: Distance from ceiling to usable water top (default: 0)
            Optional (Phase 2+ for alerting):
                - num_sources: "single" | "multiple" (water source type)
                - inlet_shutoff: "float_valve" | "manual_valve" (control method)
                - overflow_handling: "open_outlet" | "no_outlet" (overflow management)
        distance_cm: Raw ultrasonic reading (cm from sensor to water surface)

    Returns:
        TankReading with computed level, volume, percentage

    Note: volume_liters can exceed capacity_liters when distance is negative.
    The collector/alert service should check tank_cfg to determine if this is
    normal operation (open outlet) or an error condition (inlet failure).

    Phase 2+: Collector/alert layer will validate overflow_handling field and
    trigger appropriate logging/alerting based on tank configuration.
    """
    depth = float(tank_cfg["depth_cm"])
    offset = float(tank_cfg.get("sensor_offset_cm", 0))
    capacity = float(tank_cfg["capacity_liters"])

    usable_depth = depth - offset
    # Sensor is mounted on ceiling; distance grows as tank empties.
    # When distance_cm is negative, water is above the tank top (overflow condition).
    level_cm = max(0.0, usable_depth - distance_cm)
    # level_cm can be > usable_depth if distance_cm is negative (water above tank top)

    level_pct = min(100.0, round(level_cm / usable_depth * 100, 2)) if usable_depth > 0 else 0.0
    # level_pct is capped at 100% for UI display consistency

    volume = round(level_cm / usable_depth * capacity, 1) if usable_depth > 0 else 0.0
    # volume is NOT capped — can exceed capacity to indicate overflow condition.
    # Collector should check tank_cfg.overflow_handling to determine if overflow is
    # expected (open_outlet) or an error condition (no_outlet).

    return TankReading(
        tank_id=tank_cfg["id"],
        distance_raw_cm=round(distance_cm, 1),
        level_cm=round(level_cm, 1),
        level_pct=level_pct,
        volume_liters=volume,
        usable_depth_cm=usable_depth,
        capacity_liters=capacity,
    )


def normalise_distance(raw: float, unit: str) -> float:
    """Convert mm → cm if needed."""
    if unit == "mm":
        return raw / 10.0
    return float(raw)


def consumption_rate_lph(readings: list[tuple[float, float]]) -> float | None:
    """
    Estimate litres-per-hour drain rate from a time-ordered list of
    (timestamp_epoch_s, volume_liters) tuples.
    Returns None if fewer than 2 readings or if volume increased (refill).
    """
    if len(readings) < 2:
        return None
    t0, v0 = readings[0]
    t1, v1 = readings[-1]
    delta_h = (t1 - t0) / 3600
    if delta_h <= 0 or v1 >= v0:
        return None
    return round((v0 - v1) / delta_h, 2)


def days_remaining(volume_liters: float, rate_lph: float) -> float | None:
    if not rate_lph or rate_lph <= 0:
        return None
    return round(volume_liters / (rate_lph * 24), 2)
