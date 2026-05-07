from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from collector import writer
from collector.http_collector import DeviceUnreachable, LightingHTTPCollector
from collector.mqtt_collector import ConfigError, LightingMQTTCollector, run_until_stopped


@pytest.fixture
def config():
    return {
        "mqtt": {"broker_host": "localhost", "broker_port": 1883},
        "collection": {"buffer_size": 3, "http_poll_interval": 1},
        "home_assistant": {"enabled": False, "discovery_prefix": "homeassistant"},
        "devices": [
            {"id": "living_room_main", "name": "Living Room Main", "room": "living_room", "type": "shellyplus1pm", "generation": "gen2", "ip": "shelly-main.local", "shelly_id": "shellyplus1pm-main", "dimmable": False, "has_power_meter": True},
            {"id": "bedroom_lamp", "name": "Bedroom Lamp", "room": "bedroom", "type": "shelly1", "generation": "gen1", "ip": "shelly-bedroom.local", "shelly_id": "shelly1-bedroom", "dimmable": False, "has_power_meter": False},
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
    return LightingMQTTCollector(config)


def msg(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload.encode("utf-8"))


def test_mqtt_connect_success_starts_loop(config, mqtt_client):
    LightingMQTTCollector(config).start()
    mqtt_client.connect.assert_called_once_with("localhost", 1883)
    mqtt_client.loop_start.assert_called_once()


def test_mqtt_connect_failure_raises(config, mqtt_client):
    mqtt_client.connect.side_effect = OSError("down")
    with pytest.raises(OSError):
        LightingMQTTCollector(config).start()


@pytest.mark.parametrize(
    ("topic", "payload", "field", "value"),
    [
        ("shellies/shelly1-bedroom/relay/0", "on", "is_on", True),
        ("shellies/shelly1-bedroom/relay/0", "off", "is_on", False),
        ("shellies/shelly1-bedroom/light/0", '{"ison": true, "brightness": 72}', "brightness_pct", 72.0),
        ("shellies/shelly1-bedroom/emeter/0/power", "12.5", "power_w", 12.5),
        ("shellies/shelly1-bedroom/emeter/0/energy", "1234", "energy_wh", 1234.0),
        ("shellyplus1pm-main/status/switch:0", '{"output": true, "apower": 44.4, "aenergy": {"total": 900}}', "energy_wh", 900.0),
        ("shellyplus1pm-main/status/light:0", '{"output": true, "brightness": 55}', "brightness_pct", 55.0),
        ("shellyplus1pm-main/events/rpc", '{"params": {"switch:0": {"output": false, "apower": 0, "aenergy": {"total": 901}}}}', "is_on", False),
        ("shellyplus1pm-main/events/rpc", '{"params": {"light:0": {"output": true, "brightness": 40}}}', "brightness_pct", 40.0),
    ],
)
def test_parse_supported_topics(collector, topic, payload, field, value):
    reading = collector.parse_message(topic, payload)
    assert reading["state"][field] == value
    assert reading["source"] == "mqtt"


def test_gen1_relay_maps_shelly_id_to_device_id(collector):
    reading = collector.parse_message("shellies/shelly1-bedroom/relay/0", "on")
    assert reading["device"]["id"] == "bedroom_lamp"


def test_gen2_switch_parses_on_power_and_energy(collector):
    reading = collector.parse_message("shellyplus1pm-main/status/switch:0", '{"output": true, "apower": 11, "aenergy": {"total": 22}}')
    assert reading["state"] == {"is_on": True, "power_w": 11.0, "energy_wh": 22.0}


@pytest.mark.parametrize("topic", ["unknown/topic", "shellies/shelly1-bedroom/relay/1", "other/status/switch:0"])
def test_unknown_topic_returns_none(collector, topic):
    assert collector.parse_message(topic, "on") is None


@pytest.mark.parametrize("payload", ["bad", "{}", "[]"])
def test_parse_errors_are_handled_by_on_message(collector, payload):
    with patch("collector.mqtt_collector.writer.write_state") as write_state:
        collector._on_message(MagicMock(), None, msg("shellies/shelly1-bedroom/light/0", payload))
    write_state.assert_not_called()


def test_on_message_unknown_topic_skips(collector):
    with patch("collector.mqtt_collector.writer.write_state") as write_state:
        collector._on_message(MagicMock(), None, msg("missing", "1"))
    write_state.assert_not_called()


def test_on_connect_subscribes_configured_topics(collector, mqtt_client):
    collector._on_connect(mqtt_client, None, {}, 0)
    assert mqtt_client.subscribe.call_count == len(collector.subscribed_topics)


def test_on_connect_nonzero_rc_does_not_subscribe(collector, mqtt_client):
    collector._on_connect(mqtt_client, None, {}, 1)
    mqtt_client.subscribe.assert_not_called()


def test_disconnect_reconnects_unexpected(collector, mqtt_client):
    collector._on_disconnect(mqtt_client, None, 1)
    mqtt_client.reconnect.assert_called_once()


def test_disconnect_clean_does_not_reconnect(collector, mqtt_client):
    collector._on_disconnect(mqtt_client, None, 0)
    mqtt_client.reconnect.assert_not_called()


def test_disconnect_reconnect_error_is_handled(collector, mqtt_client):
    mqtt_client.reconnect.side_effect = OSError("down")
    collector._on_disconnect(mqtt_client, None, 1)
    mqtt_client.reconnect.assert_called_once()


def test_influx_write_success_path(collector):
    reading = collector.parse_message("shellies/shelly1-bedroom/relay/0", "on")
    with patch("collector.mqtt_collector.writer.write_state") as write_state:
        collector._write_or_buffer(reading)
    write_state.assert_called_once()


def test_influx_write_failure_buffers(collector):
    reading = collector.parse_message("shellies/shelly1-bedroom/relay/0", "on")
    with patch("collector.mqtt_collector.writer.write_state", side_effect=RuntimeError("down")):
        collector._write_or_buffer(reading)
    assert collector.buffered_count == 1


def test_buffer_drain_on_reconnect(collector, mqtt_client):
    collector._append_buffer(collector.parse_message("shellies/shelly1-bedroom/relay/0", "on"))
    with patch("collector.mqtt_collector.writer.write_state") as write_state:
        collector._on_connect(mqtt_client, None, {}, 0)
    assert write_state.called
    assert collector.buffered_count == 0


def test_buffer_overflow_drops_oldest(collector):
    for value in [1, 2, 3, 4]:
        collector._append_buffer({"device": {"id": str(value)}, "state": {"is_on": True}, "source": "mqtt"})
    assert collector.buffered_count == 3
    assert collector._buffer[0]["device"]["id"] == "2"


def test_home_assistant_discovery_conditional(config, mqtt_client):
    config["home_assistant"]["enabled"] = True
    LightingMQTTCollector(config).start()
    assert mqtt_client.publish.call_count == 2


def test_home_assistant_discovery_disabled_by_default(collector, mqtt_client):
    collector.start()
    mqtt_client.publish.assert_not_called()


def test_home_assistant_mirror_state(config, mqtt_client):
    config["home_assistant"]["enabled"] = True
    collector = LightingMQTTCollector(config)
    reading = collector.parse_message("shellies/shelly1-bedroom/relay/0", "on")
    collector._mirror_home_assistant_state(reading)
    mqtt_client.publish.assert_called_with("homelab/lighting/bedroom_lamp/state", "ON")


@pytest.mark.parametrize(
    ("func", "args"),
    [
        (writer.write_state, (None, "", "room", "type", "gen1", "mqtt", {"is_on": True})),
        (writer.write_state, (None, "id", "room", "type", "bad", "mqtt", {"is_on": True})),
        (writer.write_event, (None, "id", "room", "bad", "api")),
        (writer.write_event, (None, "id", "room", "on", "api", 101)),
        (writer.write_energy, (None, "id", "room", -1, 0, 0)),
        (writer.write_energy, (None, "id", "room", 1, -1, 0)),
        (writer.write_energy, (None, "id", "room", 1, 0, -1)),
    ],
)
def test_writer_validation(func, args):
    with pytest.raises(ValueError):
        func(*args)


def test_writer_omits_none_fields():
    with patch("collector.writer.influx.write_point") as write_point:
        writer.write_state(None, "id", "room", "type", "gen1", "mqtt", {"is_on": True, "power_w": None})
    assert write_point.call_args.kwargs["fields"] == {"is_on": True}


def response(data):
    item = MagicMock()
    item.json.return_value = data
    item.raise_for_status.return_value = None
    return item


def test_http_collector_gen1_poll(config):
    http = LightingHTTPCollector(config)
    with patch("collector.http_collector.requests.get", side_effect=[
        response({"ison": True}),
        response({"emeters": [{"power": 12, "total": 99}], "wifi_sta": {"rssi": -50}}),
    ]):
        state = http.poll_device(config["devices"][1])
    assert state["is_on"] is True
    assert state["rssi"] == -50


def test_http_collector_gen2_poll(config):
    http = LightingHTTPCollector(config)
    with patch("collector.http_collector.requests.post", return_value=response({"output": True, "apower": 30, "aenergy": {"total": 400}, "temperature": {"tC": 42}})):
        state = http.poll_device(config["devices"][0])
    assert state["power_w"] == 30.0
    assert state["temperature_c"] == 42.0


def test_http_timeout_raises_after_three_retries(config):
    http = LightingHTTPCollector(config)
    with patch("collector.http_collector.requests.post", side_effect=requests.Timeout), patch("collector.http_collector.time.sleep") as sleep:
        with pytest.raises(DeviceUnreachable):
            http.poll_device(config["devices"][0])
    assert sleep.call_count == 2


def test_http_unreachable_caught_in_poll_once(config):
    http = LightingHTTPCollector(config)
    with patch.object(http, "poll_device", side_effect=[DeviceUnreachable("a"), {"is_on": True}]), patch("collector.http_collector.writer.write_state"):
        states = http.poll_once()
    assert states == {"bedroom_lamp": {"is_on": True}}


def test_exponential_backoff_between_retries(config):
    http = LightingHTTPCollector(config)
    with patch("collector.http_collector.requests.post", side_effect=requests.Timeout), patch("collector.http_collector.time.sleep") as sleep:
        with pytest.raises(DeviceUnreachable):
            http.poll_device(config["devices"][0])
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


def test_http_poll_once_writes_source_http(config):
    http = LightingHTTPCollector(config)
    with patch.object(http, "poll_device", return_value={"is_on": True}), patch("collector.http_collector.writer.write_state") as write_state:
        http.poll_once()
    assert write_state.call_args.args[5] == "http"


def test_sigterm_graceful_shutdown(collector):
    with patch("collector.mqtt_collector.signal.signal") as signal_fn, patch.object(collector, "start"), patch.object(collector, "stop") as stop:
        callbacks = {}
        signal_fn.side_effect = lambda sig, cb: callbacks.setdefault(sig, cb)
        def wait_once(timeout):
            callbacks[signal.SIGTERM](signal.SIGTERM, None)
            return True
        with patch("threading.Event.wait", side_effect=wait_once):
            run_until_stopped(collector)
    stop.assert_called_once()


def test_sigint_graceful_shutdown(collector):
    with patch("collector.mqtt_collector.signal.signal") as signal_fn, patch.object(collector, "start"), patch.object(collector, "stop") as stop:
        callbacks = {}
        signal_fn.side_effect = lambda sig, cb: callbacks.setdefault(sig, cb)
        def wait_once(timeout):
            callbacks[signal.SIGINT](signal.SIGINT, None)
            return True
        with patch("threading.Event.wait", side_effect=wait_once):
            run_until_stopped(collector)
    stop.assert_called_once()


def test_invalid_config_raises():
    with pytest.raises(ConfigError):
        LightingMQTTCollector({"devices": [{"id": "x"}]})
