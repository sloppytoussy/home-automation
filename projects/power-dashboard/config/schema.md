# Power Dashboard InfluxDB Schema

This schema keeps manual utility-meter verification separate from automated
circuit collection. Manual Landis+Gyr readings remain authoritative.

## `power_readings`

Per-poll automated readings from Shelly Pro 3EM and IotaWatt.

Tags:
- `device_id`: configured local device identifier
- `device_type`: `shelly_pro_3em` or `iotawatt`
- `circuit`: stable configured circuit name
- `phase`: configured phase such as `L1`, `L2`, `L3`, or `none`
- `source`: `mqtt` or `rest`

Fields:
- `watts`: instantaneous real power
- `watt_hours`: cumulative energy where supplied by the device
- `volts`: voltage where supplied by the device
- `amps`: current where supplied by the device
- `power_factor`: power factor where supplied by the device

Cardinality note: `circuit` and `device_id` must come from YAML config, not raw
IotaWatt sensor names discovered at runtime. This bounds tag cardinality to the
installed hardware map.

## `energy_totals`

Daily rollups for dashboard summaries and projections.

Tags:
- `source`: `automated`, `manual`, or future `solar`

Fields:
- `consumed_kwh`: gross imported/consumed energy for the day
- `solar_export_kwh`: exported solar energy, defaults to `0.0` until Victron is implemented
- `net_kwh`: `consumed_kwh - solar_export_kwh`

## `verification_log`

Manual versus automated comparison for Landis+Gyr verification.

Tags:
- `meter_model`: expected `Landis+Gyr JH145`
- `source`: `manual_vs_automated`

Fields:
- `manual_kwh`: authoritative utility meter delta
- `automated_kwh`: automated collector delta
- `delta_kwh`: `automated_kwh - manual_kwh`
- `delta_pct`: percentage delta relative to manual usage
- `flagged`: boolean represented by the InfluxDB client as a boolean field

## `solar_readings`

Reserved for the future Victron Cerbo GX session. Not populated by this task.

Tags:
- `device_id`: Cerbo portal ID when available
- `source`: `victron_cerbo_gx`

Fields:
- `solar_generation_w`: instantaneous PV generation
- `battery_soc_pct`: battery state of charge
- `battery_power_w`: signed battery power
- `grid_power_w`: signed grid import/export power
- `solar_export_kwh`: exported solar energy for later rollups
