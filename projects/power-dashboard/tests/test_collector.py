from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collector.mqtt_collector import ConfigError, PowerMQTTCollector, load_config


@pytest.fixture
def config():
    return {
        "mqtt": {
            "client_id": "test-power",
            "host_env": "MQTT_BROKER_HOST",
            "port_env": "MQTT_BROKER_PORT",
            "default_host": "localhost",
            "default_port": 1883,
            "username_env": "MQTT_USERNAME",
            "password_env": "MQTT_PASSWORD",
            "reconnect": {"max_tries": 2, "base_delay_seconds": 0, "max_delay_seconds": 0},
        },
        "buffer": {"max_readings": 3},
        "influx": {"measurement": "power_readings"},
        "devices": [
            {
                "id": "shelly-main",
                "type": "shelly_pro_3em",
                "enabled": True,
                "topic_patterns": [
                    {
                        "pattern": "shellies/{device_id}/emeter/{channel}/{metric}",
                        "payload": "scalar_float",
                        "metric_fields": {
                            "power": "watts",
                            "energy": "watt_hours",
                            "voltage": "volts",
                            "current": "amps",
                            "pf": "power_factor",
                        },
                    }
                ],
                "circuits": [
                    {"channel": "0", "circuit": "mains_l1", "phase": "L1"},
                    {"channel": "1", "circuit": "mains_l2", "phase": "L2"},
                ],
            },
            {
                "id": "iotawatt-main",
                "type": "iotawatt",
                "enabled": True,
                "topic_patterns": [
                    {
                        "pattern": "iotawatt/{device_id}/sensor/{sensor}/{metric}",
                        "payload": "json_value",
                        "metric_fields": {"value": "watts", "wh": "watt_hours"},
                    }
                ],
                "rest": {
                    "enabled": True,
                    "base_url_env": "IOTAWATT_BASE_URL",
                    "query_path": "/query",
                    "interval_seconds": 30,
                    "timeout_seconds": 5,
                },
                "circuits": [
                    {"sensor": "kitchen", "circuit": "kitchen", "phase": "none"},
                    {"sensor": "pump", "circuit": "water_pump", "phase": "none"},
                ],
            },
        ],
    }


@pytest.fixture
def mqtt_client():
    with patch("collector.mqtt_collector.mqtt.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value = client
        yield client


@pytest.fixture
def collector(config, mqtt_client):
    return PowerMQTTCollector(config)


@pytest.mark.parametrize(
    "topic,payload,field,value,circuit,phase",
    [
        ("shellies/shelly-main/emeter/0/power", "123.4", "watts", 123.4, "mains_l1", "L1"),
        ("shellies/shelly-main/emeter/0/energy", "55", "watt_hours", 55.0, "mains_l1", "L1"),
        ("shellies/shelly-main/emeter/1/voltage", "231.5", "volts", 231.5, "mains_l2", "L2"),
        ("shellies/shelly-main/emeter/1/current", "10.2", "amps", 10.2, "mains_l2", "L2"),
        ("shellies/shelly-main/emeter/1/pf", "0.98", "power_factor", 0.98, "mains_l2", "L2"),
        ("iotawatt/iotawatt-main/sensor/kitchen/value", '{"value": 450, "units": "W"}', "watts", 450.0, "kitchen", "none"),
        ("iotawatt/iotawatt-main/sensor/pump/wh", '{"value": 1200, "units": "Wh"}', "watt_hours", 1200.0, "water_pump", "none"),
    ],
)
def test_parse_message_supported_topics_returns_reading(collector, topic, payload, field, value, circuit, phase):
    reading = collector.parse_message(topic, payload)
    assert reading["measurement"] == "power_readings"
    assert reading["fields"] == {field: value}
    assert reading["tags"]["circuit"] == circuit
    assert reading["tags"]["phase"] == phase
    assert reading["tags"]["source"] == "mqtt"


@pytest.mark.parametrize(
    "topic,payload",
    [
        ("shellies/shelly-main/emeter/9/power", "1"),
        ("shellies/shelly-main/emeter/0/unknown", "1"),
        ("shellies/other/emeter/0/power", "1"),
        ("iotawatt/iotawatt-main/sensor/missing/value", '{"value": 1}'),
        ("not/a/match", "1"),
    ],
)
def test_parse_message_unmapped_topics_return_none(collector, topic, payload):
    assert collector.parse_message(topic, payload) is None


@pytest.mark.parametrize("payload", ["not-float", "", "true"])
def test_parse_message_invalid_scalar_payload_raises_value_error(collector, payload):
    with pytest.raises(ValueError):
        collector.parse_message("shellies/shelly-main/emeter/0/power", payload)


@pytest.mark.parametrize("payload", ["{}", "[]", '{"value": true}', "bad-json"])
def test_parse_message_invalid_json_payload_raises_error(collector, payload):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        collector.parse_message("iotawatt/iotawatt-main/sensor/kitchen/value", payload)


def test_subscribed_topics_use_configured_wildcards(collector):
    assert "shellies/shelly-main/emeter/+/+" in collector.subscribed_topics
    assert "iotawatt/iotawatt-main/sensor/+/+" in collector.subscribed_topics


def test_on_connect_subscribes_all_routes(collector, mqtt_client):
    collector._on_connect(mqtt_client, None, {}, 0)
    assert mqtt_client.subscribe.call_count == 2


def test_on_connect_nonzero_rc_does_not_subscribe(collector, mqtt_client):
    collector._on_connect(mqtt_client, None, {}, 1)
    mqtt_client.subscribe.assert_not_called()


def test_on_disconnect_unexpected_calls_reconnect(collector, mqtt_client):
    collector._on_disconnect(mqtt_client, None, 1)
    mqtt_client.reconnect.assert_called_once()


def test_on_disconnect_clean_does_not_reconnect(collector, mqtt_client):
    collector._on_disconnect(mqtt_client, None, 0)
    mqtt_client.reconnect.assert_not_called()


def test_on_disconnect_reconnect_oserror_is_handled(collector, mqtt_client):
    mqtt_client.reconnect.side_effect = OSError("down")
    collector._on_disconnect(mqtt_client, None, 1)
    mqtt_client.reconnect.assert_called_once()


def test_on_message_writes_parsed_reading(collector):
    msg = SimpleNamespace(topic="shellies/shelly-main/emeter/0/power", payload=b"42")
    with patch("collector.mqtt_collector.influx.write_point") as write_point:
        collector._on_message(MagicMock(), None, msg)
    write_point.assert_called_once()
    assert write_point.call_args.kwargs["fields"] == {"watts": 42.0}


def test_on_message_parse_error_does_not_write(collector):
    msg = SimpleNamespace(topic="shellies/shelly-main/emeter/0/power", payload=b"bad")
    with patch("collector.mqtt_collector.influx.write_point") as write_point:
        collector._on_message(MagicMock(), None, msg)
    write_point.assert_not_called()


def test_write_failure_buffers_reading(collector):
    reading = collector.parse_message("shellies/shelly-main/emeter/0/power", "42")
    with patch("collector.mqtt_collector.influx.write_point", side_effect=RuntimeError("down")):
        collector._write_or_buffer(reading)
    assert collector.buffered_count == 1


def test_buffer_overflow_drops_oldest(collector):
    for value in [1, 2, 3, 4]:
        collector._append_buffer({"fields": {"watts": value}})
    assert collector.buffered_count == 3
    assert collector._buffer[0]["fields"] == {"watts": 2}


def test_write_success_does_not_buffer(collector):
    reading = collector.parse_message("shellies/shelly-main/emeter/0/power", "42")
    with patch("collector.mqtt_collector.influx.write_point"):
        collector._write_or_buffer(reading)
    assert collector.buffered_count == 0


def test_start_connects_and_starts_loop(config, mqtt_client, monkeypatch):
    config["devices"][1]["rest"]["enabled"] = False
    monkeypatch.setenv("MQTT_BROKER_HOST", "broker.local")
    monkeypatch.setenv("MQTT_BROKER_PORT", "1884")
    collector = PowerMQTTCollector(config)
    collector.start()
    mqtt_client.connect.assert_called_once_with("broker.local", 1884)
    mqtt_client.loop_start.assert_called_once()


def test_start_uses_default_mqtt_host_and_port(config, mqtt_client, monkeypatch):
    config["devices"][1]["rest"]["enabled"] = False
    monkeypatch.delenv("MQTT_BROKER_HOST", raising=False)
    monkeypatch.delenv("MQTT_BROKER_PORT", raising=False)
    collector = PowerMQTTCollector(config)
    collector.start()
    mqtt_client.connect.assert_called_once_with("localhost", 1883)


def test_start_sets_username_when_env_present(config, mqtt_client, monkeypatch):
    monkeypatch.setenv("MQTT_USERNAME", "user")
    monkeypatch.setenv("MQTT_PASSWORD", "pass")
    PowerMQTTCollector(config)
    mqtt_client.username_pw_set.assert_called_once_with("user", "pass")


def test_stop_stops_loop_and_disconnects(collector, mqtt_client):
    collector.stop()
    mqtt_client.loop_stop.assert_called_once()
    mqtt_client.disconnect.assert_called_once()


def test_connect_with_backoff_retries_oserror(config, mqtt_client):
    config["devices"][1]["rest"]["enabled"] = False
    mqtt_client.connect.side_effect = [OSError("down"), None]
    collector = PowerMQTTCollector(config)
    with patch("collector.mqtt_collector.time.sleep") as sleep:
        collector.start()
    assert mqtt_client.connect.call_count == 2
    sleep.assert_called_once()


def test_connect_with_backoff_raises_after_max_attempts(config, mqtt_client):
    config["devices"][1]["rest"]["enabled"] = False
    mqtt_client.connect.side_effect = OSError("down")
    collector = PowerMQTTCollector(config)
    with patch("collector.mqtt_collector.time.sleep"):
        with pytest.raises(ConnectionError):
            collector.start()


def test_poll_iotawatt_rest_once_writes_readings(collector, monkeypatch):
    monkeypatch.setenv("IOTAWATT_BASE_URL", "http://iotawatt.local")
    response = MagicMock()
    response.json.return_value = {"kitchen": 300, "pump": {"watts": 500, "wh": 900}}
    with patch("collector.mqtt_collector.requests.get", return_value=response) as get, patch(
        "collector.mqtt_collector.influx.write_point"
    ) as write_point:
        readings = collector.poll_iotawatt_rest_once()
    get.assert_called_once()
    assert len(readings) == 2
    assert write_point.call_count == 2


def test_poll_iotawatt_rest_once_skips_when_base_url_missing(collector, monkeypatch):
    monkeypatch.delenv("IOTAWATT_BASE_URL", raising=False)
    with patch("collector.mqtt_collector.requests.get") as get:
        assert collector.poll_iotawatt_rest_once() == []
    get.assert_not_called()


def test_parse_rest_payload_rejects_non_object(collector, config):
    with pytest.raises(ValueError):
        collector._parse_rest_payload(config["devices"][1], [])


def test_rest_fields_accepts_numeric_as_watts(collector):
    assert collector._rest_fields(12) == {"watts": 12.0}


def test_rest_fields_accepts_watts_and_wh_object(collector):
    assert collector._rest_fields({"watts": 12, "wh": 34}) == {"watts": 12.0, "watt_hours": 34.0}


def test_rest_fields_rejects_bad_value(collector):
    with pytest.raises(ValueError):
        collector._rest_fields("bad")


@pytest.mark.parametrize("bad_config", [None, {}, {"mqtt": {}}, {"mqtt": {}, "devices": "bad"}, {"mqtt": {}, "devices": [], "buffer": {"max_readings": 0}}])
def test_invalid_config_raises_config_error(bad_config):
    with pytest.raises(ConfigError):
        PowerMQTTCollector(bad_config)


def test_load_config_reads_yaml_file(tmp_path):
    config_file = tmp_path / "power.yaml"
    config_file.write_text("mqtt: {}\ndevices: []\n")
    assert load_config(config_file) == {"mqtt": {}, "devices": []}


def test_load_config_rejects_empty_yaml(tmp_path):
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("")
    with pytest.raises(ConfigError):
        load_config(config_file)


def test_disabled_device_is_not_subscribed(config, mqtt_client):
    config["devices"][0]["enabled"] = False
    collector = PowerMQTTCollector(config)
    assert collector.subscribed_topics == ["iotawatt/iotawatt-main/sensor/+/+"]


def test_unmapped_rest_sensor_is_ignored(collector, config):
    assert collector._parse_rest_payload(config["devices"][1], {"unknown": 1}) == []
