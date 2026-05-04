import logging
import os

import paho.mqtt.client as mqtt

from .writer import SolarReading, SolarWriter

log = logging.getLogger(__name__)


class MQTTSolarCollector:
    """
    Subscribes to Solar Assistant (or any MQTT inverter) topics and writes
    readings to InfluxDB on every message received.

    Topic values are expected to be plain numeric strings (Solar Assistant default).
    """

    def __init__(self, topic_map: dict, writer: SolarWriter):
        self._topics = topic_map          # field_name → topic
        self._topic_index = {v: k for k, v in topic_map.items()}  # topic → field_name
        self._writer = writer
        self._state: dict = {}
        self._client = mqtt.Client(client_id="solar-battery-collector")

        if os.environ.get("MQTT_USERNAME"):
            self._client.username_pw_set(
                os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD", "")
            )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connected")
            for topic in self._topic_index:
                client.subscribe(topic)
                log.debug("Subscribed: %s", topic)
        else:
            log.error("MQTT connect failed rc=%d", rc)

    def _on_message(self, client, userdata, msg):
        field = self._topic_index.get(msg.topic)
        if not field:
            return
        try:
            self._state[field] = float(msg.payload.decode().strip())
        except ValueError:
            return

        # Write once we have at least PV power and SoC
        if "pv_power_w" in self._state and "battery_soc_pct" in self._state:
            r = SolarReading(
                pv_power_w=self._state.get("pv_power_w", 0),
                battery_soc_pct=self._state.get("battery_soc_pct", 0),
                battery_power_w=self._state.get("battery_power_w", 0),
                load_power_w=self._state.get("load_power_w", 0),
                grid_power_w=self._state.get("grid_power_w", 0),
                battery_voltage_v=self._state.get("battery_voltage_v"),
                inverter_temp_c=self._state.get("inverter_temp_c"),
                daily_yield_kwh=self._state.get("daily_yield_kwh"),
                source="mqtt",
            )
            try:
                self._writer.write_reading(r)
                log.debug(
                    "pv=%.0fW soc=%.1f%% bat=%.0fW load=%.0fW grid=%.0fW",
                    r.pv_power_w, r.battery_soc_pct, r.battery_power_w,
                    r.load_power_w, r.grid_power_w,
                )
            except Exception as e:
                log.warning("Write error: %s", e)

    def start(self) -> None:
        host = os.environ["MQTT_HOST"]
        port = int(os.environ.get("MQTT_PORT", 1883))
        self._client.connect(host, port)
        self._client.loop_start()
        log.info("MQTT solar collector started — %s:%d", host, port)

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
