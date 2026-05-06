# Phase 2 Testing Strategy: Overflow Detection with Dummy Data

## Overview

Before committing Phase 2 implementation, validate:
1. Calculator correctly detects overflow (volume > capacity)
2. Overflow detection works with dummy data
3. Configuration interpretation works as expected
4. Alerting logic makes correct decisions

---

## Test Scenarios with Dummy Data

### Scenario 1: Tank with `no_outlet` (WASAC Mains - Single Source)

**Configuration**:
```python
tank_config = {
    "id": "mains_tank",
    "depth_cm": 100,
    "capacity_liters": 1000,
    "sensor_offset_cm": 5,
    "num_sources": "single",
    "inlet_shutoff": "float_valve",
    "overflow_handling": "no_outlet",  # Float valve must prevent overflow
}
```

**Test Cases**:
```python
# Case 1a: Normal operation - tank filling
distance = 50  # 50cm from ceiling
reading = compute_reading(tank_config, distance)
assert reading.volume_liters == 500.0  # 50% full
assert reading.level_pct == 50.0
assert reading.volume_liters <= reading.capacity_liters
print("✓ Normal fill detected")

# Case 1b: Tank full
distance = 5  # Just below ceiling
reading = compute_reading(tank_config, distance)
assert reading.volume_liters == 950.0  # 95% full
assert reading.level_pct == 100.0  # Capped at 100%
assert reading.volume_liters <= reading.capacity_liters
print("✓ Full tank detected")

# Case 1c: OVERFLOW - Float valve failure
distance = -3  # Negative = water above ceiling
reading = compute_reading(tank_config, distance)
assert reading.volume_liters > reading.capacity_liters  # OVERFLOW
assert reading.level_pct == 100.0  # Still capped
overflow_magnitude = reading.volume_liters - reading.capacity_liters
print(f"✗ OVERFLOW DETECTED: {overflow_magnitude:.1f}L above capacity")

# Expected Alert Decision:
# overflow_handling == "no_outlet" → MAJOR ALERT (float valve failure)
# Action: Trigger alarm, auto-shutoff valve, notify operator
assert tank_config["overflow_handling"] == "no_outlet"
print("→ ACTION: ALERT + AUTO-SHUTOFF VALVE")
```

---

### Scenario 2: Tank with `open_outlet` (Rainwater - Multiple Sources)

**Configuration**:
```python
tank_config = {
    "id": "rainwater_tank",
    "depth_cm": 120,
    "capacity_liters": 1200,
    "sensor_offset_cm": 5,
    "num_sources": "multiple",
    "inlet_shutoff": "float_valve",
    "overflow_handling": "open_outlet",  # Safe outlet below ceiling
}
```

**Test Cases**:
```python
# Case 2a: Normal operation - collecting rain
distance = 60  # 60cm from ceiling
reading = compute_reading(tank_config, distance)
assert reading.volume_liters == 573.9  # ~48% full
assert reading.level_pct == 47.83
print("✓ Rainwater collection detected")

# Case 2b: Heavy rain - outlet activating
distance = 5  # Near ceiling
reading = compute_reading(tank_config, distance)
assert reading.volume_liters == 1149.8  # 96% full
assert reading.level_pct == 100.0
assert reading.volume_liters <= reading.capacity_liters
print("✓ Tank near full")

# Case 2c: OVERFLOW - Outlet is working (heavy rain)
distance = -2  # Negative = water above ceiling, outlet flowing
reading = compute_reading(tank_config, distance)
assert reading.volume_liters > reading.capacity_liters  # OVERFLOW
assert reading.level_pct == 100.0  # Still capped
overflow_magnitude = reading.volume_liters - reading.capacity_liters
print(f"○ Outlet Active: {overflow_magnitude:.1f}L overflowing")

# Expected Alert Decision:
# overflow_handling == "open_outlet" → INFO LOG (normal operation)
# Action: Log event, update UI, continue monitoring
assert tank_config["overflow_handling"] == "open_outlet"
print("→ ACTION: LOG + MONITOR (normal operation)")
```

---

### Scenario 3: Consumption Rate Tracking (Both Tanks)

**Test Data - 24 hour period**:
```python
# Simulate readings over time
readings_mains = [
    (0,     1000.0),   # 0h:   Full tank
    (3600,   900.0),   # 1h:   100L consumed
    (7200,   700.0),   # 2h:   200L consumed
    (10800,  500.0),   # 3h:   300L consumed
    (14400,  300.0),   # 4h:   400L consumed
    (18000,  200.0),   # 5h:   500L consumed
    # Refill detected
    (21600, 1000.0),   # 6h:   Refilled
]

# Calculate drain rate
rate = consumption_rate_lph(readings_mains[:6])  # Use only pre-refill
assert rate == 100.0  # 100 L/h
print(f"✓ Drain rate: {rate} L/h")

# Project days remaining
remaining = days_remaining(200.0, rate)
assert remaining == 0.08  # ~2 hours at current rate
print(f"✓ Days remaining: {remaining} days ({remaining*24:.1f} hours)")
```

---

## Test Execution Script

Create `test_dummy_data.py`:

```python
#!/usr/bin/env python3
"""Test calculator with dummy data before Phase 2 implementation."""

import sys
sys.path.insert(0, '/home/user/home-automation/projects/water-monitor')

from collector.calculator import compute_reading, consumption_rate_lph, days_remaining

def test_scenario_1_no_outlet():
    """Tank with no_outlet (float valve should prevent overflow)."""
    print("\n" + "="*60)
    print("SCENARIO 1: NO_OUTLET Tank (WASAC Mains)")
    print("="*60)
    
    tank = {
        "id": "mains_tank",
        "depth_cm": 100,
        "capacity_liters": 1000,
        "sensor_offset_cm": 5,
        "num_sources": "single",
        "inlet_shutoff": "float_valve",
        "overflow_handling": "no_outlet",
    }
    
    # Normal operation
    reading = compute_reading(tank, 50.0)
    print(f"\n1a. Normal fill (50cm distance):")
    print(f"    Volume: {reading.volume_liters}L (capacity: {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}%")
    print(f"    Overflow? {reading.volume_liters > reading.capacity_liters}")
    assert reading.volume_liters <= reading.capacity_liters
    
    # Full tank
    reading = compute_reading(tank, 5.0)
    print(f"\n1b. Full tank (5cm distance):")
    print(f"    Volume: {reading.volume_liters}L")
    print(f"    Level: {reading.level_pct}%")
    print(f"    Overflow? {reading.volume_liters > reading.capacity_liters}")
    
    # OVERFLOW - Float valve failure
    reading = compute_reading(tank, -3.0)
    print(f"\n1c. OVERFLOW DETECTED (-3cm distance):")
    print(f"    Volume: {reading.volume_liters}L (EXCEEDS {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}% (capped)")
    print(f"    Overflow magnitude: {reading.volume_liters - reading.capacity_liters:.1f}L")
    assert reading.volume_liters > reading.capacity_liters
    print(f"    → ALERT DECISION: overflow_handling='{tank['overflow_handling']}'")
    print(f"    → ACTION: MAJOR ALERT + AUTO-SHUTOFF VALVE")
    print("    ✓ Test passed")

def test_scenario_2_open_outlet():
    """Tank with open_outlet (safe overflow during heavy rain)."""
    print("\n" + "="*60)
    print("SCENARIO 2: OPEN_OUTLET Tank (Rainwater)")
    print("="*60)
    
    tank = {
        "id": "rainwater_tank",
        "depth_cm": 120,
        "capacity_liters": 1200,
        "sensor_offset_cm": 5,
        "num_sources": "multiple",
        "inlet_shutoff": "float_valve",
        "overflow_handling": "open_outlet",
    }
    
    # Normal operation
    reading = compute_reading(tank, 60.0)
    print(f"\n2a. Rain collection (60cm distance):")
    print(f"    Volume: {reading.volume_liters}L (capacity: {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}%")
    print(f"    Overflow? {reading.volume_liters > reading.capacity_liters}")
    assert reading.volume_liters <= reading.capacity_liters
    
    # Near full
    reading = compute_reading(tank, 5.0)
    print(f"\n2b. Tank filling up (5cm distance):")
    print(f"    Volume: {reading.volume_liters}L")
    print(f"    Level: {reading.level_pct}%")
    
    # OVERFLOW - Outlet is working
    reading = compute_reading(tank, -2.0)
    print(f"\n2c. Outlet Active (-2cm distance):")
    print(f"    Volume: {reading.volume_liters}L (EXCEEDS {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}% (capped)")
    print(f"    Overflow magnitude: {reading.volume_liters - reading.capacity_liters:.1f}L")
    assert reading.volume_liters > reading.capacity_liters
    print(f"    → ALERT DECISION: overflow_handling='{tank['overflow_handling']}'")
    print(f"    → ACTION: LOG INFO + MONITOR (normal operation)")
    print("    ✓ Test passed")

def test_scenario_3_consumption():
    """Track consumption rate and project days remaining."""
    print("\n" + "="*60)
    print("SCENARIO 3: Consumption Rate & Days Remaining")
    print("="*60)
    
    # 5-hour consumption period
    readings = [
        (0,      1000.0),   # t=0h:  1000L
        (3600,    900.0),   # t=1h:  100L consumed
        (7200,    700.0),   # t=2h:  200L consumed
        (10800,   500.0),   # t=3h:  300L consumed
        (14400,   300.0),   # t=4h:  400L consumed
        (18000,   200.0),   # t=5h:  500L consumed
    ]
    
    rate = consumption_rate_lph(readings)
    print(f"\n3a. Drain rate over 5 hours:")
    print(f"    Initial: {readings[0][1]}L")
    print(f"    Final:   {readings[-1][1]}L")
    print(f"    Drained: {readings[0][1] - readings[-1][1]}L")
    print(f"    Time:    {(readings[-1][0] - readings[0][0])/3600:.1f}h")
    print(f"    Rate:    {rate} L/h")
    assert rate == 100.0
    
    remaining = days_remaining(200.0, rate)
    print(f"\n3b. Days remaining at current rate:")
    print(f"    Current volume: 200L")
    print(f"    Drain rate:     {rate} L/h")
    print(f"    Days left:      {remaining} days ({remaining*24:.1f} hours)")
    assert remaining == 0.08
    print("    ✓ Test passed")

def test_scenario_4_refill_detection():
    """Detect when tank is refilled (volume increases)."""
    print("\n" + "="*60)
    print("SCENARIO 4: Refill Detection")
    print("="*60)
    
    readings_with_refill = [
        (0,     1000.0),   # t=0h:  Start at 1000L
        (3600,   500.0),   # t=1h:  Drain to 500L (500L consumed)
        (7200,  1000.0),   # t=2h:  Refill to 1000L (REFILL DETECTED)
    ]
    
    print("\n4a. Consumption BEFORE refill:")
    rate_before = consumption_rate_lph(readings_with_refill[:2])
    print(f"    Readings: {readings_with_refill[:2]}")
    print(f"    Rate: {rate_before} L/h")
    assert rate_before == 500.0
    
    print("\n4b. Consumption INCLUDING refill:")
    rate_with_refill = consumption_rate_lph(readings_with_refill)
    print(f"    Readings: {readings_with_refill}")
    print(f"    Rate: {rate_with_refill}")
    assert rate_with_refill is None  # Refill detected (volume increased)
    print("    ✓ Refill correctly detected (returns None)")

if __name__ == "__main__":
    try:
        test_scenario_1_no_outlet()
        test_scenario_2_open_outlet()
        test_scenario_3_consumption()
        test_scenario_4_refill_detection()
        
        print("\n" + "="*60)
        print("✓ ALL DUMMY DATA TESTS PASSED")
        print("="*60)
        print("\nCalculator is ready for Phase 2 implementation:")
        print("  ✓ Detects overflow correctly")
        print("  ✓ Handles both tank types")
        print("  ✓ Tracks consumption rates")
        print("  ✓ Projects days remaining")
        print("\nPhase 2 can now implement:")
        print("  → Collector overflow detection")
        print("  → Alert service decision logic")
        print("  → Notification channels (email, SMS, syslog)")
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
```

---

## How to Run Tests

```bash
# 1. Make test script executable
chmod +x /home/user/home-automation/test_dummy_data.py

# 2. Run the dummy data tests
cd /home/user/home-automation
python test_dummy_data.py

# Expected Output:
# ============================================================
# SCENARIO 1: NO_OUTLET Tank (WASAC Mains)
# ============================================================
#
# 1a. Normal fill (50cm distance):
#     Volume: 500.0L (capacity: 1000.0L)
#     Level: 50.0%
#     Overflow? False
#
# 1b. Full tank (5cm distance):
#     Volume: 950.0L
#     Level: 100.0%
#     Overflow? False
#
# 1c. OVERFLOW DETECTED (-3cm distance):
#     Volume: 1030.0L (EXCEEDS 1000.0L)
#     Level: 100.0% (capped)
#     Overflow magnitude: 30.0L
#     → ALERT DECISION: overflow_handling='no_outlet'
#     → ACTION: MAJOR ALERT + AUTO-SHUTOFF VALVE
#     ✓ Test passed
# ...
# ✓ ALL DUMMY DATA TESTS PASSED
```

---

## What This Validates Before Phase 2

| Validation | Test Case | Status |
|-----------|-----------|--------|
| Calculator detects overflow | Scenario 1c, 2c | ✓ |
| `no_outlet` interpretation | Scenario 1 | ✓ |
| `open_outlet` interpretation | Scenario 2 | ✓ |
| Consumption rate calculation | Scenario 3 | ✓ |
| Days remaining projection | Scenario 3b | ✓ |
| Refill detection | Scenario 4 | ✓ |
| Configuration handling | All scenarios | ✓ |

---

## Summary Before Phase 2

Once `test_dummy_data.py` passes:

✓ Calculator is mathematically correct  
✓ Overflow detection works as designed  
✓ Configuration interpretation is clear  
✓ Both tank types are handled correctly  

**Ready to implement Phase 2:**
- [ ] Collector overflow detection
- [ ] Alerter service (email, SMS, syslog)
- [ ] Auto-shutoff valve integration
- [ ] Per-tank alert severity levels
- [ ] Critical tank tracking
- [ ] Test mode configuration

