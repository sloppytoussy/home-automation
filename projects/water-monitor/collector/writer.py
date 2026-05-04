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
        self._write_api.write(bucket=self._bucket, org=self._org, record=points)

    def write_reading(self, reading: TankReading, source: str = "unknown") -> None:
        p = (
            Point("water_tank")
            .tag("tank_id", reading.tank_id)
            .tag("source", source)
            .field("distance_raw_cm", reading.distance_raw_cm)
            .field("level_cm", reading.level_cm)
            .field("level_pct", reading.level_pct)
            .field("volume_liters", reading.volume_liters)
        )
        self._write([p])

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
