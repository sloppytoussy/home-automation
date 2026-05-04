# Solar & Battery Dashboard

Live view of solar PV production, battery State of Charge (SoC), and energy flow between panels, batteries, and loads.

## Data Sources
- Solar inverter (Modbus TCP / RS485)
- BMS (Battery Management System) via MQTT or serial

## Metrics Collected
- Solar production (W, kWh/day)
- Battery SoC (%)
- Battery charge/discharge rate (W)
- Estimated time to full / time to empty
- Daily yield vs consumption

## Config
```
INVERTER_IP=192.168.1.x
INVERTER_PORT=8899
BATTERY_CAPACITY_KWH=10
```
