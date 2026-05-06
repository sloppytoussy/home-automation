# Coding standards

Applies to all Python code in this repository.

---

## Python

### Imports
```python
from __future__ import annotations   # always first — required for Python 3.9
import os
import logging
from pathlib import Path
from dataclasses import dataclass
# stdlib before third-party before local
```

### Type hints
Use built-in generics (`list[str]`, `dict[str, int]`, `tuple[int, ...]`)
not `typing.List`, `typing.Dict` etc. The `from __future__ import annotations`
import makes these safe on Python 3.9.

### Logging
```python
# Always — never print()
from shared.utils import get_logger
log = get_logger(__name__)

log.info("Collector started", extra={"broker": host, "port": port})
log.warning("Buffer overflow — dropping oldest reading")
log.error("InfluxDB write failed", exc_info=True)
```

### Environment variables
```python
# Safe — always use getenv with fallback
host = os.getenv("INFLUXDB_URL", "http://localhost:8086")
bucket = os.getenv("INFLUXDB_BUCKET", "")

# Never — crashes when var is unset
host = os.environ["INFLUXDB_URL"]
```

### Exception handling
```python
# Correct — specific exception, logged with context
try:
    client.write(record)
except InfluxDBError as exc:
    log.error("InfluxDB write failed: %s", exc)
    self._buffer.append(record)

# Never — bare except
try:
    client.write(record)
except:
    pass
```

### Exponential backoff (network-dependent services)
```python
import time

BASE_DELAY = 2      # seconds
MAX_DELAY  = 60     # seconds
MAX_TRIES  = 5

for attempt in range(MAX_TRIES):
    try:
        connect()
        break
    except ConnectionError as exc:
        delay = min(BASE_DELAY * 2 ** attempt, MAX_DELAY)
        log.warning("Connect failed (attempt %d/%d), retry in %ds: %s",
                    attempt + 1, MAX_TRIES, delay, exc)
        time.sleep(delay)
else:
    log.error("Max retries reached — giving up")
```

### MQTT collector threading pattern
Follow `projects/water-monitor/collector/mqtt_collector.py` exactly:
- `threading.Event` for shutdown signalling
- `signal.signal(signal.SIGTERM, ...)` and `SIGINT` handlers
- `client.loop_start()` / `client.loop_stop()` — never `loop_forever()`
- Reconnect logic in `on_disconnect` callback

### InfluxDB writes
Always use `shared/db/influx.py`. Never instantiate `InfluxDBClient`
directly in project code.

```python
from shared.db.influx import write_point

write_point(
    measurement="power_readings",
    tags={"circuit": "mains_L1", "phase": "L1"},
    fields={"watts": 2415.3, "volts": 231.4},
)
```

### Config loading
```python
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "power_collector.yaml"

def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)
```

---

## Flask

### Route guards
Every route that touches InfluxDB must handle unavailability:

```python
@app.route("/api/summary")
def api_summary():
    try:
        data = query_safe(FLUX)
    except Exception as exc:
        log.error("InfluxDB unavailable: %s", exc)
        return jsonify({"error": "InfluxDB unavailable"}), 503
    return jsonify(data)
```

### Template JSX
Jinja templates that contain JSX `style={{ }}` syntax must wrap JSX
blocks in `{% raw %}...{% endraw %}` to prevent Jinja parse errors.

### Manual entry routes
The `/entry` and `/appliances` routes in `dashboard/app.py` must never
be modified unless the task explicitly targets them. They are the
authoritative verification layer.

---

## Testing

### File structure
```
projects/<project>/tests/
  __init__.py
  test_app.py          Flask route tests (Flask test client)
  test_collector.py    Collector unit tests (mock hardware + network)
  test_calculator.py   Pure logic tests (no mocking needed)
  test_writer.py       InfluxDB writer tests
```

### Mock targets by project

**Power dashboard**
```python
from unittest.mock import MagicMock, patch

@patch("paho.mqtt.client.Client")
@patch("shared.db.influx.write_point")
def test_shelly_payload_parse(mock_write, mock_mqtt):
    ...
```

**Water monitor (reference)**
See `projects/water-monitor/tests/test_alerter.py` for the canonical
mock pattern used throughout the project.

### Test naming
```python
def test_<function>_<scenario>_<expected_outcome>():
    # Examples:
    def test_calculate_tiered_cost_spanning_two_tiers_returns_correct_breakdown():
    def test_mqtt_collector_on_InfluxDB_failure_buffers_reading():
    def test_detect_variance_above_threshold_sets_flagged_true():
```

### Minimum test counts
| Project | Minimum | Reference |
|---|---|---|
| water-monitor | 124 (current) | Baseline — do not regress |
| power-dashboard | 105 | Target for current session |
| solar-battery | 60 | Target for solar session |
| dns-monitor | skip | Pre-existing fixture failure |

---

## What not to do

| Pattern | Instead |
|---|---|
| `print(f"Connected to {host}")` | `log.info("Connected", extra={"host": host})` |
| `os.environ["INFLUXDB_TOKEN"]` | `os.getenv("INFLUXDB_TOKEN", "")` |
| `except Exception: pass` | `except SpecificError as exc: log.error(...)` |
| `subprocess.run(cmd, shell=True)` | `subprocess.run(["cmd", "arg1"])` |
| Hardcoded `"192.168.1.100"` in `.py` | Read from YAML config |
| `from influxdb_client import ...` in app code | `from shared.db.influx import write_point` |
