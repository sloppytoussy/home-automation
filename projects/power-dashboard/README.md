# Power Dashboard

Monitors real-time power balance in kWh — grid import/export, load consumption, and net energy flow.

## Data Sources
- Modbus TCP energy meter (configurable IP/port)
- MQTT topics for smart plugs/sub-meters

## Metrics Collected
- Grid import / export (kWh)
- Current load (W)
- Daily energy balance
- Peak demand

## Config
Set in `.env` at the repo root:
```
POWER_METER_IP=192.168.1.x
POWER_METER_PORT=502
```
