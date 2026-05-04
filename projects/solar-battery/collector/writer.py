import os
from dataclasses import dataclass, field

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


@dataclass
class SolarReading:
    pv_power_w: float = 0.0
    battery_soc_pct: float = 0.0
    battery_power_w: float = 0.0        # + charging, - discharging
    load_power_w: float = 0.0
    grid_power_w: float = 0.0           # + import, - export
    battery_voltage_v: float | None = None
    inverter_temp_c: float | None = None
    daily_yield_kwh: float | None = None
    source: str = "unknown"             # mqtt | modbus | solarman

    @property
    def battery_state(self) -> str:
        if self.battery_power_w > 10:
            return "charging"
        if self.battery_power_w < -10:
            return "discharging"
        return "idle"

    @property
    def grid_state(self) -> str:
        if self.grid_power_w > 10:
            return "importing"
        if self.grid_power_w < -10:
            return "exporting"
        return "idle"


class SolarWriter:
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

    def write_reading(self, r: SolarReading) -> None:
        p = (
            Point("solar")
            .tag("source", r.source)
            .tag("battery_state", r.battery_state)
            .tag("grid_state", r.grid_state)
            .field("pv_power_w", float(r.pv_power_w))
            .field("battery_soc_pct", float(r.battery_soc_pct))
            .field("battery_power_w", float(r.battery_power_w))
            .field("load_power_w", float(r.load_power_w))
            .field("grid_power_w", float(r.grid_power_w))
        )
        if r.battery_voltage_v is not None:
            p = p.field("battery_voltage_v", float(r.battery_voltage_v))
        if r.inverter_temp_c is not None:
            p = p.field("inverter_temp_c", float(r.inverter_temp_c))
        if r.daily_yield_kwh is not None:
            p = p.field("daily_yield_kwh", float(r.daily_yield_kwh))
        self._write([p])

    def close(self) -> None:
        self._client.close()
