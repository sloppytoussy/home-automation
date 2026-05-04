import json
import logging
import os

import paho.mqtt.client as mqtt

from .calculator import compute_reading, normalise_distance
from .writer import WaterWriter

log = logging.getLogger(__name__)


class MQTTWaterCollector:
    """
    Subscribes to MQTT topics for each tank configured with type=mqtt.
    Parses distance readings, computes level/volume, and writes to InfluxDB.
    """

    def __init__(self, tanks: list[dict], writer: WaterWriter):
        # Only handle MQTT-type tanks
        self._tanks = {
            t["sensor"]["topic"]: t
            for t in tanks
            if t.get("sensor", {}).get("type") == "mqtt"
        }
        self._writer = writer
        self._client = mqtt.Client(client_id="water-monitor")

        if os.environ.get("MQTT_USERNAME"):
            self._client.username_pw_set(
                os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD", "")
            )

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connected")
            for topic in self._tanks:
                client.subscribe(topic)
                log.info("Subscribed to %s", topic)
        else:
            log.error("MQTT connect failed: rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        tank_cfg = self._tanks.get(topic)
        if not tank_cfg:
            return

        try:
            payload = msg.payload.decode()
            sensor_cfg = tank_cfg["sensor"]
            payload_key = sensor_cfg.get("payload_key", "")

            if payload_key:
                raw = json.loads(payload)[payload_key]
            else:
                raw = float(payload)

            unit = sensor_cfg.get("unit", "cm")
            distance_cm = normalise_distance(float(raw), unit)
            reading = compute_reading(tank_cfg, distance_cm)

            source = tank_cfg.get("active_source", tank_cfg["sources"][0])
            self._writer.write_reading(reading, source=source)

            log.info(
                "[%s] dist=%.1fcm level=%.1f%% vol=%.0fL",
                tank_cfg["id"], distance_cm, reading.level_pct, reading.volume_liters,
            )

            # Also handle pump state if on the same base topic
            pump_topic = tank_cfg.get("pump", {}).get("state_topic", "")
            if pump_topic and topic == pump_topic:
                self._writer.write_pump_state(tank_cfg["id"], payload.strip())

        except Exception as e:
            log.warning("Failed to process message on %s: %s", topic, e)

    def start(self) -> None:
        host = os.environ["MQTT_HOST"]
        port = int(os.environ.get("MQTT_PORT", 1883))
        self._client.connect(host, port)
        self._client.loop_start()
        log.info("MQTT collector started — host=%s port=%d", host, port)

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
