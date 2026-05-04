# Water Monitor

Tracks water levels across underground storage tanks and raises alerts on low/high thresholds.

## Data Sources
- Ultrasonic level sensors via MQTT
- Float switch fallback sensors

## Metrics Collected
- Tank level (%, liters)
- Fill/drain rate (L/hr)
- Estimated days remaining at current usage
- Pump run-time

## Config
```
WATER_SENSOR_MQTT_TOPIC=home/water/tanks
TANK_CAPACITY_LITERS=5000
```
