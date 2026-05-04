import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


class PowerWriter:
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

    def write_meter_reading(
        self,
        instant_load_w: float,
        lifetime_kwh: float,
        remaining_kwh: float,
        topup_kwh: float | None = None,
        notes: str = "",
    ) -> None:
        p = (
            Point("power_meter")
            .tag("source", "manual")
            .field("instant_load_w", float(instant_load_w))
            .field("lifetime_kwh", float(lifetime_kwh))
            .field("remaining_kwh", float(remaining_kwh))
        )
        if topup_kwh is not None:
            p = p.field("topup_kwh", float(topup_kwh))
        if notes:
            p = p.field("notes", notes)
        self._write([p])

    def write_appliance_reading(
        self,
        room: str,
        appliance: str,
        watts: float,
        daily_hours: float | None = None,
    ) -> None:
        p = (
            Point("power_appliance")
            .tag("room", room)
            .tag("appliance", appliance)
            .field("watts", float(watts))
        )
        if daily_hours is not None:
            p = p.field("daily_hours", float(daily_hours))
            p = p.field("est_daily_kwh", round(watts * daily_hours / 1000, 4))
        self._write([p])

    def close(self) -> None:
        self._client.close()
