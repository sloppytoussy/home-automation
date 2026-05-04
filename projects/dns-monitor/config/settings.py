import os
from dataclasses import dataclass


@dataclass
class Settings:
    pihole_host: str
    pihole_password: str
    pihole_port: int
    pihole_tls: bool

    influxdb_url: str
    influxdb_token: str
    influxdb_org: str
    influxdb_bucket: str

    poll_interval: int
    dashboard_port: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            pihole_host=os.environ["PIHOLE_HOST"],
            pihole_password=os.environ["PIHOLE_PASSWORD"],
            pihole_port=int(os.environ.get("PIHOLE_PORT", 80)),
            pihole_tls=os.environ.get("PIHOLE_TLS", "false").lower() == "true",
            influxdb_url=os.environ["INFLUXDB_URL"],
            influxdb_token=os.environ["INFLUXDB_TOKEN"],
            influxdb_org=os.environ["INFLUXDB_ORG"],
            influxdb_bucket=os.environ["INFLUXDB_BUCKET"],
            poll_interval=int(os.environ.get("DNS_POLL_INTERVAL", 30)),
            dashboard_port=int(os.environ.get("DASHBOARD_PORT", 5000)),
        )
