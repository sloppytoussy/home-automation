import os
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


def get_client() -> InfluxDBClient:
    return InfluxDBClient(
        url=os.environ["INFLUXDB_URL"],
        token=os.environ["INFLUXDB_TOKEN"],
        org=os.environ["INFLUXDB_ORG"],
    )


def write_point(measurement: str, fields: dict, tags: dict = None):
    with get_client() as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        point = Point(measurement)
        for k, v in (tags or {}).items():
            point = point.tag(k, v)
        for k, v in fields.items():
            point = point.field(k, v)
        write_api.write(
            bucket=os.environ["INFLUXDB_BUCKET"],
            org=os.environ["INFLUXDB_ORG"],
            record=point,
        )
