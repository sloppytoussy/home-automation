import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


class InfluxWriter:
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

    def write_summary(self, data: dict) -> None:
        p = (
            Point("dns_summary")
            .field("total_queries", int(data.get("queries", {}).get("total", 0)))
            .field("blocked_queries", int(data.get("queries", {}).get("blocked", 0)))
            .field("percent_blocked", float(data.get("queries", {}).get("percent_blocked", 0)))
            .field("unique_domains", int(data.get("queries", {}).get("unique_domains", 0)))
            .field("unique_clients", int(data.get("clients", {}).get("active", 0)))
            .field("total_clients", int(data.get("clients", {}).get("total", 0)))
        )
        self._write([p])

    def write_top_domains(self, data: dict) -> None:
        points = [
            Point("dns_top_domains")
            .tag("domain", domain)
            .field("count", int(count))
            for domain, count in (data.get("domains") or {}).items()
        ]
        if points:
            self._write(points)

    def write_top_blocked(self, data: dict) -> None:
        points = [
            Point("dns_top_blocked")
            .tag("domain", domain)
            .field("count", int(count))
            for domain, count in (data.get("blocked") or {}).items()
        ]
        if points:
            self._write(points)

    def write_top_clients(self, data: dict) -> None:
        points = [
            Point("dns_top_clients")
            .tag("client", client)
            .field("count", int(count))
            for client, count in (data.get("clients") or {}).items()
        ]
        if points:
            self._write(points)

    def write_query_types(self, data: dict) -> None:
        points = [
            Point("dns_query_types")
            .tag("type", qtype)
            .field("count", float(pct))
            for qtype, pct in (data.get("types") or {}).items()
        ]
        if points:
            self._write(points)

    def write_upstreams(self, data: dict) -> None:
        points = [
            Point("dns_upstreams")
            .tag("upstream", info.get("ip", name))
            .field("count", int(info.get("count", 0)))
            .field("percent", float(info.get("percent", 0)))
            for name, info in (data.get("upstreams") or {}).items()
        ]
        if points:
            self._write(points)

    def close(self) -> None:
        self._client.close()
