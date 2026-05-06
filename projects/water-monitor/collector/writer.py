from __future__ import annotations

import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from .calculator import TankReading


class WaterWriter:
    def __init__(self):
        self._client = InfluxDBClient(
            url=os.environ["INFLUXDB_URL"],
            token=os.environ["INFLUXDB_TOKEN"],
            org=os.environ["INFLUXDB_ORG"],
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._bucket = os.environ["INFLUXDB_BUCKET"]
        self._org = os.environ["INFLUXDB_ORG"]

    def _write(self, points: list[Point]) -> None:
        try:
            self._write_api.write(bucket=self._bucket, org=self._org, record=points)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                "Failed to write %d point(s) to InfluxDB: %s", len(points), e
            )
            raise

    def write_reading(
        self,
        reading: TankReading,
        source: str = "unknown",
        overflow_detected: bool = False,
        overflow_magnitude: float | None = None,
        overflow_handling: str | None = None,
        is_critical: bool = False,
    ) -> bool:
        try:
            p = (
                Point("water_tank")
                .tag("tank_id", reading.tank_id)
                .tag("source", source)
                .field("distance_raw_cm", reading.distance_raw_cm)
                .field("level_cm", reading.level_cm)
                .field("level_pct", reading.level_pct)
                .field("volume_liters", reading.volume_liters)
            )

            # Add overflow metadata if detected
            if overflow_detected:
                p = p.tag("overflow_detected", "true")
                if overflow_handling:
                    p = p.tag("overflow_handling", overflow_handling)
                if overflow_magnitude is not None:
                    p = p.field("overflow_magnitude_liters", round(overflow_magnitude, 1))
            else:
                p = p.tag("overflow_detected", "false")

            self._write([p])
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                "[%s] Failed to write reading: %s", reading.tank_id, e
            )
            return False

    def write_pump_state(self, tank_id: str, state: str) -> None:
        """state: 'ON' or 'OFF'"""
        p = (
            Point("water_pump")
            .tag("tank_id", tank_id)
            .field("state", 1 if state.upper() == "ON" else 0)
        )
        self._write([p])

    def write_battery(self, tank_id: str, battery_pct: float) -> None:
        p = (
            Point("water_sensor_battery")
            .tag("tank_id", tank_id)
            .field("battery_pct", float(battery_pct))
        )
        self._write([p])

    def close(self) -> None:
        self._client.close()
