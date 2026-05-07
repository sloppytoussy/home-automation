# Lighting Control InfluxDB Schema

## `lighting_state`

Written on every state change from MQTT, HTTP polling, or dashboard commands.

Tags: `device_id`, `room`, `device_type`, `generation`, `source`

Fields: `is_on`, `brightness_pct`, `power_w`, `energy_wh`, `temperature_c`, `rssi`

Time: nanosecond precision.

## `lighting_events`

Discrete on/off/dim/scene/presence/schedule events.

Tags: `device_id`, `room`, `event_type`

Fields: `triggered_by`, `brightness_pct`

Time: nanosecond precision.

## `lighting_energy`

Energy samples for power-meter-capable devices only.

Tags: `device_id`, `room`

Fields: `power_w`, `wh_delta`, `wh_total`

Time: nanosecond precision.

## Null Handling

Unknown or unsupported fields are omitted from writes. Collectors must never
write `None` field values and must not coerce missing telemetry to `0`.

## Retention

Keep raw `lighting_state`, `lighting_events`, and `lighting_energy` data for 30
days. Keep daily aggregate tasks indefinitely for long-term room and device
usage trends.

## Tag Cardinality

`device_id` is the stable platform identifier and is used instead of
`shelly_id`, which may change when hardware is replaced or re-flashed. Room,
device type, generation, source, and event type have bounded value sets, keeping
series cardinality predictable for a home deployment.
