# Solar Battery InfluxDB Schema

Phase 1 defines the query contract for data that the Victron Cerbo GX
collector will write in Phase 2. The dashboard treats missing fields as
unknown values and renders placeholders instead of zeroes.

## Primary Measurement: `solar_readings`

Tags:

| Tag | Value | Rationale |
|---|---|---|
| `device` | `cerbo` | Low-cardinality hardware class for dashboard filtering. |
| `portal_id` | Cerbo GX VRM portal ID | One stable identifier per installation; useful when replacing hostnames or IPs. |
| `source` | `victron_cerbo` | Low-cardinality source discriminator for future collector variants. |

Fields:

| Field | Type | Description |
|---|---:|---|
| `pv_power_w` | float | Total PV output watts. |
| `pv_yield_today_kwh` | float | Cumulative kWh since midnight. |
| `battery_soc_pct` | float | Battery state of charge, 0-100. |
| `battery_power_w` | float | Positive means charging, negative means discharging. |
| `battery_voltage_v` | float | Battery voltage from the BMS. |
| `battery_current_a` | float | Battery current from the BMS. |
| `grid_power_w` | float | Positive means grid import, negative means grid export. |
| `ac_load_w` | float | Total AC consumption. |
| `inverter_output_w` | float | VE.Bus AC output. |
| `mppt_state` | int | `0=off`, `2=fault`, `3=bulk`, `4=absorption`, `5=float`. |

Time precision: nanosecond precision, using the InfluxDB line protocol
timestamp supplied by the collector.

## Secondary Measurement: `energy_totals`

`energy_totals` is shared with the power dashboard and is not redefined here.
Phase 2 will write `solar_export_kwh` as a float for power-dashboard net
consumption calculations.

## Null Handling

The collector should omit fields that are not present in a Cerbo payload rather
than writing zero. The dashboard converts absent fields to JSON `null` and
shows `—` in the UI. This matters for the third-party LifePO4 battery because
the integrated BMS exposes pack-level SOC, voltage, current, and power only;
cell-level telemetry is not expected.

When no `solar_readings` records exist, `/api/solar/summary` returns HTTP 200
with `data_available: false` and all numeric fields set to `null`. History
endpoints return empty arrays.

## Retention

Recommended retention:

- Raw `solar_readings`: 90 days at 5-minute collection cadence.
- Daily `energy_totals`: 5 years.

This keeps high-resolution operational data local and bounded while preserving
long-term production, import, export, and battery-health trends.

## Tag Cardinality

All tags are deliberately low-cardinality. `device`, `source`, and
`portal_id` should have one value per Cerbo installation. Do not tag dynamic
values such as firmware versions, IP addresses, MQTT topics, MPPT states, or
metric names; those belong in fields or configuration.
